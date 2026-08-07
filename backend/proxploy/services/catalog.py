"""CatalogSource: fetch community-scripts/ProxmoxVE ct/+install script pairs
directly from GitHub raw content (see this plan's header note on why, 
there is no public bulk metadata API), parse resource defaults, classify
feasibility, upsert into `catalog_entries`."""
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

    Single definition on purpose: `_ingest_one` classifies/pins the content at
    this URL and `services/appstore.py::run_install` executes the content at
    this URL, and "pinned" only means anything if both resolve to the exact
    same bytes.
    """
    return f"{RAW_BASE}/{sha}/{path}"


def head_sha() -> str:
    """The repo's current HEAD commit SHA, one unauthenticated GitHub API
    call per refresh job (not per slug; the rate limit is 60/hr/IP)."""
    resp = _fetch(HEAD_COMMIT_API)
    if resp.status_code != 200:
        raise JobFailed(f"upstream HEAD commit lookup failed ({resp.status_code})")
    sha = (resp.json() or {}).get("sha")
    if not sha:
        raise JobFailed("upstream HEAD commit lookup returned no sha")
    return sha


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


def _ingest_one(db, slug: str, sha: str) -> None:
    row = db.query(CatalogEntry).filter_by(slug=slug).one_or_none()
    if row is not None and row.upstream_sha == sha:
        return  # nothing changed upstream since last sync

    # Fetched by commit SHA, not by `main`: the content classified and pinned
    # here must be byte-identical to what run_install later executes.
    ct_resp = _fetch(raw_url(sha, f"ct/{slug}.sh"))
    if ct_resp.status_code != 200:
        raise JobFailed(f"{slug}: ct script fetch failed ({ct_resp.status_code})")
    install_resp = _fetch(raw_url(sha, f"install/{slug}-install.sh"))
    if install_resp.status_code != 200:
        raise JobFailed(f"{slug}: install script fetch failed ({install_resp.status_code})")

    meta = parse_ct_script(ct_resp.text)
    installable, reason = classify_install_feasibility(ct_resp.text, install_resp.text)

    if row is None:
        row = CatalogEntry(slug=slug)
        db.add(row)
    row.name = meta.get("name", slug)
    row.category = category_for(slug)
    row.website = meta.get("website")
    row.script_path = f"ct/{slug}.sh"
    row.default_cpu = meta.get("default_cpu")
    row.default_ram_mb = meta.get("default_ram_mb")
    row.default_disk_gb = meta.get("default_disk_gb")
    row.default_os = meta.get("default_os")
    row.default_os_version = meta.get("default_os_version")
    row.installable = installable
    row.unsupported_reason = reason
    row.upstream_sha = sha
    row.raw = {"ct_script": ct_resp.text, "install_script": install_resp.text}
    row.synced_at = datetime.now(timezone.utc)
    db.commit()


def run_ingest(db, slugs: list[str]) -> dict:
    """One HEAD-commit lookup, then one slug at a time. A single bad slug
    (404, network hiccup) is recorded and skipped; it must not abort the
    other 23, which is what an escaping JobFailed used to do."""
    sha = head_sha()
    synced, failed = 0, []
    for slug in slugs:
        try:
            _ingest_one(db, slug, sha)
        except Exception as e:  # noqa: BLE001  (one bad slug can't kill the batch)
            db.rollback()
            failed.append({"slug": slug, "reason": str(e)})
            continue
        synced += 1
    return {"synced": synced, "failed": failed, "upstream_sha": sha}


async def refresh_catalog(ctx: JobContext, params: dict) -> dict:
    from proxploy.services.appstore import mark_updates_available

    app = ctx.backend.app
    slugs = params.get("slugs") or list(app.state.settings.catalog_slugs)
    ctx.log(f"refreshing {len(slugs)} catalog entries")
    with app.state.sessionmaker() as db:
        result = await asyncio.to_thread(run_ingest, db, slugs)
    ctx.log(f"pinned to upstream commit {result['upstream_sha']}")
    # ctx.log only runs on the event loop (every other handler does the same),
    # so per-slug failures are narrated here rather than from inside the thread.
    for f in result["failed"]:
        ctx.log(f"{f['slug']}: {f['reason']}", stream="stderr")
    ctx.log(f"synced {result['synced']}, failed {len(result['failed'])}")

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
    ctx.progress(100)
    return result


HANDLERS["catalog.refresh"] = refresh_catalog
