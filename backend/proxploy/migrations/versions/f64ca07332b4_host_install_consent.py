"""host install consent

Revision ID: f64ca07332b4
Revises: 634f5b0f23f0
Create Date: 2026-08-13

Consent moves from a per-install checkbox to a per-host acknowledgement.

THE BACKFILL IS A DELIBERATE DECISION, not a default value. Hosts that already
have an enrolled SSH key are marked acknowledged: enrolling that key IS the
grant of root execution, and those operators additionally ticked the
per-install box on every install they ran, so requiring a re-tick would be
friction that surfaces no new information. Hosts WITHOUT a key are left NULL:
there is nothing to backfill from, they never granted anything.
"""
from alembic import op
import sqlalchemy as sa

revision = "f64ca07332b4"
down_revision = "634f5b0f23f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("hosts") as batch:
        batch.add_column(sa.Column("install_consent_at", sa.DateTime(), nullable=True))
    op.execute(sa.text(
        "UPDATE hosts SET install_consent_at = CURRENT_TIMESTAMP "
        "WHERE id IN (SELECT host_id FROM host_credentials WHERE kind = 'ssh_key')"
    ))


def downgrade() -> None:
    with op.batch_alter_table("hosts") as batch:
        batch.drop_column("install_consent_at")
