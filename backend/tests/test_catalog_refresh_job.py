"""catalog.refresh job handler: discovery, the upstream metadata sync, the
telemetry popularity sync, the progress it reports, and the low-priority
background classification pass it schedules (catalog expansion plan, decisions
1 and 2; metadata design doc
docs/superpowers/specs/2026-08-13-app-store-upstream-metadata-design.md).

Every scenario here patches all THREE upstream hosts (api.github.com, the
PocketBase metadata source and the telemetry service), because a refresh now
talks to all three and an unpatched one would turn a unit test into a live
network call against someone else's service."""
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

REDIS_METADATA = {
    "slug": "redis", "name": "Redis", "description": "An in-memory data store.",
    "logo": "https://cdn.example/redis.webp", "website": "https://redis.io/",
    "documentation": "https://redis.io/docs/", "updated": "2026-06-11 14:16:43.777Z",
    "expand": {"categories": [{"id": "c1", "name": "Databases"}],
               "type": {"id": "t1", "type": "lxc"}},
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


def _fake_metadata_get(status=200, seen=None):
    """Stands in for catalog_metadata._fetch. A non-200 primary with a cold
    cache falls through to the archive, whose metadata.json 404s here too, so
    the sync reports a clean failure without a single real request."""
    def fake_get(url, **kw):
        if seen is not None:
            seen.append(url)
        if url.startswith("https://db.community-scripts.org") and status == 200:
            return httpx.Response(200, json={"page": 1, "perPage": 1000,
                                             "totalItems": 1, "totalPages": 1,
                                             "items": [REDIS_METADATA]})
        return httpx.Response(status if status != 200 else 404)
    return fake_get


def _fake_telemetry_get(status=200, seen=None):
    """Stands in for catalog_telemetry._fetch. `total` is deliberately absurd
    next to the terminal counts so any run that reads it instead of
    success+failed+aborted shows up as a wildly wrong number, not a subtly
    wrong one."""
    def fake_get(url, **kw):
        if seen is not None:
            seen.append(url)
        if status != 200:
            return httpx.Response(status)
        return httpx.Response(200, json={"top_scripts": [
            {"app": "redis", "type": "lxc", "total": 99999,
             "success": 800, "failed": 150, "aborted": 50, "installing": 7},
        ]})
    return fake_get


def _seed_job(db, job_id=1, kind="catalog.refresh"):
    db.add(Job(id=job_id, kind=kind, status="running"))
    db.commit()


def _record_progress(ctx) -> list[int]:
    """Capture the exact sequence a run reports, not just its final value:
    the bar in the Store is driven by these numbers, so their order matters
    as much as their presence."""
    seen: list[int] = []
    original = ctx.progress

    def recording(pct: int) -> None:
        seen.append(pct)
        original(pct)
    ctx.progress = recording
    return seen


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
        monkeypatch.setattr("proxploy.services.catalog_metadata._fetch",
                            _fake_metadata_get(seen=seen))
        monkeypatch.setattr("proxploy.services.catalog_telemetry._fetch",
                            _fake_telemetry_get(seen=seen))

        from proxploy.services.catalog import refresh_catalog
        result = await refresh_catalog(ctx, {})

        api_calls = [u for u in seen if u.startswith("https://api.github.com/")]
        assert len(api_calls) == 2
        with app.state.sessionmaker() as db:
            assert db.query(CatalogEntry).count() == 3
            row = db.query(CatalogEntry).filter_by(slug="redis").one()
            assert row.description == "An in-memory data store."
            assert row.metadata_source == "pocketbase"
        return result

    result = asyncio.run(scenario())
    assert result["total"] == 3
    assert result["metadata"]["matched"] == 1
    assert result["metadata"]["unmatched"] == 2


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
        monkeypatch.setattr("proxploy.services.catalog_metadata._fetch",
                            _fake_metadata_get())
        monkeypatch.setattr("proxploy.services.catalog_telemetry._fetch",
                            _fake_telemetry_get())

        from proxploy.services.catalog import refresh_catalog
        result = await refresh_catalog(ctx, {})

        with app.state.sessionmaker() as db:
            backlog_job = db.get(Job, result["classify_backlog_job_id"])
            assert backlog_job is not None
            assert backlog_job.kind == "catalog.classify_backlog"

    asyncio.run(scenario())


def test_refresh_catalog_succeeds_even_when_the_metadata_sync_raises(tmp_path, monkeypatch):
    """Failure policy: an unreachable metadata source, or an outright bug in
    the sync, must never fail the refresh job or empty the store."""
    async def scenario():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            _seed_job(db)
        backend = JobBackend(app)
        app.state.jobs = backend
        ctx = JobContext(backend, job_id=1)

        monkeypatch.setattr("proxploy.services.catalog._fetch", _fake_get())
        monkeypatch.setattr("proxploy.services.catalog_telemetry._fetch",
                            _fake_telemetry_get())

        def _boom(db):
            raise RuntimeError("db.community-scripts.org unreachable")
        monkeypatch.setattr("proxploy.services.catalog_metadata.sync_metadata", _boom)

        from proxploy.services.catalog import refresh_catalog
        result = await refresh_catalog(ctx, {})  # must not raise
        with app.state.sessionmaker() as db:
            assert db.query(CatalogEntry).count() == 3
        return result

    result = asyncio.run(scenario())
    assert result["total"] == 3
    assert result["metadata"]["ok"] is False


def test_refresh_catalog_writes_popularity_from_terminal_events(tmp_path, monkeypatch):
    """800 + 150 + 50, not the fixture's `total` of 99999."""
    async def scenario():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            _seed_job(db)
        backend = JobBackend(app)
        app.state.jobs = backend
        ctx = JobContext(backend, job_id=1)

        monkeypatch.setattr("proxploy.services.catalog._fetch", _fake_get())
        monkeypatch.setattr("proxploy.services.catalog_metadata._fetch",
                            _fake_metadata_get())
        monkeypatch.setattr("proxploy.services.catalog_telemetry._fetch",
                            _fake_telemetry_get())

        from proxploy.services.catalog import refresh_catalog
        result = await refresh_catalog(ctx, {})

        with app.state.sessionmaker() as db:
            row = db.query(CatalogEntry).filter_by(slug="redis").one()
            assert row.popularity == 1000
            assert row.popularity_synced_at is not None
            # No telemetry for this one, so no number and no "as of" stamp.
            other = db.query(CatalogEntry).filter_by(slug="grafana").one()
            assert other.popularity is None and other.popularity_synced_at is None
        return result

    result = asyncio.run(scenario())
    assert result["popularity"]["ok"] and result["popularity"]["matched"] == 1


def test_popularity_still_syncs_when_the_metadata_sync_failed(tmp_path, monkeypatch):
    """Two different services on two different hosts with two different bad
    days. Gating the telemetry phase on the metadata outcome would turn one
    service's outage into two stale signals."""
    async def scenario():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            _seed_job(db)
        backend = JobBackend(app)
        app.state.jobs = backend
        ctx = JobContext(backend, job_id=1)

        monkeypatch.setattr("proxploy.services.catalog._fetch", _fake_get())
        monkeypatch.setattr("proxploy.services.catalog_metadata._fetch",
                            _fake_metadata_get(status=503))
        monkeypatch.setattr("proxploy.services.catalog_telemetry._fetch",
                            _fake_telemetry_get())

        from proxploy.services.catalog import refresh_catalog
        result = await refresh_catalog(ctx, {})

        with app.state.sessionmaker() as db:
            assert db.query(CatalogEntry).filter_by(slug="redis").one().popularity == 1000
        return result

    result = asyncio.run(scenario())
    assert result["metadata"]["ok"] is False
    assert result["popularity"]["ok"] and result["popularity"]["matched"] == 1


def test_refresh_catalog_succeeds_even_when_the_popularity_sync_raises(tmp_path, monkeypatch):
    """The mirror of the metadata case: a bug in the telemetry sync must never
    fail the refresh job, and the rest of the catalog still lands."""
    async def scenario():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            _seed_job(db)
        backend = JobBackend(app)
        app.state.jobs = backend
        ctx = JobContext(backend, job_id=1)

        monkeypatch.setattr("proxploy.services.catalog._fetch", _fake_get())
        monkeypatch.setattr("proxploy.services.catalog_metadata._fetch",
                            _fake_metadata_get())

        def _boom(db):
            raise RuntimeError("telemetry.community-scripts.org unreachable")
        monkeypatch.setattr("proxploy.services.catalog_telemetry.sync_popularity", _boom)

        from proxploy.services.catalog import refresh_catalog
        result = await refresh_catalog(ctx, {})  # must not raise
        with app.state.sessionmaker() as db:
            row = db.query(CatalogEntry).filter_by(slug="redis").one()
            assert row.description == "An in-memory data store."
            assert row.popularity is None
        return result

    result = asyncio.run(scenario())
    assert result["popularity"]["ok"] is False
    assert result["metadata"]["ok"] is True


# --- progress: monotonic, honest, and always reaching 100 -------------------

def test_refresh_progress_is_monotonic_and_ends_at_100(tmp_path, monkeypatch):
    async def scenario():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            _seed_job(db)
        backend = JobBackend(app)
        app.state.jobs = backend
        ctx = JobContext(backend, job_id=1)
        seen = _record_progress(ctx)

        monkeypatch.setattr("proxploy.services.catalog._fetch", _fake_get())
        monkeypatch.setattr("proxploy.services.catalog_metadata._fetch",
                            _fake_metadata_get())
        monkeypatch.setattr("proxploy.services.catalog_telemetry._fetch",
                            _fake_telemetry_get())

        from proxploy.services.catalog import refresh_catalog
        await refresh_catalog(ctx, {})

        with app.state.sessionmaker() as db:
            assert db.get(Job, 1).progress_pct == 100
        return seen

    seen = asyncio.run(scenario())
    assert seen == sorted(seen) and len(set(seen)) == len(seen)
    assert seen[-1] == 100
    assert len(seen) >= 5  # a real phase sequence, not one jump from 0 to 100


def test_refresh_progress_still_reaches_100_when_the_metadata_sync_fails(tmp_path, monkeypatch):
    """A best-effort phase that failed must not strand the bar at its value."""
    async def scenario():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            _seed_job(db)
        backend = JobBackend(app)
        app.state.jobs = backend
        ctx = JobContext(backend, job_id=1)
        seen = _record_progress(ctx)

        monkeypatch.setattr("proxploy.services.catalog._fetch", _fake_get())
        monkeypatch.setattr("proxploy.services.catalog_metadata._fetch",
                            _fake_metadata_get(status=503))
        monkeypatch.setattr("proxploy.services.catalog_telemetry._fetch",
                            _fake_telemetry_get(status=503))

        from proxploy.services.catalog import refresh_catalog
        result = await refresh_catalog(ctx, {})
        assert result["metadata"]["ok"] is False
        assert result["popularity"]["ok"] is False
        return seen

    seen = asyncio.run(scenario())
    assert seen == sorted(seen) and len(set(seen)) == len(seen)
    assert seen[-1] == 100
    assert len(seen) >= 5  # a failed phase still reports its own step


def test_refresh_progress_still_reaches_100_when_only_telemetry_fails(tmp_path, monkeypatch):
    """Each best-effort phase fails independently, and neither one stranding
    the bar is the whole reason the sequence is emitted per phase."""
    async def scenario():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            _seed_job(db)
        backend = JobBackend(app)
        app.state.jobs = backend
        ctx = JobContext(backend, job_id=1)
        seen = _record_progress(ctx)

        monkeypatch.setattr("proxploy.services.catalog._fetch", _fake_get())
        monkeypatch.setattr("proxploy.services.catalog_metadata._fetch",
                            _fake_metadata_get())
        monkeypatch.setattr("proxploy.services.catalog_telemetry._fetch",
                            _fake_telemetry_get(status=503))

        from proxploy.services.catalog import refresh_catalog
        result = await refresh_catalog(ctx, {})
        assert result["metadata"]["ok"] is True
        assert result["popularity"]["ok"] is False
        return seen

    seen = asyncio.run(scenario())
    assert seen == sorted(seen) and len(set(seen)) == len(seen)
    assert seen[-1] == 100
