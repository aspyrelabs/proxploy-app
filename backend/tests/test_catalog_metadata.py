"""Upstream presentation metadata: mapping, the enforced write set, the
cold-start-only fallback, and the many normal ways a slug simply does not
match (design:
docs/superpowers/specs/2026-08-13-app-store-upstream-metadata-design.md).

Everything here is offline: the PocketBase corpus and the archived frontend
are both faked at `catalog_metadata._fetch`, and the scripts tree at
`catalog._fetch`, so no test in this file touches the network.
"""
from datetime import datetime

import httpx
import pytest

from proxploy.models import CatalogEntry
from proxploy.services import catalog_metadata as cm
from proxploy.services.catalog import ensure_classified, run_discovery
from tests.support import make_db

SHA = "d7bc6b59676456f7a8b3a20f24c3ca589d7fe2f6"

# The real record, captured live from
# /api/collections/script_scripts/records?filter=(slug='plex')&expand=categories,type
PLEX_PB = {
    "slug": "plex",
    "name": "Plex Media Server",
    "description": "Plex personal media server magically scans and organizes "
                   "your files, sorting your media intuitively and beautifully.",
    "logo": "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/plex.webp",
    "categories": ["scriptcat00013"],
    "type": "nm9bra8mzye2scg",
    "website": "https://www.plex.tv/",
    "documentation": "https://support.plex.tv/articles/",
    "port": 32400, "updateable": True, "privileged": False,
    "platforms": ["pve"], "is_deleted": False, "is_dev": False,
    "updated": "2026-06-11 14:16:43.777Z",
    # The script's own dates and tags, distinct from the record's `updated`.
    "script_created": "2024-05-02 00:00:00.000Z",
    "script_updated": "2026-06-11 00:00:00.000Z",
    "has_arm": True, "architectures": ["amd64", "arm64"],
    "expand": {
        "categories": [{"id": "scriptcat00013", "name": "Media & Streaming",
                        "icon": "play", "sort_order": 13}],
        "type": {"id": "nm9bra8mzye2scg", "type": "lxc"},
    },
}

# The same app in the archived frontend's schema: integer category ids, `ct`
# where PocketBase says `lxc`, `interface_port` where PocketBase says `port`.
PLEX_ARCHIVE = {
    "name": "Plex Media Server", "slug": "plex", "categories": [13],
    "date_created": "2024-05-02", "type": "ct", "updateable": True,
    "privileged": False, "interface_port": 32400,
    "documentation": "https://support.plex.tv/articles/",
    "website": "https://www.plex.tv/",
    "logo": "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/plex.webp",
    "description": "Plex personal media server magically scans and organizes "
                   "your files, sorting your media intuitively and beautifully.",
}

ARCHIVE_METADATA = {"categories": [
    {"name": "Proxmox & Virtualization", "id": 1, "sort_order": 1.0, "icon": "server"},
    {"name": "Media & Streaming", "id": 13, "sort_order": 13.0, "icon": "play"},
]}

REDIS_CT = '''#!/usr/bin/env bash
# Source: https://redis.io/

APP="Redis"
var_cpu="${var_cpu:-1}"
var_ram="${var_ram:-1024}"
var_disk="${var_disk:-4}"
var_os="${var_os:-debian}"
var_version="${var_version:-13}"

build_container
'''
REDIS_INSTALL = 'msg_info "Setting up Redis"\n'


def _pb_record(slug, **over):
    record = {"slug": slug, "name": slug.title(),
              "description": f"{slug} from upstream",
              "logo": f"https://cdn.example/{slug}.webp",
              "website": f"https://{slug}.example/",
              "documentation": f"https://docs.example/{slug}",
              "updated": "2026-06-11 14:16:43.777Z",
              "expand": {"categories": [{"id": "c1", "name": "Media & Streaming"}],
                         "type": {"id": "t1", "type": "lxc"}}}
    record.update(over)
    return record


def _typed(slug, upstream_type):
    """An upstream record that disagrees with our tree discovery about what
    kind of thing this slug is."""
    record = _pb_record(slug)
    record["expand"] = {**record["expand"], "type": {"id": "t2", "type": upstream_type}}
    return record


def fake_metadata_fetch(items=None, primary_status=200, archive=None,
                        archive_metadata_status=200, seen=None):
    """Stands in for catalog_metadata._fetch: the one PocketBase request, and
    the archive's metadata.json plus per-slug files."""
    archive = archive or {}

    def fake(url, **kw):
        if seen is not None:
            seen.append(url)
        if url.startswith("https://db.community-scripts.org"):
            if primary_status != 200:
                return httpx.Response(primary_status)
            return httpx.Response(200, json={
                "page": 1, "perPage": 1000, "totalItems": len(items or []),
                "totalPages": 1, "items": items or []})
        if url.endswith("/metadata.json"):
            if archive_metadata_status != 200:
                return httpx.Response(archive_metadata_status)
            return httpx.Response(200, json=ARCHIVE_METADATA)
        slug = url.rsplit("/", 1)[-1].removesuffix(".json")
        if slug in archive:
            return httpx.Response(200, json=archive[slug])
        return httpx.Response(404)
    return fake


def fake_tree_fetch(tree):
    def fake(url, **kw):
        if url.endswith("/commits/main"):
            return httpx.Response(200, json={"sha": SHA})
        if "/git/trees/" in url:
            return httpx.Response(200, json={"sha": SHA, "truncated": False,
                                             "tree": tree})
        if url.endswith(f"/{SHA}/ct/redis.sh"):
            return httpx.Response(200, text=REDIS_CT)
        if url.endswith(f"/{SHA}/install/redis-install.sh"):
            return httpx.Response(200, text=REDIS_INSTALL)
        return httpx.Response(404)
    return fake


def _seed(db, slug, entry_type="ct", **kw):
    row = CatalogEntry(slug=slug, entry_type=entry_type, **kw)
    db.add(row)
    db.commit()
    return row


# --- mapping ---------------------------------------------------------------

def test_pocketbase_record_maps_to_the_presentation_and_tag_fields():
    assert cm.map_pocketbase_record(PLEX_PB) == {
        "name": "Plex Media Server",
        "description": PLEX_PB["description"],
        "category": "Media & Streaming",
        "icon_url": "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/plex.webp",
        "website": "https://www.plex.tv/",
        "docs_url": "https://support.plex.tv/articles/",
        "script_created": datetime(2024, 5, 2, 0, 0),
        "script_updated": datetime(2026, 6, 11, 0, 0),
        "has_arm": True, "architectures": ["amd64", "arm64"],
        "updateable": True, "privileged": False, "port": 32400,
    }


def test_archive_record_maps_a_smaller_subset_through_its_own_schema():
    """The archive's integer category ids only resolve through metadata.json,
    which is the whole reason that file is fetched first. It also carries less
    than the live source does: `date_created` is its only date, its port field
    is `interface_port`, and it has no has_arm or architectures at all. The
    missing keys are OMITTED rather than mapped to None, so a cold-start
    fallback renders fewer chips instead of wrong ones."""
    categories = {c["id"]: c["name"] for c in ARCHIVE_METADATA["categories"]}

    mapped = cm.map_archive_record(PLEX_ARCHIVE, categories)

    assert mapped == {
        "name": "Plex Media Server",
        "description": PLEX_ARCHIVE["description"],
        "category": "Media & Streaming",
        "icon_url": "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/plex.webp",
        "website": "https://www.plex.tv/",
        "docs_url": "https://support.plex.tv/articles/",
        "script_created": datetime(2024, 5, 2, 0, 0),
        "updateable": True, "privileged": False, "port": 32400,
    }
    # Frozen at 2026-03-12, so it has no honest answer for "recently updated".
    assert "script_updated" not in mapped
    assert "has_arm" not in mapped and "architectures" not in mapped


def test_a_field_upstream_has_nothing_for_is_omitted_not_blanked():
    """An omitted key leaves whatever the row already had; a key mapped to ""
    would wipe a perfectly good ct-script-derived website with nothing."""
    mapped = cm.map_pocketbase_record({"slug": "x", "name": "X", "website": "",
                                       "documentation": None})

    assert "website" not in mapped and "docs_url" not in mapped


def test_upstream_timestamp_parses_to_naive_utc():
    """PocketBase stamps a space instead of the ISO "T"."""
    parsed = cm._parse_upstream_ts("2026-06-11 14:16:43.777Z")

    assert parsed is not None and parsed.tzinfo is None
    assert (parsed.year, parsed.month, parsed.day, parsed.hour) == (2026, 6, 11, 14)
    assert cm._parse_upstream_ts("not a timestamp") is None
    assert cm._parse_upstream_ts(None) is None


def test_an_upstream_false_survives_as_false_and_is_not_dropped_as_empty():
    """The mappers strip None to mean "upstream said nothing, leave the column
    alone". A boolean False is NOT nothing: "this app is not privileged" is a
    real answer, and a truthiness test here would silently turn every known
    False into an unknown."""
    mapped = cm.map_pocketbase_record(
        {"slug": "x", "has_arm": False, "updateable": False, "privileged": False})

    assert mapped["has_arm"] is False
    assert mapped["updateable"] is False
    assert mapped["privileged"] is False


def test_a_missing_or_unreadable_tag_is_omitted_rather_than_guessed():
    """Omitted, so the upsert leaves whatever the row had, rather than
    asserting a negative we cannot support. The 9 `unlisted` rows never reach
    a mapper at all and keep NULL for the same reason."""
    mapped = cm.map_pocketbase_record(
        {"slug": "x", "has_arm": "yes", "privileged": None,
         "architectures": [], "port": "8080"})

    for key in ("has_arm", "privileged", "architectures", "port"):
        assert key not in mapped, key


def test_port_and_architectures_are_read_defensively():
    """`bool` subclasses int in Python, so an unguarded port read would turn a
    JSON `true` into port 1."""
    assert cm._port(32400) == 32400
    assert cm._port(True) is None and cm._port(0) is None
    assert cm._port(70000) is None and cm._port("8080") is None
    assert cm._arch_list(["amd64", " arm64 ", "", 7]) == ["amd64", "arm64"]
    assert cm._arch_list([]) is None and cm._arch_list("amd64") is None


def test_the_script_dates_are_the_scripts_own_not_the_records(tmp_path, monkeypatch):
    """`updated` moves when someone fixes a typo in the description;
    `script_updated` moves when the script changes. "Recently updated" in the
    Store has to mean the second one, so they are stored in different
    columns."""
    db = make_db(tmp_path)
    _seed(db, "plex")
    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(items=[PLEX_PB]))

    cm.sync_metadata(db)

    row = db.query(CatalogEntry).filter_by(slug="plex").one()
    assert row.script_created == datetime(2024, 5, 2, 0, 0)
    assert row.script_updated == datetime(2026, 6, 11, 0, 0)
    # The RECORD's own stamp is a different column and a different value.
    assert row.upstream_updated_at == datetime(2026, 6, 11, 14, 16, 43, 777000)
    assert row.has_arm is True and row.privileged is False
    assert row.architectures == ["amd64", "arm64"] and row.port == 32400


def test_an_unmatched_row_keeps_null_tags_rather_than_gaining_false_ones(
        tmp_path, monkeypatch):
    """A row upstream has no record for is never handed to a mapper, so every
    tag stays NULL: unknown, not "no"."""
    db = make_db(tmp_path)
    _seed(db, "readarr")
    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(items=[PLEX_PB]))

    cm.sync_metadata(db)

    row = db.query(CatalogEntry).filter_by(slug="readarr").one()
    assert row.upstream_state == "unlisted"
    assert row.has_arm is None and row.updateable is None
    assert row.privileged is None and row.port is None
    assert row.script_created is None and row.script_updated is None


# --- the write set is enforced, not merely intended -------------------------

def test_every_mapper_output_is_a_subset_of_the_write_set():
    categories = {c["id"]: c["name"] for c in ARCHIVE_METADATA["categories"]}
    outputs = [cm.map_pocketbase_record(PLEX_PB),
               cm.map_pocketbase_record(_typed("coolify", "addon")),
               cm.map_archive_record(PLEX_ARCHIVE, categories)]

    for mapped in outputs:
        assert set(mapped) <= cm.WRITABLE_FIELDS


def test_the_write_set_widened_but_the_forbidden_columns_stayed_forbidden():
    """WRITABLE_FIELDS grew from six to thirteen when the Store gained sorting
    and tag chips. That is a deliberate widening of an upstream-owned
    presentation set; what must never widen is the other side of the line, so
    this pins it by name rather than trusting the count."""
    assert cm.WRITABLE_FIELDS == {
        "name", "description", "category", "icon_url", "website", "docs_url",
        "script_created", "script_updated",
        "has_arm", "architectures", "updateable", "privileged", "port"}
    for forbidden in ("slug", "entry_type", "script_path", "installable",
                      "unsupported_reason", "upstream_state", "popularity",
                      "metadata_source", "raw"):
        assert forbidden not in cm.WRITABLE_FIELDS, forbidden


def test_a_mapper_key_outside_the_write_set_raises_rather_than_being_dropped(tmp_path):
    """Silent dropping is the failure mode that lets someone add
    `"entry_type": ...` to a mapper, watch nothing break, and ship it."""
    db = make_db(tmp_path)
    row = _seed(db, "coolify")

    with pytest.raises(ValueError, match="entry_type"):
        cm.apply_writable_fields(row, {"name": "Coolify", "entry_type": "addon"})

    with pytest.raises(ValueError, match="installable"):
        cm.apply_writable_fields(row, {"installable": False})


def test_a_rogue_mapper_is_caught_on_the_way_out_of_the_mapper():
    """Both mappers return through the same guard the upsert uses, so a new
    field added to a mapper fails at the mapper rather than travelling one
    layer further before anyone notices."""
    def rogue(record):
        return cm._checked({"name": record.get("name"),
                            "script_path": "tools/addon/coolify.sh"})

    with pytest.raises(ValueError, match="script_path"):
        rogue(PLEX_PB)


# --- discovery keeps everything it owns ------------------------------------

DISCOVERY_OWNED = ("slug", "entry_type", "script_path", "installable",
                   "unsupported_reason", "upstream_sha", "default_cpu",
                   "default_ram_mb", "default_disk_gb", "default_os",
                   "default_os_version")


def test_discovery_fields_are_byte_identical_after_a_sync_that_disagrees(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    monkeypatch.setattr("proxploy.services.catalog._fetch",
                        fake_tree_fetch([{"path": "ct/redis.sh", "type": "blob"}]))
    run_discovery(db)
    ensure_classified(db, "redis")
    row = db.query(CatalogEntry).filter_by(slug="redis").one()
    before = {f: getattr(row, f) for f in DISCOVERY_OWNED}

    # Upstream disagrees about type and carries fields we deliberately ignore.
    upstream = _typed("redis", "addon")
    upstream.update({"port": 6379, "privileged": True, "platforms": ["pve"]})
    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(items=[upstream]))
    out = cm.sync_metadata(db)

    row = db.query(CatalogEntry).filter_by(slug="redis").one()
    assert out["ok"] and out["matched"] == 1
    assert {f: getattr(row, f) for f in DISCOVERY_OWNED} == before
    assert row.description == "redis from upstream"  # presentation did change


def test_the_five_dual_variant_slugs_stay_ct_and_stay_visible_to_the_store(tmp_path, monkeypatch):
    """coolify, runtipi, dockge, komodo and dokploy each ship BOTH
    ct/<slug>.sh and tools/addon/<slug>.sh, so PocketBase types them "addon"
    while our tree discovery correctly types them "ct". This is the test that
    stops the "let metadata set type" change: wiring entry_type to upstream
    would silently drop five installable LXC apps out of the Store."""
    five = ["coolify", "runtipi", "dockge", "komodo", "dokploy"]
    db = make_db(tmp_path)
    monkeypatch.setattr(
        "proxploy.services.catalog._fetch",
        fake_tree_fetch([{"path": f"ct/{s}.sh", "type": "blob"} for s in five]
                        + [{"path": f"tools/addon/{s}.sh", "type": "blob"} for s in five]))
    run_discovery(db)

    monkeypatch.setattr(cm, "_fetch",
                        fake_metadata_fetch(items=[_typed(s, "addon") for s in five]))
    out = cm.sync_metadata(db)

    assert out["ok"] and out["matched"] == 5
    for slug in five:
        row = db.query(CatalogEntry).filter_by(slug=slug).one()
        assert row.entry_type == "ct", slug
        assert row.description == f"{slug} from upstream", slug
    # ...and the Store's LXC-only query still returns all five.
    in_store = {r.slug for r in
                db.query(CatalogEntry).filter(CatalogEntry.entry_type == "ct").all()}
    assert set(five) <= in_store


# --- failure and fallback --------------------------------------------------

def test_primary_failure_with_a_warm_cache_is_a_no_op_that_keeps_prior_rows(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    _seed(db, "plex")
    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(items=[PLEX_PB]))
    assert cm.sync_metadata(db)["ok"]
    warm = db.query(CatalogEntry).filter_by(slug="plex").one()
    before = (warm.name, warm.description, warm.icon_url, warm.metadata_synced_at)

    seen: list[str] = []
    monkeypatch.setattr(cm, "_fetch",
                        fake_metadata_fetch(primary_status=503, seen=seen))
    out = cm.sync_metadata(db)

    assert out["ok"] is False and out["source"] is None
    assert "pocketbase unavailable" in out["reason"]
    row = db.query(CatalogEntry).filter_by(slug="plex").one()
    assert (row.name, row.description, row.icon_url, row.metadata_synced_at) == before
    # The whole point of the warm-cache check: no fallback traffic at all.
    assert not any("Frontend-Archive" in u for u in seen)


def test_the_fallback_fires_only_on_a_cold_cache_plus_a_failed_primary(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    _seed(db, "plex")
    seen: list[str] = []
    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(
        primary_status=503, archive={"plex": PLEX_ARCHIVE}, seen=seen))

    out = cm.sync_metadata(db)

    assert out["ok"] and out["source"] == "archive" and out["matched"] == 1
    row = db.query(CatalogEntry).filter_by(slug="plex").one()
    assert row.name == "Plex Media Server"
    assert row.category == "Media & Streaming"
    assert row.metadata_source == "archive"
    assert any(u.endswith("/metadata.json") for u in seen)


def test_the_fallback_only_asks_for_slugs_we_actually_discovered(tmp_path, monkeypatch):
    """The archive holds 487 per-slug files. Fetching the ones with no catalog
    row to attach to would be spent requests, since an upstream slug we never
    discovered is ignored outright."""
    db = make_db(tmp_path)
    _seed(db, "plex")
    seen: list[str] = []
    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(
        primary_status=503, archive={"plex": PLEX_ARCHIVE, "jellyfin": PLEX_ARCHIVE},
        seen=seen))

    cm.sync_metadata(db)

    assert not any(u.endswith("/jellyfin.json") for u in seen)


def test_both_sources_failing_leaves_the_rows_untouched_and_reports_why(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    _seed(db, "plex", name="Plex", category="Media & Streaming")
    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(
        primary_status=503, archive_metadata_status=500))

    out = cm.sync_metadata(db)

    assert out["ok"] is False and out["matched"] == 0
    assert "archive fallback failed" in out["reason"]
    row = db.query(CatalogEntry).filter_by(slug="plex").one()
    assert row.name == "Plex" and row.description is None
    assert row.metadata_source is None and row.metadata_synced_at is None
    # Never synced stays never synced: the cold-cache half of the guard on
    # sync_metadata. A recomputed state here would be resolved from a corpus
    # we never received.
    assert row.upstream_state is None


# --- a missing match is normal, in either direction -------------------------

def test_an_unmatched_row_keeps_its_discovery_name_and_heuristic_category(tmp_path, monkeypatch):
    """37 of our ct/ rows have no upstream record at all, mostly alpine-*
    variants plus mysql. That is the steady state, not a failure."""
    db = make_db(tmp_path)
    monkeypatch.setattr("proxploy.services.catalog._fetch", fake_tree_fetch([
        {"path": "ct/redis.sh", "type": "blob"},
        {"path": "ct/alpine-vaultwarden.sh", "type": "blob"},
    ]))
    run_discovery(db)

    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(items=[_pb_record("redis")]))
    out = cm.sync_metadata(db)

    assert out["ok"] and out["matched"] == 1 and out["unmatched"] == 1
    row = db.query(CatalogEntry).filter_by(slug="alpine-vaultwarden").one()
    assert row.name == "Alpine Vaultwarden"      # the discovery-derived name
    assert row.category == "Security"            # the catalog_categories heuristic
    assert row.description is None and row.icon_url is None
    assert row.metadata_source is None and row.metadata_synced_at is None


def test_an_upstream_slug_with_no_catalog_row_creates_nothing(tmp_path, monkeypatch):
    """Upstream carries 85 slugs we never discover. The scripts tree decides
    what exists, so metadata for something we did not discover has nothing to
    attach to."""
    db = make_db(tmp_path)
    _seed(db, "redis")
    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(
        items=[_pb_record("redis"), _pb_record("never-discovered")]))

    out = cm.sync_metadata(db)

    assert out["ok"] and out["matched"] == 1 and out["upstream_only"] == 1
    assert db.query(CatalogEntry).count() == 1
    assert db.query(CatalogEntry).filter_by(slug="never-discovered").one_or_none() is None


# --- upstream_state: what upstream's catalog says about one of our rows -----
#
# Our discovery makes one row per ct/*.sh FILE; upstream's PocketBase is the
# catalog of what THEY consider an app. These are the three ways the two
# disagree, and they are the reason 42 of our 585 store-visible ct rows used
# to render as blank cards.

def _in_store(db):
    """Exactly what the Store grid asks for, through the real route function
    rather than a hand-rolled copy of its query: the whole point of the
    variant state is which rows come back from THIS call."""
    from proxploy.api.catalog import list_catalog

    return {r["slug"] for r in list_catalog(entry_type="ct", db=db, user=None)}


def test_a_soft_deleted_record_is_delisted_and_keeps_its_presentation(tmp_path, monkeypatch):
    """5 of our rows are in this state (booklore, flatnotes, litellm, minio,
    spliit): upstream still HAS the record, flagged is_deleted. The sync used
    to drop those records, which cost us a perfectly good name, description
    and logo and left a blank card. A described, badged card is strictly
    better than a blank badged one, and the script is still in the repo so the
    row stays installable and on the grid."""
    db = make_db(tmp_path)
    _seed(db, "minio", name="Minio", installable=True)
    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(
        items=[_pb_record("redis"), _pb_record("minio", is_deleted=True)]))

    out = cm.sync_metadata(db)

    row = db.query(CatalogEntry).filter_by(slug="minio").one()
    assert row.upstream_state == "delisted"
    assert out["matched"] == 1 and out["unmatched"] == 0
    assert row.name == "Minio" and row.description == "minio from upstream"
    assert row.icon_url == "https://cdn.example/minio.webp"
    assert row.metadata_source == "pocketbase"
    assert row.installable is True and row.entry_type == "ct"
    assert _in_store(db) == {"minio"}


def test_a_slug_upstream_does_not_have_at_all_is_unlisted(tmp_path, monkeypatch):
    """9 rows: upstream dropped the app outright while the ct script stayed in
    the repo (mysql, readarr, overseerr and 6 more). Badged, not hidden."""
    db = make_db(tmp_path)
    _seed(db, "readarr", name="Readarr", installable=True)
    _seed(db, "redis")
    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(items=[_pb_record("redis")]))

    cm.sync_metadata(db)

    row = db.query(CatalogEntry).filter_by(slug="readarr").one()
    assert row.upstream_state == "unlisted"
    assert db.query(CatalogEntry).filter_by(slug="redis").one().upstream_state == "listed"
    # Still a card: the script is there and the user can still install it.
    assert row.installable is True and "readarr" in _in_store(db)


def test_a_phantom_alpine_row_is_a_variant_hidden_only_from_the_grid(tmp_path, monkeypatch):
    """Upstream models Alpine as an install METHOD of a parent app: the
    `syncthing` record carries install_methods [{type: "default"}, {type:
    "alpine"}], so ct/alpine-syncthing.sh is the implementation of that second
    method and not an app of its own. Upstream shows ONE Syncthing card.

    Hiding it is a STORE VISIBILITY decision and nothing else: the row keeps
    entry_type ct, keeps installable, keeps its script_path, and still comes
    back from the unfiltered full-catalog call."""
    db = make_db(tmp_path)
    _seed(db, "syncthing")
    _seed(db, "alpine-syncthing", installable=True,
          script_path="ct/alpine-syncthing.sh")
    monkeypatch.setattr(cm, "_fetch",
                        fake_metadata_fetch(items=[_pb_record("syncthing")]))

    out = cm.sync_metadata(db)

    row = db.query(CatalogEntry).filter_by(slug="alpine-syncthing").one()
    assert row.upstream_state == "variant"
    assert out["states"] == {"listed": 1, "variant": 1}
    assert row.entry_type == "ct" and row.installable is True
    assert row.script_path == "ct/alpine-syncthing.sh"
    assert _in_store(db) == {"syncthing"}
    # ...but the full catalog table still accounts for every discovered row.
    from proxploy.api.catalog import list_catalog
    assert {r["slug"] for r in list_catalog(db=db, user=None)} == {
        "syncthing", "alpine-syncthing"}


def test_alpine_komodo_is_a_variant_even_with_no_alpine_install_method(tmp_path, monkeypatch):
    """The edge case in the rule. `komodo` is alive upstream but has NO alpine
    install method, so upstream describes no home for this script at all. The
    rule still calls it a variant, which is the right answer for the grid:
    komodo already has a card, and a second blank "Alpine Komodo" beside it is
    exactly the duplicate this change exists to remove."""
    db = make_db(tmp_path)
    _seed(db, "komodo")
    _seed(db, "alpine-komodo")
    monkeypatch.setattr(cm, "_fetch",
                        fake_metadata_fetch(items=[_typed("komodo", "addon")]))

    cm.sync_metadata(db)

    assert db.query(CatalogEntry).filter_by(
        slug="alpine-komodo").one().upstream_state == "variant"
    assert _in_store(db) == {"komodo"}


# Upstream lists these eight as apps in their own right, with their own
# record, their own description and their own logo. Named here only as the
# fixture for the ordering assertion below; NOTHING in the implementation
# knows these names, which is the entire point (see cm.ALPINE_PREFIX).
LEGIT_ALPINE = ["alpine-borgbackup-server", "alpine-cinny", "alpine-it-tools",
                "alpine-nextcloud", "alpine-ntfy", "alpine-redlib",
                "alpine-valkey", "alpine-wakapi"]


def test_an_alpine_row_with_its_own_record_stays_listed_and_on_the_grid(tmp_path, monkeypatch):
    """The ordering that makes the variant rule safe: an own upstream record
    always wins over the alpine-<parent> rule, so these eight keep behaving
    exactly as they did, even for `alpine-ntfy`, whose parent `ntfy` is also
    listed upstream and would otherwise drag it off the grid."""
    db = make_db(tmp_path)
    for slug in LEGIT_ALPINE:
        _seed(db, slug)
    _seed(db, "ntfy")
    _seed(db, "nextcloud")
    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(
        items=[_pb_record(s) for s in LEGIT_ALPINE]
        + [_pb_record("ntfy"), _pb_record("nextcloud")]))

    out = cm.sync_metadata(db)

    for slug in LEGIT_ALPINE:
        row = db.query(CatalogEntry).filter_by(slug=slug).one()
        assert row.upstream_state == "listed", slug
    assert out["states"] == {"listed": 10}
    assert set(LEGIT_ALPINE) <= _in_store(db)


def test_our_own_synthetic_addon_slugs_are_never_marked(tmp_path, monkeypatch):
    """coolify-addon, dockge-addon, dokploy-addon, komodo-addon and
    runtipi-addon are names WE invent in dual-variant collision detection
    (services/catalog.py::_classify_path). Upstream can never hold a record
    for a slug we made up, so marking them "unlisted" would badge as retired
    five rows whose app upstream lists perfectly well under its real slug.
    They are unmatched by design and already hidden from the Store."""
    five = ["coolify", "runtipi", "dockge", "komodo", "dokploy"]
    db = make_db(tmp_path)
    for slug in five:
        _seed(db, slug)
        _seed(db, f"{slug}-addon", entry_type="addon", name=f"{slug} addon",
              installable=False)
    monkeypatch.setattr(cm, "_fetch",
                        fake_metadata_fetch(items=[_typed(s, "addon") for s in five]))

    out = cm.sync_metadata(db)

    for slug in five:
        row = db.query(CatalogEntry).filter_by(slug=f"{slug}-addon").one()
        assert row.upstream_state is None, slug
        assert row.entry_type == "addon" and row.name == f"{slug} addon", slug
        assert row.metadata_source is None, slug
        assert db.query(CatalogEntry).filter_by(
            slug=slug).one().upstream_state == "listed", slug
    assert out["states"] == {"listed": 5}


def test_a_failed_sync_leaves_every_prior_upstream_state_exactly_as_it_was(tmp_path, monkeypatch):
    """THE GUARD. State is resolved by ABSENCE from the payload, so a sync
    that recomputed it from a corpus it never actually got would mark the
    whole catalog "unlisted" and badge every card in the Store as retired,
    off a single upstream outage. Only the ok-True path may write it."""
    db = make_db(tmp_path)
    _seed(db, "syncthing")
    _seed(db, "alpine-syncthing")
    _seed(db, "minio")
    _seed(db, "readarr")
    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(
        items=[_pb_record("syncthing"), _pb_record("minio", is_deleted=True)]))
    assert cm.sync_metadata(db)["ok"]
    before = {r.slug: r.upstream_state for r in db.query(CatalogEntry).all()}
    assert before == {"syncthing": "listed", "alpine-syncthing": "variant",
                      "minio": "delisted", "readarr": "unlisted"}

    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(primary_status=503))
    out = cm.sync_metadata(db)

    assert out["ok"] is False and out["states"] == {}
    db.expire_all()
    assert {r.slug: r.upstream_state for r in db.query(CatalogEntry).all()} == before
    # And the grid is still the grid: no mass badging, no mass hiding.
    assert _in_store(db) == {"syncthing", "minio", "readarr"}


# --- provenance ------------------------------------------------------------

def test_provenance_and_the_raw_snapshot_are_written_by_the_sync(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    _seed(db, "plex")
    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(items=[PLEX_PB]))

    cm.sync_metadata(db)

    row = db.query(CatalogEntry).filter_by(slug="plex").one()
    assert row.metadata_source == "pocketbase"
    assert row.metadata_synced_at is not None
    assert row.upstream_updated_at is not None and row.upstream_updated_at.year == 2026
    assert row.raw["metadata"]["slug"] == "plex"


def test_the_metadata_snapshot_survives_a_later_classification(tmp_path, monkeypatch):
    """`raw` carries two payloads on two different schedules. Classification
    rewrites the script pair and must carry the snapshot through."""
    db = make_db(tmp_path)
    monkeypatch.setattr("proxploy.services.catalog._fetch",
                        fake_tree_fetch([{"path": "ct/redis.sh", "type": "blob"}]))
    run_discovery(db)
    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(items=[_pb_record("redis")]))
    cm.sync_metadata(db)

    ensure_classified(db, "redis")

    row = db.query(CatalogEntry).filter_by(slug="redis").one()
    assert row.raw["ct_script"] == REDIS_CT
    assert row.raw["metadata"]["slug"] == "redis"


def test_classification_does_not_take_back_a_matched_row_s_name(tmp_path, monkeypatch):
    """The ownership split: upstream owns presentation for a matched row, and
    classification runs after the metadata sync, so an unguarded `APP="..."`
    write would quietly hand the last word back to the script parse."""
    db = make_db(tmp_path)
    monkeypatch.setattr("proxploy.services.catalog._fetch",
                        fake_tree_fetch([{"path": "ct/redis.sh", "type": "blob"}]))
    run_discovery(db)
    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(
        items=[_pb_record("redis", name="Redis Stack Server")]))
    cm.sync_metadata(db)

    ensure_classified(db, "redis")

    assert db.query(CatalogEntry).filter_by(slug="redis").one().name == "Redis Stack Server"


def test_an_unmatched_row_still_gets_the_script_s_own_name(tmp_path, monkeypatch):
    """The other half of that guard: with no upstream record to defer to,
    `APP="Redis"` still beats the slug-derived fallback."""
    db = make_db(tmp_path)
    monkeypatch.setattr("proxploy.services.catalog._fetch",
                        fake_tree_fetch([{"path": "ct/redis.sh", "type": "blob"}]))
    run_discovery(db)
    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(items=[_pb_record("other")]))
    cm.sync_metadata(db)

    ensure_classified(db, "redis")

    assert db.query(CatalogEntry).filter_by(slug="redis").one().name == "Redis"


def test_a_sync_never_touches_api_github_com(tmp_path, monkeypatch):
    """The refresh's 2-call GitHub API ceiling is absolute. PocketBase and the
    archive are both other hosts, and this proves it stays that way."""
    db = make_db(tmp_path)
    _seed(db, "plex")
    seen: list[str] = []
    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(items=[PLEX_PB], seen=seen))

    cm.sync_metadata(db)

    assert seen and not any("api.github.com" in u for u in seen)


# --- fallback join on normalized name ---------------------------------------
#
# Upstream's own catalog slug sometimes differs from upstream's own script
# filename, and our discovery takes the slug from the filename. Measured over
# the real catalog this produces exactly ONE match and zero ambiguities, so
# every test below is about what happens the day that stops being true.

def test_a_row_whose_upstream_slug_differs_matches_by_name(tmp_path, monkeypatch):
    """The live case: ct/apache-airflow.sh exists and is genuinely
    installable, while the PocketBase record is slug `airflow`, name "Apache
    Airflow", alive. Exact matching missed it and the card rendered blank and
    badged as retired."""
    db = make_db(tmp_path)
    _seed(db, "apache-airflow", name="Apache Airflow", installable=True)
    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(
        items=[_pb_record("airflow", name="Apache Airflow")]))

    out = cm.sync_metadata(db)

    row = db.query(CatalogEntry).filter_by(slug="apache-airflow").one()
    assert row.upstream_state == "listed"
    assert row.description == "airflow from upstream"
    assert row.category == "Media & Streaming"
    assert out["name_matched"] == {"apache-airflow": "airflow"}
    # Recorded on the row, so a heuristic join is inspectable and not just a
    # log line that has rotated away.
    assert row.metadata_source == "pocketbase-name-match"
    # And nothing discovery owns moved.
    assert row.slug == "apache-airflow" and row.entry_type == "ct"
    assert row.installable is True


def test_an_exact_slug_match_always_beats_a_name_match(tmp_path, monkeypatch):
    """Fallback only. A row that already matched by slug is never a candidate,
    so a same-named record elsewhere in the corpus cannot displace it."""
    db = make_db(tmp_path)
    _seed(db, "redis", name="Redis")
    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(items=[
        _pb_record("redis", description="the real one"),
        _pb_record("redis-oss", name="Redis"),
    ]))

    out = cm.sync_metadata(db)

    row = db.query(CatalogEntry).filter_by(slug="redis").one()
    assert row.description == "the real one"
    assert row.metadata_source == "pocketbase"
    assert out["name_matched"] == {}


def test_an_ambiguous_name_matches_nothing_rather_than_guessing(tmp_path, monkeypatch):
    """Two upstream records normalizing to one name is not a tie to break. A
    wrong match renders one app's description, icon and website on another
    app's card, which is worse than the blank card it was fixing."""
    db = make_db(tmp_path)
    _seed(db, "apache-airflow", name="Apache Airflow")
    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(items=[
        _pb_record("airflow", name="Apache Airflow"),
        _pb_record("apache_airflow", name="apache-airflow"),
    ]))

    out = cm.sync_metadata(db)

    row = db.query(CatalogEntry).filter_by(slug="apache-airflow").one()
    assert out["name_matched"] == {}
    assert row.upstream_state == "unlisted"
    assert row.description is None and row.metadata_source is None


def test_two_of_our_rows_normalizing_alike_both_decline(tmp_path, monkeypatch):
    """The other direction of 1:1. Two rows cannot both claim one record, so
    neither does."""
    db = make_db(tmp_path)
    _seed(db, "apache-airflow", name="Apache Airflow")
    _seed(db, "apacheairflow", name="apache airflow")
    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(
        items=[_pb_record("airflow", name="Apache Airflow")]))

    out = cm.sync_metadata(db)

    assert out["name_matched"] == {}
    for slug in ("apache-airflow", "apacheairflow"):
        assert db.query(CatalogEntry).filter_by(slug=slug).one().description is None


def test_a_record_already_claimed_by_a_slug_match_is_not_a_name_candidate(
        tmp_path, monkeypatch):
    """`grafana` is claimed by our exact `grafana` row, so our differently
    slugged row cannot take it too and end up sharing one record."""
    db = make_db(tmp_path)
    _seed(db, "grafana", name="Grafana")
    _seed(db, "grafana-oss", name="Grafana")
    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(
        items=[_pb_record("grafana", name="Grafana")]))

    out = cm.sync_metadata(db)

    assert out["name_matched"] == {}
    assert db.query(CatalogEntry).filter_by(slug="grafana").one().description
    assert db.query(CatalogEntry).filter_by(
        slug="grafana-oss").one().description is None


def test_normalization_does_not_collapse_two_genuinely_distinct_apps(tmp_path,
                                                                     monkeypatch):
    """Conservative on purpose: lowercase and strip non-alphanumerics, and
    nothing else. No stemming, no edit distance, no prefix or substring
    matching, each of which turns a missing match into a wrong one."""
    assert cm.normalized_name("Apache Airflow") == "apacheairflow"
    assert cm.normalized_name("apache-airflow") == "apacheairflow"
    assert cm.normalized_name("Pi-hole") == "pihole"
    assert cm.normalized_name("") is None and cm.normalized_name(None) is None
    # Similar, and still not equal, so no match may be made between them.
    assert cm.normalized_name("Paperless") != cm.normalized_name("Paperless-ngx")
    assert cm.normalized_name("Immich") != cm.normalized_name("Immich Frame")

    db = make_db(tmp_path)
    _seed(db, "paperless", name="Paperless")
    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(
        items=[_pb_record("paperless-ngx", name="Paperless-ngx")]))

    out = cm.sync_metadata(db)

    assert out["name_matched"] == {}
    assert db.query(CatalogEntry).filter_by(
        slug="paperless").one().description is None


def test_a_name_match_still_cannot_write_anything_discovery_owns(tmp_path,
                                                                 monkeypatch):
    """The hard rule is unchanged: this decides WHICH record a row matches,
    never what may be written from it."""
    db = make_db(tmp_path)
    monkeypatch.setattr("proxploy.services.catalog._fetch",
                        fake_tree_fetch([{"path": "ct/redis.sh", "type": "blob"}]))
    run_discovery(db)
    ensure_classified(db, "redis")
    row = db.query(CatalogEntry).filter_by(slug="redis").one()
    row.name = "Apache Airflow"          # force it into the name-match path
    db.commit()
    before = {f: getattr(row, f) for f in DISCOVERY_OWNED}
    # Upstream disagrees about type, as it does for the five dual-variant
    # slugs, and reaching this row by name must not change that answer.
    upstream = _typed("airflow", "addon")
    upstream["name"] = "Apache Airflow"
    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(items=[upstream]))

    out = cm.sync_metadata(db)

    row = db.query(CatalogEntry).filter_by(slug="redis").one()
    assert out["name_matched"] == {"redis": "airflow"}
    assert {f: getattr(row, f) for f in DISCOVERY_OWNED} == before


# --- rename leftovers -------------------------------------------------------

def test_a_rename_leftover_is_superseded_and_hidden(tmp_path, monkeypatch):
    """Upstream renamed netvisor to scanopy. ct/scanopy.sh and its install
    script exist, so `scanopy` is listed and installable. The old
    ct/netvisor.sh is still in the repo with NO install script and an APP=
    line that now reads "Scanopy", so the grid showed two cards both called
    "Scanopy", one working and one blank."""
    db = make_db(tmp_path)
    _seed(db, "scanopy", name="Scanopy", installable=True)
    _seed(db, "netvisor", name="Scanopy", installable=False,
          unsupported_reason="no install script found upstream")
    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(
        items=[_pb_record("scanopy", name="Scanopy")]))

    out = cm.sync_metadata(db)

    assert db.query(CatalogEntry).filter_by(
        slug="netvisor").one().upstream_state == "superseded"
    assert db.query(CatalogEntry).filter_by(
        slug="scanopy").one().upstream_state == "listed"
    assert out["states"]["superseded"] == 1
    assert _in_store(db) == {"scanopy"}


def test_two_legitimate_rows_sharing_a_name_are_both_untouched(tmp_path, monkeypatch):
    """`valkey` and `alpine-valkey` are BOTH listed upstream and both
    legitimate. A duplicate name on the grid is not by itself evidence of
    anything, which is why the rule needs all three conditions and not just
    the collision."""
    db = make_db(tmp_path)
    _seed(db, "valkey", name="Valkey", installable=True)
    _seed(db, "alpine-valkey", name="Valkey", installable=True)
    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(items=[
        _pb_record("valkey", name="Valkey"),
        _pb_record("alpine-valkey", name="Valkey"),
    ]))

    cm.sync_metadata(db)

    for slug in ("valkey", "alpine-valkey"):
        assert db.query(CatalogEntry).filter_by(
            slug=slug).one().upstream_state == "listed", slug
    assert _in_store(db) == {"valkey", "alpine-valkey"}


def test_an_installable_leftover_is_not_hidden(tmp_path, monkeypatch):
    """The missing install script is what makes a leftover a corpse rather
    than a second way to install the same thing. Something still installable
    keeps its card and its badge."""
    db = make_db(tmp_path)
    _seed(db, "scanopy", name="Scanopy", installable=True)
    _seed(db, "netvisor", name="Scanopy", installable=True)
    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(
        items=[_pb_record("scanopy", name="Scanopy")]))

    cm.sync_metadata(db)

    assert db.query(CatalogEntry).filter_by(
        slug="netvisor").one().upstream_state == "unlisted"
    assert _in_store(db) == {"scanopy", "netvisor"}


def test_an_unclassified_leftover_is_not_hidden_on_a_guess(tmp_path, monkeypatch):
    """installable is None means "not looked at yet", not "no install
    script": classification is lazy and runs in the background. A card that is
    briefly visible beats a card that is wrongly hidden."""
    db = make_db(tmp_path)
    _seed(db, "scanopy", name="Scanopy", installable=True)
    _seed(db, "netvisor", name="Scanopy", installable=None)
    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(
        items=[_pb_record("scanopy", name="Scanopy")]))

    cm.sync_metadata(db)

    assert db.query(CatalogEntry).filter_by(
        slug="netvisor").one().upstream_state == "unlisted"


def test_the_shared_visibility_helper_hides_every_hidden_state(tmp_path, monkeypatch):
    """Task A's helper is the single definition of Store visibility, so a new
    hidden state has to be excluded everywhere at once rather than in the one
    call site whoever added it happened to remember."""
    db = make_db(tmp_path)
    _seed(db, "scanopy", name="Scanopy", installable=True)
    _seed(db, "netvisor", name="Scanopy", installable=False)
    _seed(db, "syncthing", name="Syncthing")
    _seed(db, "alpine-syncthing", name="Alpine Syncthing")
    monkeypatch.setattr(cm, "_fetch", fake_metadata_fetch(items=[
        _pb_record("scanopy", name="Scanopy"), _pb_record("syncthing")]))

    cm.sync_metadata(db)

    assert cm.HIDDEN_FROM_STORE == {"variant", "superseded"}
    hidden = {r.slug for r in db.query(CatalogEntry)
              .filter(CatalogEntry.upstream_state.in_(sorted(cm.HIDDEN_FROM_STORE)))}
    assert hidden == {"netvisor", "alpine-syncthing"}
    assert _in_store(db) == {"scanopy", "syncthing"}
