"""when proxploy last checked a backup archive

Revision ID: 53d3bc7a71d7
Revises: c9f2a41b7e63
Create Date: 2026-08-24

`backups.verify_state` holds the verdict and is reused rather than doubled:
Proxmox Backup Server writes it through the sync where PBS is the datastore,
and services/backupjobs.py's own checks write it where nothing else would. What
the column cannot carry is WHEN we looked, which the Backups page shows and the
30-day card windows on, so it gets its own stamp beside it.

Nullable with no backfill: NULL means "Proxploy has never checked this one",
which is true of every existing row.
"""
from alembic import op
import sqlalchemy as sa

revision = "53d3bc7a71d7"
down_revision = "c9f2a41b7e63"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("backups") as batch:
        batch.add_column(sa.Column("checked_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("backups") as batch:
        batch.drop_column("checked_at")
