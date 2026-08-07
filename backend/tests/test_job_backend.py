"""JobBackend semantics (doc 02 §3, doc 03 job-engine row): persistence,
queued->running->terminal, cancel, per-job fanout, orphan sweep."""
import asyncio

from proxploy.models import Job, JobEvent


def test_enqueue_runs_a_handler_and_persists_the_transcript(tmp_path, monkeypatch):
    from proxploy.jobs import HANDLERS, JobBackend
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        backend = JobBackend(app)

        async def demo(ctx, params):
            ctx.log("hello")
            ctx.progress(50)
            return {"echo": params["x"]}

        monkeypatch.setitem(HANDLERS, "test.demo", demo)
        with app.state.sessionmaker() as db:
            job = backend.enqueue(db, kind="test.demo", target_type="system",
                                  params={"x": 7})
            job_id = job.id
        assert await backend.wait(job_id, timeout=5) is True
        with app.state.sessionmaker() as db:
            row = db.get(Job, job_id)
            assert row.status == "succeeded"
            assert row.result == {"echo": 7}
            assert row.progress_pct == 100
            assert row.started_at is not None and row.finished_at is not None
            lines = (db.query(JobEvent).filter_by(job_id=job_id)
                     .order_by(JobEvent.seq).all())
            assert [(e.seq, e.stream, e.message) for e in lines][0] == (1, "stdout", "hello")
            assert lines[-1].stream == "status" and "succeeded" in lines[-1].message

    asyncio.run(run())


def test_failed_handler_records_failed_status_and_error(tmp_path, monkeypatch):
    from proxploy.jobs import HANDLERS, JobBackend, JobFailed
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        backend = JobBackend(app)

        async def boom(ctx, params):
            raise JobFailed("exitstatus: disk full")

        monkeypatch.setitem(HANDLERS, "test.boom", boom)
        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(db, kind="test.boom").id
        assert await backend.wait(job_id, timeout=5) is True
        with app.state.sessionmaker() as db:
            row = db.get(Job, job_id)
            assert row.status == "failed"
            assert "disk full" in row.error

    asyncio.run(run())


def test_unexpected_exception_in_handler_is_recorded_as_failed(tmp_path, monkeypatch):
    """The bare `except Exception` path (a handler bug), not JobFailed."""
    from proxploy.jobs import HANDLERS, JobBackend
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        backend = JobBackend(app)

        async def buggy(ctx, params):
            raise ValueError("boom")

        monkeypatch.setitem(HANDLERS, "test.buggy", buggy)
        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(db, kind="test.buggy").id
        assert await backend.wait(job_id, timeout=5) is True
        with app.state.sessionmaker() as db:
            row = db.get(Job, job_id)
            assert row.status == "failed"
            assert "ValueError" in row.error and "boom" in row.error

    asyncio.run(run())


def test_cancel_stops_a_running_job_cleanly(tmp_path, monkeypatch):
    from proxploy.jobs import HANDLERS, JobBackend
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        backend = JobBackend(app)
        started = asyncio.Event()

        async def slow(ctx, params):
            ctx.log("working")
            started.set()
            await asyncio.sleep(30)
            return {}

        monkeypatch.setitem(HANDLERS, "test.slow", slow)
        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(db, kind="test.slow").id
        await asyncio.wait_for(started.wait(), timeout=5)
        assert backend.cancel(job_id) is True
        assert await backend.wait(job_id, timeout=5) is True
        with app.state.sessionmaker() as db:
            row = db.get(Job, job_id)
            assert row.status == "canceled"
            assert row.finished_at is not None
        assert backend.cancel(job_id) is False  # already terminal

    asyncio.run(run())


def test_cancel_of_a_still_queued_job_finishes_it_and_keeps_the_pool_healthy(
        tmp_path, monkeypatch):
    """Critical fix: a job cancelled while still blocked acquiring the
    Semaphore (i.e. `queued`, never got to run) must still land in `canceled`
    with finished_at + a status job_event, and must not leak/corrupt the
    semaphore so the four running jobs behind it still complete normally."""
    from proxploy.jobs import HANDLERS, JobBackend
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        backend = JobBackend(app)
        gate = asyncio.Event()
        started = [asyncio.Event() for _ in range(4)]

        async def blocker(ctx, params):
            started[params["i"]].set()
            await gate.wait()
            return {}

        monkeypatch.setitem(HANDLERS, "test.blocker", blocker)
        with app.state.sessionmaker() as db:
            runner_ids = [backend.enqueue(db, kind="test.blocker", params={"i": i}).id
                          for i in range(4)]
        await asyncio.gather(*(asyncio.wait_for(e.wait(), timeout=5) for e in started))

        async def victim(ctx, params):
            return {}  # must never run: queued behind a full semaphore

        monkeypatch.setitem(HANDLERS, "test.victim", victim)
        with app.state.sessionmaker() as db:
            victim_id = backend.enqueue(db, kind="test.victim").id
        # Let `_spawn` create the victim's Task and block it on `_sem.acquire()`.
        await asyncio.sleep(0.02)

        assert backend.cancel(victim_id) is True
        assert await backend.wait(victim_id, timeout=5) is True
        with app.state.sessionmaker() as db:
            row = db.get(Job, victim_id)
            assert row.status == "canceled"
            assert row.finished_at is not None
            events = (db.query(JobEvent).filter_by(job_id=victim_id)
                      .order_by(JobEvent.seq).all())
            assert any(e.stream == "status" and "canceled" in e.message for e in events)

        gate.set()  # release the 4 runners; semaphore must still work for them
        for rid in runner_ids:
            assert await backend.wait(rid, timeout=5) is True
        with app.state.sessionmaker() as db:
            for rid in runner_ids:
                assert db.get(Job, rid).status == "succeeded"

    asyncio.run(run())


def test_cancel_of_a_job_still_in__pending_is_honoured_even_with_the_pool_full(
        tmp_path, monkeypatch):
    """Distinct from test_cancel_of_a_still_queued_job_...: that test lets
    `_spawn` run first (job already in `_tasks`, blocked on `_sem.acquire()`)
    before cancelling, which `cancel()` handles via a direct `task.cancel()`.
    Here `cancel()` is called in the same synchronous breath as `enqueue()`,
    before the loop has had a turn to run `_spawn`, job_id is still in
    `_pending`, so `cancel()` can only record intent in `_cancel_requested`.
    With MAX_CONCURRENT hogs holding every slot and never releasing them
    during this test, the old code (which checked `_cancel_requested` only
    after acquiring the semaphore) would leave this job stuck `queued`
    forever. It must land `canceled` promptly regardless of pool pressure."""
    from proxploy.jobs import HANDLERS, JobBackend
    from proxploy.jobs.backend import MAX_CONCURRENT
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        backend = JobBackend(app)
        gate = asyncio.Event()
        started = [asyncio.Event() for _ in range(MAX_CONCURRENT)]

        async def hog(ctx, params):
            started[params["i"]].set()
            await gate.wait()
            return {}

        monkeypatch.setitem(HANDLERS, "test.hog", hog)
        with app.state.sessionmaker() as db:
            hog_ids = [backend.enqueue(db, kind="test.hog", params={"i": i}).id
                      for i in range(MAX_CONCURRENT)]
        await asyncio.gather(*(asyncio.wait_for(e.wait(), timeout=5) for e in started))

        async def victim(ctx, params):
            return {}  # must never run: cancelled before it even got a Task

        monkeypatch.setitem(HANDLERS, "test.victim", victim)
        with app.state.sessionmaker() as db:
            victim_id = backend.enqueue(db, kind="test.victim").id
        # No `await` between enqueue and cancel: `_spawn` (scheduled via
        # call_soon_threadsafe) has not run yet, so victim_id is still in
        # `_pending`, not `_tasks`: this is the pre-spawn window.
        assert backend.cancel(victim_id) is True

        assert await backend.wait(victim_id, timeout=1) is True  # not 0.5s of `queued`
        with app.state.sessionmaker() as db:
            row = db.get(Job, victim_id)
            assert row.status == "canceled"
            assert row.finished_at is not None

        gate.set()  # release the hogs; pool must still work for them
        for hid in hog_ids:
            assert await backend.wait(hid, timeout=5) is True
        with app.state.sessionmaker() as db:
            for hid in hog_ids:
                assert db.get(Job, hid).status == "succeeded"

    asyncio.run(run())


def test_semaphore_caps_concurrency_at_four(tmp_path, monkeypatch):
    from proxploy.jobs import HANDLERS, JobBackend
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        backend = JobBackend(app)
        gate = asyncio.Event()
        started = [asyncio.Event() for _ in range(6)]

        async def worker(ctx, params):
            started[params["i"]].set()
            await gate.wait()
            return {}

        monkeypatch.setitem(HANDLERS, "test.worker", worker)
        with app.state.sessionmaker() as db:
            ids = [backend.enqueue(db, kind="test.worker", params={"i": i}).id
                   for i in range(6)]
        await asyncio.gather(*(asyncio.wait_for(started[i].wait(), timeout=5)
                                for i in range(4)))
        await asyncio.sleep(0.02)  # give 5 and 6 a chance to (wrongly) start too
        assert not started[4].is_set() and not started[5].is_set()

        gate.set()
        for job_id in ids:
            assert await backend.wait(job_id, timeout=5) is True
        with app.state.sessionmaker() as db:
            assert all(db.get(Job, job_id).status == "succeeded" for job_id in ids)

    asyncio.run(run())


def test_subscribers_receive_line_progress_and_status_frames(tmp_path, monkeypatch):
    from proxploy.jobs import HANDLERS, JobBackend
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        backend = JobBackend(app)
        gate = asyncio.Event()

        async def chatty(ctx, params):
            await gate.wait()
            ctx.log("one")
            ctx.progress(30)
            return {"ok": True}

        monkeypatch.setitem(HANDLERS, "test.chatty", chatty)
        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(db, kind="test.chatty").id
        q = backend.subscribe(job_id)
        gate.set()
        assert await backend.wait(job_id, timeout=5) is True
        frames = []
        while not q.empty():
            frames.append(q.get_nowait())
        kinds = [f["event"] for f in frames]
        assert kinds == ["line", "progress", "status"]
        assert frames[0]["id"] == 1
        assert frames[1]["data"] == {"pct": 30}
        assert frames[2]["data"]["status"] == "succeeded"

    asyncio.run(run())


def test_sweep_orphans_marks_interrupted_and_never_resumes(tmp_path):
    from proxploy.jobs import JobBackend
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            db.add_all([Job(kind="app.start", status="running"),
                        Job(kind="app.stop", status="queued"),
                        Job(kind="app.stop", status="succeeded")])
            db.commit()
        backend = JobBackend(app)
        assert backend.sweep_orphans() == 2
        # Drain the fire-and-forget notify task before the loop closes, 
        # hermetic teardown (no channels here, so it's a no-op notify(), but
        # asyncio.run() tearing down a still-pending task is exactly the
        # "does real work during teardown" hazard this test should not risk).
        for _ in range(50):
            if not backend._side:
                break
            await asyncio.sleep(0.05)
        with app.state.sessionmaker() as db:
            states = sorted(j.status for j in db.query(Job).all())
            assert states == ["interrupted", "interrupted", "succeeded"]
            assert all(j.finished_at is not None for j in db.query(Job)
                       .filter_by(status="interrupted"))

    asyncio.run(run())


def test_enqueue_rejects_unknown_kinds(tmp_path):
    import pytest

    from proxploy.jobs import JobBackend
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        backend = JobBackend(app)
        with app.state.sessionmaker() as db:
            with pytest.raises(KeyError):
                backend.enqueue(db, kind="nope.nothing")

    asyncio.run(run())
