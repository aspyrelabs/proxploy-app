"""Reboot / power off a Proxmox NODE (host actions menu), doc 02 SS9 / doc 08
SS1 and SS9 row 14.

New surface, no plan ever added it. Proxmox exposes one call for both,
POST /nodes/{node}/status?command=reboot|shutdown; Proxploy gates it far
harder than a guest lifecycle action because it can take the whole node
down, and possibly Proxploy's own recovery path with it.
"""
import json

from proxploy.services.settings import set_setting


def _app(tmp_path, fail=False):
    from fastapi.testclient import TestClient
    from proxploy.models import HostCredential
    from tests.fakes.pve import FakePVE
    from tests.support import make_app, seed_host_row

    fake = FakePVE(fail=fail)
    app = make_app(tmp_path, fake=fake)
    c = TestClient(app)
    c.__enter__()
    with app.state.sessionmaker() as db:
        h = seed_host_row(db, node="pve1")
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!mon", "token_secret": "s"}).encode())
        db.add(HostCredential(host_id=h.id, kind="api_token",
                              encrypted_blob=blob, key_version=ver,
                              public_meta="proxploy@pve!mon"))
        db.commit()
        return app, c, fake, h.id


def test_an_unknown_host_is_404(tmp_path, bootstrap_admin, csrf_header):
    app, c, fake, hid = _app(tmp_path)
    bootstrap_admin(c)
    r = c.post("/api/v1/hosts/9999/nodes/pve1/power",
               json={"command": "reboot", "confirm": "pve1"}, headers=csrf_header(c))
    assert r.status_code == 404


def test_reboot_requires_the_node_name_typed_back(tmp_path, bootstrap_admin, csrf_header):
    """No confirm at all: refused, and nothing was sent to Proxmox."""
    app, c, fake, hid = _app(tmp_path)
    bootstrap_admin(c)
    r = c.post(f"/api/v1/hosts/{hid}/nodes/pve1/power",
               json={"command": "reboot"}, headers=csrf_header(c))
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["error"] == "confirm_required"
    assert body["confirm_phrase"] == "pve1"
    assert fake.node_power_calls == []


def test_reboot_is_refused_on_a_near_miss_confirm(tmp_path, bootstrap_admin, csrf_header):
    app, c, fake, hid = _app(tmp_path)
    bootstrap_admin(c)
    r = c.post(f"/api/v1/hosts/{hid}/nodes/pve1/power",
               json={"command": "reboot", "confirm": "pve1 "}, headers=csrf_header(c))
    assert r.status_code == 409
    assert fake.node_power_calls == []


def test_reboot_calls_proxmox_with_the_reboot_command_once_confirmed(
        tmp_path, bootstrap_admin, csrf_header):
    app, c, fake, hid = _app(tmp_path)
    bootstrap_admin(c)
    r = c.post(f"/api/v1/hosts/{hid}/nodes/pve1/power",
               json={"command": "reboot", "confirm": "pve1"}, headers=csrf_header(c))
    assert r.status_code == 200, r.text
    assert r.json()["is_self"] is False
    assert fake.node_power_calls == [("pve1", "reboot")]


def test_power_off_calls_proxmox_with_the_shutdown_command(
        tmp_path, bootstrap_admin, csrf_header):
    """Proxmox's own node-status verb for "power off" is `shutdown` (a clean
    ACPI power-down), never `stop`, which is a guest-only lifecycle verb."""
    app, c, fake, hid = _app(tmp_path)
    bootstrap_admin(c)
    r = c.post(f"/api/v1/hosts/{hid}/nodes/pve1/power",
               json={"command": "shutdown", "confirm": "pve1"}, headers=csrf_header(c))
    assert r.status_code == 200, r.text
    assert fake.node_power_calls == [("pve1", "shutdown")]


def test_an_unknown_command_is_a_422(tmp_path, bootstrap_admin, csrf_header):
    app, c, fake, hid = _app(tmp_path)
    bootstrap_admin(c)
    r = c.post(f"/api/v1/hosts/{hid}/nodes/pve1/power",
               json={"command": "stop", "confirm": "pve1"}, headers=csrf_header(c))
    assert r.status_code == 422


def test_a_proxmox_error_is_a_502_not_a_500(tmp_path, bootstrap_admin, csrf_header):
    app, c, fake, hid = _app(tmp_path, fail=True)
    bootstrap_admin(c)
    r = c.post(f"/api/v1/hosts/{hid}/nodes/pve1/power",
               json={"command": "reboot", "confirm": "pve1"}, headers=csrf_header(c))
    assert r.status_code == 502


def test_power_is_owner_gated(tmp_path, bootstrap_admin, csrf_header):
    """Same severity class as host.remove/host.credentials: it can take the
    whole node, and every guest on it, down."""
    app, c, fake, hid = _app(tmp_path)
    bootstrap_admin(c)
    c.post("/api/v1/users", json={"email": "admin2@example.com",
                                  "password": "correct-horse-battery",
                                  "display_name": "A2", "role": "admin"},
           headers=csrf_header(c))
    c.post("/api/v1/auth/login", json={"email": "admin2@example.com",
                                       "password": "correct-horse-battery"},
           headers=csrf_header(c))
    r = c.post(f"/api/v1/hosts/{hid}/nodes/pve1/power",
               json={"command": "reboot", "confirm": "pve1"}, headers=csrf_header(c))
    assert r.status_code == 403


def test_reboot_writes_an_audit_event(tmp_path, bootstrap_admin, csrf_header):
    from proxploy.models import AuditEvent

    app, c, fake, hid = _app(tmp_path)
    bootstrap_admin(c)
    c.post(f"/api/v1/hosts/{hid}/nodes/pve1/power",
          json={"command": "reboot", "confirm": "pve1"}, headers=csrf_header(c))
    with app.state.sessionmaker() as db:
        row = db.query(AuditEvent).filter_by(action="host.reboot").one()
        assert row.target_type == "host" and row.target_id == hid
        assert row.result == "ok"
        assert row.params["node"] == "pve1"


def test_a_denied_confirm_is_still_audited(tmp_path, bootstrap_admin, csrf_header):
    from proxploy.models import AuditEvent

    app, c, fake, hid = _app(tmp_path)
    bootstrap_admin(c)
    c.post(f"/api/v1/hosts/{hid}/nodes/pve1/power",
          json={"command": "reboot"}, headers=csrf_header(c))
    with app.state.sessionmaker() as db:
        row = db.query(AuditEvent).filter_by(action="host.reboot").one()
        assert row.result == "denied"


# --- self-guard: the node Proxploy itself runs on --------------------------

def test_the_confirm_gate_names_the_self_warning_before_the_action_runs(
        tmp_path, bootstrap_admin, csrf_header):
    """The whole point: an operator must never be surprised by this. The 409
    the typed gate returns (client shows this BEFORE the operator can type
    anything) already carries the self warning, not just the eventual 200."""
    app, c, fake, hid = _app(tmp_path)
    with app.state.sessionmaker() as db:
        set_setting(db, "self.host_id", hid)
    bootstrap_admin(c)
    r = c.post(f"/api/v1/hosts/{hid}/nodes/pve1/power",
               json={"command": "shutdown"}, headers=csrf_header(c))
    assert r.status_code == 409
    body = r.json()
    assert body["is_self"] is True
    assert "no in-band way back" in body["detail"] or "physical" in body["detail"]


def test_confirmed_self_power_off_still_goes_through(tmp_path, bootstrap_admin, csrf_header):
    """Doc 08 SS9 row 14: self-management is a typed-confirmation backstop,
    not a hard refusal -- an operator who really means it can still do it."""
    app, c, fake, hid = _app(tmp_path)
    with app.state.sessionmaker() as db:
        set_setting(db, "self.host_id", hid)
    bootstrap_admin(c)
    r = c.post(f"/api/v1/hosts/{hid}/nodes/pve1/power",
               json={"command": "shutdown", "confirm": "pve1"}, headers=csrf_header(c))
    assert r.status_code == 200, r.text
    assert r.json()["is_self"] is True
    assert fake.node_power_calls == [("pve1", "shutdown")]


def test_a_sibling_node_of_the_same_cluster_host_is_not_flagged_self(
        tmp_path, bootstrap_admin, csrf_header):
    app, c, fake, hid = _app(tmp_path)
    with app.state.sessionmaker() as db:
        set_setting(db, "self.host_id", hid)  # entry node is pve1, not pve2
    bootstrap_admin(c)
    r = c.post(f"/api/v1/hosts/{hid}/nodes/pve2/power",
               json={"command": "reboot"}, headers=csrf_header(c))
    assert r.status_code == 409
    assert r.json()["is_self"] is False
