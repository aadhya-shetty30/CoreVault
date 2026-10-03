# CoreVault -- Phase 2

A multi-user cloud storage system built as a core-CS mini-project. Phase 1
delivered the core module: auth, folders, files, and one diagnostic
endpoint. Phase 2 (this phase) extends that same codebase, additively, with
OTP-based 2FA, chunked upload, content-addressed deduplication, file
versioning, a recycle bin, permission-based sharing, and quota enforcement
-- again with the underlying OS/DBMS concepts (mutexes, producer-consumer
queues, content-addressing, foreign keys/CHECK constraints) implemented
explicitly in application code rather than hidden behind a framework.

**Out of scope for Phase 2** (coming in Phase 3/4, do not expect them
here): a versioning-UI polish pass, an analytics dashboard, an admin panel,
AES encryption, an LRU cache, socket-based transfer, disk-scheduling
simulation, audit logging, search, and any scheduled/cron-style job --
including the recycle bin's automatic purge (see "Recycle bin" below:
`purge_at` is computed and stored now, but nothing acts on it yet).

## Cross-platform design

This project is built to run identically on Windows, macOS, and Linux:

| Concern | Library used | Why (vs. the Unix-only alternative) |
|---|---|---|
| File locking during upload | [`portalocker`](https://github.com/WoLpH/portalocker) | Same Python API compiles down to `flock()` on Linux/macOS and `msvcrt.locking()` on Windows. We never call `fcntl` directly. |
| Disk usage (`/system/disk-usage`) | `shutil.disk_usage()` (stdlib) | Works on all three OSes; `os.statvfs()` does not exist on Windows. |
| Postgres | Supabase (hosted) | No local Postgres/Docker install of any kind needed on any OS -- the app connects out over the network the same way everywhere. |

Later phases (scheduled jobs, backups) will continue this rule: no `cron`,
no shell/bash scripts invoked from Python -- `APScheduler` and the stdlib's
`tarfile`/`zipfile` modules instead.

## Architecture

```
CoreVault/
├── docker-compose.yml.unused  # no longer used -- Postgres lives on Supabase now; kept for reference
├── .env.example               # copy to .env; read by the backend only
├── backend/                   # FastAPI + SQLAlchemy (async) + Alembic
│   ├── app/
│   │   ├── main.py            # FastAPI app + CORS
│   │   ├── config.py          # pydantic-settings, reads repo-root .env
│   │   ├── database.py        # async engine/session
│   │   ├── models.py          # ORM models (users/folders/files + Phase 2 tables)
│   │   ├── schemas.py         # Pydantic request/response models
│   │   ├── security.py        # bcrypt hashing + JWT encode/decode
│   │   ├── otp.py              # Phase 2: pyotp helpers + pending-2FA token
│   │   ├── deps.py            # JWT auth dependency
│   │   ├── ownership.py       # "is this row mine" + Phase 2 permission-aware lookups
│   │   ├── permissions.py      # Phase 2: role resolution (owner/editor/viewer)
│   │   ├── storage.py         # on-disk path layout: per-file (Phase 1) + blob/staging/chunk (Phase 2)
│   │   ├── chunked_uploads.py  # Phase 2: filesystem-backed chunk-upload session bookkeeping
│   │   ├── workers.py          # Phase 2: producer-consumer pool, dedup+quota mutexes, finalize_upload
│   │   ├── blob_release.py     # Phase 2: blob ref-count release for folder hard-delete
│   │   └── routers/
│   │       ├── auth.py        # /auth/register,/login,/me + Phase 2 /auth/2fa/*
│   │       ├── folders.py     # /folders CRUD + breadcrumb + cycle check + Phase 2 role checks
│   │       ├── files.py       # /files upload(+chunked)/download/versions/permissions/share-link
│   │       ├── permissions.py  # Phase 2: DELETE /permissions/{id} (revoke)
│   │       ├── recycle_bin.py  # Phase 2: GET/restore for soft-deleted files
│   │       ├── shared.py       # Phase 2: public GET /shared/{token}(/info)
│   │       └── system.py      # /system/disk-usage
│   ├── alembic/                # 0001 (Phase 1 schema) + 0002 (Phase 2, additive)
│   ├── scripts/
│   │   ├── seed_and_demo.py       # Phase 1: register→login→folders→upload→download
│   │   ├── test_file_lock.py      # Phase 1: standalone portalocker concurrency demo
│   │   ├── test_concurrent_quota.py # Phase 2: N concurrent uploads, no lost quota updates
│   │   └── test_dedup.py           # Phase 2: same content twice -> 1 blob, ref_count=2
│   ├── storage/                 # uploaded files land here (gitignored)
│   └── requirements.txt
└── frontend/                   # React + Vite + Tailwind
    └── src/
        ├── api/client.js        # fetch wrapper, attaches JWT
        ├── api/upload.js         # Phase 2: single-shot vs. chunked upload dispatch + progress
        ├── context/              # AuthContext (in-memory JWT, now 2FA-aware), ToastContext
        ├── pages/                # Login, Register, FileBrowser, Phase 2: RecycleBin, SharedLink
        └── components/           # FolderTree, Breadcrumb, UploadZone,
                                    # Phase 2: TwoFactorSetupModal, FileVersionsModal, ShareModal
```

## Database schema

Phase 1's three tables are unchanged; Phase 2 (migration `0002_phase2.py`)
only ever **adds** columns/tables on top:

- **users**: `id, email, username, password_hash, storage_used_bytes, storage_quota_bytes, failed_login_attempts, locked_until, created_at` + Phase 2: `otp_secret, otp_enabled`
- **folders**: `id, owner_id (FK users), parent_folder_id (FK folders, nullable, self-referencing), name, created_at`
- **files**: `id, owner_id (FK users), folder_id (FK folders, nullable = root), filename, size_bytes, content_hash (sha256), storage_path, is_deleted, created_at, updated_at` + Phase 2: `deleted_at, purge_at, blob_id (FK blobs)` -- size_bytes/content_hash/storage_path now mirror the file's *current version*
- **blobs** *(Phase 2)*: `id, content_hash (unique), storage_path, size_bytes, ref_count` -- one row per unique SHA-256 on disk, shared by every file/version/user that happens to have identical content
- **file_versions** *(Phase 2)*: `id, file_id (FK files), version_number, content_hash, storage_path, size_bytes, modified_by (FK users), modified_at`
- **permissions** *(Phase 2)*: `id, file_id (FK files, nullable), folder_id (FK folders, nullable), user_id (FK users), role (owner/editor/viewer), granted_by, granted_at` -- CHECK constraint enforces exactly one of file_id/folder_id
- **shared_links** *(Phase 2)*: `id, file_id (FK files), token (unique), role (editor/viewer), expires_at, max_access_count, access_count, created_by, created_at`

## Prerequisites

- A free **[Supabase](https://supabase.com)** account — no Docker, no local
  Postgres install, on any OS.
- **Python 3.11**
- **Node.js 18+** (for Vite/React)

## 1. Create a Supabase project and point .env at it

1. At [supabase.com](https://supabase.com), create a new project (pick any
   name/region; note the database password you set — you'll need it below).
   Wait for it to finish provisioning (a minute or two).
2. In the project dashboard, click **Connect** and copy the URI under
   **Session pooler** (port `5432`).
   - **Not "Direct connection"**: that host (`db.<project-ref>.supabase.co`)
     is IPv6-only. On a network without IPv6, which includes many home
     broadband connections, it fails with "could not translate host name"
     even though the project is up.
   - **Not "Transaction pooler"** (port `6543`): that's meant for
     serverless/edge functions making brief one-off queries. This app is a
     long-running server holding persistent connections, which is what
     session mode is for.
3. Copy that URI, and from the repo root:

   ```bash
   cp .env.example .env
   ```

   Paste the URI into `.env` as `DATABASE_URL`, replacing `[YOUR-PASSWORD]`
   with the database password from step 1. It should look like this.
   The username is `postgres.<project-ref>`, and the host's region part
   matches your project's region:

   ```
   DATABASE_URL=postgresql://postgres.abcdefghijk:your-password-here@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres
   ```

   Leave `DATABASE_SSL=true` (the default) — Supabase requires SSL on every
   connection; `app/config.py` passes the right SSL connect args to
   asyncpg/psycopg2 automatically based on this flag.

That's the entire database setup — no service to start or keep running
locally; `alembic upgrade head` in the next step connects straight to it.

## 2. Backend setup

```bash
cd backend
python -m venv .venv
```

Activate the virtual environment (this is the one genuinely OS-specific step):

- **Linux / macOS**: `source .venv/bin/activate`
- **Windows (PowerShell)**: `.venv\Scripts\Activate.ps1`
  (if you get an execution-policy error: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first)
- **Windows (cmd.exe)**: `.venv\Scripts\activate.bat`

Then, the same on every OS:

```bash
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

A fresh Supabase project's database is empty, so `alembic upgrade head`
applies both migrations in order the first time you run it:
`0001_initial_schema.py` (Phase 1's users/folders/files tables) then
`0002_phase2.py` (Phase 2's additions) — Alembic tracks which have already
run in an `alembic_version` table it creates for you, so re-running this
command later is always safe/idempotent. `requirements.txt` also installs
`pyotp` (2FA).

The API is now at `http://127.0.0.1:8000` (interactive docs at `/docs`).
`STORAGE_ROOT` in `.env` (default `./storage`, i.e. `backend/storage/`) is
where uploaded files are written — relative to wherever you launched
`uvicorn` from, so run it from `backend/` as shown above. Phase 2 adds a
few subdirectories under it automatically (`blobs/`, `tmp/`,
`chunk_uploads/`) alongside Phase 1's per-user layout — all gitignored,
same as before.

## 3. Frontend setup

In a second terminal:

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

`npm install` now also pulls in `qrcode.react` (renders the 2FA setup QR
code client-side from the otpauth URI the backend returns).

Open `http://localhost:5173`. Register an account, log in, create nested
folders, and drag-and-drop a file to upload it.

## 4. Try the full flow via script (instead of, or in addition to, the UI)

With the backend running (step 2), in a fresh terminal:

```bash
cd backend
# activate the venv again, as in step 2, then:
python scripts/seed_and_demo.py
```

This registers a fresh test user, logs in, creates `Documents/2026/Reports`,
uploads a small file into it, downloads it back, and asserts the SHA-256
the server computed while streaming to disk matches what was uploaded and
what came back down. Expect output ending in `All good ...`.

## 5. Confirm the portalocker lock is real

This is a standalone demo, independent of the running API, that starts two
OS processes racing to write the same file at (as close as possible to)
the same instant:

```bash
cd backend
# activate the venv, then:
python scripts/test_file_lock.py
```

Expected output looks like:

```
[writer-A] requesting lock at t=...123
[writer-B] requesting lock at t=...124
[writer-A] ACQUIRED lock at t=...125  (waited 0.002s)
[writer-A] releasing lock at t=...128
[writer-B] ACQUIRED lock at t=...128  (waited 4.004s)
[writer-B] releasing lock at t=...131
```

The ~3-second gap between `writer-B`'s "requesting" and "ACQUIRED" lines is
the point: it proves `writer-B` genuinely blocked inside
`portalocker.Lock(...)` until `writer-A`'s lock was released, rather than
both processes writing to the file at once. The same call
(`portalocker.Lock(path, mode="wb")`) is what `POST /files/upload` uses in
`app/routers/files.py`, so this demonstrates the exact mechanism guarding
real uploads — flock() under the hood on Linux/macOS, `msvcrt.locking()` on
Windows, same code either way.

## 6. Try Phase 2's new features in the UI

With both servers running (steps 2-3):

- **2FA**: click "Enable 2FA" in the header, scan the QR code with any
  authenticator app (Google Authenticator, Authy, ...) or type the secret
  in manually, then enter the 6-digit code to confirm. Log out and back in
  — you'll now be asked for a code after your password.
- **Chunked upload with progress**: drag in a file larger than 5 MB (the
  default `SINGLE_SHOT_UPLOAD_MAX_BYTES`) — the UI automatically switches
  to the chunked flow and shows a live progress bar as each chunk is
  acknowledged. Smaller files still upload in one shot, instantly.
- **Versioning**: upload a file, then upload a *different* file under the
  exact same filename into the same folder — instead of a second file, you
  get a new version of the same one. Click "Versions" on it to see the
  history and restore an older one.
- **Recycle bin**: delete a file, then open "Recycle bin" from the header —
  it's still there with a day countdown, and can be restored.
- **Sharing**: click "Share" on a file to grant another registered user
  viewer/editor access by email or username, or generate a public link
  (optionally capped by expiry date and/or use count). Open the generated
  `/shared/<token>` URL in a private/incognito window — no login required.

## 6b. Phase 3: storage dashboard and stale-file prompt

Run `alembic upgrade head` once more. It applies three migrations:
`0003_phase3_analytics.py` adds two nullable columns to `files` (`last_accessed_at`,
`stale_prompt_snoozed_until`) and an index, `0004_file_activity.py`
adds the `file_activity` table, and `0005_admin_flag.py` adds
`users.is_admin`. As with 0002, nothing existing is altered.

- **Dashboard**: click "Dashboard" in the header. It shows quota usage,
  file count, space held by old versions and the recycle bin, bytes saved
  by deduplication, a donut chart of space by file type (Images, Videos,
  Audio, Documents, Archives, Code, Other -- by extension, see
  `app/routers/analytics.py`), and the 10 largest files with their folder
  paths.
- **Stale-file prompt**: a download (or a public share-link download)
  stamps `last_accessed_at`. Once per login, the file browser checks for
  files whose last access *and* last change are both older than
  `STALE_FILE_DAYS`, and pops up a list asking whether to delete them.
  "Delete selected" uses the normal `DELETE /files/{id}`, so files go to the
  recycle bin and can be restored. "Keep selected" silences the prompt for
  those files for a year. "Ask me later" closes it until the next login.
  The same review is available from the dashboard's "Unused files" card.
- **Trying it without waiting a year**: either set `STALE_FILE_DAYS=0` in
  `.env` and restart uvicorn, or backdate one file:

  ```bash
  cd backend
  python scripts/make_file_stale.py <username-or-email> <filename> [days]
  ```

  Then log out and back in.

- **Storage forecast** (dashboard): rebuilds your daily usage over the last
  `FORECAST_WINDOW_DAYS` (default 90) from version history, fits a
  least-squares line, and projects when you'll hit your quota. The history
  uses the same charging rule as uploads: a content hash counts the first
  time you own it, and duplicates are free. It is anchored to today's real
  `storage_used_bytes`, so the line always ends at the true number.
  Projections beyond 100 years are reported as "over 100 years". With fewer
  than 3 days of history it says so rather than extrapolating.
- **Per-file activity log** (migration `0004_file_activity.py`): every
  upload, new version, download, public-link download (logged as
  anonymous), version restore, delete, recycle-bin restore, share
  grant/revoke, link create/revoke, and "keep" answer adds a row to
  `file_activity`. The row is written in the same transaction as the change
  it describes, so a rolled-back action leaves no log line
  (`app/activity_log.py`). Click "Activity" on a file (owner only), or see
  the "Recent activity" card on the dashboard. History starts from when the
  migration is applied; earlier events aren't backfilled.

- **Admin storage overview** (migration `0005_admin_flag.py`): an **Admin**
  page, visible only to admins, listing every account's storage used, space
  left and forecast. Accounts are sorted by how soon they'll run out and
  labelled Critical (≥90% full or full within 30 days), Running low (≥75% or
  within 90 days) or OK. Clicking a user shows their forecast chart, and an
  **Email** button opens a pre-filled renewal message. Admins see storage
  numbers only: the `/admin` endpoints never return file names, counts or
  contents, and being an admin grants no access to anyone's files through
  any other route. To grant or revoke it (no API can):

  ```bash
  cd backend
  python scripts/make_admin.py <username-or-email>            # grant
  python scripts/make_admin.py <username-or-email> --revoke   # revoke
  python scripts/make_admin.py --list
  ```

  The user then logs out and back in to see the Admin page.

`last_accessed_at` is written with a Core UPDATE that pins `updated_at` to
its existing value (`app/file_activity.py`). Without that, `updated_at`'s
`onupdate=now()` would fire on every download, so "updated" would start
meaning "last downloaded".

## 7. Evidence scripts (REQ-7.1/7.2 and dedup correctness)

With the backend running (step 2), in a fresh terminal:

```bash
cd backend
# activate the venv, then:
python scripts/test_concurrent_quota.py
```

This fires 20 concurrent uploads (different content each) for one freshly
registered user from 20 threads at once, then asserts
`storage_used_bytes` on the server exactly equals the sum of their sizes —
proving the `threading.Lock` around that counter in `app/workers.py` has no
lost updates even though a bounded thread pool is processing all 20
finalize-upload jobs concurrently. Actual output from a run of this script:

```
1. Registering quota1789273980@example.com ...
2. Logging in ...
3. Preparing 20 distinct payloads (different content each, so dedup never kicks in) ...
4. Firing all 20 uploads at once from 20 threads ...
   All 20 requests completed in 0.58s
   All 20 uploads returned 201 Created
5. Checking the user's final storage_used_bytes ...
   expected total (sum of 20 unique payload sizes): 940 bytes
   actual storage_used_bytes on the server:          940 bytes

No lost updates: storage_used_bytes exactly matches the sum of all concurrent uploads' sizes.
This is REQ-7.1/7.2 evidence for the per-user threading.Lock around storage_used_bytes in app/workers.py.
```

Then:

```bash
python scripts/test_dedup.py
```

This uploads the same content twice under different filenames, connects
directly to the database, and asserts exactly one `blobs` row exists with
`ref_count == 2` and exactly one copy of the bytes is on disk — then
exercises the ref-count *decrement* side directly (there's no hard-delete
route in Phase 2 to trigger it through the API; see the script's docstring
and `app/workers.release_blob_ref`). Actual output from a run:

```
1. Registering dedup1789274022@example.com ...
2. Logging in ...
3. Uploading identical content as 'first.txt' (sha256=4a4c72a246ba...) ...
4. Uploading the SAME bytes again as 'second.txt' ...
5. Connecting directly to the database to inspect the blobs table ...
   blob row: id=5f70d496-7637-49f7-8f0a-c6647ece5709 ref_count=2 storage_path=.../storage/blobs/4a/4a4c72a246ba19d06ff28bd0913370b035c5d8849d0cd4e4163ac7dcc5ab51e2
   bytes on disk at .../blobs/4a/4a4c72a246ba19d06ff28bd0913370b035c5d8849d0cd4e4163ac7dcc5ab51e2: 55 bytes -- exactly one copy
   both files' file_versions rows point at the exact same on-disk path -- confirmed shared, not duplicated

6. Exercising the ref-count DECREMENT side (release_blob_ref) directly:
   (Phase 2 has no hard-delete route -- DELETE /files/{id} is a soft-delete into
    the recycle bin now -- so this calls the same function Phase 3's purge job will.)
   after releasing one reference: ref_count=1 (bytes still on disk: True)
   after releasing the second (last) reference: blob row exists=False, bytes on disk=False

All good -- one blob row, ref_count tracked correctly on the way up (upload) and down (release), one copy of the bytes on disk.
```

> Both transcripts above were captured in a sandboxed dev environment with
> no Docker available, running the same code against a SQLite stand-in
> instead of Postgres (`app/workers.py`'s sync engine and `app/database.py`'s
> async engine both just point at a different `DATABASE_URL` — nothing
> about the application logic changes). Re-run both scripts yourself
> against your own Postgres-backed instance per steps 1-2 above; the
> assertions are unconditional, so a passing run proves the same thing
> either way.

## API summary

| Method & path | Auth? | Purpose |
|---|---|---|
| `POST /auth/register` | no | Create an account |
| `POST /auth/login` | no | Get a JWT (locks account 15 min after 5 failed attempts) |
| `GET /auth/me` | yes | Current user's profile |
| `POST /folders` | yes | Create a folder (`parent_folder_id: null` = root) |
| `GET /folders/root` | yes | List root-level folders/files + breadcrumb |
| `GET /folders/{id}` | yes | List a folder's children + breadcrumb (viewer+) |
| `PATCH /folders/{id}` | yes | Rename (editor+) and/or move (owner only); rejects cycles |
| `DELETE /folders/{id}` | yes | Hard-delete a folder and everything inside it (owner only) |
| `POST /auth/2fa/setup` | yes | Generate an OTP secret + otpauth URI *(Phase 2)* |
| `POST /auth/2fa/verify-setup` | yes | Confirm the first code, flips `otp_enabled=true` *(Phase 2)* |
| `POST /auth/2fa/verify` | no | Exchange a pending token + OTP code for a real JWT *(Phase 2)* |
| `POST /files/upload` | yes | Small-file multipart upload; creates a new version if the filename already exists (editor+) |
| `POST /files/upload/init` | yes | Start a chunked upload, returns an `upload_id` *(Phase 2)* |
| `POST /files/upload/{id}/chunk/{i}` | yes | Upload one chunk *(Phase 2)* |
| `POST /files/upload/{id}/complete` | yes | Reassemble + finalize (dedup/quota/versioning) *(Phase 2)* |
| `GET /files/{id}` | yes | File metadata (viewer+) |
| `GET /files/{id}/download` | yes | Stream the current version back (viewer+) |
| `DELETE /files/{id}` | yes | Soft-delete into the recycle bin (owner only) *(changed in Phase 2)* |
| `GET /files/{id}/versions` | yes | List versions, newest first (viewer+) *(Phase 2)* |
| `POST /files/{id}/versions/{vid}/restore` | yes | Make an old version current (editor+) *(Phase 2)* |
| `GET`/`POST /files/{id}/permissions` | yes | List/grant editor or viewer access by email or username (owner only) *(Phase 2)* |
| `DELETE /permissions/{id}` | yes | Revoke a grant (owner only) *(Phase 2)* |
| `POST /files/{id}/share-link` | yes | Create a public link (role, optional expiry/use-limit) (owner only) *(Phase 2)* |
| `GET /shared/{token}(/info)` | no | Public info/download via a share link *(Phase 2)* |
| `GET /recycle-bin` | yes | List your own soft-deleted files + days remaining *(Phase 2)* |
| `POST /recycle-bin/{id}/restore` | yes | Restore a soft-deleted file *(Phase 2)* |
| `GET /system/disk-usage` | no | Raw `shutil.disk_usage()` on the storage volume |
| `GET /analytics/storage` | yes | Dashboard data: usage, per-file-type breakdown, largest files, version/recycle-bin/dedup totals *(Phase 3)* |
| `GET /analytics/stale-files` | yes | Your files not opened or changed in `STALE_FILE_DAYS` (default 365) *(Phase 3)* |
| `POST /analytics/stale-files/{id}/keep` | yes | Answer "keep" to the stale-file prompt; silenced for `STALE_PROMPT_SNOOZE_DAYS` *(Phase 3)* |
| `GET /analytics/forecast` | yes | Daily usage history + linear trend + projected date the quota fills *(Phase 3)* |
| `GET /analytics/activity` | yes | Recent activity across every file you own (`?limit=`, default 20) *(Phase 3)* |
| `GET /files/{id}/activity` | yes | Full activity log for one file (owner only) *(Phase 3)* |
| `GET /admin/users` | admin | Every user's storage used/left + forecast summary, no file data *(Phase 3)* |
| `GET /admin/users/{id}/forecast` | admin | One user's full forecast (daily usage curve) *(Phase 3)* |

## Deploying

The database stays on Supabase. The backend runs on **Render** (from
`render.yaml`) and the frontend on **Vercel** (from `frontend/vercel.json`).

Two constraints shape this:
- **Uploaded files live on the server's disk**, so the backend needs a
  *persistent* disk. That needs a paid Render instance; free ones wipe the
  disk on restart.
- **The backend must run as one process**, because the upload locks are
  in-memory. `render.yaml` already sets one instance with `--workers 1`.

1. **Backend (Render):** **New → Blueprint** → pick this repo. Render reads
   `render.yaml` and asks for two values:
   - `DATABASE_URL`: the Supabase **session pooler** URL.
   - `FRONTEND_URL`: enter `https://example.com` for now; it gets fixed in
     step 3.

   The disk, start command and a random `JWT_SECRET` are configured
   automatically, and migrations run on every deploy. When it's live,
   `https://<service>.onrender.com/health` returns `{"status":"ok"}`.
2. **Frontend (Vercel):** **Add New → Project** → this repo, with **Root
   Directory** `frontend` and environment variable `VITE_API_URL` =
   `https://<service>.onrender.com`. Deploy.
3. **Connect them:** in Render, set `FRONTEND_URL` to the Vercel address
   (e.g. `https://corevault.vercel.app`, no trailing slash) and save. Render
   redeploys. That one setting both allows the site to call the API and
   builds share-link URLs. Extra domains go in `CORS_ORIGINS`,
   comma-separated.

Files uploaded while running locally are stored on the local machine, and
the database records their local paths. They won't download on the server,
so re-upload anything you need there.

## Troubleshooting

- **`alembic upgrade head` can't connect / times out**: double-check
  `DATABASE_URL` in `.env` — the password has no brackets around it (it's
  `[YOUR-PASSWORD]` as a placeholder in Supabase's own UI, not literal
  brackets), the URL is the **session pooler** one (host
  `aws-0-<region>.pooler.supabase.com`, port `5432`, username
  `postgres.<project-ref>`), and the project has finished provisioning in
  the Supabase dashboard (a brand-new project can take a minute or two).
- **"could not translate host name db.<ref>.supabase.co"**: you're using
  the direct-connection host, which is IPv6-only. Switch to the session
  pooler URL as above. If the session pooler URL fails the same way, check
  the dashboard: free-plan projects pause after about a week of inactivity,
  and a paused project's hostnames stop resolving until you click
  **Restore project**.
- **SSL-related connection errors** (e.g. `SSL SYSCALL error`,
  `server does not support SSL`): Supabase always requires SSL, so
  `DATABASE_SSL` in `.env` should be `true` (the default) whenever
  `DATABASE_URL` points at Supabase — only set it to `false` if you've
  pointed the URL at a local Postgres instead (see
  `docker-compose.yml.unused`).
- **CORS errors in the browser console**: the backend only allows
  `http://localhost:5173` / `http://127.0.0.1:5173` by default (see
  `app/main.py`) — make sure the frontend really is running on port 5173.
- **`ModuleNotFoundError: bcrypt.__about__`** (or similar passlib/bcrypt
  error): re-run `pip install -r requirements.txt` — the pinned
  `bcrypt==4.0.1` in that file avoids a known incompatibility between
  passlib 1.7.4 and bcrypt >= 4.1.
- **"Invalid code" on 2FA setup/login**: the code is time-based (30s
  windows, ±1 tolerated) — make sure your machine's clock is roughly
  correct, and enter a *fresh* code rather than one from a screenshot.
- **Uploads over ~5 MB return 413 from `/files/upload`**: expected —
  that endpoint is single-shot only (`SINGLE_SHOT_UPLOAD_MAX_BYTES` in
  `app/config.py`); the frontend automatically switches to the chunked
  endpoints above that size, so this only shows up if you're calling the
  API directly (e.g. curl) rather than through the UI.

## Phase 2 design decisions worth knowing about

A few choices that aren't obvious from the endpoint list alone:

- **Quota + dedup interaction**: a blob's bytes only count against a
  user's quota the *first* time that user comes to own that content hash
  (via any file/version of theirs, past or present). Uploading a file you
  already have elsewhere is free; two different users each pay for their
  own first copy. See the comment above the charge check in
  `app/workers.py::finalize_upload`.
- **Soft-delete doesn't free quota or blob refs**: a file sitting in the
  recycle bin still counts against your quota and its blob's `ref_count`
  is untouched — only an eventual purge (Phase 3) would release either.
  This matches how most real recycle bins behave (it's still "yours").
- **Folder-level sharing is schema-ready but not exposed**: `permissions`
  supports `folder_id` grants (and `app/permissions.py` resolves them by
  walking up the folder tree), but Phase 2 only exposes the *endpoint* for
  granting on a file (`POST /files/{id}/permissions`), per the spec. A
  direct file-level grant deliberately overrides folder-level access when
  both exist, so a user shared one file inside someone else's folder can
  version that file without seeing the rest of the folder.
- **The per-content-hash and per-user locks are in-process only**
  (`threading.Lock` registries in `app/workers.py`), which is correct for
  the single `uvicorn` process this project runs as (per its Phase 1
  design) but would need a cross-process mechanism (e.g. Postgres advisory
  locks) if ever run with multiple worker processes.
- **Chunked-upload sessions live on disk, not in a table** — there's no
  "uploads" table in the Phase 2 schema, so `app/chunked_uploads.py` keeps
  each session's metadata as a `meta.json` next to its chunks and answers
  "which chunks arrived" by listing the directory, so it tolerates a
  server restart mid-upload (single-process assumption, same as above).
