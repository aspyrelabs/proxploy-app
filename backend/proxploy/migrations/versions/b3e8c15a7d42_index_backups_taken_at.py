"""index backups.taken_at

Revision ID: b3e8c15a7d42
Revises: a1f7d3c95b28
Create Date: 2026-08-15

GET /backups is capped at 200 rows, but the cap bounds what is RETURNED, not
the work done to find it: `ORDER BY taken_at DESC LIMIT 200` still sorted the
whole table on every poll, and that page polls every 60s and can be open in
several tabs. The gap widens as backup history grows, which is exactly the
direction a backup table only ever moves.

An ascending index is enough for a descending order by: SQLite walks it
backwards and stops after the limit. taken_at is nullable, and NULLs sort
smallest, so walking backwards puts them last, which is where ORDER BY DESC
wants them anyway.
"""
from alembic import op

revision = "b3e8c15a7d42"
down_revision = "a1f7d3c95b28"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_backups_taken_at", "backups", ["taken_at"])


def downgrade() -> None:
    op.drop_index("ix_backups_taken_at", table_name="backups")
