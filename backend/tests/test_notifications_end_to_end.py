"""One notification, all the way through, with nothing faked past the seam.

Every other notification test stubs `send_one`. This one stands up a real HTTP
server, points a real channel at it through the guided picker, and lets real
Apprise make a real request. It is the test that would have caught the three
defects this work removed: an event nothing emits, an event nothing offers,
and a channel pinned to one event it could never change.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from proxploy.services import notifier
from proxploy.services.notification_prefs import set_overrides


class _Inbox(BaseHTTPRequestHandler):
    received: list = []

    def do_POST(self):  # noqa: N802  (BaseHTTPRequestHandler's spelling)
        body = self.rfile.read(int(self.headers.get("content-length", 0)))
        try:
            _Inbox.received.append(json.loads(body))
        except ValueError:
            _Inbox.received.append({"raw": body.decode(errors="replace")})
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):  # keep pytest output readable
        pass


@pytest.fixture
def inbox():
    """A webhook that records what actually arrived."""
    _Inbox.received = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Inbox)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def _add_webhook_channel(client, csrf, server, name="Ops webhook"):
    """Through the guided picker, exactly as the UI does it: fields in, the
    server assembles and validates the URL, nothing here builds one."""
    host, port = server.server_address
    r = client.post("/api/v1/notifications/channels",
                    json={"name": name, "kind": "webhook",
                          "fields": {"host": f"{host}:{port}/hook"},
                          "events": []},
                    headers=csrf(client))
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "webhook"
    return r.json()["id"]


def test_a_channel_added_through_the_picker_actually_delivers(
        tmp_path, csrf_header, bootstrap_admin, inbox):
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _add_webhook_channel(c, csrf_header, inbox)

        reached = notifier.notify(app, "job.failed",
                                  "Proxploy: vm.create failed", "out of disk")

    assert reached == 1
    assert len(_Inbox.received) == 1
    got = _Inbox.received[0]
    assert got["title"] == "Proxploy: vm.create failed"
    assert got["message"] == "out of disk"


def test_the_test_send_button_reaches_the_same_channel(
        tmp_path, csrf_header, bootstrap_admin, inbox):
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        bootstrap_admin(c)
        cid = _add_webhook_channel(c, csrf_header, inbox)
        r = c.post(f"/api/v1/notifications/channels/{cid}/test",
                   headers=csrf_header(c))
        assert r.json() == {"sent": True}
    assert len(_Inbox.received) == 1
    assert "test" in _Inbox.received[0]["title"].lower()


def test_the_master_switch_stops_delivery_dead(
        tmp_path, csrf_header, bootstrap_admin, inbox):
    """Off is not "sent and discarded": nothing is decrypted and no request is
    made, which is what makes turning a noisy row off actually quiet."""
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _add_webhook_channel(c, csrf_header, inbox)

        r = c.patch("/api/v1/notifications/types",
                    json={"enabled": {"job.failed": False}},
                    headers=csrf_header(c))
        assert r.status_code == 200

        assert notifier.notify(app, "job.failed", "t", "b") == 0
    assert _Inbox.received == []


def test_housekeeping_is_quiet_out_of_the_box(
        tmp_path, csrf_header, bootstrap_admin, inbox):
    """The nightly catalog refresh and usage cleanup ship switched off, so a
    fresh install with a channel does not get a success message every night."""
    from proxploy.services.notification_types import type_for_job
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _add_webhook_channel(c, csrf_header, inbox)

        event = type_for_job("catalog.refresh", "succeeded")
        assert event == "housekeeping.succeeded"
        assert notifier.notify(app, event, "t", "b") == 0
    assert _Inbox.received == []


def test_a_named_job_kind_arrives_under_its_own_row(
        tmp_path, csrf_header, bootstrap_admin, inbox):
    """An app install failure is app.install.failed, and silencing the generic
    Job failed row must not silence it. This is the whole point of keeping the
    job kind that jobs/backend.py used to throw away."""
    from proxploy.services.notification_types import type_for_job
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _add_webhook_channel(c, csrf_header, inbox)
        c.patch("/api/v1/notifications/types",
                json={"enabled": {"job.failed": False}}, headers=csrf_header(c))

        event = type_for_job("app.install", "failed")
        assert event == "app.install.failed"
        assert notifier.notify(app, event, "Proxploy: app.install failed", "boom") == 1

    assert len(_Inbox.received) == 1
    assert _Inbox.received[0]["message"] == "boom"


def test_routing_sends_one_row_to_one_channel_and_not_the_other(
        tmp_path, csrf_header, bootstrap_admin, inbox):
    """The matrix' checkbox columns, at the level they actually take effect."""
    from proxploy.models import NotificationChannel
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        backups_only = _add_webhook_channel(c, csrf_header, inbox, "Backups only")
        everything = _add_webhook_channel(c, csrf_header, inbox, "Everything")

        # What the matrix writes when one box is cleared: the concrete list.
        r = c.patch(f"/api/v1/notifications/channels/{backups_only}",
                    json={"events": ["backup.failed"]}, headers=csrf_header(c))
        assert r.status_code == 200

        with app.state.sessionmaker() as db:
            rows = {r.name: r.events
                    for r in db.query(NotificationChannel).all()}
        assert rows["Backups only"] == ["backup.failed"]
        assert rows["Everything"] == []   # empty still means every event

        assert notifier.notify(app, "job.failed", "t", "job") == 1
        assert notifier.notify(app, "backup.failed", "t", "backup") == 2

    bodies = [m["message"] for m in _Inbox.received]
    assert bodies.count("job") == 1
    assert bodies.count("backup") == 2


def test_an_audited_failure_reaches_the_channel_with_no_job_behind_it(
        tmp_path, csrf_header, bootstrap_admin, inbox):
    """audit.error is the one type with neither a job nor an alert behind it,
    and it rides on the session get_db hangs the app onto."""
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        cid = _add_webhook_channel(c, csrf_header, inbox)
        _Inbox.received = []
        # A channel pointed at a closed port fails its test send, which audits
        # notify.channel.test as an error through an ordinary request session.
        c.post("/api/v1/notifications/channels",
               json={"name": "Dead", "url": "json://127.0.0.1:9/nope"},
               headers=csrf_header(c))
        dead = [r["id"] for r in c.get("/api/v1/notifications/channels").json()
                if r["name"] == "Dead"][0]
        c.post(f"/api/v1/notifications/channels/{dead}/test", headers=csrf_header(c))

    titles = [m["title"] for m in _Inbox.received]
    assert any("notify.channel.test failed" in t for t in titles), titles
    assert cid  # the live channel is the one that received it
