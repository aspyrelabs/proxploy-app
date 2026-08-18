"""hosts quorate

Whether the cluster this host belongs to has quorum, from the `quorate` field
of its own `/cluster/status` cluster row.

Nullable, and NULL is correct for two different hosts: a standalone node, which
has no cluster row and for which the question does not apply, and any host that
has not been polled since this column existed. Neither is "quorum lost", so
neither may render as a warning.

Added because actual quorum loss was reached on real hardware (doc 12 check 12,
PVE 9.2.10, 2026-08-18) and nothing in the product noticed: every host still
read `connected`, the test endpoint still returned a PVE version, and
`/cluster/resources` still listed guests, while every write failed with
"cluster not ready - no quorum?".

Revision ID: a4d2e8b71c39
Revises: c17f4a9be350
Create Date: 2026-08-18

"""
import sqlalchemy as sa
from alembic import op

revision = "a4d2e8b71c39"
down_revision = "c17f4a9be350"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("hosts") as batch:
        batch.add_column(sa.Column("quorate", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("hosts") as batch:
        batch.drop_column("quorate")
