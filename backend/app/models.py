"""
SQLAlchemy ORM models: Phase 1's three tables (users/folders/files) plus
Phase 2's additions (2FA columns on users; deleted_at/purge_at/blob_id on
files; the new blobs/file_versions/permissions/shared_links tables) -- see
alembic/versions/0002_phase2.py for the migration that added them. Phase 3
adds the stale-file columns on files (0003) and the file_activity table (0004).

Per the project's phase plan, later phases should only ever ADD
columns/tables via new Alembic migrations, never restructure what's here.
"""
import enum
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class PermissionRole(str, enum.Enum):
    """Role granted on a file or folder via the `permissions` table.
    Ordered weakest -> strongest; app/permissions.py ranks these to answer
    "does this user have at least role X" checks."""

    VIEWER = "viewer"
    EDITOR = "editor"
    OWNER = "owner"


class ShareRole(str, enum.Enum):
    """Role attached to a public `shared_links` token. Deliberately excludes
    OWNER -- a link can never grant ownership (granting/revoking permissions,
    deleting the file), only read or edit access."""

    VIEWER = "viewer"
    EDITOR = "editor"


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    # Tracked since Phase 1; enforced since Phase 2 -- see the quota check
    # (and its threading.Lock) in app/workers.py's finalize_upload.
    storage_used_bytes = Column(BigInteger, nullable=False, default=0)
    storage_quota_bytes = Column(BigInteger, nullable=False, default=5 * 1024 * 1024 * 1024)
    failed_login_attempts = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # --- Phase 2: OTP-based 2FA ---
    # otp_secret is written by POST /auth/2fa/setup but otp_enabled only
    # flips true once POST /auth/2fa/verify-setup confirms the user actually
    # has it loaded into an authenticator app (see routers/auth.py).
    otp_secret = Column(String(64), nullable=True)
    otp_enabled = Column(Boolean, nullable=False, default=False)
    # --- Phase 3: admin overview (migration 0005) ---
    # Grants ONLY the /admin storage overview (routers/admin.py) -- usage
    # totals and forecasts, never anyone's files. Set via
    # scripts/make_admin.py; no API endpoint can change it.
    is_admin = Column(Boolean, nullable=False, default=False)


class Folder(Base):
    __tablename__ = "folders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # ondelete="CASCADE" here is a DB-level safety net (e.g. for a future
    # "delete my account" feature). Phase 1's DELETE /folders/{id} does NOT
    # rely on this cascade -- it walks the subtree explicitly in app code
    # (routers/folders.py) because only app code can also remove the
    # matching files from disk, which the database can't do for us.
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # Self-referencing FK for the folder tree. NULL = lives at the user's
    # root. Cycle prevention (a folder can't be moved into its own
    # descendant) is enforced in application code -- see _is_descendant()
    # in routers/folders.py -- because a FK constraint has no notion of
    # "ancestor" to check against.
    parent_folder_id = Column(UUID(as_uuid=True), ForeignKey("folders.id", ondelete="CASCADE"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class File(Base):
    __tablename__ = "files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # NULL = file lives at the user's root (not inside any folder).
    folder_id = Column(UUID(as_uuid=True), ForeignKey("folders.id", ondelete="CASCADE"), nullable=True, index=True)
    filename = Column(String(500), nullable=False)
    # These three columns represent the file's CURRENT version as of Phase 2
    # (mirrored from file_versions/blobs on every upload/restore) -- kept as
    # plain columns rather than always joining through file_versions so
    # every Phase-1 route that reads size_bytes/content_hash/storage_path
    # directly off File keeps working unchanged.
    size_bytes = Column(BigInteger, nullable=False)
    content_hash = Column(String(64), nullable=False)  # sha256 hex digest
    storage_path = Column(String(1000), nullable=False)
    # Real soft-delete (hide instead of remove): DELETE /files/{id} now sets
    # is_deleted + deleted_at + purge_at instead of removing the row (see
    # routers/files.py and routers/recycle_bin.py). NULL until soft-deleted.
    is_deleted = Column(Boolean, nullable=False, default=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    purge_at = Column(DateTime(timezone=True), nullable=True)
    # Nullable: Phase 1 rows (and any row created before dedup resolved a
    # blob) have no blob yet. Set together with content_hash/storage_path
    # whenever a version is finalized -- see app/workers.py.
    blob_id = Column(UUID(as_uuid=True), ForeignKey("blobs.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    # --- Phase 3: stale-file review (migration 0003) ---
    # Stamped on every actual read of the bytes (see touch_last_accessed in
    # routers/files.py and routers/shared.py). NULL = never opened since
    # upload; routers/analytics.py falls back to updated_at in that case.
    last_accessed_at = Column(DateTime(timezone=True), nullable=True)
    # Set when the owner answers "keep" to the stale-file prompt; the file
    # isn't offered for deletion again until this passes.
    stale_prompt_snoozed_until = Column(DateTime(timezone=True), nullable=True)


class Blob(Base):
    """Content-addressed storage backing `files`/`file_versions`. One row per
    *unique* SHA-256 seen across the whole system, regardless of how many
    files/users/versions point at it -- see app/workers.py's finalize_upload
    for the check-then-write dedup sequence this table exists to support."""

    __tablename__ = "blobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    content_hash = Column(String(64), unique=True, nullable=False, index=True)
    storage_path = Column(String(1000), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    # Incremented whenever a new file_versions row starts pointing at this
    # blob, decremented when one stops (see app/workers.py's
    # release_blob_ref). The bytes on disk are only unlinked once this hits
    # zero -- never on any single file's delete.
    ref_count = Column(Integer, nullable=False, default=1)


class FileVersion(Base):
    __tablename__ = "file_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id = Column(UUID(as_uuid=True), ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    # content_hash/storage_path are copied from the Blob at the time this
    # version was created. They're denormalized (not just a blob_id FK) so
    # version history stays independently readable/auditable even if a
    # future phase changes how blobs are looked up.
    content_hash = Column(String(64), nullable=False)
    storage_path = Column(String(1000), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    modified_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    modified_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Permission(Base):
    """A role granted to one user on one file OR one folder (never both --
    enforced by the CHECK constraint below). Folder-level grants are
    resolved by walking up the folder tree (see app/permissions.py), so
    granting a role on a folder implicitly covers everything inside it."""

    __tablename__ = "permissions"
    __table_args__ = (
        CheckConstraint(
            "(file_id IS NOT NULL AND folder_id IS NULL) OR (file_id IS NULL AND folder_id IS NOT NULL)",
            name="ck_permissions_exactly_one_target",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id = Column(UUID(as_uuid=True), ForeignKey("files.id", ondelete="CASCADE"), nullable=True, index=True)
    folder_id = Column(UUID(as_uuid=True), ForeignKey("folders.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(Enum(PermissionRole, name="permission_role", native_enum=True), nullable=False)
    granted_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    granted_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SharedLink(Base):
    """A public, unauthenticated download link for one file. `token` is the
    only secret -- anyone holding it gets `role`-level access until it
    expires or `access_count` reaches `max_access_count` (see
    routers/shared.py)."""

    __tablename__ = "shared_links"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id = Column(UUID(as_uuid=True), ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True)
    token = Column(String(64), unique=True, nullable=False, index=True)
    role = Column(Enum(ShareRole, name="share_role", native_enum=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    max_access_count = Column(Integer, nullable=True)
    access_count = Column(Integer, nullable=False, default=0)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class FileActivity(Base):
    """Phase 3 (migration 0004): append-only audit trail for one file --
    uploads, new versions, downloads (including anonymous share-link ones),
    restores, deletes, and sharing changes. Rows are only ever inserted
    (see app/activity_log.py), never updated, and go away with the file via
    the FK cascade."""

    __tablename__ = "file_activity"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id = Column(UUID(as_uuid=True), ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True)
    # NULL = anonymous (public share-link download) or a since-deleted user.
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String(32), nullable=False)
    detail = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
