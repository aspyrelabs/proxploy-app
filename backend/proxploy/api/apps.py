"""Apps read + lifecycle endpoints (doc 05, Phase 2/3 rows). Identity is ours;
state is cache."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel

from proxploy.api.deps import get_db, require_entitlement, require_role
from proxploy.api.jobs import job_out
from proxploy.models import App, Host, User
from proxploy.services.audit import write_audit
from proxploy.services.lifecycle import APP_ACTIONS, job_kind
from proxploy.services.selfguard import DESTRUCTIVE, is_self

router = APIRouter(prefix="/apps", tags=["apps"])


def _app_out(a: App, host: Host, snapshots) -> dict:
    snap = snapshots.get(a.host_id)
    g = snap.guests.get(("lxc", a.ctid)) if snap else None
    return {
        "id": a.id, "name": a.name, "slug": a.slug,
        "host_id": a.host_id, "host_name": host.name, "node": host.node_name,
        "ctid": a.ctid, "category": a.category,
        "icon_initials": a.icon_initials, "icon_colors": a.icon_colors,
        "web_port": a.web_port, "web_protocol": a.web_protocol,
        "web_path": a.web_path,
        "status": a.status_cached or "unknown", "ip": a.ip_cached,
        "cpu_pct": a.cpu_pct_cached, "mem_bytes": a.mem_bytes_cached,
        "mem_total_bytes": g["mem_total_bytes"] if g else None,
        "uptime_s": a.uptime_s_cached,
        "update_available": a.update_available, "adopted": a.adopted,
    }


@router.get("")
def list_apps(request: Request, host: int | None = None, q: str | None = None,
              status: str | None = None, db=Depends(get_db),
              user: User = Depends(require_role("viewer"))):
    hosts = {h.id: h for h in db.query(Host).all()}
    query = db.query(App)
    if host is not None:
        query = query.filter(App.host_id == host)
    rows = []
    for a in query.order_by(App.name).all():
        if q and q.lower() not in f"{a.name} {a.slug}".lower():
            continue
        if status and (a.status_cached or "unknown") != status:
            continue
        h = hosts.get(a.host_id)
        if h is None:
            continue
        rows.append(_app_out(a, h, request.app.state.poller.snapshots))
    return rows


@router.get("/discovered")
def discovered(request: Request, db=Depends(get_db),
               user: User = Depends(require_role("viewer"))):
    """Pre-existing CTs not yet adopted (doc 05). Read-only until Phase 4."""
    hosts = {h.id: h for h in db.query(Host).all()}
    out = []
    for host_id, snap in sorted(request.app.state.poller.snapshots.items()):
        h = hosts.get(host_id)
        if h is None:
            continue
        for d in snap.discovered:
            out.append({"host_id": host_id, "host_name": h.name, **d})
    return out


@router.get("/{app_id}")
def app_detail(request: Request, app_id: int, db=Depends(get_db),
               user: User = Depends(require_role("viewer"))):
    a = db.get(App, app_id)
    if a is None:
        raise HTTPException(404, "app not found")
    host = db.get(Host, a.host_id)
    return _app_out(a, host, request.app.state.poller.snapshots)


class LifecycleIn(BaseModel):
    confirm: str | None = None


def enqueue_lifecycle(request: Request, db, user: User, *, target_type: str,
                      target, action: str, name: str, confirm: str | None):
    """Shared by the apps and VMs routes — one guardrail, one audit shape.

    Doc 02 §9 / doc 08 §1: a destructive action against the CT Proxploy itself
    runs in is refused unless the caller types the name back.
    """
    ip = request.client.host if request.client else None
    if action in DESTRUCTIVE and is_self(db, target_type, target.id):
        if (confirm or "") != name:
            write_audit(db, actor_type="user", actor_id=user.id,
                        action=job_kind(target_type, action),
                        target_type=target_type, target_id=target.id,
                        result="denied", ip=ip)
            raise HTTPException(409, {
                "error": "self_target", "confirm_phrase": name,
                "detail": (f"{name} is the container Proxploy itself runs in. "
                           f"A {action} here can strand its own recovery path. "
                           f"Type the name to confirm."),
            })
    job = request.app.state.jobs.enqueue(
        db, kind=job_kind(target_type, action), target_type=target_type,
        target_id=target.id, params={"target_id": target.id, "action": action},
        requested_by=user.id)
    write_audit(db, actor_type="user", actor_id=user.id,
                action=job_kind(target_type, action), target_type=target_type,
                target_id=target.id, params={"action": action},
                job_id=job.id, ip=ip)
    return job


# Reused as BOTH the route-level dependency and the parameter-level one below
# so FastAPI's dependency cache (keyed on the callable) collapses them into a
# single call that runs first. A bare `dependencies=[Depends(require_entitlement(...))]`
# would sit at position 0 of the dependant and run BEFORE this auth/role check,
# leaking 403 to an anonymous caller who should see 401 (Task 3 hit this in
# jobs.py; verified experimentally — see task-5-report.md).
_require_operator = require_role("operator")


@router.post("/{app_id}/{action}", status_code=202,
             dependencies=[Depends(_require_operator),
                          Depends(require_entitlement("apps.lifecycle"))])
def app_lifecycle(request: Request, app_id: int, action: str,
                  body: LifecycleIn = Body(default=LifecycleIn()),
                  db=Depends(get_db),
                  user: User = Depends(_require_operator)):
    if action not in APP_ACTIONS:
        raise HTTPException(422, f"action must be one of {', '.join(APP_ACTIONS)}")
    a = db.get(App, app_id)
    if a is None:
        raise HTTPException(404, "app not found")
    job = enqueue_lifecycle(request, db, user, target_type="app", target=a,
                            action=action, name=a.name, confirm=body.confirm)
    return {"job": job_out(job)}
