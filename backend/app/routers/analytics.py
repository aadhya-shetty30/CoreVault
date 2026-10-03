"""
Phase 3: storage dashboard + stale-file review.

GET  /analytics/storage                   -- everything the dashboard page draws
GET  /analytics/stale-files               -- files offered in the "delete it?" prompt
POST /analytics/stale-files/{id}/keep     -- "keep it": snooze that prompt for this file
GET  /analytics/activity                  -- recent activity across all of the caller's files
GET  /analytics/forecast                  -- usage history + when the quota will run out

Scoped strictly to files the caller OWNS (owner_id == current_user.id),
same as the recycle bin -- those are exactly the files whose bytes count
against the caller's quota, so it's the only set a storage breakdown or a
"free up space" prompt makes sense for.

Deleting a stale file deliberately has no endpoint of its own here: the
frontend calls the existing DELETE /files/{id}, so a file removed from the
prompt lands in the recycle bin and is restorable exactly like any other
delete.

A file is "stale" when NEITHER its last read (files.last_accessed_at,
stamped by app/file_activity.py on every download) NOR its last write
(files.updated_at -- a new version, a restore) is newer than
STALE_FILE_DAYS, and the owner hasn't snoozed it. Files uploaded before
migration 0003 have last_accessed_at NULL, which just means "judge by
updated_at alone".
"""
import math
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import PurePath
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import activity_log
from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.file_activity import snooze_stale_prompt
from app.models import File, FileVersion, Folder, User
from app.schemas import (
    FileActivityOut,
    ForecastPointOut,
    LargestFileOut,
    StaleFileOut,
    StorageAnalyticsOut,
    StorageCategoryOut,
    StorageForecastOut,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])

# Projections further out than this are reported as "not within the horizon".
_FORECAST_HORIZON_DAYS = 100 * 365

# Extension -> dashboard category. Anything unlisted (or extensionless) is
# "Other". The frontend assigns each category a fixed color, so a category
# keeps its color whether or not the others are present.
_CATEGORY_EXTENSIONS: dict[str, set[str]] = {
    "Images": {"jpg", "jpeg", "png", "gif", "bmp", "webp", "svg", "heic", "heif", "tif", "tiff", "ico", "raw"},
    "Videos": {"mp4", "mkv", "mov", "avi", "webm", "wmv", "flv", "m4v", "3gp"},
    "Audio": {"mp3", "wav", "flac", "aac", "ogg", "m4a", "wma", "opus"},
    "Documents": {
        "pdf", "doc", "docx", "txt", "md", "rtf", "odt", "xls", "xlsx", "csv", "ods",
        "ppt", "pptx", "odp", "epub", "tex",
    },
    "Archives": {"zip", "rar", "7z", "tar", "gz", "bz2", "xz", "tgz", "iso", "dmg"},
    "Code": {
        "py", "js", "jsx", "ts", "tsx", "java", "c", "cpp", "h", "hpp", "cs", "go", "rs", "rb",
        "php", "html", "css", "json", "xml", "yml", "yaml", "sql", "sh", "ipynb", "kt", "swift",
    },
}
_EXTENSION_TO_CATEGORY = {ext: cat for cat, exts in _CATEGORY_EXTENSIONS.items() for ext in exts}


def categorize(filename: str) -> str:
    suffix = PurePath(filename).suffix.lower().lstrip(".")
    return _EXTENSION_TO_CATEGORY.get(suffix, "Other")


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    # Same defensive coercion as routers/recycle_bin.py: timestamptz comes
    # back tz-aware from Postgres, but never let a naive value crash a
    # comparison.
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _last_activity(file_row: File) -> datetime:
    updated = _aware(file_row.updated_at)
    accessed = _aware(file_row.last_accessed_at)
    return max(updated, accessed) if accessed else updated


def _stale_filter(owner_id: uuid.UUID, now: datetime):
    """SQL-side version of the staleness rule in the module docstring."""
    cutoff = now - timedelta(days=settings.STALE_FILE_DAYS)
    return (
        File.owner_id == owner_id,
        File.is_deleted == False,  # noqa: E712
        File.updated_at < cutoff,
        or_(File.last_accessed_at.is_(None), File.last_accessed_at < cutoff),
        or_(File.stale_prompt_snoozed_until.is_(None), File.stale_prompt_snoozed_until < now),
    )


async def _folder_paths(db: AsyncSession, owner_id: uuid.UUID) -> dict[Optional[uuid.UUID], str]:
    """Maps each of the owner's folder ids (and None, for root) to a
    human-readable "My files / A / B" path. One query for the whole tree
    instead of walking parents per file."""
    rows = (
        await db.execute(select(Folder.id, Folder.name, Folder.parent_folder_id).where(Folder.owner_id == owner_id))
    ).all()
    by_id = {fid: (name, parent) for fid, name, parent in rows}
    cache: dict[Optional[uuid.UUID], str] = {None: "My files"}

    def resolve(fid: Optional[uuid.UUID], depth: int = 0) -> str:
        if fid in cache:
            return cache[fid]
        if fid not in by_id or depth > 256:  # depth guard: never loop on bad data
            return "My files"
        name, parent = by_id[fid]
        cache[fid] = f"{resolve(parent, depth + 1)} / {name}"
        return cache[fid]

    for fid in by_id:
        resolve(fid)
    return cache


@router.get("/storage", response_model=StorageAnalyticsOut)
async def storage_analytics(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(days=settings.STALE_FILE_DAYS)

    files = (await db.execute(select(File).where(File.owner_id == current_user.id))).scalars().all()
    active = [f for f in files if not f.is_deleted]
    recycled = [f for f in files if f.is_deleted]

    by_category: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # category -> [count, bytes]
    stale_count = 0
    for f in active:
        bucket = by_category[categorize(f.filename)]
        bucket[0] += 1
        bucket[1] += f.size_bytes
        snoozed = _aware(f.stale_prompt_snoozed_until)
        if _last_activity(f) < stale_cutoff and (snoozed is None or snoozed < now):
            stale_count += 1

    # Every version of every file the caller owns, recycled ones included --
    # that's what storage would cost if every version were stored separately.
    version_rows = (
        await db.execute(
            select(FileVersion.file_id, func.sum(FileVersion.size_bytes))
            .join(File, File.id == FileVersion.file_id)
            .where(File.owner_id == current_user.id)
            .group_by(FileVersion.file_id)
        )
    ).all()
    version_bytes = {fid: int(total or 0) for fid, total in version_rows}
    all_versions_bytes = sum(version_bytes.values())
    old_versions_bytes = sum(max(0, version_bytes.get(f.id, f.size_bytes) - f.size_bytes) for f in active)

    folder_paths = await _folder_paths(db, current_user.id)
    largest = sorted(active, key=lambda f: f.size_bytes, reverse=True)[: settings.ANALYTICS_TOP_FILES]

    return StorageAnalyticsOut(
        storage_used_bytes=current_user.storage_used_bytes,
        storage_quota_bytes=current_user.storage_quota_bytes,
        file_count=len(active),
        active_bytes=sum(f.size_bytes for f in active),
        recycle_bin_bytes=sum(f.size_bytes for f in recycled),
        recycle_bin_count=len(recycled),
        old_versions_bytes=old_versions_bytes,
        dedup_saved_bytes=max(0, all_versions_bytes - current_user.storage_used_bytes),
        stale_file_count=stale_count,
        stale_after_days=settings.STALE_FILE_DAYS,
        by_category=sorted(
            (StorageCategoryOut(category=c, file_count=n, total_bytes=b) for c, (n, b) in by_category.items()),
            key=lambda c: c.total_bytes,
            reverse=True,
        ),
        largest_files=[
            LargestFileOut(
                id=f.id,
                filename=f.filename,
                size_bytes=f.size_bytes,
                category=categorize(f.filename),
                folder_id=f.folder_id,
                folder_path=folder_paths.get(f.folder_id, "My files"),
                updated_at=f.updated_at,
            )
            for f in largest
        ],
    )


@router.get("/stale-files", response_model=list[StaleFileOut])
async def list_stale_files(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(select(File).where(*_stale_filter(current_user.id, now)).order_by(File.size_bytes.desc()))
    ).scalars().all()
    folder_paths = await _folder_paths(db, current_user.id)
    out = []
    for f in rows:
        last = _last_activity(f)
        out.append(
            StaleFileOut(
                id=f.id,
                filename=f.filename,
                size_bytes=f.size_bytes,
                folder_id=f.folder_id,
                folder_path=folder_paths.get(f.folder_id, "My files"),
                last_activity_at=last,
                days_idle=max(0, (now - last).days),
            )
        )
    return out


@router.post("/stale-files/{file_id}/keep", status_code=status.HTTP_204_NO_CONTENT)
async def keep_stale_file(
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    file_row = await db.get(File, file_id)
    if file_row is None or file_row.owner_id != current_user.id or file_row.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    until = datetime.now(timezone.utc) + timedelta(days=settings.STALE_PROMPT_SNOOZE_DAYS)
    activity_log.log_activity(db, file_row.id, current_user.id, activity_log.KEPT, "Kept when asked about unused files")
    await snooze_stale_prompt(db, file_row.id, until)  # commits the log row too
    return None


@router.get("/activity", response_model=list[FileActivityOut])
async def recent_activity(
    limit: int = Query(default=20, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Latest events on any file the caller owns (recycled ones included),
    whoever performed them -- so the owner sees collaborators' uploads and
    anonymous link downloads here too."""
    return await activity_log.fetch_activity(db, File.owner_id == current_user.id, limit=limit)


def build_forecast(user: User, versions) -> StorageForecastOut:
    """Pure forecast calculation, shared by GET /analytics/forecast (a user's
    own) and the admin overview (routers/admin.py, every user's).
    `versions` is that user's (content_hash, size_bytes, modified_at) rows,
    oldest first.

    Reconstructs the user's daily storage_used_bytes over the last
    FORECAST_WINDOW_DAYS from their version history, fits a least-squares
    line through it, and extrapolates to the quota.

    Reconstruction mirrors the charging rule in app/workers.py: a version
    only adds to usage the FIRST time this user owns its content hash. The
    series is anchored to today's real storage_used_bytes and walked
    backwards (usage on day d = today's usage minus everything charged after
    d), so it always ends at the true current number even though past
    hard-deletes aren't in the version history."""
    today = datetime.now(timezone.utc).date()
    used = user.storage_used_bytes
    quota = user.storage_quota_bytes

    seen: set[str] = set()
    charged_per_day: dict[date, int] = defaultdict(int)
    for content_hash, size_bytes, modified_at in versions:
        if content_hash in seen:
            continue
        seen.add(content_hash)
        charged_per_day[_aware(modified_at).date()] += size_bytes

    created = _aware(user.created_at).date() if user.created_at else today
    start = max(today - timedelta(days=settings.FORECAST_WINDOW_DAYS - 1), min(created, today))
    days = [start + timedelta(days=i) for i in range((today - start).days + 1)]

    charged_after = sum(b for d, b in charged_per_day.items() if d > today)  # clock-skew guard
    history: list[ForecastPointOut] = []
    for d in reversed(days):
        history.append(ForecastPointOut(date=d, used_bytes=max(0, used - charged_after)))
        charged_after += charged_per_day.get(d, 0)
    history.reverse()

    def result(status_: str, rate: Optional[float] = None, days_left: Optional[int] = None) -> StorageForecastOut:
        return StorageForecastOut(
            storage_used_bytes=used,
            storage_quota_bytes=quota,
            window_days=settings.FORECAST_WINDOW_DAYS,
            status=status_,
            growth_bytes_per_day=rate,
            days_until_full=days_left,
            projected_full_date=today + timedelta(days=days_left) if days_left is not None else None,
            history=history,
        )

    if not any(charged_per_day.get(d) for d in days):
        return result("flat", 0.0)
    # Fewer than 3 days of history means one upload day would set the whole
    # slope -- say so rather than extrapolate from a single burst.
    if len(history) < 3:
        return result("insufficient_data")

    n = len(history)
    mean_x = (n - 1) / 2
    mean_y = sum(p.used_bytes for p in history) / n
    var_x = sum((x - mean_x) ** 2 for x in range(n))
    slope = sum((x - mean_x) * (p.used_bytes - mean_y) for x, p in enumerate(history)) / var_x

    if slope <= 0:
        return result("flat", 0.0)
    days_left = 0 if used >= quota else math.ceil((quota - used) / slope)
    # A trickle of bytes against a GB quota can project past year 9999
    # (date overflow) -- anything beyond the horizon is reported as None.
    if days_left > _FORECAST_HORIZON_DAYS:
        return result("growing", slope)
    return result("growing", slope, days_left)


@router.get("/forecast", response_model=StorageForecastOut)
async def storage_forecast(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The caller's own storage forecast -- see build_forecast."""
    versions = (
        await db.execute(
            select(FileVersion.content_hash, FileVersion.size_bytes, FileVersion.modified_at)
            .join(File, File.id == FileVersion.file_id)
            .where(File.owner_id == current_user.id)
            .order_by(FileVersion.modified_at)
        )
    ).all()
    return build_forecast(current_user, versions)
