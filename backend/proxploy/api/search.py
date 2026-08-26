"""Global search backend (doc 06's command palette, PXP-17): one query, results
grouped by kind, so the palette is a UI concern only.

Deliberately not a full-text index: a LIKE per table answers in milliseconds
at this catalog size, and an index would be a second source of truth. Every
result is scoped by the same authz the resource's own routes use — search must
never leak a host a viewer cannot read.

Not entitlement-gated as a whole: each group carries its own entitlement (see
`search`), so the palette degrades to store-only rather than to nothing.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_

from proxploy.api.deps import authorize, dedupe_vms, get_db
from proxploy.models import App, CatalogEntry, Host, User, Vm
from proxploy.services.catalog_metadata import store_visible
from proxploy.services.authz import enforce

router = APIRouter(prefix="/search", tags=["search"])

# Viewer-level: this returns nothing a viewer could not already list. Each
# section below is additionally filtered by that section's own permission.
_read = authorize("app", "read")

# A palette shows a handful of rows per group; fetching more would be work
# thrown away by the UI.
PER_KIND = 8

# The store is browsed (557-entry catalog) and has lost its own search box, so
# it gets more than the 8 the nav groups get: 8 truncates short queries to
# near-nothing, 25 is a screenful and still far from returning the catalog.
STORE_PER_KIND = 25


def _visible(request: Request, db, user: User, resource: str, action: str) -> bool:
    return enforce(request.app.state.authz, db, user, resource, action)


@router.get("", dependencies=[Depends(_read)])
def search(request: Request, q: str = "", db=Depends(get_db),
           user: User = Depends(_read)):
    """Search across apps, VMs, hosts and store entries. Empty/single-char
    queries return nothing.

    Entitlements are per group: `ui.global_search` gates apps/VMs/hosts,
    `store.catalog` the store group; a caller with neither gets 403 (as
    before). The four groups must stay independently gated — dropping the
    route-level dependency must not leak an app/VM/host to someone who could
    not have seen this endpoint.
    """
    entitlements = request.app.state.entitlements
    palette = entitlements.enabled("ui.global_search")
    store = entitlements.enabled("store.catalog")
    if not palette and not store:
        # Nothing to serve, so answer exactly as the route-level dependency
        # used to: an empty 200 here would claim the feature exists and is
        # merely finding nothing.
        raise HTTPException(403, {"error": "entitlement_required",
                                  "feature": "ui.global_search"})
    term = (q or "").strip()
    if len(term) < 2:
        return {"query": term, "results": []}
    like = f"%{term}%"
    out: list[dict] = []

    if palette and _visible(request, db, user, "app", "read"):
        for a in (db.query(App).filter(App.name.ilike(like))
                  .order_by(App.name).limit(PER_KIND)):
            # An app has no page of its own any more: it is a row on the Apps
            # table that expands in place, and `open` is which one
            # (frontend/src/components/AppTable.tsx).
            out.append({"kind": "app", "id": a.id, "label": a.name,
                        "sublabel": f"CT {a.ctid}", "href": f"/apps?open={a.id}",
                        "status": a.status_cached})

    if palette and _visible(request, db, user, "vm", "read"):
        # Deduped before the limit, not after: the mirror holds one row per
        # (host, vmid), so on a cluster the palette showed every VM twice and a
        # PER_KIND of 5 could be 5 copies of 3 guests (doc 12 check 18).
        matches = dedupe_vms(db.query(Vm).filter(Vm.name.ilike(like)).all(),
                             {h.id: h for h in db.query(Host).all()})
        matches.sort(key=lambda v: (v.name or "", v.id))
        for v in matches[:PER_KIND]:
            # A VM has no page of its own any more either: it is a row on the
            # VMs table that expands in place, and `open` is which one
            # (frontend/src/components/VmTable.tsx).
            out.append({"kind": "vm", "id": v.id, "label": v.name,
                        "sublabel": f"VM {v.vmid}", "href": f"/vms?open={v.id}",
                        "status": v.status})

    if palette and _visible(request, db, user, "host", "read"):
        for h in (db.query(Host).filter(Host.name.ilike(like))
                  .order_by(Host.name).limit(PER_KIND)):
            out.append({"kind": "host", "id": h.id, "label": h.name,
                        "sublabel": h.node_name or h.address,
                        # No per-host page exists; link to the settings section
                        # that lists every enrolled host.
                        "href": "/settings?section=hosts", "status": h.status})

    if store and _visible(request, db, user, "catalog", "read"):
        # Name OR slug OR description (mirrors the Store grid's filter), and
        # `store_visible()` first: every result emits `/store/<slug>`, so this
        # must return exactly the rows the Store can render (searching "alpine"
        # once returned 20 unopenable hidden variants). Predicate is shared with
        # list_catalog, not repeated — repeating it caused that bug.
        for e in (db.query(CatalogEntry)
                  .filter(store_visible())
                  .filter(or_(CatalogEntry.name.ilike(like),
                              CatalogEntry.slug.ilike(like),
                              CatalogEntry.description.ilike(like)))
                  .order_by(CatalogEntry.name).limit(STORE_PER_KIND)):
            out.append({"kind": "store", "id": e.slug, "label": e.name,
                        "sublabel": e.category, "href": f"/store/{e.slug}",
                        "status": None})

    # An exact name match should not sit below a substring match just because
    # its table was queried later.
    lowered = term.lower()
    out.sort(key=lambda r: (str(r["label"]).lower() != lowered,
                            not str(r["label"]).lower().startswith(lowered),
                            str(r["label"]).lower()))
    return {"query": term, "results": out}
