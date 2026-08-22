"""Notification channels (doc 05 §Notifications).

The Apprise URL is write-only: it goes in encrypted and never comes back out:
not in a response, not in an audit row, not in an error message.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from proxploy.api.deps import authorize, get_db, require_entitlement
from proxploy.models import NotificationChannel, User, to_iso, utcnow
from proxploy.services.audit import write_audit
from proxploy.services.notification_catalog import build_url, public_catalog
from proxploy.services.notification_prefs import effective, set_overrides
from proxploy.services.notification_types import BY_KEY, TYPES
from proxploy.services.notifier import kind_for, parses, send_one

router = APIRouter(prefix="/notifications", tags=["notifications"])

# Reused as BOTH the route-level dependency and the parameter-level one below
# so FastAPI's dependency cache (keyed on the callable) collapses them into a
# single call. A bare `dependencies=[Depends(require_entitlement(...))]` sits
# at position 0 of the dependant and would run BEFORE this auth check,
# leaking 403 to an anonymous caller who should see 401 (Tasks 3 and 5 hit
# this: see jobs.py/apps.py). Putting `_manage` first in the dependencies
# list forces auth -> authz -> entitlement, in that order. Doc 05: every
# notifications route is admin, no viewer read tier: one permission covers
# the whole router.
_manage = authorize("channel", "manage")


class ChannelIn(BaseModel):
    name: str
    # Two ways in, exactly one of which must be filled (see _resolve_url).
    # `url` is the escape hatch the form has always had, and every existing
    # caller still uses it unchanged; `kind` + `fields` is the guided picker.
    url: str | None = None
    kind: str | None = None
    fields: dict[str, str] | None = None
    events: list[str] | None = None
    enabled: bool = True


class ChannelPatch(BaseModel):
    name: str | None = None
    url: str | None = None
    events: list[str] | None = None
    enabled: bool | None = None


class TypesPatch(BaseModel):
    enabled: dict[str, bool]


def _out(c: NotificationChannel) -> dict:
    return {"id": c.id, "name": c.name, "kind": c.kind, "events": c.events or [],
            "enabled": c.enabled,
            "last_notified_at": to_iso(c.last_notified_at)}


def _require_url(url: str) -> str:
    if "://" not in url:
        raise HTTPException(422, "url must be an Apprise URL, e.g. ntfy://host/topic")
    return url


def _resolve_url(body: ChannelIn) -> str:
    """Turn either input shape into one Apprise URL.

    A guided channel is checked against Apprise's parser here, before it is
    ever encrypted and stored: a kind whose fields do not actually assemble
    into something Apprise recognises would otherwise save cleanly, show a
    correct-looking badge, and silently never deliver. The pasted-URL path
    keeps its older, looser check, tightening it would reject targets that
    work today for the 122 services the catalog does not cover.
    """
    if body.kind is not None:
        if body.url:
            raise HTTPException(422, "Send either a URL or a kind, not both.")
        try:
            url = build_url(body.kind, body.fields or {})
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        if not parses(url):
            raise HTTPException(
                422, f"Those {body.kind} details are not something Apprise "
                     "can send to. Check them and try again.")
        return url
    if not body.url:
        raise HTTPException(422, "A channel needs either a URL or a kind.")
    return _require_url(body.url)


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/channels", dependencies=[Depends(_manage),
                                       Depends(require_entitlement("notify.channels"))])
def list_channels(db=Depends(get_db), user: User = Depends(_manage)):
    return [_out(c) for c in db.query(NotificationChannel).order_by(NotificationChannel.id)]


@router.get("/kinds", dependencies=[Depends(_manage),
                                    Depends(require_entitlement("notify.channels"))])
def list_kinds():
    """The questions the guided picker asks, per service. No templates: the
    client sends back what it collected and the server assembles the URL, so
    the only percent-encoding that ever runs is build_url()'s."""
    return public_catalog()


def _types_out(db) -> dict:
    live = effective(db)
    return {"types": [{"key": t.key, "label": t.label, "group": t.group,
                       "enabled": live[t.key]} for t in TYPES]}


@router.get("/types", dependencies=[Depends(_manage)])
def list_types(db=Depends(get_db)):
    """Deliberately NOT behind notify.channels: the master switches are how
    someone with no channels at all stops a toast, so gating them on the
    channel feature would make "turn that off" unreachable on the very
    installs most likely to want it."""
    return _types_out(db)


@router.patch("/types", dependencies=[Depends(_manage)])
def patch_types(request: Request, body: TypesPatch, db=Depends(get_db),
                user: User = Depends(_manage)):
    unknown = sorted(set(body.enabled) - set(BY_KEY))
    if unknown:
        raise HTTPException(422, f"unknown notification type: {unknown[0]}")
    set_overrides(db, body.enabled)
    write_audit(db, actor_type="user", actor_id=user.id,
                action="notify.types.update", target_type="setting",
                params={"changed": sorted(body.enabled)}, ip=_ip(request))
    return _types_out(db)


@router.post("/channels", status_code=201,
             dependencies=[Depends(_manage),
                          Depends(require_entitlement("notify.channels"))])
def create_channel(request: Request, body: ChannelIn, db=Depends(get_db),
                   user: User = Depends(_manage)):
    url = _resolve_url(body)
    blob, ver = request.app.state.secretstore.encrypt(url.encode())
    row = NotificationChannel(name=body.name, kind=kind_for(url),
                              url_enc=blob, key_version=ver,
                              events=body.events or [], enabled=body.enabled)
    db.add(row)
    db.commit()
    # params carries the label only: the URL is a secret and never enters audit.
    write_audit(db, actor_type="user", actor_id=user.id,
                action="notify.channel.create", target_type="notification_channel",
                target_id=row.id, params={"name": row.name, "kind": row.kind},
                ip=_ip(request))
    return _out(row)


@router.patch("/channels/{channel_id}",
              dependencies=[Depends(_manage),
                           Depends(require_entitlement("notify.channels"))])
def patch_channel(request: Request, channel_id: int, body: ChannelPatch,
                  db=Depends(get_db), user: User = Depends(_manage)):
    row = db.get(NotificationChannel, channel_id)
    if row is None:
        raise HTTPException(404, "channel not found")
    if body.name is not None:
        row.name = body.name
    if body.events is not None:
        row.events = body.events
    if body.enabled is not None:
        row.enabled = body.enabled
    if body.url is not None:
        _require_url(body.url)
        row.url_enc, row.key_version = request.app.state.secretstore.encrypt(
            body.url.encode())
        row.kind = kind_for(body.url)
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id,
                action="notify.channel.update", target_type="notification_channel",
                target_id=row.id,
                params={"name": row.name, "enabled": row.enabled, "kind": row.kind,
                        "url_rotated": body.url is not None,
                        "events_changed": body.events is not None},
                ip=_ip(request))
    return _out(row)


@router.delete("/channels/{channel_id}", status_code=204,
               dependencies=[Depends(_manage),
                            Depends(require_entitlement("notify.channels"))])
def delete_channel(request: Request, channel_id: int, db=Depends(get_db),
                   user: User = Depends(_manage)):
    row = db.get(NotificationChannel, channel_id)
    if row is None:
        raise HTTPException(404, "channel not found")
    name, kind = row.name, row.kind
    db.delete(row)
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id,
                action="notify.channel.delete", target_type="notification_channel",
                target_id=channel_id, params={"name": name, "kind": kind},
                ip=_ip(request))
    return Response(status_code=204)


@router.post("/channels/{channel_id}/test",
             dependencies=[Depends(_manage),
                          Depends(require_entitlement("notify.channels"))])
def test_channel(request: Request, channel_id: int, db=Depends(get_db),
                 user: User = Depends(_manage)):
    row = db.get(NotificationChannel, channel_id)
    if row is None:
        raise HTTPException(404, "channel not found")
    url = request.app.state.secretstore.decrypt(row.url_enc).decode()
    try:
        sent = bool(send_one(url, "Proxploy test notification",
                             f"This is a test from Proxploy for channel {row.name!r}."))
    except Exception:  # noqa: BLE001  (a bad target is a report, not a 500)
        sent = False
    if sent:
        row.last_notified_at = utcnow()
        db.commit()
    write_audit(db, actor_type="user", actor_id=user.id, action="notify.channel.test",
                target_type="notification_channel", target_id=row.id,
                result="ok" if sent else "error", params={"name": row.name},
                ip=_ip(request))
    return {"sent": sent}
