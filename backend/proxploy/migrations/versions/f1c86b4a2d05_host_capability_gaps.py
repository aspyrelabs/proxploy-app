"""hosts capability_gaps

Which privileges each configured capability token is missing, as
`{capability: [privilege, ...]}`, or `{}` when every token is fully granted.

Privilege drift is not hypothetical: `SDN.Use` and `VM.Config.HWType` were both
added to the Lifecycle role on 2026-08-18 after a real NIC write and a real VM
create refused without them (doc 12 checks 7, 17, 18). Every token generated
before that is short of them, and the only symptom was a 403 partway through a
job. `POST /hosts/{id}/test` gained a probe the same day, but that only helps
someone who thinks to press it.

Nullable, and NULL means "not probed yet", distinct from `{}` ("probed, nothing
missing"). A capability whose value is null inside the dict means PVE refused
`/access/permissions` for that token, which is "could not tell" rather than
clean, the same tri-state the rest of these probes use.

Revision ID: f1c86b4a2d05
Revises: d93a5c108e77
Create Date: 2026-08-18

"""
import sqlalchemy as sa
from alembic import op

revision = "f1c86b4a2d05"
down_revision = "d93a5c108e77"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("hosts") as batch:
        batch.add_column(sa.Column("capability_gaps", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("hosts") as batch:
        batch.drop_column("capability_gaps")
