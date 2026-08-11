"""host last_error

Why the last poll cycle was not clean. Nullable, and NULL is the normal
steady state, so there is nothing to backfill: the next clean cycle writes
NULL and the next unclean one writes a reason.

Revision ID: c4a1b7e90d55
Revises: bef9d92f4830
Create Date: 2026-08-11

"""
import sqlalchemy as sa
from alembic import op

revision = "c4a1b7e90d55"
down_revision = "bef9d92f4830"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("hosts") as batch:
        batch.add_column(sa.Column("last_error", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("hosts") as batch:
        batch.drop_column("last_error")
