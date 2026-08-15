"""Scoped, revocable bearer tokens (doc 04 `api_keys`, doc 08 §6, Task 12).

Self-service: a user manages only their own keys, no team scoping needed, so
routes gate on `get_current_user` + `require_entitlement("api.tokens")`
rather than `authorize()`; there is no (resource, action) pair for "manage
my own keys". The scope *check* itself lives in `api/deps.py::authorize`,
folded in right before the casbin decision on every OTHER route.

The raw key (`ppk_...`) exists in exactly one response body, ever: this
router's create() return value. Only `prefix` + sha256 `key_hash` persist,
and no write_audit() call in this file ever receives the raw string.
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from proxploy.api.deps import get_current_user, get_db, require_entitlement
from proxploy.models import ApiKey, User, to_iso, utcnow
from proxploy.services.audit import write_audit
from proxploy.services.authz import PERMISSIONS

router = APIRouter(prefix="/api-keys", tags=["api-keys"])

# "read" or "<matrix-resource-name>:write": e.g. "app:write", "vm:write".
# Doc 04's example ("apps:write") is plural; the matrix's resource name is
# singular ("app"), so that string is normalised here, not copied verbatim.
_SCOPE_RE = re.compile(r"^(read|[a-z]+:write)$")
_RESOURCES = {resource for resource, _ in PERMISSIONS}


def _validate_scopes(scopes: list[str]) -> None:
    for s in scopes:
        m = _SCOPE_RE.match(s)
        if not m or (s != "read" and s.split(":", 1)[0] not in _RESOURCES):
            raise HTTPException(422, f"unknown scope: {s!r}")


class ApiKeyIn(BaseModel):
    name: str
    scopes: list[str] = []
    expires_at: datetime | None = None


def _out(row: ApiKey) -> dict:
    return {"id": row.id, "name": row.name, "prefix": row.prefix,
            "scopes": row.scopes, "expires_at": to_iso(row.expires_at),
            "last_used_at": to_iso(row.last_used_at),
            "revoked_at": to_iso(row.revoked_at), "created_at": to_iso(row.created_at)}


@router.post("", status_code=201,
             dependencies=[Depends(get_current_user),
                          Depends(require_entitlement("api.tokens"))])
def create_api_key(body: ApiKeyIn, db=Depends(get_db),
                   user: User = Depends(get_current_user)):
    _validate_scopes(body.scopes)
    raw = "ppk_" + secrets.token_urlsafe(32)
    prefix = raw[:8]
    # SHA-256, not a slow hash: a 256-bit random token has no dictionary to
    # attack, unlike a password: argon2 here would just cost 100ms/request
    # for nothing (same pattern as services/authn.py::_th for session tokens).
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    row = ApiKey(user_id=user.id, name=body.name, prefix=prefix,
                key_hash=key_hash, scopes=body.scopes, expires_at=body.expires_at)
    db.add(row)
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id, action="apikey.create",
                target_type="api_key", target_id=row.id,
                params={"name": row.name, "prefix": row.prefix, "scopes": row.scopes})
    return {**_out(row), "key": raw}


@router.get("", dependencies=[Depends(get_current_user),
                              Depends(require_entitlement("api.tokens"))])
def list_api_keys(db=Depends(get_db), user: User = Depends(get_current_user)):
    rows = (db.query(ApiKey).filter_by(user_id=user.id)
            .order_by(ApiKey.created_at.desc()).all())
    return [_out(r) for r in rows]


@router.delete("/{key_id}", status_code=204,
               dependencies=[Depends(get_current_user),
                            Depends(require_entitlement("api.tokens"))])
def revoke_api_key(request: Request, key_id: int, db=Depends(get_db),
                   user: User = Depends(get_current_user)):
    row = db.query(ApiKey).filter_by(id=key_id, user_id=user.id).one_or_none()
    if row is None:
        # Also true of another user's key: 404, not 403: existence of
        # someone else's key id is not this caller's information either way,
        # and an admin revokes access by deactivating the user, not by
        # reaching into another user's keys (doc 04, kept simple).
        raise HTTPException(404, "api key not found")
    row.revoked_at = utcnow()
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id, action="apikey.revoke",
                target_type="api_key", target_id=row.id,
                params={"name": row.name, "prefix": row.prefix},
                ip=request.client.host if request.client else None)
    return Response(status_code=204)
