from fastapi import APIRouter, Depends, Request

from proxploy import __version__
from proxploy.api.deps import get_current_user, get_db
from proxploy.models import Host, User
from proxploy.services.settings import get_setting

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/version")
def version(request: Request, user=Depends(get_current_user)):
    return {"version": __version__,
            "db_backend": request.app.state.engine.dialect.name}


@router.get("/onboarding")
def onboarding(db=Depends(get_db)):
    return {"admin_exists": db.query(User).count() > 0,
            "host_added": db.query(Host).count() > 0,
            "complete": bool(get_setting(db, "onboarding.complete", False))}
