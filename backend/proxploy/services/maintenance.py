from __future__ import annotations

import asyncio
import os
from datetime import timedelta

from sqlalchemy import or_

import proxploy
from proxploy.jobs import HANDLERS
from proxploy.models import ConsoleTicket, Job, JobEvent, SessionRow, TrustedDevice, utcnow
from proxploy.services import updater

JOB_PRUNE_BATCH = 500
MIN_KEEP_DAYS = 7
DEFAULT_KEEP_DAYS = 90


def _cleanup_sessions(db) -> dict:
    now = utcnow()
    n_sessions = (db.query(SessionRow)
                  .filter(or_(SessionRow.revoked_at.is_not(None),
                              SessionRow.expires_at < now))
                  .delete(synchronize_session=False))
    n_devices = (db.query(TrustedDevice)
                 .filter(or_(TrustedDevice.revoked_at.is_not(None),
                             TrustedDevice.expires_at < now))
                 .delete(synchronize_session=False))
    n_tickets = (db.query(ConsoleTicket)
                 .filter(or_(ConsoleTicket.redeemed_at.is_not(None),
                             ConsoleTicket.expires_at < now))
                 .delete(synchronize_session=False))
    db.commit()
    return {"sessions": n_sessions, "trusted_devices": n_devices,
            "console_tickets": n_tickets}


async def cleanup_sessions(ctx, params: dict) -> dict:
    app = ctx.backend.app

    def work() -> dict:
        with app.state.sessionmaker() as db:
            return _cleanup_sessions(db)

    ctx.log("deleting dead sessions, trusted devices, and console tickets")
    deleted = await asyncio.to_thread(work)
    ctx.log(f"deleted sessions={deleted['sessions']} "
            f"trusted_devices={deleted['trusted_devices']} "
            f"console_tickets={deleted['console_tickets']}")
    ctx.progress(100)
    return {"deleted": deleted}


HANDLERS["sessions.cleanup"] = cleanup_sessions


def _prune_jobs(db, cutoff) -> dict:
    deleted_jobs = 0
    deleted_events = 0
    while True:
        ids = [jid for (jid,) in db.query(Job.id)
               .filter(Job.created_at < cutoff)
               .limit(JOB_PRUNE_BATCH).all()]
        if not ids:
            break
        deleted_events += (db.query(JobEvent)
                           .filter(JobEvent.job_id.in_(ids))
                           .delete(synchronize_session=False))
        deleted_jobs += (db.query(Job)
                         .filter(Job.id.in_(ids))
                         .delete(synchronize_session=False))
        db.commit()
    return {"jobs": deleted_jobs, "job_events": deleted_events}


async def prune_jobs(ctx, params: dict) -> dict:
    app = ctx.backend.app
    keep_days = max(MIN_KEEP_DAYS, int(params.get("keep_days", DEFAULT_KEEP_DAYS)))

    def work() -> dict:
        with app.state.sessionmaker() as db:
            cutoff = utcnow() - timedelta(days=keep_days)
            return _prune_jobs(db, cutoff)

    ctx.log(f"pruning job history older than {keep_days} days")
    deleted = await asyncio.to_thread(work)
    ctx.log(f"deleted jobs={deleted['jobs']} job_events={deleted['job_events']}")
    ctx.progress(100)
    return {"kept_days": keep_days, "deleted": deleted}


HANDLERS["jobs.prune"] = prune_jobs


def _compact(app) -> dict:
    dialect = app.state.engine.dialect.name
    out: dict = {"dialect": dialect, "ran": []}
    if dialect == "sqlite":
        path = app.state.engine.url.database
        before = os.path.getsize(path) if path and os.path.exists(path) else None
        conn = app.state.engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        try:
            conn.exec_driver_sql("VACUUM")
            out["ran"].append("VACUUM")
            conn.exec_driver_sql("PRAGMA optimize")
            out["ran"].append("PRAGMA optimize")
        finally:
            conn.close()
        after = os.path.getsize(path) if path and os.path.exists(path) else None
        out["bytes_before"] = before
        out["bytes_after"] = after
    else:
        conn = app.state.engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        try:
            conn.exec_driver_sql("ANALYZE")
            out["ran"].append("ANALYZE")
        finally:
            conn.close()
        out["note"] = "a full vacuum is left to the database server"
    return out


async def compact_db(ctx, params: dict) -> dict:
    app = ctx.backend.app
    ctx.log(f"compacting the {app.state.engine.dialect.name} database")
    out = await asyncio.to_thread(_compact, app)
    ctx.log(f"ran {', '.join(out['ran']) or 'nothing'}")
    ctx.progress(100)
    return out


HANDLERS["db.compact"] = compact_db


async def check_update(ctx, params: dict) -> dict:
    app = ctx.backend.app
    settings = app.state.settings
    if not app.state.entitlements.enabled("platform.self_update"):
        ctx.log("update checks are not included in the current plan")
        ctx.progress(100)
        return {"current": proxploy.__version__, "latest": None,
                "update_available": False, "notified": False, "error": None,
                "message": "Update checks are not included in your current plan."}

    ctx.log("checking the release channel for a newer version")
    status = await asyncio.to_thread(updater.check, settings)
    out = {"current": status["current"], "latest": status["latest"],
           "update_available": status["update_available"], "notified": False,
           "error": status["error"]}
    if status["error"]:
        ctx.log(f"update check failed: {status['error']}")
        ctx.progress(100)
        return out
    if not status["update_available"]:
        ctx.log("already up to date")
        ctx.progress(100)
        return out

    ctx.log(f"update available: {status['current']} -> {status['latest']}")
    app.state.bus.publish("update", {"current": status["current"],
                                     "latest": status["latest"],
                                     "notes_url": status.get("notes_url")})

    def send() -> int:
        from proxploy.services.links import absolute
        from proxploy.services.notification_body import compose
        from proxploy.services.notifier import notify

        with app.state.sessionmaker() as db:
            link = absolute(db, "/settings?section=updates")
        body = compose([("Current version", status["current"]),
                        ("Latest version", status["latest"])],
                       "A newer version of Proxploy is available.", link=link)
        return notify(app, "update.available",
                      f"Proxploy: update available ({status['latest']})", body)

    reached = await asyncio.to_thread(send)
    out["notified"] = reached > 0
    ctx.progress(100)
    return out


HANDLERS["update.check"] = check_update
