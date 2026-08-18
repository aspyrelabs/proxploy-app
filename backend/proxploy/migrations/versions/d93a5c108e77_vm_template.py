"""vms template

Whether this guest is a PVE TEMPLATE, from `/cluster/resources`'s own
`template` flag.

PVE permits a linked clone (`full=false`) only from a template. Proxploy could
not tell templates apart, so the clone route passed `full` through unvalidated
and `CloneDialog` offered Full and Linked as radio buttons on every VM: picking
Linked on an ordinary guest always failed with
`500 Linked clone feature is not supported for '<volume>' (scsi0)`, which never
mentions templates. Observed on real hardware 2026-08-18 (doc 12 check 18); the
`ponytail:` note on the clone route had deferred exactly this pending evidence
that PVE's rejection was confusing in practice.

Nullable: NULL means "not polled since this column existed", and the callers
treat it as "not a template", which hides an option that would have failed
anyway rather than offering one that cannot work.

Revision ID: d93a5c108e77
Revises: a4d2e8b71c39
Create Date: 2026-08-18

"""
import sqlalchemy as sa
from alembic import op

revision = "d93a5c108e77"
down_revision = "a4d2e8b71c39"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("vms") as batch:
        batch.add_column(sa.Column("template", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("vms") as batch:
        batch.drop_column("template")
