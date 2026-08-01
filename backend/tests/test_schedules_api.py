"""Schedules CRUD (doc 05 §Schedules)."""
from proxploy.models import AuditEvent, Job, Schedule
from tests.support import make_app

from fastapi.testclient import TestClient


def _admin(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    return csrf_header(client)


def _create(client, h, **over):
    body = {"name": "Nightly backup", "job_kind": "backup.run",
            "cron": "0 2 * * *", "timezone": "Europe/Berlin",
            "params": {"host_id": 1}}
    body.update(over)
    return client.post("/api/v1/schedules", json=body, headers=h)


def test_create_computes_next_run_at_and_audits(client, csrf_header, bootstrap_admin):
    h = _admin(client, csrf_header, bootstrap_admin)
    r = _create(client, h)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Nightly backup"
    assert body["job_kind"] == "backup.run"
    assert body["enabled"] is True
    assert body["next_run_at"] is not None       # primed at write time
    assert body["last_run_at"] is None

    with client.app.state.sessionmaker() as db:
        row = db.get(Schedule, body["id"])
        assert row.timezone == "Europe/Berlin"
        assert row.created_by is not None        # user-created, unlike system rows
        assert db.query(AuditEvent).filter_by(
            action="schedule.create", target_id=row.id).count() == 1


def test_create_rejects_a_malformed_cron_with_422(client, csrf_header, bootstrap_admin):
    h = _admin(client, csrf_header, bootstrap_admin)
    r = _create(client, h, cron="every tuesday")
    assert r.status_code == 422
    assert "cron" in r.json()["detail"].lower()


def test_create_rejects_an_unknown_timezone_with_422(client, csrf_header, bootstrap_admin):
    h = _admin(client, csrf_header, bootstrap_admin)
    r = _create(client, h, timezone="Mars/Olympus")
    assert r.status_code == 422


def test_create_rejects_a_job_kind_with_no_handler(client, csrf_header, bootstrap_admin):
    """Otherwise the row seeds, ticks once, and silently disables itself."""
    h = _admin(client, csrf_header, bootstrap_admin)
    r = _create(client, h, job_kind="app.teleport")
    assert r.status_code == 422
    assert "app.teleport" in r.json()["detail"]


def test_patch_recomputes_next_run_at_only_when_the_trigger_changed(
        client, csrf_header, bootstrap_admin):
    h = _admin(client, csrf_header, bootstrap_admin)
    sid = _create(client, h).json()["id"]
    before = client.get("/api/v1/schedules").json()[0]["next_run_at"]

    # A name change must NOT move the firing time.
    r = client.patch(f"/api/v1/schedules/{sid}", json={"name": "Renamed"}, headers=h)
    assert r.status_code == 200
    assert r.json()["next_run_at"] == before
    assert r.json()["name"] == "Renamed"

    # A cron change must.
    r = client.patch(f"/api/v1/schedules/{sid}", json={"cron": "30 5 * * *"},
                     headers=h)
    assert r.status_code == 200
    assert r.json()["next_run_at"] != before


def test_disabling_clears_next_run_at_and_re_enabling_restores_it(
        client, csrf_header, bootstrap_admin):
    """A disabled row with a stale next_run_at in the past would fire the
    instant it is re-enabled, which is not what "enable" means."""
    h = _admin(client, csrf_header, bootstrap_admin)
    sid = _create(client, h).json()["id"]

    off = client.patch(f"/api/v1/schedules/{sid}", json={"enabled": False},
                       headers=h).json()
    assert off["enabled"] is False and off["next_run_at"] is None

    on = client.patch(f"/api/v1/schedules/{sid}", json={"enabled": True},
                      headers=h).json()
    assert on["enabled"] is True and on["next_run_at"] is not None


def test_patch_rejects_a_bad_cron_without_corrupting_the_stored_row(
        client, csrf_header, bootstrap_admin):
    h = _admin(client, csrf_header, bootstrap_admin)
    sid = _create(client, h).json()["id"]
    assert client.patch(f"/api/v1/schedules/{sid}", json={"cron": "nope"},
                        headers=h).status_code == 422
    with client.app.state.sessionmaker() as db:
        assert db.get(Schedule, sid).cron == "0 2 * * *"   # unchanged


def test_run_now_enqueues_the_schedules_job_and_stamps_last_run(
        client, csrf_header, bootstrap_admin):
    h = _admin(client, csrf_header, bootstrap_admin)
    sid = _create(client, h, job_kind="catalog.refresh", params={}).json()["id"]

    r = client.post(f"/api/v1/schedules/{sid}/run", headers=h)
    assert r.status_code == 202, r.text
    job = r.json()["job"]
    assert job["kind"] == "catalog.refresh"
    assert job["schedule_id"] == sid

    with client.app.state.sessionmaker() as db:
        assert db.get(Job, job["id"]).requested_by is not None   # a human asked
        assert db.get(Schedule, sid).last_run_at is not None


def test_run_now_does_not_move_next_run_at(client, csrf_header, bootstrap_admin):
    """"Run now" is an extra run, not a reschedule — the window still opens
    when the operator said it would."""
    h = _admin(client, csrf_header, bootstrap_admin)
    sid = _create(client, h, job_kind="catalog.refresh", params={}).json()["id"]
    before = client.get("/api/v1/schedules").json()[0]["next_run_at"]
    client.post(f"/api/v1/schedules/{sid}/run", headers=h)
    assert client.get("/api/v1/schedules").json()[0]["next_run_at"] == before


def test_delete_removes_the_row_and_audits(client, csrf_header, bootstrap_admin):
    h = _admin(client, csrf_header, bootstrap_admin)
    sid = _create(client, h).json()["id"]
    assert client.delete(f"/api/v1/schedules/{sid}", headers=h).status_code == 204
    with client.app.state.sessionmaker() as db:
        assert db.get(Schedule, sid) is None
        assert db.query(AuditEvent).filter_by(
            action="schedule.delete", target_id=sid).count() == 1


def test_unknown_id_is_404_on_every_verb(client, csrf_header, bootstrap_admin):
    h = _admin(client, csrf_header, bootstrap_admin)
    assert client.patch("/api/v1/schedules/9999", json={"name": "x"},
                        headers=h).status_code == 404
    assert client.delete("/api/v1/schedules/9999", headers=h).status_code == 404
    assert client.post("/api/v1/schedules/9999/run", headers=h).status_code == 404


def test_auto_update_entitlement_gates_app_update_schedules_only(
        tmp_path, csrf_header, bootstrap_admin):
    """Doc 05: `sched.windows`; `store.auto_update` when job_kind=app.update.
    A backup schedule must stay creatable when only auto-update is off."""
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        c.app.state.entitlements._features = {"sched.windows": True,
                                              "store.auto_update": False}
        blocked = c.post("/api/v1/schedules", headers=h, json={
            "name": "Auto update", "job_kind": "app.update", "cron": "0 3 * * 0",
            "timezone": "UTC", "params": {"app_id": 1}})
        assert blocked.status_code == 403
        assert blocked.json()["feature"] == "store.auto_update"

        allowed = c.post("/api/v1/schedules", headers=h, json={
            "name": "Nightly backup", "job_kind": "backup.run",
            "cron": "0 2 * * *", "timezone": "UTC", "params": {"host_id": 1}})
        assert allowed.status_code == 201


def test_sched_windows_entitlement_gates_every_write(tmp_path, csrf_header,
                                                     bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        c.app.state.entitlements._features = {"sched.windows": False}
        r = c.post("/api/v1/schedules", headers=h, json={
            "name": "x", "job_kind": "catalog.refresh", "cron": "0 2 * * *",
            "timezone": "UTC", "params": {}})
        assert r.status_code == 403
        assert r.json()["feature"] == "sched.windows"


def test_entitlement_gate_runs_after_auth_not_before(tmp_path, csrf_header):
    """An anonymous caller gets 401, never a 403 that leaks which flags are on."""
    app = make_app(tmp_path)
    with TestClient(app) as c:
        h = csrf_header(c)
        c.app.state.entitlements._features = {}
        assert c.post("/api/v1/schedules", headers=h, json={}).status_code == 401
        assert c.get("/api/v1/schedules").status_code == 401
