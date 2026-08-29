"""Guest firewall routes on the apps and VMs routers (spec: 2026-08-21).

Mounted on those routers rather than the firewall one because scope_app() and
scope_vm() read the target out of request.path_params and nothing else: a guest
id in a query parameter would carry no team scope at all.
"""
import json

from fastapi.testclient import TestClient

from proxploy.models import App, AuditEvent, Host, HostCredential, Vm


def _seed(app):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.9:8006",
                    node_name="pve1", status="connected")
        db.add(host)
        db.commit()
        # console too: a GUEST firewall log needs VM.Console, which PVE
        # gates it behind rather than VM.Audit, so it reads on the
        # console credential (services/firewall.py::guest_log_reader).
        for cap in ("monitoring", "lifecycle", "console"):
            blob, ver = app.state.secretstore.encrypt(json.dumps(
                {"token_id": f"proxploy@pve!fw-{cap}",
                 "token_secret": "s3cret"}).encode())
            db.add(HostCredential(host_id=host.id, kind=f"api_token:{cap}",
                                  encrypted_blob=blob, key_version=ver))
        a = App(host_id=host.id, ctid=150, name="Immich", slug="immich",
                node_name="pve2")
        v = Vm(host_id=host.id, vmid=201, name="win11", status="running",
               node_name="pve1")
        db.add_all([a, v])
        db.commit()
        return a.id, v.id


def _fake():
    from tests.fakes.pve import FakePVE
    return FakePVE()


def test_app_rules_use_lxc_and_the_guests_own_node(tmp_path, csrf_header,
                                                    bootstrap_admin):
    """pve2, not the host's entry node pve1. On a cluster the host's own node
    reaches the wrong machine for every guest it does not own."""
    from tests.support import make_app
    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        app_id, vm_id = _seed(app)
        fake.firewall_data["nodes/pve2/lxc/150/firewall/rules"] = [
            {"pos": 0, "type": "in", "action": "ACCEPT"}]
        r = c.get(f"/api/v1/apps/{app_id}/firewall/rules")
        assert r.status_code == 200
        assert r.json()["rules"][0]["action"] == "ACCEPT"


def test_vm_rules_use_qemu(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app
    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        app_id, vm_id = _seed(app)
        c.post(f"/api/v1/vms/{vm_id}/firewall/rules", headers=csrf_header(c),
               json={"type": "in", "action": "ACCEPT"})
        _, path, _ = fake.firewall_writes[0]
        assert path == "nodes/pve1/qemu/201/firewall/rules"


def test_app_options_read_carries_the_guest_defaults(tmp_path, csrf_header,
                                                      bootstrap_admin):
    from tests.support import make_app
    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        app_id, vm_id = _seed(app)
        fake.firewall_data["nodes/pve2/lxc/150/firewall/options"] = {"digest": "d1"}
        body = c.get(f"/api/v1/apps/{app_id}/firewall/options").json()
        assert body["defaults"]["macfilter"] == 1
        assert body["defaults"]["policy_in"] == "DROP"


def test_app_ipset_member_path_escapes_the_cidr(tmp_path, csrf_header,
                                                 bootstrap_admin):
    from tests.support import make_app
    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        app_id, vm_id = _seed(app)
        c.delete(
            f"/api/v1/apps/{app_id}/firewall/ipsets/trusted/members/10.0.0.0%2F8",
            headers=csrf_header(c))
        _, path, _ = fake.firewall_writes[0]
        assert path == "nodes/pve2/lxc/150/firewall/ipset/trusted/10.0.0.0%2F8"


def test_app_rule_create_is_audited_against_the_app(tmp_path, csrf_header,
                                                     bootstrap_admin):
    from tests.support import make_app
    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        app_id, vm_id = _seed(app)
        c.post(f"/api/v1/apps/{app_id}/firewall/rules", headers=csrf_header(c),
               json={"type": "in", "action": "ACCEPT", "dport": "80"})
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="firewall.rule_create").one()
            assert row.target_type == "app"
            assert "Immich" in row.target_name


def test_firewall_route_is_not_swallowed_by_the_action_wildcard(
        tmp_path, csrf_header, bootstrap_admin):
    """apps.py ends with /{app_id}/{action}. Registered after it, this path
    matches as an action called "firewall" and never reaches the handler."""
    from tests.support import make_app
    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        app_id, vm_id = _seed(app)
        assert c.get(f"/api/v1/apps/{app_id}/firewall/rules").status_code == 200


def test_app_log_reads_the_guest_log(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app
    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        app_id, vm_id = _seed(app)
        fake.firewall_data["nodes/pve2/lxc/150/firewall/log"] = [
            {"n": 1, "t": "drop"}]
        body = c.get(f"/api/v1/apps/{app_id}/firewall/log").json()
        assert body["lines"][0]["t"] == "drop"
