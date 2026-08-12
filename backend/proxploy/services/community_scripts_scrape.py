"""Best-effort community-scripts.org enrichment (catalog expansion plan,
decision 1: "Scripts are the source of truth. The community-scripts.org
hydration payload is best-effort enrichment only.").

This scrapes an UNDOCUMENTED Next.js internal: the React Server Component
"flight" payload embedded in `/categories` as `self.__next_f.push([1, "..."])`
chunks, not a JSON API, not versioned, not covered by any stability contract.
It 403s without a browser-shaped User-Agent (Cloudflare bot protection), has
no published rate limit, and can change shape on any upstream deploy with no
warning.

Every function here is written to that reality: ANY failure (network error,
non-200, unexpected payload shape, malformed JSON) is caught and turned into
an empty result, never an exception that could reach a caller. Nothing about
catalog discovery, classification, or install depends on this module
succeeding; a refresh that could never reach community-scripts.org must still
leave a fully usable store behind, with plain scripts-as-source-of-truth data.

Not counted against the GitHub API budget: this is a different host
(community-scripts.org, not api.github.com), so it has no bearing on the
refresh's 2-request ceiling either way.
"""
from __future__ import annotations

import json
import re

import httpx

CATEGORIES_URL = "https://community-scripts.org/categories"

# Cloudflare's bot check 403s a bot-shaped UA; this is the one thing that
# reliably gets past it, confirmed during investigation (see
# .superpowers/sdd/app-store-catalog-plan.md §4).
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml",
}

# `self.__next_f.push([1,"<escaped JSON-ish text>"])`, one chunk per call.
_FLIGHT_CHUNK_RE = re.compile(r'self\.__next_f\.push\(\[1,\s*(".*?")\]\)', re.DOTALL)


def _get(timeout: float) -> httpx.Response:
    return httpx.get(CATEGORIES_URL, headers=_HEADERS, timeout=timeout)


def _find_json_arrays(text: str) -> list[list]:
    """Every top-level `[...]` JSON array literal embedded in a decoded
    flight chunk. The RSC protocol prefixes each chunk with a stream index
    (e.g. `1c:[...]`), so this scans for `[` and tries a balanced-bracket
    slice from there rather than assuming the chunk is JSON on its own."""
    arrays: list[list] = []
    i = 0
    while True:
        start = text.find("[", i)
        if start == -1:
            break
        depth = 0
        in_str = False
        esc = False
        end = None
        for j in range(start, len(text)):
            ch = text[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    end = j
                    break
        if end is None:
            break
        candidate = text[start:end + 1]
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            parsed = None
        if isinstance(parsed, list):
            arrays.append(parsed)
        i = end + 1
    return arrays


def _extract_records(html: str) -> list[dict]:
    records: list[dict] = []
    for m in _FLIGHT_CHUNK_RE.finditer(html):
        try:
            decoded = json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(decoded, str):
            continue
        for arr in _find_json_arrays(decoded):
            for item in arr:
                if isinstance(item, dict) and "slug" in item and "type" in item:
                    records.append(item)
    return records


def _category_of(record: dict) -> str | None:
    expand = record.get("expand")
    if not isinstance(expand, dict):
        return None
    categories = expand.get("categories")
    if isinstance(categories, list) and categories:
        first = categories[0]
        if isinstance(first, dict):
            name = first.get("name")
            if isinstance(name, str) and name:
                return name
    return None


def fetch_enrichment(timeout: float = 10.0) -> dict[str, dict] | None:
    """slug -> {name, description, logo, category} for every production
    (`is_dev: false`) record the scrape could parse. Returns None, never
    raises, on ANY failure: unreachable host, non-200 (including the 403 a
    bot-shaped UA gets), timeout, or a payload shape this parser doesn't
    recognize anymore. An empty-but-non-None dict is also possible (reached
    the site, found nothing parseable) and callers should treat that the same
    as None: nothing to apply."""
    try:
        resp = _get(timeout)
        if resp.status_code != 200:
            return None
        records = _extract_records(resp.text)
    except Exception:  # noqa: BLE001 - a scrape of someone else's internals
        return None    # must never be allowed to fail a catalog refresh

    out: dict[str, dict] = {}
    for r in records:
        try:
            if r.get("is_dev"):
                continue
            slug = r.get("slug")
            if not isinstance(slug, str) or not slug:
                continue
            out[slug] = {
                "name": r.get("name") or None,
                "description": r.get("description") or None,
                "logo": r.get("logo") or None,
                "category": _category_of(r),
            }
        except Exception:  # noqa: BLE001 - one malformed record must not
            continue       # drop everything else the scrape did parse
    return out


def apply_enrichment(db, mapping: dict[str, dict] | None) -> int:
    """Best-effort layer onto existing catalog_entries rows, matched by slug.
    Never touches installable/raw/script_path: this is decoration only, the
    scripts remain the source of truth (decision 1). Returns the number of
    rows touched; 0 (not an exception) if `mapping` is falsy."""
    if not mapping:
        return 0
    from proxploy.models import CatalogEntry, utcnow

    touched = 0
    for slug, meta in mapping.items():
        row = db.query(CatalogEntry).filter_by(slug=slug).one_or_none()
        if row is None or row.entry_type != "ct":
            continue  # scrape's `type` may disagree with ours (dual-variant
                      # slugs, investigation §2); directory placement wins
        changed = False
        if meta.get("description") and row.description != meta["description"]:
            row.description = meta["description"]
            changed = True
        if meta.get("logo") and row.icon_url != meta["logo"]:
            row.icon_url = meta["logo"]
            changed = True
        if meta.get("category") and row.category != meta["category"]:
            row.category = meta["category"]
            changed = True
        if changed:
            row.scraped_at = utcnow()
            touched += 1
    if touched:
        db.commit()
    return touched
