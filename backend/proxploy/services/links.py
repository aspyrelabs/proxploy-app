"""Where a thing lives in the UI, and how to say that absolutely.

Two callers need this and they must not disagree. api/search.py builds hrefs
for the command palette, and notifications now build the same paths so a
message about a failed backup can offer to open the thing it failed on. The
one time these were written twice, the backend generated /settings/hosts/{id}
for a route that never existed and nothing noticed until someone clicked it.

Paths are relative here. Making one absolute needs `public_url`, which nobody
can derive: `api_base_url` in config is the licence server, and the Host
header is attacker-controllable, so guessing would put a link to somewhere
else in an email we sent. Unset means no link, which is strictly better than
a link that 404s.
"""
from __future__ import annotations

from proxploy.services.settings import get_setting

PUBLIC_URL_KEY = "public_url"

# The same hrefs api/search.py hands the command palette. `?open=` is how both
# list pages accept "and show me this one".
_PATHS = {
    "app": lambda i: f"/apps?open={i}",
    "vm": lambda i: f"/vms?open={i}",
    # Hosts have no page of their own; they are a Settings section.
    "host": lambda i: "/settings?section=hosts",
    "backup": lambda i: "/backups",
    "schedule": lambda i: "/settings?section=schedules",
    "notification_channel": lambda i: "/settings?section=channels",
    "alert_rule": lambda i: "/alerts",
    "user": lambda i: "/settings?section=users",
    "team": lambda i: "/settings?section=teams",
    "api_key": lambda i: "/settings?section=api-keys",
}


def path_for(target_type: str | None, target_id: int | None = None) -> str | None:
    """The UI path for one thing, or None when it has no page worth opening.

    None rather than "/" on purpose: a link to the dashboard is not an answer
    to "what failed", and offering one trains people to ignore the link.
    """
    if not target_type:
        return None
    build = _PATHS.get(target_type)
    return build(target_id) if build else None


def public_url(db) -> str:
    """The address an operator reaches this installation on, or "" if nobody
    has said. Never guessed."""
    return str(get_setting(db, PUBLIC_URL_KEY, "") or "").rstrip("/")


def absolute(db, path: str | None) -> str:
    """A full URL for `path`, or "" when there is no path or no public_url."""
    if not path:
        return ""
    base = public_url(db)
    return f"{base}{path}" if base else ""
