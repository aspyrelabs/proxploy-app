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
    # body first) — verified with a minimal repro outside of any proxploy
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
