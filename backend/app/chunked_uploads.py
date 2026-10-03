"""
Bookkeeping for the chunked upload flow (POST /files/upload/init ->
.../chunk/{i} -> .../complete). Deliberately filesystem-backed rather than a
DB table (none is listed in the Phase 2 schema): each in-progress upload's
metadata lives in a small meta.json next to its chunks, under
STORAGE_ROOT/chunk_uploads/<upload_id>/. This also means "which chunks have
arrived" is answered by listing the chunks directory rather than trusting an
in-memory set, so it stays correct even if the server restarts mid-upload
(single-process assumption, same as the rest of this app -- see README).
"""
import json
import shutil
import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel

from app.storage import chunk_meta_path, chunk_part_path, chunk_upload_dir


class ChunkUploadMeta(BaseModel):
    upload_id: str
    owner_id: str  # str(UUID) -- keeps this module independent of app.models
    filename: str
    folder_id: Optional[str]
    total_size: int
    chunk_count: int
    created_at: str


def create_upload_session(
    owner_id: uuid.UUID, filename: str, folder_id: Optional[uuid.UUID], total_size: int, chunk_count: int
) -> ChunkUploadMeta:
    upload_id = uuid.uuid4().hex
    meta = ChunkUploadMeta(
        upload_id=upload_id,
        owner_id=str(owner_id),
        filename=filename,
        folder_id=str(folder_id) if folder_id else None,
        total_size=total_size,
        chunk_count=chunk_count,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    chunk_upload_dir(upload_id).mkdir(parents=True, exist_ok=True)
    chunk_part_path(upload_id, 0).parent.mkdir(parents=True, exist_ok=True)
    chunk_meta_path(upload_id).write_text(meta.model_dump_json())
    return meta


def load_upload_session(upload_id: str) -> Optional[ChunkUploadMeta]:
    path = chunk_meta_path(upload_id)
    if not path.exists():
        return None
    return ChunkUploadMeta.model_validate_json(path.read_text())


def received_chunk_indices(upload_id: str) -> set[int]:
    chunks_dir = chunk_part_path(upload_id, 0).parent
    if not chunks_dir.exists():
        return set()
    indices = set()
    for p in chunks_dir.glob("*.part"):
        try:
            indices.add(int(p.stem))
        except ValueError:
            continue
    return indices


def discard_upload_session(upload_id: str) -> None:
    shutil.rmtree(chunk_upload_dir(upload_id), ignore_errors=True)
