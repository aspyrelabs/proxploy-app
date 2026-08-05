# backend/proxploy/services/migrate.py
"""Cross-host app migration — preflight half (doc 05, doc 08 §14, doc 11 §2).

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

The `migrate.app` job handler (Task 15) reuses `preflight()`'s decision;
nothing here mutates a guest.
"""
from __future__ import annotations

from proxploy.models import Backup, Host
from proxploy.services.hostclient import client_for_host
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
