"""
Phase 3: writes to the two stale-file-review columns on `files`
(last_accessed_at, stale_prompt_snoozed_until -- see migration 0003).

Both go through a Core UPDATE that explicitly re-assigns updated_at to its
own current value. Without that, File.updated_at's onupdate=func.now()
would fire on every download, and "updated" would silently start meaning
"last downloaded" -- which would also make every file look freshly
modified to the stale-file query in routers/analytics.py.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import File


async def touch_last_accessed(db: AsyncSession, file_id: uuid.UUID) -> None:
    """Record that the file's bytes were just read. Commits."""
    await db.execute(
        update(File)
        .where(File.id == file_id)
        .values(last_accessed_at=datetime.now(timezone.utc), updated_at=File.updated_at)
    )
    await db.commit()


async def snooze_stale_prompt(db: AsyncSession, file_id: uuid.UUID, until: datetime) -> None:
    """Suppress the stale-file prompt for this file until `until`. Commits."""
    await db.execute(
        update(File)
        .where(File.id == file_id)
        .values(stale_prompt_snoozed_until=until, updated_at=File.updated_at)
    )
    await db.commit()
