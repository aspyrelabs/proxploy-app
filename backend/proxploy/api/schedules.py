"""Schedules CRUD.

The `schedules` table is authoritative and `jobs/scheduler.py` reads it every
tick, so a write is live within one tick and there is nothing to register or
de-register. Every write runs `_validated()` (the same checks as `validate()`,
split out so a 422 names which of cron/timezone/job_kind failed) rather than
discovering a bad cron when the schedule silently disables itself later.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from proxploy.api.deps import authorize, get_db, require_entitlement
from proxploy.api.jobs import job_out
from proxploy.jobs import HANDLERS
from proxploy.jobs.scheduler import BadSchedule, _target, next_fire
from proxploy.models import Job, Schedule, User, to_iso, utcnow
from proxploy.services.audit import write_audit

router = APIRouter(prefix="/schedules", tags=["schedules"])

# One singleton per permission so FastAPI's dependency cache collapses the
# route-level and parameter-level uses, and authorize always runs before
# require_entitlement.
_read = authorize("schedule", "read")
_run = authorize("schedule", "run")
_manage = authorize("schedule", "manage")

# Enforced in the body rather than a route dependency: the entitlement depends
# on the payload's job_kind, which a dependency cannot see.
AUTO_UPDATE_KIND = "app.update"


class ScheduleIn(BaseModel):
    name: str
    job_kind: str
    cron: str
    timezone: str = "UTC"
    params: dict | None = None
    enabled: bool = True


class SchedulePatch(BaseModel):
    name: str | None = None
    job_kind: str | None = None
    cron: str | None = None
    timezone: str | None = None
    params: dict | None = None
    enabled: bool | None = None


def _out(s: Schedule) -> dict:
    return {"id": s.id, "name": s.name, "job_kind": s.job_kind, "cron": s.cron,
            "timezone": s.timezone, "params": s.params or {},
            "enabled": s.enabled, "created_by": s.created_by,
            "last_run_at": to_iso(s.last_run_at), "next_run_at": to_iso(s.next_run_at)}


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _get(db, schedule_id: int) -> Schedule:
    row = db.get(Schedule, schedule_id)
    if row is None:
        raise HTTPException(404, "schedule not found")
    return row


def _check_auto_update(request: Request, job_kind: str) -> None:
    if (job_kind == AUTO_UPDATE_KIND
            and not request.app.state.entitlements.enabled("store.auto_update")):
        raise HTTPException(403, {"error": "entitlement_required",
                                  "feature": "store.auto_update"})


def _validated(cron: str, tz: str, job_kind: str) -> None:
    """Same checks as `validate()`, but discriminating which axis failed: a flat
    `str(BadSchedule)` doesn't always name it (a bad cron's message never says
    "cron"), and the caller needs to know whether to fix the trigger or the kind."""
    if job_kind not in HANDLERS:
        raise HTTPException(422, f"no job handler registered for kind {job_kind!r}")
    try:
        next_fire(cron, tz, utcnow())
    except BadSchedule as e:
        raise HTTPException(422, f"invalid cron expression or timezone: {e}") from e


@router.get("", dependencies=[Depends(_read)])
def list_schedules(db=Depends(get_db), user: User = Depends(_read)):
    # Ascending: a small admin-curated config list, where stable ordering
    # matters more than surfacing new rows (unlike /jobs' append-only log).
    return [_out(s) for s in db.query(Schedule).order_by(Schedule.id).all()]


@router.post("", status_code=201,
             dependencies=[Depends(_manage),
                           Depends(require_entitlement("sched.windows"))])
def create_schedule(request: Request, body: ScheduleIn, db=Depends(get_db),
                    user: User = Depends(_manage)):
    _check_auto_update(request, body.job_kind)
    _validated(body.cron, body.timezone, body.job_kind)
    row = Schedule(name=body.name, job_kind=body.job_kind, cron=body.cron,
                   timezone=body.timezone, params=body.params or {},
                   enabled=body.enabled, created_by=user.id)
    # Primed at write time so the row is live on the very next tick rather than
    # waiting for `prime()` to notice it.
    if row.enabled:
        row.next_run_at = next_fire(row.cron, row.timezone, utcnow())
    db.add(row)
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id, action="schedule.create",
                target_type="schedule", target_id=row.id,
                params={"name": row.name, "job_kind": row.job_kind,
                        "cron": row.cron, "timezone": row.timezone},
                ip=_ip(request))
    return _out(row)


@router.patch("/{schedule_id}",
              dependencies=[Depends(_manage),
                            Depends(require_entitlement("sched.windows"))])
def patch_schedule(request: Request, schedule_id: int, body: SchedulePatch,
                   db=Depends(get_db), user: User = Depends(_manage)):
    row = _get(db, schedule_id)
    cron = body.cron if body.cron is not None else row.cron
    tz = body.timezone if body.timezone is not None else row.timezone
    kind = body.job_kind if body.job_kind is not None else row.job_kind
    enabled = body.enabled if body.enabled is not None else row.enabled

    _check_auto_update(request, kind)
    # Validate BEFORE mutating: a rejected PATCH must leave the stored row
    # exactly as it was, not half-applied.
    _validated(cron, tz, kind)

    trigger_changed = (cron, tz) != (row.cron, row.timezone)
    was_enabled = row.enabled

    row.name = body.name if body.name is not None else row.name
    row.job_kind, row.cron, row.timezone, row.enabled = kind, cron, tz, enabled
    if body.params is not None:
        row.params = body.params

    if not enabled:
        # A stale past next_run_at would fire the instant it is re-enabled.
        row.next_run_at = None
    elif trigger_changed or not was_enabled or row.next_run_at is None:
        row.next_run_at = next_fire(cron, tz, utcnow())
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id, action="schedule.update",
                target_type="schedule", target_id=row.id,
                params={"name": row.name, "job_kind": row.job_kind,
                        "cron": row.cron, "timezone": row.timezone,
                        "enabled": row.enabled},
                ip=_ip(request))
    return _out(row)


@router.delete("/{schedule_id}", status_code=204,
               dependencies=[Depends(_manage)])
def delete_schedule(request: Request, schedule_id: int, db=Depends(get_db),
                    user: User = Depends(_manage)):
    row = _get(db, schedule_id)
    name, kind = row.name, row.job_kind
    # jobs.schedule_id is a plain nullable FK with no ON DELETE: historical
    # job rows must survive their schedule, so unlink rather than cascade.
    (db.query(Job).filter(Job.schedule_id == schedule_id)
     .update({"schedule_id": None}, synchronize_session=False))
    db.delete(row)
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id, action="schedule.delete",
                target_type="schedule", target_id=schedule_id,
                params={"name": name, "job_kind": kind}, ip=_ip(request))
    return Response(status_code=204)


@router.post("/{schedule_id}/run", status_code=202,
             dependencies=[Depends(_run)])
def run_schedule_now(request: Request, schedule_id: int, db=Depends(get_db),
                     user: User = Depends(_run)):
    """An extra run, not a reschedule: `next_run_at` deliberately does not move.

    Unlike a tick-fired run this one carries `requested_by`; a human asked for
    it, and the audit trail should say so.
    """
    row = _get(db, schedule_id)
    _check_auto_update(request, row.job_kind)
    params = dict(row.params or {})
    target_type, target_id = _target(row.job_kind, params)
    try:
        job = request.app.state.jobs.enqueue(
            db, kind=row.job_kind, target_type=target_type, target_id=target_id,
            params=params, requested_by=user.id, schedule_id=row.id)
    except KeyError as e:
        raise HTTPException(422, f"no job handler for kind {row.job_kind!r}") from e
    row.last_run_at = utcnow()
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id, action="schedule.run",
                target_type="schedule", target_id=row.id, job_id=job.id,
                params={"name": row.name, "job_kind": row.job_kind},
                ip=_ip(request))
    return {"job": job_out(job)}
