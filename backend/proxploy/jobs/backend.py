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
        # doc 02 §3 DoD "a cancelled job stops cleanly" needs three small pieces
        # of bookkeeping beyond _tasks:
        # - _pending: enqueued, `_spawn` hasn't had its loop turn yet (the same
        #   call_soon_threadsafe gap the `wait()` fix above works around) — a
        #   cancel() that lands in this window has no Task to call .cancel() on.
        # - _cancel_requested: job ids cancelled while still in _pending; _run
        #   checks this right after acquiring the semaphore and finishes the
        #   job as canceled instead of ever invoking the handler.
        # - _done: one Event per in-flight job, set (and popped) in _run's
        #   finally. wait() awaits this instead of polling _tasks, which also
        #   fixes the busy-spin and lets both dicts stay bounded to in-flight
        #   jobs only (see the finally block in _run).
        self._pending: set[int] = set()
        self._cancel_requested: set[int] = set()
        self._done: dict[int, asyncio.Event] = {}

    # --- lifecycle ---------------------------------------------------------

    def sweep_orphans(self) -> int:
        """Boot-time reconciliation (doc 02 §3). Marks; never resumes.

        Called from lifespan startup once the loop is running (main.py sets
        `app.state.loop` just before this). `job.interrupted` still owes the
        orphans a Notifier courtesy, but Apprise is blocking (~8s/channel
        worst case) and a restart can orphan an arbitrarily large backlog —
        one `_notify` per orphan would queue that many blocking sends onto
        the loop's shared default executor (poller, metrics loop and SSE
        auth hops all use it too) all at once. Send a single aggregate
        notification instead: one send regardless of backlog size, and a
        better message for a human than N separate pings. Never awaited
        here either way, so it can't stall startup.
        """
        with self.app.state.sessionmaker() as db:
            orphans = (db.query(Job.id, Job.kind)
                       .filter(Job.status.in_(("queued", "running")))
                       .all())
            n = (db.query(Job)
                 .filter(Job.status.in_(("queued", "running")))
                 .update({"status": "interrupted", "finished_at": utcnow()},
                         synchronize_session=False))
            db.commit()
        if orphans:
            kinds = ", ".join(sorted({kind for _, kind in orphans}))
            title = f"Proxploy: {n} job(s) interrupted by restart"
            body = f"{n} job(s) interrupted by restart: {kinds}"
            self._notify_async("job.interrupted", title, body)
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
        self._pending.add(job.id)
        self._done[job.id] = asyncio.Event()
        # call_soon_threadsafe works from the loop thread AND from FastAPI's
        # threadpool, which is where every `def` route handler runs.
        self.app.state.loop.call_soon_threadsafe(
            self._spawn, job.id, kind, dict(params or {}))
        return job

    def _spawn(self, job_id: int, kind: str, params: dict) -> None:
        self._pending.discard(job_id)
        self._publish(job_id, status="queued", kind=kind)
        self._tasks[job_id] = asyncio.create_task(self._run(job_id, kind, params))

    def cancel(self, job_id: int) -> bool:
        task = self._tasks.get(job_id)
        if task is not None:
            if task.done():
                return False
            self.app.state.loop.call_soon_threadsafe(task.cancel)
            return True
        if job_id in self._pending:
            # `_spawn` hasn't run yet (still in the call_soon_threadsafe gap):
            # no Task exists to cancel. Record the intent; `_run` checks this
            # right after acquiring the semaphore and finishes without ever
            # calling the handler.
            self._cancel_requested.add(job_id)
            return True
        return False  # never enqueued here, or already terminal

    async def wait(self, job_id: int, timeout: float = 30.0) -> bool:
        """Test/DoD helper: block until the job settles. Returns True if it
        did, False on timeout — lets a caller tell "settled" from "gave up".

        Waits on a per-job Event set (and popped) in `_run`'s finally, rather
        than polling `_tasks` — that dict is pruned on completion (see `_run`)
        so a poll-based wait would busy-spin its full timeout on a job that
        already finished.
        """
        ev = self._done.get(job_id)
        if ev is None:
            return True  # unknown to this backend, or already cleaned up: settled
        try:
            await asyncio.wait_for(ev.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False

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
        try:
            # `try` wraps the semaphore acquire itself: a job cancelled while
            # still queued behind MAX_CONCURRENT running jobs raises
            # CancelledError out of `await self._sem.acquire()`, before the
            # `with` block below is entered. If `try` only wrapped the body,
            # that CancelledError escaped uncaught and the row was stranded
            # in `queued` forever — no finished_at, no status event, no
            # terminal frame for any subscriber.
            async with self._sem:
                if job_id in self._cancel_requested:
                    self._cancel_requested.discard(job_id)
                    self._finish(ctx, kind, "canceled", error="canceled by user")
                    return
                self._set_running(job_id)
                self._publish(job_id, status="running", kind=kind)
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
        finally:
            # Bound _tasks/_done to in-flight jobs only — otherwise a daemon
            # running for months holds every completed Task (and its retained
            # result/exception) and every Event forever.
            self._tasks.pop(job_id, None)
            ev = self._done.pop(job_id, None)
            if ev is not None:
                ev.set()

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
        """Route the terminal result to the Notifier, off the event loop."""
        title = f"Proxploy: {kind} {status}"
        body = error or f"job {job_id} ({kind}) {status}"
        self._notify_async(f"job.{status}", title, body)

    def _notify_async(self, event: str, title: str, body: str) -> None:
        """Fire the Notifier off the event loop, fire-and-forget.

        A notification is a courtesy, never part of the job's own success (or,
        for `sweep_orphans`, part of app startup). `_side` holds a reference
        so the task is not GC'd mid-flight.
        """
        from proxploy.services import notifier

        async def go():
            try:
                await asyncio.to_thread(notifier.notify, self.app, event, title, body)
            except Exception:  # noqa: BLE001 — notifications never fail a job
                pass

        task = asyncio.ensure_future(go())
        self._side.add(task)
        task.add_done_callback(self._side.discard)
