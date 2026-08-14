"""The Scheduler loop, its system-schedule seeding, and metrics.maintain."""
import asyncio
from datetime import datetime, timedelta

from proxploy.jobs.scheduler import (
    SYSTEM_SCHEDULES, Scheduler, seed_system_schedules,
)
from proxploy.models import Job, MetricRollup, MetricSample, Schedule, utcnow
from tests.support import make_db, make_job_app


def test_seeding_is_idempotent_and_covers_every_system_schedule(tmp_path):
    db = make_db(tmp_path)
    assert seed_system_schedules(db) == len(SYSTEM_SCHEDULES)
    assert seed_system_schedules(db) == 0          # second boot adds nothing
    names = {s.name for s in db.query(Schedule).all()}
    assert names == {s["name"] for s in SYSTEM_SCHEDULES}
    for row in db.query(Schedule).all():
        assert row.enabled is True
        assert row.created_by is None              # system-owned, not a user


def test_seeding_does_not_resurrect_a_system_schedule_the_operator_disabled(tmp_path):
    """Re-enabling on every boot would make "turn off the nightly catalog
    refresh" impossible to express."""
    db = make_db(tmp_path)
    seed_system_schedules(db)
    row = db.query(Schedule).filter_by(name=SYSTEM_SCHEDULES[0]["name"]).one()
    row.enabled = False
    db.commit()

    assert seed_system_schedules(db) == 0
    db.refresh(row)
    assert row.enabled is False


def test_every_system_schedule_names_a_registered_handler():
    """Seeding a kind with no handler would disable itself on first tick."""
    from proxploy.jobs import HANDLERS
    import proxploy.services.metrics          # noqa: F401  (registers metrics.maintain)
    import proxploy.services.catalog          # noqa: F401  (registers catalog.refresh)
    for s in SYSTEM_SCHEDULES:
        assert s["job_kind"] in HANDLERS, s["name"]


def test_loop_fires_a_ripe_schedule_then_stops_cleanly(tmp_path):
    async def go():
        app = make_job_app(tmp_path)
        from proxploy.jobs import JobBackend
        app.state.jobs = JobBackend(app)
        app.state.settings = app.state.settings.model_copy(
            update={"scheduler_tick_s": 0.01})
        with app.state.sessionmaker() as db:
            db.add(Schedule(name="soon", job_kind="catalog.refresh",
                            cron="* * * * *", timezone="UTC", enabled=True,
                            next_run_at=utcnow() - timedelta(minutes=1)))
            db.commit()

        sched = Scheduler(app)
        task = asyncio.create_task(sched.run())
        for _ in range(200):                      # ~2 s ceiling
            await asyncio.sleep(0.01)
            with app.state.sessionmaker() as db:
                if db.query(Job).count():
                    break
        sched.stop()
        task.cancel()

        with app.state.sessionmaker() as db:
            jobs = db.query(Job).all()
        assert len(jobs) >= 1
        assert jobs[0].kind == "catalog.refresh"
        assert jobs[0].schedule_id is not None

    asyncio.run(go())


def test_loop_survives_a_tick_that_raises(tmp_path):
    """A supervisor that dies on one bad tick stops every future schedule."""
    async def go():
        app = make_job_app(tmp_path)
        from proxploy.jobs import JobBackend
        app.state.jobs = JobBackend(app)
        app.state.settings = app.state.settings.model_copy(
            update={"scheduler_tick_s": 0.01})

        calls = {"n": 0}
        import proxploy.jobs.scheduler as mod
        real = mod.tick

        def boom(a, now=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("db locked")
            return real(a, now)

        mod.tick, sched = boom, Scheduler(app)
        try:
            task = asyncio.create_task(sched.run())
            for _ in range(200):
                await asyncio.sleep(0.01)
                if calls["n"] >= 3:
                    break
            sched.stop()
            task.cancel()
        finally:
            mod.tick = real
        assert calls["n"] >= 3     # kept ticking after the raise

    asyncio.run(go())


# --- metrics.maintain -------------------------------------------------------

def test_metrics_maintain_rolls_up_and_prunes(tmp_path):
    async def go():
        from proxploy.jobs import HANDLERS, JobContext
        from proxploy.services import metrics as m

        app = make_job_app(tmp_path)
        from proxploy.jobs import JobBackend
        app.state.jobs = JobBackend(app)
        now = utcnow()
        with app.state.sessionmaker() as db:
            # in-window samples that must roll up ...
            for i in range(6):
                db.add(MetricSample(target_type="host", target_id=1,
                                    metric="cpu_pct", value=10.0 + i,
                                    ts=now - timedelta(minutes=20 + i)))
            # ... and one older than RAW_RETENTION_H that must be pruned.
            db.add(MetricSample(target_type="host", target_id=1,
                                metric="cpu_pct", value=99.0,
                                ts=now - timedelta(hours=m.RAW_RETENTION_H + 1)))
            db.commit()
            job = Job(kind="metrics.maintain", status="running")
            db.add(job)
            db.commit()
            job_id = job.id

        ctx = JobContext(app.state.jobs, job_id)
        out = await HANDLERS["metrics.maintain"](ctx, {})

        assert out["pruned"]["raw"] == 1
        assert out["rollups"]["5m"] >= 1
        with app.state.sessionmaker() as db:
            assert db.query(MetricRollup).filter_by(resolution="5m").count() >= 1
            assert db.query(MetricSample).filter(
                MetricSample.value == 99.0).count() == 0

    asyncio.run(go())


def test_metrics_loop_is_gone():
    """It was replaced by the metrics.maintain schedule (doc 04: "All pruning
    runs as scheduled system jobs, visible in the activity feed")."""
    from proxploy.services import metrics
    assert not hasattr(metrics, "metrics_loop")


def test_renaming_a_system_schedule_needs_a_migration_not_just_the_constant(tmp_path):
    """seed_system_schedules keys on `name` and only ever inserts, so a renamed
    constant reads as a schedule that does not exist yet.

    Left to itself that seeds a SECOND row for the same job kind and both fire
    on the same cron. Migration c7a1e4f80b93 renames the existing row instead,
    and this pins the property that makes the migration necessary, so nobody
    renames another system schedule by editing SYSTEM_SCHEDULES alone.
    """
    db = make_db(tmp_path)
    seed_system_schedules(db)
    row = db.query(Schedule).filter_by(job_kind="metrics.maintain").one()
    assert row.name == "Usage cleanup"

    # Stand in for the pre-migration database: the row exists under its old
    # name, which is exactly the state a running install is in.
    row.name = "Metrics maintenance"
    db.commit()
    assert seed_system_schedules(db) == 1

    kinds = [s.job_kind for s in db.query(Schedule).all()]
    assert kinds.count("metrics.maintain") == 2, (
        "seeding duplicated the job rather than renaming it, which is the "
        "outcome the migration exists to prevent")
