"""Append-only audit writer (docs 04/08 §7). There is deliberately no update or
delete function in this module, archival is a Phase-8+ export job, never mutation."""
from proxploy.models import AuditEvent

REDACT_KEYS = {"password", "secret", "token_secret", "token", "key",
               "license_key", "refresh_credential", "totp"}

# Exact membership alone is a near-miss away from a leak: `token_id` carries a
# pasted `PVEAPIToken=user@realm!name=<secret>`, and `apprise_url` / `db_url` /
# `dsn` / `secret_key` would all have sailed past `k.lower() in REDACT_KEYS`
# into the unencrypted `audit_events.params` column and out of GET /audit.
# These substrings redact the whole family in one rule. Deliberately NOT "key":
# `settings.update` audits `{"keys": [...]}`: the *names* of the settings
# changed, never their values: and that is worth keeping legible.
REDACT_SUBSTRINGS = ("secret", "password", "passwd", "token", "credential",
                     "url", "dsn", "private")


def _is_secret_key(k: str) -> bool:
    k = k.lower()
    return k in REDACT_KEYS or any(m in k for m in REDACT_SUBSTRINGS)


def redact(obj):
    if isinstance(obj, dict):
        return {k: "[redacted]" if _is_secret_key(k) else redact(v)
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def write_audit(db, *, actor_type: str, action: str, actor_id: int | None = None,
                target_type: str | None = None, target_id: int | None = None,
                params: dict | None = None, result: str = "ok",
                ip: str | None = None, request_id: str | None = None,
                job_id: int | None = None) -> None:
    db.add(AuditEvent(actor_type=actor_type, actor_id=actor_id, action=action,
                      target_type=target_type, target_id=target_id,
                      params=redact(params) if params else None, result=result,
                      ip=ip, request_id=request_id, job_id=job_id))
    db.commit()
