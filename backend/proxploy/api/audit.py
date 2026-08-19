import csv
import io
import json
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from sqlalchemy import and_, func, or_

from proxploy.api.deps import authorize, get_db, require_entitlement
from proxploy.models import (AlertRule, ApiKey, App, AuditEvent, Backup, Host,
                             NotificationChannel, Schedule, Team, User, Vm, to_iso)
from proxploy.services.audit import write_audit

EXPORT_COLUMNS = ("id", "ts", "actor_type", "actor_id", "action", "target_type",
                  "target_id", "params", "result", "ip", "job_id")

# target_type -> (model, the column that holds its human name). One map, used
# both to label a row's Item column and to turn the "item or action" search box
# back into ids, so the box can never match an item the column does not name.
#
# Deliberately no "storage": those rows carry the HOST's id in target_id
# (api/storage.py), so labelling them from either table would print a name that
# is wrong or right by accident. Same reason "job", "session", "alert" and
# "system" are absent: nothing there is a name a person would recognise.
TARGET_LABELS = {
    "host": (Host, Host.name),
    "app": (App, App.name),
    "vm": (Vm, Vm.name),
    "user": (User, User.email),
    "team": (Team, Team.name),
    "schedule": (Schedule, Schedule.name),
    "notification_channel": (NotificationChannel, NotificationChannel.name),
    "alert_rule": (AlertRule, AlertRule.name),
    "backup": (Backup, Backup.volid),
}


def _search_clause(db, search: str):
    """Match the stored action OR the item the row is about.

    Substring and case-insensitive, not exact: this is ONE box on the screen,
    and typing "pve-lab" into it and getting nothing back because no action is
    literally named that would read as a broken filter. The older `action=`
    parameter stays exact and untouched; the CLI (`proxploy audit export
    --action app.stop`) and anyone scripting the export depend on it.

    Names are resolved to ids first, one query per target kind, so this is a
    fixed handful of lookups per request rather than a join against nine tables.
    """
    like = f"%{search.lower()}%"
    clauses = [func.lower(AuditEvent.action).like(like),
               func.lower(AuditEvent.target_type).like(like)]
    for kind, (model, name_col) in TARGET_LABELS.items():
        ids = [i for (i,) in db.query(model.id)
               .filter(func.lower(name_col).like(like)).all()]
        if ids:
            clauses.append(and_(AuditEvent.target_type == kind,
                                AuditEvent.target_id.in_(ids)))
    return or_(*clauses)


def _filtered(db, action, actor, from_, to, *, actor_type=None, search=None):
    """The one filter definition, shared by the viewer and the export.

    An export that answers a different question than the list above it is
    worse than no export: someone hands the file to an auditor believing it
    matches what they were looking at.

    `actor_type` and `search` are keyword-only so cli.py's positional call
    keeps working: the CLI has its own smaller flag set on purpose.
    """
    q = db.query(AuditEvent)
    if action:
        q = q.filter(AuditEvent.action == action)
    if actor is not None:
        q = q.filter(AuditEvent.actor_id == actor)
    if actor_type:
        # "Performed by" can name the scheduler as well as a person, and every
        # system row has actor_id NULL, so an id filter alone cannot reach them.
        q = q.filter(AuditEvent.actor_type == actor_type)
    if search:
        q = q.filter(_search_clause(db, search))
    if from_:
        q = q.filter(AuditEvent.ts >= from_)
    if to:
        q = q.filter(AuditEvent.ts <= to)
    return q


def _labels(db, rows: list[AuditEvent]) -> tuple[dict, dict]:
    """Caller-built lookups, keyed (type, id), the same shape and for the same
    reason as api/alerts.py::_lookups: labelling a 50 row page has to be a
    handful of queries, not one per row. A kind absent from the page is never
    queried at all.
    """
    items: dict[tuple, str] = {}
    for kind, (model, name_col) in TARGET_LABELS.items():
        ids = {r.target_id for r in rows
               if r.target_type == kind and r.target_id is not None}
        if not ids:
            continue
        for rid, name in db.query(model.id, name_col).filter(model.id.in_(ids)):
            items[(kind, rid)] = name

    actors: dict[tuple, str] = {}
    uids = {r.actor_id for r in rows
            if r.actor_type == "user" and r.actor_id is not None}
    if uids:
        for u in db.query(User).filter(User.id.in_(uids)):
            actors[("user", u.id)] = u.display_name or u.email
    kids = {r.actor_id for r in rows
            if r.actor_type == "api_key" and r.actor_id is not None}
    if kids:
        for k in db.query(ApiKey).filter(ApiKey.id.in_(kids)):
            actors[("api_key", k.id)] = k.name
    return actors, items


def row_dict(r: AuditEvent, actors: dict | None = None,
             items: dict | None = None) -> dict:
    d = {"id": r.id, "ts": to_iso(r.ts), "actor_type": r.actor_type,
         "actor_id": r.actor_id, "action": r.action,
         "target_type": r.target_type, "target_id": r.target_id,
         "params": r.params, "result": r.result, "ip": r.ip,
         "job_id": r.job_id}
    if actors is not None:
        # Screen-only additions, and only when the caller asked: EXPORT_COLUMNS
        # is a machine-readable contract with tests behind it, and the JSONL
        # export writes whatever this function returns, so two extra keys there
        # would change a file someone else already parses. Either label is None
        # when nothing answers to that id, which is the deleted-host case: the
        # row still lists, reading "host #2".
        d["actor_label"] = actors.get((r.actor_type, r.actor_id))
        d["target_label"] = (items or {}).get((r.target_type, r.target_id))
    return d

router = APIRouter(prefix="/audit", tags=["audit"])

_read = authorize("audit", "read")
# Owner, the same floor host.remove and vm.remove sit at (services/authz.py).
_clear = authorize("audit", "clear")

# Typed back before anything is deleted, exactly like the app uninstall and the
# in-place restore (api/apps.py, api/backups.py). Fixed text rather than a
# resource name because the audit log has no name to type.
CLEAR_PHRASE = "clear audit log"


# `_read` first, then the entitlement: a bare require_entitlement in this list
# would land at position 0 and 403 an anonymous caller, leaking which flags are
# armed. See tests/test_route_auth_invariant.py.
#
# doc 01 lists this route as gated on `audit.log`, and until now only RBAC was
# enforced, so the documented control did not exist. It costs nothing to arm
# today (tiers.yaml keeps all_entitled) and stops the docs describing a gate
# that isn't there.
AUDIT_PAGE_MAX = 200


@router.get("", dependencies=[Depends(_read),
                              Depends(require_entitlement("audit.log"))])
def list_audit(response: Response, db=Depends(get_db), action: str | None = None,
               actor: int | None = None, actor_type: str | None = None,
               search: str | None = None, from_: datetime | None = None,
               to: datetime | None = None, page: int = 1, per_page: int = 50):
    # Same clamp the other paged reads use (alerts.py, cluster.py). Unbounded,
    # per_page=100000000 turns the append-only audit table into one response,
    # and page=0 asks SQLite for OFFSET -50.
    page, per_page = max(1, page), max(1, min(per_page, AUDIT_PAGE_MAX))
    q = _filtered(db, action, actor, from_, to, actor_type=actor_type,
                  search=search)
    response.headers["X-Total-Count"] = str(q.count())
    rows = (q.order_by(AuditEvent.ts.desc(), AuditEvent.id.desc())
            .offset((page - 1) * per_page).limit(per_page).all())
    actors, items = _labels(db, rows)
    return [row_dict(r, actors, items) for r in rows]


@router.get("/export", dependencies=[Depends(_read),
                                     Depends(require_entitlement("audit.log"))])
def export_audit(db=Depends(get_db), format: str = "csv",
                 action: str | None = None, actor: int | None = None,
                 actor_type: str | None = None, search: str | None = None,
                 from_: datetime | None = None, to: datetime | None = None):
    """The export half of doc 01's audit row and docs 04/05's audit export.

    Streams and is deliberately NOT paginated: an audit export that stops at
    page one is a trap; someone hands the file over believing it is complete.
    `yield_per` keeps a multi-year table off the heap while doing it.

    Registered before the `/{...}`-free list route is irrelevant, but it MUST
    stay a literal segment: there is no /audit/{id} route today and adding one
    later would shadow this unless it is declared after.
    """
    if format not in ("csv", "jsonl"):
        from fastapi import HTTPException
        raise HTTPException(422, "format must be csv or jsonl")

    q = (_filtered(db, action, actor, from_, to, actor_type=actor_type,
                   search=search)
         .order_by(AuditEvent.ts.desc(), AuditEvent.id.desc()))

    def rows():
        return q.yield_per(500)

    if format == "jsonl":
        def jsonl():
            for r in rows():
                yield json.dumps(row_dict(r)) + "\n"
        return StreamingResponse(
            jsonl(), media_type="application/x-ndjson",
            headers={"Content-Disposition": 'attachment; filename="audit.jsonl"'})

    def csv_stream():
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS, extrasaction="ignore")
        w.writeheader()
        yield buf.getvalue()
        for r in rows():
            buf.seek(0), buf.truncate(0)
            d = row_dict(r)
            # params is a dict; a bare str() would emit Python repr with single
            # quotes, which is not JSON and not reliably re-parseable.
            d["params"] = json.dumps(d["params"]) if d["params"] is not None else ""
            w.writerow(d)
            yield buf.getvalue()

    return StreamingResponse(
        csv_stream(), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="audit.csv"'})


class ClearIn(BaseModel):
    """`before` clears entries older than that instant; omitted clears the lot.

    Deliberately NOT tied to whatever the table is filtered to. "Clear what I
    am looking at" stops being unambiguous the moment one of those filters is a
    substring match, and the operator would eventually remove more than they
    meant to and have no way to see what.
    """
    before: datetime | None = None
    confirm: str | None = None


@router.delete("", dependencies=[Depends(_clear),
                                 Depends(require_entitlement("audit.log"))])
def clear_audit(request: Request, body: ClearIn = Body(default=ClearIn()),
                db=Depends(get_db), user: User = Depends(_clear)):
    """Clear the trail, and record who cleared it (doc 08 §7, doc 11).

    This is the one place in the product that deletes audit rows, which is why
    it is owner-only, typed-confirmed, and audited. The audit.clear row is
    written AFTER the delete on purpose: written first it would sit inside the
    range being cleared and go with it, leaving an empty table and no author.

    An operator who wants retention rather than erasure passes `before`, and the
    row says which of the two was used, because "the log was emptied" and "eight
    month old rows were pruned" are not the same event to read later.
    """
    ip = request.client.host if request.client else None
    if (body.confirm or "") != CLEAR_PHRASE:
        write_audit(db, actor_type="user", actor_id=user.id, action="audit.clear",
                    result="denied", ip=ip,
                    params={"before": to_iso(body.before)})
        raise HTTPException(409, {
            "error": "confirm_required", "confirm_phrase": CLEAR_PHRASE,
            "detail": ("Clearing the audit log cannot be undone. Type "
                       f"{CLEAR_PHRASE!r} to confirm."),
        })

    q = db.query(AuditEvent)
    if body.before:
        q = q.filter(AuditEvent.ts < body.before)
    deleted = q.delete(synchronize_session=False)
    db.commit()

    write_audit(db, actor_type="user", actor_id=user.id, action="audit.clear",
                params={"deleted": deleted,
                        "scope": "before" if body.before else "all",
                        "before": to_iso(body.before)}, ip=ip)
    return {"deleted": deleted, "before": to_iso(body.before)}
