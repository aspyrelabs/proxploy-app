"""catalog entry type and lazy classification

Revision ID: aef437ae90d2
Revises: e3b6a1d9c7f4
Create Date: 2026-08-12

App store catalog expansion (24 hardcoded slugs -> full upstream ct/ corpus,
see .superpowers/sdd/app-store-catalog-plan.md). Two schema changes this needs:

- `entry_type`: which upstream directory an entry came from (ct/vm/pve/addon/
  turnkey), the mechanical, free classification the discovery tree-walk
  produces. Backfilled to "ct" for every existing row: the pre-expansion
  catalog only ever held ct/ entries (Settings.catalog_slugs' 24-slug seed
  list), so that default is exact, not a guess.
- `installable` becomes nullable. It used to be a hard boolean written the
  moment a slug was ingested (eager fetch-and-classify, one row per
  Settings.catalog_slugs entry). Discovery now populates ~584 ct/ skeleton
  rows from two GitHub API calls without fetching any ct/+install script
  pair; NULL is the honest "not yet classified" state until a card is opened,
  an install is attempted, or the low-priority backlog job reaches it.
"""
from alembic import op
import sqlalchemy as sa

revision = "aef437ae90d2"
down_revision = "e3b6a1d9c7f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("catalog_entries") as batch:
        batch.add_column(sa.Column("entry_type", sa.Text(), nullable=False,
                                   server_default="ct"))
        batch.add_column(sa.Column("scraped_at", sa.DateTime(), nullable=True))
        batch.alter_column("installable", existing_type=sa.Boolean(),
                           nullable=True, server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("catalog_entries") as batch:
        batch.alter_column("installable", existing_type=sa.Boolean(),
                           nullable=False, server_default=sa.false())
        batch.drop_column("scraped_at")
        batch.drop_column("entry_type")
