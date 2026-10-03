"""phase 2: versioning, dedup, recycle bin, permissions, sharing, 2FA

Additive only -- every change here is a new table or a new nullable/
defaulted column on top of 0001_initial_schema. Nothing from Phase 1 is
altered or dropped.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-13

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# create_type=False on both: we create/drop these types explicitly and
# exactly once each (via .create()/.drop() with checkfirst=True below).
# Without create_type=False, SQLAlchemy's DDL compiler ALSO tries to create
# (drop) the enum type itself as an implicit side effect of create_table()
# (drop_table()) for any table that has a column of this type -- which,
# since that implicit path isn't checkfirst-protected, collides with our
# already-created type and fails with "type already exists" the moment a
# second table (or, as here, the same upgrade() creating one after
# explicitly creating the type) references it.
permission_role = postgresql.ENUM("viewer", "editor", "owner", name="permission_role", create_type=False)
share_role = postgresql.ENUM("viewer", "editor", name="share_role", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    permission_role.create(bind, checkfirst=True)
    share_role.create(bind, checkfirst=True)

    # --- users: 2FA -----------------------------------------------------------
    op.add_column("users", sa.Column("otp_secret", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("otp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))

    # --- blobs: dedup-backing content store ------------------------------------
    op.create_table(
        "blobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("storage_path", sa.String(1000), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("ref_count", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_blobs_content_hash", "blobs", ["content_hash"], unique=True)

    # --- files: recycle bin + blob pointer --------------------------------------
    op.add_column("files", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("files", sa.Column("purge_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "files",
        sa.Column(
            "blob_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("blobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_files_blob_id", "files", ["blob_id"])

    # --- file_versions ----------------------------------------------------------
    op.create_table(
        "file_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("files.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("storage_path", sa.String(1000), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "modified_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("modified_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_file_versions_file_id", "file_versions", ["file_id"])
    op.create_unique_constraint(
        "uq_file_versions_file_id_version_number", "file_versions", ["file_id", "version_number"]
    )

    # --- permissions --------------------------------------------------------------
    op.create_table(
        "permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "file_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("files.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column(
            "folder_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("folders.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("role", permission_role, nullable=False),
        sa.Column(
            "granted_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "(file_id IS NOT NULL AND folder_id IS NULL) OR (file_id IS NULL AND folder_id IS NOT NULL)",
            name="ck_permissions_exactly_one_target",
        ),
    )
    op.create_index("ix_permissions_file_id", "permissions", ["file_id"])
    op.create_index("ix_permissions_folder_id", "permissions", ["folder_id"])
    op.create_index("ix_permissions_user_id", "permissions", ["user_id"])
    # One role per (target, user) -- granting again just updates it (app code
    # does a get-or-create), it never inserts a duplicate row.
    op.create_unique_constraint(
        "uq_permissions_file_user", "permissions", ["file_id", "user_id"]
    )
    op.create_unique_constraint(
        "uq_permissions_folder_user", "permissions", ["folder_id", "user_id"]
    )

    # --- shared_links ---------------------------------------------------------------
    op.create_table(
        "shared_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "file_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("files.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("role", share_role, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_access_count", sa.Integer(), nullable=True),
        sa.Column("access_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_shared_links_file_id", "shared_links", ["file_id"])
    op.create_index("ix_shared_links_token", "shared_links", ["token"], unique=True)


def downgrade() -> None:
    op.drop_table("shared_links")

    op.drop_constraint("uq_permissions_folder_user", "permissions", type_="unique")
    op.drop_constraint("uq_permissions_file_user", "permissions", type_="unique")
    op.drop_table("permissions")

    op.drop_constraint("uq_file_versions_file_id_version_number", "file_versions", type_="unique")
    op.drop_table("file_versions")

    op.drop_index("ix_files_blob_id", table_name="files")
    op.drop_column("files", "blob_id")
    op.drop_column("files", "purge_at")
    op.drop_column("files", "deleted_at")

    op.drop_index("ix_blobs_content_hash", table_name="blobs")
    op.drop_table("blobs")

    op.drop_column("users", "otp_enabled")
    op.drop_column("users", "otp_secret")

    bind = op.get_bind()
    share_role.drop(bind, checkfirst=True)
    permission_role.drop(bind, checkfirst=True)
