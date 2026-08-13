"""catalog local icon cache

Revision ID: b6e2f8a04d71
Revises: a4d70e9c31b8
Create Date: 2026-08-13

The Store's metadata is cache-first and works offline; its icons were not.
Every card fetched cdn.jsdelivr.net at render time, so a firewalled or
air-gapped Proxmox host rendered 556 initials tiles. services/catalog_icons.py
mirrors the files into data_dir/icons, and these four columns are the
bookkeeping that makes the mirror cheap and non-sticky.

`icon_url` is deliberately NOT repurposed. It stays upstream's URL, written by
the metadata sync as one of WRITABLE_FIELDS, and remains the fallback the API
serves when no local copy exists. Overwriting it with a local path would put a
Proxploy-shaped value in a column upstream owns and destroy the only record of
where the bytes came from.

- icon_cache_path   bare filename under data_dir/icons, never a path
- icon_cache_source the upstream URL those bytes came from, so a changed logo
                    is detectable rather than cached forever
- icon_cache_etag   for If-None-Match revalidation
- icon_cached_at    when we last confirmed it, so a steady-state sync can skip

Nullable with no backfill: every existing row correctly has no cached copy
yet, and the next catalog refresh fills them in. Nothing here downloads
anything; a migration that reached out to a CDN would be a migration that
fails on an air-gapped install, which is the exact user this change is for.
"""
from alembic import op
import sqlalchemy as sa

revision = "b6e2f8a04d71"
down_revision = "a4d70e9c31b8"
branch_labels = None
depends_on = None

COLUMNS = ("icon_cache_path", "icon_cache_source", "icon_cache_etag")


def upgrade() -> None:
    with op.batch_alter_table("catalog_entries") as batch:
        for name in COLUMNS:
            batch.add_column(sa.Column(name, sa.Text(), nullable=True))
        batch.add_column(sa.Column("icon_cached_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("catalog_entries") as batch:
        batch.drop_column("icon_cached_at")
        for name in reversed(COLUMNS):
            batch.drop_column(name)
