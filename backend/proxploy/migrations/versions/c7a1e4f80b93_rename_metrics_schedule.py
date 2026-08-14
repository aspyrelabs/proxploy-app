"""Rename the "Metrics maintenance" system schedule to "Usage cleanup"

The job kind's user-facing label was renamed from "Metrics Maintained" to
"Usage Cleanup", but the SCHEDULE is a stored row whose `name` is written once
at seed time, so the Schedules table in Settings went on saying "Metrics
maintenance" after the rename.

Editing SYSTEM_SCHEDULES alone would NOT have fixed it and would have made
things worse: `seed_system_schedules` keys on `name` and only ever inserts,
deliberately, so that an operator who disabled or re-timed a system row keeps
that across restarts. A changed constant therefore reads as a schedule that
does not exist yet, and the next boot would add a SECOND row running
`metrics.maintain` alongside the first, with both firing hourly.

Matched on job_kind AND the exact old name so an operator who renamed the row
themselves keeps their name.

Revision ID: c7a1e4f80b93
Revises: b3d7e1a95c42
Create Date: 2026-08-14

"""
from alembic import op

revision = "c7a1e4f80b93"
down_revision = "b3d7e1a95c42"
branch_labels = None
depends_on = None

OLD = "Metrics maintenance"
NEW = "Usage cleanup"


def _rename(frm: str, to: str) -> None:
    op.execute(
        "UPDATE schedules SET name = '%s' "
        "WHERE name = '%s' AND job_kind = 'metrics.maintain'" % (to, frm)
    )


def upgrade() -> None:
    _rename(OLD, NEW)


def downgrade() -> None:
    _rename(NEW, OLD)
