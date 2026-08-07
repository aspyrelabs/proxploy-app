"""0002 constrain notification_channels kind to the allowlist

Revision ID: a2c7f1e33fe7
Revises: 9f3cd187d023
Create Date: 2026-07-29 22:17:29.778074

"""
from typing import Sequence, Union

from alembic import op

from proxploy.models import notification_kind_check_sql

# revision identifiers, used by Alembic.
revision: str = 'a2c7f1e33fe7'
down_revision: Union[str, Sequence[str], None] = '9f3cd187d023'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# `kind` (doc 04) is an unencrypted label parsed only from a fixed allowlist
# of URL schemes (proxploy.models.KIND_FROM_SCHEME / ALLOWED_NOTIFICATION_KINDS)
#, a prior fix made the Python-level parser (`notifier.kind_for`) an
# allowlist so it can never echo a caller-supplied Apprise URL (which embeds
# secrets) into this column. This migration makes that guarantee structural:
# even a future writer that bypasses `kind_for` entirely (raw SQL, a stray
# ORM assignment) is rejected by the database itself. Condition text is
# imported from `proxploy.models` rather than hand-copied so the migration
# and the model can never independently drift from the allowlist.
CONSTRAINT_NAME = "ck_notification_channels_kind_allowlist"


def upgrade() -> None:
    """Upgrade schema."""
    # SQLite has no ALTER TABLE ADD CONSTRAINT: batch mode recreates the
    # table (reflecting existing columns/indexes/FKs) under the hood. On
    # Postgres, batch mode is a plain in-place ALTER TABLE ADD CONSTRAINT.
    with op.batch_alter_table('notification_channels') as batch_op:
        batch_op.create_check_constraint(CONSTRAINT_NAME, notification_kind_check_sql())


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('notification_channels') as batch_op:
        batch_op.drop_constraint(CONSTRAINT_NAME, type_='check')
