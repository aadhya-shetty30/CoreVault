"""
Revoking a previously-granted permission. Granting/listing live under
/files/{id}/permissions (app/routers/files.py, since they're always scoped
to one file); revoke gets its own top-level path per the spec
(DELETE /permissions/{id}) since a permission row's id alone is enough to
identify it.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import activity_log
from app.database import get_db
from app.deps import get_current_user
from app.models import File, Folder, Permission, User

router = APIRouter(prefix="/permissions", tags=["permissions"])


@router.delete("/{permission_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_permission(
    permission_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    perm = await db.get(Permission, permission_id)
    if perm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Permission not found")

    # Only the file's/folder's actual owner may revoke -- same rule as
    # granting. 404 (not 403) if the caller isn't the owner, so this
    # endpoint never confirms a permission id they can't touch exists.
    is_owner = False
    if perm.file_id is not None:
        target = await db.get(File, perm.file_id)
        is_owner = target is not None and target.owner_id == current_user.id
    elif perm.folder_id is not None:
        target = await db.get(Folder, perm.folder_id)
        is_owner = target is not None and target.owner_id == current_user.id

    if not is_owner:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Permission not found")

    if perm.file_id is not None:
        grantee = await db.get(User, perm.user_id)
        activity_log.log_activity(
            db,
            perm.file_id,
            current_user.id,
            activity_log.PERMISSION_REVOKED,
            f"{grantee.username if grantee else 'A user'}'s {perm.role.value} access removed",
        )
    await db.delete(perm)
    await db.commit()
    return None
