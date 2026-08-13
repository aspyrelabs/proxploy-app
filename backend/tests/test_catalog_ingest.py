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


# --- ct scripts that delegate their payload to tools/addon/<slug>.sh --------
#
# Five popular apps (coolify, dockge, dokploy, komodo, runtipi) ship a full LXC
# builder with NO install/<slug>-install.sh, delegating the in-container step
# to tools/addon/<slug>.sh instead. We were reporting all five as "no install
# script found upstream", which is a wrong conclusion from a right observation
# about the file convention.

from proxploy.services.classifier import (  # noqa: E402
    UNSUPPORTED_ADDON_DELEGATED,
)
from tests.test_classifier import (  # noqa: E402
    DELEGATING_CT, INTERACTIVE_ADDON, SILENT_ADDON,
)

FIVE = ["coolify", "dockge", "dokploy", "komodo", "runtipi"]


def _delegating_fetch(slug="dockge", addon_body=SILENT_ADDON, sha=SHA, seen=None,
                      addon_status=200, tree=None):
    """A tree where <slug> has a ct script and an addon script but NO install
    script, exactly as upstream ships these five."""
    ct_body = DELEGATING_CT.format(slug=slug, name=slug.title())
    default_tree = {"sha": sha, "truncated": False, "tree": [
        {"path": f"ct/{slug}.sh", "type": "blob"},
        {"path": f"tools/addon/{slug}.sh", "type": "blob"},
        {"path": "ct/redis.sh", "type": "blob"},
    ]}

    def fake_get(url, **kw):
        if seen is not None:
            seen.append(url)
        if url.endswith("/commits/main"):
            return httpx.Response(200, json={"sha": sha})
        if "/git/trees/" in url:
            return httpx.Response(200, json=tree if tree is not None else default_tree)
        if url.endswith(f"/{sha}/ct/{slug}.sh"):
            return httpx.Response(200, text=ct_body)
        if url.endswith(f"/{sha}/tools/addon/{slug}.sh"):
            return httpx.Response(addon_status, text=addon_body)
        if url.endswith(f"/{sha}/ct/redis.sh"):
            return httpx.Response(200, text=REDIS_CT)
        if url.endswith(f"/{sha}/install/redis-install.sh"):
            return httpx.Response(200, text=REDIS_INSTALL)
        return httpx.Response(404)
    return fake_get


def test_a_delegating_ct_row_keeps_the_data_but_is_never_installable(tmp_path,
                                                                     monkeypatch):
    """We changed the VERDICT, not the data. The addon script is still
    fetched and pinned into `raw`, and the ct script's resource defaults are
    still parsed, which the old "no install script found upstream" dead end
    never got round to. The reason is now accurate rather than flatly wrong."""
    db = make_db(tmp_path)
    monkeypatch.setattr("proxploy.services.catalog._fetch", _delegating_fetch())
    run_discovery(db)

    ensure_classified(db, "dockge")

    row = db.query(CatalogEntry).filter_by(slug="dockge").one()
    assert row.installable is False
    assert row.unsupported_reason == UNSUPPORTED_ADDON_DELEGATED
    assert row.raw["addon_script"] == SILENT_ADDON
    assert "install_script" not in row.raw
    assert (row.default_cpu, row.default_ram_mb, row.default_disk_gb) == (2, 2048, 18)
    assert (row.default_os, row.default_os_version) == ("debian", "13")


def test_a_silent_addon_script_does_not_make_the_row_installable(tmp_path,
                                                                 monkeypatch):
    """THE REGRESSION THIS EXISTS TO STOP, and the hole that was open until
    now. SILENT_ADDON has no prompt at all, so a verdict derived from the
    addon script would call this row installable. Installing it would run the
    CT SCRIPT, whose build_container curls install/dockge-install.sh, gets a
    404, swallows the error because `set -Eeuo` is off there, and runs
    `bash -c ""` which exits 0: an empty container, filed as a successful
    install, invisible to run_install's "exited 0 but no CT" guard because the
    CT genuinely exists.

    All five real addon scripts prompt today, so the hole never actually
    opened. It was one non-interactive upstream rewrite away from opening.
    """
    db = make_db(tmp_path)
    monkeypatch.setattr("proxploy.services.catalog._fetch",
                        _delegating_fetch(addon_body=SILENT_ADDON))
    run_discovery(db)

    ensure_classified(db, "dockge")

    row = db.query(CatalogEntry).filter_by(slug="dockge").one()
    assert row.installable is False, "a silent addon script must not flip the verdict"
    assert row.unsupported_reason == UNSUPPORTED_ADDON_DELEGATED
    # And the verdict is NOT the interactive-input finding wearing a new hat:
    # this script has no prompt in it at all.
    assert "interactive" not in row.unsupported_reason
    from proxploy.services.classifier import classify_install_feasibility
    assert classify_install_feasibility(
        DELEGATING_CT.format(slug="dockge", name="Dockge"), SILENT_ADDON) == (True, None)


def test_an_addon_script_that_prompts_is_also_not_installable(tmp_path, monkeypatch):
    """The real shape of all five at pinned SHA a222d32a..., and it reaches
    the same verdict by the same route. The interactive-input finding is still
    true and the detector is untouched; it is simply not what decides this."""
    db = make_db(tmp_path)
    monkeypatch.setattr("proxploy.services.catalog._fetch",
                        _delegating_fetch(addon_body=INTERACTIVE_ADDON))
    run_discovery(db)

    ensure_classified(db, "dockge")

    row = db.query(CatalogEntry).filter_by(slug="dockge").one()
    assert row.installable is False
    assert row.unsupported_reason == UNSUPPORTED_ADDON_DELEGATED
    assert row.raw["addon_script"] == INTERACTIVE_ADDON


def test_the_addon_fetch_is_pinned_to_the_rows_upstream_sha(tmp_path, monkeypatch):
    """Unpinned, we would classify one revision and let run_install execute
    another, which is the entire guarantee the pin exists to make. And it is
    raw.githubusercontent.com only: no api.github.com call is added."""
    db = make_db(tmp_path)
    seen: list[str] = []
    monkeypatch.setattr("proxploy.services.catalog._fetch",
                        _delegating_fetch(seen=seen))
    run_discovery(db)
    seen.clear()

    ensure_classified(db, "dockge")

    addon_urls = [u for u in seen if "tools/addon/" in u]
    assert addon_urls == [
        f"https://raw.githubusercontent.com/community-scripts/ProxmoxVE"
        f"/{SHA}/tools/addon/dockge.sh"]
    assert "main" not in addon_urls[0].split("/ProxmoxVE/")[1].split("/")[0]
    assert not any("api.github.com" in u for u in seen)


def test_an_unfetchable_addon_script_reports_that_honestly(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    monkeypatch.setattr("proxploy.services.catalog._fetch",
                        _delegating_fetch(addon_status=500))
    run_discovery(db)

    ensure_classified(db, "dockge")

    row = db.query(CatalogEntry).filter_by(slug="dockge").one()
    assert row.installable is False
    assert row.unsupported_reason == ("could not fetch the addon script this "
                                      "app delegates to")


def test_a_ct_row_with_neither_install_nor_addon_keeps_the_old_answer(tmp_path,
                                                                      monkeypatch):
    """13 ct/ scripts have no install/ file and no delegation either. That
    path is unchanged."""
    db = make_db(tmp_path)
    plain = REDIS_CT.replace("APP=\"Redis\"", "APP=\"Orphan\"")

    def fake_get(url, **kw):
        if url.endswith("/commits/main"):
            return httpx.Response(200, json={"sha": SHA})
        if "/git/trees/" in url:
            return httpx.Response(200, json={"sha": SHA, "truncated": False,
                                             "tree": [{"path": "ct/orphan.sh",
                                                       "type": "blob"}]})
        if url.endswith(f"/{SHA}/ct/orphan.sh"):
            return httpx.Response(200, text=plain)
        return httpx.Response(404)
    monkeypatch.setattr("proxploy.services.catalog._fetch", fake_get)
    run_discovery(db)

    ensure_classified(db, "orphan")

    row = db.query(CatalogEntry).filter_by(slug="orphan").one()
    assert row.installable is False
    assert row.unsupported_reason == "no install script found upstream"
    assert "addon_script" not in (row.raw or {})


def test_classifying_the_ct_row_leaves_the_slug_addon_row_alone(tmp_path,
                                                                monkeypatch):
    """One upstream FILE now backs two catalog rows: the ct row classifies
    against tools/addon/dockge.sh, and the dual-variant collision logic also
    discovered that same file as its own `dockge-addon` row. Classifying one
    must not touch the other."""
    db = make_db(tmp_path)
    monkeypatch.setattr("proxploy.services.catalog._fetch", _delegating_fetch())
    run_discovery(db)
    addon_row = db.query(CatalogEntry).filter_by(slug="dockge-addon").one()
    before = (addon_row.entry_type, addon_row.script_path, addon_row.installable,
              addon_row.unsupported_reason, addon_row.raw, addon_row.name)

    ensure_classified(db, "dockge")

    addon_row = db.query(CatalogEntry).filter_by(slug="dockge-addon").one()
    assert (addon_row.entry_type, addon_row.script_path, addon_row.installable,
            addon_row.unsupported_reason, addon_row.raw, addon_row.name) == before
    assert addon_row.entry_type == "addon"
    # ...and the ct row kept the plain slug and its own type.
    ct_row = db.query(CatalogEntry).filter_by(slug="dockge").one()
    assert ct_row.entry_type == "ct" and ct_row.script_path == "ct/dockge.sh"


def test_all_five_stay_ct_and_visible_to_the_store_grid(tmp_path, monkeypatch):
    """The five are exactly the dual-variant collision slugs. Whatever the
    feasibility answer turns out to be, they stay ct rows on the grid."""
    from proxploy.services.catalog_metadata import store_visible

    db = make_db(tmp_path)
    tree = {"sha": SHA, "truncated": False, "tree":
            [{"path": f"ct/{s}.sh", "type": "blob"} for s in FIVE]
            + [{"path": f"tools/addon/{s}.sh", "type": "blob"} for s in FIVE]}
    for slug in FIVE:
        monkeypatch.setattr("proxploy.services.catalog._fetch",
                            _delegating_fetch(slug=slug, tree=tree))
        run_discovery(db)
        ensure_classified(db, slug)

    for slug in FIVE:
        row = db.query(CatalogEntry).filter_by(slug=slug).one()
        assert row.entry_type == "ct", slug
        # All five, including coolify/runtipi/dokploy: not installable, same
        # reason, whatever their addon scripts contain.
        assert row.installable is False, slug
        assert row.unsupported_reason == UNSUPPORTED_ADDON_DELEGATED, slug
        assert db.query(CatalogEntry).filter_by(slug=f"{slug}-addon").one(
        ).entry_type == "addon", slug
    in_grid = {r.slug for r in db.query(CatalogEntry).filter(store_visible())}
    assert set(FIVE) <= in_grid


def test_the_metadata_snapshot_survives_an_addon_classification(tmp_path, monkeypatch):
    """`raw` carries the upstream record snapshot on its own schedule, and
    _keep_metadata has to carry it through this path too."""
    db = make_db(tmp_path)
    monkeypatch.setattr("proxploy.services.catalog._fetch", _delegating_fetch())
    run_discovery(db)
    row = db.query(CatalogEntry).filter_by(slug="dockge").one()
    row.raw = {"metadata": {"slug": "dockge", "name": "Dockge"}}
    db.commit()

    ensure_classified(db, "dockge")

    row = db.query(CatalogEntry).filter_by(slug="dockge").one()
    assert row.raw["metadata"]["name"] == "Dockge"
    assert row.raw["addon_script"] == SILENT_ADDON


def test_a_normal_app_is_completely_unaffected(tmp_path, monkeypatch):
    """plex shape: an install/ script exists, so the addon branch is never
    reached and the verdict comes from the feasibility check as it always
    did."""
    db = make_db(tmp_path)
    monkeypatch.setattr("proxploy.services.catalog._fetch", _delegating_fetch())
    run_discovery(db)

    ensure_classified(db, "redis")

    row = db.query(CatalogEntry).filter_by(slug="redis").one()
    assert row.installable is True and row.unsupported_reason is None
    assert row.raw["install_script"] == REDIS_INSTALL
    assert "addon_script" not in row.raw
