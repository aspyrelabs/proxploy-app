"""apps.missing_since

When the poller first observed this app's CT to be absent from a poll cycle
it was willing to trust. Nullable, and NULL is the correct value for every
app that existed before this column did: it means "last seen present", which
is what every already-installed app is until a cycle says otherwise. The
column drives pollers.ingest_cycle's reaping of apps whose container was
destroyed outside Proxploy.

Revision ID: b3d7e1a95c42
Revises: f64ca07332b4
Create Date: 2026-08-14

"""
import sqlalchemy as sa
from alembic import op

revision = "b3d7e1a95c42"
down_revision = "f64ca07332b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("apps") as batch:
        batch.add_column(sa.Column("missing_since", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("apps") as batch:
        batch.drop_column("missing_since")
