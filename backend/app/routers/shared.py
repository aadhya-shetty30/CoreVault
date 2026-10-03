"""
Public, unauthenticated access to a file via a shared_links token.

Deliberately has no dependency on get_current_user -- anyone with the token
gets access, which is the whole point of a share link. The token itself
(secrets.token_urlsafe(32) -- 256 bits of randomness, see
routers/files.py's create_share_link) is the only thing standing in for
authentication here, so it's never guessable/enumerable.
"""
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import activity_log
from app.database import get_db
from app.file_activity import touch_last_accessed
from app.models import File, SharedLink
from app.schemas import SharedLinkInfoOut

router = APIRouter(prefix="/shared", tags=["shared"])


async def _load_link(db: AsyncSession, token: str) -> tuple[Optional[SharedLink], Optional[str]]:
    """Returns (link, invalid_reason). invalid_reason is None iff the link
    is currently usable (exists, not expired, under its access-count cap)."""
    link = (await db.execute(select(SharedLink).where(SharedLink.token == token))).scalar_one_or_none()
    if link is None:
        return None, "Link not found"
    now = datetime.now(timezone.utc)
    if link.expires_at is not None and link.expires_at < now:
        return link, "This link has expired"
    if link.max_access_count is not None and link.access_count >= link.max_access_count:
        return link, "This link has reached its access limit"
    return link, None


@router.get("/{token}/info", response_model=SharedLinkInfoOut)
async def shared_link_info(token: str, db: AsyncSession = Depends(get_db)):
    """Metadata for the public "you've been sent a file" landing page.
    Doesn't increment access_count -- only an actual download does."""
    link, reason = await _load_link(db, token)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found")

    file_row = await db.get(File, link.file_id)
    if file_row is None or file_row.is_deleted:
        return SharedLinkInfoOut(filename="", size_bytes=0, role=link.role.value, valid=False, reason="File no longer available")

    return SharedLinkInfoOut(
        filename=file_row.filename,
        size_bytes=file_row.size_bytes,
        role=link.role.value,
        valid=reason is None,
        reason=reason,
    )


@router.get("/{token}")
async def shared_link_download(token: str, db: AsyncSession = Depends(get_db)):
    link, reason = await _load_link(db, token)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found")
    if reason is not None:
        raise HTTPException(status.HTTP_410_GONE, reason)

    file_row = await db.get(File, link.file_id)
    if file_row is None or file_row.is_deleted:
        raise HTTPException(status.HTTP_410_GONE, "File no longer available")

    path = Path(file_row.storage_path)
    if not path.exists():
        raise HTTPException(status.HTTP_410_GONE, "File metadata exists but the data is missing from storage")

    # Editor and viewer links both just download here -- there is no
    # write-capable action exposed through a public link in this phase (see
    # module docstring / README), so "download only if viewer" from the
    # spec is satisfied trivially: it's download-only for everyone.
    link.access_count += 1
    uses = f"use {link.access_count}" + (f" of {link.max_access_count}" if link.max_access_count else "")
    # actor_id=None: whoever holds a public link is anonymous by design.
    activity_log.log_activity(
        db, file_row.id, None, activity_log.LINK_DOWNLOADED, f"Via public {link.role.value} link ({uses})"
    )
    await db.commit()
    filename = file_row.filename
    # Phase 3: someone actually reading the file via a link counts as it
    # being in use, so it shouldn't show up in the owner's stale-file prompt.
    await touch_last_accessed(db, file_row.id)
    return FileResponse(path, filename=filename, media_type="application/octet-stream")
