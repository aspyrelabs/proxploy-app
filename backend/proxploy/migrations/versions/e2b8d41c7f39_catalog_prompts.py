"""catalog_entries.prompts

What the install script asks a human, recovered by
services/classifier.extract_prompts and written in the same pass that sets
`installable`, against the same upstream_sha. Splitting the two would let the
verdict and the questions behind it describe different revisions of a script.

NULL means never classified. [] means classified and it asks nothing, which is
what every already-installable row will hold once it is next classified.
Deliberately not backfilled: the script text a backfill would need is fetched
per row from upstream, and ensure_classified already re-runs lazily.

Revision ID: e2b8d41c7f39
Revises: d1a7f3e95c60
Create Date: 2026-08-27

"""
import sqlalchemy as sa
from alembic import op

revision = "e2b8d41c7f39"
down_revision = "d1a7f3e95c60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("catalog_entries") as batch:
        batch.add_column(sa.Column("prompts", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("catalog_entries") as batch:
        batch.drop_column("prompts")
