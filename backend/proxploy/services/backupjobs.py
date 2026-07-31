# backend/proxploy/services/backupjobs.py
"""Backup cache sync + backup mutation job handlers (doc 01 §7, doc 04 §backups).

`backups` is a droppable mirror, exactly like the poller's `vms` handling: each
sync writes what Proxmox currently reports and deletes rows whose volid vanished
upstream. Proxmox is the source of truth; this table only feeds the Backups page.

Unlike `vms`, this is NOT on the 30 s poll cycle — listing storage content is a
per-storage call, not part of the `/cluster/resources` bulk read the doc-02 §3
budget allows. It runs as a job: on demand from the page (when the cache is
stale) and after every backup mutation.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

from proxploy.jobs import HANDLERS, JobContext
from proxploy.models import App, Backup, Host, Job, Vm, utcnow
from proxploy.services.hostclient import client_for_host
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
    # naive UTC, matching models.utcnow() — every other datetime column is naive
    return datetime.fromtimestamp(int(ctime), timezone.utc).replace(tzinfo=None)


def sync_host_backups(app, host_id: int) -> dict:
    """Blocking. Mirror one host's backup archives into `backups`.

    Returns {"host_id", "synced", "dropped"}.
    """
    with app.state.sessionmaker() as db:
        host = db.get(Host, host_id)
        if host is None:
            raise RuntimeError(f"host {host_id} not found")
        client = client_for_host(app, db, host)
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
    """`backup.sync` — every connected host, or one when `host_id` is given.

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
        except Exception as e:  # noqa: BLE001 — one bad host can't kill the batch
            failed.append({"host_id": hid, "reason": str(e)})
            ctx.log(f"host {hid}: {e}", stream="stderr")
            continue
        synced += r["synced"]
        dropped += r["dropped"]
        ctx.progress(int((i + 1) / len(host_ids) * 100))
    with app.state.sessionmaker() as db:
        # Recorded even when zero backups were found: "the cache is empty" and
        # "the cache was never filled" are different, and only this key can tell
        # the GET route apart — otherwise a cluster with no backups re-enqueues
        # a sync on every page load.
        set_setting(db, SYNCED_AT_KEY, utcnow().isoformat())
    ctx.log(f"{synced} backups cached, {dropped} dropped, {len(failed)} host(s) failed")
    ctx.progress(100)
    app.state.bus.publish("resource", {"type": "backup", "change": "list"})
    return {"synced": synced, "dropped": dropped, "failed": failed}


def sync_in_flight(db) -> bool:
    """A page that refetches while a sync is queued must not pile up a second."""
    return (db.query(Job)
            .filter(Job.kind == "backup.sync", Job.status.in_(("queued", "running")))
            .first() is not None)


HANDLERS["backup.sync"] = sync_backups
