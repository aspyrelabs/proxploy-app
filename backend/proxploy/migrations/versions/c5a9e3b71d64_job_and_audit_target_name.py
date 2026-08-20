"""jobs + audit_events: target_name, the name of the thing that was acted on

Both tables recorded only `target_type` and `target_id`, so the activity tray
and the audit log could say no more than "vm 3". Nobody remembers what VM 3
was, and a month after a delete nobody can find out: the row that held the
name is gone, which is exactly the case the audit trail exists for.

The name is now captured when the job or audit row is WRITTEN, in
JobBackend.enqueue and write_audit, which both run before the work does. That
ordering is the whole feature: a destroy job is created while the guest row
still exists.

Backfill: for rows whose target is a vm, an app, a host or a backup that STILL
exists, the name is copied across from that row. That is the same lookup the
audit screen was already doing at render time, so it invents nothing; it just
freezes the answer before the target can disappear. Everything else, including
every row whose target has already been deleted, stays NULL and renders the
old "vm 3" way. Deliberately NOT backfilled from `params`: several routes put
a DIFFERENT name there (the snapshot's name, the clone's new name), so that
would have filled the column with confident wrong answers.

Revision ID: c5a9e3b71d64
Revises: b7d2e91a4c30
Create Date: 2026-08-20

"""
import sqlalchemy as sa
from alembic import op

revision = "c5a9e3b71d64"
down_revision = "b7d2e91a4c30"
branch_labels = None
depends_on = None

# target_type -> (source table, the column holding its name). Mirrors
# services/audit.py::TARGET_LABELS, minus the kinds whose rows are not worth
# naming retrospectively; a migration is frozen history and must not import a
# map that later changes underneath it.
SOURCES = (
    ("vm", "vms", "name"),
    ("app", "apps", "name"),
    ("host", "hosts", "name"),
    ("backup", "backups", "volid"),
)


def _backfill(table: str) -> None:
    for target_type, src, col in SOURCES:
        # Correlated subquery rather than UPDATE...FROM: portable across
        # SQLite and PostgreSQL. The EXISTS guard keeps a blank name from
        # being written as an empty string.
        op.execute(sa.text(
            f"UPDATE {table} SET target_name = "
            f"  (SELECT s.{col} FROM {src} s WHERE s.id = {table}.target_id) "
            f"WHERE {table}.target_type = '{target_type}' "
            f"  AND {table}.target_id IS NOT NULL "
            f"  AND {table}.target_name IS NULL "
            f"  AND EXISTS (SELECT 1 FROM {src} s WHERE s.id = {table}.target_id "
            f"              AND s.{col} IS NOT NULL AND s.{col} <> '')"))


def upgrade() -> None:
    for table in ("jobs", "audit_events"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("target_name", sa.Text(), nullable=True))
        _backfill(table)


def downgrade() -> None:
    for table in ("jobs", "audit_events"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("target_name")
