"""trusted devices

Revision ID: a1c4d7e93b20
Revises: b52e7d09af13
Create Date: 2026-08-19

A device that has already proved the second factor can skip the code step for
`trusted_device_ttl_days`. Same columns as `sessions` on purpose: this token
bypasses two-factor, so it gets the revocation and expiry rules that are
already proven rather than a second set written from scratch.

No backfill. Nothing existing has proved anything on any device, and trusting
a device retroactively would be inventing consent nobody gave.
"""
from alembic import op
import sqlalchemy as sa

revision = "a1c4d7e93b20"
down_revision = "b52e7d09af13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trusted_devices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("ip", sa.Text()),
        sa.Column("user_agent", sa.Text()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime()),
        sa.Column("revoked_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_trusted_devices_user_id", "trusted_devices", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_trusted_devices_user_id", table_name="trusted_devices")
    op.drop_table("trusted_devices")
