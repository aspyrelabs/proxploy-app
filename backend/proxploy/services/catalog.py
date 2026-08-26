"""CatalogSource: discover the full community-scripts/ProxmoxVE corpus from
the repo's own directory layout, fetch a ct/+install script pair lazily (not
during discovery), parse resource defaults, classify feasibility, upsert into
`catalog_entries`.

Three phases, each with a distinct cost profile:

1. `run_discovery` - exactly 2 `api.github.com` calls (`head_sha` +
   `discover_tree`), FLAT regardless of catalog size. Writes a skeleton row
   for every entry in the tree and never fetches a script body. This is the
   hard ceiling: no function here may add a third per-refresh
   `api.github.com` call, let alone a per-slug one (584 of those blows the
   60/hr budget in a single refresh).
2. `ensure_classified` - one ct/ entry's script pair from
   `raw.githubusercontent.com` (a different host, not subject to the GitHub
   API rate limit) the moment a card is opened or an install starts. Never
   called from `run_discovery`.
3. `classify_many` - the low-priority background pass over whatever
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
from proxploy.services.classifier import (UNSUPPORTED_ADDON_DELEGATED,
                                          addon_delegation_slug,
                                          classify_install_feasibility)

RAW_BASE = "https://raw.githubusercontent.com/community-scripts/ProxmoxVE"
HEAD_COMMIT_API = "https://api.github.com/repos/community-scripts/ProxmoxVE/commits/main"
TREE_API = "https://api.github.com/repos/community-scripts/ProxmoxVE/git/trees/{sha}?recursive=1"

# `dockge`, `dokploy`, `komodo`, `coolify` and `runtipi` each have BOTH a
# standalone `ct/<slug>.sh` full-LXC installer and a `tools/addon/<slug>.sh`
# "install into an existing container" script under the SAME slug. Only the
# standalone installer is shown in the Store, and directory-based discovery
# already gives the ct/ row the plain slug, so an addon row with the same slug
# would collide with it in catalog_entries.slug (globally unique) if left
# alone.
#
# Detected dynamically, NOT a fixed allowlist: `runtipi` was not one of the
# four names first found, and a hardcoded set would have silently let its
# addon row shadow the ct row. Whatever ct/ slugs a given tree actually has
# decides which addon rows need disambiguating, so this keeps working as the
# upstream corpus grows.

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
    tools/copy-data/'s scripts, which fit none of the four buckets, and any
    other path in the tree).

    `ct_slugs` is every ct/ slug this SAME tree discovered, computed once by
    the caller: an addon whose slug also names a real standalone ct/ installer
    is disambiguated (see the dual-variant note above), everything else keeps
    its plain slug.
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
    """One request: `git/trees/<sha>?recursive=1`. Call #2 of the refresh's
    2-request budget; the ENTIRE catalog's shape comes from this single
    response, no matter how many entries it contains."""
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
    fetch a script pair and does NOT call the feasibility classifier: that is
    ensure_classified's job, on demand, never during discovery."""
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
        # ct/+install/ pair in the shape the classifier expects, and the Store
        # is LXC-only, so they stay in the catalog table tagged by type.
        row.installable = False
        row.unsupported_reason = NON_CT_REASON[d["entry_type"]]
    elif row.upstream_sha is not None and row.upstream_sha != sha:
        # The commit moved: any previously fetched ct/install text was pinned
        # to the OLD commit and is no longer what run_install would execute.
        # Clear it so ensure_classified re-fetches fresh content at the new
        # sha rather than silently keep serving a stale classification.
        row.installable = None
        row.unsupported_reason = None
        row.raw = _keep_metadata(row, None)
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


def pinned_payload_script(row: CatalogEntry) -> str | None:
    """The in-container payload script this catalog entry has pinned, whatever
    shape upstream ships it in, or None if nothing is pinned yet. THE ONE
    READER of that pair of `raw` keys, shared because four call sites ask the
    identical question. The reader half of what `ensure_classified` writes.

    Two keys because upstream ships two shapes. A normal app has
    `install/<slug>-install.sh`, stored under "install_script". Five apps
    (coolify, dockge, dokploy, komodo, runtipi) instead delegate to
    `tools/addon/<slug>.sh`, stored under "addon_script"
    (classifier.addon_delegation_slug). Reading only the first key files an
    AppScript row with empty content and the sha256 of the empty string for
    those five.

    NOT what gets EXECUTED. run_install and the update path execute the pinned
    ct script at `raw_url(upstream_sha, script_path)`, which performs the
    addon delegation itself at runtime. This is what gets RECORDED, diffed and
    shown. install_script wins when both are somehow present: it is the more
    specific key, and only the addon-delegating path writes the other one.
    """
    raw = row.raw or {}
    return raw.get("install_script") or raw.get("addon_script") or None


def _keep_metadata(row: CatalogEntry, new_raw: dict | None) -> dict | None:
    """`raw` carries two independent payloads with two different lifecycles:
    the pinned ct/install script pair this module fetches per upstream commit,
    and the upstream record snapshot services/catalog_metadata.py writes under
    "metadata" on its own schedule. Classification rewrites the former, so it
    has to carry the latter through rather than blow it away on every backlog
    pass."""
    snapshot = (row.raw or {}).get("metadata")
    if snapshot is None:
        return new_raw
    return {**(new_raw or {}), "metadata": snapshot}


def _apply_script_presentation(row: CatalogEntry, meta: dict) -> None:
    """The ct script's own `APP="..."` and `# Source:` lines, applied only
    where upstream metadata has not already spoken.

    Presentation fields belong to services/catalog_metadata.py when a slug
    matched an upstream record, and classification runs AFTER the metadata
    sync in a refresh, so writing these unconditionally would hand the last
    word back to the script parse for every matched row. An unmatched row has
    no upstream record to defer to, and `APP="Redis"` beats the slug-derived
    fallback name, so it still gets the script's version.
    """
    if row.metadata_source is None:
        if meta.get("name"):
            row.name = meta["name"]
        row.website = meta.get("website") or row.website


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
    # Which `raw` key the payload lands under, so a reader can tell at a
    # glance which of the two shapes this row is.
    payload_key = "install_script"
    addon_delegated = False
    if install_resp.status_code != 200:
        # Before concluding there is nothing to classify: some ct scripts
        # delegate their in-container step to tools/addon/<slug>.sh instead of
        # shipping an install/ file (classifier.addon_delegation_slug). They
        # are still NOT installable, for a reason that has nothing to do with
        # the addon script's contents (see below), but the script carries the
        # real payload for the `raw` snapshot, and reaching this branch is what
        # lets us give an accurate reason instead of the flatly wrong "no
        # install script found upstream".
        addon_slug = addon_delegation_slug(ct_resp.text)
        if addon_slug is None:
            # 13 ct/ scripts have no matching install/ file and no addon
            # delegation either: a real, known shape, not corrupt data. Store
            # what was fetched so a retry at the same commit is a no-op, and
            # report it honestly rather than crash the caller.
            meta = parse_ct_script(ct_resp.text)
            _apply_script_presentation(row, meta)
            row.installable = False
            row.unsupported_reason = "no install script found upstream"
            row.raw = _keep_metadata(row, {"ct_script": ct_resp.text})
            db.commit()
            return row
        payload_key = "addon_script"
        addon_delegated = True
        # PINNED, via the same raw_url helper as the ct and install fetches.
        # An unpinned addon fetch would classify one revision and let
        # run_install execute another, which is the entire guarantee the pin
        # exists to make. raw.githubusercontent.com only; no api.github.com
        # call is added by this path, so the flat 2-call ceiling is untouched.
        install_resp = _fetch(raw_url(row.upstream_sha,
                                      f"tools/addon/{addon_slug}.sh"))
        if install_resp.status_code != 200:
            meta = parse_ct_script(ct_resp.text)
            _apply_script_presentation(row, meta)
            row.installable = False
            row.unsupported_reason = ("could not fetch the addon script this "
                                      "app delegates to")
            row.raw = _keep_metadata(row, {"ct_script": ct_resp.text})
            db.commit()
            return row

    meta = parse_ct_script(ct_resp.text)
    if addon_delegated:
        # ALWAYS not-installable, and deliberately NOT a call to
        # classify_install_feasibility, so this verdict cannot come to depend
        # on what the addon script happens to contain.
        #
        # The addon script is not what an install runs. `build_container`
        # installs by curling `install/<var_install>.sh` and lxc-attaching it
        # (misc/build.func:5174), that URL 404s for every app in this shape,
        # the failure is swallowed because error handling is off at that point,
        # and `bash -c ""` exits 0. Upstream's own ct script builds a
        # container, installs nothing, and reports success. The addon script is
        # referenced only from `update_script()` and never runs here.
        #
        # Running the feasibility check here would mark a silent addon script
        # installable, and the install would then file an empty container as a
        # success, which run_install's "exited 0 but no CT" guard cannot catch
        # because the CT really does exist. The fix is a real second execution
        # step that never answers a prompt on the operator's behalf, not a
        # softer verdict here.
        installable, reason = False, UNSUPPORTED_ADDON_DELEGATED
    else:
        installable, reason = classify_install_feasibility(ct_resp.text,
                                                           install_resp.text)
    _apply_script_presentation(row, meta)
    row.default_cpu = meta.get("default_cpu")
    row.default_ram_mb = meta.get("default_ram_mb")
    row.default_disk_gb = meta.get("default_disk_gb")
    row.default_os = meta.get("default_os")
    row.default_os_version = meta.get("default_os_version")
    row.installable = installable
    row.unsupported_reason = reason
    row.raw = _keep_metadata(row, {"ct_script": ct_resp.text,
                                   payload_key: install_resp.text})
    db.commit()
    return row


def _classify_one_sync(sessionmaker, slug: str) -> None:
    with sessionmaker() as db:
        ensure_classified(db, slug)


async def classify_many(sessionmaker, slugs: list[str], concurrency: int = 8) -> dict:
    """The low-priority background pass: bounded-concurrency lazy
    classification of whatever ensure_classified hasn't reached yet. Runs as
    its own job, scheduled AFTER run_discovery already returned, so a freshly
    refreshed store is usable (names, types, categories) before this starts.

    Bounded concurrency, not a `for` loop: a sequential fetch of up to ~1,168
    raw files (2 per ct/ entry) is several minutes of wall-clock time blocking
    one thread. Still `raw.githubusercontent.com` only, never api.github.com,
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


# Phase boundaries for the refresh's progress bar. Weighted by real relative
# cost, not split evenly, and emitted only where a phase genuinely ends: no
# timers, no interpolation, so a bar that sits still is a phase that is still
# working. Discovery and the metadata sync are the two heavy phases and are
# close in cost, discovery slightly ahead because it writes every row rather
# than the matched subset. Popularity is a real network fetch but a much
# smaller one (about 255 KB against the metadata sync's 1.9 MB) writing one
# integer column instead of a raw JSON snapshot, so it takes roughly a third
# of that phase. The last two phases are DB-only and near-instant, so they
# share the final 15 points instead of the half of the bar an even split would
# hand them.
PCT_DISCOVERED = 38
PCT_METADATA_SYNCED = 72
PCT_POPULARITY_SYNCED = 82
# The icon mirror is the one phase whose cost swings wildly: a cold cache
# downloads ~550 files, and every sync after that makes zero requests and
# finishes instantly. Weighted for the cold case, which is the one an operator
# is actually sitting and watching.
PCT_ICONS_SYNCED = 92
PCT_UPDATES_MARKED = 97


async def refresh_catalog(ctx: JobContext, params: dict) -> dict:
    from proxploy.services.appstore import mark_updates_available
    from proxploy.services.catalog_metadata import sync_metadata
    from proxploy.services.catalog_icons import sync_icons
    from proxploy.services.catalog_telemetry import sync_popularity

    app = ctx.backend.app
    with app.state.sessionmaker() as db:
        result = await asyncio.to_thread(run_discovery, db)
    ctx.log(f"discovered {result['total']} entries: {result['counts']}")
    ctx.log(f"pinned to upstream commit {result['upstream_sha']}")
    ctx.progress(PCT_DISCOVERED)

    # Upstream presentation metadata (names, descriptions, categories, icons):
    # services/catalog_metadata.py, PocketBase with a cold-start-only fallback
    # to the frozen frontend archive. Best-effort by design and wrapped twice
    # over: sync_metadata already turns an upstream failure into an outcome
    # dict, and this catch covers a genuine bug in it. Either way the catalog
    # stays exactly as discovery left it and the job carries on to 100 rather
    # than stalling here.
    def _sync_metadata() -> dict:
        with app.state.sessionmaker() as db:
            return sync_metadata(db)

    try:
        meta = await asyncio.to_thread(_sync_metadata)
    except Exception as e:  # noqa: BLE001 - metadata never fails a refresh
        meta = {"ok": False, "source": None, "matched": 0, "unmatched": 0,
                "states": {}, "name_matched": {}, "reason": str(e)}
    if meta["ok"]:
        # Counts, once, not per slug: an unmatched row in either direction is
        # the steady state, so naming them individually would be a wall of
        # noise describing normality. The upstream_state tally rides along
        # because a jump in "unlisted" or "variant" is the signal that upstream
        # reshaped its catalog, and it is invisible in matched/unmatched.
        states = ", ".join(f"{n} {s}" for s, n in sorted(meta.get("states", {}).items()))
        ctx.log(f"metadata synced from {meta['source']}: {meta['matched']} matched, "
                f"{meta['unmatched']} unmatched" + (f" ({states})" if states else ""))
        # Name matches ARE named individually, unlike everything else here:
        # the join is a heuristic rather than an exact one, and a wrong pair
        # must be visible to whoever reads this job's log rather than only
        # discoverable by noticing a card that describes the wrong app.
        for our_slug, up_slug in (meta.get("name_matched") or {}).items():
            ctx.log(f"matched {our_slug} to upstream record {up_slug} by name "
                    f"(no exact slug match upstream)")
    else:
        ctx.log(f"metadata sync skipped, kept the last good rows: {meta['reason']}",
                stream="stderr")
    result["metadata"] = meta
    ctx.progress(PCT_METADATA_SYNCED)

    # Install popularity: services/catalog_telemetry.py, a third host with no
    # fallback source. Deliberately run REGARDLESS of what the metadata sync
    # just did, and never conditioned on `meta["ok"]`: they are different
    # services on different hosts with different outages, and skipping the
    # popularity refresh because PocketBase happened to be down would turn one
    # service's bad day into two stale signals. Same never-fail-the-job posture
    # and the same double wrapping as the metadata phase above.
    def _sync_popularity() -> dict:
        with app.state.sessionmaker() as db:
            return sync_popularity(db)

    try:
        pop = await asyncio.to_thread(_sync_popularity)
    except Exception as e:  # noqa: BLE001 - popularity never fails a refresh
        pop = {"ok": False, "matched": 0, "unmatched": 0, "telemetry_only": 0,
               "reason": str(e)}
    if pop["ok"]:
        ctx.log(f"popularity synced: {pop['matched']} matched, "
                f"{pop['unmatched']} with no telemetry")
    else:
        ctx.log(f"popularity sync skipped, kept the last good counts: "
                f"{pop['reason']}", stream="stderr")
    result["popularity"] = pop
    ctx.progress(PCT_POPULARITY_SYNCED)

    # Icons, mirrored into data_dir/icons so the Store renders offline
    # (services/catalog_icons.py). Runs AFTER the metadata sync because it
    # consumes the icon_url that sync just wrote, and like every other phase
    # here it is best effort and double wrapped: a CDN outage leaves every
    # previously cached file in place and every uncached row falling back to
    # the upstream URL. The bar moves THROUGH this phase rather than jumping
    # over it, because on a cold cache this is the longest step of a refresh by
    # a wide margin (measured at 8.0s of an 11.0s run) and the job used to sit
    # at PCT_POPULARITY_SYNCED with nothing to say, which read as stuck.
    loop = asyncio.get_running_loop()
    # Only ever announces a number it has not announced yet. Hundreds of icons
    # into a ten point span is the same percentage over and over, and every
    # repeat is a job row write and an SSE frame that tell a reader nothing
    # they did not already have. At most one announcement per point.
    last_reported = [PCT_POPULARITY_SYNCED]

    def _report(done: int, total: int) -> None:
        # Called from the download pool's thread. ctx.progress touches the job
        # row and the SSE bus, so it is handed back to the loop rather than
        # invoked here.
        #
        # The span stops one short of PCT_ICONS_SYNCED: the phase is done when
        # the rows below have been written, not when the last download lands,
        # and that boundary belongs to the single call after this block.
        # Reporting 92 here would announce the same number twice.
        span = PCT_ICONS_SYNCED - PCT_POPULARITY_SYNCED - 1
        pct = PCT_POPULARITY_SYNCED + span * done // max(1, total)
        if pct <= last_reported[0]:
            return
        last_reported[0] = pct
        loop.call_soon_threadsafe(ctx.progress, pct)

    def _sync_icons() -> dict:
        with app.state.sessionmaker() as db:
            return sync_icons(db, app.state.settings.data_dir, on_progress=_report)

    try:
        icons = await asyncio.to_thread(_sync_icons)
    except Exception as e:  # noqa: BLE001 - icons never fail a refresh
        icons = {"ok": False, "cached": 0, "unchanged": 0, "skipped": 0,
                 "failed": 0, "requests": 0, "reason": str(e)}
    if icons["ok"]:
        ctx.log(f"icons: {icons['cached']} cached, {icons['unchanged']} unchanged, "
                f"{icons['skipped']} already current, {icons['failed']} failed "
                f"({icons['requests']} request(s))")
    else:
        ctx.log(f"icon sync skipped, kept the cached files: {icons['reason']}",
                stream="stderr")
    result["icons"] = icons
    ctx.progress(PCT_ICONS_SYNCED)

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
    ctx.progress(PCT_UPDATES_MARKED)

    # Low-priority background pass: queued, not awaited. The store is already
    # usable (names, types, categories from discovery alone) before this job
    # even starts.
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
