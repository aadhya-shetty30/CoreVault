"""
Phase 3: admin storage overview -- for the operator to spot accounts that
are about to run out of space (e.g. to offer them more storage).

GET /admin/users                   -- every user's storage used/left + forecast summary
GET /admin/users/{id}/forecast     -- one user's full forecast (daily history), for the chart

Privacy boundary, deliberately narrow: these endpoints return account
identity (username, email, join date) and storage NUMBERS only. They never
return file names, file counts, folder names, sharing info, or any content,
and being an admin grants no access to anyone's files through any other
route either -- every file/folder endpoint still checks ownership/
permissions exactly as before. The forecast itself is computed from version
sizes and timestamps (routers/analytics.build_forecast), which never leave
this module except as the aggregated daily usage curve.
"""
import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_admin
from app.models import File, FileVersion, User
from app.routers.analytics import build_forecast
from app.schemas import AdminOverviewOut, AdminUserStorageOut, StorageForecastOut

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=AdminOverviewOut)
async def admin_users(
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    users = (await db.execute(select(User).order_by(User.created_at))).scalars().all()

    # One query for everyone's version history instead of one per user.
    rows = (
        await db.execute(
            select(File.owner_id, FileVersion.content_hash, FileVersion.size_bytes, FileVersion.modified_at)
            .join(File, File.id == FileVersion.file_id)
            .order_by(FileVersion.modified_at)
        )
    ).all()
    versions_by_owner: dict[uuid.UUID, list] = defaultdict(list)
    for owner_id, content_hash, size_bytes, modified_at in rows:
        versions_by_owner[owner_id].append((content_hash, size_bytes, modified_at))

    out = []
    for u in users:
        f = build_forecast(u, versions_by_owner.get(u.id, []))
        out.append(
            AdminUserStorageOut(
                id=u.id,
                username=u.username,
                email=u.email,
                created_at=u.created_at,
                is_admin=u.is_admin,
                storage_used_bytes=u.storage_used_bytes,
                storage_quota_bytes=u.storage_quota_bytes,
                storage_left_bytes=max(0, u.storage_quota_bytes - u.storage_used_bytes),
                forecast_status=f.status,
                growth_bytes_per_day=f.growth_bytes_per_day,
                days_until_full=f.days_until_full,
                projected_full_date=f.projected_full_date,
            )
        )

    return AdminOverviewOut(
        user_count=len(users),
        total_used_bytes=sum(u.storage_used_bytes for u in users),
        total_quota_bytes=sum(u.storage_quota_bytes for u in users),
        users=out,
    )


@router.get("/users/{user_id}/forecast", response_model=StorageForecastOut)
async def admin_user_forecast(
    user_id: uuid.UUID,
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    versions = (
        await db.execute(
            select(FileVersion.content_hash, FileVersion.size_bytes, FileVersion.modified_at)
            .join(File, File.id == FileVersion.file_id)
            .where(File.owner_id == user.id)
            .order_by(FileVersion.modified_at)
        )
    ).all()
    return build_forecast(user, versions)
