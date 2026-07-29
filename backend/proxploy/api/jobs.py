"""Jobs API (doc 05 §Jobs) + the per-job transcript stream (§Streaming 1).

SSE, not websockets: a job log is strictly one-way, and EventSource's native
reconnect + `Last-Event-ID` maps onto `job_events.seq` for free.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from proxploy.api.deps import get_db, require_entitlement, require_role
from proxploy.jobs import TERMINAL
from proxploy.models import Job, JobEvent, User
from proxploy.services.audit import write_audit
from proxploy.services.authn import resolve_session

router = APIRouter(prefix="/jobs", tags=["jobs"])

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


@router.get("", dependencies=[Depends(require_entitlement("jobs.history"))])
def list_jobs(response: Response, status: str | None = None, kind: str | None = None,
              target: str | None = None, page: int = 1, per_page: int = 50,
              db=Depends(get_db), user: User = Depends(require_role("viewer"))):
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


@router.get("/{job_id}", dependencies=[Depends(require_entitlement("jobs.history"))])
def job_detail(job_id: int, db=Depends(get_db),
               user: User = Depends(require_role("viewer"))):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job_out(job)


@router.get("/{job_id}/events",
            dependencies=[Depends(require_entitlement("jobs.history"))])
def job_events(job_id: int, after: int = 0, limit: int = 5000, db=Depends(get_db),
               user: User = Depends(require_role("viewer"))):
    if db.get(Job, job_id) is None:
        raise HTTPException(404, "job not found")
    return backlog(db, job_id, after=after, limit=limit)


@router.post("/{job_id}/cancel")
def cancel_job(request: Request, job_id: int, db=Depends(get_db),
               user: User = Depends(require_role("operator"))):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    if job.status in TERMINAL:
        raise HTTPException(409, f"job is already {job.status}")
    # Ask the runner first; if no task owns it (e.g. enqueued by a process that
    # has since restarted), mark it canceled here so the row never dangles.
    if not request.app.state.jobs.cancel(job_id):
        from proxploy.models import utcnow
        job.status, job.finished_at = "canceled", utcnow()
        job.error = "canceled by user"
        db.commit()
    write_audit(db, actor_type="user", actor_id=user.id, action="job.cancel",
                target_type="job", target_id=job_id, job_id=job_id,
                ip=request.client.host if request.client else None)
    return {"id": job_id, "status": "canceled"}


@router.get("/{job_id}/events/stream")
async def job_stream(request: Request, job_id: int, last_event_id: int | None = None):
    """Doc 05 §Streaming 1. `line` frames carry `id:` (the resume cursor);
    `progress` and `status` do not. A terminal `status` closes the stream."""
    raw = request.cookies.get(request.app.state.settings.session_cookie)

    def check():
        with request.app.state.sessionmaker() as db:
            user = resolve_session(db, raw) if raw else None
            if user is None:
                return None, None
            return user, db.get(Job, job_id) is not None

    user, exists = await asyncio.to_thread(check)
    if user is None:
        raise HTTPException(401, "authentication required")
    if not request.app.state.entitlements.enabled("jobs.stream"):
        raise HTTPException(403, {"error": "entitlement_required", "feature": "jobs.stream"})
    if not exists:
        raise HTTPException(404, "job not found")

    header = request.headers.get("Last-Event-ID")
    after = int(header) if header and header.isdigit() else (last_event_id or 0)
    backend = request.app.state.jobs

    def frame(f: dict) -> str:
        out = f"id: {f['id']}\n" if "id" in f else ""
        return out + f"event: {f['event']}\ndata: {json.dumps(f['data'])}\n\n"

    async def gen():
        # Subscribe BEFORE reading the backlog so a line written between the two
        # is duplicated (harmless, seq-keyed) rather than lost.
        q = backend.subscribe(job_id)
        try:
            def read():
                with request.app.state.sessionmaker() as db:
                    job = db.get(Job, job_id)
                    return backlog(db, job_id, after=after), job.status
            rows, status = await asyncio.to_thread(read)
            for r in rows:
                if r["stream"] == "status":
                    yield frame({"event": "status", "data": {"status": status}})
                else:
                    yield frame({"event": "line", "id": r["seq"],
                                 "data": {"stream": r["stream"], "ts": r["ts"],
                                          "message": r["message"]}})
            if status in TERMINAL:
                return
            while True:
                try:
                    f = await asyncio.wait_for(q.get(), timeout=PING_S)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                if f["event"] == "line" and f["id"] <= after:
                    continue
                yield frame(f)
                if f["event"] == "status":
                    return
        finally:
            backend.unsubscribe(job_id, q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
