from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from proxploy import __version__
from proxploy.api.deps import authorize, get_db, require_entitlement
from proxploy.models import Host, HostCredential, User
from proxploy.services import oidc, updater
from proxploy.services.audit import write_audit
from proxploy.services.authn import resolve_session
from proxploy.services.settings import get_setting

router = APIRouter(prefix="/meta", tags=["meta"])

_read = authorize("meta", "read")
_manage = authorize("settings", "manage")
# Always listed AFTER the auth dependency: otherwise an anonymous caller gets
# 403 instead of 401 and learns which entitlement flags are armed.
_self_update = require_entitlement("platform.self_update")

COMPOSE_HINT = "docker compose pull && docker compose up -d"


class UpdateIn(BaseModel):
    version: str


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/version")
def version(request: Request, user=Depends(_read)):
    # "reporting" is "off" (shipped default), "on", or "error: <type>". The
    # only way an operator can tell a blank/mangled DSN from an unset one.
    # Behind `_read` (not /meta/health): this install's config isn't public.
    return {"version": __version__,
            "db_backend": request.app.state.engine.dialect.name,
            "reporting": request.app.state.reporting}


@router.get("/onboarding")
def onboarding(request: Request, db=Depends(get_db)):
    """Pre-session onboarding state, PUBLIC by necessity.

    `admin_exists`/`complete`/`oidc` are safe to expose anonymously.
    `host_added`/`ssh_pending` are host reconnaissance, so they're returned
    only once a session exists (the wizard signs the admin in at step 1) and
    are absent -- not False -- otherwise, so a signed-out caller can't be sent
    to the wrong wizard step.
    """
    body = {"admin_exists": db.query(User).count() > 0,
            "complete": bool(get_setting(db, "onboarding.complete", False)),
            "oidc": oidc.configured(db) and request.app.state.entitlements.enabled("auth.oidc")}
    raw = request.cookies.get(request.app.state.settings.session_cookie)
    if raw and resolve_session(db, raw):
        body["host_added"] = db.query(Host).count() > 0
        # Enrolled-but-unverified key = wizard's authorize step still owed.
        body["ssh_pending"] = (db.query(HostCredential).filter_by(kind="ssh_key")
                               .filter(HostCredential.ssh_verified_at.is_(None))
                               .count() > 0)
    return body


@router.get("/update", dependencies=[Depends(_read), Depends(_self_update)])
def update_status(request: Request):
    settings = request.app.state.settings
    shape = updater.detect_shape(settings)
    body = updater.check(settings)
    can = shape in updater.CAN_SELF_APPLY
    body["install_shape"] = shape
    body["can_self_apply"] = can
    body["compose_hint"] = None if can else COMPOSE_HINT
    return body


@router.post("/update", status_code=202,
             dependencies=[Depends(_manage), Depends(_self_update)])
def apply_update(request: Request, body: UpdateIn, user=Depends(_manage), db=Depends(get_db)):
    settings = request.app.state.settings
    shape = updater.detect_shape(settings)
    if shape not in updater.CAN_SELF_APPLY:
        # Deliberate capability boundary: the container never rewrites its own image.
        raise HTTPException(409, {"error": "docker_shape", "compose_hint": COMPOSE_HINT})
    status = updater.check(settings)
    if status["error"]:
        raise HTTPException(502, {"error": "channel_unavailable",
                                  "detail": status["error"]})
    if status["latest"] != body.version:
        # The operator was shown this version; the channel has moved on.
        # Installing something they never saw is worse than a re-checkable error.
        raise HTTPException(409, {"error": "no_such_version",
                                  "latest": status["latest"]})
    if not Path(settings.update_script).exists():
        raise HTTPException(503, {"error": "updater_missing",
                                  "detail": f"{settings.update_script} is not installed, "
                                            f"re-run the installer to repair it"})
    write_audit(db, actor_type="user", actor_id=user.id,
                action="system.update.start", target_type="system",
                ip=request.client.host if request.client else None)
    updater.launch(settings, body.version)
    return {"ok": True, "version": body.version}
