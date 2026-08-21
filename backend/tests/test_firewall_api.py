"""Firewall routes: rules at cluster, node and security group scope
(spec: 2026-08-21)."""
import json

from fastapi.testclient import TestClient

from proxploy.models import AuditEvent, Host, HostCredential


def _seed(app):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.9:8006",
                    node_name="pve1", status="connected")
        db.add(host)
        db.commit()
        for cap in ("monitoring", "lifecycle"):
            blob, ver = app.state.secretstore.encrypt(json.dumps(
                {"token_id": f"proxploy@pve!fw-{cap}",
                 "token_secret": "s3cret"}).encode())
            db.add(HostCredential(host_id=host.id, kind=f"api_token:{cap}",
                                  encrypted_blob=blob, key_version=ver))
        db.commit()
        return host.id


def _fake():
    from tests.fakes.pve import FakePVE
    return FakePVE()


def test_cluster_rules_read(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app
    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app)
        fake.firewall_data["cluster/firewall/rules"] = [
            {"pos": 0, "type": "in", "action": "ACCEPT", "proto": "tcp",
             "dport": "22", "enable": 1, "comment": "ssh"},
        ]
        r = c.get(f"/api/v1/firewall/cluster/{host_id}/rules")
        assert r.status_code == 200
        body = r.json()
        assert body["rules"][0]["comment"] == "ssh"
        assert body["scope"] == "cluster"


def test_rule_create_records_audit_and_uses_the_lifecycle_token(
        tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app
    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app)
        r = c.post(f"/api/v1/firewall/cluster/{host_id}/rules",
                   headers=csrf_header(c),
                   json={"type": "in", "action": "ACCEPT", "proto": "tcp",
                         "dport": "22", "enable": 1, "comment": "ssh"})
        assert r.status_code == 201
        verb, path, params = fake.firewall_writes[0]
        assert (verb, path) == ("post", "cluster/firewall/rules")
        assert params["dport"] == "22"
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="firewall.rule_create").one()
            assert row.result == "ok"


def test_icmp_type_reaches_pve_hyphenated(tmp_path, csrf_header, bootstrap_admin):
    """The wire name has a hyphen and cannot be a Python identifier, so the
    model aliases it and the dump is by_alias. A snake_case leak drops it."""
    from tests.support import make_app
    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app)
        c.post(f"/api/v1/firewall/cluster/{host_id}/rules", headers=csrf_header(c),
              json={"type": "in", "action": "ACCEPT", "proto": "icmp",
                    "icmp-type": "echo-request"})
        _, _, params = fake.firewall_writes[0]
        assert params["icmp-type"] == "echo-request"
        assert "icmp_type" not in params


def test_rule_move_sends_only_moveto(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app
    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app)
        r = c.put(f"/api/v1/firewall/cluster/{host_id}/rules/3/move",
                  headers=csrf_header(c), json={"moveto": 1, "digest": "d1"})
        assert r.status_code == 200
        _, path, params = fake.firewall_writes[0]
        assert path == "cluster/firewall/rules/3"
        assert params == {"moveto": 1, "digest": "d1"}


def test_group_rules_go_to_the_group_path(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app
    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app)
        c.post(f"/api/v1/firewall/cluster/{host_id}/groups/web/rules",
              headers=csrf_header(c), json={"type": "in", "action": "DROP"})
        _, path, _ = fake.firewall_writes[0]
        assert path == "cluster/firewall/groups/web"


def test_node_rules_path(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app
    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app)
        c.post(f"/api/v1/firewall/node/{host_id}/pve1/rules",
              headers=csrf_header(c), json={"type": "in", "action": "ACCEPT"})
        _, path, _ = fake.firewall_writes[0]
        assert path == "nodes/pve1/firewall/rules"


def test_unreachable_pve_is_a_502_and_an_error_audit_row(
        tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app
    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app)
        fake.fail = True
        r = c.post(f"/api/v1/firewall/cluster/{host_id}/rules",
                   headers=csrf_header(c),
                   json={"type": "in", "action": "ACCEPT"})
        assert r.status_code == 502
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="firewall.rule_create").one()
            assert row.result == "error"


def test_unknown_host_is_404(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app
    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        assert c.get("/api/v1/firewall/cluster/999/rules").status_code == 404
