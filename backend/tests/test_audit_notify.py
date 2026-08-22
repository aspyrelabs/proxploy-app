"""An audited action that failed is the one notification type with no job and
no alert behind it. It is how a firewall rule that would not apply, or a host
that refused its credentials, reaches someone who is not watching the screen."""
from proxploy.models import AuditEvent
from proxploy.services import notifier
from proxploy.services.audit import write_audit


def _capture(monkeypatch):
    seen = []
    monkeypatch.setattr(notifier, "notify",
                        lambda a, event, title, body, **k: (
                            seen.append((event, title, body)), 1)[1])
    return seen


def test_an_errored_audit_row_notifies(session, monkeypatch):
    seen = _capture(monkeypatch)
    write_audit(session, actor_type="user", actor_id=1, action="host.test",
                result="error", app=session.info["app"])
    assert [e for e, _, _ in seen] == ["audit.error"]
    assert "host.test" in seen[0][1]


def test_a_successful_audit_row_is_silent(session, monkeypatch):
    seen = _capture(monkeypatch)
    write_audit(session, actor_type="user", actor_id=1, action="host.test",
                result="ok", app=session.info["app"])
    assert seen == []


def test_audit_still_writes_with_no_app_handle_anywhere(session, monkeypatch):
    """A session outside a request (a poller, a migration, a CLI call) has no
    app on it and no app argument. Auditing must never depend on being able
    to notify, so the row is written and nothing is sent."""
    seen = _capture(monkeypatch)
    session.info.pop("app", None)
    write_audit(session, actor_type="user", actor_id=1, action="host.test",
                result="error")
    assert session.query(AuditEvent).count() == 1
    assert seen == []


def test_a_broken_notifier_never_costs_the_audit_row(session, monkeypatch):
    """The row is the record; the notification is a courtesy. An exception on
    the courtesy path must not roll back the record."""
    def boom(*a, **k):
        raise RuntimeError("channel exploded")

    monkeypatch.setattr(notifier, "notify", boom)
    write_audit(session, actor_type="user", actor_id=1, action="host.test",
                result="error", app=session.info["app"])
    assert session.query(AuditEvent).count() == 1


def test_a_route_that_never_passes_app_still_notifies(tmp_path, csrf_header,
                                                      bootstrap_admin, monkeypatch):
    """No route threads `app=` down to write_audit. get_db hangs it on the
    session instead, so every audited failure notifies without 25 call sites
    each having to remember."""
    from fastapi.testclient import TestClient

    from tests.support import make_app

    seen = []
    monkeypatch.setattr(notifier, "notify",
                        lambda a, event, *args, **k: (seen.append(event), 1)[1])
    with TestClient(make_app(tmp_path)) as c:
        bootstrap_admin(c)
        # A channel that cannot be reached audits notify.channel.test as an
        # error, through the ordinary get_db session.
        r = c.post("/api/v1/notifications/channels",
                   json={"name": "n", "url": "json://127.0.0.1:9/nope"},
                   headers=csrf_header(c))
        assert r.status_code == 201
        c.post(f"/api/v1/notifications/channels/{r.json()['id']}/test",
               headers=csrf_header(c))
    assert "audit.error" in seen


def test_a_failed_sign_in_does_not_page_anyone(tmp_path, csrf_header, monkeypatch):
    """The audit row is still written; only the notification is withheld. One
    wrong password should not reach a phone."""
    from fastapi.testclient import TestClient

    from proxploy.models import AuditEvent
    from tests.support import make_app

    seen = []
    monkeypatch.setattr(notifier, "notify",
                        lambda a, event, *args, **k: (seen.append(event), 1)[1])
    app = make_app(tmp_path)
    with TestClient(app) as c:
        c.post("/api/v1/auth/login",
               json={"email": "nobody@example.com", "password": "wrong-password"},
               headers=csrf_header(c))
    with app.state.sessionmaker() as db:
        rows = db.query(AuditEvent).filter_by(action="auth.login",
                                              result="error").count()
    assert rows == 1
    assert "audit.error" not in seen
