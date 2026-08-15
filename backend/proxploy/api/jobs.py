"""Jobs API (doc 05 §Jobs) + the per-job transcript stream (§Streaming 1).

SSE, not websockets: a job log is strictly one-way, and EventSource's native
reconnect + `Last-Event-ID` maps onto `job_events.seq` for free.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from proxploy.api.deps import authorize, get_db, require_entitlement
from proxploy.jobs import TERMINAL
from proxploy.models import Job, JobEvent, User, utcnow
from proxploy.services.audit import write_audit
from proxploy.services.authn import resolve_session

router = APIRouter(prefix="/jobs", tags=["jobs"])

_read = authorize("job", "read")
_cancel = authorize("job", "cancel")

PING_S = 15


def job_out(j: Job) -> dict:
    return {
        "id": j.id, "kind": j.kind, "status": j.status,
        "target_type": j.target_type, "target_id": j.target_id,
        "params": j.params, "result": j.result, "error": j.error,
        "progress_pct": j.progress_pct, "requested_by": j.requested_by,
        "schedule_id": j.schedule_id,
        "started_at": j.started_at.isoformat() + "Z" if j.started_at else None,
        "finished_at": j.finished_at.isoformat() + "Z" if j.finished_at else None,
        "created_at": j.created_at.isoformat() + "Z",
    }


def backlog(db, job_id: int, after: int = 0, limit: int = 5000) -> list[dict]:
    rows = (db.query(JobEvent)
            .filter(JobEvent.job_id == job_id, JobEvent.seq > after)
            .order_by(JobEvent.seq).limit(limit).all())
    return [{"seq": e.seq, "ts": e.ts.isoformat() + "Z",
             "stream": e.stream, "message": e.message} for e in rows]


def enqueue_and_audit(request: Request, db, user: User, *, kind: str,
                      target_type: str | None, target_id: int | None,
                      params: dict, action: str | None = None) -> dict:
    """Enqueue a job, write the audit row that points at it, return the 202 body.

    api/apps.py::enqueue_lifecycle is this same shape plus the self-guard and
    the fixed `{target_type}.{action}` kind; this is the plain version every
    Phase 6 mutation route uses. `action` overrides the audit action when the
    job kind is not the right name for the audit trail (a `backup.run` job
    fired from the restore route, say); it defaults to `kind`.

    Both `params` copies are redacted at their own sink: JobBackend.enqueue
    redacts before writing `jobs.params`, write_audit before `audit_events.params`.
    """
    job = request.app.state.jobs.enqueue(
        db, kind=kind, target_type=target_type, target_id=target_id,
        params=params, requested_by=user.id)
    write_audit(db, actor_type="user", actor_id=user.id, action=action or kind,
                target_type=target_type, target_id=target_id, params=params,
                job_id=job.id, ip=request.client.host if request.client else None)
    return {"job": job_out(job)}


@router.get("", dependencies=[Depends(_read),
                              Depends(require_entitlement("jobs.history"))])
def list_jobs(response: Response, status: str | None = None, kind: str | None = None,
              target: str | None = None, page: int = 1, per_page: int = 50,
              db=Depends(get_db)):
    q = db.query(Job)
    if status:
        q = q.filter(Job.status == status)
    if kind:
        q = q.filter(Job.kind == kind)
    if target:
        try:
            ttype, tid = target.split(":", 1)
            q = q.filter(Job.target_type == ttype, Job.target_id == int(tid))
        except ValueError:
            raise HTTPException(422, "target must look like app:3 / vm:2 / host:1")
    response.headers["X-Total-Count"] = str(q.count())
    rows = (q.order_by(Job.created_at.desc(), Job.id.desc())
            .offset((page - 1) * per_page).limit(per_page).all())
    return [job_out(j) for j in rows]


@router.get("/{job_id}", dependencies=[Depends(_read),
                                       Depends(require_entitlement("jobs.history"))])
def job_detail(job_id: int, db=Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job_out(job)


@router.get("/{job_id}/events",
            dependencies=[Depends(_read),
                          Depends(require_entitlement("jobs.history"))])
def job_events(job_id: int, after: int = 0, limit: int = 5000, db=Depends(get_db)):
    if db.get(Job, job_id) is None:
        raise HTTPException(404, "job not found")
    return backlog(db, job_id, after=after, limit=limit)


@router.post("/{job_id}/cancel")
def cancel_job(request: Request, job_id: int, db=Depends(get_db),
               user: User = Depends(_cancel)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    if job.status in TERMINAL:
        raise HTTPException(409, f"job is already {job.status}")
    # Ask the runner first; if no task owns it (e.g. enqueued by a process that
    # has since restarted), mark it canceled here so the row never dangles.
    # The status check above and this update are two round trips, so a
    # conditional UPDATE (not a blind write) guards the TOCTOU window where
    # the runner's _finish lands in between: if the row is no longer
    # cancelable by the time we get here, refuse instead of clobbering it.
    if not request.app.state.jobs.cancel(job_id):
        n = (db.query(Job).filter(Job.id == job_id, Job.status.notin_(TERMINAL))
             .update({"status": "canceled", "finished_at": utcnow(),
                      "error": "canceled by user"}, synchronize_session=False))
        db.commit()
        if n == 0:
            db.expire_all()
            raise HTTPException(409, f"job is already {db.get(Job, job_id).status}")
    write_audit(db, actor_type="user", actor_id=user.id, action="job.cancel",
                target_type="job", target_id=job_id, job_id=job_id,
                ip=request.client.host if request.client else None)
    return {"id": job_id, "status": "canceled"}


@router.get("/{job_id}/events/stream")
async def job_stream(request: Request, job_id: int, last_event_id: int | None = None):
    """Doc 05 §Streaming 1. `line` frames carry `id:` (the resume cursor);
    `progress` and `status` do not. A terminal `status` closes the stream.

    Auth is resolved once via a short-lived session in a thread, never a
    `Depends(get_db)` seam, which for a StreamingResponse would stay open for
    the life of the connection. `authorize`/`require_entitlement` are
    still the ones enforcing it (called directly, not through FastAPI's DI)
    so this route stays on the same auth -> RBAC -> entitlement seam as its
    siblings, in that order.
    """
    raw = request.cookies.get(request.app.state.settings.session_cookie)

    def check():
        with request.app.state.sessionmaker() as db:
            user = resolve_session(db, raw) if raw else None
            if user is None:
                raise HTTPException(401, "Sign in again to continue.")
            _read(request, db, user)
            require_entitlement("jobs.stream")(request)
            if db.get(Job, job_id) is None:
                raise HTTPException(404, "job not found")

    await asyncio.to_thread(check)

    header = request.headers.get("Last-Event-ID")
    after = int(header) if header and header.isdigit() else (last_event_id or 0)
    backend = request.app.state.jobs

    def frame(f: dict) -> str:
        out = f"id: {f['id']}\n" if "id" in f else ""
        return out + f"event: {f['event']}\ndata: {json.dumps(f['data'])}\n\n"

    async def gen():
        # Subscribe BEFORE reading the backlog so a line written between the
        # two is at worst replayed twice (deduped below via the high-water
        # mark) rather than lost.
        q = backend.subscribe(job_id)
        try:
            def read():
                with request.app.state.sessionmaker() as db:
                    job = db.get(Job, job_id)
                    if job is None:
                        return [], None, None, None
                    return (backlog(db, job_id, after=after), job.status,
                            job.result, job.error)
            rows, status, result, error = await asyncio.to_thread(read)
            if status is None:
                return  # job row vanished between the auth check and this read
            # High-water mark over the replay window, not the fixed resume
            # cursor: a line written between subscribe() (above) and this
            # read has seq > `after` and would otherwise be replayed here AND
            # re-delivered live: the frontend log client appends by frame,
            # it does not dedup by seq, so that duplicate is user-visible.
            last = after
            for r in rows:
                if r["stream"] == "status":
                    payload = {"status": status}
                    if result:
                        payload["result"] = result
                    if error:
                        payload["error"] = error
                    yield frame({"event": "status", "data": payload})
                else:
                    yield frame({"event": "line", "id": r["seq"],
                                 "data": {"stream": r["stream"], "ts": r["ts"],
                                          "message": r["message"]}})
                last = max(last, r["seq"])
            if status in TERMINAL:
                return
            while True:
                try:
                    f = await asyncio.wait_for(q.get(), timeout=PING_S)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                if f["event"] == "line" and f["id"] <= last:
                    continue
                yield frame(f)
                if f["event"] == "status":
                    return
        finally:
            backend.unsubscribe(job_id, q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
