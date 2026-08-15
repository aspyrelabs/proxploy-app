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
# doc 01 lists self-update as gated on `platform.self_update`; only RBAC was
# enforced, so the documented gate did not exist. Always listed AFTER the auth
# dependency, or an anonymous caller gets 403 instead of 401 and learns which
# flags are armed (tests/test_route_auth_invariant.py).
_self_update = require_entitlement("platform.self_update")

COMPOSE_HINT = "docker compose pull && docker compose up -d"


class UpdateIn(BaseModel):
    version: str


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/version")
def version(request: Request, user=Depends(_read)):
    # "reporting" is "off" (the shipped default), "on", or "error: <type>".
    # An operator who put PROXPLOY_SENTRY_DSN in proxploy.env has no other way
    # to tell whether it took: a DSN that arrived blank or mangled behaves
    # exactly like one that was never set. Behind `_read` rather than on the
    # unauthenticated /meta/health, since nothing about this install's
    # configuration is a stranger's business.
    return {"version": __version__,
            "db_backend": request.app.state.engine.dialect.name,
            "reporting": request.app.state.reporting}


@router.get("/onboarding")
def onboarding(request: Request, db=Depends(get_db)):
    """Where setup has got to.

    PUBLIC by necessity, so it answers a stranger with the three booleans the
    pre-session screens genuinely cannot work without and nothing else:
    `admin_exists` (step 1 of the wizard, and whether this is a fresh
    install), `complete` (the redirect both shell.tsx and the wizard route
    make before any session exists) and `oidc` (whether the login page draws
    an SSO button).

    `host_added` and `ssh_pending` are a different kind of fact: they say
    this install manages Proxmox hosts and that a root SSH key is enrolled
    but not yet working, which is reconnaissance for anyone who can reach the
    port. The wizard only reads them from step 2 onwards, and step 1 signs
    the new admin in before it gets there (components/AdminAccountStep.tsx
    posts /users then /auth/login), so a session always exists by the time
    they matter. Absent rather than faked for everyone else: a hardcoded
    False would send a signed-out caller to the wrong wizard step.
    """
    body = {"admin_exists": db.query(User).count() > 0,
            "complete": bool(get_setting(db, "onboarding.complete", False)),
            # Task 11: login page's pre-session SSO-button gate.
            "oidc": oidc.configured(db) and request.app.state.entitlements.enabled("auth.oidc")}
    raw = request.cookies.get(request.app.state.settings.session_cookie)
    if raw and resolve_session(db, raw):
        body["host_added"] = db.query(Host).count() > 0
        # An enrolled-but-unverified key is the wizard's authorize step
        # still being owed an answer (Task 2). Verified or absent, there
        # is nothing left to ask.
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
        # Not a failure: a deliberate capability boundary (spec D3). The
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
                                  "detail": f"{settings.update_script} is not installed, "
                                            f"re-run the installer to repair it"})
    write_audit(db, actor_type="user", actor_id=user.id,
                action="system.update.start", target_type="system",
                ip=request.client.host if request.client else None)
    updater.launch(settings, body.version)
    return {"ok": True, "version": body.version}
