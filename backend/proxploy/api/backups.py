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
from typing import Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel

from proxploy.api.deps import get_db, require_entitlement, require_role
from proxploy.api.jobs import enqueue_and_audit
from proxploy.models import App, Backup, Host, User, Vm, utcnow
from proxploy.services.backupjobs import SYNCED_AT_KEY, sync_in_flight
from proxploy.services.audit import write_audit
from proxploy.services.hostclient import client_for_host
from proxploy.services.selfguard import is_self
from proxploy.services.settings import get_setting

router = APIRouter(prefix="/backups", tags=["backups"])

# Singleton first in dependencies=[...] and reused as the parameter dep so
# FastAPI collapses them and auth runs before the entitlement check
# (test_route_auth_invariant.py).
_require_viewer = require_role("viewer")
_require_operator = require_role("operator")
_require_admin = require_role("admin")

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


# --- mutations (Phase 6 Task 9) ---------------------------------------------
# Literal-segment routes (/run, /prune-preview, /prune) are declared BEFORE any
# /{backup_id} route — Starlette matches path operations in registration order,
# so a numeric-looking literal segment must never land after a param route.

class GuestRef(BaseModel):
    type: str  # "app" | "vm" — Proxploy row ids, never raw vmids
    id: int


class RunIn(BaseModel):
    guests: list[GuestRef] | Literal["all"] = "all"
    host_id: int | None = None
    storage: str | None = None
    mode: str = "snapshot"
    compress: str = "zstd"


def _resolve_guests(db, body: RunIn) -> tuple[int, list[int]]:
    """-> (host_id, vmids). One vzdump call runs on one node, so a selection
    spanning hosts is a client error, not a silent partial backup."""
    if body.guests == "all":
        hosts = db.query(Host).all()
        if body.host_id is None:
            if len(hosts) != 1:
                raise HTTPException(422, "host_id is required when more than one "
                                         "host is registered")
            return hosts[0].id, []
        if db.get(Host, body.host_id) is None:
            raise HTTPException(404, "host not found")
        return body.host_id, []
    vmids: list[int] = []
    host_ids: set[int] = set()
    for g in body.guests:
        if g.type == "app":
            row = db.get(App, g.id)
            vmid = row.ctid if row else None
        elif g.type == "vm":
            row = db.get(Vm, g.id)
            vmid = row.vmid if row else None
        else:
            raise HTTPException(422, "guest type must be 'app' or 'vm'")
        if row is None:
            raise HTTPException(404, f"{g.type} {g.id} not found")
        vmids.append(int(vmid))
        host_ids.add(row.host_id)
    if not vmids:
        raise HTTPException(422, "select at least one guest, or pass guests='all'")
    if len(host_ids) != 1:
        raise HTTPException(422, "every guest in one backup run must live on the "
                                 "same host")
    return host_ids.pop(), vmids


@router.post("/run", status_code=202,
             dependencies=[Depends(_require_operator),
                           Depends(require_entitlement("backups.run"))])
def run_backup_route(request: Request, body: RunIn = Body(default=RunIn()),
                     db=Depends(get_db), user: User = Depends(_require_operator)):
    host_id, vmids = _resolve_guests(db, body)
    return enqueue_and_audit(request, db, user, kind="backup.run",
                             target_type="host", target_id=host_id,
                             params={"host_id": host_id, "vmids": vmids,
                                     "storage": body.storage, "mode": body.mode,
                                     "compress": body.compress})


class RestoreIn(BaseModel):
    mode: str = "new"  # "new" | "in_place"
    storage: str | None = None
    confirm: str | None = None


def _guest_for(db, b: Backup):
    """The live guest a backup came from, if it still exists -> (row, name)."""
    if b.guest_type == "ct":
        row = db.query(App).filter_by(host_id=b.host_id, ctid=b.guest_vmid).one_or_none()
    else:
        row = db.query(Vm).filter_by(host_id=b.host_id, vmid=b.guest_vmid).one_or_none()
    if row is None:
        return None, ""
    return row, row.name or f"{b.guest_type}-{b.guest_vmid}"


@router.post("/{backup_id}/restore", status_code=202,
             dependencies=[Depends(_require_admin),
                           Depends(require_entitlement("backups.restore"))])
def restore_backup_route(request: Request, backup_id: int,
                         body: RestoreIn = Body(default=RestoreIn()),
                         db=Depends(get_db), user: User = Depends(_require_admin)):
    b = db.get(Backup, backup_id)
    if b is None:
        raise HTTPException(404, "backup not found")
    if body.mode not in ("new", "in_place"):
        raise HTTPException(422, "mode must be 'new' or 'in_place'")
    ip = request.client.host if request.client else None
    if body.mode == "in_place":
        # In place means force=1 over the guest's own vmid: the existing disk is
        # replaced. Restore-as-new takes a fresh id from cluster_nextid() and
        # touches nothing live, which is why it needs none of this.
        guest, name = _guest_for(db, b)
        if guest is None:
            raise HTTPException(409, {
                "error": "guest_missing",
                "detail": (f"{b.guest_type} {b.guest_vmid} no longer exists on this "
                           f"host — restore as new instead.")})
        if isinstance(guest, App) and is_self(db, "app", guest.id):
            # Unlike enqueue_lifecycle's confirmable stop, this one is refused
            # outright: an in-place restore over Proxploy's own CT destroys the
            # container running the job that is performing the restore, so there
            # is no phrase that makes it survivable. The response keeps the
            # familiar self_target shape so the UI can name the target; the
            # front end shows `detail`, not a confirm box, for this case.
            write_audit(db, actor_type="user", actor_id=user.id,
                        action="backup.restore", target_type="backup",
                        target_id=b.id, result="denied", ip=ip)
            raise HTTPException(409, {
                "error": "self_target", "confirm_phrase": name,
                "detail": (f"{name} is the container Proxploy itself runs in. An "
                           f"in-place restore would overwrite Proxploy mid-restore "
                           f"and strand the job doing it. Restore as new instead.")})
        if (body.confirm or "") != name:
            raise HTTPException(409, {
                "error": "confirm_required", "confirm_phrase": name,
                "detail": (f"An in-place restore overwrites {name} with the contents "
                           f"of this backup. Type the name to confirm.")})
        status = getattr(guest, "status_cached", None) or getattr(guest, "status", None)
        if status == "running":
            raise HTTPException(409, {
                "error": "guest_running",
                "detail": f"stop {name} before restoring over it"})
    return enqueue_and_audit(request, db, user, kind="backup.restore",
                             target_type="backup", target_id=b.id,
                             params={"backup_id": b.id, "mode": body.mode,
                                     "storage": body.storage})


# services/selfguard.py is deliberately untouched by this task: DESTRUCTIVE
# holds guest *lifecycle verbs* and its only consumer is enqueue_lifecycle,
# which backup routes never call — see this task's brief header note.
# test_selfguard_destructive_set_is_unchanged locks it.

KEEP_FIELDS = ("keep_last", "keep_daily", "keep_weekly", "keep_monthly", "keep_yearly")


def _prune_spec(values: dict) -> str:
    """`{"keep_last": 3, "keep_daily": 7}` -> `"keep-last=3,keep-daily=7"`.

    Refuses an empty spec: PVE reads no keep-* rules as "keep nothing", so a
    dropped form field would mark every archive `remove`.
    """
    parts = [f"{k.replace('_', '-')}={int(v)}" for k in KEEP_FIELDS
             if (v := values.get(k))]
    if not parts:
        raise HTTPException(422, "at least one keep-* retention value is required")
    return ",".join(parts)


def _prune_call(spec: str, guest_type: str | None, vmid: int | None) -> dict:
    call = {"prune-backups": spec}  # hyphenated -> dict unpack, never a kwarg
    if guest_type:
        call["type"] = guest_type
    if vmid:
        call["vmid"] = int(vmid)
    return call


@router.get("/prune-preview",
            dependencies=[Depends(_require_admin),
                          Depends(require_entitlement("backups.retention"))])
def prune_preview_route(request: Request, host_id: int, storage: str,
                        node: str | None = None, keep_last: int | None = None,
                        keep_daily: int | None = None, keep_weekly: int | None = None,
                        keep_monthly: int | None = None, keep_yearly: int | None = None,
                        guest_type: str | None = None, vmid: int | None = None,
                        db=Depends(get_db), user: User = Depends(_require_admin)):
    """Dry run. Calls the GET verb only — this endpoint cannot delete anything;
    POST /backups/prune is the one that does."""
    host = db.get(Host, host_id)
    if host is None:
        raise HTTPException(404, "host not found")
    spec = _prune_spec({"keep_last": keep_last, "keep_daily": keep_daily,
                        "keep_weekly": keep_weekly, "keep_monthly": keep_monthly,
                        "keep_yearly": keep_yearly})
    client = client_for_host(request.app, db, host)
    rows = client.prune_preview(node or host.node_name or "", storage,
                                _prune_call(spec, guest_type, vmid))
    return [{"volid": r.get("volid"), "type": r.get("type"), "vmid": r.get("vmid"),
             "ctime": r.get("ctime"), "mark": r.get("mark")} for r in rows]


class PruneIn(BaseModel):
    host_id: int
    storage: str
    node: str | None = None
    keep_last: int | None = None
    keep_daily: int | None = None
    keep_weekly: int | None = None
    keep_monthly: int | None = None
    keep_yearly: int | None = None
    guest_type: str | None = None
    vmid: int | None = None


@router.post("/prune", status_code=202,
             dependencies=[Depends(_require_admin),
                           Depends(require_entitlement("backups.retention"))])
def prune_route(request: Request, body: PruneIn, db=Depends(get_db),
                user: User = Depends(_require_admin)):
    if db.get(Host, body.host_id) is None:
        raise HTTPException(404, "host not found")
    spec = _prune_spec(body.model_dump())
    return enqueue_and_audit(request, db, user, kind="backup.prune",
                             target_type="host", target_id=body.host_id,
                             params={"host_id": body.host_id, "node": body.node,
                                     "storage": body.storage, "spec": spec,
                                     "guest_type": body.guest_type,
                                     "vmid": body.vmid})


@router.delete("/{backup_id}", status_code=202,
               dependencies=[Depends(_require_admin),
                             Depends(require_entitlement("backups.pbs"))])
def delete_backup_route(request: Request, backup_id: int, db=Depends(get_db),
                        user: User = Depends(_require_admin)):
    b = db.get(Backup, backup_id)
    if b is None:
        raise HTTPException(404, "backup not found")
    return enqueue_and_audit(request, db, user, kind="backup.delete",
                             target_type="backup", target_id=b.id,
                             params={"backup_id": b.id, "volid": b.volid})
