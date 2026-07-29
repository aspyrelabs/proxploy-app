"""Notifier seam (brief §5, doc 03) -> Apprise.

One dependency covers ntfy, gotify, email, Telegram, Slack and generic
webhooks. Apprise URLs embed tokens and passwords, so the URL itself is an
encrypted blob (doc 04 `notification_channels.url_enc`) and is never returned
by any endpoint, never written to an audit row, and never logged.

Everything here is blocking (Apprise does its own network I/O). Callers on the
event loop wrap it in asyncio.to_thread.
"""
from __future__ import annotations

from proxploy.models import NotificationChannel, utcnow

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


def kind_for(url: str) -> str:
    scheme = url.split("://", 1)[0].strip().lower()
    return KIND_FROM_SCHEME.get(scheme, scheme or "webhook")


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
    job that triggered it — each send is isolated.
    """
    sent = 0
    with app.state.sessionmaker() as db:
        for channel in channels_for(db, event):
            try:
                url = app.state.secretstore.decrypt(channel.url_enc).decode()
                if send_one(url, title, body):
                    channel.last_notified_at = utcnow()
                    sent += 1
            except Exception:  # noqa: BLE001 — never let one channel poison the rest
                continue
        db.commit()
    return sent
