"""Scheduler seam: cron triggers feeding the JobBackend. This module reads
`schedules` on every tick and enqueues what is ripe; APScheduler contributes
only `CronTrigger` (cron parsing + DST-correct next-fire arithmetic), not a
second registry to reconcile on CRUD writes. Ships on the stable 3.11 line
(there is no "APScheduler 4" release).

Failure policy: one malformed row must never stop the other schedules — a row
whose cron/timezone no longer parses, or whose `job_kind` has no handler, is
DISABLED with an audit row rather than retried forever.
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
    same one, that property is what stops a tick from re-firing the schedule
    it just fired.
    """
    try:
        trigger = CronTrigger.from_crontab(cron, timezone=tz)
    except (ValueError, KeyError) as e:
        # KeyError also catches zoneinfo.ZoneInfoNotFoundError (it subclasses
        # KeyError), so an unknown tz lands here rather than escaping as a 500.
        raise BadSchedule(f"{cron!r} @ {tz!r}: {e}") from e
    # Passing `after` as BOTH previous_fire_time and now forces "strictly
    # after": with previous_fire_time=None, CronTrigger treats `now` as a
    # candidate and returns it right back when it lands exactly on a firing
    # instant: which is exactly the re-fire-every-tick bug this function
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


# Missed means NEVER TRIGGERED, and never by seconds: a firing has to be owed
# for half an hour before this counts it as missed. `due()` cannot tell a row
# owed since last Tuesday from one owed twenty seconds ago, both just have a
# next_run_at in the past, and the tick only looks every `scheduler_tick_s`
# (30s), so a firing is routinely late by a little. Half an hour is long enough
# that nothing but real downtime reaches it.
#
# A job that WAS triggered on time and is still running, or still queued behind
# MAX_CONCURRENT, is not missed and nothing here looks at it: `next_run_at`
# advances at trigger time (jobs/backend.py::enqueue returns without waiting on
# the handler), so an in-flight run cannot make the next occurrence look late.
#
# Only rows with `catch_up: false` in their params consult any of this;
# everything else runs the missed occurrence, which is what Proxploy has
# always done.
MISFIRE_GRACE_S = 1800.0


def job_params(s: Schedule) -> dict:
    """The params a firing actually hands the handler.

    `catch_up` is the scheduler's own flag and no handler's business; stripping
    it here rather than at each call site keeps it out of `jobs.params`, where
    it would show up in the job detail UI as a knob that does nothing.
    """
    params = dict(s.params or {})
    params.pop("catch_up", None)
    return params


_PREFIX_TARGET = {
    "app": "app", "vm": "vm",
    "backup": "host", "storage": "host", "network": "host", "host": "host",
}


def _target(job_kind: str, params: dict | None) -> tuple[str, int | None]:
    """Job target from the job kind's dotted prefix (matching the ad-hoc run's
    `target_type`). The prefix, not a param key, is authoritative: `job_kind`
    selects the handler, and param key names vary per handler, so sniffing
    keys silently mis-derives the type.
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
    """Automatic give-up on a row the scheduler cannot run. `actor_type` and
    this action id are the AUTOMATIC disable only; a person disabling goes
    through api/schedules.py as `schedule.update`.

    `result="ok"`, not "error": `result` is the outcome of THIS action (the
    disable, which succeeded); the schedule's failure is `params["reason"]`.
    """
    s.enabled = False
    s.next_run_at = None
    db.commit()
    write_audit(db, actor_type="system", action="schedule.disable",
                target_type="schedule", target_id=s.id,
                params={"name": s.name, "reason": reason})


def prime(db, now: datetime) -> int:
    """Give every enabled schedule a `next_run_at`. Returns how many were set.

    Called at boot and at the top of every tick, so a row created directly in
    the DB (or one whose next_run_at was cleared) starts firing without a
    restart. Rows that already have a next_run_at are never recomputed here, 
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
    """Enabled, primed, and ripe; oldest first so a backlog fires in order."""
    return (db.query(Schedule)
            .filter(Schedule.enabled.is_(True),
                    Schedule.next_run_at.is_not(None),
                    Schedule.next_run_at <= now)
            .order_by(Schedule.next_run_at, Schedule.id)
            .all())


def fire_one(app, db, s: Schedule, now: datetime) -> dict | None:
    """Enqueue one schedule's job and advance the row. Returns None only when
    no job was enqueued (row disabled); still returns a dict when enqueue
    succeeded but the follow-up `next_fire()` broke (a job really was created).

    Returns None when no job was enqueued: an unregistered kind (the row is
    disabled with an audit trail), or a row that opted out of catch-up runs
    whose firing was late enough to count as missed, where `next_run_at` just
    moves on.

    `next_run_at` advances from `now`, not the stale value: after downtime a
    schedule owes one catch-up run, not one per missed occurrence.
    """
    # A start that never happened, not one serviced a little late. Ticked in
    # the form (and absent from every job saved before this existed) means run
    # it anyway, so the default here is True.
    late = (now - s.next_run_at).total_seconds() if s.next_run_at else 0.0
    if not (s.params or {}).get("catch_up", True) and late > MISFIRE_GRACE_S:
        try:
            s.next_run_at = next_fire(s.cron, s.timezone, now)
        except BadSchedule as e:
            _disable(db, s, str(e))
            return None
        db.commit()
        # Audited, because the alternative is an operator finding no backup and
        # no record of why not.
        write_audit(db, actor_type="system", action="schedule.skip",
                    target_type="schedule", target_id=s.id,
                    params={"name": s.name, "job_kind": s.job_kind,
                            "late_s": int(late)})
        return None

    params = job_params(s)
    target_type, target_id = _target(s.job_kind, params)
    try:
        job = app.state.jobs.enqueue(
            db, kind=s.job_kind, target_type=target_type, target_id=target_id,
            params=params, requested_by=None, schedule_id=s.id)
    except KeyError as e:
        # Unregistered kind (a kind can vanish across an upgrade): disable,
        # don't retry every tick forever.
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
    """One full pass: prime, select, fire. Blocking, runs in a worker thread.

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


# `catalog.refresh` is what keeps `apps.update_available` honest: without it
# an auto-update window would never see a new upstream commit.
SYSTEM_SCHEDULES: tuple[dict, ...] = (
    {"name": "Catalog refresh", "job_kind": "catalog.refresh",
     "cron": "0 */6 * * *", "timezone": "UTC", "params": {}},
    # Do not rename: seed keys on `name` and only inserts, so a rename would
    # seed a SECOND row running the same job kind rather than rename the first.
    {"name": "Usage cleanup", "job_kind": "metrics.maintain",
     "cron": "7 * * * *", "timezone": "UTC", "params": {}},
    {"name": "Session cleanup", "job_kind": "sessions.cleanup",
     "cron": "15 3 * * *", "timezone": "UTC", "params": {}},
    {"name": "Job history cleanup", "job_kind": "jobs.prune",
     "cron": "30 3 * * *", "timezone": "UTC", "params": {"keep_days": 90}},
    {"name": "Database compaction", "job_kind": "db.compact",
     "cron": "0 4 * * 0", "timezone": "UTC", "params": {}},
    {"name": "Update check", "job_kind": "update.check",
     "cron": "0 6 * * *", "timezone": "UTC", "params": {}},
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


class Scheduler:
    """One tick loop, shaped like pollers.Poller: the supervisor never dies.

    All DB work runs in `asyncio.to_thread`, SQLAlchemy is blocking, and a
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
            except Exception:  # noqa: BLE001  (one bad tick must not end them all)
                pass
            await asyncio.sleep(interval)

    def stop(self) -> None:
        self._stopped = True
