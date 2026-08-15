"""Lifecycle endpoints (doc 05 Apps/VMs rows + plan decision 1)."""
import json

from fastapi.testclient import TestClient

from proxploy.models import App, AuditEvent, Host, HostCredential, Job, Vm


def _seed(app, ctid=150, vmid=201):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.7:8006", node_name="pve1",
                    status="connected")
        db.add(host)
        db.commit()
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!life", "token_secret": "s3cret"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token:lifecycle",
                              encrypted_blob=blob, key_version=ver))
        a = App(host_id=host.id, ctid=ctid, name="Immich", slug="immich")
        v = Vm(host_id=host.id, vmid=vmid, name="win11", status="running")
        db.add_all([a, v])
        db.commit()
        return host.id, a.id, v.id


def test_missing_session_is_401_not_403(tmp_path, csrf_header, bootstrap_admin):
    """A missing session must 401, never 403; even with the entitlement gate
    stacked on the route. The CSRF double-submit is a separate, mutation-only
    gate (doc 08 §5): a bare POST with no cookie at all trips CSRF first, so
    the CSRF pair is supplied here (same as every other unauth-POST-is-401
    test in this suite, e.g. test_auth.py) to isolate the check this test is
    actually about, auth must run before the entitlement gate. (This does
    NOT exercise the operator-role branch, see test_viewer_role_is_refused
    below for that.)"""
    from tests.fakes.pve import FakePVE
    from tests.support import make_app

    app = make_app(tmp_path, fake=FakePVE())
    with TestClient(app) as c:
        _, app_id, _ = _seed(app)
        assert c.post(f"/api/v1/apps/{app_id}/start",
                      headers=csrf_header(c)).status_code == 401


def test_viewer_role_is_refused(tmp_path, csrf_header, bootstrap_admin):
    """authorize("app"/"vm", "lifecycle") must actually refuse a logged-in
    user whose role is below operator, a plain signup defaults to "viewer"
    (UserIn.role) and gets a real viewer membership. (A user with NO team
    membership is a different case entirely and is denied outright, reads
    included, Phase 8 amendment A1, pinned by test_authz_bootstrap.py.)
    Covers both the
    apps and vms routes: this is the endpoint that stops a customer's
    container, and "operator required" was previously asserted nowhere in
    the suite."""
    from tests.fakes.pve import FakePVE
    from tests.support import make_app

    app = make_app(tmp_path, fake=FakePVE())
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, app_id, vm_id = _seed(app)
        c.post("/api/v1/users", json={"email": "viewer@example.com",
                                      "password": "correct-horse-battery",
                                      "display_name": "Viewer"},
               headers=csrf_header(c))  # role omitted -> defaults to "viewer"
        c.post("/api/v1/auth/login", json={"email": "viewer@example.com",
                                           "password": "correct-horse-battery"},
               headers=csrf_header(c))
        for url in (f"/api/v1/apps/{app_id}/start", f"/api/v1/vms/{vm_id}/start"):
            r = c.post(url, headers=csrf_header(c))
            assert r.status_code == 403 and r.json()["detail"] == "Your role does not allow this."


def test_app_start_returns_202_with_a_job_and_audits(tmp_path, csrf_header,
                                                     bootstrap_admin):
    from tests.fakes.pve import FakePVE
    from tests.support import make_app

    fake = FakePVE()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, app_id, _ = _seed(app)
        r = c.post(f"/api/v1/apps/{app_id}/start", headers=csrf_header(c))
        assert r.status_code == 202
        job = r.json()["job"]
        assert job["kind"] == "app.start" and job["target_id"] == app_id
        with app.state.sessionmaker() as db:
            assert db.get(Job, job["id"]) is not None
            row = db.query(AuditEvent).filter_by(action="app.start").one()
            assert row.target_type == "app" and row.job_id == job["id"]


def test_unknown_action_is_422(tmp_path, csrf_header, bootstrap_admin):
    from tests.fakes.pve import FakePVE
    from tests.support import make_app

    app = make_app(tmp_path, fake=FakePVE())
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, app_id, _ = _seed(app)
        r = c.post(f"/api/v1/apps/{app_id}/pause", headers=csrf_header(c))
        assert r.status_code == 422


def test_vm_accepts_pause_and_resume(tmp_path, csrf_header, bootstrap_admin):
    from tests.fakes.pve import FakePVE
    from tests.support import make_app

    app = make_app(tmp_path, fake=FakePVE())
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, _, vm_id = _seed(app)
        for action in ("pause", "resume", "shutdown"):
            r = c.post(f"/api/v1/vms/{vm_id}/{action}", headers=csrf_header(c))
            assert r.status_code == 202, action
            job = r.json()["job"]
            assert job["kind"] == f"vm.{action}"
            with app.state.sessionmaker() as db:
                row = db.query(AuditEvent).filter_by(action=f"vm.{action}").one()
                assert row.target_type == "vm" and row.job_id == job["id"]


def test_missing_target_is_404(tmp_path, csrf_header, bootstrap_admin):
    from tests.fakes.pve import FakePVE
    from tests.support import make_app

    app = make_app(tmp_path, fake=FakePVE())
    with TestClient(app) as c:
        bootstrap_admin(c)
        assert c.post("/api/v1/apps/999/start", headers=csrf_header(c)).status_code == 404
        assert c.post("/api/v1/vms/999/start", headers=csrf_header(c)).status_code == 404


def test_self_targeted_stop_needs_a_typed_confirmation(tmp_path, csrf_header,
                                                       bootstrap_admin):
    from proxploy.services.settings import set_setting
    from tests.fakes.pve import FakePVE
    from tests.support import make_app

    app = make_app(tmp_path, fake=FakePVE())
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id, app_id, _ = _seed(app)
        with app.state.sessionmaker() as db:
            set_setting(db, "self.ctid", 150)
            set_setting(db, "self.host_id", host_id)

        r = c.post(f"/api/v1/apps/{app_id}/stop", headers=csrf_header(c))
        assert r.status_code == 409
        body = r.json()
        assert body["error"] == "self_target" and body["confirm_phrase"] == "Immich"
        with app.state.sessionmaker() as db:
            denied = db.query(AuditEvent).filter_by(action="app.stop").one()
            assert denied.result == "denied"

        wrong = c.post(f"/api/v1/apps/{app_id}/stop", json={"confirm": "nope"},
                       headers=csrf_header(c))
        assert wrong.status_code == 409

        ok = c.post(f"/api/v1/apps/{app_id}/stop", json={"confirm": "Immich"},
                    headers=csrf_header(c))
        assert ok.status_code == 202


def test_self_targeted_start_is_never_blocked(tmp_path, csrf_header, bootstrap_admin):
    from proxploy.services.settings import set_setting
    from tests.fakes.pve import FakePVE
    from tests.support import make_app

    app = make_app(tmp_path, fake=FakePVE())
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id, app_id, _ = _seed(app)
        with app.state.sessionmaker() as db:
            set_setting(db, "self.ctid", 150)
            set_setting(db, "self.host_id", host_id)
        assert c.post(f"/api/v1/apps/{app_id}/start",
                      headers=csrf_header(c)).status_code == 202
