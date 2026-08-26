"""Local icon cache for the App Store, so the Store works offline.

The metadata is cache-first (SQLite) but icons were hot-linked from
cdn.jsdelivr.net, so an air-gapped host rendered initials tiles; mirroring the
bytes into the durable data dir closes that gap.

LICENCE: 537 of 549 store-visible icons come from github.com/selfhst/icons
(CC BY 4.0), which permits redistribution with attribution. Attribution is
discharged where the redistribution happens: api/catalog.py's icon route sets
`Link: rel="license"` and `rel="author"` headers. Vendor brand marks are
nominative use, the same as the old hot-linking.

COST: a slug is skipped outright when its cached file exists AND upstream's URL
is unchanged AND the cache entry is younger than REVALIDATE_AFTER, so the
normal sync costs ZERO requests; past that it revalidates with If-None-Match
(304, no body). This module must never add an api.github.com call: the
refresh's flat 2-call GitHub API ceiling is untouched (cdn.jsdelivr.net and
raw.githubusercontent.com are not the GitHub API).

FAILURE POLICY: a failed download leaves the previously cached file and row
untouched; a never-cached slug falls back to the upstream URL. Nothing here
deletes a good cached icon because a refetch failed, and a total network
outage is a logged no-op, not an emptied cache.
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
# Shorter means fresher logos and more CDN requests; longer means a rebranded
# app keeps its old icon. 30 days: a logo change is a rare event nobody is
# waiting on, while 549 conditional requests every 6 hours is 2,196 a day.
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

        Slug-keyed rather than content-addressed so a changed logo overwrites in
        place and the cache never grows (content addressing would orphan the old
        file). The slug is ours (a `ct/<slug>.sh` filename, not an upstream string)
        and the extension comes from a fixed allowlist, so the result cannot
        contain a path separator or a traversal sequence whatever upstream serves.
        api/catalog.py re-checks containment at serve time anyway.
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
    # Revalidate ONLY when the etag we hold actually describes THIS url and the
    # file it names is really on disk. Both halves are load bearing:
    # 
    # - An etag from a DIFFERENT url could get a 304 and leave us serving the OLD
    # logo forever while believing we had refreshed it.
    # - An etag for a file we no longer have would earn a 304 and leave us with
    # nothing on disk at all.
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


def sync_icons(db, data_dir: Path, on_progress=None) -> dict:
    """Mirror every catalog icon into the local cache. Best effort throughout.

        Returns an outcome dict for the caller to log; it does not raise. Rows are
        only ever moved FORWARD: a failure leaves `icon_cache_path` and the file it
        names exactly as they were, so the worst case for any row is that it keeps
        serving the icon it already had, or falls back to the upstream URL if it
        never had one.

        `on_progress(done, total)` is called from the POOL's thread, so a caller
        that touches the event loop has to marshal it itself.
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

    total = len(pending)
    done = 0
    results = []
    with ThreadPoolExecutor(max_workers=_CONCURRENCY) as pool:
        # imap-style consumption rather than pool.map's list(), so a count can
        # be reported as each one lands instead of only when all of them have.
        for result in pool.map(lambda d: _cache_one(d, directory), pending):
            results.append(result)
            done += 1
            if on_progress is not None:
                on_progress(done, total)

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


def served_icon_url(entry: CatalogEntry | None) -> str | None:
    """The URL an icon is SERVED at: ours when a local copy exists, upstream's
        when it does not, None when there is nothing to show.

        `icon_url` on the row always holds upstream's URL (the metadata sync owns
        that column, this module owns the mirror), so which of the two a caller
        should hand the browser is decided here, once.

        None covers both honest absences: no entry at all and an entry upstream
        has no logo for; both fall back to the initials tile, not an error.
        """
    if entry is None:
        return None
    return (f"/api/v1/catalog/{entry.slug}/icon" if entry.icon_cache_path
            else entry.icon_url)


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
