"""Alert rules and fired alerts (doc 05 §Alerts).

The substance here is validation. The worst failure mode in alerting is a rule
that looks configured, sits `enabled`, and can never fire — nobody discovers it
until the outage it was meant to catch. So every combination the evaluator
cannot answer is a 422 at write time: unknown metric, a (metric, target_type)
pair outside services/alerts.py::METRIC_TARGETS, a target id that names
nothing, a channel id that names nothing.

`GET /alert-rules/metrics` exists so the frontend renders the enum from the
backend rather than hard-coding a second copy that can drift.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from proxploy.api.deps import get_db, require_entitlement, require_role
from proxploy.models import (Alert, AlertRule, App, Host, NotificationChannel,
                             User, Vm, utcnow)
from proxploy.services.alerts import METRIC_TARGETS, STATUS_METRICS
from proxploy.services.audit import write_audit

router = APIRouter(tags=["alerts"])

_require_viewer = require_role("viewer")
_require_operator = require_role("operator")
_require_admin = require_role("admin")

OPERATORS = ("gt", "lt")
SEVERITIES = ("info", "warning", "critical")
TARGET_MODEL = {"host": Host, "app": App, "vm": Vm}


class RuleIn(BaseModel):
    name: str
    metric: str
    target_type: str = "any"
    target_id: int | None = None
    operator: str = "gt"
    threshold: float = 0.0
    duration_s: int = 0
    severity: str = "warning"
    channel_ids: list[int] | None = None
    enabled: bool = True


class RulePatch(BaseModel):
    name: str | None = None
    metric: str | None = None
    target_type: str | None = None
    target_id: int | None = None
    operator: str | None = None
    threshold: float | None = None
    duration_s: int | None = None
    severity: str | None = None
    channel_ids: list[int] | None = None
    enabled: bool | None = None


def _rule_out(r: AlertRule) -> dict:
    return {"id": r.id, "name": r.name, "metric": r.metric,
            "target_type": r.target_type, "target_id": r.target_id,
            "operator": r.operator, "threshold": r.threshold,
            "duration_s": r.duration_s, "severity": r.severity,
            "channel_ids": list(r.channel_ids or []), "enabled": r.enabled}


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _validate(db, *, metric: str, target_type: str, target_id: int | None,
              operator: str, duration_s: int, severity: str,
              channel_ids: list[int]) -> None:
    if metric not in METRIC_TARGETS:
        raise HTTPException(422, f"unknown metric {metric!r}; supported: "
                                 f"{', '.join(sorted(METRIC_TARGETS))}")
    allowed = METRIC_TARGETS[metric]
    if target_type != "any" and target_type not in allowed:
        raise HTTPException(422, f"{metric!r} can only target "
                                 f"{', '.join(allowed)} — not {target_type!r}")
    if target_type == "any" and target_id is not None:
        raise HTTPException(422, "target_id must be null when target_type is 'any'")
    if target_type != "any":
        if target_id is None:
            raise HTTPException(422, f"target_id is required for "
                                     f"target_type {target_type!r}")
        model = TARGET_MODEL.get(target_type)
        if model is None:
            raise HTTPException(422, f"unknown target_type {target_type!r}")
        if db.get(model, target_id) is None:
            raise HTTPException(422, f"no {target_type} with id {target_id}")
    if metric not in STATUS_METRICS and operator not in OPERATORS:
        raise HTTPException(422, f"operator must be one of {', '.join(OPERATORS)}")
    if duration_s < 0:
        raise HTTPException(422, "duration_s must not be negative")
    if severity not in SEVERITIES:
        raise HTTPException(422, f"severity must be one of {', '.join(SEVERITIES)}")
    for cid in channel_ids:
        if db.get(NotificationChannel, cid) is None:
            # A rule that fires into a deleted channel notifies nobody and
            # gives no sign of it.
            raise HTTPException(422, f"no notification channel with id {cid}")


# --- rules ------------------------------------------------------------------

@router.get("/alert-rules/metrics",
            dependencies=[Depends(_require_viewer),
                          Depends(require_entitlement("alerts.rules"))])
def list_metrics(user: User = Depends(_require_viewer)):
    """One source of truth for the metric enum — the rule form renders this."""
    return {"metrics": [
        {"metric": m, "targets": list(targets),
         "needs_threshold": m not in STATUS_METRICS}
        for m, targets in METRIC_TARGETS.items()]}


@router.get("/alert-rules",
            dependencies=[Depends(_require_viewer),
                          Depends(require_entitlement("alerts.rules"))])
def list_rules(db=Depends(get_db), user: User = Depends(_require_viewer)):
    return [_rule_out(r) for r in db.query(AlertRule).order_by(AlertRule.id).all()]


@router.post("/alert-rules", status_code=201,
             dependencies=[Depends(_require_admin),
                           Depends(require_entitlement("alerts.rules"))])
def create_rule(request: Request, body: RuleIn, db=Depends(get_db),
                user: User = Depends(_require_admin)):
    channel_ids = body.channel_ids or []
    _validate(db, metric=body.metric, target_type=body.target_type,
              target_id=body.target_id, operator=body.operator,
              duration_s=body.duration_s, severity=body.severity,
              channel_ids=channel_ids)
    row = AlertRule(name=body.name, metric=body.metric,
                    target_type=body.target_type, target_id=body.target_id,
                    operator=body.operator, threshold=body.threshold,
                    duration_s=body.duration_s, severity=body.severity,
                    channel_ids=channel_ids, enabled=body.enabled)
    db.add(row)
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id,
                action="alert.rule.create", target_type="alert_rule",
                target_id=row.id, params=_rule_out(row), ip=_ip(request))
    return _rule_out(row)


@router.patch("/alert-rules/{rule_id}",
              dependencies=[Depends(_require_admin),
                            Depends(require_entitlement("alerts.rules"))])
def patch_rule(request: Request, rule_id: int, body: RulePatch,
               db=Depends(get_db), user: User = Depends(_require_admin)):
    row = db.get(AlertRule, rule_id)
    if row is None:
        raise HTTPException(404, "alert rule not found")
    merged = {**_rule_out(row),
              **{k: v for k, v in body.model_dump(exclude_unset=True).items()}}
    # Revalidate the WHOLE merged rule, not just the changed fields: a PATCH
    # that moves target_type has to be checked against the STORED metric.
    _validate(db, metric=merged["metric"], target_type=merged["target_type"],
              target_id=merged["target_id"], operator=merged["operator"],
              duration_s=merged["duration_s"], severity=merged["severity"],
              channel_ids=merged["channel_ids"] or [])
    for field in ("name", "metric", "target_type", "target_id", "operator",
                  "threshold", "duration_s", "severity", "enabled"):
        setattr(row, field, merged[field])
    row.channel_ids = merged["channel_ids"] or []
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id,
                action="alert.rule.update", target_type="alert_rule",
                target_id=row.id, params=_rule_out(row), ip=_ip(request))
    return _rule_out(row)


@router.delete("/alert-rules/{rule_id}", status_code=204,
               dependencies=[Depends(_require_admin),
                             Depends(require_entitlement("alerts.rules"))])
def delete_rule(request: Request, rule_id: int, db=Depends(get_db),
                user: User = Depends(_require_admin)):
    row = db.get(AlertRule, rule_id)
    if row is None:
        raise HTTPException(404, "alert rule not found")
    name = row.name
    # alerts.rule_id is ON DELETE CASCADE (migration 0001), but SQLite only
    # honours that with PRAGMA foreign_keys ON — delete the children explicitly
    # so the behaviour is identical on both target databases.
    db.query(Alert).filter(Alert.rule_id == rule_id).delete(
        synchronize_session=False)
    db.delete(row)
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id,
                action="alert.rule.delete", target_type="alert_rule",
                target_id=rule_id, params={"name": name}, ip=_ip(request))
    return Response(status_code=204)
