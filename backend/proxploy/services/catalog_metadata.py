"""Upstream presentation metadata for the App Store: names, descriptions,
categories, icons, website and docs links, cached into `catalog_entries` and
rendered cache-first.

THE SOURCE is a PocketBase instance, db.community-scripts.org, collection
`script_scripts`. One GET returns the whole corpus, about 700 records in one
page. Cold-start fallback only: the frozen ProxmoxVE-Frontend-Archive, since
the ProxmoxVE repo itself is scripts now and carries no per-app JSON.
PocketBase is a different host from api.github.com, so the refresh's flat
2-call GitHub API ceiling (services/catalog.py header note) is untouched, and
this module must never add an api.github.com call of any kind.

OWNERSHIP. Scripts are the source of truth for what a thing IS; metadata only
for how it PRESENTS. The write set is exactly WRITABLE_FIELDS, enforced
structurally: see `apply_writable_fields`.

TWO CATALOGS, ONE JOIN. Discovery makes one row per ct/*.sh FILE; upstream's
PocketBase is the catalog of what THEY consider an app. `upstream_state`
records which kind of disagreement each row is (resolve_upstream_state), which
is what stops alpine-* variants, soft-deleted records and dropped apps from
rendering as blank cards. It is provenance, written by the sync and never by a
mapper, and it decides STORE VISIBILITY only: never a type, never an
installability.

FAILURE POLICY. Every stage is best-effort. The archive fallback fires only
when PocketBase failed AND the cache holds no metadata at all; a warm cache
plus a dead primary is a logged no-op that keeps the last good rows. A missing
slug match in either direction is normal, never an error. Nothing here raises
into the refresh job and nothing half-writes the store, and a failed sync must
not recompute `upstream_state`: see the guard on `sync_metadata`.
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httpx
from sqlalchemy import and_, or_

from proxploy.models import CatalogEntry, utcnow

logger = logging.getLogger(__name__)

# The live source. `perPage=1000` covers the whole corpus (701 records) in a
# single page on purpose: paging would turn one predictable request into an
# unbounded loop over someone else's cursor.
POCKETBASE_URL = (
    "https://db.community-scripts.org/api/collections/script_scripts/records"
    "?perPage=1000&page=1&expand=categories,type"
)

# Cold-start fallback only. The repo is ARCHIVED and frozen, so pinning the
# SHA costs nothing and buys exact reproducibility: `main` on an archived repo
# can still move if it is ever unarchived, and this content is only ever read
# when the live source is already down.
ARCHIVE_SHA = "e1e6c153e2b1c82287923df2914f33558fc3180f"
ARCHIVE_BASE = (
    "https://raw.githubusercontent.com/community-scripts/ProxmoxVE-Frontend-Archive"
    f"/{ARCHIVE_SHA}/public/json"
)

# The complete set of columns upstream metadata is allowed to write. Not a
# guideline: `apply_writable_fields` loops over exactly this frozenset and
# does nothing else, so the write set cannot widen by accident. `slug`,
# `entry_type`, `script_path`, `installable` and `unsupported_reason` are
# absent and must stay absent: see the five-slug near-miss documented on
# `apply_writable_fields`. Widening this set is a design decision to argue
# for; weakening the mechanism around it is not.
WRITABLE_FIELDS = frozenset({
    "name", "description", "category", "icon_url", "website", "docs_url",
    # upstream's own dates for the script, which the Store sorts on
    "script_created", "script_updated",
    # the card tags, all tri-state: None means unknown, never "no"
    "has_arm", "architectures", "updateable", "privileged", "port",
})

# The prefix upstream uses for an Alpine build of an app it already lists.
# `resolve_upstream_state` treats this as a RULE, not a list of today's
# variant slugs: `runtipi` was missing from the original snapshot of that set,
# and a hardcoded allowlist stops working the moment upstream adds one.
ALPINE_PREFIX = "alpine-"

# Cold-start fallback fan-out. Same reasoning as catalog.classify_many's
# semaphore: a sequential walk of several hundred raw files is minutes of
# wall-clock on one thread. Still raw.githubusercontent.com only.
_ARCHIVE_CONCURRENCY = 8


def _fetch(url: str, **kw) -> httpx.Response:
    return httpx.get(url, timeout=30.0, **kw)



def _text(value) -> str | None:
    """Non-empty strings only. An upstream empty string is "we have nothing
    here", not "blank this out": a mapper that emitted "" would wipe a
    perfectly good discovery-derived website with nothing."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _parse_upstream_ts(value) -> datetime | None:
    """PocketBase stamps "2026-06-11 14:16:43.777Z", a space instead of the
    ISO "T", which `datetime.fromisoformat` rejects on older interpreters. A
    shape we do not recognise returns None rather than raising. Stored naive
    UTC to match models.utcnow, which every DateTime column here follows."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace(" ", "T")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _flag(value) -> bool | None:
    """A real boolean or nothing. Upstream False is a genuine answer ("this
    app is not privileged") and must survive the None-stripping the mappers
    do, so this returns None ONLY for a value that is not a bool at all.
    `bool(value)` would turn a missing field into a confident "no"."""
    return value if isinstance(value, bool) else None


def _port(value) -> int | None:
    """A usable TCP port or nothing. `bool` is excluded explicitly because it
    subclasses int in Python, so a JSON `true` would otherwise become port 1."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 < value <= 65535 else None


def _arch_list(value) -> list[str] | None:
    """Upstream's architecture vocabulary, e.g. ["amd64", "arm64"], dropping
    entries that are not non-empty strings. An empty list is None: upstream
    told us nothing, rather than "this app runs on no architecture at all"."""
    if not isinstance(value, list):
        return None
    out = [v.strip() for v in value if isinstance(v, str) and v.strip()]
    return out or None


def _checked(fields: dict) -> dict:
    """A mapper key outside WRITABLE_FIELDS is a programming error and raises
    here rather than being silently dropped. Silent dropping is what lets
    someone add `"entry_type": ...` to a mapper, watch nothing break, and ship
    a write that surfaces months later as missing apps."""
    extra = sorted(set(fields) - WRITABLE_FIELDS)
    if extra:
        raise ValueError(
            f"metadata mapper produced non-writable field(s): {', '.join(extra)}; "
            f"upstream metadata may only write {sorted(WRITABLE_FIELDS)}"
        )
    return fields



def map_pocketbase_record(record: dict) -> dict:
    """One `script_scripts` record to its writable subset. Keys are omitted
    entirely when upstream has nothing, so the upsert leaves whatever the row
    already had (a ct-script-derived website, a heuristic category) alone
    instead of overwriting it with a blank."""
    expand = record.get("expand") if isinstance(record.get("expand"), dict) else {}
    category = None
    categories = expand.get("categories")
    if isinstance(categories, list) and categories and isinstance(categories[0], dict):
        category = _text(categories[0].get("name"))

    fields = {
        "name": _text(record.get("name")),
        "description": _text(record.get("description")),
        "category": category,
        "icon_url": _text(record.get("logo")),
        "website": _text(record.get("website")),
        "docs_url": _text(record.get("documentation")),
        # Upstream's dates for the SCRIPT, not the record: `updated` moves
        # when someone fixes a typo in the description, `script_updated` when
        # the script itself changes, and the Store's "recently updated" has to
        # mean the second one.
        "script_created": _parse_upstream_ts(record.get("script_created")),
        "script_updated": _parse_upstream_ts(record.get("script_updated")),
        "has_arm": _flag(record.get("has_arm")),
        "architectures": _arch_list(record.get("architectures")),
        "updateable": _flag(record.get("updateable")),
        "privileged": _flag(record.get("privileged")),
        "port": _port(record.get("port")),
    }
    return _checked({k: v for k, v in fields.items() if v is not None})


def map_archive_record(record: dict, categories_by_id: dict[int, str]) -> dict:
    """The archived frontend's `public/json/<slug>.json` to the same writable
    subset. Its schema is NOT the PocketBase one and the differences are load
    bearing: categories are integer ids resolved through metadata.json, the
    port field is `interface_port`, its only date is `date_created` (no
    script_updated, no has_arm at all), and `type` is "ct" where PocketBase
    says "lxc" (ignored, see apply_writable_fields). Mapping a SUBSET is
    correct rather than a gap: an omitted key leaves the column untouched, so
    a card renders with fewer chips instead of with wrong ones."""
    category = None
    ids = record.get("categories")
    if isinstance(ids, list):
        for cid in ids:
            name = categories_by_id.get(cid)
            if name:
                category = name
                break

    fields = {
        "name": _text(record.get("name")),
        "description": _text(record.get("description")),
        "category": category,
        "icon_url": _text(record.get("logo")),
        "website": _text(record.get("website")),
        "docs_url": _text(record.get("documentation")),
        # `date_created` is the archive's only date and it is the script's
        # creation date. Nothing maps to script_updated: the archive is FROZEN
        # at 2026-03-12, so any "recently updated" it offered would be a lie,
        # and omitting the key leaves whatever the live source last wrote.
        "script_created": _parse_upstream_ts(record.get("date_created")),
        "updateable": _flag(record.get("updateable")),
        "privileged": _flag(record.get("privileged")),
        "port": _port(record.get("interface_port")),
    }
    return _checked({k: v for k, v in fields.items() if v is not None})



def fetch_pocketbase() -> dict[str, tuple[dict, dict]]:
    """slug -> (writable payload, full upstream record). Raises on anything
    that is not a usable corpus; `sync_metadata` owns the recovery decision.

    `is_deleted` records are INGESTED, not dropped. Upstream retiring a record
    is upstream's truth, not ours: the ct/*.sh script is still in the repo and
    the row is still installable, so skipping the record only costs the name,
    description and logo it still carries and leaves a blank card.
    `resolve_upstream_state` reads `is_deleted` off the record kept here and
    marks those rows "delisted".
    """
    resp = _fetch(POCKETBASE_URL)
    if resp.status_code != 200:
        raise RuntimeError(f"pocketbase returned {resp.status_code}")
    body = resp.json() or {}
    items = body.get("items")
    if not isinstance(items, list) or not items:
        raise RuntimeError("pocketbase returned no items")

    out: dict[str, tuple[dict, dict]] = {}
    for record in items:
        if not isinstance(record, dict):
            continue
        slug = _text(record.get("slug"))
        if slug is None:
            continue
        out[slug] = (map_pocketbase_record(record), record)
    if not out:
        raise RuntimeError("pocketbase returned no usable records")
    return out


def fetch_archive(slugs: set[str]) -> dict[str, tuple[dict, dict]]:
    """The frozen archive, for the cold-start case only.

    Fetches metadata.json (the category vocabulary the per-slug integer ids
    resolve through) and then only the per-slug files for slugs we actually
    discovered, since a slug with no catalog row is ignored anyway. A per-slug
    404 is the normal "the archive never had this app" answer and is skipped
    silently. Only a failure to read metadata.json is fatal, because without
    the vocabulary every category resolves to nothing.
    """
    resp = _fetch(f"{ARCHIVE_BASE}/metadata.json")
    if resp.status_code != 200:
        raise RuntimeError(f"archive metadata.json returned {resp.status_code}")
    categories_by_id: dict[int, str] = {}
    for cat in (resp.json() or {}).get("categories", []):
        if isinstance(cat, dict) and isinstance(cat.get("id"), int):
            name = _text(cat.get("name"))
            if name:
                categories_by_id[cat["id"]] = name

    def one(slug: str) -> tuple[str, dict] | None:
        try:
            r = _fetch(f"{ARCHIVE_BASE}/{slug}.json")
        except Exception:  # noqa: BLE001 - one unreachable slug file must not
            return None    # cost us the several hundred that did come back
        if r.status_code != 200:
            return None
        try:
            record = r.json()
        except Exception:  # noqa: BLE001
            return None
        return (slug, record) if isinstance(record, dict) else None

    with ThreadPoolExecutor(max_workers=_ARCHIVE_CONCURRENCY) as pool:
        results = list(pool.map(one, sorted(slugs)))

    out: dict[str, tuple[dict, dict]] = {}
    for result in results:
        if result is None:
            continue
        slug, record = result
        out[slug] = (map_archive_record(record, categories_by_id), record)
    if not out:
        raise RuntimeError("archive returned no usable records")
    return out



def apply_writable_fields(row: CatalogEntry, fields: dict) -> None:
    """THE only place upstream metadata is allowed to touch a catalog row.

    One loop over WRITABLE_FIELDS and no other assignment to a CatalogEntry
    attribute, so it is structurally incapable of writing `slug`,
    `entry_type`, `script_path`, `installable`, `unsupported_reason` or the
    resource defaults.

    A HARD RULE, NOT A CONVENTION. Upstream types five slugs differently than
    we do, and they are exactly the dual-variant collision slugs: coolify,
    runtipi, dockge, komodo, dokploy. Each ships BOTH a standalone
    `ct/<slug>.sh` full-LXC installer and a `tools/addon/<slug>.sh` script, so
    PocketBase calls them "addon" while our tree discovery correctly calls
    them "ct". Wiring `entry_type` to metadata here would silently drop five
    genuinely LXC-typed apps out of the Store and break dual-variant collision
    detection (services/catalog.py::_classify_path).
    """
    _checked(fields)
    for field in WRITABLE_FIELDS:
        if field in fields:
            setattr(row, field, fields[field])


def _record_provenance(row: CatalogEntry, source: str, record: dict,
                       synced_at: datetime) -> None:
    """Provenance is written by the sync, never sourced from a mapper: a
    mapper that could set `metadata_source` could claim any freshness it
    liked, and these three columns plus the raw snapshot are the only way to
    tell an unmatched row (both timestamps null) from a matched one."""
    row.metadata_source = source
    row.metadata_synced_at = synced_at
    row.upstream_updated_at = _parse_upstream_ts(
        record.get("updated") or record.get("date_created"))
    # `raw` already carries the pinned ct/install script pair for classified
    # rows (services/catalog.py::ensure_classified). Merge rather than
    # replace, and re-assign rather than mutate in place, since SQLAlchemy
    # does not track in-place edits of a JSON column.
    row.raw = {**(row.raw or {}), "metadata": record}


# Every upstream_state the Store grid refuses to show. Two so far, and they
# are genuinely different phenomena rather than one with two names: a
# "variant" is a real app upstream shows under its parent's card, while a
# "superseded" row is a dead script upstream renamed out from under us.
HIDDEN_FROM_STORE = frozenset({"variant", "superseded"})


def store_visible():
    """THE single source of truth for which catalog rows the Store may show.

    Both callers depend on this and neither may re-implement it:

      - api/catalog.py::list_catalog, for `entry_type=ct` (the grid itself)
      - api/search.py, for the store group of the command palette

    It is one function because the rule was once written twice and only one
    copy got updated: the variant exclusion landed in list_catalog and never
    reached search, so the palette went on offering variant and non-ct rows
    whose `/store/<slug>` href opened Not Found.

    The explicit IS NULL arm is not redundant. In SQL, `upstream_state NOT IN
    ('variant')` is NULL for a never-synced row, and NULL is not true, so a
    bare NOT IN returns zero rows on a fresh install where nothing has synced
    yet: an empty Store and an empty search, from a predicate that looks
    correct.
    """
    return and_(
        CatalogEntry.entry_type == "ct",
        or_(CatalogEntry.upstream_state.is_(None),
            CatalogEntry.upstream_state.notin_(sorted(HIDDEN_FROM_STORE))),
    )


def resolve_upstream_state(slug: str, entry_type: str,
                           payloads: dict[str, tuple[dict, dict]],
                           alias: str | None = None) -> str | None:
    """Which answer upstream's catalog gives for this slug.

    `alias` is the upstream slug this row matched by NAME rather than by slug
    (resolve_name_matches), consulted instead of the row's own slug when
    present, so a name-matched row is "listed" like any other match.

    "listed"   a live upstream record matched. The normal case.
    "delisted" the record is there but flagged is_deleted. Upstream retired
               the app; the script is still in the repo, so the row stays
               installable and the Store badges it.
    "unlisted" no record at all and not a variant. Upstream dropped the app
               outright. Also badged.
    "variant"  an alpine-<parent> row with no record of its own whose <parent>
               IS in the payload. Upstream models Alpine as an install METHOD
               of a parent app, not as its own app, so ct/alpine-syncthing.sh
               implements the `syncthing` record's alpine method. Upstream
               shows one Syncthing card; without this we showed two and ours
               was blank. Hidden from the Store grid and ONLY from the grid:
               still a ct row, still installable, still in the full catalog
               table and still reachable by slug.

    A RULE, not a list of today's variant slugs: see ALPINE_PREFIX. Order is
    the entire subtlety. An own record always wins, which is what keeps the
    alpine-* apps upstream really does list as their own app "listed" and on
    the grid, with no name of theirs written down anywhere. A parent that is
    itself delisted still counts as present: an alpine build of a retired app
    is a variant of a badged card, not an app of its own.

    Non-ct rows that match nothing return None rather than "unlisted", and
    deliberately so: the rows that protects are OUR OWN synthetic slugs,
    coolify-addon, dockge-addon, dokploy-addon, komodo-addon and
    runtipi-addon, invented in dual-variant collision detection
    (services/catalog.py::_classify_path). Upstream can never have a record
    for a slug we made up, so "unlisted" would badge them as retired when
    upstream lists the app perfectly well under its real slug.
    """
    payload = payloads.get(alias or slug)
    if payload is not None:
        _fields, record = payload
        return "delisted" if record.get("is_deleted") else "listed"
    if entry_type != "ct":
        return None
    if slug.startswith(ALPINE_PREFIX) and slug[len(ALPINE_PREFIX):] in payloads:
        return "variant"
    return "unlisted"



def normalized_name(value) -> str | None:
    """Lowercased with every non-alphanumeric stripped. Deliberately the
    dumbest normalisation that could possibly work: no stemming, no edit
    distance, no prefix or substring matching. Every one of those turns a
    missing match into a WRONG match, which puts one app's description, icon
    and website on another app's card, and that is worse than the blank card
    it was trying to fix."""
    if not isinstance(value, str):
        return None
    out = re.sub(r"[^a-z0-9]", "", value.lower())
    return out or None


def resolve_name_matches(db, payloads: dict[str, tuple[dict, dict]]
                         ) -> dict[str, str]:
    """our slug -> upstream slug, for rows an exact slug match missed.

    Upstream's own catalog slug sometimes differs from upstream's own script
    filename, and our discovery takes the slug from the filename. Confirmed
    live: `ct/apache-airflow.sh` is genuinely installable while the PocketBase
    record is slug `airflow`, name "Apache Airflow", alive. Exact matching
    misses it, so a real app renders blank and badged as retired.

    A FALLBACK, AND ONLY A FALLBACK. It produces one match today, so the
    guardrails are about the day upstream ships two apps with similar names:

    - An exact slug match always wins, and a record already claimed by one is
      never a candidate. Nothing here can move a row that already matched.
    - It must be 1:1 in BOTH directions. If one normalized name reaches two
      upstream records, or two of our rows reach the same record, the match is
      DECLINED, not tie-broken. Ambiguity means leave the card blank and let a
      human look, not guess.
    - ct rows only: the Store is ct-only, and our synthetic *-addon slugs must
      never name-match anything.

    It changes WHICH upstream record a row matches, never what may be written.
    """
    ours = db.query(CatalogEntry.slug, CatalogEntry.name,
                    CatalogEntry.entry_type).all()
    our_slugs = {slug for (slug, _name, _type) in ours}

    # Candidates: upstream records no exact slug match has claimed. A
    # normalized name reaching more than one of them is dropped outright.
    by_name: dict[str, list[str]] = {}
    for up_slug in payloads:
        if up_slug in our_slugs:
            continue
        _fields, record = payloads[up_slug]
        key = normalized_name(record.get("name"))
        if key is not None:
            by_name.setdefault(key, []).append(up_slug)

    # And the same collapse on our side: two unmatched rows normalizing alike
    # cannot both claim one record, so neither does.
    ours_by_name: dict[str, list[str]] = {}
    for slug, name, entry_type in ours:
        if entry_type != "ct" or slug in payloads:
            continue
        key = normalized_name(name)
        if key is not None:
            ours_by_name.setdefault(key, []).append(slug)

    matches: dict[str, str] = {}
    for key, our_candidates in ours_by_name.items():
        up_candidates = by_name.get(key, ())
        if len(our_candidates) != 1 or len(up_candidates) != 1:
            continue
        matches[our_candidates[0]] = up_candidates[0]
    return matches


def resolve_superseded(rows: list[tuple[CatalogEntry, str | None]]) -> set[str]:
    """Slugs of rename leftovers: a dead script upstream renamed out from
    under us, still sitting in the repo under its old name. Confirmed live:
    upstream renamed `netvisor` to `scanopy` and left `ct/netvisor.sh` behind
    with NO install script and an `APP=` line updated to read "Scanopy", so
    the grid showed TWO cards both called "Scanopy", one working, one blank.

    THREE CONDITIONS, ALL REQUIRED, and the third alone is nowhere near
    enough: `valkey` and `alpine-valkey` share a name, are both listed
    upstream, and both must keep their cards. So a leftover must be

      1. UNMATCHED upstream ("unlisted"), because upstream deleting the record
         is the actual evidence of the rename,
      2. UNINSTALLABLE, because the missing install script is what makes it a
         corpse rather than a second way to install the same thing, and
      3. name-colliding, case-insensitively, with a ct row that IS listed.

    `installable is False` strictly, never None. Classification is lazy, so a
    freshly discovered row is None until it has been looked at, and hiding a
    card on the strength of "we have not checked yet" is a guess. A card that
    is briefly visible beats a card that is wrongly hidden.
    """
    listed_names = {row.name.lower() for row, state in rows
                    if state == "listed" and row.entry_type == "ct"
                    and isinstance(row.name, str)}
    return {row.slug for row, state in rows
            if state == "unlisted" and row.installable is False
            and isinstance(row.name, str) and row.name.lower() in listed_names}


def has_cached_metadata(db) -> bool:
    """Whether the cache is warm. This is the entire fallback trigger: a warm
    cache plus a dead primary needs no network at all, because the rows the
    Store renders from are already the last good answer."""
    return db.query(CatalogEntry.id).filter(
        CatalogEntry.metadata_synced_at.isnot(None)).first() is not None


def upsert_metadata(db, payloads: dict[str, tuple[dict, dict]],
                    source: str) -> dict:
    """Apply a fetched corpus onto existing rows. Slug is the join key, exact
    match first and always; `resolve_name_matches` is consulted only for rows
    that missed. Rows we have and upstream does not keep their
    discovery-derived name and their heuristic category so nothing goes blank,
    and end with null metadata columns, which is what marks them unmatched.
    Slugs upstream has and we do not create nothing: the scripts tree decides
    what exists.

    `upstream_state` is recomputed for EVERY row here, matched or not, because
    an unmatched row is exactly what "unlisted" and "variant" are about. Like
    metadata_source it is provenance: written by the sync, never sourced from
    a mapper, never part of WRITABLE_FIELDS, and it changes what the Store
    SHOWS and nothing else. Reached only on a successful fetch; see
    sync_metadata.

    TWO PASSES, because "superseded" asks whether some OTHER row ended up
    listed under the same name, which is only knowable once every row has a
    state.

    Counts are returned, not logged per slug: unmatched rows in both
    directions are the steady state, so per-slug logging would be a wall of
    noise describing normality. Name matches ARE logged individually, because
    a heuristic join that goes wrong must be discoverable by a human reading a
    log rather than by noticing a card describing the wrong app.
    """
    synced_at = utcnow()
    name_matches = resolve_name_matches(db, payloads)
    for our_slug, up_slug in sorted(name_matches.items()):
        logger.info("catalog metadata name-matched %r to upstream %r "
                    "(no exact slug match; 1:1 on normalized name)",
                    our_slug, up_slug)

    matched = 0
    unmatched = 0
    resolved: list[tuple[CatalogEntry, str | None]] = []
    for row in db.query(CatalogEntry).all():
        alias = name_matches.get(row.slug)
        state = resolve_upstream_state(row.slug, row.entry_type, payloads, alias)
        row.upstream_state = state
        resolved.append((row, state))
        payload = payloads.get(alias or row.slug)
        if payload is None:
            unmatched += 1
            continue
        fields, record = payload
        apply_writable_fields(row, fields)
        # A name-matched row records a DIFFERENT source, so the join that
        # produced it is inspectable on the row itself rather than only in a
        # log line that has long since rotated away.
        _record_provenance(row, f"{source}-name-match" if alias else source,
                           record, synced_at)
        matched += 1

    # Second pass: rename leftovers, which need every state resolved first.
    superseded = resolve_superseded(resolved)
    for row, _state in resolved:
        if row.slug in superseded:
            row.upstream_state = "superseded"
            logger.info("catalog metadata marked %r superseded: unmatched "
                        "upstream, not installable, and its name collides "
                        "with a listed row", row.slug)

    states: dict[str, int] = {}
    for row, _state in resolved:
        if row.upstream_state is not None:
            states[row.upstream_state] = states.get(row.upstream_state, 0) + 1

    db.commit()
    return {"ok": True, "source": source, "matched": matched,
            "unmatched": unmatched, "states": states,
            "name_matched": dict(sorted(name_matches.items())),
            "upstream_only": len(set(payloads)
                                 - {r.slug for r in db.query(CatalogEntry.slug).all()}
                                 - set(name_matches.values())),
            "reason": None}


def sync_metadata(db) -> dict:
    """Refresh every matched row's presentation fields from upstream.

    Returns an outcome dict for the caller to log; it does not raise on an
    upstream failure. `ok: False` means nothing was written and the last good
    rows are untouched, which is a usable store, not a broken one.

    THE GUARD. `upstream_state` is recomputed ONLY on the ok-True path, inside
    upsert_metadata, only after a fetch actually returned a corpus. Every
    early return below leaves each row's previous state exactly as it was.
    State is resolved by ABSENCE from the payload, so recomputing it from an
    empty or missing corpus would mark the entire catalog "unlisted" and badge
    every card in the Store as retired, off one upstream outage on a cold
    cache. An empty corpus already raises in fetch_pocketbase, and these
    returns are the second half of the same guarantee.
    """
    try:
        payloads = fetch_pocketbase()
        source = "pocketbase"
    except Exception as primary_error:  # noqa: BLE001 - see module docstring
        if has_cached_metadata(db):
            # Warm cache: the Store already renders real metadata, so the
            # cheapest correct move is to change nothing at all.
            return {"ok": False, "source": None, "matched": 0, "unmatched": 0,
                    "states": {}, "name_matched": {}, "upstream_only": 0,
                    "reason": f"pocketbase unavailable ({primary_error}); "
                              f"kept the cached metadata"}
        slugs = {s for (s,) in db.query(CatalogEntry.slug).all()}
        try:
            payloads = fetch_archive(slugs)
            source = "archive"
        except Exception as fallback_error:  # noqa: BLE001
            return {"ok": False, "source": None, "matched": 0, "unmatched": 0,
                    "states": {}, "name_matched": {}, "upstream_only": 0,
                    "reason": f"pocketbase unavailable ({primary_error}) and the "
                              f"archive fallback failed too ({fallback_error})"}
    return upsert_metadata(db, payloads, source)
