"""
Uploads the exact same file content twice (different filenames -- dedup is
keyed on SHA-256, not on name) against a *running* CoreVault backend, then
connects directly to the database to assert:
  1. Exactly one `blobs` row exists for that content hash, with ref_count == 2
  2. Exactly one copy of those bytes actually exists on disk
  3. Both files' `file_versions` rows point at the same blob's storage_path

This exercises the same dedup check-then-write path documented in
app/workers.py's finalize_upload() -- see scripts/test_concurrent_quota.py
for the sibling script that stresses its per-user quota lock instead of its
per-hash dedup lock, and app/workers.release_blob_ref() for the ref-count
*decrement* side of this mechanism (exercised directly, below, since Phase 2
has no route that hard-deletes a file yet -- see that function's docstring).

Usage (from backend/, with the venv active and the API already running --
see the project README):
    python scripts/test_dedup.py [base_url]

base_url defaults to http://127.0.0.1:8000. Connects to the same Postgres
database the running API uses (DATABASE_URL from .env via app/config.py).
"""
import hashlib
import sys
import time
import uuid
from pathlib import Path

import requests
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.models import Blob, File, FileVersion  # noqa: E402
from app.workers import release_blob_ref  # noqa: E402

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"


def main() -> None:
    stamp = int(time.time())
    email = f"dedup{stamp}@example.com"
    username = f"dedup{stamp}"
    password = "correct-horse-battery-staple"
    content = f"This exact same content is uploaded twice - {stamp}\n".encode()
    expected_hash = hashlib.sha256(content).hexdigest()

    print(f"1. Registering {email} ...")
    r = requests.post(f"{BASE_URL}/auth/register", json={"email": email, "username": username, "password": password})
    r.raise_for_status()

    print("2. Logging in ...")
    r = requests.post(f"{BASE_URL}/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    print(f"3. Uploading identical content as 'first.txt' (sha256={expected_hash[:12]}...) ...")
    r = requests.post(
        f"{BASE_URL}/files/upload", headers=headers,
        files={"file": ("first.txt", content, "text/plain")},
    )
    r.raise_for_status()
    first = r.json()
    assert first["content_hash"] == expected_hash

    print("4. Uploading the SAME bytes again as 'second.txt' ...")
    r = requests.post(
        f"{BASE_URL}/files/upload", headers=headers,
        files={"file": ("second.txt", content, "text/plain")},
    )
    r.raise_for_status()
    second = r.json()
    assert second["content_hash"] == expected_hash
    assert second["id"] != first["id"], "these are two different files, not two versions of one"

    print("5. Connecting directly to the database to inspect the blobs table ...")
    engine = create_engine(settings.sync_database_url, future=True, connect_args=settings.psycopg2_connect_args)
    with Session(engine) as session:
        blobs = session.execute(select(Blob).where(Blob.content_hash == expected_hash)).scalars().all()
        assert len(blobs) == 1, f"expected exactly 1 blob row for this hash, found {len(blobs)}"
        blob = blobs[0]
        print(f"   blob row: id={blob.id} ref_count={blob.ref_count} storage_path={blob.storage_path}")
        assert blob.ref_count == 2, f"expected ref_count == 2 (one per file), got {blob.ref_count}"

        blob_path = Path(blob.storage_path)
        assert blob_path.exists(), f"blob bytes missing from disk at {blob_path}"
        print(f"   bytes on disk at {blob_path}: {blob_path.stat().st_size} bytes -- exactly one copy")

        for label, file_id in (("first.txt", first["id"]), ("second.txt", second["id"])):
            versions = session.execute(
                select(FileVersion).where(FileVersion.file_id == uuid.UUID(file_id))
            ).scalars().all()
            assert len(versions) == 1
            assert versions[0].storage_path == blob.storage_path, f"{label}'s version doesn't point at the shared blob"
        print("   both files' file_versions rows point at the exact same on-disk path -- confirmed shared, not duplicated")

        print("\n6. Exercising the ref-count DECREMENT side (release_blob_ref) directly:")
        print("   (Phase 2 has no hard-delete route -- DELETE /files/{id} is a soft-delete into")
        print("    the recycle bin now -- so this calls the same function Phase 3's purge job will.)")
        release_blob_ref(session, expected_hash)
        session.commit()
        blob = session.execute(select(Blob).where(Blob.content_hash == expected_hash)).scalar_one()
        print(f"   after releasing one reference: ref_count={blob.ref_count} (bytes still on disk: {blob_path.exists()})")
        assert blob.ref_count == 1
        assert blob_path.exists(), "bytes must survive while ref_count > 0"

        release_blob_ref(session, expected_hash)
        session.commit()
        remaining = session.execute(select(Blob).where(Blob.content_hash == expected_hash)).scalar_one_or_none()
        print(f"   after releasing the second (last) reference: blob row exists={remaining is not None}, bytes on disk={blob_path.exists()}")
        assert remaining is None, "blob row should be deleted once ref_count reaches 0"
        assert not blob_path.exists(), "bytes should be unlinked once ref_count reaches 0"

    print("\nAll good -- one blob row, ref_count tracked correctly on the way up (upload) and down (release), one copy of the bytes on disk.")


if __name__ == "__main__":
    main()
