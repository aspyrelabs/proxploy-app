"""Notification channel CRUD + test-send (doc 05 §Notifications)."""
from fastapi.testclient import TestClient

from proxploy.models import AuditEvent, NotificationChannel

URL = "ntfy://ntfy.sh/proxploy-test"


def test_anonymous_get_is_401(tmp_path):
    """Only covers the anonymous path (no session at all) -> 401. Does NOT
    exercise require_role("admin")'s actual role comparison — see
    test_viewer_role_is_refused for that, and
    test_entitlement_gate_runs_after_auth_not_before for the ordering fix."""
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        assert c.get("/api/v1/notifications/channels").status_code == 401


def test_entitlement_gate_runs_after_auth_not_before(tmp_path, csrf_header):
    """Mirrors test_jobs_api.py::test_entitlement_gate_runs_after_auth_not_before.
    FastAPI resolves a route's dependencies=[...] in list order, so
    require_role must be listed ahead of require_entitlement — otherwise an
    anonymous caller gets a 403 revealing which flags are armed instead of a
    401, before we've even established who they are. Disable notify.channels
    and hit every gated route with no session cookie: each must still 401.
    csrf_header is supplied on the mutating calls only to get past the
    unrelated CSRF-cookie gate (doc 08 §5), which 403s any no-cookie mutation
    before routing even starts — it is not standing in for a session."""
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        h = csrf_header(c)
        c.app.state.entitlements._features["notify.channels"] = False
        assert c.get("/api/v1/notifications/channels").status_code == 401
        assert c.post("/api/v1/notifications/channels",
                      json={"name": "n", "url": URL}, headers=h).status_code == 401
        assert c.patch("/api/v1/notifications/channels/1",
                       json={"enabled": False}, headers=h).status_code == 401
        assert c.delete("/api/v1/notifications/channels/1", headers=h).status_code == 401
        assert c.post("/api/v1/notifications/channels/1/test",
                      headers=h).status_code == 401


def test_viewer_role_is_refused(tmp_path, csrf_header, bootstrap_admin):
    """require_role("admin") must actually refuse a logged-in user whose role
    is below admin. A plain signup defaults to "viewer" (UserIn.role)."""
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        c.post("/api/v1/users", json={"email": "viewer@example.com",
                                      "password": "correct-horse-battery",
                                      "display_name": "Viewer", "role": "viewer"},
               headers=h)
        c.post("/api/v1/auth/login", json={"email": "viewer@example.com",
                                           "password": "correct-horse-battery"},
               headers=h)
        r = c.post("/api/v1/notifications/channels",
                   json={"name": "n", "url": URL}, headers=csrf_header(c))
        assert r.status_code == 403


def test_admin_with_entitlement_disabled_is_403(tmp_path, csrf_header, bootstrap_admin):
    """A real admin session, but notify.channels gated off -> 403, not 401 —
    the flip side of test_entitlement_gate_runs_after_auth_not_before."""
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        app.state.entitlements._features["notify.channels"] = False
        assert c.get("/api/v1/notifications/channels").status_code == 403


def test_create_list_patch_delete(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        r = c.post("/api/v1/notifications/channels",
                   json={"name": "Home ntfy", "url": URL, "events": ["job.failed"]},
                   headers=h)
        assert r.status_code == 201
        made = r.json()
        assert made["kind"] == "ntfy" and made["events"] == ["job.failed"]
        assert "url" not in made and URL not in r.text

        listed = c.get("/api/v1/notifications/channels").json()
        assert [x["name"] for x in listed] == ["Home ntfy"]
        assert all("url" not in x for x in listed)

        patched = c.patch(f"/api/v1/notifications/channels/{made['id']}",
                          json={"enabled": False, "events": []}, headers=h).json()
        assert patched["enabled"] is False and patched["events"] == []

        assert c.delete(f"/api/v1/notifications/channels/{made['id']}",
                        headers=h).status_code == 204
        assert c.get("/api/v1/notifications/channels").json() == []


def test_the_url_is_encrypted_at_rest_and_never_audited(tmp_path, csrf_header,
                                                        bootstrap_admin):
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        c.post("/api/v1/notifications/channels", json={"name": "n", "url": URL},
               headers=csrf_header(c))
        with app.state.sessionmaker() as db:
            row = db.query(NotificationChannel).one()
            assert URL.encode() not in row.url_enc
            assert app.state.secretstore.decrypt(row.url_enc).decode() == URL
            audit = db.query(AuditEvent).filter_by(action="notify.channel.create").one()
            assert URL not in str(audit.params)


def test_test_send_calls_apprise_and_audits(tmp_path, csrf_header, bootstrap_admin,
                                            monkeypatch):
    from proxploy.api import notifications
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        made = c.post("/api/v1/notifications/channels",
                      json={"name": "n", "url": URL}, headers=h).json()
        calls = []
        monkeypatch.setattr(notifications, "send_one",
                            lambda url, title, body: calls.append(url) or True)
        r = c.post(f"/api/v1/notifications/channels/{made['id']}/test", headers=h)
        assert r.status_code == 200 and r.json() == {"sent": True}
        assert calls == [URL]
        with app.state.sessionmaker() as db:
            assert db.query(AuditEvent).filter_by(action="notify.channel.test").count() == 1


def test_test_send_reports_failure_without_raising(tmp_path, csrf_header,
                                                   bootstrap_admin, monkeypatch):
    from proxploy.api import notifications
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        made = c.post("/api/v1/notifications/channels",
                      json={"name": "n", "url": URL}, headers=h).json()

        def blow_up(url, title, body):
            raise RuntimeError("no route to host")

        monkeypatch.setattr(notifications, "send_one", blow_up)
        r = c.post(f"/api/v1/notifications/channels/{made['id']}/test", headers=h)
        assert r.status_code == 200 and r.json()["sent"] is False


def test_an_unparseable_url_is_rejected(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/notifications/channels",
                   json={"name": "n", "url": "not-a-url"}, headers=csrf_header(c))
        assert r.status_code == 422
