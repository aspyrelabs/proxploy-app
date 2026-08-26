"""0005 totp recovery codes

Revision ID: 6cf6a0722d23
Revises: 2330a95b98d2
Create Date: 2026-08-05

Phase 8 Task 8 amendment: the plan called for
zero migrations this phase, packing recovery-code hashes as JSON inside the
existing `users.totp_secret_enc` Fernet blob. That was rejected during
implementation -- burning a single recovery code would have meant
decrypt-mutate-re-encrypt of a blob shared with a concurrent TOTP verify,
racy by construction, plus a blob whose name says it holds one secret
quietly holding two. A real table gives each code its own row and lets
burning be an ordinary `UPDATE ... WHERE used_at IS NULL`
(services/consoletickets.py's exact atomic-redeem pattern).
"""
from alembic import op
import sqlalchemy as sa

revision = "6cf6a0722d23"
down_revision = "2330a95b98d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "totp_recovery_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code_hash_enc", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_totp_recovery_codes_user_id", "totp_recovery_codes", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_totp_recovery_codes_user_id", table_name="totp_recovery_codes")
    op.drop_table("totp_recovery_codes")
