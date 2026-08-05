from fastapi import APIRouter, Depends, Request

from proxploy import __version__
from proxploy.api.deps import authorize, get_db
from proxploy.models import Host, User
from proxploy.services import oidc
from proxploy.services.settings import get_setting

router = APIRouter(prefix="/meta", tags=["meta"])

_read = authorize("meta", "read")


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
