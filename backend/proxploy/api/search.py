"""Global search, the data behind doc 06's command palette (PXP-17).

`ui.global_search` was a registered entitlement flag with nothing behind it,
and doc 06's cmdk palette was dropped rather than reimplemented when the
frontend stack was substituted (see doc 06's amendment). This is the backend
half: one query, results grouped by kind, so the palette is a UI concern only.

Deliberately NOT a full-text index. Everything searchable here lives in tables
Proxploy already owns and the largest of them is a couple of dozen catalog
entries plus however many apps and VMs the operator runs. A LIKE per table
answers in milliseconds at that size, and an index would be a second source of
truth to keep in sync with no measurable benefit.

Every result is scoped by the same authz the resource's own routes use: search
must never be the one place a viewer discovers a host they cannot read.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from proxploy.api.deps import authorize, get_db, require_entitlement
from proxploy.models import App, CatalogEntry, Host, User, Vm
from proxploy.services.authz import enforce

router = APIRouter(prefix="/search", tags=["search"])

# Viewer-level: this returns nothing a viewer could not already list. Each
# section below is additionally filtered by that section's own permission.
_read = authorize("app", "read")

# A palette shows a handful of rows per group; fetching more would be work
# thrown away by the UI.
PER_KIND = 8


def _visible(request: Request, db, user: User, resource: str, action: str) -> bool:
    return enforce(request.app.state.authz, db, user, resource, action)


@router.get("", dependencies=[Depends(_read),
                              Depends(require_entitlement("ui.global_search"))])
def search(request: Request, q: str = "", db=Depends(get_db),
           user: User = Depends(_read)):
    """Fuzzy-ish search across apps, VMs, hosts and store entries.

    An empty or single-character query returns nothing rather than everything:
    a palette that dumps the whole inventory on first keystroke is noise, and
    the operator has a nav for browsing.
    """
    term = (q or "").strip()
    if len(term) < 2:
        return {"query": term, "results": []}
    like = f"%{term}%"
    out: list[dict] = []

    if _visible(request, db, user, "app", "read"):
        for a in (db.query(App).filter(App.name.ilike(like))
                  .order_by(App.name).limit(PER_KIND)):
            out.append({"kind": "app", "id": a.id, "label": a.name,
                        "sublabel": f"CT {a.ctid}", "href": f"/apps/{a.id}",
                        "status": a.status_cached})

    if _visible(request, db, user, "vm", "read"):
        for v in (db.query(Vm).filter(Vm.name.ilike(like))
                  .order_by(Vm.name).limit(PER_KIND)):
            out.append({"kind": "vm", "id": v.id, "label": v.name,
                        "sublabel": f"VM {v.vmid}", "href": f"/vms/{v.id}",
                        "status": v.status})

    if _visible(request, db, user, "host", "read"):
        for h in (db.query(Host).filter(Host.name.ilike(like))
                  .order_by(Host.name).limit(PER_KIND)):
            out.append({"kind": "host", "id": h.id, "label": h.name,
                        "sublabel": h.node_name or h.address,
                        "href": f"/settings/hosts/{h.id}", "status": h.status})

    if _visible(request, db, user, "catalog", "read"):
        for e in (db.query(CatalogEntry)
                  .filter(CatalogEntry.name.ilike(like))
                  .order_by(CatalogEntry.name).limit(PER_KIND)):
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
