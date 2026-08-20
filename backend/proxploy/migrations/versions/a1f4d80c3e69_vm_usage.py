"""vms usage, and mem_bytes/disk_bytes now mean USED

A VM row stored only the guest's ALLOCATION, so the VMs page could draw a CPU
meter and nothing else: there was no memory, storage or network usage on the
row to draw. Apps have carried all of it since d5b3f9c17e08; this brings VMs
level.

The awkward half is that `mem_bytes` and `disk_bytes` already existed on this
table holding maxmem and maxdisk, while the same two names on `apps` held
usage. One name meaning two things across two guest types is the actual defect
underneath the missing meters, so the names are given App's meaning here rather
than left to disagree forever. The allocation is not lost: it moves into the
`*_total_bytes` columns added beside them, which is where the API has always
served it from for apps.

So the backfill is a move, not a wipe:

  * mem_total_bytes  <- the old mem_bytes  (maxmem, still true)
  * disk_total_bytes <- the old disk_bytes (maxdisk, still true)
  * mem_bytes, disk_bytes -> NULL, because nothing has ever measured them

NULL rather than a guess for the two that are cleared. The first poll cycle
after this fills mem_bytes in from the /cluster/resources read it already
makes, and disk_bytes from the QEMU guest agent when the guest has one. NULL
is also the permanent, correct value for a VM with no agent installed, so
every reader already has to handle it.

The net columns take App's exact names because pollers._update_net_rates is
shared between the two models and writes them by attribute.

Revision ID: a1f4d80c3e69
Revises: e4b1a7c05d92
Create Date: 2026-08-20

"""
import sqlalchemy as sa
from alembic import op

revision = "a1f4d80c3e69"
down_revision = "e4b1a7c05d92"
branch_labels = None
depends_on = None

COLUMNS = (
    ("mem_total_bytes", sa.BigInteger()),
    ("disk_total_bytes", sa.BigInteger()),
    ("net_in_cached", sa.BigInteger()),
    ("net_out_cached", sa.BigInteger()),
    ("net_in_bps_cached", sa.Float()),
    ("net_out_bps_cached", sa.Float()),
    ("net_sampled_at", sa.DateTime()),
)


def upgrade() -> None:
    with op.batch_alter_table("vms") as batch:
        for name, type_ in COLUMNS:
            batch.add_column(sa.Column(name, type_, nullable=True))
    op.execute("UPDATE vms SET mem_total_bytes = mem_bytes, "
               "disk_total_bytes = disk_bytes")
    op.execute("UPDATE vms SET mem_bytes = NULL, disk_bytes = NULL")


def downgrade() -> None:
    # Put the allocation back where the old schema kept it before the columns
    # holding it are dropped, or downgrading would leave the table looking
    # like every VM has an unknown size.
    op.execute("UPDATE vms SET mem_bytes = mem_total_bytes, "
               "disk_bytes = disk_total_bytes")
    with op.batch_alter_table("vms") as batch:
        for name, _ in reversed(COLUMNS):
            batch.drop_column(name)
