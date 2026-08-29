"""In-process asyncio job runner. Every state-changing operation that takes time
is a job: a `jobs` row, log/progress lines in `job_events`, one asyncio task.
Enqueue / status / cancel / log-stream is the seam; nothing outside this
module may know how a job is executed (Celery+Redis is the swap-in if
multi-worker matters).

The DB is the transcript: every line is written before it is fanned out, so a
browser attaching mid-job reads the backlog then follows live. Zero subscribers
costs nothing; the write always happens.

Restart semantics: orphaned `running` jobs are marked `interrupted` on boot and
are NEVER resumed -- half-run root scripts do not get a second, blind
execution."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import Callable

from proxploy.models import Job, JobEvent, Schedule, to_iso, utcnow
from proxploy.services.audit import redact, resolve_target_name

# `unknown` is terminal for THIS job: the run is over and nothing will
# resume it. Reconciliation later replaces the status with a real answer,
# but it does so as its own job, so a job sitting in `unknown` is finished
# and must not be waited on or cancelled.
TERMINAL = ("succeeded", "failed", "canceled", "interrupted", "unknown")

# ponytail: fixed pool: `queued` is real because a task waits on this before it
# runs. A settings knob belongs with Phase 7's scheduler UI, where a user would
# actually go looking for it.
MAX_CONCURRENT = 4

HANDLERS: dict[str, Callable] = {}


class JobFailed(RuntimeError):
    """Raised by a handler for an expected, reportable failure.

    Says the node was NOT changed. Anything that may have left an effect
    behind is JobUnknown instead.
    """


class JobUnknown(RuntimeError):
    """Raised when the job may have changed the node and we cannot tell.

    `failed` is a claim, not an absence of one: it tells an operator nothing
    happened. An install dispatches a community script to a root shell, so a
    connection that dies after the dispatch leaves a node that may be halfway
    through, fully built, or untouched, and reporting that as failed is how one
    partial install becomes two containers.

    A job finishing `unknown` is expected to be resolved by a reconciliation
    that asks the node, which is what moves it to succeeded or failed for real.
    """


def handler(kind: str):
    """Register an `async def h(ctx: JobContext, params: dict) -> dict`."""
    def register(fn):
        HANDLERS[kind] = fn
        return fn
    return register


# Values registered by ctx.hide for jobs that are still running, keyed by job
# id so a finished job stops costing anything. Read by the log record
# factory below, which is the sink ctx cannot reach on its own.
#
# This exists because the stdlib logging module is a sink ctx cannot see. A
# handler that logs directly, or a library that logs an exception carrying the
# failing command line, reaches around JobContext entirely, and the failing
# command line is exactly where an interpolated answer shows up.
_ACTIVE_SECRETS: dict[int, list[str]] = {}


def _scrub_values(text: str) -> str:
    values = {v for vs in _ACTIVE_SECRETS.values() for v in vs}
    for v in sorted(values, key=len, reverse=True):
        text = text.replace(v, "[redacted]")
    return text


_scrub_installed = False


def _install_log_scrubber() -> None:
    """Wrap the log record factory, once, the first time a job hides anything.

    A record FACTORY rather than a Filter on the root logger, which was the
    first attempt and does not work: logger-level filters only run for records
    logged directly to that logger, never for ones propagated up from a child,
    so anything logged to `proxploy.<anything>` sailed straight past it. The
    factory runs for every record from every logger before any handler sees it.

    Not installed at import: a deployment that never uses install answers
    should not pay this on every record it emits, and while no job has hidden
    anything the wrapper is a single empty-dict check.

    Residual, deliberately not solved here: an exception TRACEBACK is rendered
    from record.exc_info by the handler, long after this runs, so a secret
    inside a traceback frame is not covered. The job error path is scrubbed in
    _finish, which is where a handler's exception actually reaches an operator.
    """
    global _scrub_installed
    if _scrub_installed:
        return
    _scrub_installed = True
    previous = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        if _ACTIVE_SECRETS:
            msg = record.getMessage()
            out = _scrub_values(msg)
            if out != msg:
                # Collapsed into msg because getMessage() already interpolated
                # args; leaving args in place would re-expand the original.
                record.msg, record.args = out, ()
        return record

    logging.setLogRecordFactory(factory)


class JobContext:
    """The only way a handler emits output. Handed in by JobBackend._run.

    ponytail: job-row and job_events writes run inline on the event loop, one
    small SQLite insert each (tens of microseconds), and the cancellation path
    must persist its terminal row without an `await` (awaiting inside a
    cancelled task's except block is a re-cancellation hazard). Phase 4's
    thousand-line install transcripts are the trigger to move line writes onto
    a batched writer thread.
    """

    def __init__(self, backend: JobBackend, job_id: int) -> None:
        self.backend = backend
        self.job_id = job_id
        self._hidden: list[str] = []
        self._seq = 0
        # Safety net, not the fix: guards a handler bug reporting a value lower than
        # one it already reported, clamping UP to the last value. Never rely on it to
        # make a badly-banded job look right -- a real next phase starting low would
        # freeze at the earlier phase's high-water mark.
        self._last_pct = 0

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    @property
    def last_pct(self) -> int:
        """The last value this job reported, for a caller that wants to hold progress
                steady rather than move it (e.g. deleting a transfer artifact is not
                forward progress)."""
        return self._last_pct

    # The minimum length a value must have before `hide` will accept it.
    # A one or two character "secret" matches everywhere and would turn the
    # transcript into [redacted] soup while telling an attacker nothing they
    # could not guess, so those are refused loudly rather than scrubbed.
    MIN_HIDE_LEN = 4

    def hide(self, *values: str | None) -> None:
        """Register literal values to strip from everything this job emits.

        BY VALUE, NEVER BY NAME, and that is the whole point. services/audit.py
        redacts a params dict by inspecting KEY NAMES, which works there
        because we choose those keys. The install answers do not work that way:
        the variable a prompt assigns into is named by whoever wrote the
        upstream community-scripts installer, and that name carries no reliable
        signal. Measured against the real catalog on 2026-08-27: of 15 prompts
        whose text asks for something sensitive, 11 have a variable name the
        audit heuristic does not catch, including `ziti_pwd` holding an admin
        password, four API keys named `*key` (which `REDACT_SUBSTRINGS` excludes
        deliberately, see the note there), and an openziti enrollment JWT read
        into a variable literally called `prompt`.

        No substring list can catch `prompt`. Do not "simplify" this back into
        one. The caller knows the exact strings it injected, and matching those
        cannot miss.
        """
        for v in values:
            if v and len(v) >= self.MIN_HIDE_LEN and v not in self._hidden:
                self._hidden.append(v)
        if self._hidden:
            _install_log_scrubber()
            _ACTIVE_SECRETS[self.job_id] = list(self._hidden)

    def scrub(self, text: str | None) -> str | None:
        """Every registered value replaced, longest first so an overlapping
        pair cannot leave a fragment of the longer one behind."""
        if not text or not self._hidden:
            return text
        for v in sorted(self._hidden, key=len, reverse=True):
            text = text.replace(v, "[redacted]")
        return text

    def scrub_obj(self, obj):
        """scrub() over a result dict, which a handler may build out of the
        same answers it was given."""
        if isinstance(obj, dict):
            return {k: self.scrub_obj(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.scrub_obj(v) for v in obj]
        if isinstance(obj, str):
            return self.scrub(obj)
        return obj

    def log(self, message: str, stream: str = "stdout") -> None:
        # Scrubbed ONCE, before either sink. The row and the frame carry the
        # same text by construction, so a secret cannot be cleaned out of the
        # database while still being streamed live to a browser.
        message = self.scrub(message) or ""
        seq = self._next_seq()
        ts = utcnow()
        with self.backend.app.state.sessionmaker() as db:
            db.add(JobEvent(job_id=self.job_id, seq=seq, ts=ts,
                            stream=stream, message=message))
            db.commit()
        self.backend._fanout(self.job_id, {
            "event": "line", "id": seq,
            "data": {"stream": stream, "ts": to_iso(ts), "message": message},
        })

    def checkpoint(self, **facts) -> None:
        """Record what the node looked like before this job dispatches an
        effect, so reconciliation can ask the node afterwards.

        Committed on its own connection and BEFORE the effect leaves the
        machine, which is the whole point: a checkpoint written after the
        dispatch would be missing in exactly the crash it exists for. No
        fanout and no publish, because this is not progress an operator is
        watching, it is evidence for a recovery that may never be needed.
        """
        with self.backend.app.state.sessionmaker() as db:
            job = db.get(Job, self.job_id)
            if job is not None:
                job.checkpoint = {**(job.checkpoint or {}), **facts}
                db.commit()

    def progress(self, pct: int) -> None:
        pct = max(0, min(100, int(pct)))
        pct = max(pct, self._last_pct)  # safety net: never report backwards, see __init__
        self._last_pct = pct
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
        # "A cancelled job stops cleanly" needs three pieces of bookkeeping beyond
        # _tasks:
        # - _pending: enqueued, `_spawn` hasn't had its loop turn yet (the
        # call_soon_threadsafe gap): a cancel() in this window has no Task to cancel.
        # - _cancel_requested: job ids cancelled while still in _pending; _run checks
        # this before the semaphore and finishes as canceled.
        # - _done: one Event per in-flight job, set/popped in _run's finally; wait()
        # awaits this instead of polling _tasks.
        self._pending: set[int] = set()
        self._cancel_requested: set[int] = set()
        self._done: dict[int, asyncio.Event] = {}


    def sweep_orphans(self) -> int:
        """Boot-time sweep. Marks; still never resumes.

                Two outcomes now, not one. A job that had not dispatched anything is
                `interrupted`, unchanged. A job whose checkpoint says its command had
                already reached a root shell is `unknown` and gets a reconciliation
                queued, because this process cannot say what the node did while it was
                dead and only the node can.

                The asking stays OUT of here deliberately. This runs at boot and must
                not make startup wait on a node being reachable, and reconciliation
                needs retries, which is a job's job. So this marks and hands off.

                Orphans get a single aggregate Notifier message: Apprise is blocking
                (~8s/channel) and per-orphan sends would queue many blocking sends on
                the shared default executor at once. Never awaited, so it can't stall
                startup."""
        with self.app.state.sessionmaker() as db:
            rows = (db.query(Job)
                    .filter(Job.status.in_(("queued", "running")))
                    .all())
            orphans = [(j.id, j.kind) for j in rows]
            names = {j.id: (j.target_name or j.kind) for j in rows}
            # A job that had already dispatched an effect is not `interrupted`,
            # which reads as "it did not happen". Its checkpoint says the
            # command reached a root shell before this process died, so the
            # node may be halfway through and only the node can say. Same
            # discriminator the handler uses for a dropped connection, so both
            # ways of being interrupted land on the same reconciler.
            unknown = [j for j in rows if (j.checkpoint or {}).get("dispatched")]
            unknown_ids = {j.id for j in unknown}
            now = utcnow()
            for j in rows:
                j.status = "unknown" if j.id in unknown_ids else "interrupted"
                j.finished_at = now
            n = len(rows)
            db.commit()
        # Every job still sitting in `unknown` from an earlier life, not only
        # the ones this sweep just marked. A reconciliation that was itself
        # running when the process died was just swept to `interrupted`, and
        # nothing else would ever ask again: the install would stay unknown
        # forever and the App Store would stay blocked on it. Re-queuing is
        # safe because run_install_reconcile no-ops on a job that is no longer
        # unknown, which is also what stops two of them racing.
        with self.app.state.sessionmaker() as db:
            stale = (db.query(Job.id, Job.kind)
                     .filter(Job.status == "unknown")
                     .all())
        # Queued after the commit, so a reconciliation can never read the row
        # it is about while that row is still `running`. Enqueue hops to the
        # loop, which is why this is not inside the session above.
        for job_id, kind in stale:
            self._reconcile_after(job_id, kind)
        if unknown:
            from proxploy.services.notification_types import BY_KEY, type_for_job
            for j in unknown:
                key = type_for_job(j.kind, "unknown")
                row = BY_KEY.get(key)
                where = names.get(j.id, j.kind)
                self._notify_async(
                    key,
                    f"Proxploy: {row.label if row else j.kind + ' unknown'}",
                    f"Proxploy restarted while this was running on {where}. It "
                    f"had already started work on the host, so it may have "
                    f"completed, stopped partway, or done nothing. Proxploy is "
                    f"checking the host to find out which.")

        interrupted = [(i, k) for i, k in orphans if i not in unknown_ids]
        if interrupted:
            kinds = ", ".join(sorted({kind for _, kind in interrupted}))
            count = len(interrupted)
            job_word = "job" if count == 1 else "jobs"
            title = f"Proxploy restarted: {count} {job_word} interrupted"
            body = f"Proxploy restarted. {count} {job_word} interrupted: {kinds}"
            self._notify_async("job.interrupted", title, body)
        return n

    def stop(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        self._tasks.clear()


    def enqueue(self, db, *, kind: str, target_type: str | None = None,
                target_id: int | None = None, params: dict | None = None,
                requested_by: int | None = None,
                schedule_id: int | None = None,
                target_name: str | None = None) -> Job:
        """Called from sync (threadpool) route handlers; hops to the loop to spawn.
                Every job in the app is created here, so this is where the target's
                name gets captured -- a destroy job outlives the row it names. Callers
                pass `target_name` explicitly only when the target has no name to look
                up."""
        if kind not in HANDLERS:
            raise KeyError(f"no handler registered for job kind {kind!r}")
        job = Job(kind=kind, status="queued", target_type=target_type,
                  target_id=target_id,
                  target_name=target_name or resolve_target_name(
                      db, target_type, target_id),
                  params=redact(params) if params else None,
                  requested_by=requested_by, schedule_id=schedule_id)
        db.add(job)
        db.commit()
        self._pending.add(job.id)
        self._done[job.id] = asyncio.Event()
        # call_soon_threadsafe works from the loop thread AND from FastAPI's
        # threadpool, which is where every `def` route handler runs.
        self.app.state.loop.call_soon_threadsafe(
            self._spawn, job.id, kind, dict(params or {}), target_type)
        return job

    def _spawn(self, job_id: int, kind: str, params: dict,
               target_type: str | None = None) -> None:
        self._pending.discard(job_id)
        self._publish(job_id, status="queued", kind=kind, target_type=target_type)
        self._tasks[job_id] = asyncio.create_task(
            self._run(job_id, kind, params, target_type))

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
            # before acquiring the semaphore and finishes without ever
            # calling the handler.
            self._cancel_requested.add(job_id)
            return True
        return False  # never enqueued here, or already terminal

    async def wait(self, job_id: int, timeout: float = 30.0) -> bool:
        """Block until the job settles. Returns True if it did, False on timeout.
                Waits on a per-job Event (set/popped in `_run`'s finally) rather than
                polling `_tasks`, which is pruned on completion and would busy-spin."""
        ev = self._done.get(job_id)
        if ev is None:
            return True  # unknown to this backend, or already cleaned up: settled
        try:
            await asyncio.wait_for(ev.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False


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
        """Global `job` delta for every open tab."""
        self.app.state.bus.publish("job", {"id": job_id, **fields})


    async def _run(self, job_id: int, kind: str, params: dict,
                    target_type: str | None = None) -> None:
        ctx = JobContext(self, job_id)
        try:
            # Checked BEFORE the semaphore acquire, not inside: a pre-spawn cancel of a
            # job still in `_pending` only sets `_cancel_requested`, and nothing re-checks
            # it once the pool is full -- gating on acquire would strand the row `queued`
            # forever. A cancel after this point finds the job in `_tasks` and calls
            # `task.cancel()` directly, raising CancelledError out of the acquire.
            if job_id in self._cancel_requested:
                self._cancel_requested.discard(job_id)
                self._finish(ctx, kind, "canceled", error="canceled by user",
                             target_type=target_type)
                return
            # `try` wraps the acquire itself: a job cancelled while queued behind
            # MAX_CONCURRENT raises CancelledError out of `await self._sem.acquire()`
            # before the `with` block is entered. If `try` only wrapped the body, that
            # escape stranded the row in `queued` forever (no finished_at, status event,
            # or terminal frame).
            async with self._sem:
                self._set_running(job_id)
                self._publish(job_id, status="running", kind=kind, target_type=target_type)
                result = await HANDLERS[kind](ctx, params)
        except asyncio.CancelledError:
            self._finish(ctx, kind, "canceled", error="canceled by user",
                         target_type=target_type)
            raise
        except JobUnknown as e:
            # Ordered before JobFailed only for readability; they are siblings,
            # not a hierarchy.
            self._finish(ctx, kind, "unknown", error=str(e), target_type=target_type)
        except JobFailed as e:
            self._finish(ctx, kind, "failed", error=str(e), target_type=target_type)
        except Exception as e:  # noqa: BLE001  (a handler bug is a failed job)
            self._finish(ctx, kind, "failed", error=f"{type(e).__name__}: {e}",
                         target_type=target_type)
        else:
            self._finish(ctx, kind, "succeeded", result=result or {}, target_type=target_type)
        finally:
            # `spool_path`: a file the route staged for the job (api/storage.py spools an
            # upload body to data_dir/uploads). The job owns deleting it, and it cannot
            # live in the handler because the handler doesn't always run: both cancel
            # paths settle without calling HANDLERS[kind]. Removed here on every exit.
            # Suppressed: a failed unlink must not turn a succeeded job into a failed one.
            spool = params.get("spool_path")
            if spool:
                with contextlib.suppress(OSError):
                    os.unlink(spool)
            # Bound _tasks/_done to in-flight jobs only: otherwise a daemon
            # running for months holds every completed Task (and its retained
            # result/exception) and every Event forever.
            _ACTIVE_SECRETS.pop(job_id, None)
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

    def _reconcile_after(self, job_id: int, kind: str) -> None:
        """Queue the reconciliation for a job that ended `unknown`.

        Generic on purpose: a kind opts in by registering `<kind>.reconcile`,
        so this file needs to know nothing about installs. A kind with no
        reconciler simply stays unknown, which is still an honest answer.

        Never allowed to fail the finish it follows. The job is already
        terminal and correctly marked; losing the reconciliation costs an
        operator a manual check, while raising here would lose the status too.
        """
        reconcile_kind = f"{kind}.reconcile"
        if reconcile_kind not in HANDLERS:
            return
        try:
            with self.app.state.sessionmaker() as db:
                self.enqueue(db, kind=reconcile_kind, target_type="job",
                             target_id=job_id, params={"job_id": job_id},
                             target_name=f"job {job_id}")
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception(
                "could not queue %s for job %s", reconcile_kind, job_id)

    def _finish(self, ctx: JobContext, kind: str, status: str, *,
                result: dict | None = None, error: str | None = None,
                target_type: str | None = None) -> None:
        """Synchronous on purpose: the cancel path cannot await (see JobContext)."""
        job_id = ctx.job_id
        # The terminal path is the OTHER half of ctx.hide, and the half the
        # analysis said actually leaks. An install script interpolates an
        # answer straight into a command (kometa-install.sh puts the TMDb key
        # into a `sed`), so the value shows up in error text and under xtrace
        # rather than on the happy path. From here `error` reaches five sinks:
        # jobs.error, a job_events row, the per-job fanout, the global publish
        # and the outbound notification. Scrub once, above all five.
        error = ctx.scrub(error)
        result = ctx.scrub_obj(result) if result else result
        # Captured while the row is loaded, because the notification is sent
        # after this session closes and re-reading it there would be a second
        # query for facts already in hand.
        facts: dict = {}
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
                schedule = (db.get(Schedule, job.schedule_id)
                            if job.schedule_id else None)
                from proxploy.services.links import absolute, path_for
                facts = {"target_name": job.target_name,
                         "target_type": job.target_type or target_type,
                         "started_at": job.started_at,
                         "finished_at": job.finished_at,
                         "schedule_name": schedule.name if schedule else None,
                         # There is no /jobs route, so the link points at the
                         # thing the job was about, which is what someone
                         # reading "backup of pve1 failed" wants anyway.
                         "link": absolute(db, path_for(job.target_type,
                                                       job.target_id))}
        payload: dict = {"status": status}
        if result:
            payload["result"] = result
        if error:
            payload["error"] = error
        self._fanout(job_id, {"event": "status", "data": payload})
        # error only when set (mirrors the fanout payload above): the global
        # `job` delta is what LiveProvider's failure toast reads its message
        # from, and a bare "App Stop Failed" with no reason was the finding.
        # notify_type rides along so the client can honour the same master
        # switch without keeping its own copy of the job kind table.
        from proxploy.services.notification_types import type_for_job
        self._publish(job_id, status=status, kind=kind, target_type=target_type,
                      notify_type=type_for_job(kind, status),
                      **({"error": error} if error else {}))
        self._notify(job_id, kind, status, error, facts)
        # After the row is terminal and the world has been told, so the
        # reconciliation cannot observe a half-written status and so a failure
        # to queue it cannot lose the status itself.
        if status == "unknown":
            self._reconcile_after(job_id, kind)

    def _notify(self, job_id: int, kind: str, status: str, error: str | None,
                facts: dict) -> None:
        """Route the terminal result to the Notifier, off the event loop.
                The registry maps (kind, status) onto exactly one row, so a named kind
                never also fires the generic one. The title is the row's own label,
                not the job kind, so the Events matrix reads the same words as the
                subject line."""
        from proxploy.services.notification_body import (
            compose, human_duration, job_facts)
        from proxploy.services.notification_types import BY_KEY, type_for_job

        key = type_for_job(kind, status)
        row = BY_KEY.get(key)
        title = f"Proxploy: {row.label if row else kind + ' ' + status}"
        body = compose(
            job_facts(job_id=job_id,
                      target_name=facts.get("target_name"),
                      target_type=facts.get("target_type"),
                      duration=human_duration(facts.get("started_at"),
                                              facts.get("finished_at")),
                      schedule_name=facts.get("schedule_name")),
            error, link=facts.get("link", ""))
        self._notify_async(key, title, body)

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
            except Exception:  # noqa: BLE001  (notifications never fail a job)
                pass

        task = asyncio.ensure_future(go())
        self._side.add(task)
        task.add_done_callback(self._side.discard)
