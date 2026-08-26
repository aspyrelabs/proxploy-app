"""Install popularity for the App Store, from community-scripts' own
telemetry service, cached into `catalog_entries.popularity`.

One GET to telemetry.community-scripts.org/api/scripts?days=0 (all time, not
days=30: better row coverage and a pre-warmed upstream cache). This is a THIRD
host, so the module must never add an api.github.com call, and it is one
request per refresh, never a per-slug loop.

POPULARITY IS `success + failed + aborted`, NEVER `total`. `total` is a raw
count() over append-only, one-row-per-event telemetry, so it counts
intermediate progress pings, not installs; the terminal outcomes are deduped
one per execution_id. Upstream fixed this in their own dashboard but never
migrated /api/scripts (what we call), and the inflation is not constant
(1.00x to 17.33x across apps), so `total` is unusable even as a proxy.

Upstream caches these aggregates for 23h, so staleness is real; that is why
`popularity_synced_at` exists and the UI says "as of".

FAILURE POLICY: no second source and no cold-start fallback (a Store with no
popularity is a fine Store). Any failure writes NOTHING and returns an outcome
dict; an app MISSING from the response is NO NEW INFORMATION, never a zero;
telemetry is opt-in upstream.
"""
from __future__ import annotations

from datetime import datetime

import httpx

from proxploy.models import CatalogEntry, utcnow

# days=0 is all time. See the module docstring for why not days=30.
TELEMETRY_URL = "https://telemetry.community-scripts.org/api/scripts?days=0"

# The three TERMINAL outcomes, one deduped row per execution_id. Deliberately
# not `total` (see the module docstring) and deliberately not `installing`,
# which is an in-flight run that has not resolved into any of these three yet.
TERMINAL_OUTCOMES = ("success", "failed", "aborted")

# The one column telemetry may write, by name, so `apply_popularity` cannot
# widen into a second metadata path. Same structural enforcement as
# catalog_metadata.WRITABLE_FIELDS, for the same reason.
POPULARITY_FIELD = "popularity"


def _fetch(url: str, **kw) -> httpx.Response:
    return httpx.get(url, timeout=30.0, **kw)


def terminal_events(record: dict) -> int | None:
    """success + failed + aborted for one telemetry row, or None if the row
    carries none of them in a shape we can trust.

    None rather than 0 on purpose, all the way through: a row we cannot read
    is a row we know nothing about, and 0 would be a claim that nobody has
    ever run it. `bool` is excluded explicitly because it subclasses `int` in
    Python, so a JSON `true` would otherwise silently count as 1 install.
    """
    total = 0
    found = False
    for key in TERMINAL_OUTCOMES:
        value = record.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            continue
        total += value
        found = True
    return total if found else None


def fetch_popularity() -> dict[str, int]:
    """slug -> terminal event count. Raises on anything that is not a usable
    corpus; `sync_popularity` owns the recovery decision, not this function.

    The join key is the `app` field against our `slug`, EXACT match, no
    normalisation and no case folding (a normaliser would be the same foot-gun
    catalog_metadata.py warns about, for no coverage).

    Rows are summed rather than last-wins: a repeated `app` can only be the same
    script's events split across rows, and adding them is the only reading that
    loses nothing.
    """
    resp = _fetch(TELEMETRY_URL)
    if resp.status_code != 200:
        raise RuntimeError(f"telemetry returned {resp.status_code}")
    body = resp.json() or {}
    scripts = body.get("top_scripts")
    if not isinstance(scripts, list) or not scripts:
        raise RuntimeError("telemetry returned no top_scripts")

    counts: dict[str, int] = {}
    for record in scripts:
        if not isinstance(record, dict):
            continue
        slug = record.get("app")
        if not isinstance(slug, str) or not slug.strip():
            continue
        events = terminal_events(record)
        if events is None:
            continue
        counts[slug.strip()] = counts.get(slug.strip(), 0) + events
    if not counts:
        raise RuntimeError("telemetry returned no usable rows")
    return counts


def apply_popularity(row: CatalogEntry, count: int) -> None:
    """THE only place telemetry is allowed to touch a catalog row's data.

    One assignment, to one column, named by POPULARITY_FIELD, and no other
    assignment to a CatalogEntry attribute. Popularity measures how often people
    RUN a script; it is not evidence about what the script IS, so this cannot
    write fields discovery, the classifier or the metadata sync owns.
    `upstream_state` specifically: an app can be busy and delisted at the same
    time, and telemetry has no opinion on whether upstream still lists it.
    """
    setattr(row, POPULARITY_FIELD, count)


def _record_provenance(row: CatalogEntry, synced_at: datetime) -> None:
    """Written by the sync, never derived from the response, exactly as
    catalog_metadata does with metadata_synced_at. Upstream caches these
    aggregates for 23h, so a bare number with no "as of" beside it would
    present a value that can be a full day old as if it were live."""
    row.popularity_synced_at = synced_at


def upsert_popularity(db, counts: dict[str, int]) -> dict:
    """Apply a fetched corpus onto existing rows, joined on slug alone.

    Only rows PRESENT in `counts` are touched. A row with no upstream telemetry
    keeps whatever popularity it already had, including None: absence is no new
    information, not a zero (telemetry is opt-in), and zeroing it would turn one
    thin response into a store-wide reset.

    A slug in the response with no catalog row creates nothing, same rule as the
    metadata sync: the scripts tree decides what exists.
    """
    synced_at = utcnow()
    matched = 0
    for row in db.query(CatalogEntry).all():
        count = counts.get(row.slug)
        if count is None:
            continue
        apply_popularity(row, count)
        _record_provenance(row, synced_at)
        matched += 1
    db.commit()
    return {"ok": True, "matched": matched,
            "unmatched": db.query(CatalogEntry).count() - matched,
            "telemetry_only": len(set(counts) - {s for (s,) in
                                                 db.query(CatalogEntry.slug).all()}),
            "reason": None}


def sync_popularity(db) -> dict:
    """Refresh every matched row's install count from upstream telemetry.

    Returns an outcome dict for the caller to log; it does not raise on an
    upstream failure. `ok: False` means NOTHING was written and every row's
    previous popularity and popularity_synced_at stand as they were.

    The single early return below is the entire guard, and it is load bearing:
    popularity is applied by PRESENCE in the payload, so carrying on with an
    empty corpus would be indistinguishable from "nobody has installed anything"
    and one outage would blank every card's signal. No fallback by design: no
    popularity is a fine Store.
    """
    try:
        counts = fetch_popularity()
    except Exception as error:  # noqa: BLE001 - see the module docstring
        return {"ok": False, "matched": 0, "unmatched": 0, "telemetry_only": 0,
                "reason": f"telemetry unavailable ({error}); kept the last "
                          f"good popularity"}
    return upsert_popularity(db, counts)
