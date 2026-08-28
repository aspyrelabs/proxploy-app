"""Backups page endpoints.

The list is served from the `backups` cache table, never live from Proxmox;
listing storage content is a per-storage call and this page is polled. The
`backup.sync` job fills it, and the GET below fires one when the cache is
stale so a fresh install is never permanently blank.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func

from proxploy.api.deps import authorize, get_db, require_entitlement, scope_backup
from proxploy.api.jobs import enqueue_and_audit
from proxploy.models import App, Backup, Host, Job, User, Vm, to_iso, utcnow
from proxploy.services.backupjobs import SYNCED_AT_KEY, sync_in_flight
from proxploy.services.audit import write_audit
from proxploy.services.hostclient import client_for_host
from proxploy.services.proxmox import ProxmoxError
from proxploy.services.selfguard import is_self
from proxploy.services.settings import get_setting

router = APIRouter(prefix="/backups", tags=["backups"])

# Singleton first in dependencies=[...] and reused as the parameter dep so
# FastAPI collapses them and auth runs before the entitlement check.
# host_id/backup_id arrive as a body field or a query param on every route
# below except restore/delete, which carry {backup_id} in the path:
# scope_backup()'s default param matches it.
_read = authorize("backup", "read")
_run = authorize("backup", "run")                 # host_id is body-carried
_restore = authorize("backup", "restore", scope_of=scope_backup())
_manage = authorize("backup", "manage")            # prune/preview: host_id is body/query
_manage_scoped = authorize("backup", "manage", scope_of=scope_backup())

# GET /backups is polled every 60s and may be open in several browser tabs at
# once; each hit lands in a different FastAPI threadpool thread. A bare
# check-then-enqueue races: N threads can all see "no sync in flight" before
# any of their Job rows commit, producing N duplicate jobs hammering PVE. This
# lock serializes the check+enqueue pair so only one wins.
# ponytail: process-wide lock, one row (`backup.sync`) worth of contention.
# Upgrade to a DB-level advisory lock only if Proxploy ever runs >1 process.
_sync_enqueue_lock = threading.Lock()


def _backup_out(b: Backup, host_name: str | None) -> dict:
    return {
        "id": b.id, "host_id": b.host_id, "host_name": host_name,
        "storage": b.storage, "volid": b.volid, "node": b.node,
        "guest_type": b.guest_type, "guest_vmid": b.guest_vmid,
        "guest_name": b.guest_name, "taken_at": to_iso(b.taken_at),
        "size_bytes": b.size_bytes, "verify_state": b.verify_state,
        "checked_at": to_iso(b.checked_at),
        "notes": b.notes,
    }


def _last_sync(db) -> datetime | None:
    raw = get_setting(db, SYNCED_AT_KEY)
    if raw:
        try:
            dt = datetime.fromisoformat(raw)
            # Stored via to_iso(), which appends "Z" -> aware. Every other
            # datetime in this module is naive UTC (utcnow()'s convention),
            # so this strips the offset right back off rather than making
            # the one arithmetic site below handle both.
            return dt.replace(tzinfo=None) if dt.tzinfo else dt
        except ValueError:
            pass
    return None


BACKUPS_MAX = 200


def _stats(db) -> dict:
    """The summary block, computed with aggregates over the WHOLE table.

        Not derived from the clamped page of rows the route returns: a datastore
        with a year of daily archives is thousands of rows, and totals counted
        from the newest 200 would quietly under-report every number on the page.
        """
    stores: dict[str, dict] = {}
    for storage, count, size in (db.query(Backup.storage, func.count(Backup.id),
                                          func.coalesce(func.sum(Backup.size_bytes), 0))
                                 .group_by(Backup.storage)):
        # `or "-"` matches the old per-row key, so NULL and "" still merge.
        d = stores.setdefault(storage or "-", {"storage": storage or "-",
                                               "count": 0, "size_bytes": 0})
        d["count"] += count
        d["size_bytes"] += int(size)
    by_state = dict(db.query(Backup.verify_state, func.count(Backup.id))
                    .group_by(Backup.verify_state))
    cutoff = utcnow() - timedelta(days=30)
    recent = dict(db.query(Backup.verify_state, func.count(Backup.id))
                  .filter(Backup.taken_at >= cutoff)
                  .group_by(Backup.verify_state))
    ok_30d, bad_30d = recent.get("ok", 0), recent.get("failed", 0)
    # The fallback for a PVE-only setup. `verify_state` is written by Proxmox
    # BACKUP SERVER and by nothing else, so on a plain NFS or directory store
    # every archive is "none" for ever and the rate above is null on a system
    # whose backups are running fine. A succeeded run that wrote NOTHING is
    # excluded from both sides rather than counted as a win: vzdump over a node
    # with no guests finishes exitstatus OK having written zero bytes. Runs from
    # before `guests` was recorded are counted, since "no answer" is not the same
    # as "wrote nothing".
    run_ok = run_bad = 0
    for status, result in db.query(Job.status, Job.result).filter(
            Job.kind == "backup.run", Job.created_at >= cutoff,
            Job.status.in_(("succeeded", "failed"))):
        if status == "failed":
            run_bad += 1
        elif (result or {}).get("guests") != 0:
            run_ok += 1
    return {
        "total": sum(d["count"] for d in stores.values()),
        "total_bytes": sum(d["size_bytes"] for d in stores.values()),
        "ok_count": by_state.get("ok", 0),
        "failed_count": by_state.get("failed", 0),
        # verify_state is the only per-archive success signal Proxmox
        # exposes. Unverified archives are excluded from the denominator
        # rather than counted as either outcome, so a datastore with
        # verification switched off reports None instead of a fake 100%.
        "success_rate_30d": (round(ok_30d / (ok_30d + bad_30d) * 100, 1)
                             if (ok_30d + bad_30d) else None),
        "runs_ok_30d": run_ok,
        "runs_failed_30d": run_bad,
        "run_rate_30d": (round(run_ok / (run_ok + run_bad) * 100, 1)
                         if (run_ok + run_bad) else None),
        "datastores": sorted(stores.values(), key=lambda d: -d["size_bytes"]),
    }


@router.get("", dependencies=[Depends(_read),
                              Depends(require_entitlement("backups.pbs"))])
def list_backups(request: Request, db=Depends(get_db), limit: int = BACKUPS_MAX,
                 user: User = Depends(_read)):
    # Same clamp the other list reads use (audit.py, jobs.py, alerts.py,
    # cluster.py). A PBS datastore with a year of daily per-guest snapshots is
    # tens of thousands of rows. The newest `limit` are what the "Recent backups"
    # table shows; `stats` below still covers everything.
    limit = max(1, min(limit, BACKUPS_MAX))
    hosts = {h.id: h.name for h in db.query(Host).all()}
    rows = db.query(Backup).order_by(Backup.taken_at.desc()).limit(limit).all()
    synced_at = _last_sync(db) or db.query(func.max(Backup.synced_at)).scalar()
    stale_s = request.app.state.settings.backup_sync_stale_s
    stale = synced_at is None or (utcnow() - synced_at).total_seconds() > stale_s
    if stale:
        with _sync_enqueue_lock:
            if not sync_in_flight(db):
                request.app.state.jobs.enqueue(
                    db, kind="backup.sync", target_type="system",
                    params={}, requested_by=user.id)

    return {
        "backups": [_backup_out(b, hosts.get(b.host_id)) for b in rows],
        "stats": _stats(db),
        "synced_at": to_iso(synced_at),
        "stale": stale,
    }


# Literal-segment routes (/run, /prune-preview, /prune) are declared BEFORE any
# /{backup_id} route: Starlette matches path operations in registration order,
# so a numeric-looking literal segment must never land after a param route.

class GuestRef(BaseModel):
    type: str  # "app" | "vm", Proxploy row ids, never raw vmids
    id: int


class RunIn(BaseModel):
    guests: list[GuestRef] | Literal["all"] = "all"
    host_id: int | None = None
    storage: str | None = None
    mode: str = "snapshot"
    compress: str = "zstd"
    # Chains a backup.verify per archive once the run has written them, rather
    # than checking inline: the backup's own result must not depend on it.
    verify: bool = False


def _resolve_guests(db, body: RunIn) -> tuple[int, list[int], list[str]]:
    """-> (host_id, vmids, names). One vzdump call runs on one node, so a
        selection spanning hosts is a client error, not a silent partial backup.

        `names` is empty for a whole-host run and carries one label per guest
        otherwise, so the job says what it is backing up rather than naming the
        node it runs on."""
    if body.guests == "all":
        hosts = db.query(Host).all()
        if body.host_id is None:
            if len(hosts) != 1:
                raise HTTPException(422, "host_id is required when more than one "
                                         "host is registered")
            return hosts[0].id, [], []
        if db.get(Host, body.host_id) is None:
            raise HTTPException(404, "host not found")
        return body.host_id, [], []
    vmids: list[int] = []
    names: list[str] = []
    host_ids: set[int] = set()
    for g in body.guests:
        if g.type == "app":
            row = db.get(App, g.id)
            vmid = row.ctid if row else None
            kind = "CT"
        elif g.type == "vm":
            row = db.get(Vm, g.id)
            vmid = row.vmid if row else None
            kind = "VM"
        else:
            raise HTTPException(422, "guest type must be 'app' or 'vm'")
        if row is None:
            raise HTTPException(404, f"{g.type} {g.id} not found")
        vmids.append(int(vmid))
        names.append(f"{row.name} ({kind} {vmid})")
        host_ids.add(row.host_id)
    if not vmids:
        raise HTTPException(422, "select at least one guest, or pass guests='all'")
    if len(host_ids) != 1:
        raise HTTPException(422, "every guest in one backup run must live on the "
                                 "same host")
    return host_ids.pop(), vmids, names


@router.post("/run", status_code=202,
             dependencies=[Depends(_run),
                           Depends(require_entitlement("backups.run"))])
def run_backup_route(request: Request, body: RunIn = Body(default=RunIn()),
                     db=Depends(get_db), user: User = Depends(_run)):
    host_id, vmids, names = _resolve_guests(db, body)
    # The job still RUNS on the host (one vzdump, one node), but what it is
    # about is the guests, and the feed reads target_name. Left alone for a
    # whole-host run, where the host IS the answer.
    target_name = None if not names else (
        ", ".join(names) if len(names) <= 3
        else f"{', '.join(names[:3])} and {len(names) - 3} more")
    return enqueue_and_audit(request, db, user, kind="backup.run",
                             target_type="host", target_id=host_id,
                             target_name=target_name,
                             params={"host_id": host_id, "vmids": vmids,
                                     "storage": body.storage, "mode": body.mode,
                                     "compress": body.compress,
                                     "verify": body.verify})


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
             dependencies=[Depends(_restore),
                           Depends(require_entitlement("backups.restore"))])
def restore_backup_route(request: Request, backup_id: int,
                         body: RestoreIn = Body(default=RestoreIn()),
                         db=Depends(get_db), user: User = Depends(_restore)):
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
                           f"host, restore as new instead.")})
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
        # A destructive overwrite must be refused unless the guest is
        # POSITIVELY known to be stopped: "we do not know" is not "it is
        # safe". This also catches "unknown", which is what a guest reads
        # once its host stops answering (see pollers._mark_unreachable), so
        # without this check the guard above would fall through and let an
        # in-place restore run during the exact window a guest might genuinely
        # still be running. That case gets its own message: telling someone
        # their guest is running when Proxploy actually cannot tell would be
        # false and would waste their time chasing the wrong guest.
        if status != "stopped":
            # Only None/"unknown" is a real "we can't tell" case caused by an
            # unreachable host. A guest in a known state like "paused" has a
            # reachable host (that is how the state was recorded) and a known
            # status, so pointing someone at host connectivity would be wrong;
            # name the actual state instead.
            if status in (None, "unknown"):
                detail = (f"Proxploy cannot currently tell whether {name} is "
                          f"running. This is usually because its host cannot be "
                          f"reached right now. Try again once the host is back.")
            else:
                detail = f"{name} is {status}, not stopped. Stop it before restoring over it."
            raise HTTPException(409, {"error": "guest_status_unknown", "detail": detail})
    # Resolve the tokens the handler will spend, BEFORE queueing. A restore
    # reads the archive on `backup` and writes the guest on `lifecycle` (it
    # creates one, so PVE checks VM.Allocate and SDN.Use), and a host missing
    # either used to accept the job and fail inside the handler. No network call
    # happens here: client_for_host raises CapabilityNotConfigured on a missing
    # credential alone, and main.py turns that into a 409 naming the capability
    # and where to add it.
    host = db.get(Host, b.host_id)
    if host is not None:
        for capability in ("backup", "lifecycle"):
            client_for_host(request.app, db, host, capability=capability)
    return enqueue_and_audit(request, db, user, kind="backup.restore",
                             target_type="backup", target_id=b.id,
                             params={"backup_id": b.id, "mode": body.mode,
                                     "storage": body.storage})


def _backup_or_404(db, backup_id: int) -> Backup:
    b = db.get(Backup, backup_id)
    if b is None:
        raise HTTPException(404, "backup not found")
    return b


def _refuse_on_pbs(request: Request, b: Backup) -> None:
    """Proxmox Backup Server verifies its own archives against stored digests,
    on its own schedule. Ours reads the whole thing back over the network and
    knows less, so offering it there would only overwrite a better verdict with
    a worse one. Per archive, not per install: PBS for the important guests and
    an NFS share for the rest is an ordinary layout."""
    refuse = lambda: HTTPException(  # noqa: E731
        409, "Proxmox Backup Server checks this archive itself, on its own "
             "schedule.")
    # The row's own type first: poller.snapshots is empty between boot and the
    # first poll, so in that window every archive looked like a plain store and a
    # PBS one was accepted for a full read-back. sync_host_backups records the
    # type PVE gave it.
    if b.storage_type:
        if b.storage_type == "pbs":
            raise refuse()
        return
    # NULL means synced before that column existed; the snapshot is the only
    # thing that knows, until the next sync fills the row in.
    snap = request.app.state.poller.snapshots.get(b.host_id)
    for st in (snap.storage if snap else []):
        if st.get("storage") == b.storage and (st.get("type") or "") == "pbs":
            raise refuse()


def _refuse_a_second_check(db, host_id: int) -> None:
    """One check per host at a time.

    A check reads the entire archive back off the datastore: 40 GB over 1GbE
    saturates the link for six minutes, and two at once on one host halve each
    other while doubling nothing. Serialising is the same reasoning
    `sync_in_flight` already applies to the sync sweep, applied at the door
    instead of in the handler, so the caller is told rather than silently
    queued behind something.
    """
    running = (db.query(Job)
               .filter(Job.kind.in_(("backup.verify", "backup.test_restore")),
                       Job.target_id == host_id,
                       Job.status.in_(("queued", "running")))
               .first())
    if running is not None:
        raise HTTPException(409, "A backup check is already running on this host. "
                                 "Wait for it to finish, it reads the whole "
                                 "archive back.")


class VerifySweepIn(BaseModel):
    host_id: int
    storage: str | None = None
    max: int | None = None


# BEFORE /{backup_id}/verify, and it has to stay there: FastAPI matches in
# declaration order, and "verify" would otherwise be tried as a backup_id and
# 422 on the path type.
@router.post("/verify", status_code=202, dependencies=[Depends(_run)])
def verify_sweep_route(request: Request, body: VerifySweepIn,
                       db=Depends(get_db), user: User = Depends(_run)):
    """Check the archives on one host that nobody has checked yet.

        The other half of "back up now, verify separately". `backup.verify` reads
        a missing `backup_id` as "sweep this host", oldest first, capped, PBS left
        alone.

        `_run`, matching the per-archive route.
        """
    host = db.get(Host, body.host_id)
    if host is None:
        raise HTTPException(404, "host not found")
    _refuse_a_second_check(db, host.id)
    params: dict = {"host_id": host.id}
    # Omitted rather than sent as null: the handler reads `params.get("max")`
    # against its own default, and a null would have to be special-cased there
    # instead of simply not being here.
    if body.storage:
        params["storage"] = body.storage
    if body.max is not None:
        params["max"] = body.max
    return enqueue_and_audit(request, db, user, kind="backup.verify",
                             target_type="host", target_id=host.id,
                             target_name=host.name, params=params)


@router.post("/{backup_id}/verify", status_code=202, dependencies=[Depends(_run)])
def verify_backup_route(request: Request, backup_id: int, db=Depends(get_db),
                        user: User = Depends(_run)):
    """Read one archive back and record whether it is intact.

    `_run`, the same permission a backup itself needs: this reads an archive
    and writes a verdict, and anyone allowed to create archives is allowed to
    find out whether they are any good.
    """
    b = _backup_or_404(db, backup_id)
    _refuse_on_pbs(request, b)
    _refuse_a_second_check(db, b.host_id)
    return enqueue_and_audit(request, db, user, kind="backup.verify",
                             target_type="host", target_id=b.host_id,
                             target_name=b.guest_name or b.volid,
                             params={"backup_id": b.id})


class TestRestoreIn(BaseModel):
    storage: str | None = None


@router.post("/{backup_id}/test-restore", status_code=202,
             dependencies=[Depends(_restore)])
def test_restore_route(request: Request, backup_id: int,
                       body: TestRestoreIn = Body(default=TestRestoreIn()),
                       db=Depends(get_db), user: User = Depends(_restore)):
    """Prove an archive by restoring it into a throwaway id.

    `_restore`, not `_run`: this really does create a guest, even though it
    deletes it again, so it needs the permission that creating one needs.
    """
    b = _backup_or_404(db, backup_id)
    _refuse_on_pbs(request, b)
    _refuse_a_second_check(db, b.host_id)
    # Same door restore_backup_route stands behind, and for the same reason: a
    # host missing the token accepted the job and then failed inside the handler.
    # `lifecycle` ALONE, unlike /restore, which also names `backup`: this one
    # creates a guest and never reads the archive itself, PVE does that, so asking
    # for a backup token here would refuse hosts that can run the job perfectly
    # well. No network call happens: client_for_host raises
    # CapabilityNotConfigured on a missing credential alone, and main.py turns that
    # into a 409 naming the capability and where to add it.
    host = db.get(Host, b.host_id)
    if host is not None:
        client_for_host(request.app, db, host, capability="lifecycle")
    return enqueue_and_audit(request, db, user, kind="backup.test_restore",
                             target_type="host", target_id=b.host_id,
                             target_name=b.guest_name or b.volid,
                             params={"backup_id": b.id, "storage": body.storage})



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
            dependencies=[Depends(_manage),
                          Depends(require_entitlement("backups.retention"))])
def prune_preview_route(request: Request, host_id: int, storage: str,
                        node: str | None = None, keep_last: int | None = None,
                        keep_daily: int | None = None, keep_weekly: int | None = None,
                        keep_monthly: int | None = None, keep_yearly: int | None = None,
                        guest_type: str | None = None, vmid: int | None = None,
                        db=Depends(get_db), user: User = Depends(_manage)):
    """Dry run. Calls the GET verb only: this endpoint cannot delete anything;
    POST /backups/prune is the one that does."""
    host = db.get(Host, host_id)
    if host is None:
        raise HTTPException(404, "host not found")
    spec = _prune_spec({"keep_last": keep_last, "keep_daily": keep_daily,
                        "keep_weekly": keep_weekly, "keep_monthly": keep_monthly,
                        "keep_yearly": keep_yearly})
    try:
        client = client_for_host(request.app, db, host, capability="backup")
        rows = client.prune_preview(node or host.node_name or "", storage,
                                    _prune_call(spec, guest_type, vmid))
    except ProxmoxError as e:
        raise HTTPException(502, str(e))
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
             dependencies=[Depends(_manage),
                           Depends(require_entitlement("backups.retention"))])
def prune_route(request: Request, body: PruneIn, db=Depends(get_db),
                user: User = Depends(_manage)):
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
               dependencies=[Depends(_manage_scoped),
                             Depends(require_entitlement("backups.retention"))])
def delete_backup_route(request: Request, backup_id: int, db=Depends(get_db),
                        user: User = Depends(_manage_scoped)):
    b = db.get(Backup, backup_id)
    if b is None:
        raise HTTPException(404, "backup not found")
    return enqueue_and_audit(request, db, user, kind="backup.delete",
                             target_type="backup", target_id=b.id,
                             params={"backup_id": b.id, "volid": b.volid})
