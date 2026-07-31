"""VM read + lifecycle endpoints (doc 05, Phase 2/3 rows). Pure cache mirror +
snapshot cpu."""
from __future__ import annotations

import re

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel

from proxploy.api.apps import LifecycleIn, enqueue_lifecycle
from proxploy.api.deps import get_db, require_entitlement, require_role
from proxploy.api.jobs import enqueue_and_audit, job_out
from proxploy.api.network import NicIn, guest_nics, set_guest_nic
from proxploy.models import Host, User, Vm
from proxploy.services.audit import write_audit
from proxploy.services.hostclient import client_for_host
from proxploy.services.lifecycle import VM_ACTIONS
from proxploy.services.proxmox import ProxmoxError

router = APIRouter(prefix="/vms", tags=["vms"])


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
        "synced_at": v.synced_at.isoformat() + "Z" if v.synced_at else None,
    }


@router.get("")
def list_vms(request: Request, host: int | None = None, db=Depends(get_db),
             user: User = Depends(require_role("viewer"))):
    hosts = {h.id: h for h in db.query(Host).all()}
    query = db.query(Vm)
    if host is not None:
        query = query.filter(Vm.host_id == host)
    return [_vm_out(v, hosts[v.host_id], request.app.state.poller.snapshots)
            for v in query.order_by(Vm.name).all() if v.host_id in hosts]


@router.get("/{vm_id}")
def vm_detail(request: Request, vm_id: int, db=Depends(get_db),
              user: User = Depends(require_role("viewer"))):
    v = db.get(Vm, vm_id)
    if v is None:
        raise HTTPException(404, "vm not found")
    return _vm_out(v, db.get(Host, v.host_id), request.app.state.poller.snapshots)


# Same ordering fix as apps.py::app_lifecycle — see the comment there. Reusing
# this one callable as both the route-level dependency and the parameter
# dependency makes auth/role run first and collapses the two into one call.
# Hoisted to the top of the routes (Phase 6 Task 6) so later tasks (10, 11)
# adding more routes above the /{vm_id}/{action} wildcard can reuse these
# without re-declaring them.
_require_viewer = require_role("viewer")
_require_operator = require_role("operator")
_require_admin = require_role("admin")


def _vm_and_host(db, vm_id: int):
    v = db.get(Vm, vm_id)
    if v is None:
        raise HTTPException(404, "vm not found")
    host = db.get(Host, v.host_id)
    if host is None:
        raise HTTPException(404, "host not found")
    return v, host


# Registered ABOVE the /{vm_id}/{action} wildcard below — Starlette matches in
# registration order, and although that wildcard is POST-only today, doc 05's
# future two-segment siblings are not. Same WARNING as apps.py:266-271.
# test_network_api.py asserts this ordering by route index.
@router.get("/{vm_id}/network",
            dependencies=[Depends(_require_viewer),
                          Depends(require_entitlement("network.guest_config"))])
def vm_network(request: Request, vm_id: int, db=Depends(get_db),
               user: User = Depends(_require_viewer)):
    v, host = _vm_and_host(db, vm_id)
    return guest_nics(request, db, host, "qemu", v.vmid)


@router.put("/{vm_id}/network/{iface}",
            dependencies=[Depends(_require_operator),
                          Depends(require_entitlement("network.guest_config"))])
def vm_network_update(request: Request, vm_id: int, iface: str, body: NicIn,
                      db=Depends(get_db), user: User = Depends(_require_operator)):
    v, host = _vm_and_host(db, vm_id)
    return set_guest_nic(request, db, user, target_type="vm", target_id=v.id,
                         host=host, kind="qemu", vmid=v.vmid, iface=iface, body=body)


# Registered ABOVE the /{vm_id}/{action} wildcard — see the WARNING on that
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
            dependencies=[Depends(_require_viewer),
                          Depends(require_entitlement("vms.snapshots"))])
def list_vm_snapshots(request: Request, vm_id: int, db=Depends(get_db),
                      user: User = Depends(_require_viewer)):
    """Live read on every request (doc 05: "List snapshots (live from
    Proxmox)") — there is no snapshot table and this phase adds none.

    PVE always includes a synthetic `current` entry describing the running
    state. It is not a snapshot, has no snaptime, and cannot be rolled back to
    or deleted, so it is dropped here rather than in the UI — otherwise every
    consumer of this endpoint has to know the same trivia.
    """
    v, host = _vm_and_host(db, vm_id)
    client = client_for_host(request.app, db, host)
    try:
        rows = client.snapshots("qemu", host.node_name or "", v.vmid)
    except ProxmoxError as e:
        raise HTTPException(502, str(e)) from e
    return [_snapshot_out(s) for s in rows if s.get("name") != "current"]


class SnapshotIn(BaseModel):
    name: str
    description: str | None = None
    vmstate: bool = False


@router.post("/{vm_id}/snapshots", status_code=202,
             dependencies=[Depends(_require_operator),
                           Depends(require_entitlement("vms.snapshots"))])
def create_vm_snapshot(request: Request, vm_id: int, body: SnapshotIn,
                       db=Depends(get_db),
                       user: User = Depends(_require_operator)):
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
             dependencies=[Depends(_require_admin),
                           Depends(require_entitlement("vms.snapshots"))])
def rollback_vm_snapshot(request: Request, vm_id: int, name: str,
                         body: RollbackIn = Body(default=RollbackIn()),
                         db=Depends(get_db),
                         user: User = Depends(_require_admin)):
    """Rollback throws away every write since the snapshot was taken — there is
    no undo and no second copy. It therefore reuses the exact 409 body
    `enqueue_lifecycle` uses for a self-targeted stop, so the frontend's
    existing ConfirmSelfDialog renders it with no new component.
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
               dependencies=[Depends(_require_operator),
                             Depends(require_entitlement("vms.snapshots"))])
def delete_vm_snapshot(request: Request, vm_id: int, name: str, db=Depends(get_db),
                       user: User = Depends(_require_operator)):
    """No typed confirmation: deleting a snapshot leaves the guest and its disk
    exactly as they are. Only the rollback above destroys live state.
    """
    v, _host = _vm_and_host(db, vm_id)
    _valid_snap_name(name)
    return enqueue_and_audit(request, db, user, kind="vm.snapshot_delete",
                             target_type="vm", target_id=v.id,
                             params={"vm_id": v.id, "name": name})


@router.post("/{vm_id}/{action}", status_code=202,
             dependencies=[Depends(_require_operator),
                          Depends(require_entitlement("vms.lifecycle"))])
def vm_lifecycle(request: Request, vm_id: int, action: str,
                 body: LifecycleIn = Body(default=LifecycleIn()),
                 db=Depends(get_db),
                 user: User = Depends(_require_operator)):
    if action not in VM_ACTIONS:
        raise HTTPException(422, f"action must be one of {', '.join(VM_ACTIONS)}")
    v = db.get(Vm, vm_id)
    if v is None:
        raise HTTPException(404, "vm not found")
    job = enqueue_lifecycle(request, db, user, target_type="vm", target=v,
                            action=action, name=v.name or f"VM {v.vmid}",
                            confirm=body.confirm)
    return {"job": job_out(job)}
