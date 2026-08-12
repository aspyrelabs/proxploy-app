"""capability-encoded api_token kind

Renames the single `host_credentials.kind = "api_token"` row an existing
host has into `"api_token:monitoring"`. This is a rename, not a restructure:
`encrypted_blob`/`key_version`/`public_meta`/`last_used_at` all carry over
untouched, because the token that used to be "the one token" is, by
definition, whatever the operator granted every privilege they had at
enrolment time, which already had to include monitoring (a token missing
monitoring privileges would already have been reporting the host
unreachable/degraded before this migration ever runs).

No new column: `UniqueConstraint(host_id, kind)` already gives "one
credential per (host, dimension)" for free once `kind` carries the
capability, so `"api_token:lifecycle"` / `"api_token:console"` /
`"api_token:backup"` are simply rows that do not exist yet for an upgraded
host. That is "not configured", the same state a fresh install reaches by
ticking only Read-only monitoring in the wizard, not a broken state.
Nothing else about the row, or what the token can already do on the PVE
side, changes: this migration touches Proxploy's own bookkeeping of which
capability a stored credential belongs to, never the token itself.

Revision ID: b4d7c9e21a35
Revises: aef437ae90d2
Create Date: 2026-08-12

"""
from alembic import op

revision = "b4d7c9e21a35"
down_revision = "aef437ae90d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE host_credentials SET kind = 'api_token:monitoring' "
        "WHERE kind = 'api_token'")


def downgrade() -> None:
    # The reverse rename. Any lifecycle/console/backup rows an operator
    # added after upgrading have no pre-migration equivalent kind to fold
    # back into a single slot, so they are left as-is; a downgrade to the
    # single-token model was never going to be lossless once more than one
    # capability's token exists, and silently discarding a stored credential
    # here would be worse than leaving an extra row the old code ignores.
    op.execute(
        "UPDATE host_credentials SET kind = 'api_token' "
        "WHERE kind = 'api_token:monitoring'")
