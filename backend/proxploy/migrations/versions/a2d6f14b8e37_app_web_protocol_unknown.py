"""apps.web_protocol: nullable, and clear the placeholder "http"

Needed because there was no way to say "not known". `web_protocol` was NOT
NULL with a default of "http", so install and adopt wrote the string "http"
onto every app they created, and the Open action read it back as if an
operator had chosen it. Actual Budget serves over https on port 5006 (its
community-scripts install script calls `create_self_signed_cert`), so Open
sent the operator to `http://<ip>:5006` and the page failed to load.

Two changes, and both are needed for the fix to reach apps that already
exist:

  * the column becomes nullable, so NULL can mean "nobody has said, ask the
    app" (services/webui.py probes the guest on open).
  * every row whose value is the placeholder "http" is set to NULL.

The second is the whole point of this migration. Without it the fix would
only ever apply to apps installed after it landed: every app in an existing
database already says "http", the probe would never run for any of them, and
the reported bug would still be there for the app that reported it.

Clearing an operator's real choice is not a risk worth guarding against
here. Nothing in the product ever wrote "http" as an answer to a question, it
only ever wrote it as a placeholder, and an operator who did pick http on
purpose gets the same http back from the probe, because that is what their
app answers. "https" is left alone regardless, since only a person can have
written it.

The downgrade restores NOT NULL and has to fill the NULLs to do it, which
puts back exactly the placeholder this removed. That is correct rather than
lossy: older code cannot read a NULL here, and it treated "http" as the
default anyway.

Revision ID: a2d6f14b8e37
Revises: c5a9e3b71d64
Create Date: 2026-08-21

"""
from alembic import op
import sqlalchemy as sa

revision = "a2d6f14b8e37"
down_revision = "c5a9e3b71d64"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("apps") as batch:
        batch.alter_column("web_protocol", existing_type=sa.Text(), nullable=True)
    op.execute("UPDATE apps SET web_protocol = NULL WHERE web_protocol = 'http'")


def downgrade() -> None:
    op.execute("UPDATE apps SET web_protocol = 'http' WHERE web_protocol IS NULL")
    with op.batch_alter_table("apps") as batch:
        batch.alter_column("web_protocol", existing_type=sa.Text(), nullable=False)
