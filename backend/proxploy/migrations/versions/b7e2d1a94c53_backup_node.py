"""which node of a cluster an archive is on

Revision ID: b7e2d1a94c53
Revises: a1f4c07be2d9
Create Date: 2026-08-25

sync_host_backups read `host.node_name` and nothing else, so on a cluster whose
nodes each keep a LOCAL dump dir only the enrolled node's archives were ever
mirrored. Shared datastores report identically from any node and were always
complete, which is why this hid: invisible with a shared store, total without
one.

Reading every node needs the node on the row, for two separate reasons.
`local:backup/vzdump-lxc-110-a.tar.zst` is a valid volid on every node and
names a DIFFERENT file on each, so ux_backups(host_id, volid) could not hold
both and one node's rows silently replaced the other's. And verify, restore and
test restore all have to run where the file actually is.

Nullable with no backfill: NULL means "synced before this column existed", and
the next sync fills it in. The unique constraint is recreated rather than
altered, because SQLite cannot alter one in place; batch_alter_table rebuilds
the table, which is what every earlier migration here does too.
"""
from alembic import op
import sqlalchemy as sa

revision = "b7e2d1a94c53"
down_revision = "a1f4c07be2d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("backups") as batch:
        batch.add_column(sa.Column("node", sa.Text(), nullable=True))
        batch.drop_constraint("ux_backups", type_="unique")
        batch.create_unique_constraint("ux_backups", ["host_id", "node", "volid"])


def downgrade() -> None:
    # Rows that differ only by node collapse to one on the way down. Nothing
    # can be done about that: the old key cannot express them.
    with op.batch_alter_table("backups") as batch:
        batch.drop_constraint("ux_backups", type_="unique")
        batch.create_unique_constraint("ux_backups", ["host_id", "volid"])
        batch.drop_column("node")
