"""host storage defaults

Revision ID: 634f5b0f23f0
Revises: c9a35b71e0d4
Create Date: 2026-08-13

The pools an operator chose for a host, so the storage question is asked once
rather than on every install. Nullable with no default on purpose: NULL means
"not chosen yet" and must stay distinguishable from a pool name.
"""
from alembic import op
import sqlalchemy as sa

revision = "634f5b0f23f0"
down_revision = "c9a35b71e0d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("hosts") as batch:
        batch.add_column(sa.Column("default_container_storage", sa.Text(), nullable=True))
        batch.add_column(sa.Column("default_template_storage", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("hosts") as batch:
        batch.drop_column("default_template_storage")
        batch.drop_column("default_container_storage")
