from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from proxploy import __version__
from proxploy.api.deps import authorize, get_db
from proxploy.models import Host, User
from proxploy.services import oidc, updater
from proxploy.services.audit import write_audit
from proxploy.services.settings import get_setting

router = APIRouter(prefix="/meta", tags=["meta"])

_read = authorize("meta", "read")
_manage = authorize("settings", "manage")

COMPOSE_HINT = "docker compose pull && docker compose up -d"


class UpdateIn(BaseModel):
    version: str


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/version")
def version(request: Request, user=Depends(_read)):
    return {"version": __version__,
            "db_backend": request.app.state.engine.dialect.name}


@router.get("/onboarding")
def onboarding(request: Request, db=Depends(get_db)):
    return {"admin_exists": db.query(User).count() > 0,
            "host_added": db.query(Host).count() > 0,
            "complete": bool(get_setting(db, "onboarding.complete", False)),
            # Task 11: login page's pre-session SSO-button gate.
            "oidc": oidc.configured(db) and request.app.state.entitlements.enabled("auth.oidc")}


@router.get("/update")
def update_status(request: Request, user=Depends(_read)):
    settings = request.app.state.settings
    shape = updater.detect_shape(settings)
    body = updater.check(settings)
    can = shape in updater.CAN_SELF_APPLY
    body["install_shape"] = shape
    body["can_self_apply"] = can
    body["compose_hint"] = None if can else COMPOSE_HINT
    return body


@router.post("/update", status_code=202)
def apply_update(request: Request, body: UpdateIn, user=Depends(_manage), db=Depends(get_db)):
    settings = request.app.state.settings
    shape = updater.detect_shape(settings)
    if shape not in updater.CAN_SELF_APPLY:
        # Not a failure — a deliberate capability boundary (spec D3). The
        # container never rewrites its own image.
        raise HTTPException(409, {"error": "docker_shape", "compose_hint": COMPOSE_HINT})
    status = updater.check(settings)
    if status["error"]:
        raise HTTPException(502, {"error": "channel_unavailable",
                                  "detail": status["error"]})
    if status["latest"] != body.version:
        # The operator clicked on a version they were shown; the channel has
        # since moved. Installing something they never saw is worse than an
        # error they can re-check.
        raise HTTPException(409, {"error": "no_such_version",
                                  "latest": status["latest"]})
    if not Path(settings.update_script).exists():
        raise HTTPException(503, {"error": "updater_missing",
                                  "detail": f"{settings.update_script} is not installed — "
                                            f"re-run the installer to repair it"})
    write_audit(db, actor_type="user", actor_id=user.id,
                action="system.update.start", target_type="system",
                ip=request.client.host if request.client else None)
    updater.launch(settings, body.version)
    return {"ok": True, "version": body.version}
