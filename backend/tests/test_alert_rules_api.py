"""Alert rule CRUD (doc 05 §Alerts). Validation is the substance here: a rule
that can never fire is worse than no rule."""
from fastapi.testclient import TestClient

from proxploy.models import Alert, AlertRule, AuditEvent, NotificationChannel
from tests.support import make_app, seed_host_row


def _host(c):
    with c.app.state.sessionmaker() as db:
        return seed_host_row(db).id


def _body(**over):
    b = {"name": "CPU high", "metric": "cpu_pct", "target_type": "any",
         "target_id": None, "operator": "gt", "threshold": 85.0,
         "duration_s": 300, "severity": "warning", "channel_ids": [],
         "enabled": True}
    b.update(over)
    return b


def test_create_round_trips_every_field(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    h = csrf_header(client)
    r = client.post("/api/v1/alert-rules", json=_body(), headers=h)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["metric"] == "cpu_pct"
    assert body["threshold"] == 85.0
    assert body["duration_s"] == 300
    assert body["severity"] == "warning"
    assert body["target_type"] == "any" and body["target_id"] is None
    with client.app.state.sessionmaker() as db:
        assert db.query(AuditEvent).filter_by(
            action="alert.rule.create", target_id=body["id"]).count() == 1


def test_create_accepts_a_concrete_target(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    hid = _host(client)
    h = csrf_header(client)
    r = client.post("/api/v1/alert-rules",
                    json=_body(target_type="host", target_id=hid), headers=h)
    assert r.status_code == 201
    assert r.json()["target_id"] == hid


def test_rejects_an_unknown_metric(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    h = csrf_header(client)
    r = client.post("/api/v1/alert-rules", json=_body(metric="phase_of_moon"),
                    headers=h)
    assert r.status_code == 422
    assert "phase_of_moon" in r.json()["detail"]


def test_rejects_disk_pct_on_a_guest_target(client, csrf_header, bootstrap_admin):
    """The poller writes disk_pct for hosts only — a guest disk rule would sit
    enabled forever and never fire. Say so instead of accepting it."""
    bootstrap_admin(client)
    h = csrf_header(client)
    r = client.post("/api/v1/alert-rules",
                    json=_body(metric="disk_pct", target_type="app", target_id=1),
                    headers=h)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "disk_pct" in detail and "host" in detail


def test_rejects_a_target_id_that_does_not_exist(client, csrf_header,
                                                 bootstrap_admin):
    bootstrap_admin(client)
    h = csrf_header(client)
    r = client.post("/api/v1/alert-rules",
                    json=_body(target_type="host", target_id=4242), headers=h)
    assert r.status_code == 422
    assert "4242" in r.json()["detail"]


def test_rejects_any_with_a_target_id_and_a_concrete_type_without_one(
        client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    hid = _host(client)
    h = csrf_header(client)
    assert client.post("/api/v1/alert-rules",
                       json=_body(target_type="any", target_id=hid),
                       headers=h).status_code == 422
    assert client.post("/api/v1/alert-rules",
                       json=_body(target_type="host", target_id=None),
                       headers=h).status_code == 422


def test_rejects_a_bad_operator_severity_or_duration(client, csrf_header,
                                                     bootstrap_admin):
    bootstrap_admin(client)
    h = csrf_header(client)
    for bad in (_body(operator="ge"), _body(severity="apocalyptic"),
                _body(duration_s=-1)):
        assert client.post("/api/v1/alert-rules", json=bad,
                           headers=h).status_code == 422


def test_rejects_a_channel_id_that_names_no_channel(client, csrf_header,
                                                    bootstrap_admin):
    """Otherwise the rule fires and silently notifies nobody."""
    bootstrap_admin(client)
    h = csrf_header(client)
    r = client.post("/api/v1/alert-rules", json=_body(channel_ids=[99]),
                    headers=h)
    assert r.status_code == 422
    assert "99" in r.json()["detail"]


def test_accepts_a_channel_id_that_exists(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    h = csrf_header(client)
    with client.app.state.sessionmaker() as db:
        blob, ver = client.app.state.secretstore.encrypt(b"json://x/y")
        ch = NotificationChannel(name="c", kind="webhook", url_enc=blob,
                                 key_version=ver, events=[], enabled=True)
        db.add(ch)
        db.commit()
        cid = ch.id
    r = client.post("/api/v1/alert-rules", json=_body(channel_ids=[cid]),
                    headers=h)
    assert r.status_code == 201
    assert r.json()["channel_ids"] == [cid]


def test_status_metrics_do_not_require_a_threshold(client, csrf_header,
                                                   bootstrap_admin):
    """host_offline has nothing to compare — demanding a threshold would be
    theatre."""
    bootstrap_admin(client)
    hid = _host(client)
    h = csrf_header(client)
    r = client.post("/api/v1/alert-rules", headers=h, json={
        "name": "Host down", "metric": "host_offline", "target_type": "host",
        "target_id": hid, "duration_s": 300, "severity": "critical"})
    assert r.status_code == 201, r.text


def test_patch_revalidates_the_whole_rule(client, csrf_header, bootstrap_admin):
    """A PATCH that only sets target_type must still be checked against the
    STORED metric, or disk_pct-on-a-host becomes disk_pct-on-a-vm."""
    bootstrap_admin(client)
    hid = _host(client)
    h = csrf_header(client)
    rid = client.post("/api/v1/alert-rules", headers=h,
                      json=_body(metric="disk_pct", target_type="host",
                                 target_id=hid)).json()["id"]
    r = client.patch(f"/api/v1/alert-rules/{rid}",
                     json={"target_type": "vm", "target_id": 1}, headers=h)
    assert r.status_code == 422
    with client.app.state.sessionmaker() as db:
        assert db.get(AlertRule, rid).target_type == "host"   # unchanged


def test_patch_can_disable_a_rule(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    h = csrf_header(client)
    rid = client.post("/api/v1/alert-rules", json=_body(), headers=h).json()["id"]
    assert client.patch(f"/api/v1/alert-rules/{rid}", json={"enabled": False},
                        headers=h).json()["enabled"] is False


def test_delete_cascades_its_fired_alerts(client, csrf_header, bootstrap_admin):
    """alerts.rule_id is ON DELETE CASCADE (migration 0001) — assert the
    behaviour rather than trusting the DDL from memory."""
    bootstrap_admin(client)
    h = csrf_header(client)
    rid = client.post("/api/v1/alert-rules", json=_body(), headers=h).json()["id"]
    with client.app.state.sessionmaker() as db:
        db.add(Alert(rule_id=rid, target_type="host", target_id=1,
                     state="firing", value=99.0, message="x"))
        db.commit()

    assert client.delete(f"/api/v1/alert-rules/{rid}", headers=h).status_code == 204
    with client.app.state.sessionmaker() as db:
        assert db.get(AlertRule, rid) is None
        assert db.query(Alert).filter_by(rule_id=rid).count() == 0


def test_unknown_id_is_404(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    h = csrf_header(client)
    assert client.patch("/api/v1/alert-rules/9999", json={"enabled": False},
                        headers=h).status_code == 404
    assert client.delete("/api/v1/alert-rules/9999", headers=h).status_code == 404


def test_metrics_catalogue_describes_every_supported_metric(client, csrf_header,
                                                            bootstrap_admin):
    """The form in Task 16 renders from this, so the enum lives in exactly one
    place."""
    bootstrap_admin(client)
    body = client.get("/api/v1/alert-rules/metrics").json()
    by = {m["metric"]: m for m in body["metrics"]}
    assert set(by) == {"cpu_pct", "mem_pct", "disk_pct", "host_offline",
                       "backup_failed"}
    assert by["disk_pct"]["targets"] == ["host"]
    assert by["cpu_pct"]["needs_threshold"] is True
    assert by["host_offline"]["needs_threshold"] is False


def test_alerts_rules_entitlement_gates_reads_and_writes(tmp_path, csrf_header,
                                                         bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        c.app.state.entitlements._features = {"alerts.rules": False}
        assert c.get("/api/v1/alert-rules").status_code == 403
        r = c.post("/api/v1/alert-rules", json=_body(), headers=h)
        assert r.status_code == 403
        assert r.json()["feature"] == "alerts.rules"


def test_entitlement_gate_runs_after_auth_not_before(tmp_path, csrf_header):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        h = csrf_header(c)
        c.app.state.entitlements._features = {}
        assert c.get("/api/v1/alert-rules").status_code == 401
        assert c.post("/api/v1/alert-rules", json={}, headers=h).status_code == 401
