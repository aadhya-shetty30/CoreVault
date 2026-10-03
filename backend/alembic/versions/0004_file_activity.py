"""phase 3: per-file activity log

Additive only -- one new table, nothing existing touched.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-03

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_activity",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "file_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("files.id", ondelete="CASCADE"), nullable=False
        ),
        # NULL = anonymous (a public share-link download) or a since-deleted user.
        sa.Column(
            "actor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("detail", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_file_activity_file_created", "file_activity", ["file_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_file_activity_file_created", table_name="file_activity")
    op.drop_table("file_activity")
