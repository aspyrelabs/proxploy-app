"""drop the host storage defaults

Revision ID: c3f81a6d0e47
Revises: a1c4d7e93b20
Create Date: 2026-08-19

PXP-86 removed remembering a host's last storage placement (48fbbb2): which
pool a container lives on is a question, and answering it from a value left
over by a previous install is answering it for the operator. Nothing has read
or written these two columns since, and `remember_storage` went with them.

They stayed behind because dropping a column needs a migration and that was
outside PXP-86's scope. This is that migration.

Data IS lost, and that is the point rather than a caveat: the values are the
remembered placements the decision was about, and keeping them would leave the
next person to wonder whether something is meant to read them again.

The downgrade re-adds the columns as nullable, which is the shape they had.
It cannot bring the values back, and nothing reads them, so an install after a
downgrade behaves exactly as it does now: it asks.
"""
from alembic import op
import sqlalchemy as sa

revision = "c3f81a6d0e47"
down_revision = "a1c4d7e93b20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("hosts") as batch:
        batch.drop_column("default_template_storage")
        batch.drop_column("default_container_storage")


def downgrade() -> None:
    with op.batch_alter_table("hosts") as batch:
        batch.add_column(sa.Column("default_container_storage", sa.Text(), nullable=True))
        batch.add_column(sa.Column("default_template_storage", sa.Text(), nullable=True))
