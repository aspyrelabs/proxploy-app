"""Catalog browse + refresh routes (doc 05 Phase 4). Read routes are viewer-
level; refresh is admin-gated since it fans out into ~24 GitHub fetches."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from proxploy.api.deps import get_db, require_entitlement, require_role
from proxploy.api.jobs import job_out
from proxploy.models import CatalogEntry, User
from proxploy.services.audit import write_audit

router = APIRouter(prefix="/catalog", tags=["catalog"])

# Reused as BOTH the route-level dependency and the parameter-level one below
# so FastAPI's dependency cache (keyed on the callable) collapses them into a
# single call, and so `require_entitlement` in `dependencies=[...]` runs AFTER
# auth/role rather than at position 0 — a bare `Depends(require_entitlement(...))`
# there would leak 403 to an anonymous caller who should see 401 (same fix as
# jobs.py/apps.py/vms.py/notifications.py; see their comments).
_require_viewer = require_role("viewer")
_require_admin = require_role("admin")


def _serialize(r: CatalogEntry) -> dict:
    return {
        "slug": r.slug, "name": r.name, "category": r.category,
        "description": r.description, "icon_url": r.icon_url,
        "popularity": r.popularity, "website": r.website,
        "default_cpu": r.default_cpu, "default_ram_mb": r.default_ram_mb,
        "default_disk_gb": r.default_disk_gb, "default_os": r.default_os,
        "default_os_version": r.default_os_version,
        "installable": r.installable, "unsupported_reason": r.unsupported_reason,
        "synced_at": r.synced_at.isoformat() if r.synced_at else None,
    }


@router.get("", dependencies=[Depends(_require_viewer),
                              Depends(require_entitlement("store.catalog"))])
def list_catalog(category: str | None = None, q: str | None = None,
                 db=Depends(get_db), user: User = Depends(_require_viewer)):
    query = db.query(CatalogEntry)
    if category:
        query = query.filter(CatalogEntry.category == category)
    if q:
        query = query.filter(CatalogEntry.name.ilike(f"%{q}%"))
    return [_serialize(r) for r in query.order_by(CatalogEntry.name).all()]


@router.get("/{slug}", dependencies=[Depends(_require_viewer),
                                     Depends(require_entitlement("store.catalog"))])
def get_catalog_entry(slug: str, db=Depends(get_db),
                      user: User = Depends(_require_viewer)):
    row = db.query(CatalogEntry).filter_by(slug=slug).one_or_none()
    if row is None:
        raise HTTPException(404, "not found")
    return _serialize(row) | {"raw": row.raw}


@router.post("/refresh", status_code=202,
             dependencies=[Depends(_require_admin),
                          Depends(require_entitlement("store.refresh"))])
def refresh_catalog(request: Request, db=Depends(get_db),
                    user: User = Depends(_require_admin)):
    job = request.app.state.jobs.enqueue(db, kind="catalog.refresh",
                                         requested_by=user.id)
    write_audit(db, actor_type="user", actor_id=user.id, action="catalog.refresh",
                job_id=job.id, ip=request.client.host if request.client else None)
    return {"job": job_out(job)}
