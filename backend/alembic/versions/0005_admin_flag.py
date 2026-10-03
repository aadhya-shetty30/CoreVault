"""phase 3: admin flag on users

Additive only -- one new column, false for every existing and new user.
Granted only out-of-band via scripts/make_admin.py; no API can set it.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-03

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("users", "is_admin")
