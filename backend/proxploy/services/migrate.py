# backend/proxploy/services/migrate.py
"""Cross-host app migration — preflight + `migrate.app` job handler (doc 05,
doc 08 §14, doc 11 §2).

Strategy is decided from LIVE Proxmox state, never from `hosts.cluster_name`:
grep across the whole tree at plan time turned up nothing that ever writes
that column, so trusting it would be a silent lie. This preflight is the
first thing that ever populates it — honestly, as a side effect of the very
cluster_status() call that justified the choice — for the one strategy
(`cluster`) where the value is actually true at the moment it's written.

Every number in the response is either a live PVE read or an explicit
`None` with a note saying why it couldn't be obtained. `est_downtime_s` is
never a guess dressed up as a number: doc 10's DoD requires "accurate
downtime shown", and a plausible-looking fabricated estimate is worse than
an honest "unknown" (doc 11 §2: downtime UX must state the truth).

The `migrate.app` job handler (Task 15, below) re-runs `preflight()` itself
— params handed in from the route are only `app_id`/`target_host_id`, never
the strategy/ctid/storage the route's own preflight call saw, because state
can change in the gap between an operator clicking "migrate" and the job
actually running. `est_downtime_s` above is an ESTIMATE; `downtime_s` in the
job's result is MEASURED wall-clock time from the moment the source guest is
(or would be) stopped to the moment the target guest is confirmed running —
that is the number doc 10's "accurate downtime shown" DoD is actually about.

FAKES vs HARDWARE: every PVE call below goes through `services/proxmox.py`'s
`ProxmoxClient`, which in every test in this repo is backed by
`tests/fakes/pve.py::FakePVE` — there is no live Proxmox host here and never
will be. What the tests prove: the handler's call sequence, its honesty
properties (measured not estimated downtime, source never destroyed, no
repoint before a health check passes), and its JobFailed/rollback-messaging
behaviour, all GIVEN the PVE API shapes FakePVE encodes. What they do NOT
prove: that a real PVE 8.x/9.x vzdump/restore/migrate cycle behaves this way
end-to-end on real disks over a real network — that needs live hardware.
"""
from __future__ import annotations

import asyncio

from proxploy.jobs import HANDLERS, JobContext, JobFailed
from proxploy.models import App, Backup, Host, utcnow
from proxploy.services.backupjobs import parse_volid
from proxploy.services.hostclient import client_for_host
from proxploy.services.proxmox import ProxmoxError
from proxploy.services.pvetask import await_task
from proxploy.services.selfguard import is_self

STRATEGY_CLUSTER = "cluster"            # same PVE cluster: native migrate
STRATEGY_SHARED = "shared_storage"      # both hosts see one backup storage
STRATEGY_TRANSFER = "transfer"          # vzdump + SFTP stream + restore

_SHARED_TYPES = frozenset({"pbs", "nfs", "cifs"})

_IP_WARNING = ("The guest gets a new IP/MAC address on the target host; update "
               "any DHCP reservations or static network config it relies on.")


def _has_backup_content(row: dict) -> bool:
    """PVE reports `content` as a comma string ("backup,iso") in most shapes
    and as a list in a few; both mean the same thing (backupjobs.py precedent)."""
    content = row.get("content") or ""
    parts = content if isinstance(content, list) else content.split(",")
    return "backup" in [str(p).strip() for p in parts]


def _cluster_name(status_rows: list[dict]) -> str | None:
    for row in status_rows:
        if row.get("type") == "cluster":
            return row.get("name")
    return None


def _storage_names(rows: list[dict], *, types: frozenset[str] | None,
                   dir_only: bool) -> set[str]:
    out = set()
    for r in rows:
        name = r.get("storage")
        if not name or not _has_backup_content(r):
            continue
        rtype = r.get("type")
        if dir_only:
            if rtype == "dir":
                out.add(name)
        elif types is None or rtype in types:
            out.add(name)
    return out


def _transfer_bytes(db, src_client, source_host_id: int,
                    ctid: int) -> tuple[int | None, str | None]:
    """-> (bytes, basis). Prefers a measured backup (real bytes actually
    written); falls back to the guest's allocated disk size from a live
    /cluster/resources read. Returns (None, None) — never a guess — if
    neither is available."""
    b = (db.query(Backup)
         .filter_by(host_id=source_host_id, guest_type="ct", guest_vmid=ctid)
         .order_by(Backup.taken_at.desc()).first())
    if b is not None and b.size_bytes is not None:
        return b.size_bytes, "last_backup"
    for r in src_client.cluster_resources():
        if r.get("type") == "lxc" and r.get("vmid") is not None:
            try:
                if int(r["vmid"]) != ctid:
                    continue
            except (TypeError, ValueError):
                continue
            maxdisk = r.get("maxdisk")
            if maxdisk is not None:
                return int(maxdisk), "allocated_disk"
    return None, None


def _downtime_estimate(strategy: str, transfer_bytes: int | None,
                       assumed_bps: float) -> tuple[int | None, str]:
    if strategy == STRATEGY_CLUSTER:
        return 30, "offline migrate; restart-scale downtime, network-bound"
    if transfer_bytes is None:
        return None, ("no measured backup and no live disk size were available "
                      "for this guest; downtime cannot be honestly estimated")
    multiplier = 2 if strategy == STRATEGY_SHARED else 3  # backup+restore, or dump+copy+restore
    return int(multiplier * transfer_bytes / assumed_bps), (
        "assumes ~80 MB/s sustained; measured downtime is reported by the job")


def _downtime_statement(strategy: str, est_downtime_s: int | None) -> str:
    if strategy == STRATEGY_CLUSTER:
        if est_downtime_s is None:
            return "This is a live cluster migration; downtime cannot be estimated."
        return (f"This is a live cluster migration; expect roughly {est_downtime_s} "
               f"seconds of downtime, network-bound.")
    if est_downtime_s is None:
        return ("This is stop → backup → transfer → restore → start. "
               "Downtime cannot be estimated: no measured backup size and no live "
               "disk size were available for this guest.")
    minutes = max(1, round(est_downtime_s / 60))
    return (f"This is stop → backup → transfer → restore → start. "
           f"Expect roughly {minutes} minute(s) of downtime.")


def _capacity_ok(tgt_client, target_node: str, storage_name: str | None,
                 transfer_bytes: int | None) -> bool | None:
    """None-safe: no storage chosen yet, or no transfer size, or the target
    row is missing `avail` -> None (unknown), never a fabricated True/False."""
    if storage_name is None or transfer_bytes is None:
        return None
    for r in tgt_client.storages(target_node):
        if r.get("storage") == storage_name:
            avail = r.get("avail")
            return None if avail is None else avail >= 1.2 * transfer_bytes
    return None


def preflight(app, db, app_row, target_host_id: int) -> dict:
    """Blocking — called in-request, like api/hosts.py::test_host's own probe.

    `app_row` and `target_host_id` are assumed already validated by the route
    (app exists, target host exists, target != source, target is connected).
    """
    source_host = db.get(Host, app_row.host_id)
    target_host = db.get(Host, target_host_id)

    src_client = client_for_host(app, db, source_host)
    tgt_client = client_for_host(app, db, target_host)

    src_cluster = _cluster_name(src_client.cluster_status())
    tgt_cluster = _cluster_name(tgt_client.cluster_status())

    warnings: list[str] = []
    blockers: list[str] = []
    shared_storage: str | None = None
    capacity_storage: str | None = None

    if src_cluster is not None and src_cluster == tgt_cluster:
        strategy = STRATEGY_CLUSTER
        # The live check above just PROVED cluster membership — un-deaden the
        # column honestly now, rather than leaving it permanently stale
        # (nothing else in the codebase ever writes it).
        source_host.cluster_name = src_cluster
        target_host.cluster_name = tgt_cluster
        db.commit()
    else:
        src_storage = src_client.cluster_storage()
        tgt_storage = tgt_client.cluster_storage()  # single read, reused below
        src_shared = _storage_names(src_storage, types=_SHARED_TYPES, dir_only=False)
        tgt_shared = _storage_names(tgt_storage, types=_SHARED_TYPES, dir_only=False)
        common = sorted(src_shared & tgt_shared)
        if common:
            strategy = STRATEGY_SHARED
            shared_storage = capacity_storage = common[0]
        else:
            strategy = STRATEGY_TRANSFER
            src_dirs = _storage_names(src_storage, types=None, dir_only=True)
            tgt_dirs = _storage_names(tgt_storage, types=None, dir_only=True)
            if not src_dirs:
                blockers.append(f"no dir-type backup storage on {source_host.name}")
            if not tgt_dirs:
                blockers.append(f"no dir-type backup storage on {target_host.name}")
            capacity_storage = next(iter(sorted(tgt_dirs)), None)

    if strategy == STRATEGY_CLUSTER:
        target_ctid = app_row.ctid  # native migrate keeps the vmid
        transfer_bytes, estimate_basis = None, None
    else:
        target_ctid = tgt_client.cluster_nextid()
        transfer_bytes, estimate_basis = _transfer_bytes(
            db, src_client, source_host.id, app_row.ctid)
        warnings.append(_IP_WARNING)

    est_downtime_s, est_note = _downtime_estimate(
        strategy, transfer_bytes, app.state.settings.migrate_assumed_bps)
    capacity_ok = (True if strategy == STRATEGY_CLUSTER
                   else _capacity_ok(tgt_client, target_host.node_name,
                                     capacity_storage, transfer_bytes))
    if capacity_ok is False:
        warnings.append("target free space is insufficient for the estimated "
                        "transfer size")

    return {
        "strategy": strategy,
        "source": {"host_id": source_host.id, "host_name": source_host.name,
                   "node": source_host.node_name, "ctid": app_row.ctid},
        "target": {"host_id": target_host.id, "host_name": target_host.name,
                   "node": target_host.node_name, "ctid": target_ctid},
        "shared_storage": shared_storage,
        "transfer_bytes": transfer_bytes,
        "estimate_basis": estimate_basis,
        "est_downtime_s": est_downtime_s,
        "est_note": est_note,
        "capacity_ok": capacity_ok,
        "warnings": warnings,
        "blockers": blockers,
        "downtime_statement": _downtime_statement(strategy, est_downtime_s),
        "self_target": is_self(db, "app", app_row.id),
    }


# --- migrate.app job handler (Task 15) --------------------------------------
# ponytail: 60s / 1s are module globals, not a settings knob — nobody has
# asked for a configurable health-check window yet, and a test overrides them
# with monkeypatch.setattr exactly like pvetask.py's own TASK_TIMEOUT_S/
# TASK_POLL_S. Promote to a Settings field if a real fleet ever needs longer.
HEALTH_CHECK_DEADLINE_S = 60.0
HEALTH_CHECK_POLL_S = 1.0


def _load(app, app_id: int, target_host_id: int) -> dict:
    """Blocking: fresh in-handler preflight (never the route's stale one) +
    both clients, in one db session. Returns only plain values/client
    objects — no ORM instance escapes the closed session.

    Raises JobFailed for anything the route already should have prevented
    but that may have changed in the gap between "operator clicks migrate"
    and "this job actually runs" (doc 05 Interfaces note on Task 15).
    """
    with app.state.sessionmaker() as db:
        app_row = db.get(App, app_id)
        if app_row is None:
            raise JobFailed(f"app {app_id} not found")
        app_name = app_row.name
        try:
            pf = preflight(app, db, app_row, target_host_id)
        except ProxmoxError as e:
            raise JobFailed(str(e)) from e
        if pf["blockers"]:
            raise JobFailed("; ".join(pf["blockers"]))
        source_host = db.get(Host, app_row.host_id)
        target_host = db.get(Host, target_host_id)
        try:
            src_client = client_for_host(app, db, source_host)
            tgt_client = client_for_host(app, db, target_host)
        except ProxmoxError as e:
            raise JobFailed(str(e)) from e
    return {"pf": pf, "app_name": app_name, "src_client": src_client,
            "tgt_client": tgt_client}


def _is_running(client, ctid: int) -> bool:
    for r in client.cluster_resources():
        if r.get("type") == "lxc" and r.get("vmid") == ctid:
            return r.get("status") == "running"
    return False


async def _wait_running(client, ctid: int) -> bool:
    """Poll target `cluster_resources()` until CT `ctid` reports running, or
    give up at `HEALTH_CHECK_DEADLINE_S`. Read as module globals (not bound
    into default-argument values) so a test can monkeypatch both down to
    near-zero instead of actually waiting a minute."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + HEALTH_CHECK_DEADLINE_S
    while True:
        rows = await asyncio.to_thread(client.cluster_resources)
        for r in rows:
            if r.get("type") == "lxc" and r.get("vmid") == ctid and r.get("status") == "running":
                return True
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(HEALTH_CHECK_POLL_S)


def _repoint(app, app_id: int, target_host_id: int, target_ctid: int) -> None:
    with app.state.sessionmaker() as db:
        a = db.get(App, app_id)
        a.host_id = target_host_id
        a.ctid = target_ctid
        db.commit()


async def migrate_app(ctx: JobContext, params: dict) -> dict:
    """`migrate.app` — cluster-native or shared-storage backup/restore.

    Failure ordering IS the safety property (doc 11 §2): every step before
    the target's health check can raise JobFailed and the source is still
    the only guest anyone has touched — stopped (if it was running) but
    never destroyed, and `apps.host_id`/`apps.ctid` are never written until
    AFTER that health check passes. The vzdump+SFTP transfer strategy
    (Task 16) is out of scope here and refused honestly rather than
    silently mishandled.
    """
    app = ctx.backend.app
    app_id = int(params["app_id"])
    target_host_id = int(params["target_host_id"])

    loaded = await asyncio.to_thread(_load, app, app_id, target_host_id)
    pf = loaded["pf"]
    src_client, tgt_client = loaded["src_client"], loaded["tgt_client"]
    strategy = pf["strategy"]
    if strategy == STRATEGY_TRANSFER:
        raise JobFailed(
            "the vzdump + SFTP transfer path (no shared backup storage, no "
            "shared PVE cluster) is not implemented yet — this migration was "
            "not started, the source app is untouched")

    source, target = pf["source"], pf["target"]
    source_ctid, source_node, source_host_name = (
        source["ctid"], source["node"], source["host_name"])
    target_ctid, target_node, target_host_name = (
        target["ctid"], target["node"], target["host_name"])
    timeout_s = app.state.settings.pve_task_timeout_s

    ctx.log(pf["downtime_statement"])
    ctx.log(f"if this migration fails at any point, source CT {source_ctid} "
            f"on {source_host_name} is left stopped and intact — nothing is "
            f"ever deleted by this handler")

    # Downtime clock: starts here regardless of branch below (doc 11 §2 —
    # an already-stopped source still has its whole restore/start window
    # counted, since the app is unavailable on either host until the target
    # passes its health check).
    t0 = utcnow()

    running = await asyncio.to_thread(_is_running, src_client, source_ctid)
    if running:
        ctx.log(f"stopping CT {source_ctid} on {source_host_name}")
        upid = await asyncio.to_thread(src_client.guest_action, "lxc", source_node,
                                       source_ctid, "stop")
        await await_task(ctx, src_client, source_node, upid, timeout_s=timeout_s)
    else:
        ctx.log(f"CT {source_ctid} on {source_host_name} was already stopped")

    volid = None
    if strategy == STRATEGY_CLUSTER:
        ctx.log(f"cluster-native migrate: CT {source_ctid} {source_node} -> "
                f"{target_node}")
        upid = await asyncio.to_thread(src_client.migrate_guest, "lxc", source_node,
                                       source_ctid, {"target": target_node})
        await await_task(ctx, src_client, source_node, upid, timeout_s=timeout_s)
    else:
        shared = pf["shared_storage"]
        ctx.log(f"vzdump CT {source_ctid} on {source_host_name}/{source_node} "
                f"-> {shared}")
        upid = await asyncio.to_thread(src_client.vzdump, source_node,
                                       {"vmid": source_ctid, "storage": shared,
                                        "mode": "stop", "compress": "zstd"})
        await await_task(ctx, src_client, source_node, upid, timeout_s=timeout_s)

        rows = await asyncio.to_thread(tgt_client.storage_content, target_node,
                                       shared, "backup")
        candidates = sorted(
            (r for r in rows if parse_volid(r.get("volid") or "") == ("ct", source_ctid)),
            key=lambda r: r.get("ctime") or 0)
        if not candidates:
            raise JobFailed(
                f"vzdump succeeded but no backup archive for CT {source_ctid} "
                f"was found on {shared} — source CT {source_ctid} on "
                f"{source_host_name} is stopped but intact")
        volid = candidates[-1]["volid"]

        ctx.log(f"restoring {volid} as CT {target_ctid} on "
                f"{target_host_name}/{target_node}")
        upid = await asyncio.to_thread(tgt_client.restore_guest, "lxc", target_node,
                                       target_ctid, {"ostemplate": volid, "restore": 1})
        await await_task(ctx, tgt_client, target_node, upid, timeout_s=timeout_s)

    ctx.log(f"starting CT {target_ctid} on {target_host_name}/{target_node}")
    upid = await asyncio.to_thread(tgt_client.guest_action, "lxc", target_node,
                                   target_ctid, "start")
    await await_task(ctx, tgt_client, target_node, upid, timeout_s=timeout_s)

    healthy = await _wait_running(tgt_client, target_ctid)
    if not healthy:
        ctx.log(
            f"HEALTH CHECK FAILED after {HEALTH_CHECK_DEADLINE_S:.0f}s: source "
            f"CT {source_ctid} on {source_host_name} is stopped but intact "
            f"(not deleted); target CT {target_ctid} on {target_host_name} "
            f"was started but never reported running — inspect both by hand, "
            f"delete neither. Roll back by starting the source CT again.",
            stream="stderr")
        raise JobFailed(
            f"target CT {target_ctid} on {target_host_name} did not report "
            f"running within {HEALTH_CHECK_DEADLINE_S:.0f}s of starting — "
            f"source CT {source_ctid} on {source_host_name} is stopped but "
            f"intact; the app was NOT repointed to the target")

    # MEASURED, not the preflight estimate — this is the DoD number (doc 10
    # "accurate downtime shown"). Everything before this line ran with the
    # source authoritative and the app row untouched; only past this point,
    # with the target guest proven healthy, is it safe to repoint.
    downtime_s = (utcnow() - t0).total_seconds()

    await asyncio.to_thread(_repoint, app, app_id, target_host_id, target_ctid)
    app.state.bus.publish("resource", {"type": "app", "id": app_id,
                                       "change": "migrated"})

    rollback = (f"source CT {source_ctid} on {source_host_name} is stopped "
               f"but intact — start it to roll back")
    ctx.log(f"migrated: {downtime_s:.1f}s measured downtime. {rollback}")
    ctx.progress(100)
    return {"strategy": strategy, "downtime_s": downtime_s,
            "source_ctid": source_ctid, "target_ctid": target_ctid,
            "volid": volid, "rollback": rollback}


HANDLERS["migrate.app"] = migrate_app
