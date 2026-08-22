"""notification channel fields, so an edit can prefill

A channel stored only its assembled Apprise URL, encrypted. That is enough to
send with and not enough to edit with: correcting one mistyped password meant
re-entering the server, the topic and everything else, because the individual
values were never kept.

Parsing them back out of the URL is lossy (build_url strips empty trailing
segments, values are percent-encoded, and a value containing the separator is
ambiguous), so the values are stored alongside instead, as an encrypted JSON
object under the same key.

This is not new exposure. The URL in `url_enc` already contains every one of
these secrets, encrypted with the same key, in the same database. What stays
true is the API contract: `_out` never returns a secret, and the read endpoint
returns non-secret values with secret ones reported only as "set".

Nullable, and no backfill: rows written before this keep behaving exactly as
they did, and the edit form says so rather than pretending it knows them.

Revision ID: c9f2a41b7e63
Revises: b8e35c07d4a1
Create Date: 2026-08-22

"""
from alembic import op
import sqlalchemy as sa

revision = "c9f2a41b7e63"
down_revision = "b8e35c07d4a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notification_channels",
                  sa.Column("fields_enc", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column("notification_channels", "fields_enc")
