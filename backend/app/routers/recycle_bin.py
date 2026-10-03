"""
Recycle bin: list/restore a user's own soft-deleted files. Scoped strictly
to owner_id == current_user.id -- an editor/viewer who lost access to a
shared file never sees it here, since it isn't "their" file to begin with.

The automatic purge job (deleting anything past its purge_at, and only then
decrementing the backing blob's ref_count / freeing bytes / quota) is
explicitly Phase 3 (APScheduler); purge_at sits unused by any job for now,
per the Phase 2 spec.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import activity_log
from app.database import get_db
from app.deps import get_current_user
from app.models import File, User
from app.schemas import FileOut, RecycleBinItemOut

router = APIRouter(prefix="/recycle-bin", tags=["recycle-bin"])


@router.get("", response_model=list[RecycleBinItemOut])
async def list_recycle_bin(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(File).where(File.owner_id == current_user.id, File.is_deleted == True)  # noqa: E712
        )
    ).scalars().all()
    now = datetime.now(timezone.utc)

    def _days_remaining(purge_at) -> int:
        if purge_at is None:
            return 0
        # Defensive: purge_at should always come back tz-aware (Postgres'
        # timestamptz round-trips as one via asyncpg), but coerce a naive
        # value to UTC rather than let the subtraction below raise.
        if purge_at.tzinfo is None:
            purge_at = purge_at.replace(tzinfo=timezone.utc)
        return max(0, (purge_at - now).days)

    return [
        RecycleBinItemOut(
            id=row.id,
            filename=row.filename,
            size_bytes=row.size_bytes,
            folder_id=row.folder_id,
            deleted_at=row.deleted_at,
            purge_at=row.purge_at,
            days_remaining=_days_remaining(row.purge_at),
        )
        for row in rows
    ]


@router.post("/{file_id}/restore", response_model=FileOut)
async def restore_from_recycle_bin(
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    file_row = await db.get(File, file_id)
    if file_row is None or file_row.owner_id != current_user.id or not file_row.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found in recycle bin")

    file_row.is_deleted = False
    file_row.deleted_at = None
    file_row.purge_at = None
    activity_log.log_activity(db, file_row.id, current_user.id, activity_log.RESTORED, "Restored from the recycle bin")
    await db.commit()
    await db.refresh(file_row)
    return file_row
