import hashlib

from fastapi import Depends, HTTPException, Request

from proxploy.models import ApiKey, Team, TeamMember, User, utcnow
from proxploy.services.authn import resolve_session

ROLE_ORDER = {"viewer": 0, "operator": 1, "admin": 2, "owner": 3}


def get_db(request: Request):
    db = request.app.state.sessionmaker()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request, db=Depends(get_db)) -> User:
    """Cookie session by default; `Authorization: Bearer ppk_...` resolves
    through api_keys instead (Task 12). Bearer is never a second, weaker
    login path: same fail-closed 401 shape, same is_active gate, and the
    resolved row is stashed on request.state.api_key so authorize() can
    narrow the session's own role by the key's scopes below."""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        raw = auth[7:]
        if not raw.startswith("ppk_"):
            raise HTTPException(401, "This API key is not valid.")
        if not request.app.state.entitlements.enabled("api.tokens"):
            # feature off = no bearer auth, and a 403 here would leak flag
            # state to an anonymous caller
            raise HTTPException(401, "This API key is not valid.")
        row = (db.query(ApiKey)
               .filter_by(key_hash=hashlib.sha256(raw.encode()).hexdigest())
               .one_or_none())
        now = utcnow()
        if (row is None or row.revoked_at
                or (row.expires_at and row.expires_at < now)):
            raise HTTPException(401, "This API key is not valid.")
        user = db.get(User, row.user_id)
        if not user or not user.is_active:
            raise HTTPException(401, "This API key is not valid.")
        if row.last_used_at is None or (now - row.last_used_at).total_seconds() > 60:
            row.last_used_at = now      # rate-limited write, one per key-minute
            db.commit()
        request.state.api_key = row
        return user
    raw = request.cookies.get(request.app.state.settings.session_cookie)
    user = resolve_session(db, raw) if raw else None
    if not user:
        raise HTTPException(401, "Sign in again to continue.")
    return user


def user_role(db, user: User) -> str:
    roles = [m.role for m in db.query(TeamMember).filter_by(user_id=user.id)]
    return max(roles, key=lambda r: ROLE_ORDER.get(r, -1), default="viewer")


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
    """Doc 07 §2 backend enforcement, stack after auth/role deps on every gated route."""
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
    """Doc 08 §6 enforcement point, the only authorization path in the
    product (the Phase-1 require_role RBAC stub is retired). Fail-closed
    twice over: an unregistered (resource, action) pair refuses to even
    build a dependency (so an ungoverned route cannot be registered), and
    the enforcer denies anything it does not recognise.
    Order on routes: dependencies=[Depends(authorize(...)),
    Depends(require_entitlement(...))], authorize resolves get_current_user
    first, so an anonymous caller still gets 401 before any 403."""
    from proxploy.services.authz import PERMISSIONS
    from proxploy.services.authz import enforce as _enforce
    if (resource, action) not in PERMISSIONS:
        raise RuntimeError(f"unregistered permission: ({resource!r}, {action!r})")

    def dep(request: Request, db=Depends(get_db),
            user: User = Depends(get_current_user)) -> User:
        from proxploy.services.audit import write_audit

        # A key can only narrow its user, never widen: this runs BEFORE the
        # casbin check so a key's scopes are a ceiling on the session's own
        # role, never an alternate grant. Empty scopes = full user rights
        # (doc 04): a key with no scopes list still cannot exceed enforce()
        # below, which is keyed on the *user*, not the key.
        key = getattr(request.state, "api_key", None)
        if key is not None and key.scopes:
            allowed = ("read" in key.scopes and action == "read") or \
                      (f"{resource}:write" in key.scopes)
            if not allowed:
                write_audit(db, actor_type="api_key", actor_id=key.id,
                            action=f"{resource}.{action}", result="denied",
                            ip=request.client.host if request.client else None)
                raise HTTPException(403, "This API key does not allow this.")

        team_id = scope_of(db, request.path_params) if scope_of else None
        if not _enforce(request.app.state.authz, db, user, resource, action,
                        team_id=team_id):
            write_audit(db, actor_type="user", actor_id=user.id,
                        action=f"{resource}.{action}", result="denied",
                        ip=request.client.host if request.client else None)
            raise HTTPException(403, "Your role does not allow this.")
        return user

    dep.__proxploy_authz__ = (resource, action)   # Task 7's meta-test marker
    return dep
