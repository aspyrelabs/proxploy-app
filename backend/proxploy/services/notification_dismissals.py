"""Per-user persistence for the bell tray's job-backed notifications (see
components/BellPopover.tsx).

Only /jobs rows need this. The tray's other source -- notify.tsx's action
toasts, and an SSE job/alert event the next /jobs poll hasn't confirmed yet
(lib/notificationStore.ts) -- lives in the browser only and is already gone
on reload; there is nothing there for the server to remember.

Same self-service idiom as api/apikeys.py and auth.py's session routes: no
authorize() call, no services/authz.py PERMISSIONS entry. Reading and
writing your own dismissed-notification state isn't a role question, it's
scoped by user_id the way a session or an api key is.
"""
from __future__ import annotations

from proxploy.models import NotificationDismissal


def _row(db, user_id: int) -> NotificationDismissal | None:
    return db.query(NotificationDismissal).filter_by(user_id=user_id).one_or_none()


def get_state(db, user_id: int) -> dict:
    row = _row(db, user_id)
    if row is None:
        return {"cleared_through_job_id": None, "dismissed_job_ids": []}
    return {"cleared_through_job_id": row.cleared_through_job_id,
            "dismissed_job_ids": list(row.dismissed_job_ids or [])}


def clear_all(db, user_id: int, through_job_id: int) -> dict:
    """Moves the watermark forward only, never back: a slow tab's clear-all
    landing after a faster tab's must not un-cover jobs the faster one
    already covered. Every individually dismissed id at or below the new
    watermark is pruned in the same write -- the watermark already covers
    it, so keeping it around would only let the list grow forever."""
    row = _row(db, user_id)
    if row is None:
        row = NotificationDismissal(user_id=user_id,
                                    cleared_through_job_id=through_job_id,
                                    dismissed_job_ids=[])
        db.add(row)
    else:
        row.cleared_through_job_id = max(row.cleared_through_job_id or 0, through_job_id)
        row.dismissed_job_ids = [i for i in (row.dismissed_job_ids or [])
                                 if i > row.cleared_through_job_id]
    db.commit()
    return get_state(db, user_id)


def dismiss_job(db, user_id: int, job_id: int) -> dict:
    """A job at or below the existing watermark is already dismissed by
    that watermark, so it is not added to the list -- this is the other
    half of what keeps dismissed_job_ids bounded."""
    row = _row(db, user_id)
    if row is None:
        row = NotificationDismissal(user_id=user_id, cleared_through_job_id=None,
                                    dismissed_job_ids=[])
        db.add(row)
        db.flush()
    watermark = row.cleared_through_job_id or 0
    if job_id > watermark and job_id not in (row.dismissed_job_ids or []):
        row.dismissed_job_ids = [*(row.dismissed_job_ids or []), job_id]
    db.commit()
    return get_state(db, user_id)
