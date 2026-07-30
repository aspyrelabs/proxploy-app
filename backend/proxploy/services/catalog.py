"""CatalogSource: fetch community-scripts/ProxmoxVE ct/+install script pairs
directly from GitHub raw content (see this plan's header note on why —
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

RAW_BASE = "https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main"

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


def _ingest_one(db, slug: str) -> None:
    ct_resp = _fetch(f"{RAW_BASE}/ct/{slug}.sh")
    if ct_resp.status_code != 200:
        raise JobFailed(f"{slug}: ct script fetch failed ({ct_resp.status_code})")
    install_resp = _fetch(f"{RAW_BASE}/install/{slug}-install.sh")
    if install_resp.status_code != 200:
        raise JobFailed(f"{slug}: install script fetch failed ({install_resp.status_code})")

    etag = (ct_resp.headers.get("ETag") or "").strip('"')
    row = db.query(CatalogEntry).filter_by(slug=slug).one_or_none()
    if row is not None and etag and row.upstream_sha == etag:
        return  # unchanged since last sync

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
    row.upstream_sha = etag or None
    row.raw = {"ct_script": ct_resp.text, "install_script": install_resp.text}
    row.synced_at = datetime.now(timezone.utc)
    db.commit()


def run_ingest(db, slugs: list[str]) -> dict:
    n = 0
    for slug in slugs:
        _ingest_one(db, slug)
        n += 1
    return {"synced": n}


async def refresh_catalog(ctx: JobContext, params: dict) -> dict:
    app = ctx.backend.app
    slugs = params.get("slugs") or list(app.state.settings.catalog_slugs)
    ctx.log(f"refreshing {len(slugs)} catalog entries")
    with app.state.sessionmaker() as db:
        result = await asyncio.to_thread(run_ingest, db, slugs)
    ctx.progress(100)
    return result


HANDLERS["catalog.refresh"] = refresh_catalog
