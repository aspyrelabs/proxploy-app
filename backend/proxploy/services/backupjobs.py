"""Backup cache sync and backup mutation job handlers.

`backups` is a droppable mirror, like the poller's `vms` handling: each sync
writes what Proxmox reports and deletes rows whose volid vanished upstream.
Proxmox is the source of truth; this table only feeds the Backups page.

Unlike `vms` this is NOT on the 30 s poll cycle: listing storage content is a
per-storage call, not part of the `/cluster/resources` bulk read the poll
budget allows. It runs as a job, on demand when the cache is stale and after
every mutation.
"""
from __future__ import annotations

import asyncio
import re
import shlex
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy import or_ as sa_or

from proxploy.executor import SSHExecutor
from proxploy.jobs import HANDLERS, JobContext, JobFailed
from proxploy.models import (App, Backup, CatalogEntry, Host, Job, Vm,
                             to_iso, utcnow)
from proxploy.services.hostclient import client_for_host
from proxploy.services.proxmox import ProxmoxError
from proxploy.services.pvetask import await_task
from proxploy.services.settings import set_setting

SYNCED_AT_KEY = "backup.synced_at"

VZDUMP_RE = re.compile(r"vzdump-(lxc|openvz|qemu)-(\d+)-")
PBS_RE = re.compile(r":backup/(ct|vm)/(\d+)/")
_GUEST_KIND = {"lxc": "ct", "openvz": "ct", "ct": "ct", "qemu": "vm", "vm": "vm"}


def parse_volid(volid: str) -> tuple[str | None, int | None]:
    """-> ("ct"|"vm", vmid), or (None, None) for anything that isn't a backup.

    The volid is the identifier upstream and carries the guest it came from in
    both storage layouts. The content row's own `vmid` field is absent on some
    PBS shapes, so the name is parsed rather than trusted.
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


def _syncs_shared_stores(db, host: Host) -> bool:
    """Whether this host is the one that mirrors the cluster's SHARED backup
    datastores.

    Every node reports the same archives off a shared store, and each node is
    its own Host row with its own `backups` rows keyed ux_backups(host_id,
    volid), so one backup of one VM appeared once per enrolled node. One
    owner is what makes the list say one archive once.

    The lowest CONNECTED host id, so the answer is the same whichever sync
    runs first, and a disconnected owner hands the rows to a sibling on the
    next sweep instead of taking the cluster's backup list offline with it. A
    standalone host owns its own.
    """
    if host.cluster_name is None:
        return True
    lowest = (db.query(func.min(Host.id))
              .filter(Host.cluster_name == host.cluster_name,
                      Host.status == "connected").scalar())
    return lowest is None or lowest == host.id


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
        enrolled = host.node_name or ""
        # EVERY node of the cluster, not just the enrolled one: a node-local
        # dump dir holds its own archives, so reading one node meant a
        # multi-node user without a shared datastore never saw the rest of
        # their backups. The node list is the poller's, falling back to the
        # enrolled node before the first poll, because an empty backup list
        # until a poll landed would be the worse bug.
        snap = app.state.poller.snapshots.get(host_id)
        nodes = [n.get("node") for n in (snap.nodes if snap else []) if n.get("node")]
        if not nodes:
            nodes = [enrolled]
        shared_here = _syncs_shared_stores(db, host)
        rows: list[dict] = []
        # A shared store answers identically from every node, so it is read
        # ONCE and recorded against the enrolled node. Reading it per node would
        # turn one archive into one row per node, the same double count
        # _syncs_shared_stores prevents one level up.
        shared_done: set[str] = set()
        for node in nodes:
            for st in client.storages(node):
                if not _has_backup_content(st):
                    continue
                name = st.get("storage")
                # Only the cluster's canonical host mirrors a shared store;
                # a node-LOCAL store is synced by every host, because there the
                # same volid on two nodes really is two different files.
                if st.get("shared"):
                    if not shared_here or name in shared_done:
                        continue
                    shared_done.add(name)
                for item in client.storage_content(node, name, content="backup"):
                    # `_type` rides along with `_storage`: PVE hands both back
                    # here, and asking the poller instead gets nothing before
                    # the first poll. `_node` tells two identical volids apart.
                    rows.append({"_storage": name, "_type": st.get("type"),
                                 "_node": enrolled if st.get("shared") else node,
                                 **item})

        ct_names = {a.ctid: a.name for a in db.query(App).filter_by(host_id=host_id)}
        vm_names = {v.vmid: v.name for v in db.query(Vm).filter_by(host_id=host_id)}
        # Keyed on (node, volid), matching ux_backups: the same volid on two
        # nodes of a cluster is two different files on a node-local store.
        prior = db.query(Backup).filter_by(host_id=host_id).all()
        existing = {(b.node, b.volid): b for b in prior}
        # Rows written before `node` existed carry NULL, and matching on the
        # pair alone would MISS, build a second row for the same archive and
        # drop the first: every verdict this install recorded would go with it
        # on the first sync after upgrade. Adopted below instead.
        unplaced = {b.volid: b for b in prior if b.node is None}
        now = utcnow()
        seen: set[tuple[str | None, str]] = set()
        for item in rows:
            volid = item.get("volid")
            key = (item.get("_node"), volid)
            if not volid or key in seen:
                continue
            seen.add(key)
            b = existing.get(key)
            if b is None:
                b = unplaced.pop(volid, None)
                if b is not None:
                    # Same archive, now placed; its verify_state and checked_at
                    # come with it. The OLD (None, volid) key has to go from
                    # `existing` too: the drop loop deletes every key it did not
                    # see, and would delete this row under its old one.
                    existing.pop((None, volid), None)
                    b.node = item.get("_node")
                    existing[key] = b
                else:
                    b = Backup(host_id=host_id, volid=volid, node=item.get("_node"))
                    db.add(b)
            gtype, gvmid = parse_volid(volid)
            b.storage = item.get("_storage")
            b.storage_type = item.get("_type")
            b.guest_type, b.guest_vmid = gtype, gvmid
            b.guest_name = ct_names.get(gvmid) if gtype == "ct" else vm_names.get(gvmid)
            b.taken_at = _taken_at(item.get("ctime"))
            b.size_bytes = int(item["size"]) if item.get("size") is not None else None
            # Only when upstream actually reports one. A non-PBS store carries
            # no `verification` at all, and writing "none" there erased the
            # verdict this file's own check had just written. PBS still wins
            # wherever PBS speaks.
            upstream = (item.get("verification") or {}).get("state")
            if upstream:
                b.verify_state = upstream
            elif b.verify_state is None:
                b.verify_state = "none"
            b.notes = item.get("notes")
            b.synced_at = now
        dropped = 0
        for key, b in existing.items():
            if key not in seen:
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
        # "the cache was never filled" are different, and only this key tells
        # the GET route apart, otherwise a cluster with no backups re-enqueues a
        # sync on every page load.
        set_setting(db, SYNCED_AT_KEY, to_iso(utcnow()))
    ctx.log(f"{synced} backups cached, {dropped} dropped, {len(failed)} host(s) failed")
    ctx.progress(100)
    app.state.bus.publish("resource", {"type": "backup", "change": "list"})
    return {"synced": synced, "dropped": dropped, "failed": failed}


def sync_in_flight(db) -> bool:
    """A page that refetches while a sync is queued must not pile up a second.

    `db.rollback()` first, and it is load-bearing: the caller has already run
    queries on this session, pinning a read snapshot (SQLite in WAL holds a
    consistent view until the transaction ends). A request that enqueued and
    committed its Job row after that snapshot opened is invisible here, so
    the check returns False and a duplicate is enqueued. A lock cannot fix
    it: it serializes the code, not the visibility of the data.

    Callers must therefore have no uncommitted writes pending on `db`.
    """
    db.rollback()
    return (db.query(Job)
            .filter(Job.kind == "backup.sync", Job.status.in_(("queued", "running")))
            .first() is not None)


HANDLERS["backup.sync"] = sync_backups



def _host_target(app, host_id: int, capability: str = "backup"):
    """Blocking: host id -> (client, node, host name).

    `capability` is a parameter because a restore is not a backup call: it
    creates a guest, so it needs Lifecycle (see restore_backup).
    """
    with app.state.sessionmaker() as db:
        host = db.get(Host, host_id)
        if host is None:
            raise JobFailed(f"host {host_id} not found")
        try:
            return (client_for_host(app, db, host, capability=capability),
                    host.node_name or "", host.name)
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
                "guest_name": b.guest_name, "node": b.node or host.node_name or ""}
        try:
            # The ARCHIVE's node, not the host's: a node-local archive on a
            # sibling of the enrolled node is only readable there, `pvesm path`
            # on the wrong node finds nothing, and a restore would build the
            # guest elsewhere. Falls back to the enrolled node for a row synced
            # before `node` existed.
            return (client_for_host(app, db, host, capability="backup"),
                    info["node"], info)
        except ProxmoxError as e:
            raise JobFailed(str(e)) from e


async def _resync(ctx: JobContext, host_id: int) -> None:
    """Every backup mutation ends here. Without it the cache still lists a
    volume that was just deleted, or misses one just created.

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


def guests_on_host(app, host_id: int) -> tuple[list[int], bool]:
    """Blocking: (vmids Proxploy knows on this host, whether it was ever polled).

    The poller's own `apps`/`vms` rows, not a live read: the backup token
    carries no VM.Audit (services/pveum.py), so `cluster_resources()` on it
    answers with zero guests for a node full of them.

    The second element is the honesty guard. A Host row exists before the
    first poll writes its guests, and "no rows yet" must never be read as "no
    guests": `last_seen_at` is the poller's, so NULL means the caller must
    conclude nothing from an empty list.
    """
    with app.state.sessionmaker() as db:
        host = db.get(Host, host_id)
        if host is None:
            raise JobFailed(f"host {host_id} not found")
        vmids = [a.ctid for a in db.query(App).filter_by(host_id=host_id)]
        vmids += [v.vmid for v in db.query(Vm).filter_by(host_id=host_id)]
        return sorted(int(v) for v in vmids if v is not None), host.last_seen_at is not None


_PCT_LINE = re.compile(r"\b(\d{1,3})%")


def _vzdump_pct(total: int):
    """Read vzdump's own percentage out of its task log, across `total` guests.

    PVE's task STATUS carries no percentage, so the only honest source is the
    log this task already streams: vzdump prints
    "INFO:  37% (4.1 GiB of 11.0 GiB) in 12s, read: ..." per guest and
    restarts at 0% for the next. A guest's figure is folded into the run's:
    guests finished, plus how far the current one is, over the total.

    `total` can be wrong (a guest created since the last poll is still backed
    up), which only makes the bar conservative: await_task never reports a
    percentage backwards.
    """
    done = {"n": 0}

    def parse(line: str) -> int | None:
        if "Finished Backup of" in line:
            done["n"] = min(total, done["n"] + 1)
            return int(done["n"] / total * 100)
        m = _PCT_LINE.search(line)
        if m is None:
            return None
        within = min(100, int(m.group(1)))
        return int((done["n"] + within / 100) / total * 100)

    return parse


def _verify_command(volid: str, guest_type: str | None) -> str:
    """One shell command: resolve the archive's path, then read it back.

    One command rather than an SSH round trip per step: the path is only
    useful to the reader that follows it, and one exit status is what the
    caller judges.

    `pvesm path`, not `/mnt/pve/<store>/dump/...`: the mount point belongs to
    the storage plugin, so a guessed path breaks on the first non-default one.

    `set -o pipefail` is load bearing: without it the status is the
    verifier's alone, and a truncated archive that kills `zstdcat` still
    reports whatever `vma verify` made of the bytes it did get.

    Exit 90 means "the path could not be resolved", a broken check rather
    than a bad archive; the caller tells those apart.
    """
    reader = "vma verify -v -" if guest_type == "vm" else "tar -tf - >/dev/null"
    script = (
        "set -o pipefail; "
        f"P=\"$(pvesm path {shlex.quote(volid)})\"; "
        "test -n \"$P\" || { echo 'pvesm path returned nothing' >&2; exit 90; }; "
        "test -r \"$P\" || { echo \"cannot read $P\" >&2; exit 90; }; "
        "case \"$P\" in "
        "*.zst) D=zstdcat;; *.lzo) D='lzop -dc';; *.gz) D=zcat;; *) D=cat;; esac; "
        f"$D \"$P\" | {reader}"
    )
    # Explicitly bash: `set -o pipefail` is not in POSIX sh, and the whole
    # point of the pipeline above is that its status is honest.
    return f"bash -c {shlex.quote(script)}"


async def _verify_sweep(ctx: JobContext, params: dict) -> dict:
    """Verify the archives nobody has verified yet, oldest first.

    Capped: verifying reads every byte of every archive it takes, and a year
    of daily backups is not a thing to start at 3am without a ceiling.
    """
    app = ctx.backend.app
    host_id = int(params["host_id"])
    limit = max(1, min(int(params.get("max") or 20), 200))
    want_storage = params.get("storage")
    # Proxmox Backup Server verifies its own archives against stored digests on
    # its own schedule, so a sweep reading them back over the network would
    # spend hours re-answering a question PBS answers better. The per-archive
    # routes refuse this at the door (api/backups.py::_refuse_on_pbs); a
    # schedule has no door, so it filters. The row's own storage_type is the
    # source, not the poll snapshot, which is empty between boot and the first
    # poll, exactly when the scheduler starts.
    snap = app.state.poller.snapshots.get(host_id)
    pbs_stores = {st.get("storage") for st in (snap.storage if snap else [])
                  if (st.get("type") or "") == "pbs"}
    with app.state.sessionmaker() as db:
        q = (db.query(Backup.id, Backup.storage)
             .filter(Backup.host_id == host_id, Backup.checked_at.is_(None),
                     # NULL storage_type is "not known to be PBS", which is what
                     # a pre-migration row is until its next sync.
                     sa_or(Backup.storage_type.is_(None),
                           Backup.storage_type != "pbs")))
        if want_storage:
            q = q.filter(Backup.storage == want_storage)
        if pbs_stores:
            q = q.filter(Backup.storage.notin_(pbs_stores))
        ids = [i for (i, _) in q.order_by(Backup.taken_at.asc()).limit(limit)]
    if pbs_stores:
        ctx.log(f"skipping {', '.join(sorted(s for s in pbs_stores if s))}: "
                f"Proxmox Backup Server verifies those itself")
    if not ids:
        # Worded as the good news it is: "0 archives have never been verified"
        # reads as a failure to find something.
        ctx.log("every archive on this host has been checked already, "
                "nothing to do")
    elif len(ids) == 1:
        ctx.log("1 archive has never been verified, reading it back now")
    else:
        ctx.log(f"{len(ids)} archives have never been verified, "
                f"reading them back now")
    checked = failed = 0
    for i, bid in enumerate(ids):
        # Each archive gets its OWN slice of the bar. Progress never moves
        # backwards, so an archive handed the whole range would pin the bar at
        # 100 for the rest of the sweep.
        out = await verify_backup(ctx, {"backup_id": bid}, band=(
            int(i / len(ids) * 100), int((i + 1) / len(ids) * 100)))
        checked += 1
        failed += 1 if out["verdict"] == "failed" else 0
    ctx.log(f"verified {checked}, {failed} did not read back")
    return {"checked": checked, "failed": failed}


async def verify_backup(ctx: JobContext, params: dict, *,
                        band: tuple[int, int] = (5, 100)) -> dict:
    """`backup.verify`: read one archive back and record whether it is intact.

    The only backup path that runs over SSH: neither `pvesm path` nor
    `vma verify` exists on the PVE HTTP API, and a check that cannot run is
    worse than one borrowing the installer's transport.
    """
    app = ctx.backend.app
    if "backup_id" not in params:
        # Sweep form, which is what a schedule fires. One job over several
        # archives, so the transcript reads as one pass rather than filling the
        # activity feed with a row per file.
        return await _verify_sweep(ctx, params)
    backup_id = int(params["backup_id"])
    with app.state.sessionmaker() as db:
        row = db.get(Backup, backup_id)
        if row is None:
            raise JobFailed(f"backup {backup_id} is no longer in the list")
        host = db.get(Host, row.host_id)
        if host is None:
            raise JobFailed("the host this archive belongs to is gone")
        volid, guest_type, storage = row.volid, row.guest_type, row.storage
        host_id, address, host_name = host.id, host.address, host.name
        fingerprint = host.ssh_host_key_fingerprint
        label = row.guest_name or volid

    executor = SSHExecutor(connect_factory=app.state.ssh_connect_factory)

    def on_new_fingerprint(fp: str) -> None:
        with app.state.sessionmaker() as db:
            h = db.get(Host, host_id)
            if h is not None:
                h.ssh_host_key_fingerprint = fp
                db.commit()

    lo, hi = band
    ctx.log(f"reading {volid} back off {storage} to check it")
    ctx.progress(lo)

    # `vma verify -v -` counts through the archive on stdout: "progress 42%
    # (read 14431092736 bytes, duration 25 sec)". Read off the stream it is
    # already logging, so the bar moves instead of jumping from the opening
    # figure to done. `tar -tf -` says nothing of the kind, so a container
    # archive holds at `lo`: no progress to report, not 0% of one.
    def on_line(stream: str, line: str) -> None:
        ctx.log(line, stream=stream)
        if stream != "stdout" or not line.startswith("progress "):
            return
        m = _PCT_LINE.search(line)
        if m is not None:
            ctx.progress(lo + (hi - lo) * min(100, int(m.group(1))) // 100)

    try:
        status = await executor.run_for_host(
            app.state.sessionmaker, app.state.secretstore, host_id, address,
            _verify_command(volid, guest_type),
            pinned_fingerprint=fingerprint, on_new_fingerprint=on_new_fingerprint,
            on_line=on_line,
            timeout_s=app.state.settings.pve_task_timeout_s)
    except LookupError as e:
        # executor/keys.py raises this when the host carries no ssh_key.
        raise JobFailed(
            f"checking a backup needs SSH access to {host_name}, which is not "
            f"set up: {e}") from e
    if status == 90:
        raise JobFailed(f"{volid} could not be read on the node, so it was not "
                        f"checked. Its storage may be offline.")
    # A non-zero status from the reader is a successful check with a bad
    # answer, not a failed job: the archive really is unreadable, and raising
    # here would report a broken checker instead.
    verdict = "ok" if status == 0 else "failed"
    with app.state.sessionmaker() as db:
        row = db.get(Backup, backup_id)
        if row is not None:
            row.verify_state = verdict
            row.checked_at = utcnow()
            db.commit()
    ctx.progress(hi)
    ctx.log(f"{label}: "
            + ("the archive read back intact" if verdict == "ok"
               else "the archive did not read back, it is not usable"))
    app.state.bus.publish("resource", {"type": "backup", "change": "list"})
    return {"volid": volid, "verdict": verdict, "exit_status": status}


HANDLERS["backup.verify"] = verify_backup


def _queue_checks(ctx: JobContext, host_id: int, vmids: list[int]) -> None:
    """One `backup.verify` per archive the run that just finished wrote.

    A separate job per archive: a backup that wrote its archive succeeded
    whatever a later check says, and reading one back can take as long again
    as writing it did.

    The newest archive per guest is what "this run wrote", recorded by the
    resync just before. There is no id to match on: vzdump names its own
    files and PVE reports no link between a task and its volids.
    """
    app = ctx.backend.app
    # A host-wide run over a host Proxploy has never polled knows no vmids, so
    # it falls back to the newest handful rather than every archive on the
    # datastore: each one is a full read over the network.
    cap = len(vmids) or 5
    with app.state.sessionmaker() as db:
        q = db.query(Backup).filter(Backup.host_id == host_id)
        if vmids:
            q = q.filter(Backup.guest_vmid.in_(vmids))
        fresh: list[Backup] = []
        seen: set[int | None] = set()
        for b in q.order_by(Backup.taken_at.desc()).all():
            if b.guest_vmid in seen:
                continue
            seen.add(b.guest_vmid)
            fresh.append(b)
            if len(fresh) == cap:
                break
        for b in fresh:
            ctx.backend.enqueue(db, kind="backup.verify", target_type="host",
                                target_id=host_id,
                                target_name=b.guest_name or b.volid,
                                params={"backup_id": b.id})
    word = "archive" if len(fresh) == 1 else "archives"
    ctx.log(f"queued a check for {len(fresh)} {word}")


async def run_backup(ctx: JobContext, params: dict) -> dict:
    """`backup.run`, one vzdump task over the selected guests, or all of them."""
    app = ctx.backend.app
    host_id = int(params["host_id"])
    client, node, host_name = await asyncio.to_thread(_host_target, app, host_id)
    vmids = [int(v) for v in (params.get("vmids") or [])]
    call = {"mode": params.get("mode") or "snapshot",
            "compress": params.get("compress") or "zstd",
            # The archive's FILENAME is PVE's and cannot be templated:
            # vzdump-lxc-150-2026_08_24-02_00_00.tar.zst is parsed back into
            # guest type, vmid and time by the listing and by restore, so a
            # friendlier name would orphan it. The note is the one label that
            # is ours, and what makes an archive read as "Immich", not 150.
            "notes-template": "{{guestname}} ({{vmid}}) on {{node}}"}
    if params.get("storage"):
        call["storage"] = params["storage"]
    # Named in every line below: with no storage chosen PVE picks a backup
    # store itself, and the transcript could not otherwise say where the
    # archive went.
    lands = f"onto {call['storage']}" if call.get("storage") else \
        "onto whichever backup storage Proxmox picks, none was chosen"
    if vmids:
        call["vmid"] = ",".join(str(v) for v in vmids)
        ctx.log(f"vzdump on {host_name}/{node} {lands}: "
                f"{', '.join(str(v) for v in vmids)}")
    else:
        # `all: 1` over a node with no guests made a backup of nothing report
        # plain success: vzdump gets an empty set, PVE finishes with exitstatus
        # OK, and not one byte is written.
        #
        # It succeeds and says so rather than raising JobFailed: an empty node
        # is not an operator error, and a red `backup.run` would raise a
        # `backup_failed` alert off the host's latest finished run
        # (services/alerts.py). The harm was never the exit status, it was a
        # success line implying an archive now exists.
        #
        # The call is SKIPPED rather than made and then explained, because
        # PVE's OK for an empty job cannot be made to mean anything else.
        known, polled = await asyncio.to_thread(guests_on_host, app, host_id)
        if polled and not known:
            detail = (f"{host_name} (node {node}) has no containers and no "
                      f"virtual machines, so there was nothing to back up. No "
                      f"archive was written.")
            ctx.log(detail)
            ctx.progress(100)
            return {"vmids": [], "guests": 0, "detail": detail}
        call["all"] = 1  # empty selection means every guest on the node
        # Naming them answers "what is it backing up?" in the transcript. `all:
        # 1` is still what PVE is asked for, so a guest the last poll has not
        # seen is included even though it is not listed here.
        ctx.log(f"vzdump on {host_name}/{node} {lands}: every container and virtual "
                f"machine on the node"
                + (f", {len(known)} known here ({', '.join(str(v) for v in known)})"
                   if known else ", none known here yet, Proxploy has not polled it"))
    upid = await asyncio.to_thread(client.vzdump, node, call)
    status = await await_task(ctx, client, node, upid,
                              timeout_s=app.state.settings.pve_task_timeout_s,
                              pct_from=_vzdump_pct(len(vmids) or len(known) or 1))
    await _resync(ctx, host_id)
    if params.get("verify"):
        _queue_checks(ctx, host_id, vmids or known)
    # `guests` is what the Backups page counts, not the job's status: PVE
    # returns exitstatus OK for a vzdump that wrote nothing. The early return
    # above reports 0 for an empty node; here it is what was handed to vzdump
    # (`known` for an all:1 run, the last poll's count, which may undercount).
    return {"upid": upid, "exitstatus": status.get("exitstatus"), "vmids": vmids,
            "guests": len(vmids) or len(known)}


HANDLERS["backup.run"] = run_backup


def storage_for_content(client, node: str, want: str) -> str | None:
    """Blocking: the roomiest active storage on `node` whose `content`
    includes `want` ("rootdir" for a CT, "images" for a VM).

    Public because services/migrate.py needs the same pick for the same
    reason: PVE defaults a restore to `local`, which on a stock layout holds
    no rootfs.

    Roomiest, not first-listed. First-listed put a scratch disk on NFS with a
    far larger local pool beside it, and made callers that pick a pool and
    THEN check free space refuse an archive that would have fitted elsewhere.
    Picking the largest makes that refusal honest: if the largest eligible
    pool cannot hold it, none can.

    A pool that does not report `avail` sorts last rather than counting as
    infinite.
    """
    best, best_free = None, None
    for s in client.storages(node):
        if not s.get("active", 1):
            continue
        # PVE has been seen returning `content` both ways; migrate.py's
        # rootfs_candidates reads the same field off the same call and already
        # defends against the list form.
        content = s.get("content") or ""
        parts = content if isinstance(content, list) else content.split(",")
        if want not in [str(p).strip() for p in parts]:
            continue
        name = s.get("storage")
        if not name:
            continue
        avail = s.get("avail")
        free = int(avail) if avail is not None else None
        if best is None or (free is not None and (best_free is None or free > best_free)):
            best, best_free = name, free
    return best


def adopt_restored(app, backup_id: int, new_vmid: int) -> str | None:
    """Blocking: make a restored container Proxploy's own, and say what it is.

    Returns the catalog slug it matched, or None.

    A CT is "tracked" only when an App row exists for (host_id, ctid), and a
    restore-as-new takes a fresh vmid, so without this the restored container
    matches nothing and turns up in the discovered list asking to be adopted.

    Matched on the backup's guest name through the same normalised match the
    discovered list suggests with (pollers/__init__.py::_suggest). It may
    miss: a name the catalog does not know adopts with no slug, exactly as
    adopting it by hand would have.

    Nothing here is done for a VM: Vm rows are the poller's mirror and have
    no adoption step.
    """
    from proxploy.pollers import _norm, _suggest

    with app.state.sessionmaker() as db:
        b = db.get(Backup, backup_id)
        if b is None or b.guest_type != "ct":
            return None
        # An in-place restore overwrote a guest whose row is still here, and a
        # second restore onto the same id must not collide with
        # ux_apps_host_ctid. Either way there is nothing to adopt.
        if db.query(App).filter_by(host_id=b.host_id, ctid=new_vmid).first():
            return None
        name = b.guest_name or f"ct-{new_vmid}"
        catalog = {_norm(c.slug): c.slug for c in db.query(CatalogEntry).all()}
        slug = _suggest(catalog, name)
        entry = (db.query(CatalogEntry).filter_by(slug=slug).one_or_none()
                 if slug else None)
        db.add(App(host_id=b.host_id, ctid=new_vmid, name=name,
                   # Same shape adopt_apps builds, so a restored app and a
                   # hand-adopted one are the same kind of row.
                   slug=f"{slug or 'adopted'}-{b.host_id}-{new_vmid}",
                   catalog_slug=slug, web_path="/", adopted=True,
                   category=entry.category if entry else None,
                   web_port=entry.port if entry else None))
        db.commit()
        return slug


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
        # Nothing chosen: PVE falls back to `local`, a directory store that on
        # a stock layout holds no rootfs or disk image, so every restore died
        # on "storage 'local' does not support container directories". The UI
        # sends no storage, so that was every restore-as-new.
        want = "rootdir" if kind == "lxc" else "images"
        picked = await asyncio.to_thread(storage_for_content, client, node, want)
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
    # The restore runs on LIFECYCLE, not the backup client that read the
    # archive: it writes a guest config, so PVE checks VM.Allocate for a fresh
    # vmid and SDN.Use for the NIC it carries, neither of which the Backup
    # role holds.
    lifecycle_client, _, _ = await asyncio.to_thread(
        _host_target, app, int(info["host_id"]), "lifecycle")
    upid = await asyncio.to_thread(lifecycle_client.restore_guest, kind, node, vmid, call)
    status = await await_task(ctx, lifecycle_client, node, upid,
                              timeout_s=app.state.settings.pve_task_timeout_s)
    await _resync(ctx, info["host_id"])
    # BEFORE the poller wake below, so the mirror refreshes with the App row
    # already there and the restored container never appears as discovered,
    # even for one cycle.
    if not in_place:
        slug = await asyncio.to_thread(
            adopt_restored, app, int(params["backup_id"]), vmid)
        if slug:
            ctx.log(f"adopted {kind} {vmid} as {slug}")
        elif info["guest_type"] == "ct":
            ctx.log(f"adopted {kind} {vmid}; the store does not recognise "
                    f"{info['guest_name'] or 'it'}, so pick its app type by hand "
                    f"if you want update checks")
    # _resync above refreshes the BACKUP cache. A restore also creates or
    # overwrites a guest, and that half belongs to the poller's mirror, so it
    # needs the same wake create_vm gets.
    app.state.poller.wake(int(info["host_id"]))
    return {"upid": upid, "exitstatus": status.get("exitstatus"), "vmid": vmid,
            "mode": "in_place" if in_place else "new"}


HANDLERS["backup.restore"] = restore_backup


def _scratch_vmid_from(client, host_name: str, floor: int = 900) -> int:
    """Blocking: the lowest free guest id at or above `floor`, or refuse.

    Not `cluster_nextid()`, which answers from 100 and would hand back an id
    a human reads as "my guests". Ids from 900 up are the convention for
    throwaway work.

    Read fresh from /cluster/resources, not the poll snapshot, which can be a
    poll interval old.

    The refusal is the load-bearing part. /cluster/resources is filtered by
    the asking token's permissions, and a token that may not read guests is
    told so with an empty list, not a 403: on one twelve-guest cluster the
    lifecycle token saw 2 rows where monitoring saw 22. Read literally that
    says "nothing is in use", so this would answer `floor` unconditionally,
    safe only until somebody has a guest on 900.

    An empty cluster is a real state and must still get an id. The tell is
    not "no guests", it is "no guests AND no storage": any token that can
    read the cluster sees the storage rows.
    """
    rows = client.cluster_resources()
    guests = [r for r in rows if r.get("type") in ("qemu", "lxc")
              and r.get("vmid") is not None]
    if not guests and not any(r.get("type") == "storage" for r in rows):
        raise JobFailed(
            f"Proxploy cannot tell which guest ids are in use on {host_name}, "
            f"so it will not pick one to restore onto. The token it asked with "
            f"cannot read guests; give {host_name} a monitoring token, or add "
            f"VM.Audit to the one it has.")
    used = {int(r["vmid"]) for r in guests}
    vmid = floor
    while vmid in used:
        vmid += 1
    return vmid


def _scratch_vmid(app, host_id: int, fallback, host_name: str,
                  floor: int = 900) -> int:
    """Blocking: `_scratch_vmid_from` asked through the right client.

    Monitoring, not the lifecycle client doing the restore: "which ids exist"
    is a read. Any polled host already has one; a host without one falls back
    to the caller's client, which then either answers honestly or trips the
    refusal above.
    """
    try:
        survey, _, _ = _host_target(app, host_id, "monitoring")
    except (JobFailed, ProxmoxError):
        survey = fallback
    return _scratch_vmid_from(survey, host_name, floor)


def _free_bytes(client, node: str, storage: str) -> int | None:
    """Blocking: free space on one datastore, or None when PVE does not say.

    None means "unknown", and unknown never blocks: refusing a restore over a
    number we do not have would be worse than trying it.
    """
    for st in client.storages(node):
        if st.get("storage") == storage:
            avail = st.get("avail")
            return int(avail) if avail is not None else None
    return None


def _fmt_bytes(n: int) -> str:
    """Sizes for a job log line. GiB is the unit an operator reads a datastore
    in, but a handful of bytes rounds to 0.0 GiB and reads as a bug."""
    gib = n / (1024 ** 3)
    return f"{gib:.1f} GiB" if gib >= 0.1 else f"{n} bytes"


async def test_restore_backup(ctx: JobContext, params: dict) -> dict:
    """`backup.test_restore`: restore into a throwaway id, then destroy it.

    The strongest proof available without PBS: not "the file reads back" but
    "Proxmox built a guest out of it". The copy is never started, never
    networked and never kept, so the only lasting effect is the verdict.
    """
    app = ctx.backend.app
    backup_id = int(params["backup_id"])
    with app.state.sessionmaker() as db:
        row = db.get(Backup, backup_id)
        if row is None:
            raise JobFailed(f"backup {backup_id} is no longer in the list")
        volid, host_id = row.volid, row.host_id
        kind = "lxc" if row.guest_type == "ct" else "qemu"
        size = int(row.size_bytes or 0)
        label = row.guest_name or volid

    # Lifecycle, not backup: this really does create a guest, and the Backup
    # role holds neither VM.Allocate nor SDN.Use (see restore_backup).
    client, node, host_name = await asyncio.to_thread(_host_target, app, host_id,
                                                      "lifecycle")
    target = params.get("storage")
    if not target:
        want = "rootdir" if kind == "lxc" else "images"
        target = await asyncio.to_thread(storage_for_content, client, node, want)
        if target is None:
            raise JobFailed(f"no storage on {host_name} can hold a restored "
                            f"{'container' if kind == 'lxc' else 'virtual machine'}")

    # Preflight, before anything is created: filling the pool to prove a backup
    # is good is worse than not knowing. `size` is the COMPRESSED archive, so
    # it is a floor on what the restore needs, never a ceiling.
    free = await asyncio.to_thread(_free_bytes, client, node, target)
    if free is not None and size and free < size:
        raise JobFailed(f"{target} has {_fmt_bytes(free)} free and this archive "
                        f"needs at least {_fmt_bytes(size)}. Choose another "
                        f"storage or make room. Nothing was created.")

    vmid = await asyncio.to_thread(_scratch_vmid, app, host_id, client, host_name)
    ctx.log(f"restoring {volid} onto {target} as a throwaway {kind} {vmid} on "
            f"{host_name}/{node}, it will be deleted when the check finishes")
    ctx.progress(5)

    call = ({"ostemplate": volid, "restore": 1, "storage": target} if kind == "lxc"
            else {"archive": volid, "storage": target})
    created = False
    verdict = "failed"
    try:
        upid = await asyncio.to_thread(client.restore_guest, kind, node, vmid, call)
        created = True
        await await_task(ctx, client, node, upid,
                         timeout_s=app.state.settings.pve_task_timeout_s,
                         start_pct=10, end_pct=90)
        verdict = "ok"
    finally:
        # Only once PVE accepted the call. A restore that never started proves
        # nothing about the archive, the same way verify's exit 90 does not,
        # and marking it "failed" would blame the archive for a broken check.
        if created:
            # The verdict is written BEFORE the cleanup, deliberately: a
            # destroy that fails must not also lose what the restore proved.
            with app.state.sessionmaker() as db:
                b = db.get(Backup, backup_id)
                if b is not None:
                    b.verify_state = verdict
                    b.checked_at = utcnow()
                    db.commit()
            app.state.bus.publish("resource", {"type": "backup", "change": "list"})
            ctx.log(f"deleting the throwaway {kind} {vmid}")
            try:
                del_upid = await asyncio.to_thread(client.guest_delete, kind, node,
                                                   vmid)
                await await_task(ctx, client, node, del_upid,
                                 timeout_s=app.state.settings.pve_task_timeout_s,
                                 report_progress=False)
            except Exception as e:  # noqa: BLE001
                # Never swallowed. A guest nobody knows about, holding a disk,
                # is worse than a red job.
                raise JobFailed(
                    f"the archive was restored but the throwaway {kind} {vmid} "
                    f"on {node} could not be deleted: {e}. Delete it by hand."
                ) from e
            finally:
                # The guest was created either way, so the poller's mirror is
                # stale whether or not the delete landed.
                app.state.poller.wake(host_id)

    ctx.progress(100)
    ctx.log(f"{label}: restored cleanly, and the throwaway copy was deleted")
    return {"volid": volid, "verdict": verdict, "scratch_vmid": vmid}


HANDLERS["backup.test_restore"] = test_restore_backup


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
