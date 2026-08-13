"""Local icon cache for the App Store, so the Store works offline.

THE GAP THIS CLOSES. The Store's metadata is cache-first: it lives in SQLite
and renders from there, so it is instant and works with no network. The icons
were not. `catalog_entries.icon_url` held upstream's URL verbatim and every
card fetched cdn.jsdelivr.net at render time, so a firewalled or air-gapped
Proxmox host rendered 556 initials tiles. Mirroring the bytes into the durable
data dir alongside the DB is what makes the second half of "instant and works
offline" true.

LICENCE, and this was checked before a byte was downloaded. 537 of the 549
store-visible icons come from github.com/selfhst/icons, which is licensed
**CC BY 4.0** (Creative Commons Attribution 4.0 International, LICENSE at the
repo root). That permits redistribution, including in modified form and
commercially, on condition of attribution, and upstream's own README documents
self-hosting the collection as a supported thing to do. Attribution is
discharged where the redistribution happens: `api/catalog.py`'s icon route
sets `Link: rel="license"` and `rel="author"` headers on every file served
from that collection.

CC BY 4.0 section 2(b)(2) is explicit that "Patent and trademark rights are
not licensed under this Public License", and every icon in the set is some
vendor's brand mark. That is not an obstacle here and it is worth writing down
why: showing a vendor's logo to identify that vendor's software is nominative
use, which is exactly what the Store already did by hot-linking. Serving the
same bytes from the operator's own node changes who transmits them, not what
they are used for. The dozen icons that come from vendor domains directly
(cinny.in, getgrav.org and friends) are the same question with the same
answer, minus the CC BY grant, and they are cached on the same reasoning.

COST. This runs on the 6-hourly catalog refresh, so a steady-state sync must
not re-download 549 files. A slug is skipped outright when its cached file
exists AND upstream's URL is unchanged AND the cache entry is younger than
REVALIDATE_AFTER, which makes the normal sync cost ZERO requests. Past that
window it revalidates with `If-None-Match`, so upstream answers 304 and sends
no body. That is what keeps a logo change from being sticky forever without
paying 549 round-trips every six hours of someone else's bandwidth.

Different host from api.github.com, so the refresh's flat 2-call GitHub API
ceiling (services/catalog.py header note) is untouched: this module must never
add an api.github.com call of any kind. cdn.jsdelivr.net and
raw.githubusercontent.com are not the GitHub API.

FAILURE POLICY, the same posture as the metadata sync and stricter in one
place. A download that fails leaves the previously cached file exactly where
it is and the row keeps pointing at it; a slug that has never been cached
falls back to the upstream URL, which is what the Store did before this module
existed. Nothing here ever deletes a good cached icon because a refetch
failed, and a total network outage is a logged no-op, not an emptied cache.
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import httpx

from proxploy.models import CatalogEntry, utcnow

logger = logging.getLogger(__name__)

# Same bound and the same reasoning as catalog_metadata's archive fan-out and
# catalog.classify_many's semaphore: a sequential walk of ~550 files is
# minutes of wall clock on one thread, and anything wider is rude to a CDN
# that is giving us this bandwidth for free.
_CONCURRENCY = 8

# How long a cached icon is trusted without asking upstream anything at all.
# The trade is explicit: shorter means fresher logos and more requests against
# someone else's CDN, longer means a rebranded app keeps its old icon for
# longer. 30 days is chosen because an app logo changing is a rare event that
# nobody is waiting on, while 549 conditional requests every 6 hours is 2,196
# a day, forever, to learn nothing.
REVALIDATE_AFTER = timedelta(days=30)

# Extensions we are willing to write to disk and serve back. An allowlist, not
# a sanitiser: whatever upstream puts in a URL path, the cached filename is
# built from our own slug plus one of these, so nothing upstream controls ever
# reaches the filesystem as a path component.
CONTENT_TYPES = {
    "webp": "image/webp",
    "png": "image/png",
    "svg": "image/svg+xml",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "ico": "image/x-icon",
    "avif": "image/avif",
}

# A logo that arrives larger than this is not a logo. Bounded so one bad URL
# cannot fill the data dir the DB lives in.
MAX_ICON_BYTES = 2 * 1024 * 1024

ICON_DIR_NAME = "icons"

# The collection behind 537 of the 549 icons, and the one with an attribution
# condition attached. Matched on host+path prefix rather than host alone so a
# future unrelated jsdelivr URL does not get someone else's credit.
SELFHST_PREFIX = "https://cdn.jsdelivr.net/gh/selfhst/icons"
SELFHST_LICENSE = "https://creativecommons.org/licenses/by/4.0/"
SELFHST_AUTHOR = "https://selfh.st/icons"


def icon_dir(data_dir: Path) -> Path:
    """`backend/data/icons`, beside proxploy.db and master.key.

    Deliberately NOT a temp dir. The entire point is surviving a reboot: an
    icon cache in /tmp would be empty exactly when an offline host needs it
    most, which is the first render after a restart.
    """
    return Path(data_dir) / ICON_DIR_NAME


def _extension(url: str) -> str | None:
    """The extension from the URL path, if it is one we serve.

    Query strings are stripped first: one real icon in the corpus is
    `avatars.githubusercontent.com/u/127616157?s=200&v=4`, which has no
    extension at all and correctly returns None.
    """
    path = url.split("?", 1)[0].split("#", 1)[0]
    ext = path.rsplit(".", 1)[-1].lower() if "." in path.rsplit("/", 1)[-1] else ""
    return ext if ext in CONTENT_TYPES else None


def cache_filename(slug: str, url: str) -> str | None:
    """`<slug>.<ext>`, or None when we cannot name a file for this URL.

    Slug-keyed rather than content-addressed, and the reason is the staleness
    requirement rather than aesthetics. Content addressing would make a
    changed logo a NEW file and leave the old one behind forever, so the cache
    would grow monotonically and need its own garbage collector. Keyed on the
    slug, a changed logo overwrites in place and the cache is the same size as
    the catalog, permanently.

    The slug is ours (it is a `ct/<slug>.sh` filename from tree discovery, not
    an upstream string) and the extension comes from a fixed allowlist, so the
    result cannot contain a path separator or a traversal sequence whatever
    upstream serves. api/catalog.py checks containment again at serve time
    anyway; this is the first of the two locks, not the only one.
    """
    ext = _extension(url)
    if ext is None or not slug or "/" in slug or "\\" in slug or slug.startswith("."):
        return None
    return f"{slug}.{ext}"


def _fetch(url: str, **kw) -> httpx.Response:
    return httpx.get(url, timeout=30.0, follow_redirects=True, **kw)


def _needs_fetch(row: CatalogEntry, path: Path, now) -> bool:
    """Whether this slug needs any network at all this sync.

    Three conditions, all of which must hold for a skip: the file is really on
    disk, upstream's URL is byte-identical to the one we cached from, and the
    cache entry is younger than REVALIDATE_AFTER. Failing the first two means
    a fresh download; failing only the third means a cheap conditional
    request. This is the whole reason a steady-state sync costs nothing.
    """
    if row.icon_cache_path is None or not path.exists():
        return True
    if row.icon_cache_source != row.icon_url:
        return True
    if row.icon_cached_at is None:
        return True
    return (now - row.icon_cached_at) > REVALIDATE_AFTER


def _write_atomically(path: Path, content: bytes) -> None:
    """Write via a temp file in the same directory, then rename.

    A half-written icon is worse than no icon: the Store would render a broken
    image where it has a perfectly good initials-tile fallback. `os.replace`
    is atomic within a filesystem, so a reader either sees the whole old file
    or the whole new one, never a partial write, even if the sync dies here.
    """
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(content)
    os.replace(tmp, path)


def _cache_one(row_data: tuple[int, str, str, str | None, str | None, str | None],
               directory: Path) -> dict:
    """Fetch and store one icon. Returns an outcome for the caller to apply.

    Takes plain data rather than a CatalogEntry, and returns plain data rather
    than mutating one, because this runs on a thread-pool worker and a
    SQLAlchemy session is not thread-safe. All DB writes happen on one thread
    in `sync_icons`.
    """
    row_id, slug, url, etag, filename, source = row_data
    out = {"id": row_id, "slug": slug, "status": "failed",
           "filename": filename, "etag": etag, "content": None}
    headers = {}
    # Revalidate ONLY when the etag we hold actually describes THIS url and
    # the file it names is really on disk. Both halves are load bearing:
    #
    # - An etag from a DIFFERENT url is not a weak validator, it is a wrong
    #   one. Upstream would compare it against the new resource, and a CDN
    #   that happens to serve the same etag for both (a versioned asset path,
    #   say) would answer 304 and we would keep serving the OLD logo forever
    #   while believing we had refreshed it. That is the exact staleness this
    #   cache is supposed to prevent, arrived at by trying to be clever.
    # - An etag for a file we no longer have would earn a 304 and leave us
    #   with nothing on disk at all.
    if etag and filename and source == url and (directory / filename).exists():
        headers["If-None-Match"] = etag
    try:
        resp = _fetch(url, headers=headers)
    except Exception as e:  # noqa: BLE001 - one unreachable icon must not
        out["reason"] = str(e)  # cost us the several hundred that did resolve
        return out
    if resp.status_code == 304:
        out["status"] = "unchanged"
        return out
    if resp.status_code != 200:
        out["reason"] = f"HTTP {resp.status_code}"
        return out
    content = resp.content
    if not content or len(content) > MAX_ICON_BYTES:
        out["reason"] = f"unusable size {len(content)}"
        return out
    name = cache_filename(slug, url)
    if name is None:
        out["reason"] = "no serveable extension in the upstream URL"
        return out
    out.update(status="fetched", filename=name, content=content,
               etag=resp.headers.get("ETag"))
    return out


def sync_icons(db, data_dir: Path) -> dict:
    """Mirror every catalog icon into the local cache. Best effort throughout.

    Returns an outcome dict for the caller to log; it does not raise. Rows are
    only ever moved FORWARD: a failure leaves `icon_cache_path` and the file it
    names exactly as they were, so the worst case for any row is that it keeps
    serving the icon it already had, or falls back to the upstream URL if it
    never had one.
    """
    directory = icon_dir(data_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {"ok": False, "cached": 0, "unchanged": 0, "skipped": 0,
                "failed": 0, "requests": 0,
                "reason": f"could not create the icon cache dir ({e})"}

    now = utcnow()
    pending: list[tuple[int, str, str, str | None, str | None]] = []
    skipped = 0
    for row in db.query(CatalogEntry).filter(CatalogEntry.icon_url.isnot(None)).all():
        name = row.icon_cache_path or cache_filename(row.slug, row.icon_url)
        if name is None:
            continue  # nothing we can name a file for; keeps the upstream URL
        if _needs_fetch(row, directory / name, now):
            pending.append((row.id, row.slug, row.icon_url,
                            row.icon_cache_etag, row.icon_cache_path,
                            row.icon_cache_source))
        else:
            skipped += 1

    if not pending:
        return {"ok": True, "cached": 0, "unchanged": 0, "skipped": skipped,
                "failed": 0, "requests": 0, "reason": None}

    with ThreadPoolExecutor(max_workers=_CONCURRENCY) as pool:
        results = list(pool.map(lambda d: _cache_one(d, directory), pending))

    cached = unchanged = failed = 0
    for result in results:
        row = db.get(CatalogEntry, result["id"])
        if row is None:
            continue
        if result["status"] == "fetched":
            try:
                _write_atomically(directory / result["filename"], result["content"])
            except OSError as e:
                logger.warning("could not write icon for %s: %s", result["slug"], e)
                failed += 1
                continue
            row.icon_cache_path = result["filename"]
            row.icon_cache_etag = result["etag"]
            row.icon_cache_source = row.icon_url
            row.icon_cached_at = now
            cached += 1
        elif result["status"] == "unchanged":
            # Upstream says our copy is current. Stamp it so the next 30 days
            # cost nothing, and touch NOTHING else.
            row.icon_cached_at = now
            row.icon_cache_source = row.icon_url
            unchanged += 1
        else:
            # THE FAILURE PATH, and it deliberately writes nothing at all. Not
            # the path, not the etag, not the timestamp: a row that had a good
            # icon keeps it, and a row that never had one keeps falling back
            # to the upstream URL. An outage must never empty this cache.
            failed += 1
    db.commit()
    return {"ok": True, "cached": cached, "unchanged": unchanged,
            "skipped": skipped, "failed": failed, "requests": len(pending),
            "reason": None}


def attribution_headers(source_url: str | None) -> dict[str, str]:
    """CC BY 4.0 attribution, discharged at the point of redistribution.

    The condition attaches to sharing the material, and serving a cached file
    from the operator's node IS sharing it, so the credit belongs on that
    response rather than only in a comment in this repo. Machine readable via
    RFC 8288 `Link` relations so it survives a UI that never renders it.
    """
    if source_url and source_url.startswith(SELFHST_PREFIX):
        return {"Link": f'<{SELFHST_LICENSE}>; rel="license", '
                        f'<{SELFHST_AUTHOR}>; rel="author"'}
    return {}
