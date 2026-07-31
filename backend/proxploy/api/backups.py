# backend/proxploy/api/backups.py
"""Backups page endpoints (doc 05 §Backups, doc 01 §7).

The list is served from the `backups` cache table, never live from Proxmox —
listing storage content is a per-storage call and this page is polled. The
`backup.sync` job is what fills it, and the GET below fires one when the cache
has gone stale so a fresh install is never permanently blank.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request

from proxploy.api.deps import get_db, require_entitlement, require_role
from proxploy.models import Backup, Host, User, utcnow
from proxploy.services.backupjobs import SYNCED_AT_KEY, sync_in_flight
from proxploy.services.settings import get_setting

router = APIRouter(prefix="/backups", tags=["backups"])

# Singleton first in dependencies=[...] and reused as the parameter dep so
# FastAPI collapses them and auth runs before the entitlement check
# (test_route_auth_invariant.py).
_require_viewer = require_role("viewer")

# GET /backups is polled every 60s and may be open in several browser tabs at
# once; each hit lands in a different FastAPI threadpool thread. A bare
# check-then-enqueue races: N threads can all see "no sync in flight" before
# any of their Job rows commit, producing N duplicate jobs hammering PVE. This
# lock serializes the check+enqueue pair so only one wins.
# ponytail: process-wide lock, one row (`backup.sync`) worth of contention.
# Upgrade to a DB-level advisory lock only if Proxploy ever runs >1 process.
_sync_enqueue_lock = threading.Lock()


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def _backup_out(b: Backup, host_name: str | None) -> dict:
    return {
        "id": b.id, "host_id": b.host_id, "host_name": host_name,
        "storage": b.storage, "volid": b.volid,
        "guest_type": b.guest_type, "guest_vmid": b.guest_vmid,
        "guest_name": b.guest_name, "taken_at": _iso(b.taken_at),
        "size_bytes": b.size_bytes, "verify_state": b.verify_state,
        "notes": b.notes,
    }


def _last_sync(db) -> datetime | None:
    raw = get_setting(db, SYNCED_AT_KEY)
    if raw:
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            pass
    return None


@router.get("", dependencies=[Depends(_require_viewer),
                              Depends(require_entitlement("backups.pbs"))])
def list_backups(request: Request, db=Depends(get_db),
                 user: User = Depends(_require_viewer)):
    hosts = {h.id: h.name for h in db.query(Host).all()}
    rows = db.query(Backup).order_by(Backup.taken_at.desc()).all()
    synced_at = _last_sync(db) or max((b.synced_at for b in rows if b.synced_at),
                                      default=None)
    stale_s = request.app.state.settings.backup_sync_stale_s
    stale = synced_at is None or (utcnow() - synced_at).total_seconds() > stale_s
    if stale:
        with _sync_enqueue_lock:
            if not sync_in_flight(db):
                request.app.state.jobs.enqueue(
                    db, kind="backup.sync", target_type="system",
                    params={}, requested_by=user.id)

    cutoff = utcnow() - timedelta(days=30)
    recent = [b for b in rows if b.taken_at and b.taken_at >= cutoff]
    ok_30d = sum(1 for b in recent if b.verify_state == "ok")
    bad_30d = sum(1 for b in recent if b.verify_state == "failed")
    datastores: dict[str, dict] = {}
    for b in rows:
        d = datastores.setdefault(b.storage or "-", {"storage": b.storage or "-",
                                                     "count": 0, "size_bytes": 0})
        d["count"] += 1
        d["size_bytes"] += b.size_bytes or 0
    return {
        "backups": [_backup_out(b, hosts.get(b.host_id)) for b in rows],
        "stats": {
            "total": len(rows),
            "total_bytes": sum(b.size_bytes or 0 for b in rows),
            "ok_count": sum(1 for b in rows if b.verify_state == "ok"),
            "failed_count": sum(1 for b in rows if b.verify_state == "failed"),
            # verify_state is the only per-archive success signal Proxmox
            # exposes. Unverified archives are excluded from the denominator
            # rather than counted as either outcome, so a datastore with
            # verification switched off reports None instead of a fake 100%.
            "success_rate_30d": (round(ok_30d / (ok_30d + bad_30d) * 100, 1)
                                 if (ok_30d + bad_30d) else None),
            "datastores": sorted(datastores.values(), key=lambda d: -d["size_bytes"]),
        },
        "synced_at": _iso(synced_at),
        "stale": stale,
    }
