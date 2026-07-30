import httpx
import pytest

from proxploy.models import CatalogEntry
from proxploy.services.catalog import parse_ct_script, run_ingest
from tests.support import make_db

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


def test_parse_ct_script_extracts_metadata():
    meta = parse_ct_script(REDIS_CT)
    assert meta == {
        "name": "Redis", "website": "https://redis.io/",
        "default_cpu": 1, "default_ram_mb": 1024, "default_disk_gb": 4,
        "default_os": "debian", "default_os_version": "13",
    }


def test_run_ingest_upserts_a_classified_entry(tmp_path, monkeypatch):
    db = make_db(tmp_path)

    def fake_get(url, **kw):
        if url.endswith("/main/ct/redis.sh"):
            return httpx.Response(200, text=REDIS_CT, headers={"ETag": '"abc123"'})
        if url.endswith("/main/install/redis-install.sh"):
            return httpx.Response(200, text=REDIS_INSTALL)
        return httpx.Response(404)

    monkeypatch.setattr("proxploy.services.catalog._fetch", fake_get)

    run_ingest(db, slugs=["redis"])

    row = db.query(CatalogEntry).filter_by(slug="redis").one()
    assert row.name == "Redis"
    assert row.category == "Databases"
    assert row.installable is True
    assert row.unsupported_reason is None
    assert row.default_cpu == 1 and row.default_ram_mb == 1024
    assert row.upstream_sha == "abc123"


def test_run_ingest_is_idempotent_on_unchanged_etag(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    calls = {"n": 0}

    def fake_get(url, **kw):
        calls["n"] += 1
        if url.endswith("/main/ct/redis.sh"):
            return httpx.Response(200, text=REDIS_CT, headers={"ETag": '"abc123"'})
        if url.endswith("/main/install/redis-install.sh"):
            return httpx.Response(200, text=REDIS_INSTALL)
        return httpx.Response(404)

    monkeypatch.setattr("proxploy.services.catalog._fetch", fake_get)
    run_ingest(db, slugs=["redis"])
    first_synced_at = db.query(CatalogEntry).filter_by(slug="redis").one().synced_at

    run_ingest(db, slugs=["redis"])
    row = db.query(CatalogEntry).filter_by(slug="redis").one()
    assert row.synced_at == first_synced_at  # unchanged ETag -> no re-write
