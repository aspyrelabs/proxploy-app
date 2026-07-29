"""Poller loops end-to-end against FakePVE: populate, stream, degrade, recover."""
import json
import time
from pathlib import Path

FIX = Path(__file__).parent / "fixtures" / "pve"
HOST = {"name": "host-01", "address": "https://10.0.0.7:8006",
        "token_id": "proxploy@pve!mon", "token_secret": "s3cret",
        "verify_tls": True}


def _wait(fn, timeout=8.0, msg="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fn():
            return
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {msg}")


def test_poller_populates_degrades_recovers(tmp_path, csrf_header, bootstrap_admin):
    # NOTE: the brief's original draft used `with TestClient(app) as c:` for
    # everything, dropping to a real uvicorn server only for the
    # `c.stream("GET", "/api/v1/events/stream")` block. That doesn't work
    # here: TestClient starts the ASGI app on its own background "portal"
    # event loop (a real loop, in a real thread), and the Poller task +
    # EventBus live there. Spinning up a *second* uvicorn server on the same
    # `app` object — even with lifespan="off" to dodge re-running startup —
    # would serve the SSE request on uvicorn's own event loop while the
    # poller keeps publishing from TestClient's portal loop. EventBus.publish
    # does a bare `Queue.put_nowait()` with no cross-loop marshalling (see
    # proxploy/events.py), so a subscriber Queue created on one loop being
    # written to from a different loop/thread is a real race, not just a
    # style nit. Task 4's own SSE test sidesteps this by using exactly one
    # real server for the whole test and httpx.Client throughout (see
    # tests/test_events_sse.py::test_sse_streams_published_events) — so this
    # test does the same: one uvicorn server, one event loop, from host
    # creation through the SSE assertion to the degrade/recover checks.
    import socket
    import threading

    import httpx
    import uvicorn

    from tests.fakes.pve import FakePVE
    from tests.support import make_app

    fake = FakePVE(
        resources=json.loads((FIX / "cluster_resources_basic.json").read_text()),
        rrddata={"pve1": json.loads((FIX / "rrddata_hour.json").read_text())})
    app = make_app(tmp_path, fake=fake, poll_enabled=True, poll_interval_s=0.2)

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
            r = c.post("/api/v1/hosts", json=HOST, headers=csrf_header(c))
            assert r.status_code == 201, r.text
            hid = r.json()["id"]

            # within a few cycles the VM cache and snapshot populate
            _wait(lambda: c.get("/api/v1/hosts").json()[0]["status"] == "connected",
                  msg="first successful cycle")
            _wait(lambda: hid in app.state.poller.snapshots, msg="snapshot")
            snap = app.state.poller.snapshots[hid]
            assert {d["ctid"] for d in snap.discovered} == {150, 200}

            # SSE carries the poller's metrics events
            with c.stream("GET", "/api/v1/events/stream") as s:
                seen = []
                for line in s.iter_lines():
                    seen.append(line)
                    if any(ln == "event: metrics" for ln in seen):
                        break
                assert any(ln == "event: metrics" for ln in seen)

            # kill the host: only this host degrades, UI keeps serving
            fake.cluster.resources._fail = True
            _wait(lambda: c.get("/api/v1/hosts").json()[0]["status"] == "unreachable",
                  msg="degradation to unreachable")
            assert c.get("/api/v1/hosts").status_code == 200  # UI not broken

            # recovery flips it back
            fake.cluster.resources._fail = False
            _wait(lambda: c.get("/api/v1/hosts").json()[0]["status"] == "connected",
                  timeout=12.0, msg="recovery")  # generous: backoff may be in effect
    finally:
        server.should_exit = True
        thread.join(timeout=5)
