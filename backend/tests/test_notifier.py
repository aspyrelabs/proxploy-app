"""Notifier seam -> Apprise (brief §5, doc 03 notifications row)."""
import asyncio

import pytest

from proxploy.models import NotificationChannel
from proxploy.services.notifier import KIND_FROM_SCHEME, channels_for, kind_for, redact_url


def _channel(db, secretstore, url, *, name="ntfy", events=None, enabled=True):
    blob, ver = secretstore.encrypt(url.encode())
    row = NotificationChannel(name=name, kind=kind_for(url), url_enc=blob,
                              key_version=ver, events=events or [], enabled=enabled)
    db.add(row)
    db.commit()
    return row


@pytest.mark.parametrize("scheme,label", sorted(KIND_FROM_SCHEME.items()))
def test_every_known_scheme_maps_to_its_expected_label(scheme, label):
    assert kind_for(f"{scheme}://example.invalid/x") == label


# kind_for's invariant, pinned: it returns ONLY a fixed label from
# KIND_FROM_SCHEME or "webhook": NEVER any text derived from the input.
# Every credential-shaped candidate below must produce "webhook" and must
# not leak any fragment of itself, regardless of case, script, embedded NUL,
# length, or where/how many times "://" appears.
CREDENTIAL_SHAPED_INPUTS = [
    ("AAH-SUPERSECRETBOTTOKEN://", "SUPERSECRET"),
    ("aah-super-secret-bot-token-123://x", "secret-bot-token"),
    ("xoxb-1234-5678-abcdefghijklmnop://", "abcdefghijklmnop"),
    ("AAH-SUPERSECRETBOTTOKEN", "SUPERSECRET"),          # no "://" at all
    ("K" * 5000, "KKKKK"),                               # 5000 chars, no "://"
    ("K" * 5000 + "://", "KKKKK"),                       # 5000 chars, trailing "://"
    ("SECRETVALUEUPPERCASE://x", "SECRETVALUEUPPERCASE"),  # uppercase
    ("sécret-tökén-üñíçødé://x", "tökén"),                # unicode
    ("secret\x00nullbyte://x", "nullbyte"),               # embedded NUL byte
    ("://leadingslashsecret", "leadingslashsecret"),      # leading "://"
    ("trailingslashsecret://", "trailingslashsecret"),    # trailing "://"
    ("abc://doubledslashsecretvalue://xyz", "doubledslashsecretvalue"),  # doubled "://"
    ("se://cret-inter://leaved-tokenvalue", "leaved-tokenvalue"),  # interleaved "://"
    ("K" * 100_000, "K" * 100),                           # 100KB, no "://"
    ("K" * 100_000 + "://", "K" * 100),                   # 100KB, trailing "://"
]

# The closed set kind_for's return value must always belong to, regardless of
# input. Computed the same way the DB CHECK constraint is (proxploy.models
# .ALLOWED_NOTIFICATION_KINDS) so this test and the schema invariant can't
# silently diverge.
ALLOWED_KINDS = set(KIND_FROM_SCHEME.values()) | {"webhook"}


@pytest.mark.parametrize("candidate,secret_fragment", CREDENTIAL_SHAPED_INPUTS)
def test_kind_for_never_echoes_caller_supplied_text(candidate, secret_fragment):
    """`kind` is an unencrypted `Text` column, kind_for must never return
    anything derived from the input, only a fixed allowlisted label. A
    shape/length guard on the derived scheme is not enough (it can always be
    walked around by appending "://" or picking a short lowercase token);
    only an allowlist closes this off for good."""
    result = kind_for(candidate)
    assert secret_fragment.lower() not in result.lower()
    assert result == "webhook"


def test_kind_for_codomain_is_closed_over_the_allowlist():
    """The structural claim behind `kind_for`, pinned directly: its codomain
    is exactly `KIND_FROM_SCHEME`'s values plus "webhook", nothing else can
    ever come out, for a legitimate scheme, an adversarial credential-shaped
    string, or anything in between. This is what `ALLOWED_NOTIFICATION_KINDS`
    (proxploy.models) mirrors into the DB CHECK constraint; if this test and
    that constraint ever disagree, one of them is wrong."""
    for scheme in KIND_FROM_SCHEME:
        assert kind_for(f"{scheme}://x") in ALLOWED_KINDS
    for candidate, _ in CREDENTIAL_SHAPED_INPUTS:
        assert kind_for(candidate) in ALLOWED_KINDS


def test_redact_url_format_for_a_legitimate_scheme():
    assert redact_url("ntfy://ntfy.sh/mytopic") == "ntfy://***"
    assert redact_url("tgram://123456:AAH-BOTTOKEN/chatid") == "telegram://***"


def test_redact_url_bare_stars_when_no_scheme_can_be_derived():
    assert redact_url("AAH-SUPERSECRETBOTTOKEN") == "***"
    assert redact_url("") == "***"


@pytest.mark.parametrize("candidate,secret_fragment", CREDENTIAL_SHAPED_INPUTS)
def test_redact_url_never_echoes_caller_supplied_text(candidate, secret_fragment):
    """Same claim as `kind_for`'s adversarial test, for the helper that
    exists specifically to make a URL safe to put in a log line: whatever
    walks in, no fragment of it walks back out."""
    result = redact_url(candidate)
    assert secret_fragment.lower() not in result.lower()
    assert result in ({"***"} | {f"{k}://***" for k in ALLOWED_KINDS})


def test_send_one_actually_calls_apprise_offline():
    """The one Apprise call site, every other test in this file monkeypatches
    it away, so this pins that the real dependency is actually exercised.
    A bogus scheme is rejected by ap.add() with no network access."""
    import logging

    from proxploy.services.notifier import send_one

    assert send_one("bogus://x", "t", "b") is False
    assert logging.getLogger("apprise").propagate is False
    # Apprise's own logger being silenced isn't enough: its plugins send over
    # `requests`, whose connection pooling logs the request line (including
    # the full path/query -- where a token-bearing webhook URL keeps its
    # secret) on a wholly separate "urllib3" logger tree. See
    # test_a_real_failed_send_never_reaches_a_configured_root_handler for the
    # end-to-end proof.
    assert logging.getLogger("urllib3").propagate is False


def test_a_real_failed_send_never_reaches_a_configured_root_handler():
    """The load-bearing regression test for the "apprise propagate=False
    isn't enough" gap: a REAL (unmocked) send through send_one -> Apprise ->
    requests -> urllib3, against a local server that accepts the connection
    and returns an error, so urllib3.connectionpool actually emits its
    request-line debug log (confirmed, before the urllib3 propagate=False fix
    landed, to contain the token verbatim: "POST /<token> HTTP/1.1").

    Deliberately does NOT use pytest's `caplog`: `_pytest.logging.catching_logs`
    explicitly walks every non-propagating logger and attaches its capture
    handler directly to each one (so caplog can still show them to test
    authors) -- which would make this test pass even with the urllib3 fix
    reverted, because caplog structurally bypasses the exact `propagate =
    False` mechanism under test. A handler attached only to the root logger,
    the way a real operator's `logging.basicConfig()` would, is what actually
    exercises the guarantee.
    """
    import http.server
    import logging
    import threading

    from proxploy.services.notifier import send_one

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(500)
            self.end_headers()

        def log_message(self, *a):  # silence the stdlib server's own stderr logging
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    records: list[logging.LogRecord] = []
    root_handler = logging.Handler()
    root_handler.emit = records.append
    root_logger = logging.getLogger()
    orig_level = root_logger.level
    root_logger.addHandler(root_handler)
    root_logger.setLevel(logging.DEBUG)
    try:
        secret = "BOTTOKENSUPERSECRETVALUE12345"
        url = f"json://127.0.0.1:{server.server_port}/{secret}"
        assert send_one(url, "t", "b") is False
    finally:
        server.shutdown()
        thread.join(timeout=5)
        root_logger.removeHandler(root_handler)
        root_logger.setLevel(orig_level)

    text = "\n".join(r.getMessage() for r in records)
    assert secret not in text


def test_notify_never_logs_the_url_when_send_one_raises(tmp_path, monkeypatch, caplog):
    """`notify`'s per-channel except-continue must not just swallow the
    exception from the caller's perspective (covered by
    test_a_channel_failure_never_leaks_the_url_into_job_error_or_events) --
    the debug log it emits about the failure must also never carry the raw
    URL, even though the raised exception's own message does (a real Apprise
    plugin error can and does interpolate the URL)."""
    import logging

    from proxploy.services import notifier
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        secret = "tokenSECRET1234"
        secret_url = f"ntfy://{secret}@ntfy.sh/x"
        with app.state.sessionmaker() as db:
            _channel(db, app.state.secretstore, secret_url, name="leaky")

        def blow_up(url, title, body):
            raise RuntimeError(f"failed to reach {url}")

        monkeypatch.setattr(notifier, "send_one", blow_up)
        caplog.set_level(logging.DEBUG)
        assert notifier.notify(app, "job.failed", "t", "b") == 0
        assert secret not in caplog.text

    asyncio.run(run())


def test_notify_never_logs_the_url_when_send_one_returns_false(tmp_path, monkeypatch,
                                                                caplog):
    """The other failure mode: send_one returning False (no exception at
    all) must be equally silent about the raw URL."""
    import logging

    from proxploy.services import notifier
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        secret = "tokenSECRET1234"
        secret_url = f"ntfy://{secret}@ntfy.sh/x"
        with app.state.sessionmaker() as db:
            _channel(db, app.state.secretstore, secret_url, name="rejected")

        monkeypatch.setattr(notifier, "send_one", lambda url, title, body: False)
        caplog.set_level(logging.DEBUG)
        assert notifier.notify(app, "job.failed", "t", "b") == 0
        assert secret not in caplog.text

    asyncio.run(run())


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
    """`ap.add()` rejecting a URL returns False from send_one, the ordinary
    Apprise failure mode, distinct from an exception; and must be isolated
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
    exactly the kind of thing that can silently do nothing, confirm it doesn't.
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


def test_sweep_orphans_fires_one_aggregate_notification_without_blocking_startup(
        tmp_path, monkeypatch):
    """`sweep_orphans` runs during lifespan startup; the bulk UPDATE that
    marks orphans is the only writer of `interrupted` in the backend, so it
    must be the one that schedules the Notifier, but as a single background
    task regardless of backlog size (not one send per orphan, which would
    queue N blocking Apprise calls onto the shared default executor that the
    poller/metrics/SSE hops also use), and never awaited inline."""
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
        monkeypatch.setattr(
            notifier, "notify",
            lambda a, event, title, body: seen.append((event, body)) or 1)

        backend = JobBackend(app)
        n = backend.sweep_orphans()  # must return immediately, not await sends
        assert n == 2

        for _ in range(50):  # the notify hop is a background thread
            if seen:
                break
            await asyncio.sleep(0.05)
        assert len(seen) == 1  # one aggregate call, not one per orphan
        event, body = seen[0]
        assert event == "job.interrupted"
        assert "app.start" in body and "app.stop" in body

    asyncio.run(run())


def test_channels_for_restricted_to_explicit_ids(tmp_path):
    """only_ids is an override: named channels are used regardless of their
    `events` subscription, but never when disabled."""
    from proxploy.models import NotificationChannel
    from proxploy.services.notifier import channels_for
    from tests.support import make_db

    db = make_db(tmp_path)
    wanted = NotificationChannel(name="a", kind="webhook", url_enc=b"x",
                                 key_version=1, events=["job.failed"], enabled=True)
    other = NotificationChannel(name="b", kind="webhook", url_enc=b"x",
                                key_version=1, events=[], enabled=True)
    off = NotificationChannel(name="c", kind="webhook", url_enc=b"x",
                              key_version=1, events=[], enabled=False)
    db.add_all([wanted, other, off])
    db.commit()

    got = channels_for(db, "alert.fired", only_ids=[wanted.id, off.id])
    assert [c.name for c in got] == ["a"]
    # unchanged without only_ids: subscription rules apply
    assert {c.name for c in channels_for(db, "alert.fired")} == {"b"}


# --- Master switch, and the job kind we used to throw away ------------------

def test_a_named_kind_notifies_under_its_own_row():
    """jobs/backend.py used to discard the kind and emit job.failed for every
    outcome, which is why "App install failed" could not be its own switch."""
    from proxploy.services.notification_types import type_for_job

    assert type_for_job("app.install", "failed") == "app.install.failed"
    assert type_for_job("vm.create", "failed") == "job.failed"


def test_notify_returns_early_for_a_disabled_type(tmp_path, monkeypatch):
    """Off means no channel is decrypted and no Apprise send runs, not that
    the send happens and its result is discarded."""
    from fastapi.testclient import TestClient

    from proxploy.services import notifier
    from proxploy.services.notification_prefs import set_overrides
    from tests.support import make_app

    app = make_app(tmp_path)
    sent = []
    monkeypatch.setattr(notifier, "send_one",
                        lambda *a, **k: (sent.append(a), True)[1])
    with TestClient(app):
        with app.state.sessionmaker() as db:
            _channel(db, app.state.secretstore, "ntfy://ntfy.sh/t", events=[])
            set_overrides(db, {"job.succeeded": False})

        assert notifier.notify(app, "job.succeeded", "t", "b") == 0
        assert sent == []

        assert notifier.notify(app, "job.failed", "t", "b") == 1
        assert len(sent) == 1


def test_an_unknown_event_still_sends(tmp_path, monkeypatch):
    """A type we cannot find is a mapping bug. Swallowing the notification
    would hide it; sending it makes it visible."""
    from fastapi.testclient import TestClient

    from proxploy.services import notifier
    from tests.support import make_app

    app = make_app(tmp_path)
    monkeypatch.setattr(notifier, "send_one", lambda *a, **k: True)
    with TestClient(app):
        with app.state.sessionmaker() as db:
            _channel(db, app.state.secretstore, "ntfy://ntfy.sh/t", events=[])
        assert notifier.notify(app, "something.new", "t", "b") == 1
