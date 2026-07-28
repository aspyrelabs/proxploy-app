from fastapi import Depends, HTTPException, Request

from proxploy.models import Team, TeamMember, User
from proxploy.services.authn import resolve_session

ROLE_ORDER = {"viewer": 0, "operator": 1, "admin": 2, "owner": 3}


def get_db(request: Request):
    db = request.app.state.sessionmaker()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request, db=Depends(get_db)) -> User:
    raw = request.cookies.get(request.app.state.settings.session_cookie)
    user = resolve_session(db, raw) if raw else None
    if not user:
        raise HTTPException(401, "authentication required")
    return user


def user_role(db, user: User) -> str:
    roles = [m.role for m in db.query(TeamMember).filter_by(user_id=user.id)]
    return max(roles, key=lambda r: ROLE_ORDER.get(r, -1), default="viewer")


def require_role(min_role: str):
    """Phase-1 RBAC stub — the seam pycasbin replaces in Phase 8 (doc 08 §6)."""
    def dep(request: Request, db=Depends(get_db),
            user: User = Depends(get_current_user)) -> User:
        if ROLE_ORDER[user_role(db, user)] < ROLE_ORDER[min_role]:
            raise HTTPException(403, "insufficient role")
        return user
    return dep


def default_team(db) -> Team:
    team = db.query(Team).filter_by(slug="default").one_or_none()
    if not team:
        team = Team(name="Default", slug="default")
        db.add(team)
        db.commit()
    return team
