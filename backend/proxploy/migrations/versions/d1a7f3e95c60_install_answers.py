"""install_answers: encrypted answers to an install script's prompts

The value never goes into jobs.params, because enqueue() redacts params by
key name and these names are chosen by upstream script authors, not by us:
`ziti_pwd` holds an admin password and `prompt` holds an enrollment JWT, and
no substring list catches either. params carries only the handle.

app_id is nullable because app.install is what creates the app. The row is
staged before the job runs, bound to the app once it exists, and swept if the
install never got there.

Revision ID: d1a7f3e95c60
Revises: c3f81b6d40a7
Create Date: 2026-08-27

"""
import sqlalchemy as sa
from alembic import op

revision = "d1a7f3e95c60"
down_revision = "c3f81b6d40a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "install_answers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("handle", sa.Text(), nullable=False, unique=True),
        sa.Column("app_id", sa.Integer(),
                  sa.ForeignKey("apps.id", ondelete="CASCADE"), nullable=True,
                  index=True),
        sa.Column("encrypted_blob", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("install_answers")
