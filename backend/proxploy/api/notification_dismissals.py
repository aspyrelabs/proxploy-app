"""Per-user "what have I already cleared" state for the bell tray.

Self-service: gated on get_current_user alone, no authorize() call, no
PERMISSIONS matrix entry -- reading and writing your OWN tray state isn't a
role question. Ownership is enforced by scoping every read/write on user.id.

A separate router, not folded into api/notifications.py's /notifications
prefix, because that router's one dependency (`_manage`, `authorize(
"channel", "manage")`) is deliberately the single gate for its whole file
("every notifications route is admin, no viewer read tier"); mixing a
self-service, no-role route into that file would make that comment false.
FastAPI is happy to have two routers share a path prefix.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func

from proxploy.api.deps import get_current_user, get_db
from proxploy.models import Job, User
from proxploy.services import notification_dismissals as svc

router = APIRouter(prefix="/notifications/dismissed", tags=["notifications"])


@router.get("")
def get_dismissed(db=Depends(get_db), user: User = Depends(get_current_user)):
    return svc.get_state(db, user.id)


# Registered before "/{job_id}": FastAPI/Starlette tries routes in
# registration order and a static segment must be checked before a dynamic
# one, or a POST to /clear-all would be routed to dismiss_one and 422 on
# "clear-all" not being an int, never reaching this handler.
@router.post("/clear-all")
def clear_all(db=Depends(get_db), user: User = Depends(get_current_user)):
    # The watermark is "the highest job id that exists right now", not "every
    # id currently shown in one client's tray": a job the browser hasn't
    # polled yet is still covered, and (the trap this exists to avoid) a job
    # created a moment from now gets a HIGHER id and is never covered by it.
    through = db.query(func.max(Job.id)).scalar() or 0
    return svc.clear_all(db, user.id, through)


@router.post("/{job_id}")
def dismiss_one(job_id: int, db=Depends(get_db), user: User = Depends(get_current_user)):
    return svc.dismiss_job(db, user.id, job_id)
