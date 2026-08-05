"""Alert evaluation (doc 04 `alert_rules` / `alerts`, doc 10 Phase 7).

Reads only the DB. No HTTP, no Apprise, no event bus — it opens and closes
`alerts` rows and returns the TRANSITIONS. Task 10's notifier and Task 11's
poll-loop hook do everything outward-facing, so a change to how alerts are
delivered never touches how they are decided.

Semantics, once, so nothing has to guess:

  * `duration_s` means CONTINUOUSLY breaching for at least that long — the
    doc 04 prototype phrase is "85% CPU for 5 minutes", and a five-minute
    average that dipped to 10% in the middle is not that. Implemented by
    walking samples newest-first and taking the breaching prefix.
  * A rule holds at most ONE open alert per concrete target. A still-breaching
    rule yields no transition, which is what stops a 30 s poll cadence from
    re-notifying twice a minute.
  * Recovery resolves automatically on the first non-breaching cycle. An
    acknowledged alert still resolves — ack silences, it does not pin.
  * No samples is not a breach. Absence of data is not evidence of a problem,
    and a freshly-added host must not alarm on its first cycle.
  * `host_offline` and `backup_failed` have nothing to compare, so they ignore
    `operator` and `threshold`. `duration_s` still applies to `host_offline`
    (via `hosts.last_seen_at`) so a PVE restart blip is not an outage.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from proxploy.models import Alert, AlertRule, App, Host, Job, MetricSample, Vm, utcnow

logger = logging.getLogger(__name__)

# Which target kinds each metric can honestly be evaluated against. `disk_pct`
# is hosts-only: /cluster/resources reports `maxdisk` (allocated, not used) for
# guests and a `disk` figure that is routinely 0 for QEMU, so a guest disk_pct
# would be confidently wrong. api/alerts.py rejects the unsupported pairs at
# rule-creation time rather than accepting a rule that can never fire.
METRIC_TARGETS: dict[str, tuple[str, ...]] = {
    "cpu_pct": ("host", "app", "vm"),
    "mem_pct": ("host", "app", "vm"),
    "disk_pct": ("host",),
    "host_offline": ("host",),
    "backup_failed": ("host",),
}
SUPPORTED_METRICS: tuple[str, ...] = tuple(METRIC_TARGETS)

# Metrics answered from a status column rather than from metric_samples.
STATUS_METRICS = ("host_offline", "backup_failed")

# Extra history fetched beyond `duration_s` so the sample that ESTABLISHES the
# start of a breach is inside the window. Two poll intervals of slack.
_WINDOW_SLACK_S = 120

_METRIC_LABEL = {"cpu_pct": "CPU", "mem_pct": "memory", "disk_pct": "disk",
                 "host_offline": "host", "backup_failed": "backup"}
_OP_LABEL = {"gt": ">", "lt": "<"}


def _human_duration(seconds: int) -> str:
    if seconds <= 0:
        return ""
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def render_message(rule_name: str, label: str, metric: str, operator: str,
                   threshold: float, duration_s: int, value: float | None,
                   state: str) -> str:
    """Doc 05's SSE example: "host-02 CPU > 85% for 5m"."""
    if metric == "host_offline":
        body = f"{label} is offline"
        if duration_s:
            body += f" for {_human_duration(duration_s)}"
    elif metric == "backup_failed":
        body = f"{label}: last backup run failed"
    else:
        unit = "%" if metric.endswith("_pct") else ""
        body = (f"{label} {_METRIC_LABEL.get(metric, metric)} "
                f"{_OP_LABEL.get(operator, operator)} "
                f"{threshold:g}{unit}")
        if duration_s:
            body += f" for {_human_duration(duration_s)}"
        if value is not None:
            body += f" (now {value:g}{unit})"
    return f"Resolved: {body}" if state == "resolved" else body


def targets_for(db, rule: AlertRule) -> list[tuple[str, int, str]]:
    """Concrete `(target_type, target_id, label)` triples this rule covers.

    `target_type == "any"` expands across every target kind the metric supports
    (doc 04: "`host` | `app` | `vm` | `any`", target_id NULL when any).
    """
    kinds = METRIC_TARGETS.get(rule.metric, ())
    if rule.target_type != "any":
        if rule.target_type not in kinds:
            return []
        label = _label(db, rule.target_type, rule.target_id)
        # A rule pointing at a deleted host/app/vm is skipped, not crashed —
        # nothing cascades alert_rules on target deletion.
        return [] if label is None else [(rule.target_type, rule.target_id, label)]

    out: list[tuple[str, int, str]] = []
    if "host" in kinds:
        out += [("host", h.id, h.name) for h in db.query(Host).all()]
    if "app" in kinds:
        out += [("app", a.id, a.name) for a in db.query(App).all()]
    if "vm" in kinds:
        out += [("vm", v.id, v.name) for v in db.query(Vm).all()]
    return out


def _label(db, target_type: str, target_id: int | None) -> str | None:
    if target_id is None:
        return None
    model = {"host": Host, "app": App, "vm": Vm}.get(target_type)
    row = db.get(model, target_id) if model else None
    return row.name if row is not None else None


def _breaches(value: float, operator: str, threshold: float) -> bool:
    return value > threshold if operator == "gt" else value < threshold


def _metric_state(db, rule: AlertRule, target_type: str, target_id: int,
                  now: datetime) -> tuple[bool, float | None]:
    """(breaching for long enough, newest observed value) from metric_samples.

    Walks newest-first and takes the breaching prefix; the rule fires when the
    oldest sample of that prefix is at least `duration_s` old. That is what
    "held for 5 minutes" means, and it is why a single dip resets the clock.
    """
    since = now - timedelta(seconds=rule.duration_s + _WINDOW_SLACK_S)
    rows = (db.query(MetricSample)
            .filter(MetricSample.target_type == target_type,
                    MetricSample.target_id == target_id,
                    MetricSample.metric == rule.metric,
                    MetricSample.ts >= since, MetricSample.ts <= now)
            .order_by(MetricSample.ts.desc())
            .all())
    if not rows:
        return False, None                      # no data is not a breach
    newest = rows[0].value
    prefix_start = None
    for row in rows:
        if not _breaches(row.value, rule.operator, rule.threshold):
            break
        prefix_start = row.ts
    if prefix_start is None:
        return False, newest
    held = (now - prefix_start).total_seconds()
    return held >= rule.duration_s, newest


def _status_state(db, rule: AlertRule, target_id: int,
                  now: datetime) -> tuple[bool, float | None]:
    if rule.metric == "host_offline":
        host = db.get(Host, target_id)
        if host is None or host.status == "connected":
            return False, 0.0
        # A PVE restart blips `unreachable` for one cycle; duration_s is how an
        # operator says "only tell me if it stays down".
        if rule.duration_s and host.last_seen_at is not None:
            down_for = (now - host.last_seen_at).total_seconds()
            if down_for < rule.duration_s:
                return False, 1.0
        return True, 1.0

    # backup_failed — only the LATEST finished backup.run for this host counts.
    # An old failure that has since been fixed is not a live alert.
    latest = (db.query(Job)
              .filter(Job.kind == "backup.run", Job.target_type == "host",
                      Job.target_id == target_id, Job.finished_at.is_not(None))
              .order_by(Job.finished_at.desc(), Job.id.desc())
              .first())
    if latest is None:
        return False, 0.0
    return latest.status == "failed", 1.0 if latest.status == "failed" else 0.0


def _open_alert(db, rule_id: int, target_type: str, target_id: int) -> Alert | None:
    return (db.query(Alert)
            .filter(Alert.rule_id == rule_id, Alert.state == "firing",
                    Alert.target_type == target_type,
                    Alert.target_id == target_id)
            .order_by(Alert.id.desc())
            .first())


def _transition(rule: AlertRule, alert: Alert, label: str, state: str) -> dict:
    return {"alert_id": alert.id, "rule_id": rule.id, "rule_name": rule.name,
            "state": state, "severity": rule.severity,
            "target_type": alert.target_type, "target_id": alert.target_id,
            "target_label": label, "value": alert.value,
            "message": alert.message, "channel_ids": list(rule.channel_ids or [])}


def evaluate(db, now: datetime | None = None) -> list[dict]:
    """One pass over every enabled rule. Blocking. Returns only transitions.

    ponytail: O(rules x targets) queries per pass, each one index-covered by
    `ix_samples(target_type, target_id, metric, ts)`. At the single-digit rule
    counts a self-hoster has this is a handful of queries every 30 s. If a
    fleet ever makes it hurt, the fix is one grouped query per (metric,
    duration) bucket rather than per target — not a different design.

    A firing Alert whose (rule, target) this pass never visits — its rule got
    disabled, or its target row got deleted — would otherwise stay `firing`
    forever (deleting the RULE cascades its alerts away, so a missing rule row
    can't happen here; only a missing target or a disabled rule can). The
    orphan sweep at the bottom closes those the same way a normal recovery
    does, through the same transitions list, so it gets the same SSE/notify.
    """
    now = now or utcnow()
    transitions: list[dict] = []
    visited: set[tuple[int, str, int]] = set()
    for rule in db.query(AlertRule).filter(AlertRule.enabled.is_(True)).all():
        if rule.metric not in METRIC_TARGETS:
            # A metric this build does not know — a downgrade, or a row edited
            # by hand. Skip it; one unusable rule must not stop the others.
            logger.debug("alert rule %s: unknown metric %r", rule.id, rule.metric)
            continue
        for target_type, target_id, label in targets_for(db, rule):
            visited.add((rule.id, target_type, target_id))
            try:
                if rule.metric in STATUS_METRICS:
                    breaching, value = _status_state(db, rule, target_id, now)
                else:
                    breaching, value = _metric_state(db, rule, target_type,
                                                     target_id, now)
            except Exception:  # noqa: BLE001 — one bad target never stops the pass
                logger.debug("alert rule %s target %s:%s raised", rule.id,
                             target_type, target_id, exc_info=True)
                continue

            open_alert = _open_alert(db, rule.id, target_type, target_id)
            if breaching and open_alert is None:
                row = Alert(rule_id=rule.id, target_type=target_type,
                            target_id=target_id, state="firing", value=value,
                            message=render_message(rule.name, label, rule.metric,
                                                   rule.operator, rule.threshold,
                                                   rule.duration_s, value, "firing"),
                            fired_at=now)
                db.add(row)
                db.commit()
                transitions.append(_transition(rule, row, label, "firing"))
            elif not breaching and open_alert is not None:
                open_alert.state = "resolved"
                open_alert.resolved_at = now
                open_alert.value = value
                open_alert.message = render_message(
                    rule.name, label, rule.metric, rule.operator, rule.threshold,
                    rule.duration_s, value, "resolved")
                db.commit()
                transitions.append(_transition(rule, open_alert, label, "resolved"))

    for alert in db.query(Alert).filter(Alert.state == "firing").all():
        if (alert.rule_id, alert.target_type, alert.target_id) in visited:
            continue
        rule = db.get(AlertRule, alert.rule_id)
        if rule is None:  # cascade should have removed it too; be defensive
            continue
        label = _label(db, alert.target_type, alert.target_id) or (
            f"{alert.target_type} #{alert.target_id}")
        alert.state = "resolved"
        alert.resolved_at = now
        alert.message = f"Resolved: {rule.name} — target removed or rule disabled"
        db.commit()
        transitions.append(_transition(rule, alert, label, "resolved"))
    return transitions


def sse_frame(t: dict) -> dict:
    """The `alert` SSE delta, doc 05 §Streaming 4, verbatim:
    {"id":12,"state":"firing","severity":"warning","message":"host-02 CPU …"}
    """
    return {"id": t["alert_id"], "state": t["state"],
            "severity": t["severity"], "message": t["message"]}


def notify_transitions(app, transitions: list[dict]) -> int:
    """Fan transitions out through the Notifier. Blocking; returns sends made.

    Event names are `alert.fired` / `alert.resolved`, which is what doc 04's
    `notification_channels.events` example subscribes to. A rule's
    `channel_ids` overrides that subscription (see notifier.channels_for).

    Notification is a courtesy and must never be able to fail evaluation, so
    every send is isolated inside notifier.notify already; this only has to not
    raise on its own account.
    """
    from proxploy.services.notifier import notify

    reached = 0
    for t in transitions:
        event = f"alert.{'fired' if t['state'] == 'firing' else 'resolved'}"
        verb = "FIRING" if t["state"] == "firing" else "RESOLVED"
        title = f"Proxploy alert {verb}: {t['rule_name']}"
        try:
            reached += notify(app, event, title, t["message"],
                              only_ids=t.get("channel_ids") or None)
        except Exception:  # noqa: BLE001 — a broken channel never breaks alerting
            logger.debug("alert %s notification failed", t.get("alert_id"),
                         exc_info=True)
    return reached
