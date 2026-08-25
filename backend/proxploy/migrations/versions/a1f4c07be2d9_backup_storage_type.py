"""what kind of datastore an archive lives on

Revision ID: a1f4c07be2d9
Revises: 53d3bc7a71d7
Create Date: 2026-08-25

api/backups.py::_refuse_on_pbs and the verify sweep both need to know whether
an archive belongs to Proxmox Backup Server, which verifies its own archives
and makes ours redundant. Both read the type out of poller.snapshots, which is
empty between boot and the first poll, so in that window a PBS archive was
offered for a full read-back over the network and a sweep firing at boot would
do it to every one of them.

sync_host_backups already iterates client.storages(node) and is handed the type
by PVE, so it records it here and neither reader needs the poller.

Nullable with no backfill: NULL means "synced before this column existed", and
both readers fall back to the snapshot for those until the next sync fills them
in, which the first sync after upgrade does.
"""
from alembic import op
import sqlalchemy as sa

revision = "a1f4c07be2d9"
down_revision = "53d3bc7a71d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("backups") as batch:
        batch.add_column(sa.Column("storage_type", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("backups") as batch:
        batch.drop_column("storage_type")
