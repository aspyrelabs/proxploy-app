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
import re

from proxploy.models import NotificationChannel, utcnow

# Apprise's logger propagates to the root logger by default, which would defeat
# "never logged" (see module docstring) the moment any handler is configured —
# set once at import; this doesn't require apprise itself to be imported yet.
logging.getLogger("apprise").propagate = False

# Display label from the URL scheme (doc 04 `kind`). Unknown schemes keep their
# own scheme as the label rather than being coerced into "webhook".
KIND_FROM_SCHEME = {
    "ntfy": "ntfy", "ntfys": "ntfy",
    "gotify": "gotify", "gotifys": "gotify",
    "mailto": "email", "mailtos": "email",
    "tgram": "telegram",
    "slack": "slack",
    "json": "webhook", "jsons": "webhook",
    "form": "webhook", "forms": "webhook",
    "xml": "webhook", "xmls": "webhook",
}

_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*$")


def kind_for(url: str) -> str:
    """Doc 04: `kind` is a display label parsed from the URL *scheme* only.

    A URL with no `://` has no scheme — `split` then returns the whole
    string, which for a URL-shaped secret (no scheme separator typed) is the
    token itself. Only accept the split result when it actually looks like a
    scheme; anything else falls back to "webhook" rather than writing a
    plaintext secret into the unencrypted `kind` column.
    """
    scheme = url.split("://", 1)[0].strip().lower()
    if scheme in KIND_FROM_SCHEME:
        return KIND_FROM_SCHEME[scheme]
    return scheme if _SCHEME_RE.match(scheme) else "webhook"


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
