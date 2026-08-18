"""apps node_name

Which NODE the app's container actually runs on.

`vms.node_name` landed earlier the same day after a clustered pair sent every VM
action to the wrong node (doc 12 check 18). The App side had the identical shape
latent: an app's node was assumed to be its HOST's node, which is true while
installs choose the host and the migration handler repoints the row, and wrong
the moment a CT is migrated in the Proxmox UI instead of through Proxploy.

Nullable, and the callers fall back to `Host.node_name`, which is both correct
for a standalone host and exactly the behaviour that predates this column. The
fallback is why this is safe to add without a backfill: the next poll cycle
fills it in from `/cluster/resources`, and until then nothing changes.

`guest_node(host, row)` needed no change at all: it already reads `node_name`
off whatever row it is handed.

Revision ID: b52e7d09af13
Revises: f1c86b4a2d05
Create Date: 2026-08-18

"""
import sqlalchemy as sa
from alembic import op

revision = "b52e7d09af13"
down_revision = "f1c86b4a2d05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("apps") as batch:
        batch.add_column(sa.Column("node_name", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("apps") as batch:
        batch.drop_column("node_name")
