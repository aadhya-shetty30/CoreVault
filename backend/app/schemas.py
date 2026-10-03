"""
Pydantic request/response models.

`from_attributes=True` lets these be built directly from SQLAlchemy ORM
rows -- FastAPI's response_model machinery does this automatically on every
route below that returns an ORM instance instead of a dict.
"""
import uuid
from datetime import date as date_type, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    username: str
    storage_used_bytes: int
    storage_quota_bytes: int
    otp_enabled: bool
    is_admin: bool = False
    created_at: datetime


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginResponse(BaseModel):
    """Response of POST /auth/login. Exactly one of (access_token) or
    (pending_token) is populated, selected by `requires_2fa`."""

    requires_2fa: bool = False
    access_token: Optional[str] = None
    pending_token: Optional[str] = None
    token_type: str = "bearer"


class TwoFactorSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class TwoFactorVerifySetupRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class TwoFactorVerifyRequest(BaseModel):
    pending_token: str
    code: str = Field(min_length=6, max_length=6)


class FolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    parent_folder_id: Optional[uuid.UUID] = None


class FolderUpdate(BaseModel):
    """Both fields are optional and independently settable. We check
    `model_fields_set` in the route (not just "is it None") so that a PATCH
    can distinguish "don't touch parent_folder_id" (field omitted) from
    "move to root" (field present with value null)."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    parent_folder_id: Optional[uuid.UUID] = None


class FolderChildOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: datetime


class FileChildOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    size_bytes: int
    content_hash: str
    created_at: datetime
    updated_at: datetime


class BreadcrumbItem(BaseModel):
    id: Optional[uuid.UUID]
    name: str


class FolderDetailOut(BaseModel):
    id: Optional[uuid.UUID]
    name: str
    breadcrumb: list[BreadcrumbItem]
    folders: list[FolderChildOut]
    files: list[FileChildOut]


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    folder_id: Optional[uuid.UUID]
    filename: str
    size_bytes: int
    content_hash: str
    is_deleted: bool
    created_at: datetime
    updated_at: datetime


class DiskUsageOut(BaseModel):
    total_bytes: int
    used_bytes: int
    free_bytes: int


# --- Phase 2: versioning -----------------------------------------------------


class FileVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_number: int
    content_hash: str
    size_bytes: int
    modified_by: Optional[uuid.UUID]
    modified_at: datetime


# --- Phase 2: recycle bin ------------------------------------------------------


class RecycleBinItemOut(BaseModel):
    id: uuid.UUID
    filename: str
    size_bytes: int
    folder_id: Optional[uuid.UUID]
    deleted_at: datetime
    purge_at: datetime
    days_remaining: int


# --- Phase 2: chunked upload --------------------------------------------------


class ChunkedUploadInitRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=500)
    total_size: int = Field(gt=0)
    chunk_count: int = Field(gt=0)
    folder_id: Optional[uuid.UUID] = None


class ChunkedUploadInitOut(BaseModel):
    upload_id: str
    chunk_size_hint_bytes: int


class ChunkAckOut(BaseModel):
    upload_id: str
    chunk_index: int
    received_chunks: int
    total_chunks: int


# --- Phase 2: permissions & sharing -------------------------------------------


class PermissionGrantRequest(BaseModel):
    identifier: str = Field(min_length=1, description="Grantee's email or username")
    role: str = Field(pattern="^(editor|viewer)$")


class PermissionOut(BaseModel):
    id: uuid.UUID
    file_id: Optional[uuid.UUID]
    folder_id: Optional[uuid.UUID]
    user_id: uuid.UUID
    user_email: str
    username: str
    role: str
    granted_by: Optional[uuid.UUID]
    granted_at: datetime


class ShareLinkCreateRequest(BaseModel):
    role: str = Field(pattern="^(editor|viewer)$")
    expires_at: Optional[datetime] = None
    max_access_count: Optional[int] = Field(default=None, ge=1)


class ShareLinkOut(BaseModel):
    id: uuid.UUID
    token: str
    url: str
    role: str
    expires_at: Optional[datetime]
    max_access_count: Optional[int]
    access_count: int
    created_at: datetime


class SharedLinkInfoOut(BaseModel):
    filename: str
    size_bytes: int
    role: str
    valid: bool
    reason: Optional[str] = None


# --- Phase 3: storage dashboard / stale-file review ---------------------------


class StorageCategoryOut(BaseModel):
    category: str
    file_count: int
    total_bytes: int


class LargestFileOut(BaseModel):
    id: uuid.UUID
    filename: str
    size_bytes: int
    category: str
    folder_id: Optional[uuid.UUID]
    folder_path: str
    updated_at: datetime


class StorageAnalyticsOut(BaseModel):
    storage_used_bytes: int
    storage_quota_bytes: int
    file_count: int
    # Sum of the CURRENT version of every live (not recycled) file.
    active_bytes: int
    recycle_bin_bytes: int
    recycle_bin_count: int
    # Bytes held by non-current versions of live files.
    old_versions_bytes: int
    # What storage would cost without dedup, minus what's actually charged.
    dedup_saved_bytes: int
    stale_file_count: int
    stale_after_days: int
    by_category: list[StorageCategoryOut]
    largest_files: list[LargestFileOut]


class StaleFileOut(BaseModel):
    id: uuid.UUID
    filename: str
    size_bytes: int
    folder_id: Optional[uuid.UUID]
    folder_path: str
    last_activity_at: datetime
    days_idle: int


class FileActivityOut(BaseModel):
    id: uuid.UUID
    file_id: uuid.UUID
    filename: str
    action: str
    detail: Optional[str]
    actor_id: Optional[uuid.UUID]
    # None for anonymous share-link downloads (and since-deleted users).
    actor_username: Optional[str]
    created_at: datetime


class ForecastPointOut(BaseModel):
    date: date_type
    used_bytes: int


class StorageForecastOut(BaseModel):
    storage_used_bytes: int
    storage_quota_bytes: int
    window_days: int
    # "growing" | "flat" | "insufficient_data"
    status: str
    growth_bytes_per_day: Optional[float]
    # None when not growing, or growing too slowly to fill up within 100 years.
    days_until_full: Optional[int]
    projected_full_date: Optional[date_type]
    history: list[ForecastPointOut]


# --- Phase 3: admin overview ---------------------------------------------------
# Deliberately storage-only: nothing here identifies or describes any file.


class AdminUserStorageOut(BaseModel):
    id: uuid.UUID
    username: str
    email: str
    created_at: datetime
    is_admin: bool
    storage_used_bytes: int
    storage_quota_bytes: int
    storage_left_bytes: int
    # From the same calculation as the user's own dashboard forecast.
    forecast_status: str
    growth_bytes_per_day: Optional[float]
    days_until_full: Optional[int]
    projected_full_date: Optional[date_type]


class AdminOverviewOut(BaseModel):
    user_count: int
    total_used_bytes: int
    total_quota_bytes: int
    users: list[AdminUserStorageOut]
