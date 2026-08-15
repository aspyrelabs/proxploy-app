"""Every serialized datetime must be an unambiguous UTC instant.

Timestamps are stored naive-UTC (proxploy.models.utcnow). A bare
`dt.isoformat()` has no offset, and a browser's `new Date("...")` reads an
offset-less string as LOCAL time, not UTC -- silently shifting every
timestamp shown in the UI by the viewer's own timezone. This file proves the
fix (proxploy.models.to_iso) is wired into the endpoints that were shown to
render the wrong time in the live app: audit, sessions, hosts.
"""
from datetime import datetime, timezone

from proxploy.models import Host, to_iso


def _assert_unambiguous_utc(raw: str) -> datetime:
    """A JS `new Date(raw)` must read this as UTC, never local time. That
    requires an explicit offset (a "Z" or a "+HH:MM"/"-HH:MM" suffix)."""
    assert raw[-1] == "Z" or raw[-6] in "+-", f"{raw!r} has no timezone marker"
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def test_audit_ts_is_an_unambiguous_utc_instant(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)  # writes an auth.login audit row
    r = client.get("/api/v1/audit", params={"action": "auth.login"})
    events = r.json()
    assert events, "bootstrap_admin should have produced a login audit row"
    _assert_unambiguous_utc(events[0]["ts"])


def test_sessions_created_at_and_last_seen_at_are_unambiguous_utc(
        client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    rows = client.get("/api/v1/auth/sessions").json()
    assert rows
    for row in rows:
        _assert_unambiguous_utc(row["created_at"])
        # last_seen_at is nullable; only check the ones actually set.
        if row["last_seen_at"] is not None:
            _assert_unambiguous_utc(row["last_seen_at"])


def test_hosts_last_seen_at_is_an_unambiguous_utc_instant(
        client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    now = datetime(2026, 8, 15, 14, 7, 21, 136877, tzinfo=timezone.utc).replace(tzinfo=None)
    with client.app.state.sessionmaker() as db:
        db.add(Host(name="h1", address="https://pve:8006", status="connected",
                    last_seen_at=now))
        db.commit()

    row = client.get("/api/v1/hosts").json()[0]
    parsed = _assert_unambiguous_utc(row["last_seen_at"])
    assert parsed == now.replace(tzinfo=timezone.utc)


def test_to_iso_handles_none_and_does_not_double_suffix_aware_values():
    assert to_iso(None) is None

    naive = datetime(2026, 8, 15, 14, 7, 21)
    assert to_iso(naive) == "2026-08-15T14:07:21Z"

    aware_utc = datetime(2026, 8, 15, 14, 7, 21, tzinfo=timezone.utc)
    out = to_iso(aware_utc)
    assert out is not None and not out.endswith("ZZ")
    assert datetime.fromisoformat(out) == aware_utc


def test_hosts_last_seen_at_null_when_unset(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        db.add(Host(name="h2", address="https://pve2:8006", status="connected"))
        db.commit()

    row = next(h for h in client.get("/api/v1/hosts").json() if h["name"] == "h2")
    assert row["last_seen_at"] is None
