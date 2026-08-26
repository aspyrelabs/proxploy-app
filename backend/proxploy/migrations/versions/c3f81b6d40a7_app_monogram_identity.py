"""give every logo-less app a monogram identity

No schema change: `icon_initials` and `icon_colors` have existed since the
first migration. This is a data backfill, because apps adopted before
services/app_identity.py existed carry NULL in both and so fall through to
whatever the frontend defaults to. Before the redesign that default was the
Store's own amber gradient, which meant every logo-less app was identical to
every other one and was wearing the badge of a Store it never came from.

Only rows with NULL are touched. An operator who has already chosen letters or
a colour keeps them, and a re-run changes nothing.

Down leaves the data alone: this backfill invents no information a downgrade
could want removed, and clearing it would throw away any colour the operator
had picked in the meantime for a row that happened to be NULL before.

Revision ID: c3f81b6d40a7
Revises: b7e2d1a94c53
"""
import re
import secrets

import sqlalchemy as sa
from alembic import op

revision = "c3f81b6d40a7"
down_revision = "b7e2d1a94c53"
branch_labels = None
depends_on = None

# Inlined, not imported from services/app_identity.py. A migration has to keep
# running against the code of its own moment: importing the live module would
# make this file's behaviour change the next time that ramp is edited, and a
# migration that does not do the same thing twice is not a migration.
RAMP = [
    ("#5B9DF9", "#2F6FE0"), ("#38BDF8", "#0C7FC4"),
    ("#34D3C6", "#0FA8A0"), ("#7C8CF8", "#4C5DD8"),
    ("#A78BFA", "#7C5CFB"), ("#C084FC", "#9333EA"),
    ("#E879F9", "#C026D3"), ("#F472B6", "#DB2777"),
]
_SEP_RE = re.compile(r"[-_. ]+")


def _monogram(name):
    parts = [p for p in _SEP_RE.split(name or "") if p]
    if len(parts) >= 3:
        return "".join(p[0] for p in parts[:3]).upper()
    return _SEP_RE.sub("", name or "")[:3].upper() or "APP"


def upgrade():
    apps = sa.table("apps", sa.column("id", sa.Integer), sa.column("name", sa.Text),
                    sa.column("icon_initials", sa.Text),
                    sa.column("icon_colors", sa.JSON))
    conn = op.get_bind()
    rows = conn.execute(sa.select(apps.c.id, apps.c.name, apps.c.icon_initials,
                                 apps.c.icon_colors)).fetchall()
    for row in rows:
        values = {}
        if row.icon_initials is None:
            values["icon_initials"] = _monogram(row.name)
        if row.icon_colors is None:
            dark, light = secrets.choice(RAMP)
            values["icon_colors"] = {"dark": dark, "light": light}
        if values:
            conn.execute(apps.update().where(apps.c.id == row.id).values(**values))


def downgrade():
    """Deliberately empty. See the module docstring."""
