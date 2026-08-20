"""vms: drop synced_at, add guest_agent_ok

`vms.synced_at` recorded the instant the poller last stamped the row. Nothing
in the product ever computed with it: it was written in one place, read in one
place, and shown on the VM detail panel as "Last checked". What it actually
told an operator was that the poller was running, which every other figure on
the same page already tells them, and it told them nothing they could act on.

The column in its place answers a question an operator CAN act on: is the QEMU
guest agent installed and answering inside this VM. That is the same fact
behind the storage column reading "unknown", since a VM's used disk can only
come from the agent, so the two now explain each other.

Nullable and three-valued, and the three are kept apart deliberately:

  * 1 (true)  the agent answered.
  * 0 (false) Proxmox says this guest has no working agent, which on the lab
              reads `500 Internal Server Error: No QEMU guest agent
              configured`. A real finding, not a fault.
  * NULL      nobody knows: never probed, stopped (a guest that is not running
              cannot answer, and "not installed" would be a claim nobody
              checked), or the host was unreachable.

No backfill, so every existing row starts NULL, which is the honest value:
nothing has probed them under the new rules yet. The first poll cycle after
this fills in every running VM from the get-fsinfo call it was already making
for disk_bytes, so nothing extra is asked of any host.

Revision ID: b7d2e91a4c30
Revises: a1f4d80c3e69
Create Date: 2026-08-20

"""
import sqlalchemy as sa
from alembic import op

revision = "b7d2e91a4c30"
down_revision = "a1f4d80c3e69"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("vms") as batch:
        batch.add_column(sa.Column("guest_agent_ok", sa.Boolean(), nullable=True))
        batch.drop_column("synced_at")


def downgrade() -> None:
    # synced_at comes back empty rather than backfilled with "now": it meant
    # "when the poller last saw this row", and inventing that stamp at
    # downgrade time would claim a poll that never happened. The next cycle
    # rewrites it for every VM anyway.
    with op.batch_alter_table("vms") as batch:
        batch.add_column(sa.Column("synced_at", sa.DateTime(), nullable=True))
        batch.drop_column("guest_agent_ok")
