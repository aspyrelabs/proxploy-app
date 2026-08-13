"""catalog script dates and the card tags

Revision ID: a4d70e9c31b8
Revises: f2b9e5104c67
Create Date: 2026-08-13

The Store gains "what's popular" and "what's new" sorting plus the tag chips
community-scripts shows (ARM, Updateable, Privileged, port). Every one of
these values is ALREADY cached, inside `raw["metadata"]`, for 548 of the 557
store-visible ct rows: this migration promotes the ones the Store reads on
every card, or sorts on, out of that JSON blob and into typed columns.

Two reasons they are columns rather than json_extract reads:

- `script_created` and `script_updated` are SORT KEYS. An ORDER BY over
  json_extract is neither indexable nor cheap, and it would be paid on every
  store load over the whole 585-row ct catalog.
- The flags are read on every card of every list response. `raw` also carries
  the pinned ct/ and install script bodies, so the store-visible rows total
  ~4.2 MB of JSON with a 6.7 KB median and a 49.8 KB maximum. Reaching into
  that per row per request, for four booleans and an int, is the expensive way
  to answer a cheap question.

The three booleans are NULLABLE and must stay that way. NULL means "we have no
upstream record for this slug", which is exactly true of the 9 `unlisted`
rows, and it has to stay distinguishable from a real False: "not privileged"
and "we do not know whether it is privileged" are different claims, and only
one of them is ours to make.

No backfill. The values live in raw["metadata"] already, but backfilling would
mean this migration parsing upstream's JSON with its own copy of the mapping
rules, which is the job of services/catalog_metadata.py and would be a second
place to keep correct. The next metadata sync fills every matched row.
"""
from alembic import op
import sqlalchemy as sa

revision = "a4d70e9c31b8"
down_revision = "f2b9e5104c67"
branch_labels = None
depends_on = None

COLUMNS = (
    ("script_created", sa.DateTime()),
    ("script_updated", sa.DateTime()),
    ("has_arm", sa.Boolean()),
    ("updateable", sa.Boolean()),
    ("privileged", sa.Boolean()),
    ("port", sa.Integer()),
    ("architectures", sa.JSON()),
)


def upgrade() -> None:
    with op.batch_alter_table("catalog_entries") as batch:
        for name, type_ in COLUMNS:
            batch.add_column(sa.Column(name, type_, nullable=True))
    # "Newest" and "recently updated" are the two sorts the Store offers over
    # the whole ct catalog, and both are ORDER BY <col> DESC with a NULLS LAST
    # tiebreak. Cheap to add here, and the alternative was a table scan and a
    # sort on every store load.
    op.create_index("ix_catalog_entries_script_created", "catalog_entries",
                    ["script_created"])
    op.create_index("ix_catalog_entries_script_updated", "catalog_entries",
                    ["script_updated"])


def downgrade() -> None:
    op.drop_index("ix_catalog_entries_script_updated", "catalog_entries")
    op.drop_index("ix_catalog_entries_script_created", "catalog_entries")
    with op.batch_alter_table("catalog_entries") as batch:
        for name, _type in reversed(COLUMNS):
            batch.drop_column(name)
