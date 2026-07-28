from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from proxploy.api.deps import (ROLE_ORDER, default_team, get_current_user, get_db,
                               user_role)
from proxploy.models import TeamMember, User
from proxploy.services import authn
from proxploy.services.audit import write_audit

limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/auth", tags=["auth"])
users_router = APIRouter(prefix="/users", tags=["users"])


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
        actor_role = user_role(db, actor)
        if ROLE_ORDER[actor_role] < ROLE_ORDER["admin"]:
            raise HTTPException(403, "insufficient role")
        if body.role == "owner" and actor_role != "owner":
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
    write_audit(db, actor_type="user", actor_id=actor_id, action="user.create",
                target_type="user", target_id=user.id, params={"email": body.email,
                "role": role})
    return _user_out(db, user)
