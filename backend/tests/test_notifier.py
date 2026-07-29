"""Notifier seam -> Apprise (brief §5, doc 03 notifications row)."""
import asyncio

from proxploy.models import NotificationChannel
from proxploy.services.notifier import channels_for, kind_for


def _channel(db, secretstore, url, *, name="ntfy", events=None, enabled=True):
    blob, ver = secretstore.encrypt(url.encode())
    row = NotificationChannel(name=name, kind=kind_for(url), url_enc=blob,
                              key_version=ver, events=events or [], enabled=enabled)
    db.add(row)
    db.commit()
    return row


def test_kind_is_parsed_from_the_url_scheme():
    assert kind_for("ntfy://ntfy.sh/proxploy") == "ntfy"
    assert kind_for("tgram://bottoken/chatid") == "telegram"
    assert kind_for("mailto://user:pw@example.com") == "email"
    assert kind_for("gotify://host/token") == "gotify"
    assert kind_for("json://example.com/hook") == "webhook"
    assert kind_for("slack://a/b/c") == "slack"


def test_empty_events_means_all_events(tmp_path):
    from proxploy.secretstore import SecretStore
    from tests.support import make_db

    db = make_db(tmp_path)
    SecretStore.ensure_key_file(tmp_path / "master.key", db_file_exists=False)
    ss = SecretStore(tmp_path / "master.key")
    _channel(db, ss, "ntfy://ntfy.sh/all", name="all", events=[])
    _channel(db, ss, "ntfy://ntfy.sh/fails", name="fails", events=["job.failed"])
    _channel(db, ss, "ntfy://ntfy.sh/off", name="off", events=[], enabled=False)

    assert sorted(c.name for c in channels_for(db, "job.failed")) == ["all", "fails"]
    assert [c.name for c in channels_for(db, "job.succeeded")] == ["all"]


def test_notify_sends_to_matching_channels_and_stamps_them(tmp_path, monkeypatch):
    from proxploy.services import notifier
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            _channel(db, app.state.secretstore, "ntfy://ntfy.sh/fails",
                     name="fails", events=["job.failed"])
            _channel(db, app.state.secretstore, "ntfy://ntfy.sh/all", name="all")

        sent = []
        monkeypatch.setattr(notifier, "send_one",
                            lambda url, title, body: sent.append((url, title)) or True)
        assert notifier.notify(app, "job.failed", "Job failed", "app.stop failed") == 2
        assert sorted(u for u, _ in sent) == ["ntfy://ntfy.sh/all", "ntfy://ntfy.sh/fails"]
        with app.state.sessionmaker() as db:
            assert all(c.last_notified_at is not None
                       for c in db.query(NotificationChannel).all())

    asyncio.run(run())


def test_a_broken_channel_never_breaks_the_others(tmp_path, monkeypatch):
    from proxploy.services import notifier
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            _channel(db, app.state.secretstore, "ntfy://bad/x", name="bad")
            _channel(db, app.state.secretstore, "ntfy://good/x", name="good")

        def fake_send(url, title, body):
            if "bad" in url:
                raise RuntimeError("resolution failure")
            return True

        monkeypatch.setattr(notifier, "send_one", fake_send)
        assert notifier.notify(app, "job.failed", "t", "b") == 1

    asyncio.run(run())


def test_job_failure_routes_through_the_notifier(tmp_path, monkeypatch):
    from proxploy.jobs import HANDLERS, JobBackend, JobFailed
    from proxploy.services import notifier
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        backend = JobBackend(app)
        seen = []
        monkeypatch.setattr(notifier, "notify",
                            lambda a, event, title, body: seen.append(event) or 1)

        async def boom(ctx, params):
            raise JobFailed("exitstatus: CT is locked")

        monkeypatch.setitem(HANDLERS, "test.notify_boom", boom)
        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(db, kind="test.notify_boom").id
        await backend.wait(job_id, timeout=5)
        for _ in range(50):  # the notify hop is a background thread
            if seen:
                break
            await asyncio.sleep(0.05)
        assert seen == ["job.failed"]

    asyncio.run(run())


def test_a_cancelled_job_still_gets_its_notification_scheduled_and_delivered(
        tmp_path, monkeypatch):
    """_finish runs (synchronously, no await) inside the CancelledError handler
    of an already-cancelling task. Creating a fire-and-forget task there is
    exactly the kind of thing that can silently do nothing — confirm it doesn't.
    """
    from proxploy.jobs import HANDLERS, JobBackend
    from proxploy.services import notifier
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        backend = JobBackend(app)
        started = asyncio.Event()
        seen = []

        async def slow(ctx, params):
            started.set()
            await asyncio.sleep(30)
            return {}

        monkeypatch.setitem(HANDLERS, "test.cancel_notify", slow)
        monkeypatch.setattr(notifier, "notify",
                            lambda a, event, title, body: seen.append(event) or 1)

        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(db, kind="test.cancel_notify").id
        await asyncio.wait_for(started.wait(), timeout=5)
        assert backend.cancel(job_id) is True
        assert await backend.wait(job_id, timeout=5) is True

        for _ in range(50):  # the notify hop is a background thread
            if seen:
                break
            await asyncio.sleep(0.05)
        assert seen == ["job.canceled"]

    asyncio.run(run())
