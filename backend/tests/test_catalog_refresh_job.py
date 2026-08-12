"""catalog.refresh job handler: discovery + best-effort enrichment + the
low-priority background classification pass it schedules (catalog expansion
plan, decisions 1 and 2)."""
import asyncio

import httpx

from proxploy.jobs import JobBackend, JobContext
from proxploy.models import CatalogEntry, Job
from tests.support import make_job_app

SHA = "d7bc6b59676456f7a8b3a20f24c3ca589d7fe2f6"

FIXTURE_TREE = {
    "sha": SHA, "truncated": False,
    "tree": [
        {"path": "ct/redis.sh", "type": "blob"},
        {"path": "ct/grafana.sh", "type": "blob"},
        {"path": "vm/haos.sh", "type": "blob"},
    ],
}


def _fake_get(seen=None):
    def fake_get(url, **kw):
        if seen is not None:
            seen.append(url)
        if url.endswith("/commits/main"):
            return httpx.Response(200, json={"sha": SHA})
        if "/git/trees/" in url:
            return httpx.Response(200, json=FIXTURE_TREE)
        return httpx.Response(404)
    return fake_get


def _seed_job(db, job_id=1, kind="catalog.refresh"):
    db.add(Job(id=job_id, kind=kind, status="running"))
    db.commit()


def test_refresh_catalog_populates_the_catalog_and_stays_at_two_api_calls(tmp_path, monkeypatch):
    async def scenario():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            _seed_job(db)
        backend = JobBackend(app)
        app.state.jobs = backend
        ctx = JobContext(backend, job_id=1)

        seen: list[str] = []
        monkeypatch.setattr("proxploy.services.catalog._fetch", _fake_get(seen=seen))
        monkeypatch.setattr(
            "proxploy.services.community_scripts_scrape.fetch_enrichment",
            lambda: None)

        from proxploy.services.catalog import refresh_catalog
        result = await refresh_catalog(ctx, {})

        api_calls = [u for u in seen if u.startswith("https://api.github.com/")]
        assert len(api_calls) == 2
        with app.state.sessionmaker() as db:
            assert db.query(CatalogEntry).count() == 3
        return result

    result = asyncio.run(scenario())
    assert result["total"] == 3


def test_refresh_catalog_schedules_a_low_priority_backlog_job(tmp_path, monkeypatch):
    """Decision 2: the backlog classification pass runs AFTER the store is
    already usable, as its own job, never blocking the refresh."""
    async def scenario():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            _seed_job(db)
        backend = JobBackend(app)
        app.state.jobs = backend
        ctx = JobContext(backend, job_id=1)

        monkeypatch.setattr("proxploy.services.catalog._fetch", _fake_get())
        monkeypatch.setattr(
            "proxploy.services.community_scripts_scrape.fetch_enrichment",
            lambda: None)

        from proxploy.services.catalog import refresh_catalog
        result = await refresh_catalog(ctx, {})

        with app.state.sessionmaker() as db:
            backlog_job = db.get(Job, result["classify_backlog_job_id"])
            assert backlog_job is not None
            assert backlog_job.kind == "catalog.classify_backlog"

    asyncio.run(scenario())


def test_refresh_catalog_succeeds_even_when_enrichment_raises(tmp_path, monkeypatch):
    """Decision 1: an enrichment failure (403, timeout, shape change) must
    never fail the refresh job itself."""
    async def scenario():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            _seed_job(db)
        backend = JobBackend(app)
        app.state.jobs = backend
        ctx = JobContext(backend, job_id=1)

        monkeypatch.setattr("proxploy.services.catalog._fetch", _fake_get())

        def _boom():
            raise RuntimeError("community-scripts.org unreachable")
        monkeypatch.setattr(
            "proxploy.services.community_scripts_scrape.fetch_enrichment", _boom)

        from proxploy.services.catalog import refresh_catalog
        result = await refresh_catalog(ctx, {})  # must not raise
        with app.state.sessionmaker() as db:
            assert db.query(CatalogEntry).count() == 3
        return result

    result = asyncio.run(scenario())
    assert result["total"] == 3
