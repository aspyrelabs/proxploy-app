"""Append-only audit writer (docs 04/08 §7). There is deliberately no update or
delete function in this module, archival is a Phase-8+ export job, never mutation."""
import logging

from proxploy.models import (AlertRule, ApiKey, App, AuditEvent, Backup, Host,
                             Job, NotificationChannel, Schedule, Team, User, Vm)

# target_type -> (model, the column that holds its human name). One map, used
# to capture a row's name when it is written (resolve_target_name below), to
# label a row's Item column in api/audit.py, and to turn that screen's "item or
# action" search box back into ids, so the box can never match an item the
# column does not name.
#
# Deliberately no "storage": those rows carry the HOST's id in target_id
# (api/storage.py), so labelling them from either table would print a name that
# is wrong or right by accident. Those two routes pass their own name instead.
# Same reason "session", "alert" and "system" are absent: nothing there is a
# name a person would recognise.
logger = logging.getLogger(__name__)

TARGET_LABELS = {
    "host": (Host, Host.name),
    "app": (App, App.name),
    "vm": (Vm, Vm.name),
    "user": (User, User.email),
    "team": (Team, Team.name),
    "schedule": (Schedule, Schedule.name),
    "notification_channel": (NotificationChannel, NotificationChannel.name),
    "alert_rule": (AlertRule, AlertRule.name),
    "backup": (Backup, Backup.volid),
    # A revoked key is deleted from nobody's screen but its rows outlive it,
    # and "api_key #3" names nothing: the key someone revoked in a hurry is
    # exactly the row an audit reader comes back for.
    "api_key": (ApiKey, ApiKey.name),
}


def resolve_target_name(db, target_type: str | None,
                        target_id: int | None) -> str | None:
    """The name of the thing a job or audit row is about, read RIGHT NOW.

    Called from the two write paths (JobBackend.enqueue and write_audit), both
    of which run before the work does. That ordering is the whole point: a
    destroy job is enqueued while the guest row still exists, so the name is
    captured before the thing that owns it is deleted. Resolving at render time
    instead is what left the history reading "vm 3" for the one case where the
    name can never be recovered.

    Returns None for a target with no human name, and for one that is already
    gone; callers store the None and the UI falls back to "type id".
    """
    if not target_type or target_id is None:
        return None
    # A job's own name is its kind ("vm.delete"), which is not in TARGET_LABELS
    # because it is not the sort of name the audit screen's Item column wants.
    if target_type == "job":
        job = db.get(Job, target_id)
        return job.kind if job is not None else None
    entry = TARGET_LABELS.get(target_type)
    if entry is None:
        return None
    model, name_col = entry
    row = db.get(model, target_id)
    if row is None:
        return None
    name = (getattr(row, name_col.key, None) or "").strip()
    if name:
        return name
    # An unnamed guest is still worth naming by the id Proxmox shows it under.
    if target_type == "vm":
        return f"VM {row.vmid}"
    if target_type == "app":
        return f"CT {row.ctid}"
    return None

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
                job_id: int | None = None,
                target_name: str | None = None, app=None) -> None:
    """`target_name` is resolved from the target here unless the caller passes
    one, so a route cannot forget to record what it acted on. Pass it only
    where the target has no name of its own to look up, e.g. a storage row
    whose target_id is a host id.

    `app` is optional and only enables the `audit.error` notification. Most
    call sites have no app handle, and auditing must never depend on being
    able to notify, so its absence means a silent row rather than an error."""
    db.add(AuditEvent(actor_type=actor_type, actor_id=actor_id, action=action,
                      target_type=target_type, target_id=target_id,
                      target_name=target_name or resolve_target_name(
                          db, target_type, target_id),
                      params=redact(params) if params else None, result=result,
                      ip=ip, request_id=request_id, job_id=job_id))
    db.commit()
    app = app or db.info.get("app")
    if app is not None and result == "error" and action not in _NOT_OPERATIONAL:
        _notify_error(app, action, target_name)


# A failed sign-in is a security event, not an operational failure, and one
# fat-fingered password would page whoever owns the channel. The audit row
# still records every one of these; only the notification is withheld.
_NOT_OPERATIONAL = frozenset({
    "auth.login", "auth.login.totp_pending", "oidc.jit_provision.pending",
})


def _notify_error(app, action: str, target_name: str | None) -> None:
    """The row is the record and the notification is a courtesy, so a broken
    channel must never cost the record. Fired after the commit, and swallowed
    whole."""
    from proxploy.services.notifier import notify

    subject = f"{action} on {target_name}" if target_name else action
    try:
        notify(app, "audit.error", f"Proxploy: {action} failed",
               f"{subject} did not complete.")
    except Exception:  # noqa: BLE001  (a courtesy never breaks the record)
        logger.debug("audit error notification failed for %s", action,
                     exc_info=True)
