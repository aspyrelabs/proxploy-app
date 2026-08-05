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


def get_entitlements(request: Request):
    return request.app.state.entitlements


def require_entitlement(key: str):
    """Doc 07 §2 backend enforcement — stack after auth/role deps on every gated route."""
    def dep(request: Request):
        if not request.app.state.entitlements.enabled(key):
            raise HTTPException(403, {"error": "entitlement_required", "feature": key})
    return dep


def _team_of_host(db, host_id) -> int | None:
    from proxploy.models import Host
    h = db.get(Host, int(host_id))
    if h is None:
        return None          # let the handler 404; never an existence oracle
    return h.team_id if h.team_id is not None else default_team(db).id


def scope_host(param: str = "host_id"):
    def resolve(db, path_params) -> int | None:
        raw = path_params.get(param)
        return _team_of_host(db, raw) if raw is not None else None
    return resolve


def scope_app(param: str = "app_id"):
    def resolve(db, path_params) -> int | None:
        from proxploy.models import App
        raw = path_params.get(param)
        if raw is None:
            return None
        a = db.get(App, int(raw))
        return _team_of_host(db, a.host_id) if a else None
    return resolve


def scope_vm(param: str = "vm_id"):
    def resolve(db, path_params) -> int | None:
        from proxploy.models import Vm
        raw = path_params.get(param)
        if raw is None:
            return None
        v = db.get(Vm, int(raw))
        return _team_of_host(db, v.host_id) if v else None
    return resolve


def scope_backup(param: str = "backup_id"):
    def resolve(db, path_params) -> int | None:
        from proxploy.models import Backup
        raw = path_params.get(param)
        if raw is None:
            return None
        b = db.get(Backup, int(raw))
        return _team_of_host(db, b.host_id) if b else None
    return resolve


def authorize(resource: str, action: str, *, scope_of=None):
    """Doc 08 §6 enforcement point. Replaces require_role() route-by-route in
    Phase 8. Fail-closed twice over: an unregistered (resource, action) pair
    refuses to even build a dependency (so an ungoverned route cannot be
    registered), and the enforcer denies anything it does not recognise.
    Order on routes: dependencies=[Depends(authorize(...)),
    Depends(require_entitlement(...))] — authorize resolves get_current_user
    first, so an anonymous caller still gets 401 before any 403."""
    from proxploy.services.authz import PERMISSIONS
    from proxploy.services.authz import enforce as _enforce
    if (resource, action) not in PERMISSIONS:
        raise RuntimeError(f"unregistered permission: ({resource!r}, {action!r})")

    def dep(request: Request, db=Depends(get_db),
            user: User = Depends(get_current_user)) -> User:
        team_id = scope_of(db, request.path_params) if scope_of else None
        # Task 12 folds API-key scope checks in here (require_key_scope).
        if not _enforce(request.app.state.authz, db, user, resource, action,
                        team_id=team_id):
            from proxploy.services.audit import write_audit
            write_audit(db, actor_type="user", actor_id=user.id,
                        action=f"{resource}.{action}", result="denied",
                        ip=request.client.host if request.client else None)
            raise HTTPException(403, "forbidden")
        return user

    dep.__proxploy_authz__ = (resource, action)   # Task 7's meta-test marker
    return dep
