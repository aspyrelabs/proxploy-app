from datetime import datetime

from fastapi import APIRouter, Depends, Response

from proxploy.api.deps import authorize, get_db, require_entitlement
from proxploy.models import AuditEvent

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
    q = db.query(AuditEvent)
    if action:
        q = q.filter(AuditEvent.action == action)
    if actor is not None:
        q = q.filter(AuditEvent.actor_id == actor)
    if from_:
        q = q.filter(AuditEvent.ts >= from_)
    if to:
        q = q.filter(AuditEvent.ts <= to)
    response.headers["X-Total-Count"] = str(q.count())
    rows = (q.order_by(AuditEvent.ts.desc(), AuditEvent.id.desc())
            .offset((page - 1) * per_page).limit(per_page))
    return [{"id": r.id, "ts": r.ts.isoformat(), "actor_type": r.actor_type,
             "actor_id": r.actor_id, "action": r.action, "target_type": r.target_type,
             "target_id": r.target_id, "params": r.params, "result": r.result,
             "ip": r.ip, "job_id": r.job_id} for r in rows]
