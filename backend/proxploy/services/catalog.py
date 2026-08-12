"""CatalogSource: discover the full community-scripts/ProxmoxVE corpus from
the repo's own directory layout, fetch a ct/+install script pair lazily (not
during discovery), parse resource defaults, classify feasibility, upsert into
`catalog_entries` (catalog expansion plan,
.superpowers/sdd/app-store-catalog-plan.md).

Three phases, each with a distinct cost profile:

1. `run_discovery` - exactly 2 `api.github.com` calls (`head_sha` +
   `discover_tree`'s tree listing), FLAT regardless of catalog size. Writes a
   skeleton row (slug, entry_type, category, script_path) for every entry the
   tree contains; never fetches a script body. This is the hard ceiling: no
   function in this module may add a third per-refresh `api.github.com` call,
   let alone a per-slug one (584 of those blows the 60/hr budget in a single
   refresh).
2. `ensure_classified` - one ct/ entry's script pair, fetched from
   `raw.githubusercontent.com` (a different host, not subject to the GitHub
   API rate limit) the moment a card is opened or an install starts. Never
   called from `run_discovery`.
3. `classify_many` - the low-priority background pass that walks whatever
   `ensure_classified` hasn't reached yet, bounded concurrency, run as its own
   job AFTER a refresh already returned, so it never blocks first paint.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

import httpx

from proxploy.jobs import HANDLERS, JobContext, JobFailed
from proxploy.models import CatalogEntry
from proxploy.services.catalog_categories import category_for
from proxploy.services.classifier import classify_install_feasibility

RAW_BASE = "https://raw.githubusercontent.com/community-scripts/ProxmoxVE"
HEAD_COMMIT_API = "https://api.github.com/repos/community-scripts/ProxmoxVE/commits/main"
TREE_API = "https://api.github.com/repos/community-scripts/ProxmoxVE/git/trees/{sha}?recursive=1"

# `dockge`, `dokploy`, `komodo`, `coolify` (investigation §2), and confirmed
# live during this plan's own verification, `runtipi` too: each has BOTH a
# standalone `ct/<slug>.sh` full-LXC installer and a `tools/addon/<slug>.sh`
# "install into an existing container" script under the SAME slug. Decision
# 4: show only the standalone installer in the Store. Directory-based
# discovery already gives the ct/ row the plain slug; an addon row with the
# same slug would collide with it in catalog_entries.slug (globally unique)
# if left alone.
#
# Detected dynamically, NOT a fixed allowlist: `runtipi` was not one of the
# four names the investigation's snapshot found, and a hardcoded set would
# have silently let its addon row collide with and shadow the ct row (an
# addon can never win a slug the repo also uses for a real standalone LXC
# installer). Whatever ct/ slugs a given tree actually has decides which
# addon rows need disambiguating, so this keeps working as the upstream
# corpus grows without needing a code change for the next one.

NON_CT_REASON = {
    "vm": "VM script: builds a virtual machine, not a single LXC container",
    "pve": "host script: configures the Proxmox node itself, not an app container",
    "addon": "add-on: installs into an existing container rather than creating one",
    "turnkey": "turnkey appliance: deploys a pre-built template, not a "
               "community-scripts build_container install",
}

APP_RE = re.compile(r'^APP="([^"]+)"', re.MULTILINE)
SOURCE_RE = re.compile(r"^#\s*Source:\s*(\S+)", re.MULTILINE)
VAR_RE = {
    "default_cpu": re.compile(r'var_cpu="\$\{var_cpu:-(\d+)\}"'),
    "default_ram_mb": re.compile(r'var_ram="\$\{var_ram:-(\d+)\}"'),
    "default_disk_gb": re.compile(r'var_disk="\$\{var_disk:-(\d+)\}"'),
    "default_os": re.compile(r'var_os="\$\{var_os:-([a-z0-9]+)\}"'),
    "default_os_version": re.compile(r'var_version="\$\{var_version:-([\w.]+)\}"'),
}


def _fetch(url: str, **kw) -> httpx.Response:
    return httpx.get(url, timeout=15.0, **kw)


def raw_url(sha: str, path: str) -> str:
    """Raw-content URL pinned to an immutable commit, never to `main`.

    Single definition on purpose: `ensure_classified` classifies/pins the
    content at this URL and `services/appstore.py::run_install` executes the
    content at this URL, and "pinned" only means anything if both resolve to
    the exact same bytes.
    """
    return f"{RAW_BASE}/{sha}/{path}"


def head_sha() -> str:
    """The repo's current HEAD commit SHA. Call #1 of the refresh's flat,
    catalog-size-independent 2-request GitHub API budget."""
    resp = _fetch(HEAD_COMMIT_API)
    if resp.status_code != 200:
        raise JobFailed(f"upstream HEAD commit lookup failed ({resp.status_code})")
    sha = (resp.json() or {}).get("sha")
    if not sha:
        raise JobFailed("upstream HEAD commit lookup returned no sha")
    return sha


def _ct_slug(path: str) -> str | None:
    if path.startswith("ct/headers/") or not path.startswith("ct/") or not path.endswith(".sh"):
        return None
    return path[len("ct/"):-len(".sh")]


def _classify_path(path: str, ct_slugs: set[str]) -> dict | None:
    """Type comes from directory placement, mechanically. Returns None for
    anything that isn't a real, classifiable entry (ct/headers/ banners,
    tools/copy-data/'s 9 scripts, which fit none of the four buckets per
    investigation §3, and any other path in the tree).

    `ct_slugs` is every ct/ slug this SAME tree discovered, computed once by
    the caller: an addon whose slug also names a real standalone ct/
    installer is disambiguated (see the DUAL_VARIANT note above), everything
    else keeps its plain slug.
    """
    if (slug := _ct_slug(path)) is not None:
        return {"slug": slug, "entry_type": "ct", "script_path": path}
    if path.startswith("tools/copy-data/"):
        return None
    if path.startswith("vm/") and path.endswith(".sh"):
        return {"slug": path[len("vm/"):-len(".sh")], "entry_type": "vm", "script_path": path}
    if path.startswith("tools/pve/") and path.endswith(".sh"):
        return {"slug": path[len("tools/pve/"):-len(".sh")], "entry_type": "pve",
                "script_path": path}
    if path.startswith("tools/addon/") and path.endswith(".sh"):
        slug = path[len("tools/addon/"):-len(".sh")]
        if slug in ct_slugs:
            return {"slug": f"{slug}-addon", "entry_type": "addon", "script_path": path}
        return {"slug": slug, "entry_type": "addon", "script_path": path}
    if path == "turnkey/turnkey.sh":
        return {"slug": "turnkey", "entry_type": "turnkey", "script_path": path}
    return None


def discover_tree(sha: str) -> list[dict]:
    """One request: `git/trees/<sha>?recursive=1`, `truncated: false`
    confirmed against the live repo (investigation §1). Call #2 of the
    refresh's 2-request budget; the ENTIRE catalog's shape comes from this
    single response, no matter how many entries it contains."""
    resp = _fetch(TREE_API.format(sha=sha))
    if resp.status_code != 200:
        raise JobFailed(f"upstream tree listing failed ({resp.status_code})")
    body = resp.json() or {}
    if body.get("truncated"):
        # A truncated tree would silently drop entries below some GitHub-side
        # size cutoff. Refusing beats ingesting a partial catalog and looking
        # complete when it isn't.
        raise JobFailed("upstream tree listing was truncated; refusing a partial catalog")
    blobs = [node for node in body.get("tree", []) if node.get("type") == "blob"]
    ct_slugs = {s for node in blobs if (s := _ct_slug(node.get("path", ""))) is not None}
    out = []
    for node in blobs:
        parsed = _classify_path(node.get("path", ""), ct_slugs)
        if parsed is not None:
            out.append(parsed)
    return out


def _display_name(slug: str) -> str:
    return " ".join(w.capitalize() for w in re.split(r"[-_]+", slug) if w) or slug


def run_discovery(db) -> dict:
    """Populate the catalog with every entry the tree contains: name (a
    slug-derived fallback; ensure_classified improves it for ct/ once fetched
    lazily), entry_type, category, slug, script_path. Deliberately does NOT
    fetch a single ct/+install script pair here, and deliberately does NOT
    call the feasibility classifier: those are ensure_classified's job, run
    on demand, never during discovery."""
    sha = head_sha()
    discovered = discover_tree(sha)
    counts: dict[str, int] = {}
    for d in discovered:
        counts[d["entry_type"]] = counts.get(d["entry_type"], 0) + 1
        _upsert_skeleton(db, d, sha)
    db.commit()
    return {"upstream_sha": sha, "total": len(discovered), "counts": counts}


def _upsert_skeleton(db, d: dict, sha: str) -> None:
    row = db.query(CatalogEntry).filter_by(slug=d["slug"]).one_or_none()
    if row is not None and row.upstream_sha == sha and row.entry_type == d["entry_type"]:
        return  # nothing changed upstream since the last refresh
    is_new = row is None
    if is_new:
        row = CatalogEntry(slug=d["slug"])
        db.add(row)
    row.entry_type = d["entry_type"]
    row.script_path = d["script_path"]
    if is_new or not row.name:
        row.name = _display_name(d["slug"])
    if is_new or not row.category:
        row.category = category_for(d["slug"], d["entry_type"])
    if d["entry_type"] != "ct":
        # Never installable, never classified: these types don't have a
        # ct/+install/ pair in the shape the classifier expects, and the
        # Store never shows them regardless (decision: LXC-only Store, other
        # types stay in the catalog table tagged by type).
        row.installable = False
        row.unsupported_reason = NON_CT_REASON[d["entry_type"]]
    elif row.upstream_sha is not None and row.upstream_sha != sha:
        # The commit moved: any previously fetched ct/install text was pinned
        # to the OLD commit and is no longer what run_install would execute.
        # Clear it so ensure_classified re-fetches fresh content at the new
        # sha rather than silently keep serving a stale classification.
        row.installable = None
        row.unsupported_reason = None
        row.raw = None
    row.upstream_sha = sha
    row.synced_at = datetime.now(timezone.utc)


def parse_ct_script(content: str) -> dict:
    meta: dict = {}
    if m := APP_RE.search(content):
        meta["name"] = m.group(1)
    if m := SOURCE_RE.search(content):
        meta["website"] = m.group(1)
    for field, pattern in VAR_RE.items():
        if m := pattern.search(content):
            meta[field] = int(m.group(1)) if field != "default_os" and field != "default_os_version" else m.group(1)
    return meta


def _already_classified(row: CatalogEntry) -> bool:
    return row.installable is not None and row.raw is not None


def ensure_classified(db, slug: str) -> CatalogEntry | None:
    """Fetch, parse and classify one ct/ entry's script pair, lazily: called
    the moment a card is opened (GET /catalog/{slug}) or an install starts
    (POST /catalog/{slug}/install), never during discovery. Idempotent: a
    slug already classified at its current upstream_sha is a no-op.

    Raw-content fetches only (raw.githubusercontent.com), no api.github.com
    call, so this never touches the refresh's 2-request budget no matter how
    many times it runs.
    """
    row = db.query(CatalogEntry).filter_by(slug=slug, entry_type="ct").one_or_none()
    if row is None or _already_classified(row):
        return row
    if not row.upstream_sha or not row.script_path:
        return row  # nothing pinned yet; a refresh hasn't run

    ct_resp = _fetch(raw_url(row.upstream_sha, row.script_path))
    if ct_resp.status_code != 200:
        row.installable = False
        row.unsupported_reason = "could not fetch the install script from upstream"
        db.commit()
        return row

    install_path = f"install/{slug}-install.sh"
    install_resp = _fetch(raw_url(row.upstream_sha, install_path))
    if install_resp.status_code != 200:
        # 13 ct/ scripts have no matching install/ file (investigation §1):
        # a real, known shape, not corrupt data. Store what was fetched so a
        # retry at the same commit is a no-op, and report it honestly rather
        # than crash the caller.
        meta = parse_ct_script(ct_resp.text)
        if meta.get("name"):
            row.name = meta["name"]
        row.website = meta.get("website") or row.website
        row.installable = False
        row.unsupported_reason = "no install script found upstream"
        row.raw = {"ct_script": ct_resp.text}
        db.commit()
        return row

    meta = parse_ct_script(ct_resp.text)
    installable, reason = classify_install_feasibility(ct_resp.text, install_resp.text)
    if meta.get("name"):
        row.name = meta["name"]
    row.website = meta.get("website") or row.website
    row.default_cpu = meta.get("default_cpu")
    row.default_ram_mb = meta.get("default_ram_mb")
    row.default_disk_gb = meta.get("default_disk_gb")
    row.default_os = meta.get("default_os")
    row.default_os_version = meta.get("default_os_version")
    row.installable = installable
    row.unsupported_reason = reason
    row.raw = {"ct_script": ct_resp.text, "install_script": install_resp.text}
    db.commit()
    return row


def _classify_one_sync(sessionmaker, slug: str) -> None:
    with sessionmaker() as db:
        ensure_classified(db, slug)


async def classify_many(sessionmaker, slugs: list[str], concurrency: int = 8) -> dict:
    """The low-priority background pass (decision 2): bounded-concurrency
    lazy classification of whatever ensure_classified hasn't reached yet.
    Runs as its own job, scheduled AFTER run_discovery already returned, so a
    freshly refreshed store is usable (names, types, categories) before this
    even starts.

    Bounded concurrency, not a `for` loop: the investigation flagged a plain
    sequential fetch of up to ~1,168 raw files (2 per ct/ entry) as several
    minutes of wall-clock time blocking one thread. Concurrency here is
    asyncio tasks each parking a blocking httpx call in a thread, capped by a
    semaphore; still `raw.githubusercontent.com` only, never api.github.com,
    so it has no effect on the refresh's 2-request ceiling.
    """
    sem = asyncio.Semaphore(concurrency)
    done = 0
    failed: list[dict] = []
    lock = asyncio.Lock()

    async def worker(slug: str) -> None:
        nonlocal done
        async with sem:
            try:
                await asyncio.to_thread(_classify_one_sync, sessionmaker, slug)
                async with lock:
                    done += 1
            except Exception as e:  # noqa: BLE001 - one bad slug can't kill the pass
                async with lock:
                    failed.append({"slug": slug, "reason": str(e)})

    await asyncio.gather(*(worker(s) for s in slugs))
    return {"done": done, "failed": failed}


async def refresh_catalog(ctx: JobContext, params: dict) -> dict:
    from proxploy.services.appstore import mark_updates_available
    from proxploy.services.community_scripts_scrape import (
        apply_enrichment, fetch_enrichment,
    )

    app = ctx.backend.app
    with app.state.sessionmaker() as db:
        result = await asyncio.to_thread(run_discovery, db)
    ctx.log(f"discovered {result['total']} entries: {result['counts']}")
    ctx.log(f"pinned to upstream commit {result['upstream_sha']}")

    # Best-effort enrichment (decision 1): an undocumented scrape of another
    # site's internals. Wrapped so that a 403, a timeout, or a shape change
    # never fails this job; the catalog is fully usable from discovery alone.
    def _enrich() -> int:
        with app.state.sessionmaker() as db:
            mapping = fetch_enrichment()
            return apply_enrichment(db, mapping)

    try:
        enriched = await asyncio.to_thread(_enrich)
        ctx.log(f"community-scripts.org enrichment applied to {enriched} entries")
    except Exception as e:  # noqa: BLE001 - see module docstring: best-effort only
        ctx.log(f"community-scripts.org enrichment skipped: {e}", stream="stderr")

    # A refresh is the ONLY moment `update_available` can change, so it is the
    # only place this has to run: no separate sweep, no separate schedule.
    def _mark():
        with app.state.sessionmaker() as db:
            return mark_updates_available(db)

    counts = await asyncio.to_thread(_mark)
    result["updates_marked"] = counts["marked"]
    result["updates_cleared"] = counts["cleared"]
    ctx.log(f"{counts['marked']} app(s) have an update available")
    if counts["marked"] or counts["cleared"]:
        app.state.bus.publish("resource", {"type": "app", "change": "list"})

    # Low-priority background pass (decision 2): queued, not awaited. The
    # store is already usable (names, types, categories from discovery
    # alone) before this job even starts.
    with app.state.sessionmaker() as db:
        backlog_job = app.state.jobs.enqueue(db, kind="catalog.classify_backlog")
    ctx.log(f"queued background classification job {backlog_job.id}")
    result["classify_backlog_job_id"] = backlog_job.id

    ctx.progress(100)
    app.state.bus.publish("resource", {"type": "catalog", "change": "refreshed"})
    return result


HANDLERS["catalog.refresh"] = refresh_catalog


async def classify_backlog(ctx: JobContext, params: dict) -> dict:
    """Low-priority background pass: classify every ct/ entry a refresh
    discovered but hasn't been opened or installed yet. Self-enqueued by
    refresh_catalog, never blocks it."""
    app = ctx.backend.app
    with app.state.sessionmaker() as db:
        slugs = [r.slug for r in db.query(CatalogEntry.slug)
                .filter(CatalogEntry.entry_type == "ct",
                       CatalogEntry.installable.is_(None)).all()]
    ctx.log(f"classifying {len(slugs)} unclassified entries")
    result = await classify_many(app.state.sessionmaker, slugs)
    ctx.log(f"classified {result['done']}, {len(result['failed'])} failed")
    for f in result["failed"]:
        ctx.log(f"{f['slug']}: {f['reason']}", stream="stderr")
    ctx.progress(100)
    if result["done"]:
        app.state.bus.publish("resource", {"type": "catalog", "change": "list"})
    return result


HANDLERS["catalog.classify_backlog"] = classify_backlog
