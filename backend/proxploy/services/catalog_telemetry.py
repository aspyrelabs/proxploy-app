"""Install popularity for the App Store, from community-scripts' own
telemetry service, cached into `catalog_entries.popularity`.

WHERE THIS COMES FROM. One GET to
telemetry.community-scripts.org/api/scripts?days=0, the same aggregate their
public dashboard renders. It is a THIRD host, distinct from both
api.github.com and db.community-scripts.org, so the refresh's flat 2-call
GitHub API ceiling (services/catalog.py header note) is untouched: like
services/catalog_metadata.py, this module must never add an api.github.com
call of any kind. The GET endpoints are not rate limited (upstream rate-limits
only the POST /telemetry ingest handler), but this is still someone else's
service, so it is one request per refresh and never a per-slug loop.

POPULARITY IS `success + failed + aborted`, AND NEVER `total`. This is the
whole point of the module and the one thing a future reader will be tempted to
"simplify" away, so:

  The telemetry backend is ClickHouse, append-only, ONE ROW PER EVENT. `total`
  is a raw count() over event rows, so it counts intermediate
  validation/configuring progress pings, not installs. success/failed/aborted
  are terminal rows only, deduped one per execution_id. Upstream found this
  exact bug and fixed it in their own dashboard (FetchDashboardData uses
  uniqExact(execution_id), and its code comment says a plain count() "inflated
  the number ~5x") but never migrated /api/scripts, which is the endpoint we
  call.

  `total` is not even usable as a scaled proxy, because the inflation is not a
  constant: the ratio spans 1.00x to 17.33x across apps. Measured sums at
  investigation time: days=30 was 619,382 total against 113,899 terminal;
  days=0 was 5,377,240 against 2,910,740.

  And the part that lands squarely on this catalog's design: ranking by
  `total` instead of by terminal events moved dokploy 312 places, dockge 280,
  komodo 272, coolify 270 and runtipi 202. Those are EXACTLY the five
  dual-variant slugs the rest of this catalog is built around
  (services/catalog.py::_classify_path,
  catalog_metadata.py::apply_writable_fields). Addon scripts emit ~1 event per
  run and full LXC installs ~7.5, so `total` demotes our five most
  design-sensitive rows by a factor that has nothing to do with popularity.

  Those rank deltas are a snapshot, not a constant, and they will not
  reproduce exactly: the aggregate moves and upstream caches it for 23h. The
  MECHANISM is what is stable, and it is independently visible in any sample.
  Spot-checked live while writing this: the five sit at a total/terminal ratio
  of 1.01x to 1.07x (they emit about one event per run) against docker 1.98x,
  redis 1.87x and plex 1.50x. Ranking by `total` therefore penalises exactly
  the rows whose scripts are cheapest in events, every time, whatever the
  day's numbers happen to be.

WHY days=0 (all time) AND NOT days=30. Coverage: 585/585 of our ct rows match
at days=0, against 570/585 at days=30. The median matched card has 967
terminal events at days=0 and 43 at days=30, and days=30 leaves 222 cards
under 30 attempts, which is noise being rendered as a number. days=0 is also
one of the three cache keys upstream pre-warms, so it is the cheap ask.

STALENESS IS REAL AND MUST BE LABELLED. Upstream caches these aggregates for
23h for any days>7, so a value can be up to a day old and moves in
discontinuous jumps rather than smoothly. That is why `popularity_synced_at`
exists as its own column: the UI says "as of", and a 6h refresh cadence that
mostly hits their warm cache stays honest about it.

FAILURE POLICY, and it is stricter than the metadata sync's. There is no
second source and no cold-start fallback, because a Store with no popularity
is a perfectly fine Store. Any failure writes NOTHING AT ALL and returns an
outcome dict; and separately, an app MISSING from the response is NO NEW
INFORMATION, never a zero. Both halves matter: telemetry is strictly opt-in
upstream (gated on DIAGNOSTICS in /usr/local/community-scripts/diagnostics),
so absence means nobody who opted in has run it, not that nobody has. Writing
through a failed fetch, or zeroing an absent app, would blank the popularity
signal on every card in the Store off one upstream outage.
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
    normalisation and no case folding. Verified: `app` IS the upstream script
    slug, only 3 alias splits exist in the whole response (UniFi OS Server,
    obsidianlivesync, pocket-id) and case-insensitive matching buys exactly 0
    extra matches. A normaliser here would be the same foot-gun
    catalog_metadata.py warns about on its own slug join, for no coverage.

    Rows are summed rather than last-wins because a repeated `app` could only
    ever be the same script's events split across rows, and adding them is the
    only reading that loses nothing. Today all 1545 rows are unique by `app`,
    so this never fires; it just cannot go wrong later.
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

    One assignment, to one column, named by POPULARITY_FIELD, and deliberately
    no other assignment to a CatalogEntry attribute anywhere in it. Popularity
    is a measurement of how often people RUN a script; it is not evidence
    about what the script IS, so this is structurally incapable of writing
    `entry_type`, `installable`, `unsupported_reason`, `upstream_state`,
    `name`, `description` or anything else discovery, the classifier or the
    metadata sync owns. `upstream_state` is worth calling out specifically: an
    app can be busy and delisted at the same time, and telemetry has no
    opinion on whether upstream still lists it.
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

    Only rows PRESENT in `counts` are touched. A row upstream has no telemetry
    for keeps whatever popularity it already had, including None: absence is
    no new information, not a zero, because telemetry is opt-in and an app
    nobody who opted in has run is indistinguishable here from an app upstream
    simply did not report this time. Zeroing it would turn one thin response
    into a store-wide reset of the signal.

    A slug in the response with no catalog row creates nothing, same rule as
    the metadata sync: the scripts tree decides what exists.
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
    previous popularity and popularity_synced_at stand exactly as they were.

    The single early return below is the entire guard, and it is load bearing
    for the same reason sync_metadata's is: popularity is applied by PRESENCE
    in the payload, so a sync that carried on with an empty or missing corpus
    would be indistinguishable from "nobody has installed anything", and one
    upstream outage would blank the signal on every card in the Store. An
    empty corpus already raises inside fetch_popularity rather than returning
    {}, and this return is the second half of the same guarantee. There is no
    fallback source to try, by design: no popularity is a fine Store.
    """
    try:
        counts = fetch_popularity()
    except Exception as error:  # noqa: BLE001 - see the module docstring
        return {"ok": False, "matched": 0, "unmatched": 0, "telemetry_only": 0,
                "reason": f"telemetry unavailable ({error}); kept the last "
                          f"good popularity"}
    return upsert_popularity(db, counts)
