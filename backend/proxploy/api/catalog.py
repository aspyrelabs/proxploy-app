"""Catalog browse + refresh routes. Read routes are viewer-level; refresh is
admin-gated. A refresh costs exactly 2 api.github.com calls flat, regardless
of catalog size (services/catalog.py::run_discovery); per-entry script pairs
are fetched lazily by ensure_classified from raw.githubusercontent.com (a
different host, no GitHub rate limit) the moment a card is opened or an
install is attempted."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import nulls_last

from proxploy.api.deps import authorize, get_db, require_entitlement
from proxploy.api.jobs import job_out
from proxploy.models import (App, CatalogEntry, Host, HostCredential, Job, User,
                             to_iso, utcnow)
from proxploy.services import installanswers
from proxploy.services.audit import write_audit
from proxploy.services.catalog import ensure_classified
from proxploy.services.catalog_icons import (CONTENT_TYPES,
                                             attribution_headers, icon_dir,
                                             served_icon_url)
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


# Allowlist of prebuilt orderings: a sort key is caller-controlled, so the
# only safe shape is one that never reaches SQL as a string (an unknown key
# selects the default, never interpolated).
# 
# NULLS ALWAYS LAST on every descending sort: SQLite orders NULL FIRST
# ascending, so a bare `popularity ASC` would crown the 84 unmeasured rows
# "most popular" (same for `newest` over the 9 unlisted rows). Name is the
# tiebreak everywhere so equal values don't shuffle between requests.
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
        # not. services/catalog_icons.py::served_icon_url owns that swap, and
        # api/apps.py resolves an installed app's icon through the same call,
        # so a card and the app installed from it can never disagree.
        "icon_url": served_icon_url(r),
        # `docs_url` rides alongside `website`: they come from the same upstream
        # place (services/catalog_metadata.py), and serving one without the other
        # would sit on the docs link for the ~616 rows that have one. Provenance
        # columns (metadata_source, metadata_synced_at, upstream_updated_at) stay
        # unserved: sync bookkeeping, not card content.
        "popularity": r.popularity, "website": r.website, "docs_url": r.docs_url,
        # The one sync timestamp that IS served: popularity comes through a 23h
        # server-side cache (services/catalog_telemetry.py), so a raw count with no
        # "as of" would present stale data as live.
        "popularity_synced_at": to_iso(r.popularity_synced_at),
        # "listed" | "delisted" | "unlisted" | "variant" | null. Served because it
        # changes what the card says: "delisted"/"unlisted" mean upstream retired
        # the app while the script stays in the repo (Store badges them). "variant"
        # rows never reach the grid (see list_catalog), so this value only shows on
        # the unfiltered full-catalog call and a direct by-slug lookup.
        "upstream_state": r.upstream_state,
        "default_cpu": r.default_cpu, "default_ram_mb": r.default_ram_mb,
        "default_disk_gb": r.default_disk_gb, "default_os": r.default_os,
        "default_os_version": r.default_os_version,
        "installable": r.installable, "unsupported_reason": r.unsupported_reason,
        # The questions the install dialog has to ask. NULL until the row is
        # classified, so the client renders nothing rather than guessing.
        "prompts": r.prompts,
        "synced_at": to_iso(r.synced_at),
        # `script_path` is SERVED, never derived. The slug is not the filename for
        # the 84 unfiltered rows: 35 pve (`tools/pve/add-iptag.sh`), 32 addon, 16 vm
        # (`vm/debian-13-vm.sh`), `turnkey` (`turnkey/turnkey.sh`). The addon rows
        # are the sharp case: discovery renames `tools/addon/coolify.sh` to
        # `coolify-addon` (dual-variant collision detection) so it can't shadow the
        # ct row. Any rule reconstructing a path from a slug must know this, which is
        # the coupling this column exists to avoid. Discovery owns it; this is a read
        # of it. Either null is normal and serves null: an unpinned row has no honest
        # link, and a default would be a link to the wrong file.
        "script_path": r.script_path, "upstream_sha": r.upstream_sha,
        # Upstream's dates for the SCRIPT itself, which is what the Store's
        # "newest" and "recently updated" sorts mean. Not to be confused with
        # `synced_at` (when WE last discovered the row) or with
        # upstream_updated_at (when the upstream RECORD was last edited, which
        # a description fix bumps). ISO or null.
        "script_created": to_iso(r.script_created),
        "script_updated": to_iso(r.script_updated),
        # The card tags. ALL FOUR ARE TRI-STATE AND NULL MEANS UNKNOWN, NEVER "NO":
        # the 9 `unlisted` rows have no upstream record, so we don't know whether
        # they're ARM-capable/updateable/privileged. No chip is the honest rendering
        # of null; a negative chip is not.
        "has_arm": r.has_arm, "architectures": r.architectures,
        "updateable": r.updateable, "privileged": r.privileged,
        "port": r.port,
    }


@router.get("", dependencies=[Depends(_read),
                              Depends(require_entitlement("store.catalog"))])
def list_catalog(category: str | None = None, q: str | None = None,
                 entry_type: str | None = None, sort: str = DEFAULT_SORT,
                 db=Depends(get_db), user: User = Depends(_read)):
    """Backs the Store grid (always `entry_type=ct`; non-LXC entries never
    appear) and, unfiltered, the full catalog table every discovered entry
    lands in. The variant exclusion hangs off the `entry_type=ct` filter, not
    the query as a whole: the grid must not show 28 blank duplicate cards, and
    the full table must still account for every row discovery created.

    `sort` is one of `_SORTS`: name (default), popularity, newest, updated.
    Anything else falls back to the default (never errors; never reaches SQL).

    Ordering is about CORRECTNESS, not paging: the frontend fetches every ct
    row and slices client side, so this decides which rows the user sees
    first, not which rows they receive."""
    query = db.query(CatalogEntry)
    if category:
        query = query.filter(CatalogEntry.category == category)
    if q:
        query = query.filter(CatalogEntry.name.ilike(f"%{q}%"))
    if entry_type == "ct":
        # The Store grid. `store_visible()` is the ONE definition of what the Store
        # may show (services/catalog_metadata.py), shared with the command palette's
        # store group (api/search.py).
        query = query.filter(store_visible())
    elif entry_type:
        query = query.filter(CatalogEntry.entry_type == entry_type)
    order_by = _SORTS.get(sort, _SORTS[DEFAULT_SORT])()
    return [_serialize(r) for r in query.order_by(*order_by).all()]


@router.get("/status", dependencies=[Depends(_read),
                                     Depends(require_entitlement("store.catalog"))])
def catalog_status(request: Request, db=Depends(get_db), user: User = Depends(_read)):
    """How old the catalog cache is.

    MUST stay registered above `/{slug}`: Starlette matches in registration
    order, so declaring it after would make this a lookup for a catalog entry
    named "status" and 404 forever.

    A separate route rather than a field on `GET /catalog` because that route
    returns a bare list and wrapping it now would break every existing caller."""
    from sqlalchemy import func

    # `entries` counts what the operator can actually SEE, through the same
    # store_visible() predicate list_catalog and search.py use.
    total = db.query(CatalogEntry).filter(store_visible()).count()

    # `synced_at` is deliberately NOT narrowed: the count answers "how many
    # cards", this answers "is the refresh schedule alive". Discovery stamps
    # every row in one pass, so a hidden row witnesses that as well as a
    # visible one, and narrowing would report "never refreshed" for an install
    # whose ct rows were all hidden. Scoped to ct: vm/pve/turnkey freshness was
    # never part of this signal.
    newest = db.query(func.max(CatalogEntry.synced_at)).filter(
        CatalogEntry.entry_type == "ct").scalar()
    stale_after_s = request.app.state.settings.catalog_stale_after_s
    age_s = (utcnow() - newest).total_seconds() if newest else None
    return {
        "synced_at": to_iso(newest),
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
    # Lazy classification: opening a card is one of the two moments a ct/ entry's
    # script pair gets fetched, never during discovery. A failed upstream fetch
    # degrades to "not yet classified" rather than 500ing a card.
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
    # `${var_ctid:-$NEXTID}`.
    ctid: int | None = None
    overrides: dict = {}
    consent: bool = False
    # One entry per prompt the install script asks that build.func cannot
    # answer from the environment, keyed by the variable the prompt assigns
    # into. Validated against the catalog row's own `prompts`, so a caller
    # cannot use this to export an arbitrary variable into a root shell.
    answers: dict[str, str] = {}

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


# This route triggers the single most security-relevant action: SSH as root
# into a node and run a community-scripts.org script. Two independent gates,
# either can 400 first: root-consent for THIS HOST (asked once per host,
# remembered on Host.install_consent_at, not re-ticked per install) and an
# already-enrolled `ssh_key` HostCredential: no key, no route, regardless of
# consent.
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
        # Lazy classification: the second of the two moments a ct/ entry's script
        # pair gets fetched, on demand, not during discovery. A fetch failure here is
        # a real 400, not a 500: the caller asked to install something the server
        # could not verify.
        try:
            ensure_classified(db, slug)
            db.refresh(entry)
        except Exception:  # noqa: BLE001
            raise HTTPException(400, "could not verify install feasibility from "
                                     "upstream; try again or refresh the catalog")
    if not entry.installable:
        raise HTTPException(400, f"not installable: {entry.unsupported_reason}")
    # Split before anything is written. `secret` never touches jobs.params:
    # it is staged encrypted below and params carries only the handle, because
    # params is redacted by KEY NAME and these names come from upstream
    # (see services/installanswers for the measurements).
    try:
        plain_answers, secret_answers = installanswers.prepare(entry.prompts,
                                                               body.answers)
    except installanswers.AnswerError as e:
        raise HTTPException(400, str(e)) from e
    # Pre-flight the (host_id, ctid) uniqueness the DB enforces anyway. Without
    # it a repeat install runs the whole script to completion on the real node
    # and only then hits IntegrityError inside the job handler: leaving an
    # untracked container behind. Cheap check, real node mutation avoided.
    if (db.query(App).filter_by(host_id=body.host_id, ctid=body.ctid)
            .one_or_none()) is not None:
        raise HTTPException(409, f"CT {body.ctid} on host {body.host_id} is already tracked")
    # The guard above only fires when a ctid was supplied, and the dialog tells
    # operators to leave it blank so the node picks the next free id. That is
    # the gap that turns one interrupted install into two containers: the first
    # run really built CT 9001, its job reads unknown, and a second run with no
    # pinned id is handed 9002 while 9001 is left unmanaged.
    #
    # So refuse on the pair the operator actually repeats, (catalog_slug,
    # host_id), while an install for it is still unresolved. `unknown` IS
    # unresolved by definition: moving a job off it is the only thing
    # reconciliation does, so no second flag can drift out of step with this.
    unresolved = (db.query(Job)
                  .filter(Job.kind == "app.install", Job.status == "unknown")
                  .all())
    for j in unresolved:
        cp = j.checkpoint or {}
        if (cp.get("catalog_slug") == slug
                and cp.get("host_id") == body.host_id):
            raise HTTPException(409,
                f"a previous install of {slug} on this host was interrupted and "
                f"Proxploy is still checking the node to find out whether it "
                f"created a container (job {j.id}). Installing again now could "
                f"leave two. This clears by itself once the check completes, or "
                f"if the host is unreachable, once it can be reached.")
    # BOTH host writes live here, after every refusal above, so a request that
    # 400s/404s/409s elsewhere in this route never mutates the host as a side
    # effect of failing. That matters most for the consent stamp: it is the
    # operator's acknowledgement that an install ran as root, and a request
    # that installs nothing must not permanently record one.
    if host.install_consent_at is None and body.consent:
        host.install_consent_at = utcnow()
    db.commit()
    # The App row does not exist yet (the job below creates it), so there is no
    # app id for resolve_target_name to look up, and the audit row would take the
    # HOST's name ("App Install / pve1") and never say which app. Record what was
    # REQUESTED instead. The ctid is optional: blank means the node picks the
    # next free one, not knowable until it does.
    where = f"{body.name} (CT {body.ctid})" if body.ctid else body.name
    requested = f"{where} on {host.name}"
    answers_handle = installanswers.stage(db, request.app.state.secretstore,
                                          secret_answers)
    job = request.app.state.jobs.enqueue(
        db, kind="app.install", requested_by=user.id, target_name=requested,
        params={"catalog_slug": slug, "host_id": body.host_id, "name": body.name,
               "ctid": body.ctid, "overrides": body.overrides,
               "answers": plain_answers, "answers_handle": answers_handle})
    write_audit(db, actor_type="user", actor_id=user.id, action="app.install",
                target_type="host", target_id=body.host_id, job_id=job.id,
                target_name=requested,
                params={"catalog_slug": slug, "name": body.name, "ctid": body.ctid,
                        # NAMES only. The values are the operator's answers,
                        # audit_events.params is unencrypted, and the sensitive
                        # ones are not here to write down in the first place.
                        "answered": sorted(body.answers)},
                ip=request.client.host if request.client else None)
    return {"job": job_out(job)}
