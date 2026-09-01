"""node shell enabled by default

Sys.Console now rides the Console role, so the privilege is always there and
the in-app toggle is the only thing deciding whether a host may open a node
shell. Defaulting it off made a granted privilege look broken.

Only the default for NEW hosts changes. Rows that already exist keep whatever
they were set to: silently turning a root shell on for an existing install
during an upgrade is not a default, it is a change to that operator's posture.

Revision ID: c5a91f27de40
Revises: d4f60b1a83c7
"""
from alembic import op
import sqlalchemy as sa

revision = "c5a91f27de40"
down_revision = "d4f60b1a83c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("hosts") as batch:
        batch.alter_column("node_shell_enabled",
                           existing_type=sa.Boolean(),
                           existing_nullable=False,
                           server_default=sa.true())


def downgrade() -> None:
    with op.batch_alter_table("hosts") as batch:
        batch.alter_column("node_shell_enabled",
                           existing_type=sa.Boolean(),
                           existing_nullable=False,
                           server_default=sa.false())
