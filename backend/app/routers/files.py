"""
File upload/download/metadata/delete, plus everything Phase 2 adds on top:
chunked upload, content-dedup, versioning, the recycle-bin soft-delete, and
permission-based sharing.

Phase 1's upload wrote straight to a path derived from (user, folder,
filename), guarded by a portalocker lock on that exact path (see git history
/ README for the Phase-1 writeup). Phase 2 needs every upload of an existing
filename to become a new *version* instead of overwriting, and needs
identical bytes to be stored once no matter how many files/users reference
them -- both are impossible with a filename-derived path. So uploads now
stream to a private staging file first (see app/storage.py's
new_staging_path -- unique per request, nothing else can ever target it, so
no lock is needed there), then hand off to app/workers.py's
finalize_upload(), which does the real dedup-check/quota/versioning work
under its per-content-hash and per-user locks. That module's docstring has
the full race-condition writeup this phase is graded on.
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File as FastAPIFile, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chunked_uploads import (
    create_upload_session,
    discard_upload_session,
    load_upload_session,
    received_chunk_indices,
)
from app import activity_log
from app.activity_log import log_activity
from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.file_activity import touch_last_accessed
from app.models import Blob, File as FileModel, FileActivity, FileVersion, Folder, Permission, PermissionRole, SharedLink, ShareRole, User
from app.ownership import get_accessible_file
from app.permissions import get_file_role, get_folder_role, require_role
from app.schemas import (
    ChunkAckOut,
    ChunkedUploadInitOut,
    ChunkedUploadInitRequest,
    FileActivityOut,
    FileOut,
    FileVersionOut,
    PermissionGrantRequest,
    PermissionOut,
    ShareLinkCreateRequest,
    ShareLinkOut,
)
from app.storage import chunk_part_path, new_staging_path, sanitize_filename
from app.workers import FinalizeUploadJob, QuotaExceededError, submit_finalize_upload

router = APIRouter(prefix="/files", tags=["files"])

CHUNK_SIZE = 1024 * 1024  # 1 MiB per read/write/hash step


# --- shared helpers ------------------------------------------------------------


async def _stage_upload(upload: UploadFile, max_bytes: Optional[int] = None) -> tuple[Path, str, int]:
    """Stream `upload` to a private staging path, hashing as bytes arrive.
    Raises 413 (without leaving a partial file behind) if `max_bytes` is set
    and exceeded -- checked as bytes stream in, so an oversized upload is
    rejected without ever fully landing on disk."""
    staged_path = new_staging_path()
    hasher = hashlib.sha256()
    size = 0
    with open(staged_path, "wb") as f:
        while True:
            chunk = await upload.read(CHUNK_SIZE)
            if not chunk:
                break
            size += len(chunk)
            if max_bytes is not None and size > max_bytes:
                f.close()
                staged_path.unlink(missing_ok=True)
                raise HTTPException(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    f"File exceeds the {max_bytes}-byte single-shot upload limit; "
                    "use the chunked upload endpoints (/files/upload/init) instead",
                )
            f.write(chunk)
            hasher.update(chunk)
    return staged_path, hasher.hexdigest(), size


async def _find_existing_file(
    db: AsyncSession, owner_id: uuid.UUID, folder_id: Optional[uuid.UUID], filename: str
) -> Optional[FileModel]:
    return (
        await db.execute(
            select(FileModel).where(
                FileModel.owner_id == owner_id,
                FileModel.folder_id == folder_id,
                FileModel.filename == filename,
                FileModel.is_deleted == False,  # noqa: E712
            )
        )
    ).scalar_one_or_none()


async def _authorize_upload(
    db: AsyncSession, current_user: User, folder_id: Optional[uuid.UUID], filename: str
) -> tuple[Optional[uuid.UUID], uuid.UUID, Optional[FileModel]]:
    """Checks the caller may upload `filename` into `folder_id`, resolves
    who the resulting file belongs to (and therefore whose quota it counts
    against -- the folder's owner, so a shared folder's storage counts
    against its owner regardless of which editor actually uploads into it),
    and finds any existing file this upload would create a new version of.

    Deliberately checks the EXISTING FILE's own permissions first, before
    ever requiring folder-level access: a user shared a file directly
    (permissions.file_id) can upload new versions of *that file* without
    needing any access to the folder it happens to live in. Folder-level
    access is only required to create a brand-new file (nothing to check a
    direct grant against yet).

    Returns (folder_id_or_None, charge_owner_id, existing_file_or_None).
    Raises 404 (never confirming *why*) if the caller can't reach this file
    or folder at all, or can but only as a viewer."""
    folder: Optional[Folder] = None
    if folder_id is not None:
        folder = await db.get(Folder, folder_id)
        if folder is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found")

    charge_owner_id = folder.owner_id if folder else current_user.id
    resolved_folder_id = folder.id if folder else None

    existing_file = await _find_existing_file(db, charge_owner_id, resolved_folder_id, filename)
    if existing_file is not None:
        role = await get_file_role(db, existing_file, current_user.id)
        require_role(role, PermissionRole.EDITOR, "File not found")
    else:
        folder_role = await get_folder_role(db, folder, current_user.id)
        require_role(folder_role, PermissionRole.EDITOR, "Folder not found")

    return resolved_folder_id, charge_owner_id, existing_file


async def _finish_upload(
    db: AsyncSession,
    current_user: User,
    charge_owner_id: uuid.UUID,
    folder_id: Optional[uuid.UUID],
    filename: str,
    existing_file: Optional[FileModel],
    staged_path: Path,
    content_hash: str,
    size: int,
) -> FileModel:
    job = FinalizeUploadJob(
        charge_owner_id=charge_owner_id,
        uploader_id=current_user.id,
        existing_file_id=existing_file.id if existing_file else None,
        folder_id=folder_id,
        filename=filename,
        staged_path=staged_path,
        content_hash=content_hash,
        size_bytes=size,
    )
    try:
        result = await submit_finalize_upload(job)
    except QuotaExceededError as e:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(e))

    file_row = await db.get(FileModel, result.file_id)
    await db.refresh(file_row)  # the worker thread wrote this via a separate session -- don't trust any cached copy
    await db.refresh(current_user)  # storage_used_bytes may have changed
    return file_row


# --- single-shot upload (Phase 1, extended) -----------------------------------


@router.post("/upload", response_model=FileOut, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = FastAPIFile(...),
    folder_id: Optional[str] = Form(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file has no filename")

    parsed_folder_id: Optional[uuid.UUID] = None
    if folder_id:
        try:
            parsed_folder_id = uuid.UUID(folder_id)
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "folder_id is not a valid UUID")

    filename = sanitize_filename(file.filename)
    resolved_folder_id, charge_owner_id, existing_file = await _authorize_upload(
        db, current_user, parsed_folder_id, filename
    )

    staged_path, content_hash, size = await _stage_upload(file, max_bytes=settings.SINGLE_SHOT_UPLOAD_MAX_BYTES)

    return await _finish_upload(
        db, current_user, charge_owner_id, resolved_folder_id, filename, existing_file, staged_path, content_hash, size
    )


# --- chunked upload ------------------------------------------------------------


@router.post("/upload/init", response_model=ChunkedUploadInitOut, status_code=status.HTTP_201_CREATED)
async def init_chunked_upload(
    payload: ChunkedUploadInitRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    filename = sanitize_filename(payload.filename)
    # Fails fast (before the client sends a single byte) if the caller can't
    # actually upload here -- re-checked again at /complete in case
    # permissions changed mid-upload.
    await _authorize_upload(db, current_user, payload.folder_id, filename)

    meta = create_upload_session(current_user.id, filename, payload.folder_id, payload.total_size, payload.chunk_count)
    return ChunkedUploadInitOut(upload_id=meta.upload_id, chunk_size_hint_bytes=settings.UPLOAD_CHUNK_SIZE_HINT_BYTES)


@router.post("/upload/{upload_id}/chunk/{chunk_index}", response_model=ChunkAckOut)
async def upload_chunk(
    upload_id: str,
    chunk_index: int,
    chunk: UploadFile = FastAPIFile(...),
    current_user: User = Depends(get_current_user),
):
    meta = load_upload_session(upload_id)
    if meta is None or meta.owner_id != str(current_user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload session not found")
    if not (0 <= chunk_index < meta.chunk_count):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "chunk_index out of range for this upload")

    part_path = chunk_part_path(upload_id, chunk_index)
    part_path.parent.mkdir(parents=True, exist_ok=True)
    with open(part_path, "wb") as f:
        while True:
            data = await chunk.read(CHUNK_SIZE)
            if not data:
                break
            f.write(data)

    received = received_chunk_indices(upload_id)
    return ChunkAckOut(
        upload_id=upload_id, chunk_index=chunk_index, received_chunks=len(received), total_chunks=meta.chunk_count
    )


@router.post("/upload/{upload_id}/complete", response_model=FileOut, status_code=status.HTTP_201_CREATED)
async def complete_chunked_upload(
    upload_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    meta = load_upload_session(upload_id)
    if meta is None or meta.owner_id != str(current_user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload session not found")

    expected = set(range(meta.chunk_count))
    received = received_chunk_indices(upload_id)
    if received != expected:
        missing = sorted(expected - received)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Missing chunk(s): {missing}")

    folder_id = uuid.UUID(meta.folder_id) if meta.folder_id else None
    resolved_folder_id, charge_owner_id, existing_file = await _authorize_upload(
        db, current_user, folder_id, meta.filename
    )

    # Reassemble in order into one staged file, hashing the reassembled
    # bytes exactly as the single-shot path hashes a streamed body -- the
    # dedup/versioning code downstream can't tell the two flows apart.
    staged_path = new_staging_path()
    hasher = hashlib.sha256()
    size = 0
    with open(staged_path, "wb") as out:
        for i in range(meta.chunk_count):
            data = chunk_part_path(upload_id, i).read_bytes()
            out.write(data)
            hasher.update(data)
            size += len(data)
    discard_upload_session(upload_id)

    return await _finish_upload(
        db,
        current_user,
        charge_owner_id,
        resolved_folder_id,
        meta.filename,
        existing_file,
        staged_path,
        hasher.hexdigest(),
        size,
    )


# --- metadata / download / delete ---------------------------------------------


@router.get("/{file_id}", response_model=FileOut)
async def get_file_metadata(
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_accessible_file(db, file_id, current_user.id, PermissionRole.VIEWER)


@router.get("/{file_id}/download")
async def download_file(
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    file_row = await get_accessible_file(db, file_id, current_user.id, PermissionRole.VIEWER)
    path = Path(file_row.storage_path)
    if not path.exists():
        raise HTTPException(status.HTTP_410_GONE, "File metadata exists but the data is missing from storage")
    filename = file_row.filename
    log_activity(db, file_row.id, current_user.id, activity_log.DOWNLOADED)
    await touch_last_accessed(db, file_row.id)  # Phase 3: feeds the stale-file review
    return FileResponse(path, filename=filename, media_type="application/octet-stream")


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Phase 2: soft-delete into the recycle bin (see routers/recycle_bin.py)
    instead of Phase 1's hard delete. Deliberately does NOT touch
    storage_used_bytes or any blob's ref_count -- a soft-deleted file is
    still "yours" and still recoverable, so it still counts against your
    quota until it's actually purged (a Phase 3 scheduled job, per the
    project's phase plan) or restored."""
    file_row = await get_accessible_file(db, file_id, current_user.id, PermissionRole.OWNER)
    now = datetime.now(timezone.utc)
    file_row.is_deleted = True
    file_row.deleted_at = now
    file_row.purge_at = now + timedelta(days=settings.RECYCLE_BIN_RETENTION_DAYS)
    log_activity(db, file_row.id, current_user.id, activity_log.DELETED, "Moved to the recycle bin")
    await db.commit()
    return None


# --- versioning ------------------------------------------------------------------


@router.get("/{file_id}/versions", response_model=list[FileVersionOut])
async def list_versions(
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    file_row = await get_accessible_file(db, file_id, current_user.id, PermissionRole.VIEWER)
    versions = (
        await db.execute(
            select(FileVersion).where(FileVersion.file_id == file_row.id).order_by(FileVersion.version_number.desc())
        )
    ).scalars().all()
    return versions


@router.post("/{file_id}/versions/{version_id}/restore", response_model=FileOut)
async def restore_version(
    file_id: uuid.UUID,
    version_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    file_row = await get_accessible_file(db, file_id, current_user.id, PermissionRole.EDITOR)
    version = await db.get(FileVersion, version_id)
    if version is None or version.file_id != file_row.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found")

    blob = (
        await db.execute(select(Blob).where(Blob.content_hash == version.content_hash))
    ).scalar_one_or_none()

    # Repoints the "current version" columns only -- restoring never deletes
    # or duplicates any file_versions row, and (since the hash was already
    # counted against this file's owner when the version was first created)
    # never changes storage_used_bytes either.
    file_row.content_hash = version.content_hash
    file_row.storage_path = version.storage_path
    file_row.size_bytes = version.size_bytes
    file_row.blob_id = blob.id if blob else None
    log_activity(db, file_row.id, current_user.id, activity_log.VERSION_RESTORED, f"Version {version.version_number} made current")
    await db.commit()
    await db.refresh(file_row)
    return file_row


# --- Phase 3: activity log -------------------------------------------------------


@router.get("/{file_id}/activity", response_model=list[FileActivityOut])
async def file_activity(
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Owner only, same as listing permissions: the log says who opened the
    file and when, which is the owner's business, not every viewer's."""
    file_row = await get_accessible_file(db, file_id, current_user.id, PermissionRole.OWNER)
    return await activity_log.fetch_activity(db, FileActivity.file_id == file_row.id)


# --- sharing: permissions --------------------------------------------------------


def _permission_out(perm: Permission, grantee: User) -> PermissionOut:
    return PermissionOut(
        id=perm.id,
        file_id=perm.file_id,
        folder_id=perm.folder_id,
        user_id=perm.user_id,
        user_email=grantee.email,
        username=grantee.username,
        role=perm.role.value,
        granted_by=perm.granted_by,
        granted_at=perm.granted_at,
    )


@router.get("/{file_id}/permissions", response_model=list[PermissionOut])
async def list_permissions(
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    file_row = await get_accessible_file(db, file_id, current_user.id, PermissionRole.OWNER)
    rows = (
        await db.execute(
            select(Permission, User).join(User, User.id == Permission.user_id).where(Permission.file_id == file_row.id)
        )
    ).all()
    return [_permission_out(perm, grantee) for perm, grantee in rows]


@router.post("/{file_id}/permissions", response_model=PermissionOut, status_code=status.HTTP_201_CREATED)
async def grant_permission(
    file_id: uuid.UUID,
    payload: PermissionGrantRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    file_row = await get_accessible_file(db, file_id, current_user.id, PermissionRole.OWNER)

    grantee = (
        await db.execute(select(User).where((User.email == payload.identifier) | (User.username == payload.identifier)))
    ).scalar_one_or_none()
    if grantee is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No user found with that email or username")
    if grantee.id == current_user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You already own this file")

    existing = (
        await db.execute(select(Permission).where(Permission.file_id == file_row.id, Permission.user_id == grantee.id))
    ).scalar_one_or_none()
    role = PermissionRole(payload.role)
    if existing is not None:
        existing.role = role
        existing.granted_by = current_user.id
        perm = existing
        detail = f"{grantee.username}'s access changed to {role.value}"
    else:
        perm = Permission(file_id=file_row.id, user_id=grantee.id, role=role, granted_by=current_user.id)
        db.add(perm)
        detail = f"{grantee.username} given {role.value} access"
    log_activity(db, file_row.id, current_user.id, activity_log.PERMISSION_GRANTED, detail)
    await db.commit()
    await db.refresh(perm)
    return _permission_out(perm, grantee)


# --- sharing: public links --------------------------------------------------------


@router.post("/{file_id}/share-link", response_model=ShareLinkOut, status_code=status.HTTP_201_CREATED)
async def create_share_link(
    file_id: uuid.UUID,
    payload: ShareLinkCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    file_row = await get_accessible_file(db, file_id, current_user.id, PermissionRole.OWNER)
    link = SharedLink(
        file_id=file_row.id,
        token=secrets.token_urlsafe(32),
        role=ShareRole(payload.role),
        expires_at=payload.expires_at,
        max_access_count=payload.max_access_count,
        created_by=current_user.id,
    )
    db.add(link)
    limits = []
    if payload.expires_at:
        limits.append(f"expires {payload.expires_at:%Y-%m-%d}")
    if payload.max_access_count:
        limits.append(f"max {payload.max_access_count} use{'' if payload.max_access_count == 1 else 's'}")
    log_activity(
        db,
        file_row.id,
        current_user.id,
        activity_log.LINK_CREATED,
        f"Public {payload.role} link" + (f" ({', '.join(limits)})" if limits else ""),
    )
    await db.commit()
    await db.refresh(link)
    return ShareLinkOut(
        id=link.id,
        token=link.token,
        url=f"{settings.FRONTEND_URL}/shared/{link.token}",
        role=link.role.value,
        expires_at=link.expires_at,
        max_access_count=link.max_access_count,
        access_count=link.access_count,
        created_at=link.created_at,
    )


@router.get("/{file_id}/share-links", response_model=list[ShareLinkOut])
async def list_share_links(
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    file_row = await get_accessible_file(db, file_id, current_user.id, PermissionRole.OWNER)
    links = (await db.execute(select(SharedLink).where(SharedLink.file_id == file_row.id))).scalars().all()
    return [
        ShareLinkOut(
            id=link.id,
            token=link.token,
            url=f"{settings.FRONTEND_URL}/shared/{link.token}",
            role=link.role.value,
            expires_at=link.expires_at,
            max_access_count=link.max_access_count,
            access_count=link.access_count,
            created_at=link.created_at,
        )
        for link in links
    ]


@router.delete("/{file_id}/share-links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_share_link(
    file_id: uuid.UUID,
    link_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    file_row = await get_accessible_file(db, file_id, current_user.id, PermissionRole.OWNER)
    link = await db.get(SharedLink, link_id)
    if link is None or link.file_id != file_row.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Share link not found")
    await db.delete(link)
    log_activity(db, file_row.id, current_user.id, activity_log.LINK_REVOKED, f"Public {link.role.value} link revoked")
    await db.commit()
    return None
