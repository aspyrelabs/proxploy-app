"""In-process event bus + SSE fanout endpoint (doc 05 §Streaming 4)."""
import asyncio


def test_bus_fanout_and_slow_consumer_drop():
    from proxploy.events import EventBus

    async def run():
        bus = EventBus()
        q1, q2 = bus.subscribe(), bus.subscribe()
        bus.publish("metrics", {"targets": []})
        assert q1.get_nowait() == ("metrics", {"targets": []})
        assert q2.get_nowait() == ("metrics", {"targets": []})
        bus.unsubscribe(q2)
        bus.publish("resource", {"type": "app"})
        assert q1.get_nowait()[0] == "resource"
        assert q2.empty()
        # a full queue drops instead of blocking the publisher
        small = bus.subscribe()
        for _ in range(500):
            bus.publish("metrics", {})
        assert small.full()

    asyncio.run(run())


def test_sse_requires_session(tmp_path):
    from fastapi.testclient import TestClient
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        r = c.get("/api/v1/events/stream")
        assert r.status_code == 401


def test_sse_streams_published_events(tmp_path, csrf_header, bootstrap_admin):
    # NOTE: this can't use fastapi.testclient.TestClient here. The installed
    # starlette (1.3.1) TestClient's _TestClientTransport.handle_request runs
    # the whole ASGI app via a single blocking `portal.call(...)` and only
    # returns once the app coroutine *fully finishes* (fully buffering the
    # body first): verified with a minimal repro outside of any proxploy
    # code. Our SSE generator is intentionally infinite (a persistent
    # connection), so that call never returns and TestClient.stream() hangs
    # forever, regardless of app.state.loop wiring. A real server thread +
    # real httpx.Client gives genuine incremental reads over a socket.
    import socket
    import threading
    import time

    import httpx
    import uvicorn

    from tests.support import make_app

    app = make_app(tmp_path)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                if httpx.get(f"{base}/api/v1/meta/health").status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        else:
            raise RuntimeError("server did not start")

        with httpx.Client(base_url=base) as c:
            bootstrap_admin(c)

            # publish from the app's own loop once the subscriber is attached
            async def publish_soon():
                await asyncio.sleep(0.2)
                app.state.bus.publish("metrics", {"targets": [{"t": "host", "id": 1}]})

            with c.stream("GET", "/api/v1/events/stream") as r:
                assert r.headers["content-type"].startswith("text/event-stream")
                app.state.loop.call_soon_threadsafe(asyncio.ensure_future, publish_soon())
                lines = []
                for line in r.iter_lines():
                    lines.append(line)
                    if any(ln.startswith("data:") for ln in lines):
                        break
                assert any(ln == "event: metrics" for ln in lines)
                assert any('"t": "host"' in ln or '"t":"host"' in ln
                           for ln in lines if ln.startswith("data:"))
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_the_live_stream_denies_an_authenticated_user_with_no_membership(tmp_path,
                                                                         csrf_header):
    """GET /events/stream used to check only that a session resolved, not what
    the user was allowed to see. This bus carries host, app, job and alert
    deltas for the whole cluster, so an account with no team membership --
    denied every other route by Phase 8 amendment A1 -- could still watch the
    entire system through it. Now it runs the same authorize("meta","read")
    the rest of the product does, invoked directly because a StreamingResponse
    must not hold a DI-scoped DB session open for the life of the connection.

    Found by test_rbac_invariant.py only AFTER its route walk was fixed; the
    original walk matched zero routes and passed vacuously.
    """
    from fastapi.testclient import TestClient

    from proxploy.models import TeamMember, User
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        h = csrf_header(c)
        c.post("/api/v1/users", json={"email": "own@x.io",
               "password": "Correct-Horse-Battery-9"}, headers=h)   # bootstrap owner
        c.post("/api/v1/auth/login", json={"email": "own@x.io",
               "password": "Correct-Horse-Battery-9"}, headers=h)
        c.post("/api/v1/users", json={"email": "orphan@x.io", "role": "viewer",
               "password": "Correct-Horse-Battery-9"}, headers=h)
        c.post("/api/v1/auth/logout", headers=h)

        # Strip the membership POST /users granted, leaving a real account
        # that belongs to nothing: the A1 case.
        with app.state.sessionmaker() as db:
            orphan = db.query(User).filter_by(email="orphan@x.io").one()
            db.query(TeamMember).filter_by(user_id=orphan.id).delete()
            db.commit()
            from proxploy.services.authz import sync_user
            sync_user(app.state.authz, db, orphan.id)

        c.post("/api/v1/auth/login", json={"email": "orphan@x.io",
               "password": "Correct-Horse-Battery-9"}, headers=h)
        assert c.get("/api/v1/events/stream").status_code == 403
