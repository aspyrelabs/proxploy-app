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




def test_what_a_real_failure_actually_says(tmp_path, csrf_header, bootstrap_admin,
                                           inbox, monkeypatch):
    """The body used to be "out of disk", or with no error text at all,
    "job 7 (vm.create) failed": a backend job kind, a number nobody can act on,
    and nothing about which machine on which host.

    _notify_async is run inline here rather than through ensure_future. The
    fire-and-forget dispatch is not what this is testing and there is no
    running loop in a sync test; everything below it, the composition and the
    real Apprise send, is the real thing.
    """
    from datetime import timedelta

    from proxploy.jobs.backend import JobBackend, JobContext
    from proxploy.models import Job, Schedule, utcnow
    from proxploy.services import notifier
    from tests.support import make_app

    app = make_app(tmp_path)
    monkeypatch.setattr(JobBackend, "_notify_async",
                        lambda self, event, title, body:
                            notifier.notify(self.app, event, title, body))

    with TestClient(app) as c:
        bootstrap_admin(c)
        _add_webhook_channel(c, csrf_header, inbox)

        with app.state.sessionmaker() as db:
            sched = Schedule(name="Nightly backup", job_kind="backup.run",
                             cron="0 2 * * *", enabled=True)
            db.add(sched)
            db.commit()
            job = Job(kind="backup.run", status="running", target_type="host",
                      target_id=1, target_name="pve1",
                      started_at=utcnow() - timedelta(seconds=134),
                      schedule_id=sched.id)
            db.add(job)
            db.commit()
            job_id = job.id

        app.state.jobs._finish(JobContext(app.state.jobs, job_id), "backup.run",
                               "failed", error="no space left on device",
                               target_type="host")

    assert len(_Inbox.received) == 1
    got = _Inbox.received[0]
    # The title is the row's own label, the same words the Events matrix uses,
    # rather than the job kind.
    assert got["title"] == "Proxploy: Backup failed"
    body = got["message"]
    assert "pve1" in body                     # which host
    assert "2m 14s" in body                   # how long it ran
    assert "Nightly backup" in body           # nobody did this by hand
    assert f"#{job_id}" in body               # the job to go and read
    assert "no space left on device" in body  # why
    assert "backup.run" not in body           # and no backend spelling anywhere


def test_no_public_url_means_no_link_rather_than_a_broken_one(
        tmp_path, csrf_header, bootstrap_admin, inbox):
    """Nothing can derive it: api_base_url is the licence server and the Host
    header is attacker-controllable. A link to the wrong installation, in a
    message we sent, is worse than no link."""
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _add_webhook_channel(c, csrf_header, inbox)
        notifier.notify(app, "job.failed", "Proxploy: Job failed", "it broke")

    assert "Open in Proxploy" not in _Inbox.received[0]["message"]


def test_a_configured_public_url_puts_a_real_link_in_the_message(
        tmp_path, csrf_header, bootstrap_admin, inbox, monkeypatch):
    from proxploy.jobs.backend import JobBackend, JobContext
    from proxploy.models import Job
    from proxploy.services.links import PUBLIC_URL_KEY
    from proxploy.services.settings import set_setting
    from tests.support import make_app

    app = make_app(tmp_path)
    monkeypatch.setattr(JobBackend, "_notify_async",
                        lambda self, event, title, body:
                            notifier.notify(self.app, event, title, body))
    with TestClient(app) as c:
        bootstrap_admin(c)
        _add_webhook_channel(c, csrf_header, inbox)
        with app.state.sessionmaker() as db:
            set_setting(db, PUBLIC_URL_KEY, "https://pve.example.com")
            job = Job(kind="app.install", status="running", target_type="app",
                      target_id=12, target_name="nextcloud")
            db.add(job)
            db.commit()
            job_id = job.id
        app.state.jobs._finish(JobContext(app.state.jobs, job_id), "app.install",
                               "failed", error="template missing",
                               target_type="app")

    body = _Inbox.received[0]["message"]
    # The link points at the app, because there is no /jobs route and the
    # thing that failed is what someone reading this wants to open.
    assert "[Open in Proxploy](https://pve.example.com/apps?open=12)" in body
    assert _Inbox.received[0]["title"] == "Proxploy: App install failed"


def test_a_thing_with_no_page_gets_the_message_without_a_link(
        tmp_path, csrf_header, bootstrap_admin, inbox, monkeypatch):
    """A storage job has nowhere useful to point, so it says everything else
    and offers nothing rather than linking to the dashboard."""
    from proxploy.jobs.backend import JobBackend, JobContext
    from proxploy.models import Job
    from proxploy.services.links import PUBLIC_URL_KEY
    from proxploy.services.settings import set_setting
    from tests.support import make_app

    app = make_app(tmp_path)
    monkeypatch.setattr(JobBackend, "_notify_async",
                        lambda self, event, title, body:
                            notifier.notify(self.app, event, title, body))
    with TestClient(app) as c:
        bootstrap_admin(c)
        _add_webhook_channel(c, csrf_header, inbox)
        with app.state.sessionmaker() as db:
            set_setting(db, PUBLIC_URL_KEY, "https://pve.example.com")
            job = Job(kind="storage.upload", status="running",
                      target_type="storage", target_id=1, target_name="tank")
            db.add(job)
            db.commit()
            job_id = job.id
        app.state.jobs._finish(JobContext(app.state.jobs, job_id),
                               "storage.upload", "failed", error="disk full",
                               target_type="storage")

    body = _Inbox.received[0]["message"]
    assert "disk full" in body
    assert "Open in Proxploy" not in body


# --- Every type, actually delivered -----------------------------------------

def test_every_registry_key_can_be_produced_by_something(inbox):
    """No key without an emitter. `app.updated` was tickable in the old form
    for the life of the feature and nothing could ever produce it."""
    import importlib
    import pkgutil

    import proxploy
    from proxploy.jobs import HANDLERS, TERMINAL
    from proxploy.services.notification_types import BY_KEY, type_for_job

    for mod in pkgutil.walk_packages(proxploy.__path__, "proxploy."):
        try:
            importlib.import_module(mod.name)
        except Exception:  # noqa: BLE001
            pass

    producible = {type_for_job(k, s) for k in HANDLERS for s in TERMINAL}
    # The three with no job behind them, emitted by services/alerts.py and
    # services/audit.py.
    producible |= {"alert.fired", "alert.resolved", "audit.error", "update.available"}
    assert set(BY_KEY) == producible


def test_every_notification_type_reaches_a_channel(tmp_path, csrf_header,
                                                   bootstrap_admin, inbox):
    """One sweep over all nineteen, through real Apprise to a real socket.

    Delivery had been proven for eight of them; the rest were covered only by
    the mapping test, which says a key is correct and nothing about whether
    anything comes out the other end.
    """
    from proxploy.services.notification_prefs import set_overrides
    from proxploy.services.notification_types import TYPES
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _add_webhook_channel(c, csrf_header, inbox)
        # Housekeeping ships off, so turn everything on for the sweep.
        with app.state.sessionmaker() as db:
            set_overrides(db, {t.key: True for t in TYPES})

        for t in TYPES:
            assert notifier.notify(app, t.key, f"Proxploy: {t.label}",
                                   "- **Job:** #1") == 1, t.key

    assert len(_Inbox.received) == len(TYPES) == 20
    titles = [m["title"] for m in _Inbox.received]
    for t in TYPES:
        assert f"Proxploy: {t.label}" in titles
    # And not one of them carries a backend key where a person will read it.
    assert not [x for x in titles if "." in x.replace("Proxploy: ", "")]


def test_the_two_that_ship_off_stay_off_until_asked(tmp_path, csrf_header,
                                                    bootstrap_admin, inbox):
    from proxploy.services.notification_types import TYPES
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _add_webhook_channel(c, csrf_header, inbox)
        for t in TYPES:
            reached = notifier.notify(app, t.key, "t", "b")
            assert reached == (0 if t.key.startswith("housekeeping.") else 1), t.key

    assert len(_Inbox.received) == 18
