"""Catalog discovery + lazy classification (catalog expansion plan,
.superpowers/sdd/app-store-catalog-plan.md). Replaces the old eager
per-slug `run_ingest` this module used to test: discovery now populates the
catalog from the repo's own directory layout in 2 flat api.github.com calls,
and a ct/ entry's script pair is fetched lazily by `ensure_classified`, on
card-open or install-attempt, never during discovery."""
import httpx

from proxploy.models import CatalogEntry
from proxploy.services.catalog import (
    discover_tree, ensure_classified, parse_ct_script, run_discovery,
)
from tests.support import make_db

SHA = "d7bc6b59676456f7a8b3a20f24c3ca589d7fe2f6"

REDIS_CT = '''#!/usr/bin/env bash
source <(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/misc/build.func)
# Source: https://redis.io/

APP="Redis"
var_tags="${var_tags:-database}"
var_cpu="${var_cpu:-1}"
var_ram="${var_ram:-1024}"
var_disk="${var_disk:-4}"
var_os="${var_os:-debian}"
var_version="${var_version:-13}"

start
build_container
description
'''
REDIS_INSTALL = 'msg_info "Setting up Redis"\n$STD apt install -y redis\n'

# A fixture tree exercising all five real types, plus the two buckets that
# must be excluded entirely (ct/headers/ banners, tools/copy-data/), plus one
# of the four dual-variant slugs (investigation §2: ct/dockge.sh AND
# tools/addon/dockge.sh both exist upstream).
FIXTURE_TREE = {
    "sha": SHA,
    "truncated": False,
    "tree": [
        {"path": "ct/redis.sh", "type": "blob"},
        {"path": "ct/dockge.sh", "type": "blob"},
        {"path": "ct/headers/redis", "type": "blob"},
        {"path": "vm/haos.sh", "type": "blob"},
        {"path": "tools/pve/post-pve-install.sh", "type": "blob"},
        {"path": "tools/addon/dockge.sh", "type": "blob"},
        {"path": "tools/addon/portainer.sh", "type": "blob"},
        {"path": "tools/copy-data/home-assistant-container-copy-data.sh", "type": "blob"},
        {"path": "turnkey/turnkey.sh", "type": "blob"},
        {"path": "misc/build.func", "type": "blob"},  # framework file, not an entry
        {"path": "ct", "type": "tree"},  # a directory node, not a blob
    ],
}


def _fake_get(sha=SHA, seen=None, tree=None):
    """Stands in for catalog._fetch: the two flat api.github.com calls
    (head commit + tree listing) plus per-entry raw.githubusercontent.com
    fetches, lazy and on demand only."""
    def fake_get(url, **kw):
        if seen is not None:
            seen.append(url)
        if url.endswith("/commits/main"):
            return httpx.Response(200, json={"sha": sha})
        if "/git/trees/" in url:
            return httpx.Response(200, json=tree if tree is not None else FIXTURE_TREE)
        if url.endswith(f"/{sha}/ct/redis.sh"):
            return httpx.Response(200, text=REDIS_CT)
        if url.endswith(f"/{sha}/install/redis-install.sh"):
            return httpx.Response(200, text=REDIS_INSTALL)
        return httpx.Response(404)
    return fake_get


def test_parse_ct_script_extracts_metadata():
    meta = parse_ct_script(REDIS_CT)
    assert meta == {
        "name": "Redis", "website": "https://redis.io/",
        "default_cpu": 1, "default_ram_mb": 1024, "default_disk_gb": 4,
        "default_os": "debian", "default_os_version": "13",
    }


# --- discovery: finds all five types, tags each correctly ------------------

def test_discover_tree_finds_all_five_types_and_tags_each_correctly(monkeypatch):
    monkeypatch.setattr("proxploy.services.catalog._fetch", _fake_get())

    entries = discover_tree(SHA)
    by_slug = {e["slug"]: e for e in entries}

    assert by_slug["redis"] == {"slug": "redis", "entry_type": "ct", "script_path": "ct/redis.sh"}
    assert by_slug["dockge"]["entry_type"] == "ct"
    assert by_slug["haos"] == {"slug": "haos", "entry_type": "vm", "script_path": "vm/haos.sh"}
    assert by_slug["post-pve-install"]["entry_type"] == "pve"
    assert by_slug["portainer"]["entry_type"] == "addon"
    assert by_slug["turnkey"]["entry_type"] == "turnkey"


def test_discover_tree_excludes_headers_copy_data_and_non_blob_nodes(monkeypatch):
    monkeypatch.setattr("proxploy.services.catalog._fetch", _fake_get())

    entries = discover_tree(SHA)
    slugs = {e["slug"] for e in entries}

    # ct/headers/redis is a banner, not a script
    assert "redis" in slugs  # the real ct/redis.sh, not the header, still present
    assert not any(e["script_path"].startswith("ct/headers/") for e in entries)
    # tools/copy-data doesn't classify cleanly (investigation §3): excluded
    assert not any("copy-data" in e["script_path"] for e in entries)
    # a directory node ("ct", type=tree) and an unrelated file (misc/build.func)
    assert not any(e["script_path"] == "ct" for e in entries)
    assert not any(e["script_path"] == "misc/build.func" for e in entries)


def test_discover_tree_refuses_a_truncated_response(monkeypatch):
    truncated = {**FIXTURE_TREE, "truncated": True}
    monkeypatch.setattr("proxploy.services.catalog._fetch",
                        _fake_get(tree=truncated))

    import pytest
    from proxploy.jobs import JobFailed
    with pytest.raises(JobFailed):
        discover_tree(SHA)


# --- dual-variant slugs: ct/ wins the plain slug, addon is tagged, excluded -

def test_dual_variant_slug_surfaces_the_standalone_ct_installer(tmp_path, monkeypatch):
    """dockge, dokploy, komodo, coolify each have BOTH a standalone ct/
    installer and a tools/addon/ variant under the same upstream slug
    (investigation §2). Decision 4: the Store shows only the standalone
    installer; the addon row stays in the catalog table, tagged by type,
    never installable, and must not collide with the ct/ row's slug."""
    db = make_db(tmp_path)
    monkeypatch.setattr("proxploy.services.catalog._fetch", _fake_get())

    run_discovery(db)

    ct_row = db.query(CatalogEntry).filter_by(slug="dockge").one()
    assert ct_row.entry_type == "ct"
    assert ct_row.installable is None  # not yet classified, but eligible

    addon_row = db.query(CatalogEntry).filter_by(slug="dockge-addon").one()
    assert addon_row.entry_type == "addon"
    assert addon_row.installable is False
    assert "existing container" in addon_row.unsupported_reason


def test_a_ct_addon_collision_is_detected_dynamically_not_from_a_fixed_list(tmp_path, monkeypatch):
    """This plan's own live verification found `runtipi` colliding the same
    way as the four the investigation named, confirming the corpus grows: the
    fix must generalize to ANY ct/+addon slug collision the tree contains,
    not just a hardcoded set of four names."""
    db = make_db(tmp_path)
    tree = {
        "sha": SHA, "truncated": False,
        "tree": [
            {"path": "ct/runtipi.sh", "type": "blob"},
            {"path": "tools/addon/runtipi.sh", "type": "blob"},
        ],
    }
    monkeypatch.setattr("proxploy.services.catalog._fetch", _fake_get(tree=tree))

    run_discovery(db)

    ct_row = db.query(CatalogEntry).filter_by(slug="runtipi").one()
    assert ct_row.entry_type == "ct"
    addon_row = db.query(CatalogEntry).filter_by(slug="runtipi-addon").one()
    assert addon_row.entry_type == "addon" and addon_row.installable is False


def test_only_ct_entries_are_ever_installable(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    monkeypatch.setattr("proxploy.services.catalog._fetch", _fake_get())

    run_discovery(db)

    for row in db.query(CatalogEntry).all():
        if row.entry_type != "ct":
            assert row.installable is False, row.slug


# --- the 2-request ceiling: flat, not proportional to catalog size ---------

def test_a_full_refresh_makes_exactly_two_api_github_com_calls(tmp_path, monkeypatch):
    """Hard invariant: the refresh's api.github.com call count must be
    constant, never scaling with catalog size. A fixture tree with several
    dozen entries proves the same 2-call cost as one with a handful."""
    db = make_db(tmp_path)
    big_tree = {
        "sha": SHA, "truncated": False,
        "tree": [{"path": f"ct/app-{i}.sh", "type": "blob"} for i in range(50)]
                + FIXTURE_TREE["tree"],
    }
    seen: list[str] = []
    monkeypatch.setattr("proxploy.services.catalog._fetch",
                        _fake_get(seen=seen, tree=big_tree))

    result = run_discovery(db)

    api_calls = [u for u in seen if u.startswith("https://api.github.com/")]
    assert len(api_calls) == 2
    assert result["total"] > 50  # the fixture really did carry that many entries
    assert db.query(CatalogEntry).count() == result["total"]


def test_the_api_call_count_does_not_scale_with_entry_count(tmp_path, monkeypatch):
    """The same assertion, run twice at two different catalog sizes, proving
    the count is flat rather than merely "2 in this one sample"."""
    small_tree = {"sha": SHA, "truncated": False,
                 "tree": [{"path": "ct/redis.sh", "type": "blob"}]}
    large_tree = {
        "sha": SHA, "truncated": False,
        "tree": [{"path": f"ct/app-{i}.sh", "type": "blob"} for i in range(200)],
    }

    counts = []
    for tree in (small_tree, large_tree):
        db = make_db(tmp_path)
        seen: list[str] = []
        monkeypatch.setattr("proxploy.services.catalog._fetch",
                            _fake_get(seen=seen, tree=tree))
        run_discovery(db)
        counts.append(len([u for u in seen if u.startswith("https://api.github.com/")]))

    assert counts == [2, 2]


# --- classification is on-demand, never during discovery -------------------

def test_discovery_never_calls_the_feasibility_classifier(tmp_path, monkeypatch):
    """Decision 2: run_discovery only ever writes skeleton rows. If it ever
    starts calling the classifier, that's the eager-per-slug-fetch regression
    this plan replaces; fail loudly rather than let it slip back in."""
    db = make_db(tmp_path)
    monkeypatch.setattr("proxploy.services.catalog._fetch", _fake_get())

    def _boom(*a, **kw):
        raise AssertionError("classify_install_feasibility must not run during discovery")
    monkeypatch.setattr("proxploy.services.catalog.classify_install_feasibility", _boom)

    run_discovery(db)  # must not raise

    row = db.query(CatalogEntry).filter_by(slug="redis").one()
    assert row.installable is None


def test_ensure_classified_runs_the_classifier_on_demand(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    seen: list[str] = []
    monkeypatch.setattr("proxploy.services.catalog._fetch", _fake_get(seen=seen))
    run_discovery(db)
    seen.clear()

    row = ensure_classified(db, "redis")

    assert row.installable is True
    assert row.unsupported_reason is None
    assert row.default_cpu == 1 and row.default_ram_mb == 1024
    assert row.raw == {"ct_script": REDIS_CT, "install_script": REDIS_INSTALL}
    # ...and it fetched from raw.githubusercontent.com, by commit sha, never main
    assert all("api.github.com" not in u for u in seen)
    assert not any("/ProxmoxVE/main/" in u for u in seen)


def test_ensure_classified_is_idempotent_once_already_classified(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    seen: list[str] = []
    monkeypatch.setattr("proxploy.services.catalog._fetch", _fake_get(seen=seen))
    run_discovery(db)
    ensure_classified(db, "redis")
    seen.clear()

    ensure_classified(db, "redis")  # already classified at this upstream_sha

    assert seen == []  # no refetch


def test_ensure_classified_degrades_cleanly_on_a_missing_install_script(tmp_path, monkeypatch):
    """13 ct/ scripts have no matching install/ file (investigation §1), a
    real, known shape, not corrupt data."""
    db = make_db(tmp_path)
    tree = {"sha": SHA, "truncated": False,
            "tree": [{"path": "ct/lonely.sh", "type": "blob"}]}

    def fake_get(url, **kw):
        if url.endswith("/commits/main"):
            return httpx.Response(200, json={"sha": SHA})
        if "/git/trees/" in url:
            return httpx.Response(200, json=tree)
        if url.endswith(f"/{SHA}/ct/lonely.sh"):
            return httpx.Response(200, text='APP="Lonely"\nbuild_container\n')
        return httpx.Response(404)  # no install/lonely-install.sh upstream
    monkeypatch.setattr("proxploy.services.catalog._fetch", fake_get)
    run_discovery(db)

    row = ensure_classified(db, "lonely")

    assert row.installable is False
    assert "no install script" in row.unsupported_reason


def test_a_new_head_commit_clears_stale_classification_for_re_fetch(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    monkeypatch.setattr("proxploy.services.catalog._fetch", _fake_get())
    run_discovery(db)
    ensure_classified(db, "redis")
    assert db.query(CatalogEntry).filter_by(slug="redis").one().installable is True

    newer = "0" * 40
    monkeypatch.setattr("proxploy.services.catalog._fetch", _fake_get(sha=newer))
    run_discovery(db)

    row = db.query(CatalogEntry).filter_by(slug="redis").one()
    assert row.upstream_sha == newer
    assert row.installable is None  # cleared, not silently kept from the old commit
    assert row.raw is None


def test_run_discovery_is_idempotent_on_an_unchanged_head_commit(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    monkeypatch.setattr("proxploy.services.catalog._fetch", _fake_get())
    run_discovery(db)
    first_synced_at = db.query(CatalogEntry).filter_by(slug="redis").one().synced_at

    run_discovery(db)
    row = db.query(CatalogEntry).filter_by(slug="redis").one()
    assert row.synced_at == first_synced_at  # unchanged HEAD commit -> no re-write


def test_run_discovery_preserves_a_slug_it_no_longer_needs_to_touch(tmp_path, monkeypatch):
    """A re-run at the same commit must not clobber a name/category that
    ensure_classified or the scrape enrichment already improved."""
    db = make_db(tmp_path)
    monkeypatch.setattr("proxploy.services.catalog._fetch", _fake_get())
    run_discovery(db)
    ensure_classified(db, "redis")
    assert db.query(CatalogEntry).filter_by(slug="redis").one().name == "Redis"

    run_discovery(db)

    assert db.query(CatalogEntry).filter_by(slug="redis").one().name == "Redis"
