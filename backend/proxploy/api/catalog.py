"""Catalog browse + refresh routes (doc 05 Phase 4). Read routes are viewer-
level; refresh is admin-gated since it fans out into ~24 GitHub fetches."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from proxploy.api.deps import authorize, get_db, require_entitlement
from proxploy.api.jobs import job_out
from proxploy.models import App, CatalogEntry, HostCredential, User
from proxploy.services.audit import write_audit

router = APIRouter(prefix="/catalog", tags=["catalog"])

# Reused as BOTH the route-level dependency and the parameter-level one below
# so FastAPI's dependency cache (keyed on the callable) collapses them into a
# single call, and so authorize() in `dependencies=[...]` runs BEFORE
# require_entitlement — a bare `Depends(require_entitlement(...))` first would
# leak 403 to an anonymous caller who should see 401 (same fix as
# jobs.py/apps.py/vms.py/notifications.py; see their comments).
_read = authorize("catalog", "read")
_refresh = authorize("catalog", "refresh")
# Install is a store-wide ("app", "install") permission, not scoped by
# catalog entry — its team lives in the request BODY (host_id), not a path
# param, so there's no scope_of resolver to hand it (deps.py's scope_*
# helpers all resolve off request.path_params). ponytail: global-domain
# install for now; body-derived team scoping is the upgrade path if a
# non-owner-of-that-host operator installing onto it ever needs blocking.
_install = authorize("app", "install")


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


@router.get("", dependencies=[Depends(_read),
                              Depends(require_entitlement("store.catalog"))])
def list_catalog(category: str | None = None, q: str | None = None,
                 db=Depends(get_db), user: User = Depends(_read)):
    query = db.query(CatalogEntry)
    if category:
        query = query.filter(CatalogEntry.category == category)
    if q:
        query = query.filter(CatalogEntry.name.ilike(f"%{q}%"))
    return [_serialize(r) for r in query.order_by(CatalogEntry.name).all()]


@router.get("/{slug}", dependencies=[Depends(_read),
                                     Depends(require_entitlement("store.catalog"))])
def get_catalog_entry(slug: str, db=Depends(get_db),
                      user: User = Depends(_read)):
    row = db.query(CatalogEntry).filter_by(slug=slug).one_or_none()
    if row is None:
        raise HTTPException(404, "not found")
    return _serialize(row) | {"raw": row.raw}


@router.post("/refresh", status_code=202,
             dependencies=[Depends(_refresh),
                          Depends(require_entitlement("store.refresh"))])
def refresh_catalog(request: Request, db=Depends(get_db),
                    user: User = Depends(_refresh)):
    job = request.app.state.jobs.enqueue(db, kind="catalog.refresh",
                                         requested_by=user.id)
    write_audit(db, actor_type="user", actor_id=user.id, action="catalog.refresh",
                job_id=job.id, ip=request.client.host if request.client else None)
    return {"job": job_out(job)}


class InstallIn(BaseModel):
    host_id: int
    name: str
    ctid: int
    overrides: dict = {}
    consent: bool = False

    @field_validator("overrides")
    @classmethod
    def _keys_are_safe_shell_var_names(cls, v: dict) -> dict:
        """appstore.py turns each key into an inlined `var_{key}=...` shell
        prefix (services/appstore.py, executor/ssh.py). Reject a bad key here
        with a clean 422 instead of letting it travel all the way to a job
        that fails deep inside SSHExecutor.run's own defense-in-depth check."""
        for k in v:
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k):
                raise ValueError(f"invalid override key: {k!r}")
        return v


# This route triggers the single most security-relevant action in the whole
# phase: SSH as root into a node and run a community-scripts.org script. Two
# independent gates, either can 400 first (order doesn't matter, both are
# exercised in tests/test_catalog_install_api.py): explicit `consent: true`
# (mirrors hosts.py's CONSENT_NOTE shape) and an already-enrolled `ssh_key`
# HostCredential — no key, no route, regardless of consent.
@router.post("/{slug}/install", status_code=202,
             dependencies=[Depends(_install),
                          Depends(require_entitlement("store.install"))])
def install_catalog_entry(slug: str, body: InstallIn, request: Request,
                          db=Depends(get_db), user: User = Depends(_install)):
    if not body.consent:
        raise HTTPException(400, "root-consent required: this installs and runs a "
                                 "community-scripts.org script as root on the node")
    cred = (db.query(HostCredential)
            .filter_by(host_id=body.host_id, kind="ssh_key").one_or_none())
    if cred is None:
        raise HTTPException(400, "host has no enrolled ssh_key credential")
    entry = db.query(CatalogEntry).filter_by(slug=slug).one_or_none()
    if entry is None:
        raise HTTPException(404, "not found")
    if not entry.installable:
        raise HTTPException(400, f"not installable: {entry.unsupported_reason}")
    # Pre-flight the (host_id, ctid) uniqueness the DB enforces anyway. Without
    # it a repeat install runs the whole script to completion on the real node
    # and only then hits IntegrityError inside the job handler — leaving an
    # untracked container behind. Cheap check, real node mutation avoided.
    if (db.query(App).filter_by(host_id=body.host_id, ctid=body.ctid)
            .one_or_none()) is not None:
        raise HTTPException(409, f"CT {body.ctid} on host {body.host_id} is already tracked")
    job = request.app.state.jobs.enqueue(
        db, kind="app.install", requested_by=user.id,
        params={"catalog_slug": slug, "host_id": body.host_id, "name": body.name,
               "ctid": body.ctid, "overrides": body.overrides})
    write_audit(db, actor_type="user", actor_id=user.id, action="app.install",
                target_type="host", target_id=body.host_id, job_id=job.id,
                params={"catalog_slug": slug, "name": body.name, "ctid": body.ctid},
                ip=request.client.host if request.client else None)
    return {"job": job_out(job)}
