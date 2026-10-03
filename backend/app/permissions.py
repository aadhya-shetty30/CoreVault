"""
Role resolution for Phase 2's sharing model.

A user's role on a file/folder is, in order:
  1. "owner"  if they're the row's owner_id
  2. whatever `permissions` row grants them the role directly on that file
  3. whatever `permissions` row grants them the role on any folder in that
     file/folder's ancestor chain (a folder-level grant covers everything
     nested inside it, recursively -- see _folder_role_by_ancestry)
  4. None (no access at all -- callers should 404, not 403, to avoid
     confirming the row exists; see require_role's callers)

Folder ownership determines who a *new* file uploaded into it belongs to
(app/routers/files.py), so "does this user have >= editor on this folder"
is also the gate for "can they add files here".
"""
import uuid
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import File, Folder, Permission, PermissionRole

_ROLE_RANK = {
    PermissionRole.VIEWER: 1,
    PermissionRole.EDITOR: 2,
    PermissionRole.OWNER: 3,
}


async def _folder_role_by_ancestry(
    db: AsyncSession, folder_id: uuid.UUID, user_id: uuid.UUID
) -> Optional[PermissionRole]:
    """Walk from folder_id up to the root, returning the first explicit
    permission role found for user_id along the way (i.e. the grant closest
    to the target wins if a user somehow has grants at multiple levels)."""
    current_id: Optional[uuid.UUID] = folder_id
    seen: set[uuid.UUID] = set()
    while current_id is not None:
        if current_id in seen:
            break  # defensive: never trust the data enough to loop forever
        seen.add(current_id)
        perm = (
            await db.execute(
                select(Permission).where(Permission.folder_id == current_id, Permission.user_id == user_id)
            )
        ).scalar_one_or_none()
        if perm is not None:
            return perm.role
        folder = await db.get(Folder, current_id)
        current_id = folder.parent_folder_id if folder else None
    return None


async def get_folder_role(db: AsyncSession, folder: Optional[Folder], user_id: uuid.UUID) -> Optional[PermissionRole]:
    """`folder=None` means the user's own root -- always their own space."""
    if folder is None:
        return PermissionRole.OWNER
    if folder.owner_id == user_id:
        return PermissionRole.OWNER
    return await _folder_role_by_ancestry(db, folder.id, user_id)


async def get_file_role(db: AsyncSession, file: File, user_id: uuid.UUID) -> Optional[PermissionRole]:
    if file.owner_id == user_id:
        return PermissionRole.OWNER
    perm = (
        await db.execute(select(Permission).where(Permission.file_id == file.id, Permission.user_id == user_id))
    ).scalar_one_or_none()
    if perm is not None:
        return perm.role
    if file.folder_id is not None:
        role = await _folder_role_by_ancestry(db, file.folder_id, user_id)
        if role is not None:
            return role
    return None


def require_role(role: Optional[PermissionRole], minimum: PermissionRole, detail: str = "Not found") -> None:
    """Raise 404 (never 403) when access is missing or insufficient, so the
    API never confirms to a caller that a file/folder id they can't touch
    even exists -- same reasoning as app/ownership.py's Phase-1 helpers."""
    if role is None or _ROLE_RANK[role] < _ROLE_RANK[minimum]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail)
