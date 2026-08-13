"""Catalog browse + refresh routes (doc 05 Phase 4; catalog expansion plan,
.superpowers/sdd/app-store-catalog-plan.md). Read routes are viewer-level;
refresh is admin-gated. A refresh costs exactly 2 api.github.com calls flat,
regardless of catalog size (services/catalog.py::run_discovery); per-entry
script pairs are fetched lazily by ensure_classified, from
raw.githubusercontent.com (a different host, no GitHub rate limit), the
moment a card is opened here or an install is attempted."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import nulls_last

from proxploy.api.deps import authorize, get_db, require_entitlement
from proxploy.api.jobs import job_out
from proxploy.models import App, CatalogEntry, Host, HostCredential, User, utcnow
from proxploy.services.audit import write_audit
from proxploy.services.catalog import ensure_classified
from proxploy.services.catalog_icons import (CONTENT_TYPES,
                                             attribution_headers, icon_dir)
from proxploy.services.catalog_metadata import store_visible

router = APIRouter(prefix="/catalog", tags=["catalog"])

# Reused as BOTH the route-level dependency and the parameter-level one below
# so FastAPI's dependency cache (keyed on the callable) collapses them into a
# single call, and so authorize() in `dependencies=[...]` runs BEFORE
# require_entitlement: a bare `Depends(require_entitlement(...))` first would
# leak 403 to an anonymous caller who should see 401 (same fix as
# jobs.py/apps.py/vms.py/notifications.py; see their comments).
_read = authorize("catalog", "read")
_refresh = authorize("catalog", "refresh")
# Install is a store-wide ("app", "install") permission, not scoped by
# catalog entry: its team lives in the request BODY (host_id), not a path
# param, so there's no scope_of resolver to hand it (deps.py's scope_*
# helpers all resolve off request.path_params). ponytail: global-domain
# install for now; body-derived team scoping is the upgrade path if a
# non-owner-of-that-host operator installing onto it ever needs blocking.
_install = authorize("app", "install")


# The complete set of orderings the Store may ask for, as an ALLOWLIST of
# prebuilt criteria. A sort key is a query parameter, so it is caller
# controlled, and the only safe shape for caller-controlled ordering is one
# that never reaches SQL as a string: an unknown key selects the default here
# rather than being interpolated, quoted or trusted.
#
# NULLS ALWAYS LAST on every descending sort, and this is the trap the whole
# table exists to avoid. SQLite orders NULL FIRST ascending, so a bare
# `popularity DESC` puts every row we have no number for at the BOTTOM, which
# is right, while a bare `popularity ASC` or any NULLS-default flip would put
# them at the top of "most popular": 84 rows claiming to be the most installed
# apps in the catalog on the strength of having no measurement at all. Same
# for "newest" over the 9 unlisted rows that have no script_created. Name is
# the tiebreak everywhere so equal values do not shuffle between requests.
_SORTS = {
    "name": lambda: (CatalogEntry.name.asc(),),
    "popularity": lambda: (nulls_last(CatalogEntry.popularity.desc()),
                           CatalogEntry.name.asc()),
    "newest": lambda: (nulls_last(CatalogEntry.script_created.desc()),
                       CatalogEntry.name.asc()),
    "updated": lambda: (nulls_last(CatalogEntry.script_updated.desc()),
                        CatalogEntry.name.asc()),
}
DEFAULT_SORT = "name"


def _serialize(r: CatalogEntry) -> dict:
    return {
        "slug": r.slug, "name": r.name, "category": r.category, "type": r.entry_type,
        "description": r.description,
        # OUR endpoint when a local copy exists, upstream's URL when it does
        # not. The DB column always keeps upstream's URL
        # (services/catalog_icons.py owns the mirror, the metadata sync owns
        # the column), so this is a serve-time swap and nothing else.
        #
        # Chosen because it needs NO frontend change: StoreCard already
        # renders `entry.icon_url` and already falls back to an initials tile
        # on error, so a cached icon, an uncached one and a broken one all
        # already work. The alternative, a second `icon_local_url` field, would
        # have made every consumer decide which to prefer, which is a decision
        # with exactly one right answer and therefore not one to distribute.
        "icon_url": (f"/api/v1/catalog/{r.slug}/icon" if r.icon_cache_path
                     else r.icon_url),
        # `docs_url` rides alongside `website` because they are the same kind
        # of thing and now come from the same place (upstream's `website` and
        # `documentation`, services/catalog_metadata.py). Serving one and
        # withholding the other would mean a card that links the vendor site
        # while silently sitting on the docs link for the ~616 matched rows
        # that have one. The provenance columns (metadata_source,
        # metadata_synced_at, upstream_updated_at) deliberately stay
        # unserved: they are sync bookkeeping, and the freshness signal the UI
        # actually shows already has its own route in /catalog/status.
        "popularity": r.popularity, "website": r.website, "docs_url": r.docs_url,
        # The one sync timestamp that IS served, and it has to be: popularity
        # comes from upstream's telemetry service through a 23h server-side
        # cache (services/catalog_telemetry.py), so the number can be a full
        # day old while the name and icon beside it are minutes old. A raw
        # count with no "as of" next to it would present stale data as live.
        "popularity_synced_at": (r.popularity_synced_at.isoformat()
                                 if r.popularity_synced_at else None),
        # "listed" | "delisted" | "unlisted" | "variant" | null. The one
        # metadata-sync column that IS served, because it changes what the
        # card says rather than how fresh it is: "delisted" and "unlisted"
        # both mean upstream retired the app while the script is still in the
        # repo, which the Store badges. "variant" rows never reach the grid
        # (see list_catalog), so the value is only ever visible on the
        # unfiltered full-catalog call and on a direct by-slug lookup.
        "upstream_state": r.upstream_state,
        "default_cpu": r.default_cpu, "default_ram_mb": r.default_ram_mb,
        "default_disk_gb": r.default_disk_gb, "default_os": r.default_os,
        "default_os_version": r.default_os_version,
        "installable": r.installable, "unsupported_reason": r.unsupported_reason,
        "synced_at": r.synced_at.isoformat() if r.synced_at else None,
        # The verifiable answer to "what will Proxploy actually run?". These
        # two are only meaningful together: the path names the exact file and
        # the sha pins the exact revision of it, which is the same
        # pin-diff-consent posture install and update already hold themselves
        # to (services/appstore.py runs raw_url(upstream_sha, script_path) and
        # nothing else).
        #
        # `script_path` is SERVED, never derived, and the reason is worth
        # stating precisely because the obvious reason is wrong. All 585 ct
        # rows DO match `ct/<slug>.sh`, including the addon-delegated five and
        # the rename leftovers, and not by luck: discovery takes the slug FROM
        # the path (services/catalog.py::_ct_slug), so for ct rows the two
        # cannot diverge by construction. A derivation would pass any test
        # written only against the grid.
        #
        # It breaks on the 84 rows this same serializer returns from the
        # UNFILTERED catalog call, where the slug is not the filename: 35 pve
        # (`tools/pve/add-iptag.sh`), 32 addon, 16 vm (`vm/debian-13-vm.sh`)
        # and `turnkey` at `turnkey/turnkey.sh`. The addon rows are the sharp
        # case, because there discovery deliberately INVENTS a slug that
        # differs from the file: dual-variant collision detection renames
        # `tools/addon/coolify.sh` to `coolify-addon` so it cannot shadow the
        # ct row. Any rule that reconstructs a path from a slug has to know
        # about that, which is precisely the coupling this column exists to
        # avoid. Discovery owns it; this is a read of it, and nothing here is
        # added to WRITABLE_FIELDS.
        #
        # Either being null is normal and serves null: a row discovery has not
        # pinned yet has no honest link to offer, and a default would be a
        # link to the wrong file rather than no link.
        "script_path": r.script_path, "upstream_sha": r.upstream_sha,
        # Upstream's dates for the SCRIPT itself, which is what the Store's
        # "newest" and "recently updated" sorts mean. Not to be confused with
        # `synced_at` (when WE last discovered the row) or with
        # upstream_updated_at (when the upstream RECORD was last edited, which
        # a description fix bumps). ISO or null.
        "script_created": (r.script_created.isoformat()
                           if r.script_created else None),
        "script_updated": (r.script_updated.isoformat()
                           if r.script_updated else None),
        # The card tags. ALL FOUR ARE TRI-STATE AND NULL MEANS UNKNOWN, NEVER
        # "NO". The 9 `unlisted` rows have no upstream record at all, so we do
        # not know whether they are ARM-capable, updateable or privileged, and
        # a UI that renders null as a negative chip ("not ARM") would be
        # asserting something nothing here supports. No chip is the honest
        # rendering of null; a negative chip is not.
        "has_arm": r.has_arm, "architectures": r.architectures,
        "updateable": r.updateable, "privileged": r.privileged,
        "port": r.port,
    }


@router.get("", dependencies=[Depends(_read),
                              Depends(require_entitlement("store.catalog"))])
def list_catalog(category: str | None = None, q: str | None = None,
                 entry_type: str | None = None, sort: str = DEFAULT_SORT,
                 db=Depends(get_db), user: User = Depends(_read)):
    """Backs both the Store grid (always `entry_type=ct`, decision: non-LXC
    entries never appear there) and, unfiltered, the full catalog table every
    discovered entry lands in regardless of type.

    Both surfaces are real, which is why the variant exclusion below hangs off
    the `entry_type=ct` filter and not off the query as a whole: the grid must
    not show 28 blank duplicate cards, and the full catalog table must still
    account for every row discovery created.

    `sort` is one of `_SORTS`: name (default), popularity, newest, updated.
    Anything else falls back to the default rather than erroring, because the
    Store rendering in the wrong order is a far better failure than the Store
    not rendering; the value never reaches SQL either way.

    Ordering here is about CORRECTNESS, not paging: the frontend fetches every
    ct row and slices client side, so this decides which rows the user sees
    first, not which rows they receive.
    """
    query = db.query(CatalogEntry)
    if category:
        query = query.filter(CatalogEntry.category == category)
    if q:
        query = query.filter(CatalogEntry.name.ilike(f"%{q}%"))
    if entry_type == "ct":
        # The Store grid. `store_visible()` is the ONE definition of what the
        # Store may show (services/catalog_metadata.py), shared with the
        # command palette's store group in api/search.py. It is a shared
        # helper rather than a predicate written here because it was once
        # written twice, and the copy in search.py never got the variant
        # exclusion: the palette offered 28 hidden alpine phantoms and 84
        # non-ct rows, each linking to a /store/<slug> that opened Not Found.
        query = query.filter(store_visible())
    elif entry_type:
        query = query.filter(CatalogEntry.entry_type == entry_type)
    order_by = _SORTS.get(sort, _SORTS[DEFAULT_SORT])()
    return [_serialize(r) for r in query.order_by(*order_by).all()]


@router.get("/status", dependencies=[Depends(_read),
                                     Depends(require_entitlement("store.catalog"))])
def catalog_status(request: Request, db=Depends(get_db), user: User = Depends(_read)):
    """How old the catalog cache is, for doc 01's staleness indicator.

    MUST stay registered above `/{slug}`: Starlette matches in registration
    order, so declaring it after would make this a lookup for a catalog entry
    named "status" and 404 forever (same trap api/apps.py documents around its
    lifecycle wildcard).

    A separate route rather than a field on `GET /catalog` because that route
    returns a bare list and wrapping it now would break every existing caller
    for a banner.

    Staleness is a real signal, not decoration: the catalog is refreshed by a
    system schedule, so a stale cache means that schedule is off or has been
    failing, and every install decision the operator makes is being taken
    against pinned scripts that upstream may have moved past.
    """
    from sqlalchemy import func

    # `entries` counts what the operator can actually SEE, through the same
    # store_visible() predicate list_catalog and search.py use. It used to
    # count every ct row and reported 585 against a grid showing 556: the same
    # class of bug as the search one, a rule applied in one place and not
    # another, which is why this is the shared helper and not a third copy.
    total = db.query(CatalogEntry).filter(store_visible()).count()

    # `synced_at` is deliberately NOT narrowed the same way, and the two
    # answer different questions on purpose. The count answers "how many cards
    # do I have"; this answers "is the refresh schedule alive". Discovery
    # stamps every discovered row in the same pass, so a hidden row is exactly
    # as good a witness to that as a visible one, and restricting the sample
    # would buy nothing while introducing a real failure mode: an install
    # whose ct rows were all hidden would report "never refreshed" seconds
    # after a successful refresh. Scoped to ct because a vm/pve/turnkey row's
    # freshness has never been part of this signal.
    newest = db.query(func.max(CatalogEntry.synced_at)).filter(
        CatalogEntry.entry_type == "ct").scalar()
    stale_after_s = request.app.state.settings.catalog_stale_after_s
    age_s = (utcnow() - newest).total_seconds() if newest else None
    return {
        "synced_at": newest.isoformat() if newest else None,
        "age_s": age_s,
        "entries": total,
        "stale_after_s": stale_after_s,
        # Never refreshed counts as stale: an empty catalog is not a fresh one.
        "stale": True if newest is None else age_s > stale_after_s,
    }


@router.get("/{slug}/icon", dependencies=[Depends(_read),
                                          Depends(require_entitlement("store.catalog"))])
def get_catalog_icon(slug: str, db=Depends(get_db), request: Request = None,
                     user: User = Depends(_read)):
    """The locally mirrored icon, so the Store renders with no network.

    MUST stay registered above `/{slug}`: Starlette matches in registration
    order, and while a one-segment template cannot swallow a two-segment path
    today, the ordering rule this file already documents around `/status` is
    cheaper to follow than to re-derive.

    PATH TRAVERSAL, closed twice over, because the slug arrives from the URL.
    First, the slug is never used to build a path: it is an exact-match DB
    lookup, and the filename comes from the ROW (`icon_cache_path`), which the
    sync wrote from our own slug plus a fixed extension allowlist. A slug of
    `../../etc/passwd` matches no row and 404s before touching the filesystem.
    Second, the resolved path is required to sit inside the cache dir before
    it is opened, so even a corrupted column cannot escape. Belt and braces on
    purpose: this route reads files off disk on behalf of an HTTP caller, and
    that is worth two locks rather than one.
    """
    row = db.query(CatalogEntry).filter_by(slug=slug).one_or_none()
    if row is None or not row.icon_cache_path:
        raise HTTPException(404, "no cached icon")
    directory = icon_dir(request.app.state.settings.data_dir).resolve()
    path = (directory / row.icon_cache_path).resolve()
    if not path.is_file() or directory not in path.parents:
        # Either the file went missing under us or the stored name is not
        # inside the cache dir. Both are a 404 rather than a 500: the caller
        # asked for an icon, and _serialize's fallback to the upstream URL is
        # the honest answer, not a stack trace.
        raise HTTPException(404, "no cached icon")
    return FileResponse(
        path, media_type=CONTENT_TYPES.get(path.suffix.lstrip(".").lower(),
                                           "application/octet-stream"),
        # Immutable for a day: the file only changes when a catalog refresh
        # replaces it, and the refresh runs every 6 hours at most.
        headers={"Cache-Control": "public, max-age=86400",
                 **attribution_headers(row.icon_cache_source)})


@router.get("/{slug}", dependencies=[Depends(_read),
                                     Depends(require_entitlement("store.catalog"))])
def get_catalog_entry(slug: str, db=Depends(get_db),
                      user: User = Depends(_read)):
    row = db.query(CatalogEntry).filter_by(slug=slug).one_or_none()
    if row is None:
        raise HTTPException(404, "not found")
    # Lazy classification (decision 2): opening a card is one of the two
    # moments a ct/ entry's script pair gets fetched, never during discovery.
    # Wrapped so a failed upstream fetch (404, network hiccup, rate limit on
    # raw.githubusercontent.com) degrades to "not yet classified" rather than
    # 500ing a card the user is just trying to look at.
    if row.entry_type == "ct" and row.installable is None:
        try:
            ensure_classified(db, slug)
            db.refresh(row)
        except Exception:  # noqa: BLE001 - the card must still render
            pass
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
    # Optional: blank means build.func assigns the next free id via
    # `${var_ctid:-$NEXTID}`. Requiring one was a bug; there is nothing an
    # operator can usefully say here that the node cannot say better.
    ctid: int | None = None
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
# exercised in tests/test_catalog_install_api.py): root-consent for THIS HOST
# (mirrors hosts.py's CONSENT_NOTE shape, but asked once per host and
# remembered on Host.install_consent_at rather than re-ticked on every
# install) and an already-enrolled `ssh_key` HostCredential: no key, no
# route, regardless of consent.
@router.post("/{slug}/install", status_code=202,
             dependencies=[Depends(_install),
                          Depends(require_entitlement("store.install"))])
def install_catalog_entry(slug: str, body: InstallIn, request: Request,
                          db=Depends(get_db), user: User = Depends(_install)):
    host = db.get(Host, body.host_id)
    if host is None:
        raise HTTPException(404, "host not found")
    # A host that has already acknowledged the root-execution risk (either
    # ticked it on a prior install, or was backfilled at ssh_key enrolment
    # time, see the host_install_consent migration) proceeds without asking
    # again. A host that has not needs the explicit tick, and that tick is
    # what gets recorded here, on first use, so it is never asked again.
    if host.install_consent_at is None and not body.consent:
        raise HTTPException(400, "root-consent required: this installs and runs a "
                                 "community-scripts.org script as root on the node")
    if host.install_consent_at is None and body.consent:
        host.install_consent_at = utcnow()
        db.commit()
    cred = (db.query(HostCredential)
            .filter_by(host_id=body.host_id, kind="ssh_key").one_or_none())
    if cred is None:
        raise HTTPException(400, "host has no enrolled ssh_key credential")
    entry = db.query(CatalogEntry).filter_by(slug=slug).one_or_none()
    if entry is None:
        raise HTTPException(404, "not found")
    if entry.entry_type != "ct":
        raise HTTPException(400, f"not an installable LXC app: {entry.unsupported_reason}")
    if entry.installable is None:
        # Lazy classification (decision 2): the second of the two moments a
        # ct/ entry's script pair gets fetched, on demand, right here, not
        # during discovery. A fetch failure here is a real 400, not a 500:
        # the caller asked to install something the server could not verify.
        try:
            ensure_classified(db, slug)
            db.refresh(entry)
        except Exception:  # noqa: BLE001
            raise HTTPException(400, "could not verify install feasibility from "
                                     "upstream; try again or refresh the catalog")
    if not entry.installable:
        raise HTTPException(400, f"not installable: {entry.unsupported_reason}")
    # Pre-flight the (host_id, ctid) uniqueness the DB enforces anyway. Without
    # it a repeat install runs the whole script to completion on the real node
    # and only then hits IntegrityError inside the job handler: leaving an
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
