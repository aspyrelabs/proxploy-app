"""Scheduler core (doc 10 Phase 7, doc 04 `schedules`).

These are the pure pieces — cron math, due selection, one firing pass. The
loop that calls `tick` lives in Task 2 and is tested separately.
"""
import asyncio
from datetime import datetime

import pytest

from proxploy.jobs.scheduler import (
    BadSchedule, due, fire_one, next_fire, prime, tick, validate,
)
from proxploy.models import AuditEvent, Job, Schedule
from tests.support import make_db, make_job_app


def _sched(db, **kw):
    kw.setdefault("name", "nightly")
    kw.setdefault("job_kind", "catalog.refresh")
    kw.setdefault("cron", "0 3 * * *")
    kw.setdefault("timezone", "UTC")
    kw.setdefault("enabled", True)
    row = Schedule(**kw)
    db.add(row)
    db.commit()
    return row


# --- next_fire --------------------------------------------------------------

def test_next_fire_is_naive_utc_in_and_out():
    got = next_fire("0 3 * * *", "UTC", datetime(2026, 8, 1, 12, 0))
    assert got == datetime(2026, 8, 2, 3, 0)
    assert got.tzinfo is None


def test_next_fire_converts_a_local_timezone_to_utc():
    # 03:00 America/New_York on 2026-08-02 is 07:00 UTC (EDT, UTC-4).
    assert next_fire("0 3 * * *", "America/New_York",
                     datetime(2026, 8, 1, 12, 0)) == datetime(2026, 8, 2, 7, 0)
    # 03:00 Asia/Kolkata is 21:30 UTC the previous day (UTC+5:30).
    assert next_fire("0 3 * * *", "Asia/Kolkata",
                     datetime(2026, 8, 1, 12, 0)) == datetime(2026, 8, 1, 21, 30)


def test_next_fire_at_the_boundary_advances_rather_than_repeating():
    """`after` == a firing instant must yield the NEXT one. Without this a
    schedule fires again on every tick until the minute rolls over."""
    assert next_fire("0 3 * * *", "UTC",
                     datetime(2026, 8, 2, 3, 0)) == datetime(2026, 8, 3, 3, 0)


@pytest.mark.parametrize("cron", ["bogus", "0 3 * * * *", "99 3 * * *", ""])
def test_next_fire_rejects_malformed_cron(cron):
    with pytest.raises(BadSchedule):
        next_fire(cron, "UTC", datetime(2026, 8, 1, 12, 0))


def test_next_fire_rejects_an_unknown_timezone():
    # zoneinfo raises ZoneInfoNotFoundError, which subclasses KeyError, not
    # ValueError — both have to be caught or this escapes as a 500.
    with pytest.raises(BadSchedule):
        next_fire("0 3 * * *", "Not/AZone", datetime(2026, 8, 1, 12, 0))


def test_validate_rejects_an_unregistered_job_kind():
    validate("0 3 * * *", "UTC", "catalog.refresh")  # registered, no raise
    with pytest.raises(BadSchedule) as e:
        validate("0 3 * * *", "UTC", "app.doesnotexist")
    assert "app.doesnotexist" in str(e.value)


# --- prime / due ------------------------------------------------------------

def test_prime_fills_next_run_at_only_where_it_is_missing(tmp_path):
    db = make_db(tmp_path)
    fresh = _sched(db, name="fresh")
    already = _sched(db, name="already", next_run_at=datetime(2030, 1, 1))
    off = _sched(db, name="off", enabled=False)

    assert prime(db, datetime(2026, 8, 1, 12, 0)) == 1
    db.refresh(fresh); db.refresh(already); db.refresh(off)
    assert fresh.next_run_at == datetime(2026, 8, 2, 3, 0)
    assert already.next_run_at == datetime(2030, 1, 1)   # untouched
    assert off.next_run_at is None                        # disabled rows are not primed


def test_prime_disables_a_row_whose_cron_no_longer_parses(tmp_path):
    """A hand-edited DB, or a tz dropped from the host's tzdata. One bad row
    must not make prime() raise and take the whole tick with it."""
    db = make_db(tmp_path)
    bad = _sched(db, name="bad", cron="not a cron")
    assert prime(db, datetime(2026, 8, 1, 12, 0)) == 0
    db.refresh(bad)
    assert bad.enabled is False
    assert bad.next_run_at is None


def test_due_returns_only_enabled_rows_that_are_ripe_oldest_first(tmp_path):
    db = make_db(tmp_path)
    now = datetime(2026, 8, 1, 12, 0)
    late = _sched(db, name="late", next_run_at=datetime(2026, 8, 1, 10, 0))
    ripe = _sched(db, name="ripe", next_run_at=now)
    _sched(db, name="future", next_run_at=datetime(2026, 8, 1, 13, 0))
    _sched(db, name="disabled", enabled=False, next_run_at=datetime(2026, 1, 1))
    _sched(db, name="unprimed", next_run_at=None)

    assert [s.id for s in due(db, now)] == [late.id, ripe.id]


# --- fire_one ---------------------------------------------------------------

def test_fire_one_enqueues_stamps_and_advances(tmp_path):
    async def go():
        app = make_job_app(tmp_path)
        from proxploy.jobs import JobBackend
        app.state.jobs = JobBackend(app)
        now = datetime(2026, 8, 1, 12, 0)
        with app.state.sessionmaker() as db:
            s = _sched(db, next_run_at=now)
            out = fire_one(app, db, s, now)
            assert out["schedule_id"] == s.id
            assert out["kind"] == "catalog.refresh"

            job = db.get(Job, out["job_id"])
            assert job.kind == "catalog.refresh"
            assert job.schedule_id == s.id
            assert job.requested_by is None        # system-spawned, doc 04
            assert job.target_type == "system"

            db.refresh(s)
            assert s.last_run_at == now
            # advanced from `now`, NOT from the stale next_run_at — a week of
            # downtime must produce one catch-up run, not one per missed day.
            assert s.next_run_at == datetime(2026, 8, 2, 3, 0)

            row = (db.query(AuditEvent)
                   .filter_by(action="schedule.fire", target_id=s.id).one())
            assert row.actor_type == "system"
            assert row.actor_id is None
            assert row.job_id == out["job_id"]

    asyncio.run(go())


def test_fire_one_derives_the_job_target_from_params(tmp_path):
    async def go():
        app = make_job_app(tmp_path)
        from proxploy.jobs import JobBackend
        app.state.jobs = JobBackend(app)
        now = datetime(2026, 8, 1, 12, 0)
        with app.state.sessionmaker() as db:
            s = _sched(db, job_kind="backup.run", params={"host_id": 7},
                       next_run_at=now)
            out = fire_one(app, db, s, now)
            job = db.get(Job, out["job_id"])
            assert (job.target_type, job.target_id) == ("host", 7)
            assert job.params == {"host_id": 7}

    asyncio.run(go())


def test_fire_one_disables_a_schedule_whose_handler_vanished(tmp_path):
    """A job kind can disappear across an upgrade. Enqueue would raise KeyError
    and kill the tick; instead the row is disabled with an audit trail."""
    async def go():
        app = make_job_app(tmp_path)
        from proxploy.jobs import JobBackend
        app.state.jobs = JobBackend(app)
        now = datetime(2026, 8, 1, 12, 0)
        with app.state.sessionmaker() as db:
            s = _sched(db, job_kind="gone.forever", next_run_at=now)
            assert fire_one(app, db, s, now) is None
            db.refresh(s)
            assert s.enabled is False
            row = (db.query(AuditEvent)
                   .filter_by(action="schedule.disable", target_id=s.id).one())
            assert row.result == "error"
            assert db.query(Job).count() == 0

    asyncio.run(go())


# --- tick -------------------------------------------------------------------

def test_tick_primes_then_fires_and_is_idempotent_within_the_minute(tmp_path):
    async def go():
        app = make_job_app(tmp_path)
        from proxploy.jobs import JobBackend
        app.state.jobs = JobBackend(app)
        with app.state.sessionmaker() as db:
            _sched(db, name="hourly", cron="0 * * * *")

        # 11:59 — primed to 12:00, nothing due yet.
        assert tick(app, datetime(2026, 8, 1, 11, 59)) == []
        # 12:00 — fires once.
        first = tick(app, datetime(2026, 8, 1, 12, 0))
        assert len(first) == 1
        # 12:00:30 — the row now points at 13:00, so the same tick does not
        # re-fire it. This is the regression the boundary rule above prevents.
        assert tick(app, datetime(2026, 8, 1, 12, 0, 30)) == []

        with app.state.sessionmaker() as db:
            assert db.query(Job).count() == 1

    asyncio.run(go())
