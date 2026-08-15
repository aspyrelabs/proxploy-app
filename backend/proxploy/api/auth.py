import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from proxploy.api.deps import (ROLE_ORDER, authorize, default_team, get_current_user,
                               get_db, require_entitlement, user_role)
from proxploy.models import SessionRow, TeamMember, User, utcnow
from proxploy.services import authn, oidc, totp
from proxploy.services.audit import write_audit
from proxploy.services.authz import enforce

limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/auth", tags=["auth"])
users_router = APIRouter(prefix="/users", tags=["users"])

# Module-level singleton (hosts.py idiom, api/deps.py::authorize docstring):
# GET/PUT/DELETE all gate on the same ("settings", "manage") permission: the
# OIDC IdP config is an "own flow" settings.py's `.enc`-key refusal points at.
_oidc_manage = authorize("settings", "manage")

# GET /users (Task 6, doc 05): the member-picker source, ("user", "read")
# global (any-team admin, no scope_of): same status as ("user", "manage")
# in create_user below.
_users_read = authorize("user", "read")


class UserIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12)
    display_name: str | None = None
    role: str = "viewer"


def _user_out(db, user: User) -> dict:
    return {"id": user.id, "email": user.email, "display_name": user.display_name,
            "role": user_role(db, user), "totp_enabled": user.totp_enabled}


def _issue_session(request: Request, response: Response, db, user: User) -> dict:
    """The exact create_session + set_cookie + audit block both login paths
    (password-only, and the TOTP second factor below) need; extracted so
    the two cannot drift apart."""
    settings = request.app.state.settings
    ip = request.client.host if request.client else None
    raw = authn.create_session(db, user, ip, request.headers.get("user-agent"),
                               settings.session_ttl_hours)
    write_audit(db, actor_type="user", actor_id=user.id, action="auth.login", ip=ip)
    response.set_cookie(settings.session_cookie, raw, httponly=True, samesite="lax",
                        secure=settings.cookie_secure)
    return {"ok": True, "user": _user_out(db, user)}


# --- Pending-2FA store (Task 9) ---------------------------------------------
#
# NOT a session and cannot be turned into one by any request other than
# POST /auth/totp: resolve_session()/get_current_user never look at
# app.state.pending_totp, so holding a pending token grants access to
# exactly one route, and that route only completes or burns it. Single-use
# (popped on success), TTL-bounded (pruned on every access), and capped at
# PENDING_MAX_ATTEMPTS wrong codes before the entry is discarded outright.
PENDING_MAX_ATTEMPTS = 5


def _create_pending(request: Request, user: User) -> str:
    raw = secrets.token_urlsafe(32)
    ttl = request.app.state.settings.totp_pending_ttl_s
    request.app.state.pending_totp[authn._th(raw)] = (user.id, utcnow() + timedelta(seconds=ttl), 0)
    return raw


def _prune_pending(request: Request) -> None:
    store = request.app.state.pending_totp
    now = utcnow()
    for key in [k for k, (_, expires_at, _) in store.items() if expires_at < now]:
        del store[key]


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TotpLoginIn(BaseModel):
    pending: str
    code: str


@router.post("/login")
@limiter.limit("10/minute")
def login(request: Request, body: LoginIn, response: Response, db=Depends(get_db)):
    user = db.query(User).filter_by(email=body.email).one_or_none()
    ip = request.client.host if request.client else None
    # Always one password verification, even with nothing to verify against.
    # Short-circuiting on "no such email" or "no password on this account"
    # answered in the time of one indexed SELECT while a real password
    # account took a full argon2id run, so the two identical 401s below were
    # still telling anyone with a stopwatch which addresses exist.
    ok = authn.verify_password(user.password_hash if user and user.password_hash
                               else authn.DUMMY_HASH, body.password)
    if not user or not user.password_hash or not ok or not user.is_active:
        write_audit(db, actor_type="user", actor_id=user.id if user else None,
                    action="auth.login", result="error", ip=ip)
        raise HTTPException(401, "invalid credentials")
    if user.totp_enabled:
        # No cookie: the password check alone never grants a session. The
        # pending token below is the only thing this response hands back,
        # and it is not usable for anything except POST /auth/totp.
        pending = _create_pending(request, user)
        write_audit(db, actor_type="user", actor_id=user.id,
                    action="auth.login.totp_pending", ip=ip)
        return {"totp_required": True, "pending": pending}
    return _issue_session(request, response, db, user)


@router.post("/totp")
@limiter.limit("10/minute")
def totp_login(request: Request, body: TotpLoginIn, response: Response, db=Depends(get_db)):
    # PUBLIC (test_route_auth_invariant.py) and UNGOVERNED (test_rbac_invariant.py):
    # this route IS the second half of acquiring a session, so it can carry
    # neither get_current_user nor authorize(): see both files' allowlist
    # comments for this path.
    ip = request.client.host if request.client else None
    _prune_pending(request)
    store = request.app.state.pending_totp
    key = authn._th(body.pending)
    entry = store.get(key)
    ok = False
    user = None
    if entry is not None:
        user_id, expires_at, attempts = entry
        user = db.get(User, user_id)
        ok = bool(user and user.is_active and user.totp_enabled and totp.verify_login(
            db, request.app.state.secretstore, user, body.code))
        if ok:
            del store[key]  # single-use: a second call with the same pending 401s
        else:
            attempts += 1
            if attempts >= PENDING_MAX_ATTEMPTS:
                del store[key]  # attempts exhausted: re-login required, no more guesses
            else:
                store[key] = (user_id, expires_at, attempts)
    if not ok:
        write_audit(db, actor_type="user", actor_id=user.id if user else None,
                    action="auth.login", result="error", ip=ip)
        raise HTTPException(401, "invalid or expired code")
    return _issue_session(request, response, db, user)


@router.post("/logout")
def logout(request: Request, response: Response, db=Depends(get_db),
           user: User = Depends(get_current_user)):
    settings = request.app.state.settings
    raw = request.cookies.get(settings.session_cookie)
    authn.revoke_session(db, raw)
    write_audit(db, actor_type="user", actor_id=user.id, action="auth.logout")
    response.delete_cookie(settings.session_cookie)
    return {"ok": True}


@router.get("/me")
def me(db=Depends(get_db), user: User = Depends(get_current_user)):
    return _user_out(db, user)


# --- TOTP (Task 8: enrollment; login-step + session mgmt is Task 9) --------
#
# Self-service on the caller's own account, same shape as api/apikeys.py:
# `dependencies=[Depends(get_current_user), Depends(require_entitlement(...))]`
# in that order (route-ordering invariant: auth before entitlement, so an
# anonymous caller 401s, never a flag-leaking 403), plus get_current_user
# again as a function parameter to get the User back (cached per-request,
# not a second DB hit). No authorize() call: this isn't an RBAC-gated admin
# action, it's a user managing their own 2FA, so it isn't in
# services/authz.py's PERMISSIONS matrix either.
_totp_ent = require_entitlement("auth.totp")


class TotpConfirmIn(BaseModel):
    code: str


class TotpDisableIn(BaseModel):
    password: str  # or, for an OIDC-only account, a current TOTP/recovery code


@router.post("/totp/enroll",
            dependencies=[Depends(get_current_user), Depends(_totp_ent)])
def totp_enroll(request: Request, db=Depends(get_db),
                user: User = Depends(get_current_user)):
    if user.totp_enabled:
        raise HTTPException(409, "disable first")
    result = totp.start_enrollment(db, request.app.state.secretstore, user)
    write_audit(db, actor_type="user", actor_id=user.id, action="auth.totp.enroll")
    return result


@router.post("/totp/confirm",
            dependencies=[Depends(get_current_user), Depends(_totp_ent)])
def totp_confirm(request: Request, body: TotpConfirmIn, db=Depends(get_db),
                 user: User = Depends(get_current_user)):
    if not totp.confirm(db, request.app.state.secretstore, user, body.code):
        raise HTTPException(400, "invalid code")
    write_audit(db, actor_type="user", actor_id=user.id, action="auth.totp.confirm")
    return {"ok": True}


@router.delete("/totp",
               dependencies=[Depends(get_current_user), Depends(_totp_ent)])
def totp_disable(request: Request, body: TotpDisableIn, db=Depends(get_db),
                 user: User = Depends(get_current_user)):
    # Doc 08 requires re-auth before disabling 2FA. A password is the one
    # thing an OIDC-only account (password_hash IS NULL) doesn't have, so
    # that path accepts a current TOTP/recovery code in the same field
    # instead -- still proof of possession, just of the second factor
    # rather than the first.
    if user.password_hash:
        ok = authn.verify_password(user.password_hash, body.password)
    else:
        ok = totp.verify_login(db, request.app.state.secretstore, user, body.password)
    if not ok:
        raise HTTPException(403, "Confirm your identity to continue.")
    totp.disable(db, user)
    write_audit(db, actor_type="user", actor_id=user.id, action="auth.totp.disable")
    return {"ok": True}


@router.post("/totp/recovery-codes/regenerate",
            dependencies=[Depends(get_current_user), Depends(_totp_ent)])
def totp_regenerate_recovery_codes(request: Request, body: TotpDisableIn, db=Depends(get_db),
                                   user: User = Depends(get_current_user)):
    # Same re-auth requirement as disable above, and the same password-or-
    # OIDC-code check, verbatim: minting yourself a fresh set of recovery
    # codes is exactly the kind of action re-auth exists to gate, and this
    # follows that existing check rather than inventing a second pattern.
    if user.password_hash:
        ok = authn.verify_password(user.password_hash, body.password)
    else:
        ok = totp.verify_login(db, request.app.state.secretstore, user, body.password)
    if not ok:
        raise HTTPException(403, "Confirm your identity to continue.")
    codes = totp.regenerate_recovery_codes(db, request.app.state.secretstore, user)
    if codes is None:
        raise HTTPException(409, "enable two-factor first")
    write_audit(db, actor_type="user", actor_id=user.id,
                action="auth.totp.recovery_codes.regenerate")
    return {"recovery_codes": codes}


# --- Session management (Task 9) --------------------------------------------
#
# Self-service on the caller's own sessions, same idiom as api/apikeys.py:
# gated on get_current_user alone (no authorize(): "list/revoke my own
# sessions" has no (resource, action) pair in services/authz.py's PERMISSIONS
# matrix, and doesn't need one: this is not a role question, viewer and
# owner alike may always manage their own login state). Ownership is
# enforced by filtering the query on user_id=user.id, so a caller can never
# even discover another user's session id, let alone revoke it.

def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


@router.get("/sessions")
def list_sessions(request: Request, db=Depends(get_db),
                  user: User = Depends(get_current_user)):
    settings = request.app.state.settings
    raw = request.cookies.get(settings.session_cookie)
    current_hash = authn._th(raw) if raw else None
    now = utcnow()
    rows = (db.query(SessionRow)
            .filter(SessionRow.user_id == user.id, SessionRow.revoked_at.is_(None),
                   SessionRow.expires_at > now)
            .order_by(SessionRow.id))
    return [{"id": r.id, "ip": r.ip, "user_agent": r.user_agent,
             "created_at": _iso(r.created_at), "last_seen_at": _iso(r.last_seen_at),
             "current": r.token_hash == current_hash} for r in rows]


@router.delete("/sessions/{sid}")
def revoke_session_route(request: Request, sid: int, db=Depends(get_db),
                         user: User = Depends(get_current_user)):
    row = db.query(SessionRow).filter_by(id=sid, user_id=user.id).one_or_none()
    if row is None:
        # Also true of another user's session: 404, not 403: this isn't a
        # role/permission question (api-keys' revoke_api_key precedent), and
        # an unauthenticated-role probe learning "403 = exists, 404 =
        # doesn't" would still be an existence oracle either way.
        raise HTTPException(404, "session not found")
    if not row.revoked_at:
        row.revoked_at = utcnow()  # revocation takes effect immediately:
        db.commit()                # resolve_session() checks revoked_at on
                                    # every subsequent request for this token.
    write_audit(db, actor_type="user", actor_id=user.id, action="auth.session.revoke",
                target_type="session", target_id=sid,
                ip=request.client.host if request.client else None)
    return {"ok": True}


@users_router.post("", status_code=201)
def create_user(request: Request, body: UserIn, db=Depends(get_db)):
    first_run = db.query(User).count() == 0
    if first_run:
        role = "owner"  # doc 08 §8: forced owner-account creation on first visit
        actor_id = None
    else:
        raw = request.cookies.get(request.app.state.settings.session_cookie)
        actor = authn.resolve_session(db, raw) if raw else None
        if not actor:
            raise HTTPException(401, "Sign in again to continue.")
        if not enforce(request.app.state.authz, db, actor, "user", "manage"):
            raise HTTPException(403, "Your role does not allow this.")
        if body.role == "owner" and user_role(db, actor) != "owner":
            raise HTTPException(403, "only an owner may grant owner")
        role = body.role
        actor_id = actor.id
    if body.role not in ROLE_ORDER:
        raise HTTPException(422, "unknown role")
    if db.query(User).filter_by(email=body.email).one_or_none():
        raise HTTPException(409, "email already exists")
    user = User(email=body.email, display_name=body.display_name,
                password_hash=authn.hash_password(body.password))
    db.add(user)
    db.commit()
    db.add(TeamMember(team_id=default_team(db).id, user_id=user.id, role=role))
    db.commit()
    from proxploy.services.authz import sync_user
    sync_user(request.app.state.authz, db, user.id)
    write_audit(db, actor_type="user", actor_id=actor_id, action="user.create",
                target_type="user", target_id=user.id, params={"email": body.email,
                "role": role})
    return _user_out(db, user)


@users_router.get("")
def list_users(db=Depends(get_db), user: User = Depends(_users_read)):
    memberships: dict[int, list[dict]] = {}
    for m in db.query(TeamMember):
        memberships.setdefault(m.user_id, []).append(
            {"team_id": m.team_id, "role": m.role})
    return [{"id": u.id, "email": u.email, "display_name": u.display_name,
             "is_active": u.is_active, "teams": memberships.get(u.id, [])}
            for u in db.query(User).order_by(User.id)]


# --- OIDC (Task 11: routes over services/oidc.py's Task-10 begin()/complete()) ---


class OIDCConfigIn(BaseModel):
    issuer: str
    client_id: str
    client_secret: str


def _oidc_config_out(db) -> dict:
    from proxploy.services.settings import get_setting
    return {"issuer": get_setting(db, "oidc.issuer"),
            "client_id": get_setting(db, "oidc.client_id"),
            "configured": oidc.configured(db)}


def _oidc_redirect_uri(request: Request) -> str:
    # Deterministic function of (route name, request base URL): begin() and
    # callback() both call this and must agree, since the IdP echoes back
    # whatever redirect_uri begin() sent it.
    return str(request.url_for("oidc_callback"))


@router.get("/oidc/login", name="oidc_login")
async def oidc_login(request: Request, db=Depends(get_db)):
    # PUBLIC (test_route_auth_invariant.py): 404, never 403: an anonymous
    # caller has no session to leak role/entitlement state through, and this
    # route is how a session gets created in the first place.
    if not (oidc.configured(db) and request.app.state.entitlements.enabled("auth.oidc")):
        raise HTTPException(404, {"error": "oidc_not_configured"})
    url = await oidc.begin(request.app, db, _oidc_redirect_uri(request))
    return RedirectResponse(url, status_code=307)


@router.get("/oidc/callback", name="oidc_callback")
async def oidc_callback(request: Request, state: str, code: str, db=Depends(get_db)):
    settings = request.app.state.settings
    ip = request.client.host if request.client else None
    try:
        user = await oidc.complete(request.app, db, state=state, code=code,
                                   redirect_uri=_oidc_redirect_uri(request))
    except oidc.OIDCError as e:
        # Every OIDCError becomes the same generic redirect (no detail in the
        # URL, per doc 10 Task 11) EXCEPT the one case that is not a login
        # failure at all: an account that JIT-provisioned successfully but
        # has no role yet. That gets its own error code so the login page
        # can say "ask an administrator to approve your account" instead of
        # a bare "sign-in failed": still no stack trace, still no session.
        error = "oidc_pending" if str(e) == oidc.PENDING_APPROVAL_MESSAGE else "oidc"
        write_audit(db, actor_type="user", actor_id=None, action="auth.login",
                    result="error", params={"via": "oidc"}, ip=ip)
        return RedirectResponse(f"/login?error={error}", status_code=307)
    # A RuntimeError from a misconfigured oidc_default_role/oidc_default_team_slug
    # (services/oidc.py::_create_user) is deliberately NOT caught here: that is
    # an operator misconfiguration, not something the signing-in user caused
    # or a message safe to hand them, and swallowing it would silently strand
    # every OIDC sign-in with no record of why. It propagates to FastAPI's
    # default handler as a 500: logged, not silent, not a fake success.
    raw = authn.create_session(db, user, ip, request.headers.get("user-agent"),
                               settings.session_ttl_hours)
    write_audit(db, actor_type="user", actor_id=user.id, action="auth.login",
                params={"via": "oidc"}, ip=ip)
    resp = RedirectResponse("/", status_code=307)
    resp.set_cookie(settings.session_cookie, raw, httponly=True, samesite="lax",
                    secure=settings.cookie_secure)
    return resp


@router.get("/oidc/config")
def oidc_config_get(db=Depends(get_db), user: User = Depends(_oidc_manage)):
    return _oidc_config_out(db)


@router.put("/oidc/config")
def oidc_config_put(request: Request, body: OIDCConfigIn, db=Depends(get_db),
                    user: User = Depends(_oidc_manage)):
    oidc.set_config(db, request.app.state.secretstore, body.issuer, body.client_id,
                    body.client_secret)
    write_audit(db, actor_type="user", actor_id=user.id, action="oidc.config.set",
                params=body.model_dump())  # client_secret redacted by REDACT_SUBSTRINGS
    return _oidc_config_out(db)


@router.delete("/oidc/config")
def oidc_config_delete(db=Depends(get_db), user: User = Depends(_oidc_manage)):
    oidc.clear_config(db)
    write_audit(db, actor_type="user", actor_id=user.id, action="oidc.config.clear")
    return {"ok": True}


# --- user administration (PXP-17) -------------------------------------------
# Create and list existed; deactivate, delete and admin password reset never
# did, in either the API or the UI. ("user","manage") already covered them.

_users_manage = authorize("user", "manage")


class UserPatchIn(BaseModel):
    is_active: bool | None = None
    display_name: str | None = None


class PasswordResetIn(BaseModel):
    password: str = Field(min_length=12)


def _owner_ids(db) -> set[int]:
    return {m.user_id for m in db.query(TeamMember).filter_by(role="owner")}


def _would_strand_the_install(db, target_id: int) -> bool:
    """True when removing this user leaves nobody who can sign in and grant
    owner back. Deactivating and deleting have to ask the same question: a
    guard that counts every owner lets you deactivate one owner and then
    delete the other, which is how you reach zero active owners through two
    individually allowed steps."""
    active = {o for o in _owner_ids(db)
              if (u := db.get(User, o)) is not None and u.is_active}
    return not (active - {target_id})


def _revoke_all_sessions(db, user_id: int) -> int:
    """Every live session for a user, gone.

    Deactivating or resetting a password that leaves existing cookies working
    is not deactivating or resetting anything: `resolve_session` re-checks
    `revoked_at` on every request, so this takes effect immediately.
    """
    rows = (db.query(SessionRow)
            .filter(SessionRow.user_id == user_id, SessionRow.revoked_at.is_(None))
            .all())
    now = utcnow()
    for r in rows:
        r.revoked_at = now
    return len(rows)


@users_router.patch("/{user_id}")
def patch_user(request: Request, user_id: int, body: UserPatchIn,
               db=Depends(get_db), actor: User = Depends(_users_manage)):
    """Deactivate or reactivate an account, or fix its display name.

    Deactivation rather than deletion is the normal path: it keeps the user's
    audit rows attributable, which deletion cannot.
    """
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "user not found")
    ip = request.client.host if request.client else None
    changed: dict = {}

    if body.is_active is not None and body.is_active != target.is_active:
        if not body.is_active:
            if target.id == actor.id:
                raise HTTPException(409, {
                    "error": "self_deactivate",
                    "detail": "you cannot deactivate your own account"})
            if _would_strand_the_install(db, target.id):
                # The one lockout with no in-app recovery path: no active owner
                # means nobody can grant owner back.
                raise HTTPException(409, {
                    "error": "last_owner",
                    "detail": "this is the last active owner; promote another "
                              "owner before deactivating this one"})
        target.is_active = body.is_active
        changed["is_active"] = body.is_active

    if body.display_name is not None:
        target.display_name = body.display_name
        changed["display_name"] = body.display_name

    if not changed:
        raise HTTPException(422, "nothing to change")

    revoked = 0
    if changed.get("is_active") is False:
        revoked = _revoke_all_sessions(db, target.id)
    db.commit()
    write_audit(db, actor_type="user", actor_id=actor.id, action="user.update",
                target_type="user", target_id=target.id,
                params={"changed": changed, "sessions_revoked": revoked}, ip=ip)
    return {**_user_out(db, target), "sessions_revoked": revoked}


@users_router.post("/{user_id}/password")
def reset_password(request: Request, user_id: int, body: PasswordResetIn,
                   db=Depends(get_db), actor: User = Depends(_users_manage)):
    """Set another user's password.

    An admin-set password is a recovery mechanism, not a login: every existing
    session is revoked so a stolen cookie cannot outlive the reset. The old
    password is never required, which is precisely why this is
    ("user","manage") and audited.
    """
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "user not found")
    target.password_hash = authn.hash_password(body.password)
    # A password reset does not clear TOTP: the second factor is the user's,
    # not the admin's, and silently dropping it would weaken the account
    # while looking like a routine recovery.
    revoked = _revoke_all_sessions(db, target.id)
    db.commit()
    write_audit(db, actor_type="user", actor_id=actor.id,
                action="user.password_reset", target_type="user",
                target_id=target.id, params={"sessions_revoked": revoked},
                ip=request.client.host if request.client else None)
    return {"ok": True, "sessions_revoked": revoked}


@users_router.delete("/{user_id}")
def delete_user(request: Request, user_id: int, db=Depends(get_db),
                actor: User = Depends(_users_manage)):
    """Delete an account outright.

    Prefer PATCH is_active=false: audit rows carry actor_id, and deleting the
    user makes every action they ever took unattributable. This exists for the
    account that should never have been created.
    """
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "user not found")
    if target.id == actor.id:
        raise HTTPException(409, {"error": "self_delete",
                                  "detail": "you cannot delete your own account"})
    if _would_strand_the_install(db, target.id):
        raise HTTPException(409, {
            "error": "last_owner",
            "detail": "this is the last owner who can sign in; promote another "
                      "owner first"})

    email = target.email
    _revoke_all_sessions(db, target.id)
    for m in db.query(TeamMember).filter_by(user_id=target.id):
        db.delete(m)
    db.flush()
    db.delete(target)
    db.commit()
    from proxploy.services.authz import build_enforcer
    # Rebuild rather than sync_user: the user is gone, so there is nothing left
    # to sync policies FOR, and a stale casbin row would keep granting.
    request.app.state.authz = build_enforcer(db)
    write_audit(db, actor_type="user", actor_id=actor.id, action="user.delete",
                target_type="user", target_id=user_id, params={"email": email},
                ip=request.client.host if request.client else None)
    return {"deleted": True}
