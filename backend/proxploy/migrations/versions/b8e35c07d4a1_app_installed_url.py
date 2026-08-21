"""apps.installed_url, and recover it for installs that already ran

A community-scripts install script ends by printing the finished URL, which is
the app stating its own scheme, port and path. Proxploy already captured that
line into `job_events` and threw the information away, so Open fell back to
probing (and before that, to guessing "http").

`services/appstore.py` now stores it when an install finishes. This migration
adds the column and does the one-time pass for the installs that already ran,
because their logs are still in `job_events` and re-installing an app to
recover a line Proxploy already has would be absurd.

WHY A MIGRATION AND NOT A SCRIPT. There is nothing for an operator to decide
here and nothing to schedule: the data is already local, the pass is a few
milliseconds, and it must happen exactly once per database. Same shape and
same reasoning as e4b1a7c05d92, which backfilled apps.category and
apps.web_port from the catalog.

WHY IT CANNOT BE SQL. The line has to have its ANSI escapes stripped, one URL
picked out of it, and that URL corroborated against the catalog's port before
it is trusted, so the parser in services/webui.py is imported and used.
Importing app code into a migration is unusual, and it is right here: this
backfill is best effort by construction, so a later, better parser applied to
the same logs on a fresh database is an improvement rather than a divergence.
Duplicating the parser is what would rot.

An install job carries no app id (`jobs.target_type` is NULL for app.install),
so an app is matched to its job by the host and name the job's params carry,
newest succeeded job wins. A failed job is never read: it may have printed a
URL for a container that was then rolled back.

Nothing an operator owns is written. The only column touched is the new one,
and web_protocol / web_port / web_path are read at open time in that order of
precedence, so an operator's value still wins over anything recovered here.

Revision ID: b8e35c07d4a1
Revises: a2d6f14b8e37
Create Date: 2026-08-21

"""
import json

import sqlalchemy as sa
from alembic import op

revision = "b8e35c07d4a1"
down_revision = "a2d6f14b8e37"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("apps", sa.Column("installed_url", sa.Text(), nullable=True))

    from proxploy.services.webui import TAIL_LINES, url_from_install_log

    conn = op.get_bind()
    apps = conn.execute(sa.text(
        "SELECT a.id, a.name, a.host_id, c.port FROM apps a "
        "LEFT JOIN catalog_entries c ON c.slug = a.catalog_slug")).fetchall()
    jobs = conn.execute(sa.text(
        "SELECT id, params FROM jobs "
        "WHERE kind = 'app.install' AND status = 'succeeded' ORDER BY id")).fetchall()

    by_app: dict[tuple, int] = {}
    for job_id, params in jobs:
        try:
            p = json.loads(params or "{}")
        except ValueError:
            continue
        by_app[(p.get("host_id"), p.get("name"))] = job_id

    for app_id, name, host_id, port in apps:
        job_id = by_app.get((host_id, name))
        if job_id is None:
            continue
        lines = [r[0] for r in conn.execute(sa.text(
            "SELECT message FROM job_events WHERE job_id = :j AND stream = 'stdout' "
            "ORDER BY seq DESC LIMIT :n"), {"j": job_id, "n": TAIL_LINES})]
        url = url_from_install_log(reversed(lines), expected_port=port)
        if url:
            conn.execute(sa.text("UPDATE apps SET installed_url = :u WHERE id = :i"),
                         {"u": url, "i": app_id})


def downgrade() -> None:
    with op.batch_alter_table("apps") as batch:
        batch.drop_column("installed_url")
