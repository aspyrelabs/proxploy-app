"""GET /alerts and POST /alerts/{id}/ack (doc 05 §Alerts)."""
from datetime import timedelta

from proxploy.models import Alert, AlertRule, AuditEvent, utcnow
from tests.support import seed_host_row


def _seed(c):
    with c.app.state.sessionmaker() as db:
        host = seed_host_row(db)
        rule = AlertRule(name="CPU high", metric="cpu_pct", target_type="host",
                         target_id=host.id, operator="gt", threshold=85.0,
                         duration_s=300, severity="warning", channel_ids=[],
                         enabled=True)
        db.add(rule)
        db.commit()
        now = utcnow()
        firing = Alert(rule_id=rule.id, target_type="host", target_id=host.id,
                       state="firing", value=92.0, message="host-01 CPU > 85%",
                       fired_at=now)
        old = Alert(rule_id=rule.id, target_type="host", target_id=host.id,
                    state="resolved", value=10.0, message="Resolved: host-01 CPU",
                    fired_at=now - timedelta(hours=2),
                    resolved_at=now - timedelta(hours=1))
        db.add_all([firing, old])
        db.commit()
        return rule.id, firing.id, old.id, host.id


def test_list_returns_both_states_newest_first(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    _rid, firing, old, _ = _seed(client)
    rows = client.get("/api/v1/alerts").json()
    assert [r["id"] for r in rows] == [firing, old]


def test_state_filter_narrows_to_firing(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    _rid, firing, _old, _ = _seed(client)
    rows = client.get("/api/v1/alerts?state=firing").json()
    assert [r["id"] for r in rows] == [firing]


def test_each_row_carries_its_rule_name_and_target_label(client, csrf_header,
                                                         bootstrap_admin):
    """The Alerts table and the bell tray both render these; without them
    every row would need a second and third fetch."""
    bootstrap_admin(client)
    _seed(client)
    row = client.get("/api/v1/alerts?state=firing").json()[0]
    assert row["rule_name"] == "CPU high"
    assert row["severity"] == "warning"
    assert row["target_label"] == "host-01"
    assert row["fired_at"].endswith("Z")


def test_a_target_deleted_since_firing_still_renders(client, csrf_header,
                                                     bootstrap_admin):
    """History outlives the host it was about."""
    bootstrap_admin(client)
    _rid, firing, _old, host_id = _seed(client)
    with client.app.state.sessionmaker() as db:
        from proxploy.models import Host
        db.delete(db.get(Host, host_id))
        db.commit()
    row = next(r for r in client.get("/api/v1/alerts").json() if r["id"] == firing)
    assert row["target_label"] is None      # honest gap, not a crash


def test_limit_is_bounded(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    _seed(client)
    assert len(client.get("/api/v1/alerts?limit=1").json()) == 1
    # absurd values are clamped rather than 500ing or dumping the table
    assert client.get("/api/v1/alerts?limit=100000").status_code == 200


def test_ack_stamps_the_user_and_audits(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    _rid, firing, _old, _ = _seed(client)
    h = csrf_header(client)
    r = client.post(f"/api/v1/alerts/{firing}/ack", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["acked_by"] is not None
    assert body["acked_by_email"] == "admin@example.com"
    assert body["acked_at"] is not None
    assert body["state"] == "firing"          # ack silences, it does not resolve
    with client.app.state.sessionmaker() as db:
        assert db.query(AuditEvent).filter_by(
            action="alert.ack", target_id=firing).count() == 1


def test_acking_twice_is_idempotent_and_keeps_the_first_acker(client, csrf_header,
                                                              bootstrap_admin):
    bootstrap_admin(client)
    _rid, firing, _old, _ = _seed(client)
    h = csrf_header(client)
    first = client.post(f"/api/v1/alerts/{firing}/ack", headers=h).json()
    second = client.post(f"/api/v1/alerts/{firing}/ack", headers=h).json()
    assert second["acked_at"] == first["acked_at"]


def test_ack_404s_an_unknown_alert(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    h = csrf_header(client)
    assert client.post("/api/v1/alerts/9999/ack", headers=h).status_code == 404


def test_alerts_are_readable_without_any_entitlement(tmp_path, csrf_header,
                                                     bootstrap_admin):
    """Doc 05 leaves the entitlement column blank for GET /alerts: the Alerts
    page and the bell tray must work on every tier, including the free
    one."""
    from fastapi.testclient import TestClient
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        c.app.state.entitlements._features = {}
        assert c.get("/api/v1/alerts?state=firing").status_code == 200
