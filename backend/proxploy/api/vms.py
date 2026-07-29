"""VM read + lifecycle endpoints (doc 05, Phase 2/3 rows). Pure cache mirror +
snapshot cpu."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from proxploy.api.apps import LifecycleIn, enqueue_lifecycle
from proxploy.api.deps import get_db, require_entitlement, require_role
from proxploy.api.jobs import job_out
from proxploy.models import Host, User, Vm
from proxploy.services.lifecycle import VM_ACTIONS

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
_require_operator = require_role("operator")


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
