"""drop the dead catalog_entries.deprecated column

Revision ID: c9a35b71e0d4
Revises: b6e2f8a04d71
Create Date: 2026-08-13

`deprecated` has been dead since the first migration
(9f3cd187d023_0001_full_entity_list.py:88): NOT NULL, defaulting to false,
written nowhere and read nowhere. Every row in the 669-row dev catalog still
holds the default it was created with.

It is dropped now rather than left alone because the catalog grew a column
today that does the job it was presumably meant for. `upstream_state` records
what upstream's catalog actually says about a slug (listed / delisted /
unlisted / variant / superseded), and it was deliberately added BESIDE this
one rather than overloading it: a boolean cannot carry five states, and
"deprecated" asserts a judgement upstream has not made. A dead column sitting
next to a live one that looks like it means the same thing is a trap for
whoever reads this model next.

SQLite has no DROP COLUMN in the form alembic needs, so `batch_alter_table`
rebuilds the table: create a new one from the current metadata, copy the rows,
drop the old, rename. That rebuild is the risk in this migration, not the drop
itself, and `catalog_entries` grew fourteen columns today, so the round trip
was verified against a copy of the real 669-row database with a full
before/after column and row comparison rather than by inspection.

The downgrade restores it faithfully: Boolean, NOT NULL, server default false.
Restoring it nullable, or without the default, would leave a schema that looks
right and rejects the next insert.
"""
from alembic import op
import sqlalchemy as sa

revision = "c9a35b71e0d4"
down_revision = "b6e2f8a04d71"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("catalog_entries") as batch:
        batch.drop_column("deprecated")


def downgrade() -> None:
    # TWO steps, and the second one is the whole point of the first being
    # temporary. 9f3cd187d023 created this column NOT NULL with NO server
    # default: the false() default lives in the SQLAlchemy model, Python side,
    # and never reached the DDL. So a faithful restore cannot simply add it
    # back with a server default, because the resulting schema would carry a
    # `DEFAULT 0` clause the original never had.
    #
    # But it cannot be added back WITHOUT one either: the table holds rows,
    # and a NOT NULL column with no default has nothing to put in them.
    #
    # So: add it with a default to populate the existing rows, then drop the
    # default so the final DDL matches 9f3cd187d023 exactly. Each batch block
    # is its own table rebuild, which is the cost of getting this right on
    # SQLite and is paid once, on a downgrade nobody runs twice.
    with op.batch_alter_table("catalog_entries") as batch:
        batch.add_column(sa.Column("deprecated", sa.Boolean(), nullable=False,
                                   server_default=sa.false()))
    with op.batch_alter_table("catalog_entries") as batch:
        batch.alter_column("deprecated", existing_type=sa.Boolean(),
                           existing_nullable=False, server_default=None)
