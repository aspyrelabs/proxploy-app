"""catalog upstream metadata provenance, and a 6h refresh cadence

Revision ID: c8f2a4b71d90
Revises: b4d7c9e21a35
Create Date: 2026-08-13

The App Store's metadata source moved out of the scripts repo (see
docs/superpowers/specs/2026-08-13-app-store-upstream-metadata-design.md).
community-scripts/ProxmoxVE is scripts only now: its tree at HEAD has 2009
entries and four .json files, all CI config. The live source is PocketBase at
db.community-scripts.org, which is what upstream's own ProxmoxVE-Local client
reads.

Three changes:

- `scraped_at` goes. It belonged to services/community_scripts_scrape.py, an
  undocumented scrape of community-scripts.org's Next.js flight payload, which
  is deleted in this same change. It was null on every row in practice, so
  nothing is lost by dropping it rather than renaming it.
- `metadata_source` / `metadata_synced_at` / `upstream_updated_at` record where
  a row's presentation fields came from and how fresh they are.
  `metadata_source` is "pocketbase" or "archive". Both timestamp columns null
  means "no upstream record matched this slug", which is a normal state, not an
  error: 37 of our ct/ rows have no upstream record at all.
- The "Catalog refresh" system schedule is retimed from nightly to every 6h.

The schedule retime is deliberately conditional. `seed_system_schedules` is
one-way by design (jobs/scheduler.py: "a system row the operator disabled or
re-timed stays that way across restarts"), so changing SYSTEM_SCHEDULES alone
would never reach an existing install. Updating the row unconditionally here
would break the same promise from the other side, silently stomping a cron the
operator chose. So this only rewrites the row still holding the old seeded
default, and clears next_run_at so the scheduler re-primes it on the next tick.
"""
from alembic import op
import sqlalchemy as sa

revision = "c8f2a4b71d90"
down_revision = "b4d7c9e21a35"
branch_labels = None
depends_on = None

OLD_CRON = "0 4 * * *"
NEW_CRON = "0 */6 * * *"


def upgrade() -> None:
    with op.batch_alter_table("catalog_entries") as batch:
        batch.add_column(sa.Column("metadata_source", sa.Text(), nullable=True))
        batch.add_column(sa.Column("metadata_synced_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("upstream_updated_at", sa.DateTime(), nullable=True))
        batch.drop_column("scraped_at")

    op.execute(
        sa.text(
            "UPDATE schedules SET cron = :new, next_run_at = NULL "
            "WHERE job_kind = 'catalog.refresh' AND cron = :old"
        ).bindparams(new=NEW_CRON, old=OLD_CRON)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE schedules SET cron = :old, next_run_at = NULL "
            "WHERE job_kind = 'catalog.refresh' AND cron = :new"
        ).bindparams(new=NEW_CRON, old=OLD_CRON)
    )

    with op.batch_alter_table("catalog_entries") as batch:
        batch.add_column(sa.Column("scraped_at", sa.DateTime(), nullable=True))
        batch.drop_column("upstream_updated_at")
        batch.drop_column("metadata_synced_at")
        batch.drop_column("metadata_source")
