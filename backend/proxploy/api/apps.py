"""Apps read endpoints (doc 05, Phase 2 rows). Identity is ours; state is cache."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from proxploy.api.deps import get_db, require_role
from proxploy.models import App, Host, User

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
