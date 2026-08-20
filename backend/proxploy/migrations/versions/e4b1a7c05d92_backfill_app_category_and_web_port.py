"""backfill apps.category and apps.web_port from the catalog

Data only, no schema change. Both columns have existed since the first
migration; POST /apps/adopt simply never filled them in, so every app adopted
before this landed read back with no category (the Apps grid put all of them
under "unknown") and no web port (nothing on the row knew where its web UI
answers). api/apps.py::adopt_apps now copies both at adopt time; the rows that
already exist need this one pass to catch up.

Copies only from the catalog entry the app's own `catalog_slug` names, which is
the same source adopt now reads, so a backfilled row and a freshly adopted one
cannot disagree.

Idempotent, and safe to run against a database an operator has already curated:

  * a row whose value is already set is skipped. That value may have been
    chosen by hand and this migration has no way to tell, so it never wins an
    argument with one.
  * a NULL `catalog_slug` matches no entry and is left alone.
  * a slug that no longer resolves (an entry removed by a catalog refresh) is
    left alone rather than blanked.
  * a catalog entry whose own category or port is NULL is not copied, so a NULL
    is never written over a NULL and re-running changes nothing.

Deliberately does NOT touch ip_cached, the third column that read back as
"unknown" for every app. That one is a cache of live state, not a fact from the
catalog, so there is nothing here to copy it from; the poller fills it in on its
next cycle (pollers/__init__.py::_refresh_ip).

Revision ID: e4b1a7c05d92
Revises: d5b3f9c17e08
Create Date: 2026-08-20

"""
from alembic import op

revision = "e4b1a7c05d92"
down_revision = "d5b3f9c17e08"
branch_labels = None
depends_on = None


def _backfill(column: str, source: str) -> str:
    return (
        f"UPDATE apps SET {column} = ("
        f"  SELECT c.{source} FROM catalog_entries c"
        f"   WHERE c.slug = apps.catalog_slug) "
        f"WHERE {column} IS NULL AND catalog_slug IS NOT NULL "
        f"  AND EXISTS ("
        f"  SELECT 1 FROM catalog_entries c"
        f"   WHERE c.slug = apps.catalog_slug AND c.{source} IS NOT NULL)")


def upgrade() -> None:
    op.execute(_backfill("category", "category"))
    op.execute(_backfill("web_port", "port"))


def downgrade() -> None:
    # Nothing to undo. A backfilled value is indistinguishable from one an
    # operator set by hand or one adopt wrote on its own, so clearing "the
    # backfilled ones" would mean clearing every category and web port in the
    # table. The columns were nullable before this ran and still are, so older
    # code reads a filled-in row perfectly happily.
    pass
