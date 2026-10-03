"""
"Does this row belong to this user" lookups shared by the folders and files
routers. Kept in one place (instead of duplicated per-router private
helpers) since both routers need the exact same not-found-vs-not-yours
semantics.
"""
import uuid
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import File, Folder, PermissionRole
from app.permissions import get_file_role, get_folder_role, require_role


async def get_owned_folder(db: AsyncSession, folder_id: uuid.UUID, owner_id: uuid.UUID) -> Folder:
    folder = await db.get(Folder, folder_id)
    if folder is None or folder.owner_id != owner_id:
        # 404 (not 403) even when the folder exists but belongs to someone
        # else, so the API never confirms another user's folder ids exist.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found")
    return folder


async def get_owned_file(db: AsyncSession, file_id: uuid.UUID, owner_id: uuid.UUID) -> File:
    file_row = await db.get(File, file_id)
    if file_row is None or file_row.owner_id != owner_id or file_row.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return file_row


# --- Phase 2: permission-aware access (sharing) ------------------------------
#
# The two helpers above stay exactly as Phase 1 left them (still used by
# owner-only routes: grant/revoke, hard bits of delete, recycle bin). These
# additionally accept a shared editor/viewer, per app/permissions.py.


async def get_accessible_folder(
    db: AsyncSession, folder_id: Optional[uuid.UUID], user_id: uuid.UUID, minimum: PermissionRole = PermissionRole.VIEWER
) -> Optional[Folder]:
    """Returns the folder (or None for root) if `user_id` has at least
    `minimum` role on it -- via ownership or a permissions grant on it or an
    ancestor. Raises 404 otherwise. `folder_id=None` always succeeds (a
    user's own root)."""
    if folder_id is None:
        return None
    folder = await db.get(Folder, folder_id)
    if folder is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found")
    role = await get_folder_role(db, folder, user_id)
    require_role(role, minimum, "Folder not found")
    return folder


async def get_accessible_file(
    db: AsyncSession, file_id: uuid.UUID, user_id: uuid.UUID, minimum: PermissionRole = PermissionRole.VIEWER
) -> File:
    file_row = await db.get(File, file_id)
    if file_row is None or file_row.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    role = await get_file_role(db, file_row, user_id)
    require_role(role, minimum, "File not found")
    return file_row
