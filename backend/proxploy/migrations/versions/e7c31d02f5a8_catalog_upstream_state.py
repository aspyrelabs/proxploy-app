"""catalog upstream_state: badge the retired apps, hide the alpine variants

Revision ID: e7c31d02f5a8
Revises: c8f2a4b71d90
Create Date: 2026-08-13

Our discovery walks ct/*.sh and makes one row per FILE. Upstream's PocketBase
is the catalog of what they consider an APP. The two disagree three ways, and
42 of our 585 store-visible ct rows currently render as blank cards:

- 28 alpine-* rows are variants, not apps. Verified live: the `syncthing`
  record carries install_methods [{type: "default"}, {type: "alpine"}], so
  ct/alpine-syncthing.sh is the IMPLEMENTATION of Syncthing's Alpine method.
  Upstream shows one Syncthing card; we showed two, one of them blank.
- 5 rows upstream soft-deleted (record present, is_deleted true).
- 9 rows upstream dropped outright, no record at all.

`upstream_state` records which of those a row is, so the Store can badge the
retired ones (still installable, the script is still in the repo) and drop the
variants off the grid. Nullable with no backfill: NULL means "never synced",
and the next metadata sync resolves every row. Backfilling here would mean
this migration guessing at upstream's catalog with no network, and the sync is
the only thing that can answer.

Deliberately a new column rather than a reuse of `deprecated`: that column is
written nowhere and read nowhere since the initial migration, and a boolean
cannot carry four states anyway. It is left exactly as it is.
"""
from alembic import op
import sqlalchemy as sa

revision = "e7c31d02f5a8"
down_revision = "c8f2a4b71d90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("catalog_entries") as batch:
        batch.add_column(sa.Column("upstream_state", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("catalog_entries") as batch:
        batch.drop_column("upstream_state")
