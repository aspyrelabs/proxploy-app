"""Notifier seam (brief §5, doc 03) -> Apprise.

One dependency covers ntfy, gotify, email, Telegram, Slack and generic
webhooks. Apprise URLs embed tokens and passwords, so the URL itself is an
encrypted blob (doc 04 `notification_channels.url_enc`) and is never returned
by any endpoint, never written to an audit row, and never logged.

Everything here is blocking (Apprise does its own network I/O). Callers on the
event loop wrap it in asyncio.to_thread.
"""
from __future__ import annotations

import logging

from proxploy.models import KIND_FROM_SCHEME, NotificationChannel, utcnow

logger = logging.getLogger(__name__)

# Apprise's logger propagates to the root logger by default, which would defeat
# "never logged" (see module docstring) the moment any handler is configured —
# set once at import; this doesn't require apprise itself to be imported yet.
#
# This alone is NOT sufficient: Apprise's plugins send over `requests`, whose
# connection pooling logs the request line (method + full path/query — for
# schemes where the token lives in the path, e.g. json/form/xml webhooks, that
# IS the token) via a separate "urllib3" logger tree that never touches
# "apprise" at all. Silencing "apprise" alone leaves that tree fully live —
# confirmed by capturing a real failed send at DEBUG with propagation on
# before this line existed: the token showed up under "urllib3.connectionpool".
logging.getLogger("apprise").propagate = False
logging.getLogger("urllib3").propagate = False


def kind_for(url: str) -> str:
    """Doc 04: `kind` is a display label parsed from the URL *scheme* only.

    Never returns caller-supplied text. `kind` is an unencrypted `Text`
    column, so any fallback that echoes part of the input (the scheme, or
    even a length/shape-filtered version of it) is a plaintext-secret leak
    the moment a channel URL is malformed or a bare credential is pasted
    without a scheme at all — a URL-shaped guard can always be walked around
    by appending "://" or picking a short lowercase-and-dashes token. An
    unrecognised-but-legitimate scheme showing as "webhook" is a fine
    outcome; there is no other fallback.
    """
    scheme = url.split("://", 1)[0].strip().lower() if "://" in url else ""
    return KIND_FROM_SCHEME.get(scheme, "webhook")


def redact_url(url: str) -> str:
    """Safe-to-log/safe-to-show stand-in for an Apprise URL — use this
    anywhere a channel URL would otherwise reach a log line or a human-visible
    string. Same allowlist discipline as `kind_for`: the visible scheme label
    is never echoed input, only a fixed label from `KIND_FROM_SCHEME` (or
    "webhook"). With no "://" at all there's nothing safe to show, so this
    returns a bare "***".
    """
    if "://" not in url:
        return "***"
    return f"{kind_for(url)}://***"


def send_one(url: str, title: str, body: str) -> bool:
    """The ONE Apprise call site. Blocking."""
    import apprise

    ap = apprise.Apprise()
    if not ap.add(url):
        return False
    return bool(ap.notify(title=title, body=body))


def channels_for(db, event: str) -> list[NotificationChannel]:
    """Doc 04: an empty `events` list means every event."""
    return [c for c in db.query(NotificationChannel).filter_by(enabled=True).all()
            if not c.events or event in c.events]


def notify(app, event: str, title: str, body: str) -> int:
    """Fan a single event out to every subscribed channel. Returns channels reached.

    A channel that is misconfigured, unreachable or slow must never fail the
    job that triggered it — each send is isolated. Decryption happens inside
    the session (cheap); the blocking Apprise sends happen outside it, so a
    slow/hanging channel doesn't hold a DB connection checked out for
    ~8s-per-channel (Apprise's default connect+read timeout) while every
    other channel's `last_notified_at` stamp waits behind it.
    """
    with app.state.sessionmaker() as db:
        targets = []
        for channel in channels_for(db, event):
            try:
                url = app.state.secretstore.decrypt(channel.url_enc).decode()
            except Exception:  # noqa: BLE001 — never let one channel poison the rest
                continue
            targets.append((channel.id, url))

    reached = []
    for channel_id, url in targets:
        try:
            ok = send_one(url, title, body)
        except Exception:  # noqa: BLE001 — never let one channel poison the rest
            # Log the redacted URL, never the exception object: a channel is
            # free to raise with the raw URL interpolated into its message
            # (send_one's own caller — the HTTP test endpoint — sees exactly
            # that from real Apprise plugin errors), and `str(exc)`/`repr(exc)`
            # would carry it straight into this log line otherwise.
            logger.debug("channel %s raised during send: %s",
                        channel_id, redact_url(url))
            continue
        if ok:
            reached.append(channel_id)
        else:
            logger.debug("channel %s did not deliver: %s", channel_id, redact_url(url))

    if reached:
        with app.state.sessionmaker() as db:
            (db.query(NotificationChannel)
             .filter(NotificationChannel.id.in_(reached))
             .update({"last_notified_at": utcnow()}, synchronize_session=False))
            db.commit()
    return len(reached)
