"""totp last accepted step

Revision ID: a1f7d3c95b28
Revises: c7a1e4f80b93
Create Date: 2026-08-15

The time step of the last TOTP code this user got in with, so the same code
cannot be presented twice (RFC 6238 section 5.2). Nullable with no default on
purpose: NULL means "has never signed in with a code" and must stay
distinguishable from step 0.
"""
from alembic import op
import sqlalchemy as sa

revision = "a1f7d3c95b28"
down_revision = "c7a1e4f80b93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("totp_last_step", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    # Not lossless: dropping this column forgets which code was last used, so
    # the code accepted just before a downgrade becomes replayable for the
    # remainder of its window.
    with op.batch_alter_table("users") as batch:
        batch.drop_column("totp_last_step")
