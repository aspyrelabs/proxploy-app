"""vms node_name

Which NODE the guest actually runs on, which the mirror never recorded.

Every VM action resolved its node as `host.node_name`, the node of the host
whose credentials were used. On a standalone host those are the same node and
nothing was wrong. On a cluster they are not: `/cluster/resources` reports the
whole cluster from any member, so each polled host mirrored every VM in the
cluster, and every row except the one belonging to the owning node answered
each action with `500 Configuration file 'nodes/<other>/qemu-server/<id>.conf'
does not exist` (doc 12 check 18, PVE 9.2.10, 2026-08-18).

Nullable, and NULL means "not polled since this column existed" rather than
"standalone". The callers fall back to `host.node_name`, which is exactly the
old behaviour, so a row the poller has not refreshed yet is no worse off than
it was before.

Revision ID: c17f4a9be350
Revises: b3e8c15a7d42
Create Date: 2026-08-18

"""
import sqlalchemy as sa
from alembic import op

revision = "c17f4a9be350"
down_revision = "b3e8c15a7d42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("vms") as batch:
        batch.add_column(sa.Column("node_name", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("vms") as batch:
        batch.drop_column("node_name")
