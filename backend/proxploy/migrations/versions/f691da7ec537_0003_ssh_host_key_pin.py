"""0003 ssh host key pin

Revision ID: f691da7ec537
Revises: a2c7f1e33fe7
Create Date: 2026-07-30

"""
from alembic import op
import sqlalchemy as sa

revision = "f691da7ec537"
down_revision = "a2c7f1e33fe7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("hosts") as batch:
        batch.add_column(sa.Column("ssh_host_key_fingerprint", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("hosts") as batch:
        batch.drop_column("ssh_host_key_fingerprint")
