from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from proxploy.api.deps import (ROLE_ORDER, authorize, default_team, get_current_user,
                               get_db, user_role)
from proxploy.models import TeamMember, User
from proxploy.services import authn, oidc
from proxploy.services.audit import write_audit
from proxploy.services.authz import enforce

limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/auth", tags=["auth"])
users_router = APIRouter(prefix="/users", tags=["users"])

# Module-level singleton (hosts.py idiom, api/deps.py::authorize docstring):
# GET/PUT/DELETE all gate on the same ("settings", "manage") permission — the
# OIDC IdP config is an "own flow" settings.py's `.enc`-key refusal points at.
_oidc_manage = authorize("settings", "manage")

# GET /users (Task 6, doc 05): the member-picker source, ("user", "read")
# global (any-team admin, no scope_of) — same status as ("user", "manage")
# in create_user below.
_users_read = authorize("user", "read")


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12)
    display_name: str | None = None
    role: str = "viewer"


def _user_out(db, user: User) -> dict:
    return {"id": user.id, "email": user.email, "display_name": user.display_name,
            "role": user_role(db, user)}


@router.post("/login")
@limiter.limit("10/minute")
def login(request: Request, body: LoginIn, response: Response, db=Depends(get_db)):
    settings = request.app.state.settings
    user = db.query(User).filter_by(email=body.email).one_or_none()
    ip = request.client.host if request.client else None
    if not user or not user.password_hash or not authn.verify_password(
            user.password_hash, body.password) or not user.is_active:
        write_audit(db, actor_type="user", actor_id=user.id if user else None,
                    action="auth.login", result="error", ip=ip)
        raise HTTPException(401, "invalid credentials")
    raw = authn.create_session(db, user, ip, request.headers.get("user-agent"),
                               settings.session_ttl_hours)
    write_audit(db, actor_type="user", actor_id=user.id, action="auth.login", ip=ip)
    response.set_cookie(settings.session_cookie, raw, httponly=True, samesite="lax",
                        secure=settings.cookie_secure)
    return {"ok": True, "user": _user_out(db, user)}


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
            raise HTTPException(401, "authentication required")
        if not enforce(request.app.state.authz, db, actor, "user", "manage"):
            raise HTTPException(403, "forbidden")
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
    # Deterministic function of (route name, request base URL) — begin() and
    # callback() both call this and must agree, since the IdP echoes back
    # whatever redirect_uri begin() sent it.
    return str(request.url_for("oidc_callback"))


@router.get("/oidc/login", name="oidc_login")
async def oidc_login(request: Request, db=Depends(get_db)):
    # PUBLIC (test_route_auth_invariant.py): 404, never 403 — an anonymous
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
        # a bare "sign-in failed" — still no stack trace, still no session.
        error = "oidc_pending" if str(e) == oidc.PENDING_APPROVAL_MESSAGE else "oidc"
        write_audit(db, actor_type="user", actor_id=None, action="auth.login",
                    result="error", params={"via": "oidc"}, ip=ip)
        return RedirectResponse(f"/login?error={error}", status_code=307)
    # A RuntimeError from a misconfigured oidc_default_role/oidc_default_team_slug
    # (services/oidc.py::_create_user) is deliberately NOT caught here: that is
    # an operator misconfiguration, not something the signing-in user caused
    # or a message safe to hand them, and swallowing it would silently strand
    # every OIDC sign-in with no record of why. It propagates to FastAPI's
    # default handler as a 500 — logged, not silent, not a fake success.
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
