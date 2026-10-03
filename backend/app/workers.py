"""
Upload finalization: dedup check-then-write, quota accounting, and the
files/file_versions/blobs bookkeeping that makes a staged upload "real".

This module is the OS-concepts core of Phase 2 (mirroring what
app/routers/files.py's portalocker lock was for Phase 1):

  Producer-consumer queue (REQ-7.1-style)
      A single bounded ThreadPoolExecutor (`UPLOAD_EXECUTOR`) is the
      consumer side: a fixed pool of worker threads pulling jobs off the
      executor's internal work queue. Every upload-completing request
      (single-shot upload, or chunked .../complete) is a producer -- it
      builds a FinalizeUploadJob and calls submit_finalize_upload(), then
      awaits the result. When more requests arrive than there are free
      worker threads, they simply queue; nothing is dropped or rejected,
      finalization is just serialized behind the pool's capacity.

  Two *separate* mutexes, guarding two *separate* races
      1. Per-content-hash lock (`get_hash_lock`): guards the dedup
         check-then-write sequence "does a blob with this hash exist?" ->
         "if not, create one". Without it, two concurrent uploads of a
         brand-new (not yet deduped) identical file could both check, both
         see "no blob yet", and both write the bytes + both insert a blobs
         row for the same hash (violating the unique constraint at best,
         silently doubling disk usage at worst if the constraint were ever
         relaxed). Locking per-hash (not one global lock) lets unrelated
         uploads of *different* content proceed fully in parallel.
      2. Per-user lock (`get_user_lock`): guards the read-modify-write on
         users.storage_used_bytes. Without it, two concurrent uploads
         charging the same user's quota could both read the same starting
         value, both add their own delta, and last-write-wins -- losing one
         update. See scripts/test_concurrent_quota.py for a standalone
         demonstration.

  Both locks are acquired in a fixed order (hash lock, then user lock) by
  every caller, so they can never deadlock against each other.

A plain sync SQLAlchemy session (via psycopg2, same driver Alembic already
uses) is used inside worker threads rather than the app's async engine --
AsyncSession instances are not safe to share across threads/event loops, and
spinning up a *dedicated* asyncio event loop per worker thread would add
complexity for no benefit here, since this module's DB work is a short,
synchronous, transaction-scoped unit either way.
"""
import dataclasses
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app import activity_log
from app.config import settings
from app.models import Blob, File, FileVersion, User
from app.storage import blob_path

# --- Producer-consumer thread pool -------------------------------------------

UPLOAD_EXECUTOR = ThreadPoolExecutor(
    max_workers=settings.UPLOAD_WORKER_THREADS, thread_name_prefix="upload-worker"
)

# --- Sync DB access for worker threads ----------------------------------------

_sync_engine = create_engine(
    settings.sync_database_url, pool_pre_ping=True, future=True, connect_args=settings.psycopg2_connect_args
)
SyncSessionLocal = sessionmaker(bind=_sync_engine, future=True, expire_on_commit=False)


# --- Lock registries -----------------------------------------------------------
#
# Both registries grow by one entry per distinct key ever seen and are never
# pruned. For a mini-project's demo/dev lifetime that's a non-issue; a
# longer-lived deployment would want an LRU-bounded registry or a striped
# lock table instead (noted here, not built -- out of scope for this phase).

_hash_locks: dict[str, threading.Lock] = {}
_hash_locks_guard = threading.Lock()

_user_locks: dict[uuid.UUID, threading.Lock] = {}
_user_locks_guard = threading.Lock()


def get_hash_lock(content_hash: str) -> threading.Lock:
    with _hash_locks_guard:
        lock = _hash_locks.get(content_hash)
        if lock is None:
            lock = threading.Lock()
            _hash_locks[content_hash] = lock
        return lock


def get_user_lock(user_id: uuid.UUID) -> threading.Lock:
    with _user_locks_guard:
        lock = _user_locks.get(user_id)
        if lock is None:
            lock = threading.Lock()
            _user_locks[user_id] = lock
        return lock


class QuotaExceededError(Exception):
    def __init__(self, usage: int, quota: int, incoming: int):
        self.usage = usage
        self.quota = quota
        self.incoming = incoming
        super().__init__(
            f"Storage quota exceeded: {usage} + {incoming} bytes would exceed the {quota}-byte quota"
        )


@dataclasses.dataclass
class FinalizeUploadJob:
    # Whose quota this upload counts against, and who owns the resulting
    # File row. Equal to the uploader for root uploads / uploads into a
    # folder they own; equal to the folder's owner when an editor uploads
    # into a folder shared with them (see routers/files.py).
    charge_owner_id: uuid.UUID
    uploader_id: uuid.UUID  # who's recorded as file_versions.modified_by
    existing_file_id: Optional[uuid.UUID]  # set => this is a new version of an existing file
    folder_id: Optional[uuid.UUID]
    filename: str
    staged_path: Path  # bytes currently sitting in app/storage.py's staging dir
    content_hash: str
    size_bytes: int


@dataclasses.dataclass
class FinalizeUploadResult:
    file_id: uuid.UUID
    version_id: uuid.UUID
    version_number: int
    deduplicated: bool  # True if this hash already had a blob (bytes were NOT rewritten)


def _user_already_owns_hash(session, owner_id: uuid.UUID, content_hash: str) -> bool:
    """True if `owner_id` already has *any* version of *any* file (including
    old, non-current versions) with this content hash -- i.e. they've
    already been charged for these bytes once before."""
    row = session.execute(
        select(FileVersion.id)
        .join(File, File.id == FileVersion.file_id)
        .where(File.owner_id == owner_id, FileVersion.content_hash == content_hash)
        .limit(1)
    ).first()
    return row is not None


def finalize_upload(job: FinalizeUploadJob) -> FinalizeUploadResult:
    """Runs inside a worker thread (see submit_finalize_upload). Raises
    QuotaExceededError if charging this upload would exceed the target
    user's quota -- callers must translate that into an HTTP 413/422 and
    must not have written anything permanent yet when it's raised (it never
    is, by construction: the quota check happens before the blob is moved
    out of staging)."""
    hash_lock = get_hash_lock(job.content_hash)
    with hash_lock:  # --- serializes the whole dedup decision for this hash ---
        session = SyncSessionLocal()
        try:
            blob = session.execute(select(Blob).where(Blob.content_hash == job.content_hash)).scalar_one_or_none()
            deduplicated = blob is not None

            user_lock = get_user_lock(job.charge_owner_id)
            with user_lock:  # --- serializes storage_used_bytes read-modify-write ---
                user = session.get(User, job.charge_owner_id)
                already_owned = _user_already_owns_hash(session, job.charge_owner_id, job.content_hash)

                # Quota policy (documented once, here, since it's easy to get
                # subtly wrong with dedup in the picture): a unique blob only
                # counts against a user's quota the FIRST time *that user*
                # comes to own it. If user A already has this hash (from an
                # earlier upload, in any file/version), a second upload of
                # the identical content is free for A. If user B uploads the
                # exact same bytes for the first time, B is charged once,
                # independent of A. This is checked/charged before either
                # branch below touches disk.
                if not already_owned:
                    if user.storage_used_bytes + job.size_bytes > user.storage_quota_bytes:
                        raise QuotaExceededError(user.storage_used_bytes, user.storage_quota_bytes, job.size_bytes)
                    user.storage_used_bytes += job.size_bytes

                if blob is None:
                    # Not a dedup hit: move the staged bytes into permanent,
                    # content-addressed storage and register the new blob.
                    dest = blob_path(job.content_hash)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(job.staged_path), str(dest))
                    blob = Blob(
                        content_hash=job.content_hash,
                        storage_path=str(dest),
                        size_bytes=job.size_bytes,
                        ref_count=1,
                    )
                    session.add(blob)
                    session.flush()  # populate blob.id
                else:
                    # Dedup hit: identical bytes already exist on disk under
                    # another version/file (possibly another user's) --
                    # don't write a second copy, just add a reference to it.
                    blob.ref_count += 1
                    job.staged_path.unlink(missing_ok=True)

                if job.existing_file_id is not None:
                    file_row = session.get(File, job.existing_file_id)
                    last_version = session.execute(
                        select(func.max(FileVersion.version_number)).where(FileVersion.file_id == file_row.id)
                    ).scalar() or 0
                    version_number = last_version + 1
                else:
                    file_row = File(
                        owner_id=job.charge_owner_id,
                        folder_id=job.folder_id,
                        filename=job.filename,
                        size_bytes=job.size_bytes,
                        content_hash=job.content_hash,
                        storage_path=blob.storage_path,
                        blob_id=blob.id,
                    )
                    session.add(file_row)
                    session.flush()  # populate file_row.id
                    version_number = 1

                version = FileVersion(
                    file_id=file_row.id,
                    version_number=version_number,
                    content_hash=job.content_hash,
                    storage_path=blob.storage_path,
                    size_bytes=job.size_bytes,
                    modified_by=job.uploader_id,
                )
                session.add(version)
                activity_log.log_activity(
                    session,
                    file_row.id,
                    job.uploader_id,
                    activity_log.UPLOADED if version_number == 1 else activity_log.NEW_VERSION,
                    f"Version {version_number}, {activity_log.human_bytes(job.size_bytes)}"
                    + (" (identical content already stored -- no extra space used)" if deduplicated else ""),
                )

                # Repoint the file's "current version" columns at what we
                # just created -- this is what makes an upload of an
                # existing filename a new version instead of an overwrite.
                file_row.content_hash = job.content_hash
                file_row.storage_path = blob.storage_path
                file_row.size_bytes = job.size_bytes
                file_row.blob_id = blob.id

                session.commit()
                return FinalizeUploadResult(
                    file_id=file_row.id,
                    version_id=version.id,
                    version_number=version_number,
                    deduplicated=deduplicated,
                )
        except Exception:
            session.rollback()
            # Clean up the staged file on any failure -- if we got as far as
            # shutil.move()'ing it into blob storage, this is a no-op.
            job.staged_path.unlink(missing_ok=True)
            raise
        finally:
            session.close()


async def submit_finalize_upload(job: FinalizeUploadJob) -> FinalizeUploadResult:
    """Async-friendly entry point: hands `job` to the producer-consumer pool
    and awaits its result without blocking the event loop."""
    import asyncio

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(UPLOAD_EXECUTOR, finalize_upload, job)


def release_blob_ref(session, content_hash: str) -> None:
    """Decrement the ref_count of the blob backing `content_hash`; delete its
    bytes from disk (and the blobs row) once it reaches zero. Not called
    anywhere in Phase 2 yet -- there is no hard-delete path once DELETE
    /files/{id} became a soft-delete into the recycle bin (see
    routers/files.py). It exists now, fully implemented and exercised
    directly by scripts/test_dedup.py, because it's exactly what Phase 3's
    recycle-bin purge job will call once a file's purge_at is reached."""
    blob = session.execute(select(Blob).where(Blob.content_hash == content_hash)).scalar_one_or_none()
    if blob is None:
        return
    blob.ref_count -= 1
    if blob.ref_count <= 0:
        Path(blob.storage_path).unlink(missing_ok=True)
        session.delete(blob)
    session.flush()
