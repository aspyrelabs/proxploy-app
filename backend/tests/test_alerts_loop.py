"""The evaluator riding the poll loop (doc 10 Phase 7)."""
import asyncio

from proxploy.models import Alert, AlertRule, MetricSample, utcnow
from proxploy.pollers import Poller
from tests.support import make_job_app, seed_host_row


def _seed(app, threshold=85.0):
    with app.state.sessionmaker() as db:
        host = seed_host_row(db)
        db.add(AlertRule(name="CPU high", metric="cpu_pct", target_type="host",
                         target_id=host.id, operator="gt", threshold=threshold,
                         duration_s=0, severity="warning", channel_ids=[],
                         enabled=True))
        db.add(MetricSample(target_type="host", target_id=host.id,
                            metric="cpu_pct", value=99.0, ts=utcnow()))
        db.commit()
        return host.id


def test_the_supervisor_pass_evaluates_and_publishes_an_alert_event(tmp_path):
    async def go():
        app = make_job_app(tmp_path)
        app.state.settings = app.state.settings.model_copy(
            update={"poll_interval_s": 0.01, "alerts_enabled": True})
        app.state.poller = Poller(app)
        _seed(app)

        q = app.state.bus.subscribe()
        task = asyncio.create_task(app.state.poller.run())
        frame = None
        for _ in range(300):
            try:
                name, data = q.get_nowait()
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.01)
                continue
            if name == "alert":
                frame = data
                break
        task.cancel()
        app.state.poller.stop()

        assert frame is not None, "no alert event was published"
        assert frame["state"] == "firing"
        assert frame["severity"] == "warning"
        assert set(frame) == {"id", "state", "severity", "message"}
        with app.state.sessionmaker() as db:
            assert db.query(Alert).filter_by(state="firing").count() == 1

    asyncio.run(go())


def test_alerts_disabled_evaluates_nothing(tmp_path):
    async def go():
        app = make_job_app(tmp_path)
        app.state.settings = app.state.settings.model_copy(
            update={"poll_interval_s": 0.01, "alerts_enabled": False})
        app.state.poller = Poller(app)
        _seed(app)

        task = asyncio.create_task(app.state.poller.run())
        await asyncio.sleep(0.2)
        task.cancel()
        app.state.poller.stop()

        with app.state.sessionmaker() as db:
            assert db.query(Alert).count() == 0

    asyncio.run(go())


def test_an_evaluator_failure_never_kills_the_supervisor(tmp_path, monkeypatch):
    """The supervisor also (re)spawns host loops — if alerting can kill it,
    one bad rule stops all polling."""
    async def go():
        app = make_job_app(tmp_path)
        app.state.settings = app.state.settings.model_copy(
            update={"poll_interval_s": 0.01, "alerts_enabled": True})
        app.state.poller = Poller(app)
        _seed(app)

        calls = {"n": 0}

        def boom(db, now=None):
            calls["n"] += 1
            raise RuntimeError("database is locked")

        monkeypatch.setattr("proxploy.services.alerts.evaluate", boom)
        task = asyncio.create_task(app.state.poller.run())
        await asyncio.sleep(0.2)
        task.cancel()
        app.state.poller.stop()
        assert calls["n"] >= 3          # kept ticking after each raise

    asyncio.run(go())


def test_a_notifier_failure_does_not_lose_the_sse_event(tmp_path, monkeypatch):
    """The UI badge must still update when a webhook is down."""
    async def go():
        app = make_job_app(tmp_path)
        app.state.settings = app.state.settings.model_copy(
            update={"poll_interval_s": 0.01, "alerts_enabled": True})
        app.state.poller = Poller(app)
        _seed(app)

        monkeypatch.setattr(
            "proxploy.services.alerts.notify_transitions",
            lambda a, t: (_ for _ in ()).throw(RuntimeError("smtp down")))

        q = app.state.bus.subscribe()
        task = asyncio.create_task(app.state.poller.run())
        seen = False
        for _ in range(300):
            try:
                name, _data = q.get_nowait()
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.01)
                continue
            if name == "alert":
                seen = True
                break
        task.cancel()
        app.state.poller.stop()
        assert seen

    asyncio.run(go())
