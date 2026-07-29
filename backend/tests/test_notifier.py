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


def test_kind_for_never_leaks_a_secret_into_the_plaintext_kind_column():
    """A URL with no `://` has no scheme at all — `kind` is `Text`, unbounded
    and never encrypted, so a bare token must fall back to "webhook" rather
    than being written to the DB in plaintext."""
    leaked = kind_for("tgram//123456:AAH-SUPERSECRETBOTTOKEN/chatid")
    assert "AAH-SUPERSECRETBOTTOKEN" not in leaked
    assert leaked == "webhook"


def test_send_one_actually_calls_apprise_offline():
    """The one Apprise call site — every other test in this file monkeypatches
    it away, so this pins that the real dependency is actually exercised.
    A bogus scheme is rejected by ap.add() with no network access."""
    import logging

    from proxploy.services.notifier import send_one

    assert send_one("bogus://x", "t", "b") is False
    assert logging.getLogger("apprise").propagate is False


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


def test_a_broken_channel_never_fails_the_job_that_triggered_it(tmp_path, monkeypatch):
    """The global constraint is that the *job* survives a broken channel, not
    merely that other channels still get their notification (that's covered
    below in test_send_one_false_is_isolated_same_as_a_raise)."""
    from proxploy.jobs import HANDLERS, JobBackend
    from proxploy.models import Job
    from proxploy.services import notifier
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            _channel(db, app.state.secretstore, "ntfy://bad/x", name="bad")
            _channel(db, app.state.secretstore, "ntfy://good/x", name="good")

        sent = []

        def fake_send(url, title, body):
            if "bad" in url:
                raise RuntimeError("resolution failure")
            sent.append(url)
            return True

        monkeypatch.setattr(notifier, "send_one", fake_send)

        backend = JobBackend(app)

        async def ok(ctx, params):
            return {"ok": True}

        monkeypatch.setitem(HANDLERS, "test.notify_ok", ok)
        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(db, kind="test.notify_ok").id
        assert await backend.wait(job_id, timeout=5) is True
        with app.state.sessionmaker() as db:
            assert db.get(Job, job_id).status == "succeeded"

        for _ in range(50):  # the notify hop is a background thread
            if sent:
                break
            await asyncio.sleep(0.05)
        assert sent == ["ntfy://good/x"]  # the good channel is unaffected

    asyncio.run(run())


def test_send_one_false_is_isolated_same_as_a_raise(tmp_path, monkeypatch):
    """`ap.add()` rejecting a URL returns False from send_one — the ordinary
    Apprise failure mode, distinct from an exception — and must be isolated
    the same way a raise is."""
    from proxploy.services import notifier
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            _channel(db, app.state.secretstore, "ntfy://rejected/x", name="rejected")
            _channel(db, app.state.secretstore, "ntfy://good/x", name="good")

        monkeypatch.setattr(notifier, "send_one",
                            lambda url, title, body: "rejected" not in url)
        assert notifier.notify(app, "job.failed", "t", "b") == 1

    asyncio.run(run())


def test_a_channel_failure_never_leaks_the_url_into_job_error_or_events(
        tmp_path, monkeypatch):
    """The reviewer's headline security constraint, locked in: a channel URL
    (which embeds tokens/passwords) must never end up in `Job.error` or any
    `JobEvent.message`, even when the channel raises with the URL in its own
    exception message."""
    import threading

    from proxploy.jobs import HANDLERS, JobBackend, JobFailed
    from proxploy.models import Job, JobEvent
    from proxploy.services import notifier
    from tests.support import make_job_app

    secret_url = "ntfy://tokenSECRET1234@ntfy.sh/x"

    async def run():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            _channel(db, app.state.secretstore, secret_url, name="leaky")

        called = threading.Event()

        def fake_send(url, title, body):
            called.set()
            raise RuntimeError(f"failed to reach {url}")

        monkeypatch.setattr(notifier, "send_one", fake_send)

        backend = JobBackend(app)

        async def boom(ctx, params):
            raise JobFailed("boom")

        monkeypatch.setitem(HANDLERS, "test.leak_check", boom)
        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(db, kind="test.leak_check").id
        assert await backend.wait(job_id, timeout=5) is True

        for _ in range(50):  # the notify hop is a background thread
            if called.is_set():
                break
            await asyncio.sleep(0.05)
        assert called.is_set()
        await asyncio.sleep(0.05)  # let notify()'s except-continue finish

        with app.state.sessionmaker() as db:
            job = db.get(Job, job_id)
            assert "tokenSECRET1234" not in (job.error or "")
            events = db.query(JobEvent).filter_by(job_id=job_id).all()
            assert all("tokenSECRET1234" not in e.message for e in events)

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


def test_sweep_orphans_fires_job_interrupted_without_blocking_startup(
        tmp_path, monkeypatch):
    """`sweep_orphans` runs during lifespan startup; the bulk UPDATE that
    marks orphans is the only writer of `interrupted` in the backend, so it
    must be the one that schedules the Notifier — but as a background task,
    same as every other terminal state, never awaited inline."""
    from proxploy.jobs import JobBackend
    from proxploy.models import Job
    from proxploy.services import notifier
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            db.add_all([Job(kind="app.start", status="running"),
                        Job(kind="app.stop", status="queued")])
            db.commit()

        seen = []
        monkeypatch.setattr(notifier, "notify",
                            lambda a, event, title, body: seen.append(event) or 1)

        backend = JobBackend(app)
        n = backend.sweep_orphans()  # must return immediately, not await sends
        assert n == 2

        for _ in range(50):  # the notify hop is a background thread
            if len(seen) >= 2:
                break
            await asyncio.sleep(0.05)
        assert seen == ["job.interrupted", "job.interrupted"]

    asyncio.run(run())
