"""jobs: a checkpoint written before an effect leaves the machine

An install runs a pinned community script as root over SSH. If the connection
dies after the script was dispatched, or Proxploy itself is killed, the node
may be halfway through a real change and nothing recorded what the node looked
like beforehand. `run_install` reads exactly that set of container ids into a
local variable and it dies with the process, so the one question worth asking
afterwards, "did this actually build something", could not be asked at all.

The column holds what a later reconciliation needs and nothing else: whether
the command was dispatched, the container ids present before it was, and the
host, ctid and catalog slug it was for.

Deliberately not reusing `result`. That column means outcome, `_finish`
overwrites it on success, and storing pre-state in a field named result is the
kind of overloading that causes the next bug.

Nullable with no default: every job that never dispatches an effect leaves it
NULL, which is the honest reading of "nothing had happened yet".
"""
import sqlalchemy as sa
from alembic import op

revision = "b8e4c02a71f6"
down_revision = "a7d3f1c95b20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("checkpoint", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("checkpoint")
