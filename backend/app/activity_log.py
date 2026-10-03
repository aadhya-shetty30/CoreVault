"""
Phase 3: one-line helper for writing file_activity rows (see
models.FileActivity). It only ADDS the row to the caller's session -- it
never commits -- so each event lands in the same transaction as the change
it describes: if the delete/grant/upload rolls back, so does its log line.

Works with both session flavours in this codebase: the request's
AsyncSession and app/workers.py's sync Session both expose a plain,
non-awaited .add().
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import File, FileActivity, User
from app.schemas import FileActivityOut

# The complete vocabulary -- the frontend maps each to a label/icon.
UPLOADED = "uploaded"
NEW_VERSION = "new_version"
DOWNLOADED = "downloaded"
LINK_DOWNLOADED = "link_downloaded"
VERSION_RESTORED = "version_restored"
DELETED = "deleted"
RESTORED = "restored"
PERMISSION_GRANTED = "permission_granted"
PERMISSION_REVOKED = "permission_revoked"
LINK_CREATED = "link_created"
LINK_REVOKED = "link_revoked"
KEPT = "kept"


def human_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def log_activity(session, file_id: uuid.UUID, actor_id: Optional[uuid.UUID], action: str, detail: Optional[str] = None) -> None:
    # created_at is stamped here (microsecond precision) rather than left to
    # the server default, so events from back-to-back requests always sort
    # in the order they happened, on any database.
    session.add(
        FileActivity(
            file_id=file_id,
            actor_id=actor_id,
            action=action,
            detail=detail[:500] if detail else None,
            created_at=datetime.now(timezone.utc),
        )
    )


async def fetch_activity(db: AsyncSession, *where, limit: int = 200) -> list[FileActivityOut]:
    """Newest-first activity rows matching `where` (SQLAlchemy criteria on
    FileActivity/File), with the filename and actor's username joined in."""
    rows = (
        await db.execute(
            select(FileActivity, File.filename, User.username)
            .join(File, File.id == FileActivity.file_id)
            .outerjoin(User, User.id == FileActivity.actor_id)
            .where(*where)
            .order_by(FileActivity.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [
        FileActivityOut(
            id=a.id,
            file_id=a.file_id,
            filename=filename,
            action=a.action,
            detail=a.detail,
            actor_id=a.actor_id,
            actor_username=username,
            created_at=a.created_at,
        )
        for a, filename, username in rows
    ]
