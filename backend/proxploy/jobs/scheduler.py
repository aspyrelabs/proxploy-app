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

import asyncio
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


_PREFIX_TARGET = {
    "app": "app", "vm": "vm",
    "backup": "host", "storage": "host", "network": "host", "host": "host",
}


def _target(job_kind: str, params: dict | None) -> tuple[str, int | None]:
    """Job target from the job kind's dotted prefix, so a scheduled run
    invalidates the same UI caches an ad-hoc one does (doc 05 §Streaming: the
    `job` delta carries `target_type`, and api/live.ts routes on it).

    The prefix, not a param key name, is authoritative: `job_kind` is what
    selects the handler (`HANDLERS[job_kind]`), so it cannot disagree with
    itself. Param key names vary per handler — lifecycle's `run_lifecycle`
    reads a bare `target_id` (api/apps.py), `backup.run` reads `host_id` — so
    sniffing keys instead of the prefix silently mis-derives the type for
    whichever handler doesn't use the sniffed name (this broke every
    `app.*`/`vm.*` lifecycle kind before this fix).
    """
    prefix = job_kind.split(".", 1)[0]
    target_type = _PREFIX_TARGET.get(prefix, "system")
    if target_type == "system":
        return "system", None
    params = params or {}
    for key in ("target_id", "app_id", "vm_id", "host_id"):
        if params.get(key) is not None:
            return target_type, int(params[key])
    return target_type, None


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
    """Enqueue one schedule's job and advance the row.

    Returns None ONLY when no job was enqueued at all — `s.job_kind` has no
    registered handler, `app.state.jobs.enqueue` raised, and the row is
    disabled with an audit trail. It does NOT mean "the row was disabled": if
    enqueue succeeds but the schedule's own cron/timezone then breaks on the
    following `next_fire()` call, a job really was created and the caller
    needs its id, so the dict is returned even though the row is also
    disabled in that path (both a `schedule.fire` and a `schedule.disable`
    audit row are written).

    `next_run_at` advances from `now`, NOT from the stale `next_run_at`: after
    a week of downtime the schedule owes exactly one catch-up run, not one per
    missed occurrence. Skipped occurrences are visible as the gap in the job
    history, which is the honest record.
    """
    params = dict(s.params or {})
    target_type, target_id = _target(s.job_kind, params)
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


# --- system schedules -------------------------------------------------------

# Rows Proxploy owns. Seeded by name at boot if absent, never re-created or
# re-enabled once the operator has touched them (see seed_system_schedules).
# `catalog.refresh` is what keeps `apps.update_available` honest — without it
# an auto-update window would never see a new upstream commit.
SYSTEM_SCHEDULES: tuple[dict, ...] = (
    {"name": "Catalog refresh", "job_kind": "catalog.refresh",
     "cron": "0 4 * * *", "timezone": "UTC", "params": {}},
    {"name": "Metrics maintenance", "job_kind": "metrics.maintain",
     "cron": "7 * * * *", "timezone": "UTC", "params": {}},
)


def seed_system_schedules(db) -> int:
    """Insert any missing system schedule. Returns how many were created.

    Keyed on `name`, and deliberately one-way: a system row the operator
    disabled or re-timed stays that way across restarts. Re-enabling here would
    make "stop refreshing the catalog nightly" impossible to express.
    """
    existing = {name for (name,) in db.query(Schedule.name).all()}
    created = 0
    for spec in SYSTEM_SCHEDULES:
        if spec["name"] in existing:
            continue
        db.add(Schedule(enabled=True, created_by=None, **spec))
        created += 1
    if created:
        db.commit()
    return created


# --- the loop ---------------------------------------------------------------

class Scheduler:
    """One tick loop, shaped like pollers.Poller: the supervisor never dies.

    All DB work runs in `asyncio.to_thread` — SQLAlchemy is blocking, and a
    scheduler that stalls the event loop would stall the SSE fanout, the
    pollers and every in-flight job with it.
    """

    def __init__(self, app) -> None:
        self.app = app
        self._stopped = False

    async def run(self) -> None:
        interval = self.app.state.settings.scheduler_tick_s
        while not self._stopped:
            try:
                for entry in await asyncio.to_thread(tick, self.app):
                    self.app.state.bus.publish(
                        "job", {"id": entry["job_id"], "kind": entry["kind"],
                                "status": "queued",
                                "schedule_id": entry["schedule_id"]})
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — one bad tick must not end them all
                pass
            await asyncio.sleep(interval)

    def stop(self) -> None:
        self._stopped = True
