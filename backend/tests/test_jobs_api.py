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
            c.post("/api/v1/users", json={"email": "a@b.c", "password": "correct-horse-battery",
                                          "display_name": "A"}, headers=h)
            c.post("/api/v1/auth/login", json={"email": "a@b.c",
                                               "password": "correct-horse-battery"}, headers=h)
            job_id = _seed(app)
            body = c.get(f"/api/v1/jobs/{job_id}/events/stream").text
        assert "event: line" in body
        assert "id: 1" in body
        assert "event: status" in body
        assert '"status": "succeeded"' in body or '"status":"succeeded"' in body
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_sse_resumes_from_last_event_id(tmp_path):
    """Backlog selection is pure — assert it without a socket."""
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


def test_enqueued_job_streams_live_frames_to_a_subscriber(tmp_path):
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

        HANDLERS["test.live"] = h
        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(db, kind="test.live").id
        q = backend.subscribe(job_id)
        gate.set()
        await backend.wait(job_id, timeout=5)
        first = q.get_nowait()
        assert first["event"] == "line" and first["data"]["message"] == "live line"

    asyncio.run(run())
