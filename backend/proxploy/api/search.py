"""Global search, the data behind doc 06's command palette (PXP-17).

`ui.global_search` was a registered entitlement flag with nothing behind it,
and doc 06's cmdk palette was dropped rather than reimplemented when the
frontend stack was substituted (see doc 06's amendment). This is the backend
half: one query, results grouped by kind, so the palette is a UI concern only.

Deliberately NOT a full-text index. Everything searchable here lives in tables
Proxploy already owns: the catalog is the big one at ~669 rows, plus however
many apps and VMs the operator runs. A LIKE per table answers in milliseconds
at that size, and an index would be a second source of truth to keep in sync
with no measurable benefit.

Every result is scoped by the same authz the resource's own routes use: search
must never be the one place a viewer discovers a host they cannot read.

TWO GATES, NOT ONE. This endpoint is no longer entitlement-gated as a whole.
The App Store's own search box is gone, and it was never behind
`ui.global_search`, so a plan carrying `store.catalog` without
`ui.global_search` would have lost the ability to search the store at all: a
capability removal, dressed up as a UI cleanup. Instead each group carries its
own entitlement (see `search`), so the palette degrades to store-only rather
than to nothing, and the app/VM/host groups stay gated exactly as they were.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_

from proxploy.api.deps import authorize, get_db
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

# The store is the exception, and it earns it. The other three groups are
# navigation: you know the app exists and you are jumping to it, so 8 covers
# every realistic ambiguity. The store is a 557-entry catalog people BROWSE,
# and it is losing its own search box, so this is now the only way to search
# it. At 8, a two or three letter query silently truncates to near-nothing and
# the palette looks like the catalog does not contain what it plainly does.
# 25 is about a screenful in one group and still two orders of magnitude below
# returning the catalog, which is the thing that must never happen here.
STORE_PER_KIND = 25


def _visible(request: Request, db, user: User, resource: str, action: str) -> bool:
    return enforce(request.app.state.authz, db, user, resource, action)


@router.get("", dependencies=[Depends(_read)])
def search(request: Request, q: str = "", db=Depends(get_db),
           user: User = Depends(_read)):
    """Fuzzy-ish search across apps, VMs, hosts and store entries.

    An empty or single-character query returns nothing rather than everything:
    a palette that dumps the whole inventory on first keystroke is noise, and
    the operator has a nav for browsing.

    ENTITLEMENTS ARE PER GROUP, and the route-level dependency is deliberately
    gone. `ui.global_search` still gates apps, VMs and hosts, exactly as it
    gated the whole endpoint before; `store.catalog` gates the store group, the
    same flag the Store's own routes use (api/catalog.py). A caller with
    neither is 403ed on `ui.global_search`, which is the response this route
    already gave that caller, so nothing that could see this endpoint before
    loses anything.

    Moving the check inside is what makes store-only possible at all, and it
    is the one restructuring with a real hazard: the four groups must stay
    independently gated, so that dropping the route-level dependency cannot
    hand an app, VM or host row to a caller who could not have seen this
    endpoint at all a moment ago. Both halves of every group's condition, the
    entitlement AND `_visible`, are load bearing.
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
            out.append({"kind": "app", "id": a.id, "label": a.name,
                        "sublabel": f"CT {a.ctid}", "href": f"/apps/{a.id}",
                        "status": a.status_cached})

    if palette and _visible(request, db, user, "vm", "read"):
        for v in (db.query(Vm).filter(Vm.name.ilike(like))
                  .order_by(Vm.name).limit(PER_KIND)):
            out.append({"kind": "vm", "id": v.id, "label": v.name,
                        "sublabel": f"VM {v.vmid}", "href": f"/vms/{v.id}",
                        "status": v.status})

    if palette and _visible(request, db, user, "host", "read"):
        for h in (db.query(Host).filter(Host.name.ilike(like))
                  .order_by(Host.name).limit(PER_KIND)):
            out.append({"kind": "host", "id": h.id, "label": h.name,
                        "sublabel": h.node_name or h.address,
                        "href": f"/settings/hosts/{h.id}", "status": h.status})

    if store and _visible(request, db, user, "catalog", "read"):
        # Name OR slug OR description, mirroring the rule the Store's own grid
        # filters by (frontend/src/routes/store.tsx), because this now has to
        # stand in for the box that used it.
        #
        # Description is the half that changed the answer: 617 rows carry a
        # real upstream description as of the metadata sync, 548 of them ct
        # (services/catalog_metadata.py), and a palette matching names only
        # would have made every one of them unsearchable the day they landed.
        # Slug stays in the haystack for the opposite case: the 9 "unlisted"
        # rows have no description at all, and their slug is often the name
        # anyone would actually type.
        #
        # `store_visible()` FIRST, and it is not optional. Every result here
        # emits `href: /store/<slug>`, so this query must return exactly the
        # rows the Store grid can render and nothing else. It did not, and a
        # user found it: searching "alpine" returned 25 results of which 20
        # were unopenable, every one of them a hidden alpine-<parent> variant
        # or a non-ct row, and each opened Not Found. The predicate is shared
        # with list_catalog rather than repeated here precisely because
        # repeating it is what caused that.
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
