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

# Apprise's logger propagates to the root logger by default, which would defeat
# "never logged" (see module docstring) the moment any handler is configured —
# set once at import; this doesn't require apprise itself to be imported yet.
logging.getLogger("apprise").propagate = False


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
            if send_one(url, title, body):
                reached.append(channel_id)
        except Exception:  # noqa: BLE001 — never let one channel poison the rest
            continue

    if reached:
        with app.state.sessionmaker() as db:
            (db.query(NotificationChannel)
             .filter(NotificationChannel.id.in_(reached))
             .update({"last_notified_at": utcnow()}, synchronize_session=False))
            db.commit()
    return len(reached)
