"""Apps read + lifecycle endpoints (doc 05, Phase 2/3 rows). Identity is ours;
state is cache."""
from __future__ import annotations

import difflib
import hashlib

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from proxploy.api.deps import get_db, require_entitlement, require_role
from proxploy.api.jobs import job_out
from proxploy.models import App, AppScript, CatalogEntry, Host, User
from proxploy.services.audit import write_audit
from proxploy.services.lifecycle import APP_ACTIONS, job_kind
from proxploy.services.selfguard import DESTRUCTIVE, is_self

router = APIRouter(prefix="/apps", tags=["apps"])

# Reused as BOTH the route-level dependency and the parameter-level one below
# (same collapse-and-ordering rationale as catalog.py's _require_admin/
# _require_viewer and this file's own _require_operator further down): auth/
# role must run before require_entitlement, or an anonymous caller gets a
# leaky 403 instead of 401 (test_route_auth_invariant.py).
_require_admin = require_role("admin")

# Defined here (rather than just above the lifecycle wildcard further down)
# so the script routes below — registered before that wildcard per the
# WARNING near it — can also reuse it as a single collapsed dependency.
_require_operator = require_role("operator")


def _app_out(a: App, host: Host, snapshots) -> dict:
    snap = snapshots.get(a.host_id)
    g = snap.guests.get(("lxc", a.ctid)) if snap else None
    return {
        "id": a.id, "name": a.name, "slug": a.slug,
        "host_id": a.host_id, "host_name": host.name, "node": host.node_name,
        "ctid": a.ctid, "category": a.category, "catalog_slug": a.catalog_slug,
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


class AdoptItem(BaseModel):
    host_id: int
    ctid: int
    name: str
    catalog_slug: str | None = None


class AdoptIn(BaseModel):
    items: list[AdoptItem]


@router.post("/adopt", dependencies=[Depends(_require_admin),
                                     Depends(require_entitlement("apps.adopt"))])
def adopt_apps(body: AdoptIn, request: Request, db=Depends(get_db),
               user: User = Depends(_require_admin)):
    """Bulk-adopt pre-existing/discovered CTs as tracked apps (doc 05, Phase 4).

    One commit for the whole batch: a mid-batch ux_apps_host_ctid conflict
    rolls back everything flushed so far in this request (nothing partially
    lands), and a single audit row covers the whole batch rather than one per
    item.
    """
    adopted = []
    for item in body.items:
        slug = f"{item.catalog_slug or 'adopted'}-{item.host_id}-{item.ctid}"
        row = App(host_id=item.host_id, ctid=item.ctid, name=item.name, slug=slug,
                  catalog_slug=item.catalog_slug, web_protocol="http", web_path="/",
                  adopted=True)
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, f"CT {item.ctid} on host {item.host_id} is already adopted")
        adopted.append(row.id)
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id, action="apps.adopt",
                params={"count": len(adopted), "app_ids": adopted},
                ip=request.client.host if request.client else None)
    return {"adopted": adopted}


@router.get("/{app_id}")
def app_detail(request: Request, app_id: int, db=Depends(get_db),
               user: User = Depends(require_role("viewer"))):
    a = db.get(App, app_id)
    if a is None:
        raise HTTPException(404, "app not found")
    host = db.get(Host, a.host_id)
    return _app_out(a, host, request.app.state.poller.snapshots)


def _diff_vs_upstream(db, app_row: App, pinned_content: str) -> str | None:
    """Doc 05/10: diff the pinned app_scripts row against the *current*
    catalog_entries.raw.install_script for this app's catalog_slug — not just
    against this app's own prior version. A catalog refresh can move upstream
    forward with the app's pinned content untouched, and that drift has to
    surface too (see test_upstream_moving_on_after_pin_also_surfaces_a_diff)."""
    if not app_row.catalog_slug:
        return None
    entry = db.query(CatalogEntry).filter_by(slug=app_row.catalog_slug).one_or_none()
    if entry is None or not entry.raw:
        return None
    upstream = entry.raw.get("install_script")
    if upstream is None or upstream == pinned_content:
        return None
    diff = difflib.unified_diff(
        upstream.splitlines(keepends=True), pinned_content.splitlines(keepends=True),
        fromfile="upstream", tofile="pinned")
    return "".join(diff)


# Literal two-segment/three-segment paths registered here — BEFORE the
# lifecycle wildcard further down — per that route's own WARNING: Starlette
# matches path templates in registration order, and `/{app_id}/{action}`
# would otherwise swallow these (it's POST-only though, so GET/PUT here don't
# actually collide on method; kept ahead of it anyway for the same reason
# doc 05's future /{id}/update and /{id}/migrate must be).
@router.get("/{app_id}/script", dependencies=[Depends(_require_operator),
                                              Depends(require_entitlement("apps.script_edit"))])
def get_app_script(app_id: int, db=Depends(get_db)):
    latest = (db.query(AppScript).filter_by(app_id=app_id)
             .order_by(AppScript.version.desc()).first())
    if latest is None:
        raise HTTPException(404, "no pinned script for this app")
    app_row = db.get(App, app_id)
    return {"version": latest.version, "content": latest.content, "source": latest.source,
           "diff_vs_upstream": _diff_vs_upstream(db, app_row, latest.content)}


class ScriptIn(BaseModel):
    content: str


@router.put("/{app_id}/script", dependencies=[Depends(_require_admin),
                                              Depends(require_entitlement("apps.script_edit"))])
def put_app_script(app_id: int, body: ScriptIn, request: Request, db=Depends(get_db),
                   user: User = Depends(_require_admin)):
    # Validate before writing, like every sibling route here: a missing
    # `content` used to KeyError into a 500, and an unknown app_id used to
    # 500 on the AppScript FK violation at commit time.
    if db.get(App, app_id) is None:
        raise HTTPException(404, "app not found")
    content = body.content
    latest = (db.query(AppScript).filter_by(app_id=app_id)
             .order_by(AppScript.version.desc()).first())
    next_version = (latest.version + 1) if latest else 1
    row = AppScript(app_id=app_id, version=next_version, content=content,
                    content_sha256=hashlib.sha256(content.encode()).hexdigest(),
                    source="edited", created_by=user.id)
    db.add(row)
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id, action="apps.script_edit",
                target_type="app", target_id=app_id, params={"version": row.version},
                ip=request.client.host if request.client else None)
    return {"version": row.version, "content": row.content, "source": row.source}


@router.get("/{app_id}/script/versions",
            dependencies=[Depends(_require_operator),
                         Depends(require_entitlement("apps.script_edit"))])
def list_app_script_versions(app_id: int, db=Depends(get_db)):
    rows = (db.query(AppScript).filter_by(app_id=app_id)
           .order_by(AppScript.version.desc()).all())
    return [{"version": r.version, "source": r.source, "created_at": r.created_at.isoformat()}
           for r in rows]


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


# WARNING: this wildcard is registered last and Starlette matches routes in
# registration order, so it will silently swallow any future two-segment
# sibling under /apps/{id}/... — e.g. doc 05's still-unbuilt /apps/{id}/update
# (Phase 4) and /apps/{id}/migrate (Phase 8). Register those routes with their
# literal action segments BEFORE this one, or they'll hit this handler instead
# and 422 with "action must be one of start, stop, restart, shutdown".
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
