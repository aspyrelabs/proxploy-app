# backend/proxploy/api/storage.py
"""Storage routes (doc 05 §Storage, doc 01 §5).

Reads only, in this task. The LIST is served from the poller's in-memory
`HostSnapshot.storage`: doc 05 calls it a "live-refreshed cache", and since the
poll loop's single `cluster_resources()` already carries every field the page
needs, listing costs zero PVE calls. Detail and content are on-demand
passthroughs, one PVE call each, triggered by a human opening a datastore.
There is no storage table and none is added: doc 04 defines no storage entity.

Entitlements: doc 05 leaves the column blank on all three reads. Doc 01 §5
names `storage.view` (datastore overview) and `storage.content` (content
browser) as real features, and doc 07 §3 says a feature without a key does not
merge, so the reads are gated with their doc-01 keys rather than left ungated.
Functionally identical today (every flag defaults ON); recorded as a doc-05
amendment in the phase notes.
"""
from __future__ import annotations

import contextlib
import os
import tempfile

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Request,
                     UploadFile)
from pydantic import BaseModel

from proxploy.api.deps import (authorize, cluster_scope, get_db,
                               require_entitlement, scope_host)
from proxploy.api.jobs import enqueue_and_audit
from proxploy.pollers import pool_key, storage_snapshot_rows
from proxploy.models import Host, Schedule, User
from proxploy.services.audit import write_audit
from proxploy.services.hostclient import client_for_host
from proxploy.services.proxmox import ProxmoxError

router = APIRouter(prefix="/storage", tags=["storage"])

# Reused as BOTH the route-level dependency and the parameter-level one so
# FastAPI's dependency cache (keyed on the callable) collapses them into a
# single call that runs FIRST. A bare `dependencies=[Depends(require_entitlement(...))]`
# lands at position 0 and runs BEFORE auth, answering an anonymous caller with
# 403 instead of 401: see tests/test_route_auth_invariant.py. scope_host()'s
# default param "host_id" matches every {host_id} path segment in this router;
# on GET "" (no host id in the path) the resolver returns None and enforce()
# falls back to "any of the user's teams", same as before this had a scope.
_read = authorize("storage", "read", scope_of=scope_host())
_content = authorize("storage", "content", scope_of=scope_host())
_manage_global = authorize("storage", "manage")          # POST "" (host_id in body)
_manage = authorize("storage", "manage", scope_of=scope_host())
_remove = authorize("storage", "remove", scope_of=scope_host())

UPLOAD_CHUNK = 1024 * 1024


class StorageAttachIn(BaseModel):
    """`config` is a free-form passthrough because the key set is per-plugin
    (dir wants `path`, nfs wants `server`+`export`, pbs wants `server`+
    `datastore`+`username`+`password`+`fingerprint`) and Proxmox is the
    authority on what is valid, mirroring it here would be a second schema to
    keep in sync and a new way to reject a storage type Proxmox supports.
    It may carry a live credential; see the module note on where it does NOT go."""
    host_id: int
    storage: str
    type: str
    config: dict = {}


class StorageEditIn(BaseModel):
    config: dict


def _resync_snapshot(request: Request, db, host: Host) -> None:
    """The LIST above is served from the poll snapshot, so a change PVE has
    already applied stays invisible for up to a whole poll interval: unticking
    `backup` on a datastore left the Backups page still counting it, until the
    poller came round and it changed under the operator's hands. One
    cluster_resources() call, the same one the poller makes, is enough for the
    next read to tell the truth.

    Read on MONITORING, never on the lifecycle client these routes write with.
    /cluster/resources returns only what the token may audit, and the Lifecycle
    role deliberately carries no Datastore.Audit (services/pveum.py), so that
    client sees an EMPTY cluster: reading through it wiped every datastore off
    the Storage page for a whole poll interval after any edit.

    Written to EVERY enrolled member of the same cluster, not just the host the
    write went to. /cluster/resources answers for the whole cluster, so each
    member's snapshot holds its own copy of these same rows, and the LIST above
    dedupes across all of them keeping whichever it sees FIRST. Refreshing one
    host therefore fixed nothing on a two-node cluster whenever the peer's
    stale copy won that race.

    Best effort in both directions: the write has already succeeded by the time
    this runs, so a failure here must not fail the request, and the poller
    corrects the snapshots within the cycle regardless.
    """
    snaps = request.app.state.poller.snapshots
    try:
        rows = storage_snapshot_rows(
            client_for_host(request.app, db, host).cluster_resources())
    except Exception:  # noqa: BLE001  (never fail a write that already succeeded)
        return
    # An empty read is not proof the cluster has no storage, it is equally a
    # token that may not see it or a node that answered thin. The same reason
    # pollers/__init__.py::_absence_is_trustworthy exists: leave the snapshot
    # alone and let the poller, which can tell those apart, decide.
    if not rows:
        return
    scope = cluster_scope(host)
    for h in db.query(Host).all():
        if cluster_scope(h) == scope and h.id in snaps:
            snaps[h.id].storage = rows


def _backup_job_on(request: Request, db, host: Host, name: str) -> str | None:
    """The name of an enabled backup schedule this detach would strand, or None.

    A scheduled `backup.run` carries no storage of its own (ScheduleForm sends
    only `host_id`, and services/backupjobs.py lets PVE pick from whatever
    accepts `backup` content), so detaching one of several backup datastores
    strands nothing and is NOT refused. Detaching the last one leaves the job
    with nowhere to write, which is what the guard is for.

    A host with no snapshot has never been polled, so "another target exists"
    cannot be shown to be true; that counts as the last one rather than
    assuming the operator is safe.
    """
    snap = request.app.state.poller.snapshots.get(host.id)
    others = [r for r in (snap.storage if snap else [])
              if r.get("storage") != name and "backup" in _content_list(r.get("content"))]
    if others:
        return None
    for s in (db.query(Schedule)
                .filter(Schedule.job_kind == "backup.run", Schedule.enabled.is_(True))
                .all()):
        if (s.params or {}).get("host_id") == host.id:
            return s.name
    return None


def _pct(used: float, total: float) -> float:
    return round(used / total * 100, 1) if total else 0.0


def _content_list(v) -> list[str]:
    """Snapshot rows already hold a list; `storage_status()` returns PVE's raw
    comma string ("iso,vztmpl,backup"). Accept either."""
    if isinstance(v, list):
        return v
    return [c for c in str(v or "").split(",") if c]


def _row(host: Host, st: dict) -> dict:
    used, total = int(st.get("used_bytes") or 0), int(st.get("total_bytes") or 0)
    return {"host_id": host.id, "host_name": host.name, "node": st.get("node"),
            # The serving host's cluster, so a caller can tell "a sibling node
            # of my cluster reported this" from "an unrelated host did". The
            # dedupe below deliberately drops host_id from its key, so host_id
            # alone cannot answer that, and the install dialog filtering on it
            # was why one host of a cluster saw no pools at all.
            "cluster_name": host.cluster_name,
            "storage": st.get("storage"), "type": st.get("type"),
            "content": _content_list(st.get("content")),
            "shared": bool(st.get("shared")),
            "status": st.get("status") or "unknown",
            "used_bytes": used, "total_bytes": total,
            "used_pct": _pct(used, total)}


def _host_or_404(db, host_id: int) -> Host:
    host = db.get(Host, host_id)
    if host is None:
        raise HTTPException(404, "host not found")
    return host


def _nodes_with(request: Request, host_id: int, name: str) -> list[str]:
    snap = request.app.state.poller.snapshots.get(host_id)
    if snap is None:
        return []
    return sorted({st["node"] for st in snap.storage
                   if st.get("storage") == name and st.get("node")})


def _resolve_node(request: Request, host: Host, name: str, node: str | None) -> str:
    """Every per-datastore PVE path is node-scoped, but the UI addresses a
    datastore by (host, name). Explicit ?node= wins; otherwise take the first
    node the last poll saw serving it, then the host's own node."""
    if node:
        return node
    found = _nodes_with(request, host.id, name)
    if found:
        return found[0]
    if host.node_name:
        return host.node_name
    raise HTTPException(409, f"cannot tell which node serves {name!r} on "
                             f"{host.name}, pass ?node=")


@router.get("", dependencies=[Depends(_read),
                              Depends(require_entitlement("storage.view"))])
def list_storage(request: Request, db=Depends(get_db),
                 user: User = Depends(_read)):
    snaps = request.app.state.poller.snapshots
    hosts = {h.id: h for h in db.query(Host).all()}
    seen: dict[tuple, dict] = {}
    for host_id, snap in snaps.items():
        host = hosts.get(host_id)
        if host is None:
            continue  # host deleted between poll and request
        for st in snap.storage:
            # A shared datastore is reported once per node and is ONE
            # datastore; a local one with the same name on two nodes is two.
            # No host_id in the key: two Hosts can be two nodes of the SAME
            # cluster, and cluster_resources() returns the whole cluster from
            # either one, so both snapshots carry every datastore. host_id
            # in the key made each polling host's copy look like a distinct
            # datastore; the surviving row is just whichever host's poll was
            # seen first, which is fine since any host in the cluster can
            # serve it. cluster_scope(host) IS still needed: a node name and
            # a datastore name are only unique within one cluster, so two
            # different clusters (or two standalone hosts) with a same-named
            # node or datastore must not collapse into one row.
            key = (cluster_scope(host), pool_key(st))
            seen.setdefault(key, _row(host, st))
    return sorted(seen.values(),
                  key=lambda r: (r["storage"] or "", r["node"] or "", r["host_id"]))


@router.get("/{host_id}/{name}",
            dependencies=[Depends(_read),
                          Depends(require_entitlement("storage.view"))])
def storage_detail(request: Request, host_id: int, name: str,
                   node: str | None = None, db=Depends(get_db),
                   user: User = Depends(_read)):
    host = _host_or_404(db, host_id)
    node = _resolve_node(request, host, name, node)
    try:
        st = client_for_host(request.app, db, host).storage_status(node, name)
    except ProxmoxError as e:
        raise HTTPException(502, str(e))
    used, total = int(st.get("used") or 0), int(st.get("total") or 0)
    return {"host_id": host.id, "host_name": host.name, "node": node,
            "storage": name, "type": st.get("type"),
            "content": _content_list(st.get("content")),
            "shared": bool(st.get("shared")),
            "status": "available" if st.get("active") else "inactive",
            "used_bytes": used, "total_bytes": total,
            "avail_bytes": int(st.get("avail") or 0),
            "used_pct": _pct(used, total),
            "nodes": _nodes_with(request, host_id, name) or [node]}


@router.get("/{host_id}/{name}/content",
            dependencies=[Depends(_read),
                          Depends(require_entitlement("storage.content"))])
def storage_content(request: Request, host_id: int, name: str,
                    node: str | None = None, content: str | None = None,
                    db=Depends(get_db), user: User = Depends(_read)):
    host = _host_or_404(db, host_id)
    node = _resolve_node(request, host, name, node)
    try:
        rows = client_for_host(request.app, db, host).storage_content(node, name, content)
    except ProxmoxError as e:
        raise HTTPException(502, str(e))
    # `content` already rides to PVE as a server-side filter (proxmox.py); this
    # re-applies it client-side so the response is correct even against a PVE
    # (or fake) that ignores the filter param and returns everything.
    return [{"volid": r.get("volid"), "format": r.get("format"),
             "size": int(r.get("size") or 0), "used": int(r.get("used") or 0),
             "vmid": r.get("vmid"), "ctime": r.get("ctime"),
             "content": r.get("content"), "notes": r.get("notes"),
             "verification": r.get("verification")}
            for r in rows if not content or r.get("content") == content]


def _refuse_silent_overwrite(request, db, host, node: str, storage: str,
                             content: str, filename: str,
                             overwrite: bool) -> None:
    """An upload whose name already exists REPLACES the existing volume, and
    PVE does it without a word: the second of two uploads under one name simply
    wins (observed on PVE 9.2.6, 2026-08-10). An ISO a VM is booting from can be
    swapped out from under it that way.

    A brand-new name stays frictionless; nothing is being destroyed there. A
    collision stops and asks once, and `overwrite=true` is the whole answer:
    deliberately a plain boolean the UI drives from a Replace/Skip/Cancel
    dialog, NOT the typed confirm_phrase that backups.py and vms.py use. Those
    guard deletions, which are unrecoverable; replacing a file the operator is
    in the middle of uploading is not in that class.

    Checked BEFORE the body is spooled, so a multi-GB upload is not read to
    disk only to be rejected.
    """
    if overwrite:
        return
    volid = f"{storage}:{content}/{filename}"
    try:
        client = client_for_host(request.app, db, host)
        existing = {r.get("volid"): r for r in
                    client.storage_content(node, storage, content=content)}
    except ProxmoxError as e:
        # Cannot read the storage: the upload itself would fail next anyway,
        # and a 409 naming the real reason beats a confusing overwrite prompt.
        raise HTTPException(409, str(e)) from e
    row = existing.get(volid)
    if row is None:
        return
    raise HTTPException(409, {
        "error": "volume_exists",
        # Named parts so the dialog can render the file without parsing prose.
        "volid": volid,
        "filename": filename,
        "size_bytes": row.get("size"),
        "detail": (f"{volid} already exists on {storage}"
                   + (f" ({row.get('size')} bytes)" if row.get("size") else "")
                   + ". Replacing it keeps the name and swaps the contents, so "
                     "anything already using it gets the new file."),
    })


@router.post("/{host_id}/{name}/content", status_code=202,
             dependencies=[Depends(_content),
                           Depends(require_entitlement("storage.content"))])
def upload_content(request: Request, host_id: int, name: str,
                   file: UploadFile = File(...), content: str = Form("iso"),
                   node: str | None = Form(None), overwrite: bool = Form(False),
                   db=Depends(get_db), user: User = Depends(_content)):
    """Spool the body to disk, then hand the PATH to a job (doc 05 §Storage).

    Never slurp the whole upload in one call: FastAPI's UploadFile already
    spools to a SpooledTemporaryFile, and reading it all at once would
    materialise a multi-GB ISO in this process's RAM. The 1 MiB loop below
    keeps peak memory flat regardless of file size. The cost, stated in
    services/storagejobs.py's docstring too: the ISO crosses the wire twice
    (browser -> here -> PVE) and the Proxploy host needs transient free disk
    equal to the file size.
    """
    host = _host_or_404(db, host_id)
    node = _resolve_node(request, host, name, node)
    _refuse_silent_overwrite(request, db, host, node, name, content,
                             file.filename or "upload", overwrite)
    max_bytes = request.app.state.settings.storage_upload_max_bytes
    updir = request.app.state.settings.data_dir / "uploads"
    updir.mkdir(parents=True, exist_ok=True)
    fd, spool = tempfile.mkstemp(dir=updir, suffix=".upload")
    written = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = file.file.read(UPLOAD_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(413, f"upload exceeds the "
                                             f"{max_bytes} byte limit")
                out.write(chunk)
    except BaseException:
        # Anything at all: cap exceeded, disconnect, cancellation; must not
        # leave a partial multi-GB file behind on the Proxploy host.
        with contextlib.suppress(OSError):
            os.unlink(spool)
        raise
    return enqueue_and_audit(
        request, db, user, kind="storage.upload", target_type="storage",
        target_id=host.id,
        # target_id is the HOST here, so nothing can look this name up
        # later; the storage a person recognises is the pool on that host.
        target_name=f"{name} on {host.name}",
        params={"host_id": host.id, "node": node, "storage": name,
                "content": content, "filename": file.filename or "upload",
                # `spool_path`, not `path`: the job runner deletes whatever
                # this key names on every exit, including a cancel that
                # settles the job before its handler ever runs
                # (jobs/backend.py::JobBackend._run).
                "spool_path": spool, "size_bytes": written})


@router.delete("/{host_id}/{name}/content/{volid:path}", status_code=202,
               dependencies=[Depends(_content),
                             Depends(require_entitlement("storage.content"))])
def delete_content(request: Request, host_id: int, name: str, volid: str,
                   node: str | None = None, db=Depends(get_db),
                   user: User = Depends(_content)):
    """`:path` because a volid is `local:iso/ubuntu.iso`; it carries a slash,
    which a plain `{volid}` converter would refuse to match."""
    host = _host_or_404(db, host_id)
    node = _resolve_node(request, host, name, node)
    return enqueue_and_audit(
        request, db, user, kind="storage.delete_volume", target_type="storage",
        target_id=host.id, target_name=f"{name} on {host.name}",
        params={"host_id": host.id, "node": node, "storage": name, "volid": volid})


@router.post("", status_code=201,
             dependencies=[Depends(_manage_global),
                           Depends(require_entitlement("storage.manage"))])
def attach_storage(request: Request, body: StorageAttachIn, db=Depends(get_db),
                   user: User = Depends(_manage_global)):
    """Attach a storage definition (doc 05 §Storage, doc 01 §5 "Add/edit storage").

    Synchronous: Proxmox returns no UPID for /storage, so there is no job and
    therefore no `jobs.params` row holding `body.config`. The audit row is the
    only durable trace, and write_audit runs it through redact(); nested
    `config.password` included.

    The response deliberately echoes NO config: a credential the caller just
    sent must not come back out of a GET the browser might cache or a screenshot
    someone pastes into a ticket.

    `capability="lifecycle"`: attaching/editing/detaching a storage POOL
    DEFINITION needs Datastore.Allocate, a node-infrastructure privilege
    none of the four capabilities carried until the per-capability token
    sweep found the gap (host-token-privileges-step-one-report.md), the
    same class of bug Sys.PowerMgmt was.
    """
    host = _host_or_404(db, body.host_id)
    ip = request.client.host if request.client else None
    # target_id here is the HOST's id, not a storage row's, so
    # resolve_target_name has nothing to look up and these rows rendered as
    # "storage #1", an id that points at a different table. Same label the
    # upload and delete-volume routes above already pass.
    label = f"{body.storage} on {host.name}"
    # Route-controlled keys (storage/type) go LAST in the unpack so a
    # caller-supplied config.storage or config.type overrides nothing this
    # route says it is attaching: storage.py has no _SAFE_KEY filter at all
    # (deliberate free-form plugin passthrough), so this collision is even
    # more open than network.py's.
    client = client_for_host(request.app, db, host, capability="lifecycle")
    try:
        client.storage_create({**body.config, "storage": body.storage, "type": body.type})
    except ProxmoxError as e:
        write_audit(db, actor_type="user", actor_id=user.id, action="storage.create",
                    target_type="storage", target_id=host.id, target_name=label,
                    params=body.model_dump(), result="error", ip=ip)
        raise HTTPException(502, str(e))
    write_audit(db, actor_type="user", actor_id=user.id, action="storage.create",
                target_type="storage", target_id=host.id, target_name=label,
                params=body.model_dump(), ip=ip)
    _resync_snapshot(request, db, host)
    request.app.state.bus.publish("resource", {"type": "storage", "id": host.id,
                                               "change": "list"})
    return {"host_id": host.id, "storage": body.storage, "type": body.type}


@router.patch("/{host_id}/{name}",
              dependencies=[Depends(_manage),
                            Depends(require_entitlement("storage.manage"))])
def edit_storage(request: Request, host_id: int, name: str, body: StorageEditIn,
                 db=Depends(get_db), user: User = Depends(_manage)):
    """Audits the NAMES of the keys changed, never their values; the same rule
    settings.py::patch_settings follows, and the reason a rotated PBS password
    leaves a legible audit trail without leaving the password in it."""
    host = _host_or_404(db, host_id)
    keys = sorted(body.config)
    ip = request.client.host if request.client else None
    label = f"{name} on {host.name}"
    client = client_for_host(request.app, db, host, capability="lifecycle")
    try:
        client.storage_update(name, body.config)
    except ProxmoxError as e:
        write_audit(db, actor_type="user", actor_id=user.id, action="storage.update",
                    target_type="storage", target_id=host.id, target_name=label,
                    params={"storage": name, "keys": keys}, result="error", ip=ip)
        raise HTTPException(502, str(e))
    write_audit(db, actor_type="user", actor_id=user.id, action="storage.update",
                target_type="storage", target_id=host.id, target_name=label,
                params={"storage": name, "keys": keys}, ip=ip)
    _resync_snapshot(request, db, host)
    request.app.state.bus.publish("resource", {"type": "storage", "id": host.id,
                                               "change": "list"})
    return {"host_id": host.id, "storage": name, "updated": keys}


@router.delete("/{host_id}/{name}",
               dependencies=[Depends(_remove),
                             Depends(require_entitlement("storage.manage"))])
def detach_storage(request: Request, host_id: int, name: str, db=Depends(get_db),
                   user: User = Depends(_remove)):
    """Owner, not admin (doc 05): detaching drops the definition while guest
    disks keep pointing at it, which is the one action here that can strand
    running guests. Upstream data is left in place; this is not a wipe."""
    host = _host_or_404(db, host_id)
    ip = request.client.host if request.client else None
    label = f"{name} on {host.name}"
    stranded = _backup_job_on(request, db, host, name)
    if stranded is not None:
        raise HTTPException(409, f'The backup job "{stranded}" writes to {name}, and it is '
                                 f"the last storage on {host.name} that accepts backups. "
                                 "Update or remove the job before detaching this storage.")
    client = client_for_host(request.app, db, host, capability="lifecycle")
    try:
        client.storage_remove(name)
    except ProxmoxError as e:
        write_audit(db, actor_type="user", actor_id=user.id, action="storage.remove",
                    target_type="storage", target_id=host.id, target_name=label,
                    params={"storage": name}, result="error", ip=ip)
        raise HTTPException(502, str(e))
    write_audit(db, actor_type="user", actor_id=user.id, action="storage.remove",
                target_type="storage", target_id=host.id, target_name=label,
                params={"storage": name}, ip=ip)
    _resync_snapshot(request, db, host)
    request.app.state.bus.publish("resource", {"type": "storage", "id": host.id,
                                               "change": "list"})
    return {"host_id": host.id, "storage": name, "detached": True}
