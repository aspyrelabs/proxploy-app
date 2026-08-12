"""host node_power_missing

Whether the stored token lacks Sys.PowerMgmt (host reboot/power off),
recomputed at enrolment and by POST /hosts/{id}/test. Nullable, and NULL is
the correct value for every host that existed before this column did: it
means "not checked yet", not "granted" -- a host enrolled before Sys.
PowerMgmt existed as a concept has genuinely never been probed for it, and
defaulting to False would claim a certainty this migration does not have.

Revision ID: e3b6a1d9c7f4
Revises: d8a1c9f4b2e6
Create Date: 2026-08-12

"""
import sqlalchemy as sa
from alembic import op

revision = "e3b6a1d9c7f4"
down_revision = "d8a1c9f4b2e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("hosts") as batch:
        batch.add_column(sa.Column("node_power_missing", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("hosts") as batch:
        batch.drop_column("node_power_missing")
