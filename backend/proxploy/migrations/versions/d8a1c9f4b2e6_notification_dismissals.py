"""notification dismissals

Per-user memory of what the bell tray has cleared (see
docs/notes/persist-cleared-notifications-report.md). One row per user: a
watermark (the highest job id cleared as of the last "clear all") plus a
small list of individually dismissed job ids newer than that watermark. The
watermark is what keeps this bounded on a busy cluster instead of growing a
dismissed-id list forever -- see the model's own docstring
(proxploy/models/__init__.py::NotificationDismissal).

Revision ID: d8a1c9f4b2e6
Revises: c4a1b7e90d55
Create Date: 2026-08-12

"""
from alembic import op
import sqlalchemy as sa

revision = "d8a1c9f4b2e6"
down_revision = "c4a1b7e90d55"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_dismissals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(),
                 sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cleared_through_job_id", sa.Integer(), nullable=True),
        sa.Column("dismissed_job_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ux_notification_dismissals_user_id", "notification_dismissals",
                    ["user_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ux_notification_dismissals_user_id",
                  table_name="notification_dismissals")
    op.drop_table("notification_dismissals")
