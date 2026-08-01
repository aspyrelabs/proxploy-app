"""Scheduler seam (brief §5, doc 02 §3, doc 04 `schedules`) — cron triggers
feeding the JobBackend.

Doc 04, verbatim: "APScheduler's own state is reconstructed from these rows at
boot; this table is authoritative." Taken literally there is no second registry
to reconstruct — this module reads `schedules` on every tick and enqueues what
is ripe. APScheduler contributes `CronTrigger` and nothing else: cron parsing
and DST-correct next-fire arithmetic, the one part of scheduling that must
never be hand-rolled. Its BaseScheduler/AsyncIOScheduler/jobstores would be a
second source of truth to reconcile on every CRUD write, which is exactly what
doc 04's sentence rules out.

Docs 02/03/04/09/10 name "APScheduler 4". No 4.x release exists — only
4.0.0a1..a6 (verified against PyPI 2026-08-01) — and doc 03 marks Scheduling
"Provisional (seam: `Scheduler`)", so this ships on the stable 3.11 line. See
docs/notes/phase-7-operate.md.

Failure policy: one malformed row must never stop the other schedules. A row
whose cron/timezone no longer parses, or whose `job_kind` has no registered
handler, is DISABLED with an audit row rather than retried forever or allowed
to raise out of the tick.
"""
from __future__ import annotations

from datetime import datetime, timezone

from apscheduler.triggers.cron import CronTrigger

from proxploy.jobs import HANDLERS
from proxploy.models import Schedule, utcnow
from proxploy.services.audit import write_audit


class BadSchedule(ValueError):
    """Malformed cron expression, unknown timezone, or unregistered job kind."""


def next_fire(cron: str, tz: str, after: datetime) -> datetime:
    """Next firing strictly after `after`. Naive UTC in, naive UTC out.

    Every DateTime column in this codebase is naive UTC (`models.utcnow`);
    CronTrigger needs an aware datetime and hands back an aware one in `tz`.
    Both conversions happen here so no caller ever holds an aware datetime.

    Passing a firing instant as `after` yields the NEXT occurrence, not the
    same one — that property is what stops a tick from re-firing the schedule
    it just fired.
    """
    try:
        trigger = CronTrigger.from_crontab(cron, timezone=tz)
    except (ValueError, KeyError) as e:
        # ValueError: field count / range errors.
        # KeyError: zoneinfo.ZoneInfoNotFoundError subclasses it, so an unknown
        # tz lands here rather than escaping as a 500.
        raise BadSchedule(f"{cron!r} @ {tz!r}: {e}") from e
    # Passing `after` as BOTH previous_fire_time and now forces "strictly
    # after": with previous_fire_time=None, CronTrigger treats `now` as a
    # candidate and returns it right back when it lands exactly on a firing
    # instant — which is exactly the re-fire-every-tick bug this function
    # exists to prevent.
    aware_after = after.replace(tzinfo=timezone.utc)
    nxt = trigger.get_next_fire_time(aware_after, aware_after)
    if nxt is None:
        raise BadSchedule(f"cron {cron!r} has no future firing")
    return nxt.astimezone(timezone.utc).replace(tzinfo=None)


def validate(cron: str, tz: str, job_kind: str) -> None:
    """Everything the API must reject at write time. Raises BadSchedule."""
    if job_kind not in HANDLERS:
        raise BadSchedule(f"no job handler registered for kind {job_kind!r}")
    next_fire(cron, tz, utcnow())


def _target(params: dict | None) -> tuple[str, int | None]:
    """Job target from the schedule's params, so a scheduled run invalidates
    the same UI caches an ad-hoc one does (doc 05 §Streaming: the `job` delta
    carries `target_type`, and api/live.ts routes on it)."""
    params = params or {}
    for key, kind in (("app_id", "app"), ("vm_id", "vm"), ("host_id", "host")):
        if params.get(key) is not None:
            return kind, int(params[key])
    return "system", None


def _disable(db, s: Schedule, reason: str) -> None:
    s.enabled = False
    s.next_run_at = None
    db.commit()
    write_audit(db, actor_type="system", action="schedule.disable",
                target_type="schedule", target_id=s.id, result="error",
                params={"name": s.name, "reason": reason})


def prime(db, now: datetime) -> int:
    """Give every enabled schedule a `next_run_at`. Returns how many were set.

    Called at boot and at the top of every tick, so a row created directly in
    the DB (or one whose next_run_at was cleared) starts firing without a
    restart. Rows that already have a next_run_at are never recomputed here —
    that would move a schedule's firing time on every tick.
    """
    primed = 0
    rows = (db.query(Schedule)
            .filter(Schedule.enabled.is_(True), Schedule.next_run_at.is_(None))
            .all())
    for s in rows:
        try:
            s.next_run_at = next_fire(s.cron, s.timezone, now)
        except BadSchedule as e:
            _disable(db, s, str(e))
            continue
        primed += 1
    db.commit()
    return primed


def due(db, now: datetime) -> list[Schedule]:
    """Enabled, primed, and ripe — oldest first so a backlog fires in order."""
    return (db.query(Schedule)
            .filter(Schedule.enabled.is_(True),
                    Schedule.next_run_at.is_not(None),
                    Schedule.next_run_at <= now)
            .order_by(Schedule.next_run_at, Schedule.id)
            .all())


def fire_one(app, db, s: Schedule, now: datetime) -> dict | None:
    """Enqueue one schedule's job and advance the row. None if it was disabled.

    `next_run_at` advances from `now`, NOT from the stale `next_run_at`: after
    a week of downtime the schedule owes exactly one catch-up run, not one per
    missed occurrence. Skipped occurrences are visible as the gap in the job
    history, which is the honest record.
    """
    params = dict(s.params or {})
    target_type, target_id = _target(params)
    try:
        job = app.state.jobs.enqueue(
            db, kind=s.job_kind, target_type=target_type, target_id=target_id,
            params=params, requested_by=None, schedule_id=s.id)
    except KeyError as e:
        # JobBackend.enqueue raises this for an unregistered kind — a job kind
        # can genuinely disappear across an upgrade, and retrying it every tick
        # forever would be the wrong answer.
        _disable(db, s, f"no handler for job kind {s.job_kind!r}: {e}")
        return None

    s.last_run_at = now
    try:
        s.next_run_at = next_fire(s.cron, s.timezone, now)
    except BadSchedule as e:
        # The job is already enqueued and stays enqueued; only the schedule
        # stops. Disabling here still leaves the audit trail below unwritten,
        # so write it first.
        write_audit(db, actor_type="system", action="schedule.fire",
                    target_type="schedule", target_id=s.id, job_id=job.id,
                    params={"name": s.name, "job_kind": s.job_kind})
        _disable(db, s, str(e))
        return {"schedule_id": s.id, "job_id": job.id, "kind": s.job_kind}
    db.commit()
    write_audit(db, actor_type="system", action="schedule.fire",
                target_type="schedule", target_id=s.id, job_id=job.id,
                params={"name": s.name, "job_kind": s.job_kind})
    return {"schedule_id": s.id, "job_id": job.id, "kind": s.job_kind}


def tick(app, now: datetime | None = None) -> list[dict]:
    """One full pass: prime, select, fire. Blocking — runs in a worker thread.

    `JobBackend.enqueue` is explicitly safe from FastAPI's threadpool (it hops
    to the loop via `call_soon_threadsafe`), which is the same contract this
    relies on.
    """
    now = now or utcnow()
    fired: list[dict] = []
    with app.state.sessionmaker() as db:
        prime(db, now)
        for s in due(db, now):
            out = fire_one(app, db, s, now)
            if out is not None:
                fired.append(out)
    return fired
