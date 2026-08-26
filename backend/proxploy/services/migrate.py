"""Cross-host app migration: preflight plus the `migrate.app` job handler.

Strategy is decided from LIVE Proxmox state, never from `hosts.cluster_name`:
nothing else in the tree writes that column, so trusting it would be a silent
lie. This preflight is the first thing that populates it, and only for the
`cluster` strategy, where the value is true at the moment it is written.

Every number in the response is either a live PVE read or an explicit `None`
with a note saying why: a plausible fabricated estimate is worse than an
honest "unknown". `est_downtime_s` is an ESTIMATE; the job's `downtime_s` is
MEASURED wall-clock time from the source guest stopping to the target guest
confirmed running.

The handler re-runs `preflight()` itself. Params from the route are only
`app_id`/`target_host_id`, never the strategy/ctid/storage the route's own
preflight saw, because state can change before the job runs.

The transfer strategy (no shared cluster, no shared backup storage) vzdumps
on the source into local dir storage, streams the archive to the target over
SFTP through `executor/transfer.py::sftp_copy_for_hosts` (the only module
outside executor/ allowed to call it: it gets host ids and a
sessionmaker/secretstore, never key bytes), then restores from the
target-local copy. Both scratch archives are plumbing, not backups, and
`_cleanup_volume` deletes both on every exit path so neither host's storage
silently fills with orphaned dumps.
"""
from __future__ import annotations

import asyncio

from proxploy.executor.transfer import sftp_copy_for_hosts
from proxploy.jobs import HANDLERS, JobContext, JobFailed
from proxploy.models import App, Backup, Host, utcnow
from proxploy.services.backupjobs import parse_volid, storage_for_content
from proxploy.services.hostclient import client_for_host, guest_node
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


def _serves(row: dict, node: str | None) -> bool:
    """Does `node` actually serve this storage?

    `cluster_storage()` is `GET /storage`, the cluster-wide CONFIGURATION, so
    it lists every definition regardless of which nodes carry it. Two fields
    decide: `nodes` restricts a storage to named nodes, `disable` switches one
    off. Ignoring them offered a pool restricted to another node as the shared
    storage for a migration, one that `pvesm status` reported disabled on the
    source in the same minute: the vzdump would then go to a pool the source
    cannot write. No fixture carries either field.

    `node` None means "do not filter".
    """
    if row.get("disable"):
        return False
    if node is None:
        return True
    allowed = row.get("nodes")
    if not allowed:
        return True
    if isinstance(allowed, str):
        allowed = [n.strip() for n in allowed.split(",")]
    return node in allowed


def _storage_names(rows: list[dict], *, types: frozenset[str] | None,
                   dir_only: bool, node: str | None = None) -> set[str]:
    out = set()
    for r in rows:
        name = r.get("storage")
        if not name or not _has_backup_content(r) or not _serves(r, node):
            continue
        rtype = r.get("type")
        if dir_only:
            if rtype == "dir":
                out.add(name)
        elif types is None or rtype in types:
            out.add(name)
    return out


def _dir_storage(rows: list[dict], node: str | None = None) -> str | None:
    """Same pick as preflight's `capacity_storage` for the transfer strategy:
    the lexicographically-first dir-type backup storage this NODE serves.
    Recomputed here rather than threaded through `preflight()`'s return dict,
    because preflight discards the name once it has used it for capacity."""
    names = _storage_names(rows, types=None, dir_only=True, node=node)
    return next(iter(sorted(names)), None)


def _storage_path(rows: list[dict], name: str | None) -> str | None:
    """The dir storage's filesystem root (`/storage`'s `path`), the physical
    parent of its `dump/` directory. `None` if the storage was not found or
    carries no `path`: a real PVE dir storage always has one, so a fixture that
    omits it is treated as "cannot transfer", not guessed at."""
    if name is None:
        return None
    for r in rows:
        if r.get("storage") == name:
            return r.get("path") or None
    return None


def _dump_filename(volid: str) -> str:
    """"local:backup/vzdump-lxc-150-....tar.zst" -> the filename tail, i.e.
    what actually sits under storage `path`'s `dump/` directory."""
    _, _, tail = volid.partition(":backup/")
    return tail or volid


def _transfer_bytes(db, src_client, source_host_id: int,
                    ctid: int) -> tuple[int | None, str | None]:
    """-> (bytes, basis). Prefers a measured backup (real bytes actually
    written); falls back to the guest's allocated disk size from a live
    /cluster/resources read. Returns (None, None); never a guess, if
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
        # Measured 47s on real hardware against this estimate of 30, but PVE
        # had the volume on shared storage and `vzmigrate` finished in one
        # second, so that downtime was the guest stopping and starting, not
        # moving. On non-shared storage the transfer does dominate, hence both
        # halves below. The 30 stands: one measurement is not a new constant,
        # and the job reports the real number either way.
        return 30, ("offline migrate; downtime is the guest stopping and "
                    "starting, plus the disk copy when the storage is not "
                    "shared. Measured downtime is reported by the job")
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
               f"seconds of downtime. On real hardware with shared storage it "
               f"measured 47s, so treat this as a floor rather than a promise.")
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


def rootfs_candidates(client, node: str) -> list[str]:
    """Every active storage on `node` that can hold a container rootfs.

    `storage_for_content` answers "the first one", which is the restore's
    default; this is the whole set, so preflight can offer the choice and the
    route can refuse a name outside it.
    """
    out = []
    for row in client.storages(node):
        if not row.get("active", 1):
            continue
        content = row.get("content") or ""
        parts = content if isinstance(content, list) else content.split(",")
        if "rootdir" in [str(p).strip() for p in parts] and row.get("storage"):
            out.append(str(row["storage"]))
    return sorted(out)


def preflight(app, db, app_row, target_host_id: int,
              chosen_storage: str | None = None) -> dict:
    """Blocking, called in-request.

    `app_row` and `target_host_id` are assumed already validated by the route
    (app exists, target host exists, target != source, target is connected).

    Every call here is a READ, so it runs on the "monitoring" capability
    deliberately: previewing a migration must not require lifecycle/backup
    tokens on both hosts, and monitoring is the one capability every enrolled
    host has. The job resolves the others separately, and fails on their
    absence only when it is about to use them.
    """
    source_host = db.get(Host, app_row.host_id)
    target_host = db.get(Host, target_host_id)

    src_client = client_for_host(app, db, source_host, capability="monitoring")
    tgt_client = client_for_host(app, db, target_host, capability="monitoring")

    src_cluster = _cluster_name(src_client.cluster_status())
    tgt_cluster = _cluster_name(tgt_client.cluster_status())

    warnings: list[str] = []
    blockers: list[str] = []

    # Quorum, before anything else: without it /etc/pve is read-only, so no
    # guest config can be written, while /version and /cluster/resources answer
    # perfectly and every other check here passes. A blocker rather than a
    # warning, because the alternative is stopping the source and finding out
    # afterwards. False only, never None: NULL means standalone or not yet
    # polled.
    for host, side in ((source_host, "source"), (target_host, "target")):
        if host.quorate is False:
            blockers.append(
                f"{host.name} ({side}) has lost cluster quorum, so Proxmox will "
                f"refuse every configuration write until quorum returns")
    shared_storage: str | None = None
    capacity_storage: str | None = None

    if src_cluster is not None and src_cluster == tgt_cluster:
        strategy = STRATEGY_CLUSTER
        # The live check above just PROVED cluster membership, so write the
        # column honestly now rather than leave it permanently stale.
        source_host.cluster_name = src_cluster
        target_host.cluster_name = tgt_cluster
        db.commit()
    else:
        src_storage = src_client.cluster_storage()
        tgt_storage = tgt_client.cluster_storage()  # single read, reused below
        src_shared = _storage_names(src_storage, types=_SHARED_TYPES, dir_only=False,
                                    node=source_host.node_name)
        tgt_shared = _storage_names(tgt_storage, types=_SHARED_TYPES, dir_only=False,
                                    node=target_host.node_name)
        common = sorted(src_shared & tgt_shared)
        if common:
            strategy = STRATEGY_SHARED
            shared_storage = capacity_storage = common[0]
        else:
            strategy = STRATEGY_TRANSFER
            src_dirs = _storage_names(src_storage, types=None, dir_only=True,
                                      node=source_host.node_name)
            tgt_dirs = _storage_names(tgt_storage, types=None, dir_only=True,
                                      node=target_host.node_name)
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

    # Where the restored ROOTFS lands, which is not where the archive is
    # staged: `capacity_storage` is the pool holding the dump, and on a stock
    # layout that is a dir store carrying no `rootdir` content at all, so
    # checking only it could read `capacity_ok: true` while the pool the disk
    # needs is full. Named so the operator sees it before committing and the
    # job restores where the preview said.
    rootfs_options = ([] if strategy == STRATEGY_CLUSTER else
                      rootfs_candidates(tgt_client, target_host.node_name))
    # The operator's pick wins when it is one of the real candidates, otherwise
    # the first candidate is the default. An unusable name is reported rather
    # than quietly swapped: silently migrating a guest onto a pool nobody chose
    # is how one ended up on NFS when its source was local-lvm.
    rootfs_storage = None
    if strategy != STRATEGY_CLUSTER:
        if chosen_storage:
            if chosen_storage in rootfs_options:
                rootfs_storage = chosen_storage
            else:
                blockers.append(
                    f"{chosen_storage!r} cannot hold a container rootfs on "
                    f"{target_host.name}" + (f"; choose one of "
                    f"{', '.join(rootfs_options)}" if rootfs_options else ""))
        else:
            rootfs_storage = next(iter(rootfs_options), None)
        if rootfs_storage is None and not blockers:
            blockers.append(f"no storage on {target_host.name} accepts container "
                            f"rootfs")

    if strategy == STRATEGY_CLUSTER:
        capacity_ok = True
    else:
        # Both pools have to fit: the archive on the staging store, the disk on
        # the rootfs pool. Unknown (None) on either stays unknown overall rather
        # than being rounded up to a pass.
        checks = [_capacity_ok(tgt_client, target_host.node_name, name,
                               transfer_bytes)
                  for name in (capacity_storage, rootfs_storage) if name]
        capacity_ok = (False if False in checks
                       else None if (not checks or None in checks) else True)
    if capacity_ok is False:
        warnings.append("target free space is insufficient for the estimated "
                        "transfer size")

    return {
        "strategy": strategy,
        # The GUEST's node on the source side: a CT migrated in the Proxmox UI
        # sits on a different node than its host row implies, and every stop
        # and vzdump below aims at this value. The target side is the host's
        # node by definition.
        "source": {"host_id": source_host.id, "host_name": source_host.name,
                   "node": guest_node(source_host, app_row), "ctid": app_row.ctid},
        "target": {"host_id": target_host.id, "host_name": target_host.name,
                   "node": target_host.node_name, "ctid": target_ctid},
        "shared_storage": shared_storage,
        "rootfs_storage": rootfs_storage,
        "rootfs_options": rootfs_options,
        "staging_storage": capacity_storage if strategy == STRATEGY_TRANSFER else None,
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


# ponytail: 60s / 1s are module globals, not a settings knob: nobody has asked
# for a configurable health-check window yet, and a test overrides them the
# same way pvetask.py's TASK_TIMEOUT_S/TASK_POLL_S are overridden. Promote to
# a Settings field if a real fleet ever needs longer.
HEALTH_CHECK_DEADLINE_S = 60.0
HEALTH_CHECK_POLL_S = 1.0

# migrate_app chains several PVE tasks (and for transfer an SFTP hop) into one
# job. Each await_task brackets its own task with ctx.progress(start_pct) /
# ctx.progress(end_pct); left at the module default (10, 100) every phase would
# report itself as the WHOLE job, so vzdump finishing would hit 100 and the
# SFTP transfer would resume from ~10%. Each strategy's phases get their own
# slice of 0-100 so the reported number only ever goes up, and all three fold
# back into START_PCT for the final start, so that call site does not need to
# know which strategy ran.
STOP_PCT = (0, 5)
CLUSTER_MIGRATE_PCT = (5, 90)
SHARED_VZDUMP_PCT = (5, 45)
SHARED_RESTORE_PCT = (45, 90)
TRANSFER_VZDUMP_PCT = (5, 40)
TRANSFER_BYTES_PCT = (40, 80)   # on_progress scales into this band, byte by byte
TRANSFER_RESTORE_PCT = (80, 90)
START_PCT = (90, 100)


def _load(app, app_id: int, target_host_id: int,
          chosen_storage: str | None = None) -> dict:
    """Blocking: fresh in-handler preflight (never the route's stale one) plus
    every client the strategy needs, in one db session. Returns plain values
    and client objects only, no ORM instance escapes the closed session.

    Raises JobFailed for anything the route should have prevented but that may
    have changed since the operator clicked migrate. A missing lifecycle or
    backup token is exactly that: `client_for_host` raises
    `CapabilityNotConfigured`, naming host and capability, before any PVE call,
    so it becomes one JobFailed line instead of a mid-job 403.

    Non-cluster migration needs lifecycle for stop/start AND backup for
    vzdump/restore/cleanup. Cluster-native needs only lifecycle, so backup is
    resolved lazily: an operator who only migrates inside a cluster must not be
    forced to configure a backup token they will never touch.
    """
    with app.state.sessionmaker() as db:
        app_row = db.get(App, app_id)
        if app_row is None:
            raise JobFailed(f"app {app_id} not found")
        app_name = app_row.name
        try:
            pf = preflight(app, db, app_row, target_host_id, chosen_storage)
        except ProxmoxError as e:
            raise JobFailed(str(e)) from e
        if pf["blockers"]:
            raise JobFailed("; ".join(pf["blockers"]))
        source_host = db.get(Host, app_row.host_id)
        target_host = db.get(Host, target_host_id)
        try:
            # Health-check/status reads (_is_running, _wait_running): always
            # monitoring, guaranteed present, never the reason a migration
            # can't start.
            src_mon_client = client_for_host(app, db, source_host,
                                             capability="monitoring")
            tgt_mon_client = client_for_host(app, db, target_host,
                                             capability="monitoring")
            # Stop the source, start the target: every strategy does both.
            src_client = client_for_host(app, db, source_host,
                                         capability="lifecycle")
            tgt_client = client_for_host(app, db, target_host,
                                         capability="lifecycle")
            src_backup_client = tgt_backup_client = None
            if pf["strategy"] != STRATEGY_CLUSTER:
                src_backup_client = client_for_host(app, db, source_host,
                                                    capability="backup")
                tgt_backup_client = client_for_host(app, db, target_host,
                                                    capability="backup")
        except ProxmoxError as e:
            raise JobFailed(str(e)) from e
        # Plain strings only, never the ORM rows: used solely by the transfer
        # strategy's SFTP hop below. Cheap to always compute, both rows are
        # already loaded above, and the other strategies ignore this key.
        ssh = {"src_address": source_host.address,
              "src_fingerprint": source_host.ssh_host_key_fingerprint,
              "tgt_address": target_host.address,
              "tgt_fingerprint": target_host.ssh_host_key_fingerprint}
    return {"pf": pf, "app_name": app_name,
            "src_client": src_client, "tgt_client": tgt_client,
            "src_mon_client": src_mon_client, "tgt_mon_client": tgt_mon_client,
            "src_backup_client": src_backup_client,
            "tgt_backup_client": tgt_backup_client, "ssh": ssh}


def _is_running(client, ctid: int) -> bool:
    for r in client.cluster_resources():
        if r.get("type") == "lxc" and r.get("vmid") == ctid:
            return r.get("status") == "running"
    return False


async def _wait_running(client, ctid: int) -> bool:
    """Poll target `cluster_resources()` until CT `ctid` reports running, or
    give up at `HEALTH_CHECK_DEADLINE_S`. Both are read as module globals, not
    bound into default-argument values, so either can be overridden without
    actually waiting a minute."""
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


async def _cleanup_volume(ctx: JobContext, client, node: str, storage: str | None,
                          volid: str | None, timeout_s: float) -> None:
    """Best-effort delete of one vzdump/SFTP transfer scratch archive.

    Never raises. It runs on the success path (the archive did its job) and on
    every failure path (so a transfer that died mid-copy leaves no orphans),
    and a cleanup failure must not mask or block the migration's real outcome.
    """
    if storage is None or volid is None:
        return
    try:
        upid = await asyncio.to_thread(client.storage_delete_volume, node, storage, volid)
        if upid:
            # Deleting a scratch archive is not forward progress on the
            # migration itself: hold the job's reported percentage exactly
            # where it already was rather than let await_task's own bracket
            # jump it, since its default end_pct is 100.
            hold = ctx.last_pct
            await await_task(ctx, client, node, upid, timeout_s=timeout_s,
                             start_pct=hold, end_pct=hold)
        ctx.log(f"cleaned up transfer artifact {volid}")
    except Exception as e:  # noqa: BLE001  (cleanup is best-effort by design)
        ctx.log(f"could not remove transfer artifact {volid}: {e}", stream="stderr")


async def migrate_app(ctx: JobContext, params: dict) -> dict:
    """`migrate.app`: cluster-native migrate, shared-storage backup/restore, or
    vzdump + SFTP transfer + restore for hosts with neither.

    Failure ordering IS the safety property: every step before the target's
    health check can raise JobFailed with the source still the only guest
    touched, stopped but never destroyed, and `apps.host_id`/`apps.ctid` are
    never written until AFTER that check passes.
    """
    app = ctx.backend.app
    app_id = int(params["app_id"])
    target_host_id = int(params["target_host_id"])

    loaded = await asyncio.to_thread(_load, app, app_id, target_host_id,
                                     params.get("storage"))
    pf = loaded["pf"]
    src_client, tgt_client = loaded["src_client"], loaded["tgt_client"]
    src_mon_client, tgt_mon_client = loaded["src_mon_client"], loaded["tgt_mon_client"]
    src_backup_client, tgt_backup_client = (loaded["src_backup_client"],
                                            loaded["tgt_backup_client"])
    strategy = pf["strategy"]

    source, target = pf["source"], pf["target"]
    source_ctid, source_node, source_host_name = (
        source["ctid"], source["node"], source["host_name"])
    target_ctid, target_node, target_host_name = (
        target["ctid"], target["node"], target["host_name"])
    timeout_s = app.state.settings.pve_task_timeout_s

    def _restore_storage() -> str:
        """Where the restored rootfs lands on the target.

        Taken from this job's OWN preflight rather than recomputed, so the
        preview and the restore name the same pool. Sending no storage lets PVE
        fall back to `local`, which on a stock layout carries no `rootdir`
        content, so the restore dies on "storage 'local' does not support
        container directories" after the archive has already crossed the wire.
        """
        picked = pf.get("rootfs_storage")
        if picked is None:
            raise JobFailed(
                f"no active storage on {target_host_name} accepts container "
                f"rootfs, source CT {source_ctid} on {source_host_name} is "
                f"stopped but intact")
        return picked

    ctx.log(pf["downtime_statement"])
    ctx.log(f"if this migration fails at any point, source CT {source_ctid} "
            f"on {source_host_name} is left stopped and intact, nothing is "
            f"ever deleted by this handler")

    # Downtime clock: starts here regardless of the branch below. An
    # already-stopped source still has its whole restore/start window counted,
    # since the app is unavailable on either host until the target passes its
    # health check.
    t0 = utcnow()

    running = await asyncio.to_thread(_is_running, src_mon_client, source_ctid)
    if running:
        ctx.log(f"stopping CT {source_ctid} on {source_host_name}")
        upid = await asyncio.to_thread(src_client.guest_action, "lxc", source_node,
                                       source_ctid, "stop")
        await await_task(ctx, src_client, source_node, upid, timeout_s=timeout_s,
                         start_pct=STOP_PCT[0], end_pct=STOP_PCT[1])
    else:
        ctx.log(f"CT {source_ctid} on {source_host_name} was already stopped")

    volid = None
    if strategy == STRATEGY_CLUSTER:
        ctx.log(f"cluster-native migrate: CT {source_ctid} {source_node} -> "
                f"{target_node}")
        upid = await asyncio.to_thread(src_client.migrate_guest, "lxc", source_node,
                                       source_ctid, {"target": target_node})
        await await_task(ctx, src_client, source_node, upid, timeout_s=timeout_s,
                         start_pct=CLUSTER_MIGRATE_PCT[0], end_pct=CLUSTER_MIGRATE_PCT[1])
    elif strategy == STRATEGY_SHARED:
        shared = pf["shared_storage"]
        ctx.log(f"vzdump CT {source_ctid} on {source_host_name}/{source_node} "
                f"-> {shared}")
        upid = await asyncio.to_thread(src_backup_client.vzdump, source_node,
                                       {"vmid": source_ctid, "storage": shared,
                                        "mode": "stop", "compress": "zstd"})
        await await_task(ctx, src_backup_client, source_node, upid, timeout_s=timeout_s,
                         start_pct=SHARED_VZDUMP_PCT[0], end_pct=SHARED_VZDUMP_PCT[1])

        rows = await asyncio.to_thread(tgt_backup_client.storage_content, target_node,
                                       shared, "backup")
        candidates = sorted(
            (r for r in rows if parse_volid(r.get("volid") or "") == ("ct", source_ctid)),
            key=lambda r: r.get("ctime") or 0)
        if not candidates:
            raise JobFailed(
                f"vzdump succeeded but no backup archive for CT {source_ctid} "
                f"was found on {shared}, source CT {source_ctid} on "
                f"{source_host_name} is stopped but intact")
        volid = candidates[-1]["volid"]

        restore_storage = _restore_storage()
        ctx.log(f"restoring {volid} as CT {target_ctid} on "
                f"{target_host_name}/{target_node}, rootfs on {restore_storage}")
        # LIFECYCLE, not backup: a restore to a ctid that does not exist yet
        # CREATES a guest, so PVE checks VM.Allocate, which the Backup role
        # deliberately does not carry. On real hardware the backup token got a
        # bare "403 Permission check failed" here, naming no privilege.
        upid = await asyncio.to_thread(tgt_client.restore_guest, "lxc", target_node,
                                       target_ctid, {"ostemplate": volid, "restore": 1,
                                                     "storage": restore_storage})
        await await_task(ctx, tgt_client, target_node, upid, timeout_s=timeout_s,
                         start_pct=SHARED_RESTORE_PCT[0], end_pct=SHARED_RESTORE_PCT[1])
    else:  # STRATEGY_TRANSFER, vzdump locally, SFTP the archive, restore
        ssh = loaded["ssh"]
        src_storage_rows = await asyncio.to_thread(src_backup_client.cluster_storage)
        tgt_storage_rows = await asyncio.to_thread(tgt_backup_client.cluster_storage)
        src_storage = _dir_storage(src_storage_rows, source_node)
        tgt_storage = _dir_storage(tgt_storage_rows, target_node)
        if src_storage is None or tgt_storage is None:
            missing = source_host_name if src_storage is None else target_host_name
            raise JobFailed(
                f"no dir-type backup storage available on {missing} for the "
                f"transfer path, source CT {source_ctid} on {source_host_name} "
                f"is stopped but intact")

        ctx.log(f"vzdump CT {source_ctid} on {source_host_name}/{source_node} "
                f"-> {src_storage} (local staging for transfer)")
        upid = await asyncio.to_thread(src_backup_client.vzdump, source_node,
                                       {"vmid": source_ctid, "storage": src_storage,
                                        "mode": "stop", "compress": "zstd"})
        await await_task(ctx, src_backup_client, source_node, upid, timeout_s=timeout_s,
                         start_pct=TRANSFER_VZDUMP_PCT[0], end_pct=TRANSFER_VZDUMP_PCT[1])

        rows = await asyncio.to_thread(src_backup_client.storage_content, source_node,
                                       src_storage, "backup")
        candidates = sorted(
            (r for r in rows if parse_volid(r.get("volid") or "") == ("ct", source_ctid)),
            key=lambda r: r.get("ctime") or 0)
        if not candidates:
            raise JobFailed(
                f"vzdump succeeded but no backup archive for CT {source_ctid} "
                f"was found on {src_storage}, source CT {source_ctid} on "
                f"{source_host_name} is stopped but intact")
        src_row = candidates[-1]
        src_volid = src_row["volid"]
        archive_bytes = src_row.get("size")
        filename = _dump_filename(src_volid)
        dst_volid = f"{tgt_storage}:backup/{filename}"

        src_root = _storage_path(src_storage_rows, src_storage)
        tgt_root = _storage_path(tgt_storage_rows, tgt_storage)
        if src_root is None or tgt_root is None:
            await _cleanup_volume(ctx, src_backup_client, source_node, src_storage,
                                  src_volid, timeout_s)
            missing_storage = src_storage if src_root is None else tgt_storage
            missing_host = source_host_name if src_root is None else target_host_name
            raise JobFailed(
                f"dir storage {missing_storage} on {missing_host} has no "
                f"filesystem path configured, transfer cannot proceed; "
                f"source CT {source_ctid} on {source_host_name} is stopped "
                f"but intact")

        src_path = f"{src_root.rstrip('/')}/dump/{filename}"
        dst_path = f"{tgt_root.rstrip('/')}/dump/{filename}"

        def on_progress(done: int) -> None:
            # Scales into TRANSFER_BYTES_PCT: vzdump above already reached
            # this band's floor via its own end_pct, restore below starts
            # from this band's ceiling via its own start_pct.
            lo, hi = TRANSFER_BYTES_PCT
            if archive_bytes:
                ctx.progress(min(hi, lo + int((hi - lo) * done / archive_bytes)))

        def on_new_src_fp(fp: str) -> None:
            # Fresh session: the `_load` one that read `ssh` is already closed.
            with app.state.sessionmaker() as db:
                h = db.get(Host, source["host_id"])
                if h is not None:
                    h.ssh_host_key_fingerprint = fp
                    db.commit()

        def on_new_tgt_fp(fp: str) -> None:
            with app.state.sessionmaker() as db:
                h = db.get(Host, target_host_id)
                if h is not None:
                    h.ssh_host_key_fingerprint = fp
                    db.commit()

        ctx.log(f"streaming {filename} "
                f"({archive_bytes if archive_bytes else 'size unknown'} bytes) "
                f"{source_host_name} -> {target_host_name} over SFTP")
        try:
            await sftp_copy_for_hosts(
                app.state.sessionmaker, app.state.secretstore,
                src_host_id=source["host_id"], src_host=ssh["src_address"],
                src_pinned_fingerprint=ssh["src_fingerprint"],
                src_on_new_fingerprint=on_new_src_fp,
                dst_host_id=target_host_id, dst_host=ssh["tgt_address"],
                dst_pinned_fingerprint=ssh["tgt_fingerprint"],
                dst_on_new_fingerprint=on_new_tgt_fp,
                src_path=src_path, dst_path=dst_path, on_progress=on_progress,
                connect_factory=app.state.ssh_connect_factory)
        except Exception as e:
            # SSHHostKeyMismatch, LookupError (no ssh_key), a dropped
            # connection mid-copy: all land here. The source archive exists on
            # disk by now, so clean it up rather than leave an orphan. The
            # destination file may or may not exist; the delete is a harmless
            # no-op either way.
            await _cleanup_volume(ctx, src_backup_client, source_node, src_storage,
                                  src_volid, timeout_s)
            await _cleanup_volume(ctx, tgt_backup_client, target_node, tgt_storage,
                                  dst_volid, timeout_s)
            raise JobFailed(
                f"SFTP transfer of {filename} failed: {e}, source CT "
                f"{source_ctid} on {source_host_name} is stopped but intact"
            ) from e
        ctx.progress(TRANSFER_BYTES_PCT[1])

        restore_storage = _restore_storage()
        ctx.log(f"restoring {dst_volid} as CT {target_ctid} on "
                f"{target_host_name}/{target_node}, rootfs on {restore_storage}")
        try:
            # LIFECYCLE, same reason as the shared branch above: this creates a
            # guest at a ctid that does not exist yet, so it needs VM.Allocate.
            upid = await asyncio.to_thread(tgt_client.restore_guest, "lxc", target_node,
                                           target_ctid, {"ostemplate": dst_volid,
                                                         "restore": 1,
                                                         "storage": restore_storage})
            await await_task(ctx, tgt_client, target_node, upid, timeout_s=timeout_s,
                             start_pct=TRANSFER_RESTORE_PCT[0], end_pct=TRANSFER_RESTORE_PCT[1])
        # ProxmoxError as well as JobFailed: await_task raises JobFailed for a
        # task that RAN and failed, but restore_guest raises ProxmoxError when
        # PVE refuses the call outright. Catching only the first left both
        # scratch archives on disk on two hosts.
        except (JobFailed, ProxmoxError):
            await _cleanup_volume(ctx, src_backup_client, source_node, src_storage,
                                  src_volid, timeout_s)
            await _cleanup_volume(ctx, tgt_backup_client, target_node, tgt_storage,
                                  dst_volid, timeout_s)
            raise

        # Both scratch files were transfer plumbing, not backups: remove them
        # on both hosts. On the BACKUP clients, like every failure path above:
        # these are the tokens that wrote the archives, and a host granting
        # Datastore.AllocateSpace through the Backup role only would 403 the
        # lifecycle token. `_cleanup_volume` swallows that, so the wrong client
        # leaves multi-GB dumps behind and says nothing.
        await _cleanup_volume(ctx, src_backup_client, source_node, src_storage,
                              src_volid, timeout_s)
        await _cleanup_volume(ctx, tgt_backup_client, target_node, tgt_storage,
                              dst_volid, timeout_s)
        volid = dst_volid

    ctx.log(f"starting CT {target_ctid} on {target_host_name}/{target_node}")
    upid = await asyncio.to_thread(tgt_client.guest_action, "lxc", target_node,
                                   target_ctid, "start")
    await await_task(ctx, tgt_client, target_node, upid, timeout_s=timeout_s,
                     start_pct=START_PCT[0], end_pct=START_PCT[1])

    healthy = await _wait_running(tgt_mon_client, target_ctid)
    if not healthy:
        ctx.log(
            f"HEALTH CHECK FAILED after {HEALTH_CHECK_DEADLINE_S:.0f}s: source "
            f"CT {source_ctid} on {source_host_name} is stopped but intact "
            f"(not deleted); target CT {target_ctid} on {target_host_name} "
            f"was started but never reported running, inspect both by hand, "
            f"delete neither. Roll back by starting the source CT again.",
            stream="stderr")
        raise JobFailed(
            f"target CT {target_ctid} on {target_host_name} did not report "
            f"running within {HEALTH_CHECK_DEADLINE_S:.0f}s of starting, "
            f"source CT {source_ctid} on {source_host_name} is stopped but "
            f"intact; the app was NOT repointed to the target")

    # MEASURED, not the preflight estimate. Everything before this line ran
    # with the source authoritative and the app row untouched; only past this
    # point, with the target guest proven healthy, is it safe to repoint.
    downtime_s = (utcnow() - t0).total_seconds()

    await asyncio.to_thread(_repoint, app, app_id, target_host_id, target_ctid)
    # Both ends changed: the target has a CT the poller has never seen and the
    # source has one it will not see again. Without these the migrated app
    # reads "unknown" for up to a poll interval and the source CT keeps being
    # offered for adoption.
    app.state.poller.wake(target_host_id)
    app.state.poller.wake(int(source["host_id"]))
    app.state.bus.publish("resource", {"type": "app", "id": app_id,
                                       "change": "migrated"})

    rollback = (f"source CT {source_ctid} on {source_host_name} is stopped "
               f"but intact, start it to roll back")
    ctx.log(f"migrated: {downtime_s:.1f}s measured downtime. {rollback}")
    ctx.progress(100)
    return {"strategy": strategy, "downtime_s": downtime_s,
            "source_ctid": source_ctid, "target_ctid": target_ctid,
            "volid": volid, "rollback": rollback}


HANDLERS["migrate.app"] = migrate_app
