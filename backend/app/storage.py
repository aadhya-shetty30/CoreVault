"""
Filesystem layout helpers for user-uploaded files.

Layout: STORAGE_ROOT/<user_id>/<folder_id-or-"root">/<sanitized filename>

Deriving the on-disk path from (user, folder, filename) -- rather than a
random id generated per upload -- is deliberate: it means uploading a file
with the same name into the same folder twice targets the *same* physical
path. That is exactly the race condition app/routers/files.py's portalocker
lock exists to demonstrate/guard against. Content dedup and versioning
across uploads that land on the same path are explicitly out of scope for
this phase.
"""
import os
import uuid
from pathlib import Path
from typing import Optional

from app.config import settings

STORAGE_ROOT = Path(settings.STORAGE_ROOT).resolve()


def sanitize_filename(filename: str) -> str:
    """Strip any directory components a client might smuggle into the
    filename (e.g. "../../etc/passwd") so an upload can never write outside
    the user's own storage directory. Deliberately simple -- this is the
    entire defense, and it's enough because we only ever use the result as
    the last path segment under a directory we already control."""
    name = os.path.basename(filename.replace("\\", "/"))
    return name or "unnamed"


def user_root(user_id: uuid.UUID) -> Path:
    return STORAGE_ROOT / str(user_id)


def folder_storage_dir(user_id: uuid.UUID, folder_id: Optional[uuid.UUID]) -> Path:
    segment = str(folder_id) if folder_id else "root"
    return user_root(user_id) / segment


def destination_path(user_id: uuid.UUID, folder_id: Optional[uuid.UUID], filename: str) -> Path:
    return folder_storage_dir(user_id, folder_id) / sanitize_filename(filename)


# --- Phase 2: content-addressed blob storage, staging, and chunked upload ----
#
# Deduplication (see app/workers.py) needs uploaded bytes to live at a path
# derived from their SHA-256 rather than from (user, folder, filename) --
# that's what lets two different files with identical content share one copy
# on disk. This lives alongside the Phase-1 per-file layout above; neither
# replaces the other. Phase-1 rows keep pointing at their original
# `destination_path()` location untouched.

STAGING_DIR = STORAGE_ROOT / "tmp"
BLOBS_DIR = STORAGE_ROOT / "blobs"
CHUNK_UPLOADS_DIR = STORAGE_ROOT / "chunk_uploads"


def new_staging_path() -> Path:
    """A throwaway path for streaming an in-progress upload to disk before
    its SHA-256 (and therefore its final, permanent location) is known."""
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    return STAGING_DIR / f"{uuid.uuid4().hex}.part"


def blob_path(content_hash: str) -> Path:
    """Permanent, content-addressed location for a blob. Splitting on the
    first two hex chars keeps any single directory from accumulating
    thousands of entries as the store grows."""
    return BLOBS_DIR / content_hash[:2] / content_hash


def chunk_upload_dir(upload_id: str) -> Path:
    return CHUNK_UPLOADS_DIR / upload_id


def chunk_part_path(upload_id: str, chunk_index: int) -> Path:
    return chunk_upload_dir(upload_id) / "chunks" / f"{chunk_index:08d}.part"


def chunk_meta_path(upload_id: str) -> Path:
    return chunk_upload_dir(upload_id) / "meta.json"
