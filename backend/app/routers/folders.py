"""
Folder CRUD: create, fetch (children + breadcrumb), rename/move, hard delete.

Move-cycle prevention (PATCH): a folder can never become its own descendant
by being moved under itself, or under one of its own children. We check
this explicitly in _is_descendant() below rather than relying on any DB
constraint, because a self-referencing FK has no notion of "ancestor" --
only application code walking the tree can answer that question.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.blob_release import hard_delete_file
from app.database import get_db
from app.deps import get_current_user
from app.models import File, Folder, PermissionRole, User
from app.ownership import get_accessible_folder, get_owned_folder
from app.schemas import (
    BreadcrumbItem,
    FileChildOut,
    FolderChildOut,
    FolderCreate,
    FolderDetailOut,
    FolderUpdate,
)

router = APIRouter(prefix="/folders", tags=["folders"])


async def _breadcrumb(db: AsyncSession, folder: Optional[Folder]) -> list[BreadcrumbItem]:
    """Walk parent_folder_id up to the root, then reverse -> root-first path."""
    crumbs: list[BreadcrumbItem] = []
    current = folder
    seen: set[uuid.UUID] = set()
    while current is not None:
        if current.id in seen:
            break  # defensive: never trust the data enough to loop forever
        seen.add(current.id)
        crumbs.append(BreadcrumbItem(id=current.id, name=current.name))
        current = await db.get(Folder, current.parent_folder_id) if current.parent_folder_id else None
    crumbs.append(BreadcrumbItem(id=None, name="My files"))
    crumbs.reverse()
    return crumbs


async def _is_descendant(db: AsyncSession, candidate_id: uuid.UUID, ancestor_id: uuid.UUID) -> bool:
    """True if `candidate_id` IS `ancestor_id`, or lies anywhere beneath it
    in the folder tree. Used to block a move that would create a cycle."""
    current_id: Optional[uuid.UUID] = candidate_id
    seen: set[uuid.UUID] = set()
    while current_id is not None:
        if current_id == ancestor_id:
            return True
        if current_id in seen:
            break
        seen.add(current_id)
        current = await db.get(Folder, current_id)
        current_id = current.parent_folder_id if current else None
    return False


async def _folder_detail(db: AsyncSession, owner_id: uuid.UUID, folder: Optional[Folder]) -> FolderDetailOut:
    """`owner_id` is whoever the folder's contents actually belong to -- the
    folder's own owner_id for a real Folder, or the caller's own id for
    root (root has no owner_id/sharing of its own). NOT necessarily the
    caller: a shared folder's children still belong to its real owner."""
    parent_id = folder.id if folder else None
    child_folders = (
        await db.execute(select(Folder).where(Folder.owner_id == owner_id, Folder.parent_folder_id == parent_id))
    ).scalars().all()
    child_files = (
        await db.execute(
            select(File).where(
                File.owner_id == owner_id,
                File.folder_id == parent_id,
                File.is_deleted == False,  # noqa: E712 -- SQLAlchemy needs "==", not "is"
            )
        )
    ).scalars().all()

    return FolderDetailOut(
        id=folder.id if folder else None,
        name=folder.name if folder else "My files",
        breadcrumb=await _breadcrumb(db, folder),
        folders=[FolderChildOut.model_validate(f) for f in child_folders],
        files=[FileChildOut.model_validate(f) for f in child_files],
    )


@router.post("", response_model=FolderDetailOut, status_code=status.HTTP_201_CREATED)
async def create_folder(
    payload: FolderCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Creating a subfolder needs the same access level as uploading a file
    # into one -- editor or better (owner of one's own root always qualifies).
    parent = await get_accessible_folder(db, payload.parent_folder_id, current_user.id, PermissionRole.EDITOR)
    owner_id = parent.owner_id if parent else current_user.id

    folder = Folder(owner_id=owner_id, parent_folder_id=parent.id if parent else None, name=payload.name)
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return await _folder_detail(db, owner_id, folder)


@router.get("/root", response_model=FolderDetailOut)
async def get_root(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _folder_detail(db, current_user.id, None)


@router.get("/{folder_id}", response_model=FolderDetailOut)
async def get_folder(
    folder_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    folder = await get_accessible_folder(db, folder_id, current_user.id, PermissionRole.VIEWER)
    return await _folder_detail(db, folder.owner_id, folder)


@router.patch("/{folder_id}", response_model=FolderDetailOut)
async def update_folder(
    folder_id: uuid.UUID,
    payload: FolderUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    fields_set = payload.model_fields_set
    # Renaming is an editor-level action; moving a folder (reparenting, in
    # either direction) is restricted to the owner, since it can change who
    # is allowed to see it.
    minimum = PermissionRole.OWNER if "parent_folder_id" in fields_set else PermissionRole.EDITOR
    folder = await get_accessible_folder(db, folder_id, current_user.id, minimum)

    if "name" in fields_set and payload.name is not None:
        folder.name = payload.name

    if "parent_folder_id" in fields_set:
        new_parent_id = payload.parent_folder_id
        if new_parent_id is not None:
            if new_parent_id == folder.id or await _is_descendant(db, new_parent_id, folder.id):
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Cannot move a folder into itself or one of its own subfolders",
                )
            await get_owned_folder(db, new_parent_id, current_user.id)  # destination must be owned outright
        folder.parent_folder_id = new_parent_id

    await db.commit()
    await db.refresh(folder)
    return await _folder_detail(db, folder.owner_id, folder)


async def _collect_subtree_folder_ids(db: AsyncSession, root_id: uuid.UUID) -> list[uuid.UUID]:
    """Breadth-first walk of the folder tree rooted at root_id (inclusive).
    Returned in level order (root first, deepest last) so callers can
    delete in reverse to satisfy the parent_folder_id FK."""
    ids = [root_id]
    frontier = [root_id]
    while frontier:
        rows = (await db.execute(select(Folder.id).where(Folder.parent_folder_id.in_(frontier)))).scalars().all()
        if not rows:
            break
        ids.extend(rows)
        frontier = rows
    return ids


@router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(
    folder_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    folder = await get_owned_folder(db, folder_id, current_user.id)
    subtree_ids = await _collect_subtree_folder_ids(db, folder.id)

    # Files first: release each one's blob reference(s) (deleting bytes from
    # disk only once nothing else references them -- see
    # app/blob_release.py) and the metadata rows, for every file anywhere in
    # this folder's subtree, INCLUDING ones currently sitting in the
    # recycle bin (is_deleted=True) -- a folder delete is permanent and
    # shouldn't leave orphaned recycle-bin entries pointing at a folder that
    # no longer exists.
    files = (
        await db.execute(select(File).where(File.folder_id.in_(subtree_ids), File.owner_id == current_user.id))
    ).scalars().all()
    freed_bytes = 0
    for f in files:
        freed_bytes += await hard_delete_file(db, f)

    # Folders deepest-first (reverse of the BFS level order) so we never try
    # to delete a folder row while one of its children still points at it.
    folders = (await db.execute(select(Folder).where(Folder.id.in_(subtree_ids)))).scalars().all()
    folders_by_id = {f.id: f for f in folders}
    for fid in reversed(subtree_ids):
        if fid in folders_by_id:
            await db.delete(folders_by_id[fid])

    current_user.storage_used_bytes = max(0, current_user.storage_used_bytes - freed_bytes)
    await db.commit()
    return None
