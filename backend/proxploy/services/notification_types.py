"""Which notification type owns which job outcome.

Twenty rows, not one per job kind: eleven of the 33 registered kinds earn a
named row; the other 22 fall through to the generic Job rows. The catch-all is
load-bearing — without it, adding a job kind would silently stop notifying.
Each kind owns two of the four terminal outcomes; cancel and interrupt are
global rows, because a cancelled app install firing against both
`app.install.failed` and `job.canceled` is the double-notify this mapping
prevents.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NotificationType:
    key: str
    label: str
    group: str
    default_on: bool = True


TYPES: tuple[NotificationType, ...] = (
    NotificationType("app.install.failed", "App install failed", "Apps"),
    NotificationType("app.install.succeeded", "App install succeeded", "Apps"),
    NotificationType("app.update.failed", "App update failed", "Apps"),
    NotificationType("app.update.succeeded", "App update succeeded", "Apps"),
    NotificationType("app.uninstall.failed", "App removal failed", "Apps"),
    NotificationType("app.uninstall.succeeded", "App removal succeeded", "Apps"),
    NotificationType("backup.failed", "Backup failed", "Backups"),
    NotificationType("backup.succeeded", "Backup succeeded", "Backups"),
    NotificationType("backup.restore.failed", "Restore failed", "Backups"),
    NotificationType("backup.restore.succeeded", "Restore succeeded", "Backups"),
    NotificationType("housekeeping.failed", "Housekeeping failed",
                     "Housekeeping", default_on=False),
    NotificationType("housekeeping.succeeded", "Housekeeping succeeded",
                     "Housekeeping", default_on=False),
    NotificationType("job.failed", "Job failed", "Other jobs"),
    NotificationType("job.succeeded", "Job succeeded", "Other jobs"),
    NotificationType("job.canceled", "Job cancelled", "Other jobs"),
    NotificationType("job.interrupted", "Job interrupted", "Other jobs"),
    NotificationType("alert.fired", "Alert triggered", "Alerts"),
    NotificationType("alert.resolved", "Alert resolved", "Alerts"),
    NotificationType("audit.error", "Audited action failed", "Audit"),
    NotificationType("update.available", "Update available", "Housekeeping"),
    NotificationType("catalog.apps_unavailable",
                     "Apps can no longer be installed", "App Store"),
    NotificationType("catalog.apps_available",
                     "New apps can be installed", "App Store"),
)

BY_KEY: dict[str, NotificationType] = {t.key: t for t in TYPES}
DEFAULTS: dict[str, bool] = {t.key: t.default_on for t in TYPES}

# Job kind to the row prefix that owns its failed/succeeded outcomes. A kind
# absent here is not a bug, it is the 22 that belong to the generic rows.
_KIND_PREFIX: dict[str, str] = {
    "app.install": "app.install",
    "app.update": "app.update",
    "app.uninstall": "app.uninstall",
    "backup.run": "backup",
    "backup.restore": "backup.restore",
    # The built-in system schedules, plus backup retention work on the
    # same unattended footing. `backup.sync` sits under "housekeeping", not
    # "backup": nobody asks for one, GET /backups enqueues it whenever the
    # cache is stale (api/backups.py::list_backups), so filing it as a backup
    # outcome toasted "Backup Sync Succeeded" at anyone on the Backups page.
    "catalog.refresh": "housekeeping",
    "catalog.classify_backlog": "housekeeping",
    "metrics.maintain": "housekeeping",
    "backup.sync": "housekeeping",
    "backup.delete": "housekeeping",
    "backup.prune": "housekeeping",
    "sessions.cleanup": "housekeeping",
    "jobs.prune": "housekeeping",
    "db.compact": "housekeeping",
    "update.check": "housekeeping",
}

# Cancel and interrupt are never categorised, whatever the kind.
_GLOBAL_ONLY = {"canceled": "job.canceled", "interrupted": "job.interrupted"}


def type_for_job(kind: str, status: str) -> str:
    """Which registry row owns this job outcome. Total: every (kind, status)
    resolves, so a kind nobody mapped notifies generically rather than not at
    all."""
    if status in _GLOBAL_ONLY:
        return _GLOBAL_ONLY[status]
    return f"{_KIND_PREFIX.get(kind, 'job')}.{status}"
