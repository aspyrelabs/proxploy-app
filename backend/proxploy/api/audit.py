import csv
import io
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse

from proxploy.api.deps import authorize, get_db, require_entitlement
from proxploy.models import AuditEvent

EXPORT_COLUMNS = ("id", "ts", "actor_type", "actor_id", "action", "target_type",
                  "target_id", "params", "result", "ip", "job_id")


def _filtered(db, action, actor, from_, to):
    """The one filter definition, shared by the viewer and the export.

    An export that answers a different question than the list above it is
    worse than no export: someone hands the file to an auditor believing it
    matches what they were looking at.
    """
    q = db.query(AuditEvent)
    if action:
        q = q.filter(AuditEvent.action == action)
    if actor is not None:
        q = q.filter(AuditEvent.actor_id == actor)
    if from_:
        q = q.filter(AuditEvent.ts >= from_)
    if to:
        q = q.filter(AuditEvent.ts <= to)
    return q


def row_dict(r: AuditEvent) -> dict:
    return {"id": r.id, "ts": r.ts.isoformat(), "actor_type": r.actor_type,
            "actor_id": r.actor_id, "action": r.action,
            "target_type": r.target_type, "target_id": r.target_id,
            "params": r.params, "result": r.result, "ip": r.ip,
            "job_id": r.job_id}

router = APIRouter(prefix="/audit", tags=["audit"])

_read = authorize("audit", "read")


# `_read` first, then the entitlement: a bare require_entitlement in this list
# would land at position 0 and 403 an anonymous caller, leaking which flags are
# armed. See tests/test_route_auth_invariant.py.
#
# doc 01 lists this route as gated on `audit.log`, and until now only RBAC was
# enforced, so the documented control did not exist. It costs nothing to arm
# today (tiers.yaml keeps all_entitled) and stops the docs describing a gate
# that isn't there.
@router.get("", dependencies=[Depends(_read),
                              Depends(require_entitlement("audit.log"))])
def list_audit(response: Response, db=Depends(get_db), action: str | None = None,
               actor: int | None = None, from_: datetime | None = None,
               to: datetime | None = None, page: int = 1, per_page: int = 50):
    q = _filtered(db, action, actor, from_, to)
    response.headers["X-Total-Count"] = str(q.count())
    rows = (q.order_by(AuditEvent.ts.desc(), AuditEvent.id.desc())
            .offset((page - 1) * per_page).limit(per_page))
    return [row_dict(r) for r in rows]


@router.get("/export", dependencies=[Depends(_read),
                                     Depends(require_entitlement("audit.log"))])
def export_audit(db=Depends(get_db), format: str = "csv",
                 action: str | None = None, actor: int | None = None,
                 from_: datetime | None = None, to: datetime | None = None):
    """The export half of doc 01's audit row and docs 04/05's audit export.

    Streams and is deliberately NOT paginated: an audit export that stops at
    page one is a trap, someone hands the file over believing it is complete.
    `yield_per` keeps a multi-year table off the heap while doing it.

    Registered before the `/{...}`-free list route is irrelevant, but it MUST
    stay a literal segment: there is no /audit/{id} route today and adding one
    later would shadow this unless it is declared after.
    """
    if format not in ("csv", "jsonl"):
        from fastapi import HTTPException
        raise HTTPException(422, "format must be csv or jsonl")

    q = (_filtered(db, action, actor, from_, to)
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
