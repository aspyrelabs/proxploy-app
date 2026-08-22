"""Notification channel CRUD + test-send (doc 05 §Notifications)."""
import pytest
from fastapi.testclient import TestClient

from proxploy.models import AuditEvent, NotificationChannel

URL = "ntfy://ntfy.sh/proxploy-test"


def test_anonymous_get_is_401(tmp_path):
    """Only covers the anonymous path (no session at all) -> 401. Does NOT
    exercise require_role("admin")'s actual role comparison, see
    test_viewer_role_is_refused for that, and
    test_entitlement_gate_runs_after_auth_not_before for the ordering fix."""
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        assert c.get("/api/v1/notifications/channels").status_code == 401


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
    """A real admin session, but notify.channels gated off -> 403, not 401; 
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


def test_test_send_never_leaks_the_url_on_failure(tmp_path, csrf_header,
                                                   bootstrap_admin, monkeypatch):
    """Forces a realistic Apprise-style failure -- send_one raising with the
    URL interpolated straight into its own exception message, exactly what a
    real plugin error looks like -- and confirms the secret survives nowhere
    reachable from this request: not in the HTTP response body, not in the
    audit row `test_test_send_reports_failure_without_raising` (above)
    doesn't check either of those."""
    from proxploy.api import notifications
    from proxploy.models import AuditEvent
    from tests.support import make_app

    secret = "tokenSECRET1234"
    secret_url = f"ntfy://{secret}@ntfy.sh/x"
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        made = c.post("/api/v1/notifications/channels",
                      json={"name": "n", "url": secret_url}, headers=h).json()

        def blow_up(url, title, body):
            raise RuntimeError(f"failed to reach {url}")

        monkeypatch.setattr(notifications, "send_one", blow_up)
        r = c.post(f"/api/v1/notifications/channels/{made['id']}/test", headers=h)
        assert r.status_code == 200 and r.json() == {"sent": False}
        assert secret not in r.text
        with app.state.sessionmaker() as db:
            audit = db.query(AuditEvent).filter_by(action="notify.channel.test").one()
            assert secret not in str(audit.params)


def test_an_unparseable_url_is_rejected(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/notifications/channels",
                   json={"name": "n", "url": "not-a-url"}, headers=csrf_header(c))
        assert r.status_code == 422


# --- Guided picker (services/notification_catalog.py) -----------------------

def test_kinds_lists_every_service_without_leaking_templates(
        tmp_path, csrf_header, bootstrap_admin):
    """The client gets the questions, never the string they assemble into."""
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        bootstrap_admin(c)
        r = c.get("/api/v1/notifications/kinds")
        assert r.status_code == 200
        kinds = r.json()
        assert len(kinds) == 20
        assert {"kind", "label", "setup_url", "fields"} == set(kinds[0])
        telegram = next(k for k in kinds if k["kind"] == "telegram")
        assert [f["key"] for f in telegram["fields"]] == ["bot_token", "chat_id"]
        assert next(f for f in telegram["fields"] if f["key"] == "bot_token")["secret"]


def test_guided_create_assembles_and_stores_the_url(
        tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/notifications/channels",
                   json={"name": "Bot", "kind": "telegram",
                         "fields": {"bot_token": "123456789:AAHrLHtM3vJqPpAaBbCcDdEeFfGgHhI",
                                    "chat_id": "123456789"}},
                   headers=csrf_header(c))
        assert r.status_code == 201, r.text
        assert r.json()["kind"] == "telegram"
        # The assembled URL is stored encrypted like any other, and the raw
        # field values never come back out.
        assert "bot_token" not in r.text and "123456789:" not in r.text
        with app.state.sessionmaker() as db:
            row = db.query(NotificationChannel).one()
        url = app.state.secretstore.decrypt(row.url_enc).decode()
        # The colon inside a bot token is content, not structure, so it is
        # percent-encoded; Apprise unquotes it back on the way out.
        assert url == ("tgram://123456789%3AAAHrLHtM3vJqPpAaBbCcDdEeFfGgHhI"
                       "/123456789")


def test_guided_create_reports_a_missing_field_by_name(
        tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/notifications/channels",
                   json={"name": "n", "kind": "ntfy", "fields": {"host": "ntfy.sh"}},
                   headers=csrf_header(c))
        assert r.status_code == 422
        assert "Topic is required" in r.text


def test_guided_create_refuses_a_field_that_breaks_its_rule(
        tmp_path, csrf_header, bootstrap_admin):
    """The point of validating before storing: a channel that saves cleanly and
    then never delivers is worse than a 422 while the form is still open.

    The field rule is the first of two gates and catches this one, so the
    message names the field rather than mentioning Apprise at all."""
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/notifications/channels",
                   json={"name": "n", "kind": "telegram",
                         "fields": {"bot_token": "not-a-token", "chat_id": "x"}},
                   headers=csrf_header(c))
        assert r.status_code == 422
        assert "Bot token" in r.text
        assert "BotFather" in r.text


def test_guided_create_still_refuses_what_only_apprise_can_judge(
        tmp_path, csrf_header, bootstrap_admin, monkeypatch):
    """The second gate. Field rules are deliberately permissive, because a
    rule that rejects something which actually works is worse than the rubbish
    it was meant to stop, so Apprise's own parser stays behind them as the
    backstop for anything a pattern cannot express."""
    from proxploy.api import notifications
    from tests.support import make_app

    monkeypatch.setattr(notifications, "parses", lambda url: False)
    with TestClient(make_app(tmp_path)) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/notifications/channels",
                   json={"name": "n", "kind": "ntfy",
                         "fields": {"host": "ntfy.sh", "topic": "fine-topic"}},
                   headers=csrf_header(c))
        assert r.status_code == 422
        assert "Apprise" in r.text


def test_channel_needs_either_a_url_or_a_kind(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        assert c.post("/api/v1/notifications/channels", json={"name": "n"},
                      headers=h).status_code == 422
        assert c.post("/api/v1/notifications/channels",
                      json={"name": "n", "url": URL, "kind": "ntfy"},
                      headers=csrf_header(c)).status_code == 422


def test_pasted_url_still_works_unchanged(tmp_path, csrf_header, bootstrap_admin):
    """The escape hatch keeps its looser check: tightening it would reject
    targets that work today for services the catalog does not cover."""
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/notifications/channels",
                   json={"name": "Raw", "url": "sinch://a/b/c/+15551234567"},
                   headers=csrf_header(c))
        assert r.status_code == 201


# --- Master switches (services/notification_prefs.py) -----------------------

def test_types_lists_every_row_with_its_live_value(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        bootstrap_admin(c)
        r = c.get("/api/v1/notifications/types")
        assert r.status_code == 200
        rows = r.json()["types"]
        assert len(rows) == 19
        by_key = {t["key"]: t for t in rows}
        assert by_key["job.failed"]["enabled"] is True
        assert by_key["job.failed"]["label"] == "Job failed"
        assert by_key["housekeeping.succeeded"]["enabled"] is False


def test_patching_a_type_persists_and_is_audited(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        r = c.patch("/api/v1/notifications/types",
                    json={"enabled": {"job.succeeded": False}},
                    headers=csrf_header(c))
        assert r.status_code == 200
        by_key = {t["key"]: t for t in r.json()["types"]}
        assert by_key["job.succeeded"]["enabled"] is False
        again = {t["key"]: t for t in c.get("/api/v1/notifications/types").json()["types"]}
        assert again["job.succeeded"]["enabled"] is False
        with app.state.sessionmaker() as db:
            actions = [a.action for a in db.query(AuditEvent).all()]
        assert "notify.types.update" in actions


def test_patching_an_unknown_type_is_refused(tmp_path, csrf_header, bootstrap_admin):
    """`app.updated` was tickable in the old form and no emitter could produce
    it. Refusing the key at the door is how that stops recurring."""
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        bootstrap_admin(c)
        r = c.patch("/api/v1/notifications/types",
                    json={"enabled": {"app.updated": False}},
                    headers=csrf_header(c))
        assert r.status_code == 422
        assert "app.updated" in r.text


def test_types_needs_admin(tmp_path):
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        assert c.get("/api/v1/notifications/types").status_code == 401


# --- Editing a channel ------------------------------------------------------

def test_renaming_a_channel_leaves_its_credential_alone(
        tmp_path, csrf_header, bootstrap_admin):
    """The common edit. Credentials are unrecoverable, so an edit that only
    changes the name must not need them re-entered."""
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/notifications/channels",
                   json={"name": "Old", "kind": "ntfy",
                         "fields": {"host": "ntfy.sh", "topic": "first-topic"}},
                   headers=csrf_header(c))
        cid = r.json()["id"]
        with app.state.sessionmaker() as db:
            before = db.get(NotificationChannel, cid).url_enc

        r = c.patch(f"/api/v1/notifications/channels/{cid}",
                    json={"name": "New"}, headers=csrf_header(c))
        assert r.status_code == 200
        assert r.json()["name"] == "New"
        with app.state.sessionmaker() as db:
            row = db.get(NotificationChannel, cid)
            assert row.url_enc == before
            assert row.kind == "ntfy"


def test_replacing_credentials_reassembles_and_re_encrypts(
        tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        cid = c.post("/api/v1/notifications/channels",
                     json={"name": "Bot", "kind": "ntfy",
                           "fields": {"host": "ntfy.sh", "topic": "first-topic"}},
                     headers=csrf_header(c)).json()["id"]

        r = c.patch(f"/api/v1/notifications/channels/{cid}",
                    json={"kind": "ntfy",
                          "fields": {"host": "ntfy.sh", "topic": "second-topic"}},
                    headers=csrf_header(c))
        assert r.status_code == 200
        with app.state.sessionmaker() as db:
            row = db.get(NotificationChannel, cid)
        url = app.state.secretstore.decrypt(row.url_enc).decode()
        assert url == "ntfy://ntfy.sh/second-topic"
        # The id is unchanged, so the channel keeps its column in the Events
        # matrix and everything ticked in it. Delete-and-recreate does not.
        assert row.id == cid


def test_an_edit_cannot_walk_around_the_field_rules(
        tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        bootstrap_admin(c)
        cid = c.post("/api/v1/notifications/channels",
                     json={"name": "Bot", "kind": "ntfy",
                           "fields": {"host": "ntfy.sh", "topic": "fine"}},
                     headers=csrf_header(c)).json()["id"]

        r = c.patch(f"/api/v1/notifications/channels/{cid}",
                    json={"kind": "ntfy",
                          "fields": {"host": "ntfy.sh", "topic": "no spaces!!"}},
                    headers=csrf_header(c))
        assert r.status_code == 422
        assert "Topic" in r.text


def test_an_edit_can_move_a_channel_to_a_different_service(
        tmp_path, csrf_header, bootstrap_admin):
    """Changing service keeps the row, so the matrix column survives."""
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        cid = c.post("/api/v1/notifications/channels",
                     json={"name": "Alerts", "kind": "ntfy",
                           "fields": {"host": "ntfy.sh", "topic": "t"}},
                     headers=csrf_header(c)).json()["id"]
        c.patch(f"/api/v1/notifications/channels/{cid}",
                json={"events": ["job.failed"]}, headers=csrf_header(c))

        r = c.patch(f"/api/v1/notifications/channels/{cid}",
                    json={"kind": "gotify",
                          "fields": {"host": "gotify.example.com:8080",
                                     "token": "AbCdEfGhIjKlMnO"}},
                    headers=csrf_header(c))
        assert r.status_code == 200
        assert r.json()["kind"] == "gotify"
        assert r.json()["events"] == ["job.failed"]


def test_an_edit_records_that_the_credential_was_rotated(
        tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        cid = c.post("/api/v1/notifications/channels",
                     json={"name": "Bot", "kind": "ntfy",
                           "fields": {"host": "ntfy.sh", "topic": "t"}},
                     headers=csrf_header(c)).json()["id"]
        c.patch(f"/api/v1/notifications/channels/{cid}", json={"name": "Renamed"},
                headers=csrf_header(c))
        c.patch(f"/api/v1/notifications/channels/{cid}",
                json={"kind": "ntfy", "fields": {"host": "ntfy.sh", "topic": "u"}},
                headers=csrf_header(c))
    with app.state.sessionmaker() as db:
        rotated = [a.params.get("rotated") for a in db.query(AuditEvent)
                   .filter_by(action="notify.channel.update").all()]
    assert rotated == [False, True]
    # And the raw values never reach an audit row.
    with app.state.sessionmaker() as db:
        blob = " ".join(str(a.params) for a in db.query(AuditEvent).all())
    assert "ntfy.sh" not in blob


# --- Prefilling an edit -----------------------------------------------------

def test_a_saved_channel_gives_its_details_back_except_the_secrets(
        tmp_path, csrf_header, bootstrap_admin):
    """Correcting one mistyped password should not mean re-entering the server
    and the topic as well."""
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        bootstrap_admin(c)
        cid = c.post("/api/v1/notifications/channels",
                     json={"name": "G", "kind": "gotify",
                           "fields": {"host": "gotify.example.com:8080",
                                      "token": "AbCdEfGhIjKlMnO"}},
                     headers=csrf_header(c)).json()["id"]

        r = c.get(f"/api/v1/notifications/channels/{cid}/fields")
        assert r.status_code == 200
        body = r.json()
        assert body["known"] is True
        assert body["kind"] == "gotify"
        assert body["fields"] == {"host": "gotify.example.com:8080"}
        assert body["secrets_set"] == ["token"]
        # The secret is reported as set and never as a value, anywhere.
        assert "AbCdEfGhIjKlMnO" not in r.text


def test_a_blank_secret_on_save_keeps_the_stored_one(
        tmp_path, csrf_header, bootstrap_admin):
    """The browser is never sent a secret, so it cannot send one back. Without
    the merge, correcting a hostname would silently blank the token beside it
    and the channel would stop delivering."""
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        cid = c.post("/api/v1/notifications/channels",
                     json={"name": "G", "kind": "gotify",
                           "fields": {"host": "gotify.example.com:8080",
                                      "token": "AbCdEfGhIjKlMnO"}},
                     headers=csrf_header(c)).json()["id"]

        r = c.patch(f"/api/v1/notifications/channels/{cid}",
                    json={"name": "G", "kind": "gotify",
                          "fields": {"host": "gotify.example.com:9090", "token": ""}},
                    headers=csrf_header(c))
        assert r.status_code == 200, r.text
        with app.state.sessionmaker() as db:
            row = db.get(NotificationChannel, cid)
        url = app.state.secretstore.decrypt(row.url_enc).decode()
        assert url == "gotify://gotify.example.com:9090/AbCdEfGhIjKlMnO"


def test_typing_a_new_secret_replaces_the_old_one(
        tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        cid = c.post("/api/v1/notifications/channels",
                     json={"name": "G", "kind": "gotify",
                           "fields": {"host": "gotify.example.com",
                                      "token": "AbCdEfGhIjKlMnO"}},
                     headers=csrf_header(c)).json()["id"]
        c.patch(f"/api/v1/notifications/channels/{cid}",
                json={"name": "G", "kind": "gotify",
                      "fields": {"host": "gotify.example.com",
                                 "token": "ZzZzZzZzZzZzZzZ"}},
                headers=csrf_header(c))
    with app.state.sessionmaker() as db:
        row = db.get(NotificationChannel, cid)
    assert "ZzZzZzZzZzZzZzZ" in app.state.secretstore.decrypt(row.url_enc).decode()


def test_changing_service_does_not_carry_the_old_secret_over(
        tmp_path, csrf_header, bootstrap_admin):
    """The merge is keyed on the kind being unchanged. Moving a channel from
    Gotify to ntfy must not smuggle the Gotify token into the new URL."""
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        cid = c.post("/api/v1/notifications/channels",
                     json={"name": "G", "kind": "gotify",
                           "fields": {"host": "gotify.example.com",
                                      "token": "AbCdEfGhIjKlMnO"}},
                     headers=csrf_header(c)).json()["id"]
        c.patch(f"/api/v1/notifications/channels/{cid}",
                json={"name": "G", "kind": "ntfy",
                      "fields": {"host": "ntfy.sh", "topic": "moved"}},
                headers=csrf_header(c))
    with app.state.sessionmaker() as db:
        row = db.get(NotificationChannel, cid)
    url = app.state.secretstore.decrypt(row.url_enc).decode()
    assert url == "ntfy://ntfy.sh/moved"
    assert "AbCdEfGhIjKlMnO" not in url


def test_a_pasted_url_channel_says_it_has_nothing_to_prefill(
        tmp_path, csrf_header, bootstrap_admin):
    """Rather than presenting an empty form as if it were the stored truth."""
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        bootstrap_admin(c)
        cid = c.post("/api/v1/notifications/channels",
                     json={"name": "Raw", "url": "sinch://a/b/c/+15551234567"},
                     headers=csrf_header(c)).json()["id"]
        body = c.get(f"/api/v1/notifications/channels/{cid}/fields").json()
    assert body["known"] is False
    assert body["fields"] == {}


def test_the_stored_fields_are_encrypted_at_rest(tmp_path, csrf_header, bootstrap_admin):
    """Same discipline as url_enc: the column is a blob, not readable JSON."""
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        c.post("/api/v1/notifications/channels",
               json={"name": "G", "kind": "gotify",
                     "fields": {"host": "gotify.example.com",
                                "token": "AbCdEfGhIjKlMnO"}},
               headers=csrf_header(c))
    with app.state.sessionmaker() as db:
        blob = db.query(NotificationChannel).one().fields_enc
    assert blob and b"AbCdEfGhIjKlMnO" not in blob and b"gotify.example.com" not in blob


# --- This installation's address --------------------------------------------

def test_the_public_url_round_trips(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        bootstrap_admin(c)
        assert c.get("/api/v1/notifications/public-url").json() == {"url": ""}
        r = c.put("/api/v1/notifications/public-url",
                  json={"url": "https://pve.example.com/"}, headers=csrf_header(c))
        assert r.status_code == 200
        assert r.json() == {"url": "https://pve.example.com"}
        assert c.get("/api/v1/notifications/public-url").json()["url"] \
            == "https://pve.example.com"


@pytest.mark.parametrize("bad", [
    "javascript:alert(1)",
    "not-a-url",
    "ftp://pve.example.com",
    "https://pve.example.com/ path",
    "//pve.example.com",
])
def test_only_a_real_web_address_is_accepted(bad, tmp_path, csrf_header,
                                             bootstrap_admin):
    """This string is interpolated into a Markdown link in mail we send, so a
    javascript: URL must never reach it."""
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        bootstrap_admin(c)
        r = c.put("/api/v1/notifications/public-url", json={"url": bad},
                  headers=csrf_header(c))
        assert r.status_code == 422, bad


def test_clearing_it_is_allowed_because_no_link_is_a_real_choice(
        tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        bootstrap_admin(c)
        c.put("/api/v1/notifications/public-url",
              json={"url": "https://pve.example.com"}, headers=csrf_header(c))
        r = c.put("/api/v1/notifications/public-url", json={"url": ""},
                  headers=csrf_header(c))
        assert r.status_code == 200
        assert r.json() == {"url": ""}


def test_the_address_is_never_written_through_the_generic_settings_route(
        tmp_path, csrf_header, bootstrap_admin):
    """api/settings.py says a fresh key gets its own route rather than a hole
    in its allowlist. This is the test that keeps that true."""
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        bootstrap_admin(c)
        r = c.patch("/api/v1/settings", json={"public_url": "https://x.example.com"},
                    headers=csrf_header(c))
        assert r.status_code == 422
