"""0004 console tickets

Revision ID: 2330a95b98d2
Revises: f691da7ec537
Create Date: 2026-07-30

"""
from alembic import op
import sqlalchemy as sa

revision = "2330a95b98d2"
down_revision = "f691da7ec537"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "console_tickets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),  # app_console | node_shell | vm_vnc
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("node", sa.Text(), nullable=False),
        sa.Column("guest_kind", sa.Text(), nullable=True),  # lxc | qemu | NULL (node shell)
        sa.Column("vmid", sa.Integer(), nullable=True),
        sa.Column("upstream_user", sa.Text(), nullable=False),
        sa.Column("upstream_ticket", sa.Text(), nullable=False),
        sa.Column("upstream_port", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_console_tickets_token_hash", "console_tickets", ["token_hash"])
    with op.batch_alter_table("hosts") as batch:
        batch.add_column(sa.Column("node_shell_enabled", sa.Boolean(), nullable=False,
                                   server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("hosts") as batch:
        batch.drop_column("node_shell_enabled")
    op.drop_index("ix_console_tickets_token_hash", table_name="console_tickets")
    op.drop_table("console_tickets")
