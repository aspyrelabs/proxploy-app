"""Jobs REST surface (doc 05 §Jobs) + SSE transcript stream (§Streaming 1)."""
import asyncio

from fastapi.testclient import TestClient

from proxploy.models import Job, JobEvent


def _seed(app, **kw):
    with app.state.sessionmaker() as db:
        job = Job(kind=kw.pop("kind", "app.start"), status=kw.pop("status", "succeeded"),
                  target_type="app", target_id=1, **kw)
        db.add(job)
        db.commit()
        db.add_all([
            JobEvent(job_id=job.id, seq=1, stream="stdout", message="starting CT 150"),
            JobEvent(job_id=job.id, seq=2, stream="status", message="succeeded: ok"),
        ])
        db.commit()
        return job.id


def test_list_and_detail_require_a_session(tmp_path):
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        assert c.get("/api/v1/jobs").status_code == 401
        assert c.get("/api/v1/jobs/1").status_code == 401


def test_list_filters_by_status_and_kind(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _seed(app, kind="app.start", status="succeeded")
        _seed(app, kind="vm.stop", status="failed")
        assert len(c.get("/api/v1/jobs").json()) == 2
        assert c.get("/api/v1/jobs").headers["X-Total-Count"] == "2"
        only = c.get("/api/v1/jobs?status=failed").json()
        assert [j["kind"] for j in only] == ["vm.stop"]
        assert [j["kind"] for j in c.get("/api/v1/jobs?kind=app.start").json()] == ["app.start"]
        assert [j["kind"] for j in c.get("/api/v1/jobs?target=app:1").json()] == ["vm.stop", "app.start"]


def test_detail_and_transcript(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        job_id = _seed(app)
        detail = c.get(f"/api/v1/jobs/{job_id}").json()
        assert detail["kind"] == "app.start" and detail["status"] == "succeeded"
        events = c.get(f"/api/v1/jobs/{job_id}/events").json()
        assert [e["seq"] for e in events] == [1, 2]
        assert [e["seq"] for e in c.get(f"/api/v1/jobs/{job_id}/events?after=1").json()] == [2]
        assert c.get("/api/v1/jobs/999").status_code == 404


def test_cancel_refuses_terminal_jobs(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        job_id = _seed(app, status="succeeded")
        r = c.post(f"/api/v1/jobs/{job_id}/cancel", headers=csrf_header(c))
        assert r.status_code == 409


def test_cancel_marks_a_running_job_and_audits(tmp_path, csrf_header, bootstrap_admin):
    from proxploy.models import AuditEvent
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        job_id = _seed(app, status="running")
        r = c.post(f"/api/v1/jobs/{job_id}/cancel", headers=csrf_header(c))
        assert r.status_code == 200 and r.json()["status"] == "canceled"
        with app.state.sessionmaker() as db:
            assert db.get(Job, job_id).status == "canceled"
            assert db.query(AuditEvent).filter_by(action="job.cancel").count() == 1


def test_cancel_stops_a_live_task_through_the_route(
        tmp_path, csrf_header, bootstrap_admin, monkeypatch):
    """test_cancel_marks_a_running_job_and_audits seeds a bare `running` row
    with no JobBackend task behind it, so `backend.cancel()` always returns
    False there and only the orphan-row fallback ever runs, the exact branch
    the TOCTOU bug lived in. This one enqueues a real handler so the request
    hits `backend.cancel() -> True` and the job settles via `_finish`, not
    the route's fallback UPDATE."""
    import time

    from proxploy.jobs import HANDLERS
    from proxploy.models import AuditEvent
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)

        async def slow(ctx, params):
            await asyncio.sleep(30)
            return {}

        monkeypatch.setitem(HANDLERS, "test.cancelable", slow)
        with app.state.sessionmaker() as db:
            job_id = app.state.jobs.enqueue(db, kind="test.cancelable").id

        deadline = time.monotonic() + 5
        status = None
        while status != "running" and time.monotonic() < deadline:
            with app.state.sessionmaker() as db:
                status = db.get(Job, job_id).status
            if status != "running":
                time.sleep(0.02)
        assert status == "running"

        r = c.post(f"/api/v1/jobs/{job_id}/cancel", headers=csrf_header(c))
        assert r.status_code == 200 and r.json()["status"] == "canceled"

        deadline = time.monotonic() + 5
        row = None
        while (row is None or row.status != "canceled") and time.monotonic() < deadline:
            with app.state.sessionmaker() as db:
                row = db.get(Job, job_id)
                if row.status != "canceled":
                    time.sleep(0.02)
        assert row.status == "canceled" and row.finished_at is not None
        with app.state.sessionmaker() as db:
            assert db.query(AuditEvent).filter_by(action="job.cancel").count() == 1


def test_cancel_refuses_a_job_that_finished_in_the_toctou_window(
        tmp_path, csrf_header, bootstrap_admin, monkeypatch):
    """Important 1: the route reads job.status once (still `running`), then
    calls `backend.cancel()`. If the runner's `_finish` lands in that gap, 
    `_tasks` already popped, so `cancel()` returns False; the old code blindly
    overwrote the now-`succeeded` row with `canceled`. Simulate the race by
    making the monkeypatched `cancel()` itself finish the job (mirroring what
    `_finish` really does) and return False, then assert the fallback refuses
    instead of clobbering."""
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        job_id = _seed(app, status="running")

        def race_then_miss(_job_id):
            with app.state.sessionmaker() as db:
                row = db.get(Job, job_id)
                row.status, row.result = "succeeded", {"ok": True}
                db.commit()
            return False  # no Task owns it any more by the time we ask

        monkeypatch.setattr(app.state.jobs, "cancel", race_then_miss)
        r = c.post(f"/api/v1/jobs/{job_id}/cancel", headers=csrf_header(c))
        assert r.status_code == 409
        with app.state.sessionmaker() as db:
            row = db.get(Job, job_id)
            assert row.status == "succeeded" and row.result == {"ok": True}
            assert row.error is None


def test_sse_transcript_replays_backlog_then_closes_on_terminal_status(
        tmp_path, csrf_header, bootstrap_admin):
    # Real uvicorn server + httpx: TestClient.stream() buffers forever on an
    # SSE generator (see the NOTE in tests/test_events_sse.py).
    import socket
    import threading
    import time

    import httpx
    import uvicorn

    from tests.support import make_app

    app = make_app(tmp_path)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started
        base = f"http://127.0.0.1:{port}"
        with httpx.Client(base_url=base, timeout=10) as c:
            c.get("/api/v1/meta/health")
            h = {"X-CSRF-Token": c.cookies["pp_csrf"]}
            c.post("/api/v1/users", json={"email": "a@b.c", "password": "Correct-Horse-Battery-9",
                                          "display_name": "A"}, headers=h)
            c.post("/api/v1/auth/login", json={"email": "a@b.c",
                                               "password": "Correct-Horse-Battery-9"}, headers=h)
            job_id = _seed(app)
            body = c.get(f"/api/v1/jobs/{job_id}/events/stream").text
        assert "event: line" in body
        assert "id: 1" in body
        assert "event: status" in body
        assert '"status": "succeeded"' in body or '"status":"succeeded"' in body
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_sse_dedups_a_line_written_in_the_subscribe_to_backlog_race_window(
        tmp_path, monkeypatch):
    """Important 3: a line committed between subscribe() and the backlog
    SELECT is legitimately in that SELECT's results (the row already exists)
    but was ALSO already fanned out live (subscribe() ran first), without a
    high-water mark tracked across the replay, it is emitted twice: once from
    backlog, once from the live queue. Reproduce the race deterministically:
    the patched backlog() call pushes that same row onto the subscriber
    queue itself, mirroring what real concurrent fanout does in that window.
    """
    import socket
    import threading
    import time

    import httpx
    import uvicorn

    import proxploy.api.jobs as jobs_mod
    from tests.support import make_app

    app = make_app(tmp_path)
    real_backlog = jobs_mod.backlog

    def racy_backlog(db, job_id, after=0, limit=5000):
        rows = real_backlog(db, job_id, after=after, limit=limit)
        for r in rows:
            if r["message"] == "overlap line":
                for q in list(app.state.jobs._subs.get(job_id, ())):
                    q.put_nowait({"event": "line", "id": r["seq"],
                                 "data": {"stream": r["stream"], "ts": r["ts"],
                                          "message": r["message"]}})
        return rows

    monkeypatch.setattr(jobs_mod, "backlog", racy_backlog)

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started
        base = f"http://127.0.0.1:{port}"
        with httpx.Client(base_url=base, timeout=10) as c:
            c.get("/api/v1/meta/health")
            h = {"X-CSRF-Token": c.cookies["pp_csrf"]}
            c.post("/api/v1/users", json={"email": "a@b.c", "password": "Correct-Horse-Battery-9",
                                          "display_name": "A"}, headers=h)
            c.post("/api/v1/auth/login", json={"email": "a@b.c",
                                               "password": "Correct-Horse-Battery-9"}, headers=h)
            with app.state.sessionmaker() as db:
                job = Job(kind="app.start", status="running", target_type="app", target_id=1)
                db.add(job)
                db.commit()
                job_id = job.id
                db.add(JobEvent(job_id=job_id, seq=1, stream="stdout", message="overlap line"))
                db.commit()

            async def finish_soon():
                await asyncio.sleep(0.2)
                with app.state.sessionmaker() as db:
                    db.get(Job, job_id).status = "succeeded"
                    db.add(JobEvent(job_id=job_id, seq=2, stream="status",
                                    message="succeeded: ok"))
                    db.commit()
                app.state.jobs._fanout(job_id, {"event": "status",
                                                "data": {"status": "succeeded"}})

            with c.stream("GET", f"/api/v1/jobs/{job_id}/events/stream") as r:
                app.state.loop.call_soon_threadsafe(asyncio.ensure_future, finish_soon())
                lines = []
                for line in r.iter_lines():
                    lines.append(line)
                    if any(ln == "event: status" for ln in lines):
                        break
        assert lines.count("id: 1") == 1
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_sse_resumes_from_last_event_id(tmp_path):
    """Backlog selection is pure, assert it without a socket."""
    from proxploy.api.jobs import backlog

    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app):
        job_id = _seed(app)
        with app.state.sessionmaker() as db:
            assert [e["seq"] for e in backlog(db, job_id, after=0)] == [1, 2]
            assert [e["seq"] for e in backlog(db, job_id, after=1)] == [2]
            assert backlog(db, job_id, after=2) == []


def test_stream_requires_a_session(tmp_path):
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        assert c.get("/api/v1/jobs/1/events/stream").status_code == 401


def test_enqueued_job_streams_live_frames_to_a_subscriber(tmp_path, monkeypatch):
    """The fanout path the SSE generator consumes, without HTTP."""
    from proxploy.jobs import HANDLERS, JobBackend
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        backend = JobBackend(app)
        gate = asyncio.Event()

        async def h(ctx, params):
            await gate.wait()
            ctx.log("live line")
            return {}

        monkeypatch.setitem(HANDLERS, "test.live", h)
        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(db, kind="test.live").id
        q = backend.subscribe(job_id)
        gate.set()
        await backend.wait(job_id, timeout=5)
        first = q.get_nowait()
        assert first["event"] == "line" and first["data"]["message"] == "live line"

    asyncio.run(run())
