"""Metrics range query (doc 05): series for uPlot, raw vs rollup by range."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from proxploy.api.deps import authorize, get_db
from proxploy.models import User, utcnow
from proxploy.services.metrics import METRICS, pick_resolution, query_series

router = APIRouter(prefix="/metrics", tags=["metrics"])

_read = authorize("metric", "read")

TARGET_TYPES = ("host", "app", "vm")


def _parse_ts(raw: str) -> datetime:
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(422, f"bad timestamp {raw!r}")
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


@router.get("/query")
def metrics_query(request: Request, target: str, metric: str,
                  frm: str | None = Query(None, alias="from"),
                  to: str | None = None, resolution: str | None = None,
                  db=Depends(get_db),
                  user: User = Depends(_read)):
    try:
        ttype, raw_id = target.split(":", 1)
        tid = int(raw_id)
    except ValueError:
        raise HTTPException(422, "target must look like host:1 / app:3 / vm:2")
    if ttype not in TARGET_TYPES:
        raise HTTPException(422, f"unknown target type {ttype!r}")
    if metric not in METRICS:
        raise HTTPException(422, f"unknown metric {metric!r}")
    if resolution is not None and resolution not in ("raw", "5m", "1h"):
        raise HTTPException(422, "resolution must be raw|5m|1h")

    now = utcnow()
    to_dt = _parse_ts(to) if to else now
    frm_dt = _parse_ts(frm) if frm else to_dt - timedelta(hours=1)
    if frm_dt >= to_dt:
        raise HTTPException(422, "from must be before to")

    # metrics.history gates only the deep past (doc 05) — inline conditional
    # check, hosts.multi precedent
    if (frm_dt < now - timedelta(hours=48)
            and not request.app.state.entitlements.enabled("metrics.history")):
        raise HTTPException(403, {"error": "entitlement_required",
                                  "feature": "metrics.history"})

    res = resolution or pick_resolution(frm_dt, to_dt)
    out = query_series(db, ttype, tid, metric, frm_dt, to_dt, res)
    return {"target": target, "metric": metric, **out}
