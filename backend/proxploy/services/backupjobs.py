# backend/proxploy/services/backupjobs.py
"""Backup cache sync + backup mutation job handlers (doc 01 §7, doc 04 §backups).

`backups` is a droppable mirror, exactly like the poller's `vms` handling: each
sync writes what Proxmox currently reports and deletes rows whose volid vanished
upstream. Proxmox is the source of truth; this table only feeds the Backups page.

Unlike `vms`, this is NOT on the 30 s poll cycle; listing storage content is a
per-storage call, not part of the `/cluster/resources` bulk read the doc-02 §3
budget allows. It runs as a job: on demand from the page (when the cache is
stale) and after every backup mutation.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

from proxploy.jobs import HANDLERS, JobContext, JobFailed
from proxploy.models import App, Backup, Host, Job, Vm, to_iso, utcnow
from proxploy.services.hostclient import client_for_host
from proxploy.services.proxmox import ProxmoxError
from proxploy.services.pvetask import await_task
from proxploy.services.settings import set_setting

SYNCED_AT_KEY = "backup.synced_at"

# vzdump archives:  local:backup/vzdump-lxc-150-2026_07_30-02_00_00.tar.zst
# PBS snapshots:    pbs-ds:backup/ct/150/2026-07-30T02:00:00Z
VZDUMP_RE = re.compile(r"vzdump-(lxc|openvz|qemu)-(\d+)-")
PBS_RE = re.compile(r":backup/(ct|vm)/(\d+)/")
_GUEST_KIND = {"lxc": "ct", "openvz": "ct", "ct": "ct", "qemu": "vm", "vm": "vm"}


def parse_volid(volid: str) -> tuple[str | None, int | None]:
    """-> ("ct"|"vm", vmid), or (None, None) for anything that isn't a backup.

    The volid is the identifier upstream (doc 04) and carries the guest it came
    from in both storage layouts; the content row's own `vmid` field is absent
    on some PBS shapes, so the name is parsed rather than trusted.
    """
    m = VZDUMP_RE.search(volid) or PBS_RE.search(volid)
    if not m:
        return None, None
    return _GUEST_KIND[m.group(1)], int(m.group(2))


def _has_backup_content(entry: dict) -> bool:
    """PVE reports `content` as a comma string ("backup,iso") in most shapes and
    as a list in a few; both mean the same thing."""
    content = entry.get("content") or ""
    parts = content if isinstance(content, list) else content.split(",")
    return "backup" in [str(p).strip() for p in parts]


def _taken_at(ctime) -> datetime | None:
    if ctime in (None, ""):
        return None
    # naive UTC, matching models.utcnow(): every other datetime column is naive
    return datetime.fromtimestamp(int(ctime), timezone.utc).replace(tzinfo=None)


def sync_host_backups(app, host_id: int) -> dict:
    """Blocking. Mirror one host's backup archives into `backups`.

    Returns {"host_id", "synced", "dropped"}.
    """
    with app.state.sessionmaker() as db:
        host = db.get(Host, host_id)
        if host is None:
            raise RuntimeError(f"host {host_id} not found")
        try:
            client = client_for_host(app, db, host, capability="backup")
        except ProxmoxError as e:
            raise JobFailed(str(e)) from e
        node = host.node_name or ""
        # ponytail: one node per Host row. Shared datastores (PBS, NFS, CephFS)
        # report identically from any node, so this is complete for them;
        # node-local vzdump archives on a sibling node of a cluster are missed
        # until Host models its nodes. Upgrade path: iterate the poller's
        # snapshot node list instead of this single name.
        rows: list[dict] = []
        for st in client.storages(node):
            if not _has_backup_content(st):
                continue
            name = st.get("storage")
            for item in client.storage_content(node, name, content="backup"):
                rows.append({"_storage": name, **item})

        ct_names = {a.ctid: a.name for a in db.query(App).filter_by(host_id=host_id)}
        vm_names = {v.vmid: v.name for v in db.query(Vm).filter_by(host_id=host_id)}
        existing = {b.volid: b for b in db.query(Backup).filter_by(host_id=host_id)}
        now = utcnow()
        seen: set[str] = set()
        for item in rows:
            volid = item.get("volid")
            if not volid or volid in seen:
                continue
            seen.add(volid)
            b = existing.get(volid)
            if b is None:
                b = Backup(host_id=host_id, volid=volid)  # ux_backups(host_id, volid)
                db.add(b)
            gtype, gvmid = parse_volid(volid)
            b.storage = item.get("_storage")
            b.guest_type, b.guest_vmid = gtype, gvmid
            b.guest_name = ct_names.get(gvmid) if gtype == "ct" else vm_names.get(gvmid)
            b.taken_at = _taken_at(item.get("ctime"))
            b.size_bytes = int(item["size"]) if item.get("size") is not None else None
            b.verify_state = (item.get("verification") or {}).get("state") or "none"
            b.notes = item.get("notes")
            b.synced_at = now
        dropped = 0
        for volid, b in existing.items():
            if volid not in seen:
                db.delete(b)  # gone upstream = gone here; the mirror is droppable
                dropped += 1
        db.commit()
        return {"host_id": host_id, "synced": len(seen), "dropped": dropped}


async def sync_backups(ctx: JobContext, params: dict) -> dict:
    """`backup.sync`, every connected host, or one when `host_id` is given.

    One bad host is recorded and skipped: a host missing its API token must not
    stop the other three from syncing (services/catalog.py::run_ingest's rule).
    """
    app = ctx.backend.app
    if params.get("host_id"):
        host_ids = [int(params["host_id"])]
    else:
        with app.state.sessionmaker() as db:
            host_ids = [h.id for h in db.query(Host).filter_by(status="connected").all()]
    ctx.log(f"syncing backups from {len(host_ids)} host(s)")
    synced = dropped = 0
    failed: list[dict] = []
    for i, hid in enumerate(host_ids):
        try:
            r = await asyncio.to_thread(sync_host_backups, app, hid)
        except Exception as e:  # noqa: BLE001  (one bad host can't kill the batch)
            failed.append({"host_id": hid, "reason": str(e)})
            ctx.log(f"host {hid}: {e}", stream="stderr")
            continue
        synced += r["synced"]
        dropped += r["dropped"]
        ctx.progress(int((i + 1) / len(host_ids) * 100))
    with app.state.sessionmaker() as db:
        # Recorded even when zero backups were found: "the cache is empty" and
        # "the cache was never filled" are different, and only this key can tell
        # the GET route apart: otherwise a cluster with no backups re-enqueues
        # a sync on every page load.
        set_setting(db, SYNCED_AT_KEY, to_iso(utcnow()))
    ctx.log(f"{synced} backups cached, {dropped} dropped, {len(failed)} host(s) failed")
    ctx.progress(100)
    app.state.bus.publish("resource", {"type": "backup", "change": "list"})
    return {"synced": synced, "dropped": dropped, "failed": failed}


def sync_in_flight(db) -> bool:
    """A page that refetches while a sync is queued must not pile up a second.

    `db.rollback()` first, and it is load-bearing: the caller has already run
    queries on this session, which pins a read snapshot (SQLite in WAL gives a
    transaction a consistent view until it ends). A concurrent request that
    enqueued and committed its Job row AFTER that snapshot opened is invisible
    here, so the check returns False and a duplicate job is enqueued; which is
    exactly the race `api/backups.py::_sync_enqueue_lock` looks like it
    prevents but cannot: the lock serializes the code, not the visibility of
    the data. Ending the read transaction starts a fresh snapshot.

    Callers must therefore have no uncommitted writes pending on `db`. Every
    caller today is a read path.
    """
    db.rollback()
    return (db.query(Job)
            .filter(Job.kind == "backup.sync", Job.status.in_(("queued", "running")))
            .first() is not None)


HANDLERS["backup.sync"] = sync_backups


# --- backup mutations (Phase 6 Task 9) --------------------------------------

def _host_target(app, host_id: int):
    """Blocking: host id -> (client, node, host name)."""
    with app.state.sessionmaker() as db:
        host = db.get(Host, host_id)
        if host is None:
            raise JobFailed(f"host {host_id} not found")
        try:
            return client_for_host(app, db, host, capability="backup"), host.node_name or "", host.name
        except ProxmoxError as e:
            raise JobFailed(str(e)) from e


def _backup_target(app, backup_id: int):
    """Blocking: backup id -> (client, node, plain dict of the row's fields).

    The row itself is not returned: the resync at the end of every mutation may
    delete it, and a detached ORM object would then be unreadable.
    """
    with app.state.sessionmaker() as db:
        b = db.get(Backup, backup_id)
        if b is None:
            raise JobFailed(f"backup {backup_id} not found")
        host = db.get(Host, b.host_id)
        if host is None:
            raise JobFailed(f"host {b.host_id} not found")
        info = {"host_id": b.host_id, "volid": b.volid, "storage": b.storage,
                "guest_type": b.guest_type, "guest_vmid": b.guest_vmid,
                "guest_name": b.guest_name}
        try:
            return client_for_host(app, db, host, capability="backup"), host.node_name or "", info
        except ProxmoxError as e:
            raise JobFailed(str(e)) from e


async def _resync(ctx: JobContext, host_id: int) -> None:
    """Every backup mutation ends here. Without it the cache still lists a
    volume that was just deleted, or misses one that was just created.

    A failed resync is logged, not raised: the mutation upstream already
    succeeded, and failing the job over a stale cache would misreport it.
    """
    app = ctx.backend.app
    try:
        r = await asyncio.to_thread(sync_host_backups, app, host_id)
    except Exception as e:  # noqa: BLE001
        ctx.log(f"backup cache resync failed: {e}", stream="stderr")
        return
    ctx.log(f"backup cache resynced: {r['synced']} cached, {r['dropped']} dropped")
    app.state.bus.publish("resource", {"type": "backup", "change": "list"})


async def run_backup(ctx: JobContext, params: dict) -> dict:
    """`backup.run`, one vzdump task over the selected guests, or all of them."""
    app = ctx.backend.app
    host_id = int(params["host_id"])
    client, node, host_name = await asyncio.to_thread(_host_target, app, host_id)
    vmids = [int(v) for v in (params.get("vmids") or [])]
    call = {"mode": params.get("mode") or "snapshot",
            "compress": params.get("compress") or "zstd"}
    if params.get("storage"):
        call["storage"] = params["storage"]
    if vmids:
        call["vmid"] = ",".join(str(v) for v in vmids)
    else:
        call["all"] = 1  # empty selection means every guest on the node
    ctx.log(f"vzdump on {host_name}/{node}: "
            f"{'all guests' if not vmids else ', '.join(str(v) for v in vmids)}")
    upid = await asyncio.to_thread(client.vzdump, node, call)
    status = await await_task(ctx, client, node, upid,
                              timeout_s=app.state.settings.pve_task_timeout_s)
    await _resync(ctx, host_id)
    return {"upid": upid, "exitstatus": status.get("exitstatus"), "vmids": vmids}


HANDLERS["backup.run"] = run_backup


def _storage_for_content(client, node: str, want: str) -> str | None:
    """Blocking: first active storage on `node` whose `content` list includes
    `want` ("rootdir" for a CT, "images" for a VM).

    ponytail: first match wins, in whatever order PVE lists them. A host with
    several eligible pools gets an arbitrary one of them, which is still
    strictly better than the `local` PVE would otherwise pick and always fail
    on. Let the caller pass `storage` to choose deliberately.
    """
    for s in client.storages(node):
        if not s.get("active", 1):
            continue
        if want in (s.get("content") or "").split(","):
            return s.get("storage")
    return None


async def restore_backup(ctx: JobContext, params: dict) -> dict:
    """`backup.restore`, in place (same vmid, force=1) or as new (fresh vmid).

    The route already refused an in-place restore over a running guest or over
    Proxploy itself; this handler assumes that gate was passed.
    """
    app = ctx.backend.app
    in_place = params.get("mode") == "in_place"
    client, node, info = await asyncio.to_thread(
        _backup_target, app, int(params["backup_id"]))
    kind = "lxc" if info["guest_type"] == "ct" else "qemu"
    if in_place:
        if not info["guest_vmid"]:
            raise JobFailed(f"{info['volid']} carries no guest id to restore over")
        vmid = int(info["guest_vmid"])
    else:
        vmid = await asyncio.to_thread(client.cluster_nextid)
    call = ({"ostemplate": info["volid"], "restore": 1} if kind == "lxc"
            else {"archive": info["volid"]})
    if params.get("storage"):
        call["storage"] = params["storage"]
    else:
        # Nothing chosen: PVE falls back to `local`, which on a stock layout is
        # a directory store that holds no rootfs or disk image, so every
        # restore died on "storage 'local' does not support container
        # directories". The UI sends no storage at all (api/backups.ts), so
        # that was every restore-as-new. Pick a store on this node that can
        # actually hold the guest instead of letting PVE guess wrong.
        want = "rootdir" if kind == "lxc" else "images"
        picked = await asyncio.to_thread(_storage_for_content, client, node, want)
        if picked is None:
            raise JobFailed(
                f"no active storage on {node} accepts {want} content; "
                f"choose a target storage for this restore")
        ctx.log(f"no storage given, restoring onto {picked!r} (accepts {want})")
        call["storage"] = picked
    if in_place:
        call["force"] = 1  # overwrite the existing guest; PVE requires it stopped
    ctx.log(f"restoring {info['volid']} to {kind} {vmid} on {node} "
            f"({'in place' if in_place else 'as new'})")
    upid = await asyncio.to_thread(client.restore_guest, kind, node, vmid, call)
    status = await await_task(ctx, client, node, upid,
                              timeout_s=app.state.settings.pve_task_timeout_s)
    await _resync(ctx, info["host_id"])
    return {"upid": upid, "exitstatus": status.get("exitstatus"), "vmid": vmid,
            "mode": "in_place" if in_place else "new"}


HANDLERS["backup.restore"] = restore_backup


async def delete_backup(ctx: JobContext, params: dict) -> dict:
    """`backup.delete`, remove one archive upstream, then re-mirror."""
    app = ctx.backend.app
    client, node, info = await asyncio.to_thread(
        _backup_target, app, int(params["backup_id"]))
    ctx.log(f"deleting {info['volid']} from {info['storage']} on {node}")
    upid = await asyncio.to_thread(client.storage_delete_volume, node,
                                   info["storage"], info["volid"])
    if upid:
        await await_task(ctx, client, node, upid,
                         timeout_s=app.state.settings.pve_task_timeout_s)
    else:
        # Some storage plugins delete synchronously and return no task id.
        ctx.log("storage deleted the volume synchronously (no task id)")
        ctx.progress(100)
    await _resync(ctx, info["host_id"])
    return {"upid": upid, "volid": info["volid"]}


async def prune_backups_job(ctx: JobContext, params: dict) -> dict:
    """`backup.prune`, apply a retention spec for real. `spec` was built and
    validated by the route; an empty one would mark every archive `remove`."""
    app = ctx.backend.app
    host_id = int(params["host_id"])
    client, node, host_name = await asyncio.to_thread(_host_target, app, host_id)
    node = params.get("node") or node
    storage = params["storage"]
    # `prune-backups` is hyphenated: a dict that gets unpacked at the proxmoxer
    # call, never a Python kwarg.
    call = {"prune-backups": params["spec"]}
    if params.get("guest_type"):
        call["type"] = params["guest_type"]
    if params.get("vmid"):
        call["vmid"] = int(params["vmid"])
    ctx.log(f"pruning {storage} on {host_name}/{node} with {params['spec']}")
    upid = await asyncio.to_thread(client.prune_backups, node, storage, call)
    status = await await_task(ctx, client, node, upid,
                              timeout_s=app.state.settings.pve_task_timeout_s)
    await _resync(ctx, host_id)
    return {"upid": upid, "exitstatus": status.get("exitstatus"),
            "spec": params["spec"], "storage": storage}


HANDLERS["backup.delete"] = delete_backup
HANDLERS["backup.prune"] = prune_backups_job
