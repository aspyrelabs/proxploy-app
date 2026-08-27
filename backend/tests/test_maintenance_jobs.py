import asyncio
from datetime import timedelta

from proxploy.entitlements.client import Entitlements
from proxploy.jobs import JobBackend, JobContext
from proxploy.models import (
    ConsoleTicket, Job, JobEvent, SessionRow, TrustedDevice, User, utcnow,
)
from proxploy.services import maintenance
from tests.support import make_job_app


def _app(tmp_path):
    app = make_job_app(tmp_path)
    app.state.entitlements = Entitlements({})
    app.state.engine = app.state.sessionmaker.kw["bind"]
    return app


def _seed_job(db, job_id=1, kind="sessions.cleanup"):
    db.add(Job(id=job_id, kind=kind, status="running"))
    db.commit()


def _user(db, user_id=1):
    if db.get(User, user_id) is None:
        db.add(User(id=user_id, email=f"u{user_id}@example.test"))
        db.commit()


# --- sessions.cleanup ---------------------------------------------------

def test_cleanup_sessions_deletes_only_dead_rows(tmp_path):
    async def scenario():
        app = _app(tmp_path)
        with app.state.sessionmaker() as db:
            _user(db)
            _seed_job(db)
            now = utcnow()
            db.add(SessionRow(id=1, user_id=1, token_hash="live-session",
                              expires_at=now + timedelta(days=1)))
            db.add(SessionRow(id=2, user_id=1, token_hash="revoked-session",
                              expires_at=now + timedelta(days=1),
                              revoked_at=now))
            db.add(SessionRow(id=3, user_id=1, token_hash="expired-session",
                              expires_at=now - timedelta(days=1)))
            db.add(TrustedDevice(id=1, user_id=1, token_hash="live-device",
                                 expires_at=now + timedelta(days=1)))
            db.add(TrustedDevice(id=2, user_id=1, token_hash="revoked-device",
                                 expires_at=now + timedelta(days=1),
                                 revoked_at=now))
            db.add(TrustedDevice(id=3, user_id=1, token_hash="expired-device",
                                 expires_at=now - timedelta(days=1)))
            db.add(ConsoleTicket(id=1, user_id=1, kind="app_console", target_id=1,
                                 node="pve1", upstream_user="proxploy@pve!console",
                                 upstream_ticket="PVEVNC:live", upstream_port="5900",
                                 token_hash="live-ticket",
                                 expires_at=now + timedelta(minutes=1)))
            db.add(ConsoleTicket(id=2, user_id=1, kind="app_console", target_id=1,
                                 node="pve1", upstream_user="proxploy@pve!console",
                                 upstream_ticket="PVEVNC:redeemed", upstream_port="5900",
                                 token_hash="redeemed-ticket",
                                 expires_at=now + timedelta(minutes=1),
                                 redeemed_at=now))
            db.add(ConsoleTicket(id=3, user_id=1, kind="app_console", target_id=1,
                                 node="pve1", upstream_user="proxploy@pve!console",
                                 upstream_ticket="PVEVNC:expired", upstream_port="5900",
                                 token_hash="expired-ticket",
                                 expires_at=now - timedelta(minutes=1)))
            db.commit()

        backend = JobBackend(app)
        app.state.jobs = backend
        ctx = JobContext(backend, job_id=1)
        result = await maintenance.cleanup_sessions(ctx, {})

        with app.state.sessionmaker() as db:
            assert [r.id for r in db.query(SessionRow).all()] == [1]
            assert [r.id for r in db.query(TrustedDevice).all()] == [1]
            assert [r.id for r in db.query(ConsoleTicket).all()] == [1]
        return result

    result = asyncio.run(scenario())
    assert result["deleted"] == {"sessions": 2, "trusted_devices": 2,
                                 "console_tickets": 2}


# --- jobs.prune -----------------------------------------------------------

def _old_job(db, job_id, kind="app.install", days_old=100):
    db.add(Job(id=job_id, kind=kind, status="succeeded",
               created_at=utcnow() - timedelta(days=days_old)))
    db.commit()
    db.add(JobEvent(job_id=job_id, seq=1, stream="stdout", message="line one"))
    db.add(JobEvent(job_id=job_id, seq=2, stream="stdout", message="line two"))
    db.commit()


def test_prune_jobs_deletes_old_jobs_and_their_events_keeps_recent(tmp_path):
    async def scenario():
        app = _app(tmp_path)
        with app.state.sessionmaker() as db:
            _seed_job(db, job_id=1, kind="jobs.prune")
            _old_job(db, job_id=2, days_old=100)
            _old_job(db, job_id=3, days_old=91)
            db.add(Job(id=4, kind="app.install", status="succeeded",
                       created_at=utcnow() - timedelta(days=10)))
            db.commit()

        backend = JobBackend(app)
        app.state.jobs = backend
        ctx = JobContext(backend, job_id=1)
        result = await maintenance.prune_jobs(ctx, {})

        with app.state.sessionmaker() as db:
            remaining_ids = {j.id for j in db.query(Job).all()}
            assert remaining_ids == {1, 4}
            assert db.query(JobEvent).filter(JobEvent.job_id.in_([2, 3])).count() == 0
        return result

    result = asyncio.run(scenario())
    assert result["kept_days"] == 90
    assert result["deleted"] == {"jobs": 2, "job_events": 4}


def test_prune_jobs_clamps_keep_days_to_the_minimum(tmp_path):
    async def scenario():
        app = _app(tmp_path)
        with app.state.sessionmaker() as db:
            _seed_job(db, job_id=1, kind="jobs.prune")
            db.add(Job(id=2, kind="app.install", status="succeeded",
                       created_at=utcnow() - timedelta(days=3)))
            db.commit()

        backend = JobBackend(app)
        app.state.jobs = backend
        ctx = JobContext(backend, job_id=1)
        result = await maintenance.prune_jobs(ctx, {"keep_days": 1})

        with app.state.sessionmaker() as db:
            assert db.get(Job, 2) is not None
        return result

    result = asyncio.run(scenario())
    assert result["kept_days"] == maintenance.MIN_KEEP_DAYS


def test_prune_jobs_deletes_everything_across_multiple_batches(tmp_path, monkeypatch):
    async def scenario():
        app = _app(tmp_path)
        monkeypatch.setattr(maintenance, "JOB_PRUNE_BATCH", 3)
        with app.state.sessionmaker() as db:
            _seed_job(db, job_id=1, kind="jobs.prune")
            for i in range(2, 12):
                _old_job(db, job_id=i, days_old=200)
            db.commit()

        backend = JobBackend(app)
        app.state.jobs = backend
        ctx = JobContext(backend, job_id=1)
        result = await maintenance.prune_jobs(ctx, {})

        with app.state.sessionmaker() as db:
            assert db.query(Job).count() == 1
            assert db.query(JobEvent).filter(JobEvent.job_id != 1).count() == 0
        return result

    result = asyncio.run(scenario())
    assert result["deleted"] == {"jobs": 10, "job_events": 20}


# --- db.compact -------------------------------------------------------------

def test_compact_db_runs_vacuum_and_optimize_on_sqlite(tmp_path):
    async def scenario():
        app = _app(tmp_path)
        with app.state.sessionmaker() as db:
            _seed_job(db, job_id=1, kind="db.compact")

        backend = JobBackend(app)
        app.state.jobs = backend
        ctx = JobContext(backend, job_id=1)
        return await maintenance.compact_db(ctx, {})

    result = asyncio.run(scenario())
    assert result["dialect"] == "sqlite"
    assert "VACUUM" in result["ran"]
    assert "PRAGMA optimize" in result["ran"]


# --- update.check -----------------------------------------------------------

def _status(**overrides):
    base = {"current": "1.2.0", "latest": None, "update_available": False,
            "notes_url": None, "channel": None, "error": None}
    base.update(overrides)
    return base


def test_check_update_reports_the_error_without_raising(tmp_path, monkeypatch):
    async def scenario():
        app = _app(tmp_path)
        with app.state.sessionmaker() as db:
            _seed_job(db, job_id=1, kind="update.check")

        monkeypatch.setattr(maintenance.updater, "check",
                            lambda settings: _status(error="could not reach the release channel"))

        backend = JobBackend(app)
        app.state.jobs = backend
        ctx = JobContext(backend, job_id=1)
        return await maintenance.check_update(ctx, {})

    result = asyncio.run(scenario())
    assert result["error"] == "could not reach the release channel"
    assert result["notified"] is False


def test_check_update_when_already_up_to_date(tmp_path, monkeypatch):
    async def scenario():
        app = _app(tmp_path)
        with app.state.sessionmaker() as db:
            _seed_job(db, job_id=1, kind="update.check")

        monkeypatch.setattr(maintenance.updater, "check",
                            lambda settings: _status(latest="1.2.0", update_available=False))

        backend = JobBackend(app)
        app.state.jobs = backend
        ctx = JobContext(backend, job_id=1)
        return await maintenance.check_update(ctx, {})

    result = asyncio.run(scenario())
    assert result["update_available"] is False
    assert result["notified"] is False


def test_check_update_notifies_when_an_update_is_available(tmp_path, monkeypatch):
    async def scenario():
        app = _app(tmp_path)
        with app.state.sessionmaker() as db:
            _seed_job(db, job_id=1, kind="update.check")

        monkeypatch.setattr(maintenance.updater, "check",
                            lambda settings: _status(latest="1.3.0", update_available=True))

        calls = []

        def fake_notify(app, event, title, body, only_ids=None):
            calls.append((event, title, body))
            return 1
        monkeypatch.setattr("proxploy.services.notifier.notify", fake_notify)

        backend = JobBackend(app)
        app.state.jobs = backend
        ctx = JobContext(backend, job_id=1)
        result = await maintenance.check_update(ctx, {})
        return result, calls

    result, calls = asyncio.run(scenario())
    assert result["update_available"] is True
    assert result["notified"] is True
    assert len(calls) == 1
    assert calls[0][0] == "update.available"


def test_check_update_skips_the_check_when_self_update_is_not_entitled(tmp_path, monkeypatch):
    async def scenario():
        app = _app(tmp_path)
        app.state.entitlements._features["platform.self_update"] = False
        with app.state.sessionmaker() as db:
            _seed_job(db, job_id=1, kind="update.check")

        called = []
        monkeypatch.setattr(maintenance.updater, "check",
                            lambda settings: called.append(True))

        backend = JobBackend(app)
        app.state.jobs = backend
        ctx = JobContext(backend, job_id=1)
        return await maintenance.check_update(ctx, {}), called

    result, called = asyncio.run(scenario())
    assert result["update_available"] is False
    assert result["message"] == "Update checks are not included in your current plan."
    assert called == []
