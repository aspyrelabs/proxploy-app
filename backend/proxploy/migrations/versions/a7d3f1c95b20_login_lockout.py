"""users: failed login count and lockout

A password guessed at machine speed is the realistic attack on a panel that
manages somebody's hypervisor, and rate limiting by IP does not stop a slow
distributed one against a single account. Five wrong answers park the account
for ten minutes, which costs an attacker three orders of magnitude and costs
the person who fat-fingered their password one coffee.

Both columns are on the user rather than a side table: they are read on the
hot path of every login and written on every failure, and a join for two
integers would be a join per attempt.
"""
import sqlalchemy as sa
from alembic import op

revision = "a7d3f1c95b20"
down_revision = "e2b8d41c7f39"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("failed_login_count", sa.Integer(),
                                   nullable=False, server_default="0"))
        batch.add_column(sa.Column("locked_until", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("locked_until")
        batch.drop_column("failed_login_count")
