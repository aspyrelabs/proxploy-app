import httpx

from proxploy.models import CatalogEntry
from proxploy.services.catalog import parse_ct_script, run_ingest
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


def _fake_get(sha=SHA, seen=None):
    """Stands in for catalog._fetch: the GitHub HEAD-commit API call plus the
    two commit-pinned raw fetches."""
    def fake_get(url, **kw):
        if seen is not None:
            seen.append(url)
        if url.endswith("/commits/main"):
            return httpx.Response(200, json={"sha": sha})
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


def test_run_ingest_upserts_a_classified_entry(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    monkeypatch.setattr("proxploy.services.catalog._fetch", _fake_get())

    run_ingest(db, slugs=["redis"])

    row = db.query(CatalogEntry).filter_by(slug="redis").one()
    assert row.name == "Redis"
    assert row.category == "Databases"
    assert row.installable is True
    assert row.unsupported_reason is None
    assert row.default_cpu == 1 and row.default_ram_mb == 1024
    assert row.upstream_sha == SHA


def test_ingest_fetches_both_files_by_commit_sha_not_main(tmp_path, monkeypatch):
    """Critical #2: the content that gets classified/pinned must come from an
    immutable commit, so run_install can execute that exact same commit."""
    db = make_db(tmp_path)
    seen: list[str] = []
    monkeypatch.setattr("proxploy.services.catalog._fetch", _fake_get(seen=seen))

    result = run_ingest(db, slugs=["redis"])

    assert result["upstream_sha"] == SHA
    assert seen == [
        "https://api.github.com/repos/community-scripts/ProxmoxVE/commits/main",
        f"https://raw.githubusercontent.com/community-scripts/ProxmoxVE/{SHA}/ct/redis.sh",
        f"https://raw.githubusercontent.com/community-scripts/ProxmoxVE/{SHA}/install/redis-install.sh",
    ]
    # ...and no fetch anywhere used the moving `main` ref for script content.
    assert not any("/ProxmoxVE/main/" in u for u in seen)
    assert db.query(CatalogEntry).filter_by(slug="redis").one().upstream_sha == SHA


def test_one_head_commit_lookup_per_refresh_not_per_slug(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    seen: list[str] = []
    monkeypatch.setattr("proxploy.services.catalog._fetch", _fake_get(seen=seen))

    run_ingest(db, slugs=["redis", "nope-a", "nope-b"])

    assert len([u for u in seen if u.endswith("/commits/main")]) == 1


def test_run_ingest_is_idempotent_on_an_unchanged_head_commit(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    monkeypatch.setattr("proxploy.services.catalog._fetch", _fake_get())
    run_ingest(db, slugs=["redis"])
    first_synced_at = db.query(CatalogEntry).filter_by(slug="redis").one().synced_at

    run_ingest(db, slugs=["redis"])
    row = db.query(CatalogEntry).filter_by(slug="redis").one()
    assert row.synced_at == first_synced_at  # unchanged HEAD commit -> no re-write


def test_a_new_head_commit_re_ingests(tmp_path, monkeypatch):
    """I2: the old per-ct-file ETag check never re-triggered when only the
    install/ file moved. A repo-wide commit SHA does."""
    db = make_db(tmp_path)
    monkeypatch.setattr("proxploy.services.catalog._fetch", _fake_get())
    run_ingest(db, slugs=["redis"])

    newer = "0" * 40
    monkeypatch.setattr("proxploy.services.catalog._fetch", _fake_get(sha=newer))
    run_ingest(db, slugs=["redis"])

    assert db.query(CatalogEntry).filter_by(slug="redis").one().upstream_sha == newer


def test_one_bad_slug_does_not_abort_the_batch(tmp_path, monkeypatch):
    """I3: a 404 on one slug used to raise JobFailed out of run_ingest and
    leave every later slug in the list unprocessed."""
    db = make_db(tmp_path)
    monkeypatch.setattr("proxploy.services.catalog._fetch", _fake_get())

    result = run_ingest(db, slugs=["does-not-exist", "redis"])

    assert result["synced"] == 1
    assert [f["slug"] for f in result["failed"]] == ["does-not-exist"]
    assert "ct script fetch failed (404)" in result["failed"][0]["reason"]
    # the good slug that came *after* the failure still landed
    assert db.query(CatalogEntry).filter_by(slug="redis").one().installable is True
