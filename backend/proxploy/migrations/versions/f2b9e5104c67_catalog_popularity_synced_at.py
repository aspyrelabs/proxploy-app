"""catalog popularity freshness stamp

Revision ID: f2b9e5104c67
Revises: e7c31d02f5a8
Create Date: 2026-08-13

`catalog_entries.popularity` has existed since the initial migration and has
never been written by anything. services/catalog_telemetry.py starts filling
it from community-scripts' telemetry service, so the column finally means
something, and it needs a freshness stamp beside it.

Its own column rather than a reuse of `synced_at` or `metadata_synced_at`,
because the three move on genuinely different clocks: `synced_at` is the
scripts-tree discovery, `metadata_synced_at` is the PocketBase presentation
sync, and this is a third host with a 23h server-side cache in front of it.
A popularity number can be a full day stale while the name and icon beside it
are minutes old, and the Store has to be able to say so.

Nullable with no backfill: NULL means "never read", which is exactly true of
every existing row, and the first telemetry sync stamps the ones it matches.
"""
from alembic import op
import sqlalchemy as sa

revision = "f2b9e5104c67"
down_revision = "e7c31d02f5a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("catalog_entries") as batch:
        batch.add_column(sa.Column("popularity_synced_at", sa.DateTime(),
                                   nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("catalog_entries") as batch:
        batch.drop_column("popularity_synced_at")
