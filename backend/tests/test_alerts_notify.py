"""Alert -> Notifier routing and the SSE frame shape (doc 05 §Streaming)."""
import asyncio

from proxploy.models import NotificationChannel
from proxploy.services.alerts import notify_transitions, sse_frame
from tests.support import make_job_app


def _channel(app, name, events, enabled=True):
    with app.state.sessionmaker() as db:
        blob, ver = app.state.secretstore.encrypt(b"json://example.com/hook")
        row = NotificationChannel(name=name, kind="webhook", url_enc=blob,
                                  key_version=ver, events=events, enabled=enabled)
        db.add(row)
        db.commit()
        return row.id


def _t(**kw):
    base = {"alert_id": 1, "rule_id": 2, "rule_name": "CPU high",
            "state": "firing", "severity": "warning", "target_type": "host",
            "target_id": 3, "target_label": "host-02", "value": 92.0,
            "message": "host-02 CPU > 85% for 5m (now 92%)", "channel_ids": []}
    base.update(kw)
    return base


def test_sse_frame_matches_the_doc_05_shape(tmp_path):
    """doc 05: {"id":12,"state":"firing","severity":"warning","message":"…"}"""
    assert sse_frame(_t(alert_id=12)) == {
        "id": 12, "state": "firing", "severity": "warning",
        "message": "host-02 CPU > 85% for 5m (now 92%)"}


def test_a_firing_alert_reaches_channels_subscribed_to_alert_fired(tmp_path, monkeypatch):
    # make_job_app requires a running event loop (support.py:81,
    # asyncio.get_running_loop()) -- same asyncio.run(run()) wrapper every
    # other make_job_app test in this suite uses (e.g. test_notifier.py).
    async def run():
        app = make_job_app(tmp_path)
        _channel(app, "subscribed", ["alert.fired"])
        _channel(app, "wrong event", ["job.failed"])
        _channel(app, "all events", [])

        sent = []
        monkeypatch.setattr("proxploy.services.notifier.send_one",
                            lambda url, title, body: sent.append((title, body)) or True)

        assert notify_transitions(app, [_t()]) == 2      # subscribed + all-events
        assert all("host-02" in body for _, body in sent)

    asyncio.run(run())


def test_a_resolved_alert_routes_on_alert_resolved(tmp_path, monkeypatch):
    async def run():
        app = make_job_app(tmp_path)
        _channel(app, "fired only", ["alert.fired"])
        _channel(app, "resolved only", ["alert.resolved"])

        sent = []
        monkeypatch.setattr("proxploy.services.notifier.send_one",
                            lambda url, title, body: sent.append(title) or True)

        assert notify_transitions(app, [_t(state="resolved")]) == 1
        assert len(sent) == 1

    asyncio.run(run())


def test_rule_channel_ids_override_the_event_subscription(tmp_path, monkeypatch):
    """A rule that names its channels means EXACTLY those, not those plus
    everything subscribed to alert.fired."""
    async def run():
        app = make_job_app(tmp_path)
        chosen = _channel(app, "chosen", [])
        _channel(app, "also subscribed to everything", [])

        sent = []
        monkeypatch.setattr("proxploy.services.notifier.send_one",
                            lambda url, title, body: sent.append(title) or True)

        assert notify_transitions(app, [_t(channel_ids=[chosen])]) == 1
        assert len(sent) == 1

    asyncio.run(run())


def test_a_named_channel_that_is_disabled_still_does_not_fire(tmp_path, monkeypatch):
    async def run():
        app = make_job_app(tmp_path)
        off = _channel(app, "off", [], enabled=False)
        monkeypatch.setattr("proxploy.services.notifier.send_one",
                            lambda url, title, body: True)
        assert notify_transitions(app, [_t(channel_ids=[off])]) == 0

    asyncio.run(run())


def test_a_channel_that_raises_never_stops_the_others(tmp_path, monkeypatch):
    async def run():
        app = make_job_app(tmp_path)
        _channel(app, "broken", [])
        _channel(app, "fine", [])

        calls = {"n": 0}

        def flaky(url, title, body):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("connection refused to https://user:pass@host")
            return True

        monkeypatch.setattr("proxploy.services.notifier.send_one", flaky)
        assert notify_transitions(app, [_t()]) == 1

    asyncio.run(run())


def test_the_notification_body_never_carries_a_channel_url(tmp_path, monkeypatch,
                                                           caplog):
    """A raised Apprise error can interpolate the raw URL; notifier.notify logs
    the redacted form only."""
    import logging

    async def run():
        app = make_job_app(tmp_path)
        _channel(app, "broken", [])

        def boom(url, title, body):
            raise RuntimeError(f"failed talking to {url}")

        monkeypatch.setattr("proxploy.services.notifier.send_one", boom)
        with caplog.at_level(logging.DEBUG, logger="proxploy.services.notifier"):
            notify_transitions(app, [_t()])
        assert "example.com/hook" not in caplog.text

    asyncio.run(run())


def test_an_empty_transition_list_sends_nothing(tmp_path, monkeypatch):
    async def run():
        app = make_job_app(tmp_path)
        _channel(app, "c", [])
        monkeypatch.setattr("proxploy.services.notifier.send_one",
                            lambda *a: (_ for _ in ()).throw(AssertionError("sent!")))
        assert notify_transitions(app, []) == 0

    asyncio.run(run())
