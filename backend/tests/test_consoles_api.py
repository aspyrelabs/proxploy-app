"""App console + VM VNC ticket/websocket routes (doc 05 Console rows, Task 5)."""
import json

from fastapi.testclient import TestClient

from tests.fakes.pve import FakePVE
from tests.support import make_app, seed_host_row


def _seed_app(db, host):
    from proxploy.models import App

    a = App(host_id=host.id, ctid=150, name="immich", status_cached="running", slug="immich-1")
    db.add(a)
    db.commit()
    return a


def _seed_credential(app, host):
    from proxploy.models import HostCredential

    with app.state.sessionmaker() as db:
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!console", "token_secret": "s3cret"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token", encrypted_blob=blob,
                              key_version=ver))
        db.commit()


def test_console_tickets_requires_operator_and_entitlement(tmp_path, csrf_header):
    fake = FakePVE()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as client:
        with app.state.sessionmaker() as db:
            host = seed_host_row(db)
            a = _seed_app(db, host)
        r = client.post(f"/api/v1/apps/{a.id}/console/tickets", headers=csrf_header(client))
        assert r.status_code == 401  # no session at all


def test_console_tickets_mints_a_ticket_and_audits(tmp_path, csrf_header, bootstrap_admin):
    fake = FakePVE()
    fake.termproxy_response = {"user": "proxploy@pve!console", "ticket": "PVEVNC:abc",
                                "port": "5900", "upid": "UPID:pve1:...:termproxy::proxploy@pve:"}
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as client:
        bootstrap_admin(client)
        with app.state.sessionmaker() as db:
            host = seed_host_row(db)
            a = _seed_app(db, host)
            app_id = a.id
        _seed_credential(app, host)

        r = client.post(f"/api/v1/apps/{app_id}/console/tickets", headers=csrf_header(client))
        assert r.status_code == 200
        body = r.json()
        assert "ticket" in body and "expires_at" in body

        with app.state.sessionmaker() as db:
            from proxploy.models import AuditEvent
            row = db.query(AuditEvent).filter_by(action="console.open").one()
            assert row.target_type == "app" and row.target_id == app_id
            assert "ticket" not in (row.params or {})  # never audit the raw/upstream ticket


def _start_upstream_in_background_thread(expected_auth_line):
    """FakeXtermUpstream must keep accepting connections for the whole test,
    but TestClient's websocket_connect runs the route (and its ptybridge call
    into this fake) on its own portal thread's event loop -- a plain
    `asyncio.run(fake.start())` would return the server bound to a loop that's
    already closed by the time anything tries to connect to it (confirmed:
    that shape reproduces `TimeoutError: timed out during opening handshake`
    here). Run it on a persistent loop in its own thread instead, the same
    "real background server" idea test_events_sse.py uses for uvicorn."""
    import asyncio
    import threading

    from tests.fakes.pve_ws import FakeXtermUpstream

    fake_ws = FakeXtermUpstream(expected_auth_line=expected_auth_line)
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    state = {}

    def _run():
        asyncio.set_event_loop(loop)

        async def _start():
            state["url"] = await fake_ws.start()
            ready.set()

        loop.run_until_complete(_start())
        loop.run_forever()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    ready.wait(timeout=5)
    return fake_ws, state["url"], loop, thread


def _stop_upstream(fake_ws, loop, thread):
    import asyncio

    asyncio.run_coroutine_threadsafe(fake_ws.stop(), loop).result(timeout=15)
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)


def test_console_ws_bridges_after_redeeming_ticket(tmp_path, csrf_header, bootstrap_admin):
    fake = FakePVE()
    fake.termproxy_response = {"user": "proxploy@pve!console", "ticket": "PVEVNC:abc",
                               "port": "5900", "upid": "UPID:..."}
    app = make_app(tmp_path, fake=fake)

    fake_ws, url, upstream_loop, upstream_thread = _start_upstream_in_background_thread(
        "proxploy@pve!console:PVEVNC:abc\n")
    import proxploy.services.ptybridge as ptybridge_mod
    import websockets

    async def fake_ws_connect(*a, **k):
        return await websockets.connect(url, subprotocols=["binary"])

    orig = ptybridge_mod.connect_upstream_pty

    async def patched(**kwargs):
        kwargs["ws_connect"] = fake_ws_connect
        return await orig(**kwargs)
    ptybridge_mod.connect_upstream_pty = patched
    try:
        with TestClient(app) as client:
            bootstrap_admin(client)
            with app.state.sessionmaker() as db:
                host = seed_host_row(db)
                a = _seed_app(db, host)
                app_id = a.id
            _seed_credential(app, host)

            ticket = client.post(f"/api/v1/apps/{app_id}/console/tickets",
                                 headers=csrf_header(client)).json()["ticket"]

            with client.websocket_connect(f"/api/v1/apps/{app_id}/console/ws?ticket={ticket}") as ws:
                first = ws.receive_text()
                assert first == "OK"
                ws.send_text("ls\n")
                echoed = ws.receive_text()
                assert "echo:ls" in echoed
    finally:
        ptybridge_mod.connect_upstream_pty = orig
        _stop_upstream(fake_ws, upstream_loop, upstream_thread)
