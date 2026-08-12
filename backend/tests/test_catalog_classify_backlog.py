"""The low-priority background classification pass (catalog expansion plan,
decision 2): bounded-concurrency lazy classification of whatever
ensure_classified hasn't reached yet, run as its own job after a refresh."""
import asyncio

import httpx

from proxploy.jobs import JobBackend, JobContext
from proxploy.models import CatalogEntry, Job
from proxploy.services.catalog import classify_many
from tests.support import make_db, make_job_app

SHA = "d7bc6b59676456f7a8b3a20f24c3ca589d7fe2f6"


def _seed_ct(db, slug, sha=SHA):
    db.add(CatalogEntry(slug=slug, entry_type="ct", upstream_sha=sha,
                        script_path=f"ct/{slug}.sh", installable=None))


def test_classify_many_classifies_every_unclassified_slug(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    for slug in ("redis", "grafana", "gitea"):
        _seed_ct(db, slug)
    db.commit()

    def fake_get(url, **kw):
        for slug in ("redis", "grafana", "gitea"):
            if url.endswith(f"/{SHA}/ct/{slug}.sh"):
                return httpx.Response(200, text=f'APP="{slug}"\nbuild_container\n')
            if url.endswith(f"/{SHA}/install/{slug}-install.sh"):
                return httpx.Response(200, text='msg_info "ok"\n')
        return httpx.Response(404)
    monkeypatch.setattr("proxploy.services.catalog._fetch", fake_get)

    async def scenario():
        from proxploy.config import Settings
        from proxploy.db import make_engine, make_sessionmaker

        s = Settings(db_url=f"sqlite:///{tmp_path}/t.db", data_dir=tmp_path,
                    master_key_file=tmp_path / "master.key")
        sm = make_sessionmaker(make_engine(s))
        return await classify_many(sm, ["redis", "grafana", "gitea"], concurrency=2)

    result = asyncio.run(scenario())

    assert result["done"] == 3
    assert result["failed"] == []
    for slug in ("redis", "grafana", "gitea"):
        row = db.query(CatalogEntry).filter_by(slug=slug).one()
        assert row.installable is True


def test_classify_many_handles_a_bad_http_status_without_raising(tmp_path, monkeypatch):
    """A 500/404 from upstream is NOT an exception here: ensure_classified
    turns it into an honest unsupported row (decision 1, degrade silently),
    so it still counts as "done", and the good slug is unaffected either
    way."""
    db = make_db(tmp_path)
    _seed_ct(db, "redis")
    _seed_ct(db, "broken")
    db.commit()

    def fake_get(url, **kw):
        if "broken" in url:
            return httpx.Response(500)
        if url.endswith(f"/{SHA}/ct/redis.sh"):
            return httpx.Response(200, text='APP="Redis"\nbuild_container\n')
        if url.endswith(f"/{SHA}/install/redis-install.sh"):
            return httpx.Response(200, text='msg_info "ok"\n')
        return httpx.Response(404)
    monkeypatch.setattr("proxploy.services.catalog._fetch", fake_get)

    async def scenario():
        from proxploy.config import Settings
        from proxploy.db import make_engine, make_sessionmaker

        s = Settings(db_url=f"sqlite:///{tmp_path}/t.db", data_dir=tmp_path,
                    master_key_file=tmp_path / "master.key")
        sm = make_sessionmaker(make_engine(s))
        return await classify_many(sm, ["broken", "redis"])

    result = asyncio.run(scenario())

    assert result["done"] == 2
    assert result["failed"] == []
    assert db.query(CatalogEntry).filter_by(slug="redis").one().installable is True
    assert db.query(CatalogEntry).filter_by(slug="broken").one().installable is False


def test_classify_many_records_a_real_exception_without_aborting_the_rest(tmp_path, monkeypatch):
    """A genuine exception (network error, DB hiccup) on one slug must not
    take down the rest of the backlog pass; recorded in `failed` instead."""
    db = make_db(tmp_path)
    _seed_ct(db, "redis")
    _seed_ct(db, "broken")
    db.commit()

    def fake_get(url, **kw):
        if "broken" in url:
            raise ConnectionError("connection reset")
        if url.endswith(f"/{SHA}/ct/redis.sh"):
            return httpx.Response(200, text='APP="Redis"\nbuild_container\n')
        if url.endswith(f"/{SHA}/install/redis-install.sh"):
            return httpx.Response(200, text='msg_info "ok"\n')
        return httpx.Response(404)
    monkeypatch.setattr("proxploy.services.catalog._fetch", fake_get)

    async def scenario():
        from proxploy.config import Settings
        from proxploy.db import make_engine, make_sessionmaker

        s = Settings(db_url=f"sqlite:///{tmp_path}/t.db", data_dir=tmp_path,
                    master_key_file=tmp_path / "master.key")
        sm = make_sessionmaker(make_engine(s))
        return await classify_many(sm, ["broken", "redis"])

    result = asyncio.run(scenario())

    assert result["done"] == 1
    assert [f["slug"] for f in result["failed"]] == ["broken"]
    assert db.query(CatalogEntry).filter_by(slug="redis").one().installable is True


def test_classify_backlog_job_only_touches_unclassified_ct_entries(tmp_path, monkeypatch):
    async def scenario():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            db.add(Job(id=1, kind="catalog.classify_backlog", status="running"))
            _seed_ct(db, "redis")
            db.add(CatalogEntry(slug="grafana", entry_type="ct", upstream_sha=SHA,
                                script_path="ct/grafana.sh", installable=True))  # already done
            db.add(CatalogEntry(slug="haos", entry_type="vm", installable=False,
                                unsupported_reason="vm"))  # never a classification target
            db.commit()

        def fake_get(url, **kw):
            if url.endswith(f"/{SHA}/ct/redis.sh"):
                return httpx.Response(200, text='APP="Redis"\nbuild_container\n')
            if url.endswith(f"/{SHA}/install/redis-install.sh"):
                return httpx.Response(200, text='msg_info "ok"\n')
            raise AssertionError(f"unexpected fetch: {url}")
        monkeypatch.setattr("proxploy.services.catalog._fetch", fake_get)

        backend = JobBackend(app)
        app.state.jobs = backend
        ctx = JobContext(backend, job_id=1)

        from proxploy.services.catalog import classify_backlog
        result = await classify_backlog(ctx, {})

        with app.state.sessionmaker() as db:
            assert db.query(CatalogEntry).filter_by(slug="redis").one().installable is True
        return result

    result = asyncio.run(scenario())
    assert result["done"] == 1  # only "redis" needed classifying
