"""Live text editing for files shared with editor permissions."""
import hashlib
import asyncio
import uuid
from pathlib import Path
from typing import Dict, Set

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal, get_db
from app.deps import get_current_user
from app.models import File, PermissionRole, User
from app.ownership import get_accessible_file
from app.permissions import get_file_role
from app.routers.files import _finish_upload
from app.storage import new_staging_path

router = APIRouter(prefix="/files", tags=["collaboration"])
_rooms: Dict[str, Set[WebSocket]] = {}
_room_lock = asyncio.Lock()
_save_locks: Dict[uuid.UUID, asyncio.Lock] = {}


class DocumentSave(BaseModel):
    content: str = Field(max_length=2_000_000)
    base_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


def _is_text_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in {
        ".txt", ".md", ".markdown", ".csv", ".json", ".xml", ".html", ".htm",
        ".css", ".js", ".jsx", ".ts", ".tsx", ".py", ".java", ".c", ".h",
        ".cpp", ".yaml", ".yml", ".toml", ".ini", ".log", ".sql", ".sh",
    }


@router.get("/{file_id}/document")
async def read_document(file_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await get_accessible_file(db, file_id, current_user.id, PermissionRole.VIEWER)
    if not _is_text_file(row.filename):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Live editing is available for text files")
    try:
        content = Path(row.storage_path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "This file is not valid UTF-8 text")
    except OSError:
        raise HTTPException(status.HTTP_410_GONE, "File data is missing from storage")
    return {"content": content, "content_hash": row.content_hash, "filename": row.filename}


@router.put("/{file_id}/document")
async def save_document(file_id: uuid.UUID, payload: DocumentSave, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    lock = _save_locks.setdefault(file_id, asyncio.Lock())
    async with lock:
        # Check the base hash after acquiring the per-file lock so concurrent
        # saves cannot both pass against the same old version.
        row = await get_accessible_file(db, file_id, current_user.id, PermissionRole.EDITOR)
        if not _is_text_file(row.filename):
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Live editing is available for text files")
        if row.content_hash != payload.base_hash:
            raise HTTPException(status.HTTP_409_CONFLICT, "This document changed since your last save. Reload the latest version before saving.")
        content = payload.content.encode("utf-8")
        staged = new_staging_path()
        staged.write_bytes(content)
        try:
            # The existing upload finalizer keeps quota, deduplication, audit, and
            # version history consistent with ordinary uploads.
            row = await _finish_upload(db, current_user, row.owner_id, row.folder_id, row.filename, row, staged,
                                       hashlib.sha256(content).hexdigest(), len(content))
        except Exception:
            staged.unlink(missing_ok=True)
            raise
    await broadcast(str(file_id), {"type": "saved", "content": payload.content, "content_hash": row.content_hash,
                                  "username": current_user.username})
    return {"content_hash": row.content_hash, "updated_at": row.updated_at}


async def broadcast(file_id: str, message: dict):
    async with _room_lock:
        sockets = list(_rooms.get(file_id, set()))
    dead = []
    for socket in sockets:
        try:
            await socket.send_json(message)
        except Exception:
            dead.append(socket)
    if dead:
        async with _room_lock:
            _rooms.get(file_id, set()).difference_update(dead)


@router.websocket("/{file_id}/collaboration")
async def collaboration_socket(websocket: WebSocket, file_id: uuid.UUID, token: str = Query(...)):
    try:
        claims = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        user_id = uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    username = "Collaborator"
    try:
        async with AsyncSessionLocal() as db:
            user = await db.get(User, user_id)
            if user is None:
                await websocket.close(code=4401)
                return
            row = await get_accessible_file(db, file_id, user_id, PermissionRole.VIEWER)
            if not _is_text_file(row.filename):
                await websocket.close(code=4400)
                return
            username = user.username
            role = await get_file_role(db, row, user_id)
            await websocket.send_json({"type": "presence", "username": username, "can_edit": role in (PermissionRole.EDITOR, PermissionRole.OWNER)})
        key = str(file_id)
        async with _room_lock:
            _rooms.setdefault(key, set()).add(websocket)
        await broadcast(key, {"type": "presence", "username": username, "online": True})
        while True:
            # Client messages are reserved for presence pings; document saves
            # go through the authenticated, versioned HTTP endpoint.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except HTTPException:
        await websocket.close(code=4404)
    finally:
        async with _room_lock:
            members = _rooms.get(str(file_id), set())
            members.discard(websocket)
            if not members:
                _rooms.pop(str(file_id), None)
        await broadcast(str(file_id), {"type": "presence", "username": username, "online": False})
