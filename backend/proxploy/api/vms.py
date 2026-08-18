"""VM read + lifecycle endpoints (doc 05, Phase 2/3 rows). Pure cache mirror +
snapshot cpu."""
from __future__ import annotations

import re

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel

from proxploy.api.apps import LifecycleIn, enqueue_lifecycle
from proxploy.api.deps import authorize, get_db, require_entitlement, scope_vm
from proxploy.api.jobs import enqueue_and_audit, job_out
from proxploy.api.network import NicIn, guest_nics, set_guest_nic
from proxploy.models import Host, User, Vm, to_iso
from proxploy.services.audit import write_audit
from proxploy.services.hostclient import client_for_host, guest_node
from proxploy.services.lifecycle import VM_ACTIONS
from proxploy.services.proxmox import ProxmoxError
from proxploy.services.selfguard import is_self

router = APIRouter(prefix="/vms", tags=["vms"])

# Singletons so FastAPI's dependency cache (keyed on the callable) collapses
# repeated uses into one call per request, and so route-level dependencies=[...]
# and the parameter-level copy run the same auth check first (doc 10 "auth
# before entitlement" ordering invariant). scope_vm()'s default param "vm_id"
# matches every {vm_id} path segment in this router.
_read = authorize("vm", "read", scope_of=scope_vm())
_lifecycle = authorize("vm", "lifecycle", scope_of=scope_vm())
_snapshot = authorize("vm", "snapshot", scope_of=scope_vm())
_rollback = authorize("vm", "rollback", scope_of=scope_vm())
_create = authorize("vm", "create")               # host_id is body-carried, no id yet
_clone = authorize("vm", "clone", scope_of=scope_vm())
_remove = authorize("vm", "remove", scope_of=scope_vm())
_configure = authorize("vm", "configure", scope_of=scope_vm())


def _vm_out(v: Vm, host: Host, snapshots) -> dict:
    snap = snapshots.get(v.host_id)
    g = snap.guests.get(("qemu", v.vmid)) if snap else None
    return {
        "id": v.id, "host_id": v.host_id, "host_name": host.name,
        "vmid": v.vmid, "name": v.name, "status": v.status,
        "os_type": v.os_type,  # NULL in Phase 2 (plan decision 5)
        "cpu_cores": v.cpu_cores,
        "cpu_pct": g["cpu_pct"] if g else None,
        "mem_bytes": v.mem_bytes, "disk_bytes": v.disk_bytes,
        "uptime_s": v.uptime_s,
        "synced_at": to_iso(v.synced_at),
    }


@router.get("")
def list_vms(request: Request, host: int | None = None, db=Depends(get_db),
             user: User = Depends(_read)):
    hosts = {h.id: h for h in db.query(Host).all()}
    query = db.query(Vm)
    if host is not None:
        query = query.filter(Vm.host_id == host)
    return [_vm_out(v, hosts[v.host_id], request.app.state.poller.snapshots)
            for v in query.order_by(Vm.name).all() if v.host_id in hosts]


@router.get("/{vm_id}")
def vm_detail(request: Request, vm_id: int, db=Depends(get_db),
              user: User = Depends(_read)):
    v = db.get(Vm, vm_id)
    if v is None:
        raise HTTPException(404, "vm not found")
    return _vm_out(v, db.get(Host, v.host_id), request.app.state.poller.snapshots)


def _vm_and_host(db, vm_id: int):
    v = db.get(Vm, vm_id)
    if v is None:
        raise HTTPException(404, "vm not found")
    host = db.get(Host, v.host_id)
    if host is None:
        raise HTTPException(404, "host not found")
    return v, host


# Registered ABOVE the /{vm_id}/{action} wildcard below: Starlette matches in
# registration order, and although that wildcard is POST-only today, doc 05's
# future two-segment siblings are not. Same WARNING as apps.py:266-271.
# test_network_api.py asserts this ordering by route index.
@router.get("/{vm_id}/network",
            dependencies=[Depends(_read),
                          Depends(require_entitlement("network.guest_config"))])
def vm_network(request: Request, vm_id: int, db=Depends(get_db),
               user: User = Depends(_read)):
    v, host = _vm_and_host(db, vm_id)
    return guest_nics(request, db, host, "qemu", v.vmid, v)


@router.put("/{vm_id}/network/{iface}",
            dependencies=[Depends(_configure),
                          Depends(require_entitlement("network.guest_config"))])
def vm_network_update(request: Request, vm_id: int, iface: str, body: NicIn,
                      db=Depends(get_db), user: User = Depends(_configure)):
    v, host = _vm_and_host(db, vm_id)
    return set_guest_nic(request, db, user, target_type="vm", target_id=v.id,
                         host=host, kind="qemu", vmid=v.vmid, iface=iface, body=body,
                         row=v)


# PVE's own name rule for a guest: a DNS-ish label, since it becomes the
# hostname the guest advertises.
VM_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,62}$")


def _pick_node(request: Request, host: Host, node: str | None) -> str:
    """Resolve and validate the target node for a create.

    The known-node list comes from the poller's snapshot for this host (its
    `nodes` entries are `{"node": name, …}`), falling back to `Host.node_name`
    for a host that has not been polled yet. A caller-supplied node is checked
    against that list; an unknown one is a 422 rather than a job that fails
    thirty seconds later inside Proxmox.
    """
    snap = request.app.state.poller.snapshots.get(host.id)
    known = [n["node"] for n in (snap.nodes if snap else []) if n.get("node")]
    if not known and host.node_name:
        known = [host.node_name]
    if node:
        if known and node not in known:
            raise HTTPException(422, f"node {node!r} is not on host {host.name} "
                                     f"(known: {', '.join(known)})")
        return node
    if not known:
        raise HTTPException(422, "this host has no known node yet; wait for the "
                                 "first poll or name a node explicitly")
    return known[0]


class VmCreateIn(BaseModel):
    host_id: int
    name: str
    node: str | None = None
    vmid: int | None = None
    cores: int = 2
    memory_mb: int = 2048
    disk_gb: int = 32
    storage: str = "local-lvm"
    iso: str | None = None
    bridge: str = "vmbr0"
    # Task 17's wizard has a VLAN field on its Network step. Pydantic ignores
    # unknown keys rather than rejecting them, so omitting this here would
    # silently drop the operator's tag and build an untagged NIC: a wrong
    # result that looks like a success. Declared, validated, and threaded
    # through to net0 below.
    vlan_tag: int | None = None
    ostype: str = "l26"
    start: bool = False


@router.post("", status_code=202,
             dependencies=[Depends(_create),
                           Depends(require_entitlement("vms.create"))])
def create_vm_route(request: Request, body: VmCreateIn, db=Depends(get_db),
                    user: User = Depends(_create)):
    """Validate the spec here, not in the job: a bad spec should be a 422 the
    operator sees while the form is still open, not a failed job in the history.
    """
    host = db.get(Host, body.host_id)
    if host is None:
        raise HTTPException(404, "host not found")
    if not VM_NAME_RE.match(body.name or ""):
        raise HTTPException(422, "name must be a hostname-shaped label: letters, "
                                 "digits, '.' and '-', starting with a letter or "
                                 "digit")
    for field, value in (("cores", body.cores), ("memory_mb", body.memory_mb),
                         ("disk_gb", body.disk_gb)):
        if value <= 0:
            raise HTTPException(422, f"{field} must be greater than zero")
    node = _pick_node(request, host, body.node)
    vmid = body.vmid
    if vmid is None:
        # Minted here so the 202 can name the id and the audit row records it.
        # cluster_nextid is advisory, not a reservation: between this call and
        # the job's POST another orchestrator can take the id, and PVE then
        # rejects the create. See create_vm()'s ponytail comment: no retry.
        client = client_for_host(request.app, db, host, capability="lifecycle")
        try:
            vmid = int(client.cluster_nextid())
        except ProxmoxError as e:
            raise HTTPException(502, str(e)) from e
    params = {"host_id": host.id, "node": node, "vmid": int(vmid),
              "name": body.name, "cores": body.cores, "memory_mb": body.memory_mb,
              "disk_gb": body.disk_gb, "storage": body.storage, "iso": body.iso,
              "bridge": body.bridge, "vlan_tag": body.vlan_tag,
              "ostype": body.ostype, "start": body.start}
    out = enqueue_and_audit(request, db, user, kind="vm.create",
                            target_type="host", target_id=host.id, params=params)
    return {**out, "vmid": int(vmid)}


# Registered ABOVE the /{vm_id}/{action} wildcard: see the WARNING on that
# route. Out of order, `POST /vms/3/snapshots` lands in vm_lifecycle with
# action="snapshots" and 422s (test_post_snapshots_is_not_swallowed_by_the_
# lifecycle_wildcard proves it stays this way).

# PVE's own pve-configid shape, plus its 40-char ceiling. Enforced here because
# the value is interpolated into a Proxmox path segment, and because "current"
# is PVE's synthetic pseudo-snapshot name and must never be creatable.
SNAP_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,39}$")


def _valid_snap_name(name: str) -> str:
    if not SNAP_NAME_RE.match(name or "") or name == "current":
        raise HTTPException(422, "snapshot name must start with a letter and use "
                                 "only letters, digits, '-' and '_' (2-40 chars), "
                                 "and cannot be 'current'")
    return name


def _snapshot_out(s: dict) -> dict:
    return {
        "name": s.get("name"),
        "description": s.get("description"),
        "snaptime": s.get("snaptime"),
        # PVE returns 0/1 (and omits it entirely on containers)
        "vmstate": bool(int(s.get("vmstate") or 0)),
        "parent": s.get("parent"),
    }


@router.get("/{vm_id}/snapshots",
            dependencies=[Depends(_read),
                          Depends(require_entitlement("vms.snapshots"))])
def list_vm_snapshots(request: Request, vm_id: int, db=Depends(get_db),
                      user: User = Depends(_read)):
    """Live read on every request (doc 05: "List snapshots (live from
    Proxmox)"); there is no snapshot table and this phase adds none.

    PVE always includes a synthetic `current` entry describing the running
    state. It is not a snapshot, has no snaptime, and cannot be rolled back to
    or deleted, so it is dropped here rather than in the UI; otherwise every
    consumer of this endpoint has to know the same trivia.
    """
    v, host = _vm_and_host(db, vm_id)
    client = client_for_host(request.app, db, host)
    try:
        rows = client.snapshots("qemu", guest_node(host, v), v.vmid)
    except ProxmoxError as e:
        raise HTTPException(502, str(e)) from e
    return [_snapshot_out(s) for s in rows if s.get("name") != "current"]


class SnapshotIn(BaseModel):
    name: str
    description: str | None = None
    vmstate: bool = False


@router.post("/{vm_id}/snapshots", status_code=202,
             dependencies=[Depends(_snapshot),
                           Depends(require_entitlement("vms.snapshots"))])
def create_vm_snapshot(request: Request, vm_id: int, body: SnapshotIn,
                       db=Depends(get_db),
                       user: User = Depends(_snapshot)):
    v, _host = _vm_and_host(db, vm_id)
    name = _valid_snap_name(body.name)
    return enqueue_and_audit(request, db, user, kind="vm.snapshot_create",
                             target_type="vm", target_id=v.id,
                             params={"vm_id": v.id, "name": name,
                                     "description": body.description,
                                     "vmstate": body.vmstate})


class RollbackIn(BaseModel):
    confirm: str | None = None


@router.post("/{vm_id}/snapshots/{name}/rollback", status_code=202,
             dependencies=[Depends(_rollback),
                           Depends(require_entitlement("vms.snapshots"))])
def rollback_vm_snapshot(request: Request, vm_id: int, name: str,
                         body: RollbackIn = Body(default=RollbackIn()),
                         db=Depends(get_db),
                         user: User = Depends(_rollback)):
    """Rollback throws away every write since the snapshot was taken; there is
    no undo and no second copy. It therefore reuses the same three-key 409
    *shape* (`error`/`confirm_phrase`/`detail`) `enqueue_lifecycle` uses, so
    the frontend's existing typed-confirmation dialog renders it with no new
    component, but the `error` value here is `"confirm_required"`, not
    `enqueue_lifecycle`'s self-targeted-stop `"self_target"`: rollback asks
    for confirmation from *every* caller, not only when the VM happens to be
    the one Proxploy itself runs in. The frontend keys on this exact string,
    so do not conflate the two.
    """
    v, _host = _vm_and_host(db, vm_id)
    _valid_snap_name(name)
    vm_name = v.name or f"VM {v.vmid}"
    ip = request.client.host if request.client else None
    if (body.confirm or "") != vm_name:
        write_audit(db, actor_type="user", actor_id=user.id,
                    action="vm.snapshot_rollback", target_type="vm",
                    target_id=v.id, params={"name": name}, result="denied", ip=ip)
        raise HTTPException(409, {
            "error": "confirm_required", "confirm_phrase": vm_name,
            "detail": (f"Rolling {vm_name} back to {name!r} discards everything "
                       f"written since that snapshot was taken. Type the VM name "
                       f"to confirm."),
        })
    return enqueue_and_audit(request, db, user, kind="vm.snapshot_rollback",
                             target_type="vm", target_id=v.id,
                             params={"vm_id": v.id, "name": name})


@router.delete("/{vm_id}/snapshots/{name}", status_code=202,
               dependencies=[Depends(_snapshot),
                             Depends(require_entitlement("vms.snapshots"))])
def delete_vm_snapshot(request: Request, vm_id: int, name: str, db=Depends(get_db),
                       user: User = Depends(_snapshot)):
    """No typed confirmation: deleting a snapshot leaves the guest and its disk
    exactly as they are. Only the rollback above destroys live state.
    """
    v, _host = _vm_and_host(db, vm_id)
    _valid_snap_name(name)
    return enqueue_and_audit(request, db, user, kind="vm.snapshot_delete",
                             target_type="vm", target_id=v.id,
                             params={"vm_id": v.id, "name": name})


class VmCloneIn(BaseModel):
    name: str | None = None
    newid: int | None = None
    full: bool = True
    target: str | None = None
    storage: str | None = None


@router.post("/{vm_id}/clone", status_code=202,
             dependencies=[Depends(_clone),
                           Depends(require_entitlement("vms.clone"))])
def clone_vm_route(request: Request, vm_id: int,
                   body: VmCloneIn = Body(default=VmCloneIn()), db=Depends(get_db),
                   user: User = Depends(_clone)):
    """`full` is passed through to PVE unvalidated.

    ponytail: PVE permits a linked clone (`full=false`) only from a template,
    and Proxploy cannot tell templates apart, the `vms` table has no `template`
    column and this phase adds no migration. Pre-validating would mean guessing.
    Upgrade path if PVE's rejection proves confusing in practice: have the
    poller mirror `/cluster/resources`'s `template` flag onto `Vm`, then refuse
    a linked clone of a non-template here with a message naming the reason.
    """
    v, host = _vm_and_host(db, vm_id)
    if body.name is not None and not VM_NAME_RE.match(body.name):
        raise HTTPException(422, "name must be a hostname-shaped label")
    newid = body.newid
    if newid is None:
        client = client_for_host(request.app, db, host, capability="lifecycle")
        try:
            newid = int(client.cluster_nextid())
        except ProxmoxError as e:
            raise HTTPException(502, str(e)) from e
    out = enqueue_and_audit(request, db, user, kind="vm.clone", target_type="vm",
                            target_id=v.id,
                            params={"vm_id": v.id, "newid": int(newid),
                                    "name": body.name, "full": body.full,
                                    "target": body.target,
                                    "storage": body.storage})
    return {**out, "vmid": int(newid)}


class VmDeleteIn(BaseModel):
    confirm: str | None = None


@router.delete("/{vm_id}", status_code=202,
               dependencies=[Depends(_remove),
                             Depends(require_entitlement("vms.create"))])
def delete_vm_route(request: Request, vm_id: int,
                    body: VmDeleteIn = Body(default=VmDeleteIn()),
                    db=Depends(get_db), user: User = Depends(_remove)):
    """The most destructive route in this phase: the guest and its disks are
    gone, and nothing here backs them up first. Doc 05 puts it at owner, one
    rung above every other VM route; on top of that it takes the same
    typed-confirmation path as a self-targeted stop, and refuses a running
    guest outright rather than forcing it down first.
    """
    v, _host = _vm_and_host(db, vm_id)
    name = v.name or f"VM {v.vmid}"
    ip = request.client.host if request.client else None

    def _deny(payload: dict):
        write_audit(db, actor_type="user", actor_id=user.id, action="vm.delete",
                    target_type="vm", target_id=v.id, result="denied", ip=ip)
        raise HTTPException(409, payload)

    # One guard point for "is this Proxploy itself". is_self() answers False for
    # every VM today (selfguard.py:21: Proxploy ships as an LXC CT), so this is
    # currently always a pass. It is called anyway rather than reasoned around:
    # the day a VM-hosted install exists, the guard is already wired, and the
    # alternative is a comment asserting an invariant no code enforces.
    if is_self(db, "vm", v.id):
        _deny({"error": "self_target", "confirm_phrase": name,
               "detail": f"{name} is the guest Proxploy itself runs in, "
                         f"destroying it would destroy this process."})
    if (v.status or "") == "running":
        _deny({"error": "guest_running",
               "detail": f"stop {name} before destroying it"})
    if (body.confirm or "") != name:
        _deny({"error": "confirm_required", "confirm_phrase": name,
               "detail": (f"Destroying {name} deletes the VM and every disk "
                          f"attached to it. There is no undo and no automatic "
                          f"backup. Type the VM name to confirm.")})
    return enqueue_and_audit(request, db, user, kind="vm.delete", target_type="vm",
                             target_id=v.id, params={"vm_id": v.id, "vmid": v.vmid})


@router.post("/{vm_id}/{action}", status_code=202,
             dependencies=[Depends(_lifecycle),
                          Depends(require_entitlement("vms.lifecycle"))])
def vm_lifecycle(request: Request, vm_id: int, action: str,
                 body: LifecycleIn = Body(default=LifecycleIn()),
                 db=Depends(get_db),
                 user: User = Depends(_lifecycle)):
    if action not in VM_ACTIONS:
        raise HTTPException(422, f"action must be one of {', '.join(VM_ACTIONS)}")
    v = db.get(Vm, vm_id)
    if v is None:
        raise HTTPException(404, "vm not found")
    job = enqueue_lifecycle(request, db, user, target_type="vm", target=v,
                            action=action, name=v.name or f"VM {v.vmid}",
                            confirm=body.confirm)
    return {"job": job_out(job)}
