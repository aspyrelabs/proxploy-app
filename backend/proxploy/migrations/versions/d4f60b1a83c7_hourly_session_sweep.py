"""Run the session/console-ticket sweep hourly instead of nightly

`console_tickets.upstream_ticket` holds Proxmox's own ticket in the clear, so
a redeemed or expired row is spent credential material at rest until the sweep
takes it: up to 24 hours at "15 3 * * *". SYSTEM_SCHEDULES only ever inserts,
so an existing install keeps the nightly cron unless this moves it. Matched on
job_kind AND the exact old cron so an operator who re-timed the row keeps their
timing; clearing next_run_at hands the recompute to scheduler.prime().

Revision ID: d4f60b1a83c7
Revises: b8e4c02a71f6
Create Date: 2026-08-30

"""
from alembic import op

revision = "d4f60b1a83c7"
down_revision = "b8e4c02a71f6"
branch_labels = None
depends_on = None

OLD = "15 3 * * *"
NEW = "15 * * * *"


def retime_sql(frm: str, to: str) -> str:
    return ("UPDATE schedules SET cron = '%s', next_run_at = NULL "
            "WHERE cron = '%s' AND job_kind = 'sessions.cleanup'" % (to, frm))


def upgrade() -> None:
    op.execute(retime_sql(OLD, NEW))


def downgrade() -> None:
    op.execute(retime_sql(NEW, OLD))
