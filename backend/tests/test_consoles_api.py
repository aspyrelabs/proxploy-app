"""App console + VM VNC ticket/websocket routes (doc 05 Console rows, Task 5)."""
import json

import pytest
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

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
        db.add(HostCredential(host_id=host.id, kind="api_token:console", encrypted_blob=blob,
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
                # No literal "OK" sentinel is sent (finding #7) -- the fake
                # upstream here has no scripted output_lines, so there is no
                # buffered prompt to flush either (finding #2); the first
                # thing the browser should see is the echo of what it sends.
                ws.send_text("ls\n")
                echoed = ws.receive_text()
                assert "echo:ls" in echoed
    finally:
        ptybridge_mod.connect_upstream_pty = orig
        _stop_upstream(fake_ws, upstream_loop, upstream_thread)


def test_shell_ticket_requires_node_shell_enabled(tmp_path, csrf_header, bootstrap_admin):
    fake = FakePVE()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as client:
        bootstrap_admin(client)
        with app.state.sessionmaker() as db:
            host = seed_host_row(db)  # node_shell_enabled defaults False
            host_id = host.id
        _seed_credential(app, host)

        r = client.post(f"/api/v1/hosts/{host_id}/shell/tickets", headers=csrf_header(client))
        assert r.status_code == 409
        assert "node shell" in r.json()["detail"].lower()


def test_shell_ticket_mints_after_toggling_on_and_audits(tmp_path, csrf_header, bootstrap_admin):
    fake = FakePVE()
    fake.termproxy_response = {"user": "proxploy@pve!console", "ticket": "PVEVNC:abc",
                                "port": "5900", "upid": "UPID:pve1:...:termproxy::proxploy@pve:"}
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as client:
        bootstrap_admin(client)
        with app.state.sessionmaker() as db:
            host = seed_host_row(db)
            host_id = host.id
        _seed_credential(app, host)

        r = client.patch(f"/api/v1/hosts/{host_id}", json={"node_shell_enabled": True},
                         headers=csrf_header(client))
        assert r.status_code == 200

        r = client.post(f"/api/v1/hosts/{host_id}/shell/tickets", headers=csrf_header(client))
        assert r.status_code == 200
        body = r.json()
        assert "ticket" in body and "expires_at" in body
        assert fake.last_node_termproxy_call == "pve1"

        with app.state.sessionmaker() as db:
            from proxploy.models import AuditEvent
            row = db.query(AuditEvent).filter_by(action="console.open").one()
            assert row.target_type == "host" and row.target_id == host_id


def test_mismatched_ticket_kind_is_rejected(tmp_path, csrf_header, bootstrap_admin):
    """Finding #14: an app_console ticket must not be redeemable at the
    node-shell WS route (or vice versa) just because _run_pty_ws is shared
    and would otherwise permissively dispatch on whatever kind it finds."""
    fake = FakePVE()
    fake.termproxy_response = {"user": "proxploy@pve!console", "ticket": "PVEVNC:abc",
                                "port": "5900", "upid": "UPID:..."}
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as client:
        bootstrap_admin(client)
        with app.state.sessionmaker() as db:
            host = seed_host_row(db)
            a = _seed_app(db, host)
            app_id, host_id = a.id, host.id
        _seed_credential(app, host)

        ticket = client.post(f"/api/v1/apps/{app_id}/console/tickets",
                             headers=csrf_header(client)).json()["ticket"]

        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/api/v1/hosts/{host_id}/shell/ws?ticket={ticket}"):
                pass


def test_deleted_app_during_ticket_ttl_closes_cleanly_not_500(tmp_path, csrf_header, bootstrap_admin):
    """Finding #17: if the App row a ticket points at is deleted during the
    ticket's short TTL window, redemption must not AttributeError-crash on
    `db.get(App, row.target_id).host_id` -- it should close with a clean
    4404, same shape as an unknown/expired ticket."""
    fake = FakePVE()
    fake.termproxy_response = {"user": "proxploy@pve!console", "ticket": "PVEVNC:abc",
                                "port": "5900", "upid": "UPID:..."}
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as client:
        bootstrap_admin(client)
        with app.state.sessionmaker() as db:
            host = seed_host_row(db)
            a = _seed_app(db, host)
            app_id = a.id
        _seed_credential(app, host)

        ticket = client.post(f"/api/v1/apps/{app_id}/console/tickets",
                             headers=csrf_header(client)).json()["ticket"]

        with app.state.sessionmaker() as db:
            from proxploy.models import App
            db.query(App).filter_by(id=app_id).delete()
            db.commit()

        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/api/v1/apps/{app_id}/console/ws?ticket={ticket}"):
                pass


def test_vm_vnc_ws_closes_with_reason_on_connect_upstream_vnc_error(tmp_path, csrf_header,
                                                                     bootstrap_admin, monkeypatch):
    """Finding #8: a ConsoleProxyError from connect_upstream_vnc (e.g. a
    TLS-pin mismatch) must not be an unhandled exception / bare abnormal
    close -- vm_vnc_ws should catch it and close with a code/reason the
    browser can show."""
    from proxploy.models import Vm

    fake = FakePVE()
    fake.vncproxy_response = {"user": "proxploy@pve!console", "ticket": "PVEVNC:def",
                              "port": "5902", "cert": "-----BEGIN CERTIFICATE-----...",
                              "upid": "UPID:..."}
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as client:
        bootstrap_admin(client)
        with app.state.sessionmaker() as db:
            host = seed_host_row(db)
            v = Vm(host_id=host.id, vmid=200, name="win11", status="running")
            db.add(v)
            db.commit()
            vm_id = v.id
        _seed_credential(app, host)

        ticket = client.post(f"/api/v1/vms/{vm_id}/console/tickets",
                             headers=csrf_header(client)).json()["ticket"]

        import proxploy.api.consoles as consoles_mod
        from proxploy.services.consoleproxy import ConsoleProxyError

        async def boom(**kwargs):
            raise ConsoleProxyError("TLS fingerprint mismatch: pinned AA, got BB")
        monkeypatch.setattr(consoles_mod, "connect_upstream_vnc", boom)

        # accept() already happened by this point (host resolution succeeded),
        # so the reject is a close *after* handshake, not a denial during
        # it -- receive_bytes() is what surfaces that as WebSocketDisconnect.
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(f"/api/v1/vms/{vm_id}/vnc/ws?ticket={ticket}") as ws:
                ws.receive_bytes()
        assert exc_info.value.code == 1011
        assert "mismatch" in exc_info.value.reason


def _seed_app_with_status(db, host, status, ctid=160, name="redis"):
    from proxploy.models import App

    a = App(host_id=host.id, ctid=ctid, name=name, status_cached=status,
            slug=f"{name}-{ctid}")
    db.add(a)
    db.commit()
    return a


def test_console_ticket_refuses_a_stopped_guest(tmp_path, csrf_header, bootstrap_admin):
    """A stopped guest still gets a termproxy ticket from PVE, and the socket
    then attaches to a PTY that never emits a byte: the operator sees a blank
    terminal with no error at all. Confirmed on PVE 9.2.6, 2026-08-10, where
    connecting to a stopped CT succeeded and returned nothing, forever.
    """
    app = make_app(tmp_path, fake=FakePVE())
    with TestClient(app) as client:
        bootstrap_admin(client)
        with app.state.sessionmaker() as db:
            host = seed_host_row(db)
            app_id = _seed_app_with_status(db, host, "stopped").id
        _seed_credential(app, host)

        r = client.post(f"/api/v1/apps/{app_id}/console/tickets",
                        headers=csrf_header(client))
        assert r.status_code == 409, r.text
        # main.py's RFC7807 handler merges a dict detail into the top level,
        # so `error` sits beside `detail`, it is not nested under it.
        body = r.json()
        assert body["error"] == "guest_not_running"
        assert "start it" in body["detail"].lower()


def test_console_ticket_allows_a_guest_whose_status_is_unknown(tmp_path, csrf_header,
                                                               bootstrap_admin):
    """Fail OPEN on an unknown status. Blocking a console because the poller
    has not filled the cache yet would be a worse failure than the blank
    terminal the stopped-guest check exists to prevent."""
    fake = FakePVE()
    fake.termproxy_response = {"user": "proxploy@pve!console", "ticket": "PVEVNC:abc",
                               "port": "5900", "upid": "UPID:pve1:...:termproxy::x:"}
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as client:
        bootstrap_admin(client)
        with app.state.sessionmaker() as db:
            host = seed_host_row(db)
            app_id = _seed_app_with_status(db, host, None, ctid=161, name="fresh").id
        _seed_credential(app, host)

        r = client.post(f"/api/v1/apps/{app_id}/console/tickets",
                        headers=csrf_header(client))
        assert r.status_code == 200, r.text
