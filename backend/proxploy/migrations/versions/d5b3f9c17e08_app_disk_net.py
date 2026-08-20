"""apps storage and network

The Apps views show storage and network alongside CPU and RAM, and neither
existed on the app row. Both come out of the /cluster/resources read the
poller already makes, so this adds where to put them and costs no extra call
to PVE.

netin/netout are counters since the container booted rather than rates, so
the raw readings are stored next to the derived rates: the diff that makes a
rate needs the previous reading, and it needs to know how long ago that
reading was, which is what net_sampled_at records.

All nullable with no backfill. Null is the honest value for an app that has
not been polled since this landed, and it is the same value the rate takes on
the first cycle and after a counter reset, so every reader already has to
handle it.

Revision ID: d5b3f9c17e08
Revises: c3f81a6d0e47
Create Date: 2026-08-20

"""
import sqlalchemy as sa
from alembic import op

revision = "d5b3f9c17e08"
down_revision = "c3f81a6d0e47"
branch_labels = None
depends_on = None

COLUMNS = (
    ("disk_bytes_cached", sa.BigInteger()),
    ("disk_total_bytes_cached", sa.BigInteger()),
    ("net_in_cached", sa.BigInteger()),
    ("net_out_cached", sa.BigInteger()),
    ("net_in_bps_cached", sa.Float()),
    ("net_out_bps_cached", sa.Float()),
    ("net_sampled_at", sa.DateTime()),
)


def upgrade() -> None:
    for name, type_ in COLUMNS:
        op.add_column("apps", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(COLUMNS):
        op.drop_column("apps", name)
