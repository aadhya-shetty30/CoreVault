"""phase 3: storage dashboard + stale-file review

Additive only, same rule as 0002 -- two new nullable columns on files and
one index. Nothing from Phase 1/2 is altered or dropped.

- files.last_accessed_at: stamped whenever the file's bytes are actually
  read (authenticated download or a public share-link download). NULL for
  every pre-existing row; the stale-file query treats NULL as "never opened
  since upload" and falls back to updated_at (see routers/analytics.py).
- files.stale_prompt_snoozed_until: set when the owner answers "keep it" to
  the stale-file prompt, so the same file doesn't nag again until then.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-03

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("files", sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("files", sa.Column("stale_prompt_snoozed_until", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_files_owner_last_accessed", "files", ["owner_id", "last_accessed_at"])


def downgrade() -> None:
    op.drop_index("ix_files_owner_last_accessed", table_name="files")
    op.drop_column("files", "stale_prompt_snoozed_until")
    op.drop_column("files", "last_accessed_at")
