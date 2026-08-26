"""Alert rules and fired alerts (doc 05 §Alerts).

Validation is the substance: the worst failure mode is a rule that looks
configured but can never fire, so every combination the evaluator cannot
answer is a 422 at write time. `GET /alert-rules/metrics` serves the metric
enum so the frontend doesn't hard-code a second copy that can drift.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from proxploy.api.deps import authorize, get_db, require_entitlement
from proxploy.models import (Alert, AlertRule, App, Host, NotificationChannel,
                             User, Vm, to_iso, utcnow)
from proxploy.services.alerts import METRIC_TARGETS, STATUS_METRICS
from proxploy.services.audit import write_audit

router = APIRouter(tags=["alerts"])

_read = authorize("alert", "read")
_ack = authorize("alert", "ack")
_manage = authorize("alert", "manage")

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
                                 f"{', '.join(allowed)}; not {target_type!r}")
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


@router.get("/alert-rules/metrics",
            dependencies=[Depends(_read),
                          Depends(require_entitlement("alerts.rules"))])
def list_metrics(user: User = Depends(_read)):
    """One source of truth for the metric enum: the rule form renders this."""
    return {"metrics": [
        {"metric": m, "targets": list(targets),
         "needs_threshold": m not in STATUS_METRICS}
        for m, targets in METRIC_TARGETS.items()]}


@router.get("/alert-rules",
            dependencies=[Depends(_read),
                          Depends(require_entitlement("alerts.rules"))])
def list_rules(db=Depends(get_db), user: User = Depends(_read)):
    return [_rule_out(r) for r in db.query(AlertRule).order_by(AlertRule.id).all()]


@router.post("/alert-rules", status_code=201,
             dependencies=[Depends(_manage),
                           Depends(require_entitlement("alerts.rules"))])
def create_rule(request: Request, body: RuleIn, db=Depends(get_db),
                user: User = Depends(_manage)):
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
              dependencies=[Depends(_manage),
                            Depends(require_entitlement("alerts.rules"))])
def patch_rule(request: Request, rule_id: int, body: RulePatch,
               db=Depends(get_db), user: User = Depends(_manage)):
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
               dependencies=[Depends(_manage),
                             Depends(require_entitlement("alerts.rules"))])
def delete_rule(request: Request, rule_id: int, db=Depends(get_db),
                user: User = Depends(_manage)):
    row = db.get(AlertRule, rule_id)
    if row is None:
        raise HTTPException(404, "alert rule not found")
    name = row.name
    # alerts.rule_id is ON DELETE CASCADE (migration 0001), but SQLite only
    # honours that with PRAGMA foreign_keys ON: delete the children explicitly
    # so the behaviour is identical on both target databases.
    db.query(Alert).filter(Alert.rule_id == rule_id).delete(
        synchronize_session=False)
    db.delete(row)
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id,
                action="alert.rule.delete", target_type="alert_rule",
                target_id=rule_id, params={"name": name}, ip=_ip(request))
    return Response(status_code=204)


ALERTS_MAX = 200


def alert_out(a: Alert, rules: dict, labels: dict, emails: dict) -> dict:
    """One row, fully renderable; rule name, severity and target label are
    joined here so the Alerts table and the bell tray (BellPopover) each need
    exactly one fetch.

    `rules`/`labels`/`emails` are caller-built lookup dicts, so listing N
    alerts is a constant number of queries rather than 3N.
    """
    rule = rules.get(a.rule_id)
    return {
        "id": a.id, "rule_id": a.rule_id,
        "rule_name": rule.name if rule else None,
        "severity": rule.severity if rule else "warning",
        "target_type": a.target_type, "target_id": a.target_id,
        "target_label": labels.get((a.target_type, a.target_id)),
        "state": a.state, "value": a.value, "message": a.message,
        "fired_at": to_iso(a.fired_at),
        "resolved_at": to_iso(a.resolved_at),
        "acked_by": a.acked_by, "acked_by_email": emails.get(a.acked_by),
        "acked_at": to_iso(a.acked_at),
    }


def _lookups(db, rows: list[Alert]) -> tuple[dict, dict, dict]:
    rules = {r.id: r for r in db.query(AlertRule)
             .filter(AlertRule.id.in_({a.rule_id for a in rows})).all()} if rows else {}
    labels: dict[tuple, str] = {}
    for kind, model in TARGET_MODEL.items():
        ids = {a.target_id for a in rows
               if a.target_type == kind and a.target_id is not None}
        if not ids:
            continue
        for row in db.query(model).filter(model.id.in_(ids)).all():
            labels[(kind, row.id)] = row.name
    acked = {a.acked_by for a in rows if a.acked_by}
    emails = {u.id: u.email for u in db.query(User)
              .filter(User.id.in_(acked)).all()} if acked else {}
    return rules, labels, emails


@router.get("/alerts", dependencies=[Depends(_read)])
def list_alerts(state: str | None = None, limit: int = 50, db=Depends(get_db),
                user: User = Depends(_read)):
    """No entitlement gate here on purpose: the bell tray (BellPopover) fetches
    this before entitlements resolve, and the Alerts page is on every tier's
    nav, so a plan flag would 403 both regardless of tier."""
    limit = max(1, min(limit, ALERTS_MAX))
    q = db.query(Alert)
    if state:
        q = q.filter(Alert.state == state)
    rows = q.order_by(Alert.fired_at.desc(), Alert.id.desc()).limit(limit).all()
    rules, labels, emails = _lookups(db, rows)
    return [alert_out(a, rules, labels, emails) for a in rows]


@router.post("/alerts/{alert_id}/ack", dependencies=[Depends(_ack)])
def ack_alert(request: Request, alert_id: int, db=Depends(get_db),
              user: User = Depends(_ack)):
    """Acknowledging silences; it never resolves. The evaluator still flips an
    acked alert to `resolved` on recovery (services/alerts.py); an operator
    saying "I know" must not make the system stop tracking whether it is fixed.
    """
    row = db.get(Alert, alert_id)
    if row is None:
        raise HTTPException(404, "alert not found")
    if row.acked_at is None:
        row.acked_by, row.acked_at = user.id, utcnow()
        db.commit()
        write_audit(db, actor_type="user", actor_id=user.id, action="alert.ack",
                    target_type="alert", target_id=row.id,
                    params={"message": row.message}, ip=_ip(request))
    rules, labels, emails = _lookups(db, [row])
    return alert_out(row, rules, labels, emails)
