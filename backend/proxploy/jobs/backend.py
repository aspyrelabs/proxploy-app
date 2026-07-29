"""JobBackend — the in-process asyncio job runner (brief §5, doc 02 §3, doc 03).

Every state-changing operation that takes time is a job: a `jobs` row, log and
progress lines in `job_events`, executed as one asyncio task. Enqueue / status /
cancel / log-stream is the seam; Celery+Redis is the swap-in if multi-worker
ever matters — nothing outside this module may know how a job is executed.

The DB is the transcript. Every line is written before it is fanned out, so a
browser attaching mid-job reads the backlog from `job_events` and then follows
live (doc 02 §6). Zero subscribers costs nothing; the write always happens.

Restart semantics (doc 02 §3, verbatim): orphaned `running` jobs are marked
`interrupted` on boot and are NEVER resumed — half-run root scripts do not get
a second, blind execution.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable

from proxploy.models import Job, JobEvent, utcnow
from proxploy.services.audit import redact

TERMINAL = ("succeeded", "failed", "canceled", "interrupted")

# ponytail: fixed pool — `queued` is real because a task waits on this before it
# runs. A settings knob belongs with Phase 7's scheduler UI, where a user would
# actually go looking for it.
MAX_CONCURRENT = 4

HANDLERS: dict[str, Callable] = {}


class JobFailed(RuntimeError):
    """Raised by a handler for an expected, reportable failure."""


def handler(kind: str):
    """Register an `async def h(ctx: JobContext, params: dict) -> dict`."""
    def register(fn):
        HANDLERS[kind] = fn
        return fn
    return register


class JobContext:
    """The only way a handler emits output. Handed in by JobBackend._run.

    ponytail: job-row and job_events writes run inline on the event loop — one
    small SQLite insert each (tens of microseconds), and the cancellation path
    must persist its terminal row without an `await` (awaiting inside a
    cancelled task's except block is a re-cancellation hazard). Phase 4's
    thousand-line install transcripts are the trigger to move line writes onto
    a batched writer thread.
    """

    def __init__(self, backend: JobBackend, job_id: int) -> None:
        self.backend = backend
        self.job_id = job_id
        self._seq = 0

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def log(self, message: str, stream: str = "stdout") -> None:
        seq = self._next_seq()
        ts = utcnow()
        with self.backend.app.state.sessionmaker() as db:
            db.add(JobEvent(job_id=self.job_id, seq=seq, ts=ts,
                            stream=stream, message=message))
            db.commit()
        self.backend._fanout(self.job_id, {
            "event": "line", "id": seq,
            "data": {"stream": stream, "ts": ts.isoformat() + "Z", "message": message},
        })

    def progress(self, pct: int) -> None:
        pct = max(0, min(100, int(pct)))
        with self.backend.app.state.sessionmaker() as db:
            job = db.get(Job, self.job_id)
            if job is not None:
                job.progress_pct = pct
                db.commit()
        self.backend._fanout(self.job_id, {"event": "progress", "data": {"pct": pct}})
        self.backend._publish(self.job_id, progress_pct=pct)


class JobBackend:
    def __init__(self, app) -> None:
        self.app = app
        self._tasks: dict[int, asyncio.Task] = {}
        self._subs: dict[int, set[asyncio.Queue]] = {}
        self._sem = asyncio.Semaphore(MAX_CONCURRENT)
        self._side: set[asyncio.Task] = set()  # keeps fire-and-forget tasks alive

    # --- lifecycle ---------------------------------------------------------

    def sweep_orphans(self) -> int:
        """Boot-time reconciliation (doc 02 §3). Marks; never resumes."""
        with self.app.state.sessionmaker() as db:
            n = (db.query(Job)
                 .filter(Job.status.in_(("queued", "running")))
                 .update({"status": "interrupted", "finished_at": utcnow()},
                         synchronize_session=False))
            db.commit()
            return n

    def stop(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        self._tasks.clear()

    # --- enqueue / cancel --------------------------------------------------

    def enqueue(self, db, *, kind: str, target_type: str | None = None,
                target_id: int | None = None, params: dict | None = None,
                requested_by: int | None = None,
                schedule_id: int | None = None) -> Job:
        """Called from sync (threadpool) route handlers; hops to the loop to spawn."""
        if kind not in HANDLERS:
            raise KeyError(f"no handler registered for job kind {kind!r}")
        job = Job(kind=kind, status="queued", target_type=target_type,
                  target_id=target_id, params=redact(params) if params else None,
                  requested_by=requested_by, schedule_id=schedule_id)
        db.add(job)
        db.commit()
        # call_soon_threadsafe works from the loop thread AND from FastAPI's
        # threadpool, which is where every `def` route handler runs.
        self.app.state.loop.call_soon_threadsafe(
            self._spawn, job.id, kind, dict(params or {}))
        return job

    def _spawn(self, job_id: int, kind: str, params: dict) -> None:
        self._publish(job_id, status="queued", kind=kind)
        self._tasks[job_id] = asyncio.create_task(self._run(job_id, kind, params))

    def cancel(self, job_id: int) -> bool:
        task = self._tasks.get(job_id)
        if task is None or task.done():
            return False
        self.app.state.loop.call_soon_threadsafe(task.cancel)
        return True

    async def wait(self, job_id: int, timeout: float = 30.0) -> None:
        """Test/DoD helper: block until the job's task settles.

        ponytail-deviation: `enqueue` spawns via `call_soon_threadsafe`, which
        only *schedules* `_spawn` — it hasn't run yet when `wait` is called
        back-to-back on the same loop (every test in this suite does exactly
        that). The brief's version read `self._tasks` before that callback
        ever got a turn and returned instantly with nothing to wait on. Poll
        with `asyncio.sleep(0)` until the task exists (or timeout) so the
        loop gets a turn to run `_spawn` first.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while job_id not in self._tasks:
            if loop.time() >= deadline:
                return
            await asyncio.sleep(0)
        await asyncio.wait([self._tasks[job_id]], timeout=timeout)

    # --- per-job fanout ----------------------------------------------------

    def subscribe(self, job_id: int) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subs.setdefault(job_id, set()).add(q)
        return q

    def unsubscribe(self, job_id: int, q: asyncio.Queue) -> None:
        subs = self._subs.get(job_id)
        if subs:
            subs.discard(q)
            if not subs:
                self._subs.pop(job_id, None)

    def _fanout(self, job_id: int, frame: dict) -> None:
        for q in list(self._subs.get(job_id, ())):
            try:
                q.put_nowait(frame)
            except asyncio.QueueFull:
                pass  # slow consumer loses frames; the DB transcript is intact

    def _publish(self, job_id: int, **fields) -> None:
        """Global `job` delta for every open tab (doc 05 §Streaming 4)."""
        self.app.state.bus.publish("job", {"id": job_id, **fields})

    # --- the runner --------------------------------------------------------

    async def _run(self, job_id: int, kind: str, params: dict) -> None:
        ctx = JobContext(self, job_id)
        async with self._sem:
            self._set_running(job_id)
            self._publish(job_id, status="running", kind=kind)
            try:
                result = await HANDLERS[kind](ctx, params)
            except asyncio.CancelledError:
                self._finish(ctx, kind, "canceled", error="canceled by user")
                raise
            except JobFailed as e:
                self._finish(ctx, kind, "failed", error=str(e))
            except Exception as e:  # noqa: BLE001 — a handler bug is a failed job
                self._finish(ctx, kind, "failed", error=f"{type(e).__name__}: {e}")
            else:
                self._finish(ctx, kind, "succeeded", result=result or {})

    def _set_running(self, job_id: int) -> None:
        with self.app.state.sessionmaker() as db:
            job = db.get(Job, job_id)
            if job is not None:
                job.status, job.started_at = "running", utcnow()
                db.commit()

    def _finish(self, ctx: JobContext, kind: str, status: str, *,
                result: dict | None = None, error: str | None = None) -> None:
        """Synchronous on purpose: the cancel path cannot await (see JobContext)."""
        job_id = ctx.job_id
        with self.app.state.sessionmaker() as db:
            job = db.get(Job, job_id)
            if job is not None:
                job.status, job.finished_at = status, utcnow()
                job.result, job.error = result, error
                if status == "succeeded":
                    job.progress_pct = 100
                db.add(JobEvent(job_id=job_id, seq=ctx._next_seq(), ts=utcnow(),
                                stream="status",
                                message=f"{status}: {error or 'ok'}"))
                db.commit()
        payload: dict = {"status": status}
        if result:
            payload["result"] = result
        if error:
            payload["error"] = error
        self._fanout(job_id, {"event": "status", "data": payload})
        self._publish(job_id, status=status, kind=kind)
        self._notify(job_id, kind, status, error)

    def _notify(self, job_id: int, kind: str, status: str, error: str | None) -> None:
        """Route the terminal result through the Notifier. Wired in Task 6."""
        return
