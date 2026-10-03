"""
Async-session counterpart to app/workers.py's release_blob_ref, used by
DELETE /folders/{id} (routers/folders.py) -- the one place in Phase 2 that
still permanently destroys file rows (Phase 2 made DELETE /files/{id} a
soft-delete into the recycle bin instead, so it no longer touches blobs at
all; see that router).

Kept separate from app/workers.py deliberately: that module's sync session
exists specifically for the upload-finalization worker pool, whereas
deleting a folder subtree is a plain sequential admin-style operation
already running on the request's own async session -- there's no benefit to
routing it through the thread pool too. It reuses the exact same
per-content-hash lock (get_hash_lock) so a folder delete can never race
against a concurrent upload that's deciding whether a blob for that hash
already exists.
"""
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Blob, File, FileVersion
from app.workers import get_hash_lock


async def hard_delete_file(db: AsyncSession, file_row: File) -> int:
    """Permanently removes `file_row` and (via FK cascade) all of its
    file_versions rows. For each version, decrements the ref_count of the
    blob it points to -- deleting that blob's bytes and row only once
    nothing references it any more. Returns the number of bytes that should
    be freed from file_row.owner_id's quota: a version's bytes are only
    "freed" if, after this deletion, the owner no longer owns that content
    hash through any other file (mirrors the charge-once-per-user-per-hash
    policy applied on upload -- see app/workers.py)."""
    versions = (await db.execute(select(FileVersion).where(FileVersion.file_id == file_row.id))).scalars().all()
    distinct_hashes = {v.content_hash: v.size_bytes for v in versions}

    for version in versions:
        lock = get_hash_lock(version.content_hash)
        with lock:
            blob = (
                await db.execute(select(Blob).where(Blob.content_hash == version.content_hash))
            ).scalar_one_or_none()
            if blob is None:
                continue
            blob.ref_count -= 1
            if blob.ref_count <= 0:
                Path(blob.storage_path).unlink(missing_ok=True)
                await db.delete(blob)
    await db.flush()

    freed_bytes = 0
    for content_hash, size_bytes in distinct_hashes.items():
        still_owned = (
            await db.execute(
                select(FileVersion.id)
                .join(File, File.id == FileVersion.file_id)
                .where(File.owner_id == file_row.owner_id, FileVersion.content_hash == content_hash, File.id != file_row.id)
                .limit(1)
            )
        ).first()
        if still_owned is None:
            freed_bytes += size_bytes

    await db.delete(file_row)  # cascades to any remaining file_versions rows
    return freed_bytes
