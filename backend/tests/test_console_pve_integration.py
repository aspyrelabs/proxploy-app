"""Needs a disposable live PVE (PROXPLOY_TEST_PVE_* env, same gate as
tests/test_pve_integration.py -- every pve_integration test in this repo
shares that one convention). Proves-or-disproves this plan's documented open
question: does this host's termproxy accept API-token auth for LXC/node-shell
consoles (doc's "Spike correction" note -- fixed for VMs in qemu-server
9.1.7+, unconfirmed for the LXC/node-shell path, Proxmox bugzilla #6079)."""
import json
import os

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.pve_integration

REQUIRED = ("PROXPLOY_TEST_PVE_URL", "PROXPLOY_TEST_PVE_TOKEN_ID",
            "PROXPLOY_TEST_PVE_TOKEN_SECRET", "PROXPLOY_TEST_PVE_NODE",
            "PROXPLOY_TEST_PVE_CTID")


@pytest.mark.skipif(not all(os.environ.get(k) for k in REQUIRED),
                    reason="disposable PVE env not configured (needs URL/TOKEN_ID/"
                           "TOKEN_SECRET/NODE/CTID for a real, already-running LXC "
                           "container safe to open a console against)")
def test_app_console_ticket_and_ws_against_real_pve(tmp_path, csrf_header, bootstrap_admin):
    """Exercises POST /apps/{id}/console/tickets and WS /apps/{id}/console/ws
    against the real host from PROXPLOY_TEST_PVE_* env, through the real
    ProxmoxClient (no FakePVE) and the real connect_upstream_pty (no patched
    ws_connect) -- the one path in this whole phase that has never run against
    genuine Proxmox termproxy auth.

    Either outcome below is a PASS for this test: a working PTY round-trip
    (this PVE/qemu-server version accepts API-token termproxy auth for LXC),
    or the PtyBridgeError message this plan's Task 3 makes explicit for the
    known token/termproxy limitation (this version still rejects it). A bare
    hang/timeout is the only failure -- that would mean the bridge doesn't
    even surface the known failure mode cleanly.
    """
    from proxploy.config import Settings
    from proxploy.main import create_app
    from proxploy.services.proxmox import ProxmoxClient

    url = os.environ["PROXPLOY_TEST_PVE_URL"]
    token_id = os.environ["PROXPLOY_TEST_PVE_TOKEN_ID"]
    token_secret = os.environ["PROXPLOY_TEST_PVE_TOKEN_SECRET"]
    node = os.environ["PROXPLOY_TEST_PVE_NODE"]
    ctid = int(os.environ["PROXPLOY_TEST_PVE_CTID"])
    verify_tls = os.environ.get("PROXPLOY_TEST_PVE_VERIFY", "0") == "1"

    # Real reachability/version check first (same precondition
    # test_pve_integration.py itself asserts) so a bad env fails loudly here
    # rather than deep inside a ticket-mint 500.
    client_probe = ProxmoxClient(url, token_id, token_secret, verify_tls=verify_tls)
    v = client_probe.version()
    assert v["release"].split(".")[0] in ("8", "9")

    s = Settings(db_url=f"sqlite:///{tmp_path}/t.db", data_dir=tmp_path,
                master_key_file=tmp_path / "master.key", poll_enabled=False)
    app = create_app(s)
    with TestClient(app) as client:
        bootstrap_admin(client)
        with app.state.sessionmaker() as db:
            from proxploy.models import App, Host, HostCredential

            host = Host(name="live-pve", address=url, node_name=node, status="connected")
            db.add(host)
            db.commit()
            blob, ver = app.state.secretstore.encrypt(
                json.dumps({"token_id": token_id, "token_secret": token_secret}).encode())
            db.add(HostCredential(host_id=host.id, kind="api_token", encrypted_blob=blob,
                                  key_version=ver))
            a = App(host_id=host.id, ctid=ctid, name="live-ct", status_cached="running",
                    slug="live-ct-pve-integration")
            db.add(a)
            db.commit()
            app_id = a.id

        r = client.post(f"/api/v1/apps/{app_id}/console/tickets", headers=csrf_header(client))
        assert r.status_code == 200, r.text
        ticket = r.json()["ticket"]

        with client.websocket_connect(
                f"/api/v1/apps/{app_id}/console/ws?ticket={ticket}", timeout=15) as ws:
            first = ws.receive_text()
            if first == "OK":
                # Termproxy accepted API-token auth -- Proxmox bugzilla #6079
                # is fixed (or never applied) for the LXC/node-shell path on
                # this host's PVE/qemu-server version.
                ws.send_text("echo proxploy-pve-integration\n")
                ws.receive_text()  # any further frame proves the PTY is alive
            else:
                # Handshake rejected -- must be the documented, explicit
                # PtyBridgeError exit frame, not a silent hang or a different
                # kind of failure.
                payload = json.loads(first)
                assert payload["type"] == "exit"
                assert "termproxy" in payload.get("error", "").lower()
