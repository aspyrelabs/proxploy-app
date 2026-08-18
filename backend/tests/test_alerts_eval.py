"""Alert evaluation (doc 04 alert_rules/alerts, doc 10 Phase 7)."""
from datetime import timedelta

from proxploy.models import (Alert, AlertRule, App, Backup, Host, Job,
                             MetricSample, User, Vm, utcnow)
from proxploy.services.alerts import (METRIC_TARGETS, evaluate, render_message,
                                      targets_for)
from tests.support import make_db, seed_host_row


def _rule(db, **kw):
    kw.setdefault("name", "CPU high")
    kw.setdefault("metric", "cpu_pct")
    kw.setdefault("target_type", "host")
    kw.setdefault("operator", "gt")
    kw.setdefault("threshold", 85.0)
    kw.setdefault("duration_s", 0)
    kw.setdefault("severity", "warning")
    kw.setdefault("channel_ids", [])
    kw.setdefault("enabled", True)
    r = AlertRule(**kw)
    db.add(r)
    db.commit()
    return r


def _samples(db, target_type, target_id, metric, values, now, step_s=30):
    """values[0] is the NEWEST."""
    for i, v in enumerate(values):
        db.add(MetricSample(target_type=target_type, target_id=target_id,
                            metric=metric, value=float(v),
                            ts=now - timedelta(seconds=i * step_s)))
    db.commit()


# --- firing -----------------------------------------------------------------

def test_a_breach_with_no_duration_fires_immediately(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db)
    rule = _rule(db, target_id=host.id)
    now = utcnow()
    _samples(db, "host", host.id, "cpu_pct", [92.0], now)

    out = evaluate(db, now)
    assert len(out) == 1
    t = out[0]
    assert t["state"] == "firing"
    assert t["rule_id"] == rule.id
    assert t["target_type"] == "host" and t["target_id"] == host.id
    assert t["value"] == 92.0
    assert t["severity"] == "warning"
    assert db.query(Alert).filter_by(state="firing").count() == 1


def test_a_breach_shorter_than_duration_does_not_fire(tmp_path):
    """Two 30 s samples is one minute of breach, not five."""
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _rule(db, target_id=host.id, duration_s=300)
    now = utcnow()
    _samples(db, "host", host.id, "cpu_pct", [92.0, 91.0], now)

    assert evaluate(db, now) == []
    assert db.query(Alert).count() == 0


def test_a_breach_held_for_the_full_duration_fires(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _rule(db, target_id=host.id, duration_s=300)
    now = utcnow()
    _samples(db, "host", host.id, "cpu_pct", [92.0] * 12, now)   # 11 * 30s = 330s

    out = evaluate(db, now)
    assert len(out) == 1 and out[0]["state"] == "firing"


def test_a_dip_inside_the_window_resets_the_clock(tmp_path):
    """"85% for 5 minutes" means continuously, one healthy sample two minutes
    ago means it has only been breaching for two minutes."""
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _rule(db, target_id=host.id, duration_s=300)
    now = utcnow()
    _samples(db, "host", host.id, "cpu_pct",
             [92.0, 92.0, 92.0, 10.0, 92.0, 92.0, 92.0, 92.0, 92.0, 92.0, 92.0,
              92.0], now)

    assert evaluate(db, now) == []


def test_no_samples_is_never_a_breach(tmp_path):
    """Absence of data is not evidence of a problem."""
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _rule(db, target_id=host.id)
    assert evaluate(db, utcnow()) == []


def test_the_lt_operator_fires_below_the_threshold(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _rule(db, metric="mem_pct", operator="lt", threshold=10.0, target_id=host.id)
    now = utcnow()
    _samples(db, "host", host.id, "mem_pct", [3.0], now)
    assert evaluate(db, now)[0]["state"] == "firing"


# --- idempotence and resolution --------------------------------------------

def test_a_still_breaching_rule_produces_no_second_transition(tmp_path):
    """Otherwise every 30 s poll re-notifies for the same problem."""
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _rule(db, target_id=host.id)
    now = utcnow()
    _samples(db, "host", host.id, "cpu_pct", [92.0], now)

    assert len(evaluate(db, now)) == 1
    assert evaluate(db, now + timedelta(seconds=30)) == []
    assert db.query(Alert).count() == 1


def test_recovery_resolves_the_open_alert(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _rule(db, target_id=host.id)
    now = utcnow()
    _samples(db, "host", host.id, "cpu_pct", [92.0], now)
    evaluate(db, now)

    later = now + timedelta(seconds=60)
    _samples(db, "host", host.id, "cpu_pct", [20.0], later)
    out = evaluate(db, later)
    assert len(out) == 1 and out[0]["state"] == "resolved"

    a = db.query(Alert).one()
    assert a.state == "resolved" and a.resolved_at is not None
    # and it stays resolved: no re-resolve transition on the next cycle
    assert evaluate(db, later + timedelta(seconds=30)) == []


def test_an_acknowledged_alert_still_resolves(tmp_path):
    """Ack silences the noise; it does not pin the alert open."""
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _rule(db, target_id=host.id)
    now = utcnow()
    _samples(db, "host", host.id, "cpu_pct", [92.0], now)
    evaluate(db, now)
    a = db.query(Alert).one()
    u = User(email="op@example.com", display_name="Op")
    db.add(u)
    db.commit()
    a.acked_by, a.acked_at = u.id, now
    db.commit()

    later = now + timedelta(seconds=60)
    _samples(db, "host", host.id, "cpu_pct", [20.0], later)
    assert evaluate(db, later)[0]["state"] == "resolved"


def test_a_disabled_rule_is_not_evaluated_at_all(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _rule(db, target_id=host.id, enabled=False)
    now = utcnow()
    _samples(db, "host", host.id, "cpu_pct", [99.0], now)
    assert evaluate(db, now) == []


# --- target resolution ------------------------------------------------------

def test_target_any_expands_across_every_supported_target(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db)
    db.add(App(host_id=host.id, ctid=101, name="redis", slug="redis-1-101",
               web_protocol="http", web_path="/", adopted=True))
    db.add(Vm(host_id=host.id, vmid=201, name="win", status="running"))
    db.commit()
    rule = _rule(db, target_type="any", target_id=None)

    labels = {t[2] for t in targets_for(db, rule)}
    assert labels == {"host-01", "redis", "win"}


def test_target_any_fires_once_per_breaching_target(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db)
    db.add(App(host_id=host.id, ctid=101, name="redis", slug="redis-1-101",
               web_protocol="http", web_path="/", adopted=True))
    db.commit()
    app_id = db.query(App).one().id
    _rule(db, target_type="any", target_id=None)
    now = utcnow()
    _samples(db, "host", host.id, "cpu_pct", [92.0], now)
    _samples(db, "app", app_id, "cpu_pct", [10.0], now)     # healthy

    out = evaluate(db, now)
    assert len(out) == 1
    assert (out[0]["target_type"], out[0]["target_id"]) == ("host", host.id)


def test_disk_pct_only_ever_targets_hosts(tmp_path):
    """Guest disk figures from /cluster/resources are meaningless for QEMU, so
    the poller writes disk_pct for hosts only and this must match."""
    assert METRIC_TARGETS["disk_pct"] == ("host",)
    db = make_db(tmp_path)
    host = seed_host_row(db)
    db.add(App(host_id=host.id, ctid=101, name="redis", slug="redis-1-101",
               web_protocol="http", web_path="/", adopted=True))
    db.commit()
    rule = _rule(db, metric="disk_pct", target_type="any", target_id=None)
    assert {t[0] for t in targets_for(db, rule)} == {"host"}


def test_a_rule_pointing_at_a_deleted_target_is_skipped_not_crashed(tmp_path):
    db = make_db(tmp_path)
    _rule(db, target_type="host", target_id=4242)
    assert evaluate(db, utcnow()) == []


def test_a_firing_alert_whose_target_was_deleted_resolves_on_the_next_pass(tmp_path):
    """Otherwise the health footer says "1 alert firing" forever."""
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _rule(db, target_id=host.id)
    now = utcnow()
    _samples(db, "host", host.id, "cpu_pct", [92.0], now)
    evaluate(db, now)
    assert db.query(Alert).filter_by(state="firing").count() == 1

    db.delete(host)
    db.commit()

    out = evaluate(db, now + timedelta(seconds=30))
    assert len(out) == 1 and out[0]["state"] == "resolved"
    assert db.query(Alert).filter_by(state="firing").count() == 0


def test_a_firing_alert_whose_rule_was_disabled_resolves_on_the_next_pass(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db)
    rule = _rule(db, target_id=host.id)
    now = utcnow()
    _samples(db, "host", host.id, "cpu_pct", [92.0], now)
    evaluate(db, now)
    assert db.query(Alert).filter_by(state="firing").count() == 1

    rule.enabled = False
    db.commit()

    out = evaluate(db, now + timedelta(seconds=30))
    assert len(out) == 1 and out[0]["state"] == "resolved"
    assert db.query(Alert).filter_by(state="firing").count() == 0


# --- status-backed metrics --------------------------------------------------

def test_host_offline_fires_on_an_unreachable_host(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db, status="unreachable")
    host.last_seen_at = utcnow() - timedelta(minutes=10)
    db.commit()
    _rule(db, name="Host down", metric="host_offline", target_id=host.id,
          duration_s=300, severity="critical")

    out = evaluate(db, utcnow())
    assert len(out) == 1
    assert out[0]["severity"] == "critical"
    assert "offline" in out[0]["message"].lower()


def test_host_offline_respects_duration_before_firing(tmp_path):
    """A 30 s blip during a PVE restart is not an outage."""
    db = make_db(tmp_path)
    host = seed_host_row(db, status="unreachable")
    host.last_seen_at = utcnow() - timedelta(seconds=30)
    db.commit()
    _rule(db, metric="host_offline", target_id=host.id, duration_s=300)
    assert evaluate(db, utcnow()) == []


def test_host_offline_resolves_when_the_host_comes_back(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db, status="unreachable")
    host.last_seen_at = utcnow() - timedelta(minutes=10)
    db.commit()
    _rule(db, metric="host_offline", target_id=host.id)
    now = utcnow()
    evaluate(db, now)

    host.status, host.last_seen_at = "connected", now
    db.commit()
    assert evaluate(db, now + timedelta(seconds=30))[0]["state"] == "resolved"


def test_quorum_lost_fires_and_says_what_it_means(tmp_path):
    """A cluster without quorum answers every read and refuses every write, so
    no other metric moves: cpu, memory and disk all look normal, the host is
    `connected`, and nothing is offline. Reached for real on 2026-08-18 (doc 12
    check 12), where nothing in the product noticed.
    """
    db = make_db(tmp_path)
    host = seed_host_row(db)          # connected, healthy
    host.quorate = False
    db.commit()
    _rule(db, name="No quorum", metric="quorum_lost", target_id=host.id,
          severity="critical")

    out = evaluate(db, utcnow())
    assert len(out) == 1
    assert out[0]["severity"] == "critical"
    # The message has to say what it costs, not name a corosync concept.
    assert "quorum" in out[0]["message"].lower()
    assert "will fail" in out[0]["message"].lower()


def test_quorum_lost_does_not_fire_for_a_standalone_or_unpolled_host(tmp_path):
    """NULL is "the question does not apply" (standalone) or "not polled yet",
    and firing on either would alert every standalone host in the fleet."""
    db = make_db(tmp_path)
    host = seed_host_row(db)
    assert host.quorate is None
    _rule(db, metric="quorum_lost", target_id=host.id)
    assert evaluate(db, utcnow()) == []


def test_quorum_lost_resolves_when_quorum_returns(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db)
    host.quorate = False
    db.commit()
    _rule(db, metric="quorum_lost", target_id=host.id)
    now = utcnow()
    evaluate(db, now)

    host.quorate = True
    db.commit()
    assert evaluate(db, now + timedelta(seconds=30))[0]["state"] == "resolved"


def test_backup_failed_fires_on_the_hosts_latest_failed_backup_job(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db)
    db.add(Job(kind="backup.run", status="failed", target_type="host",
               target_id=host.id, finished_at=utcnow()))
    db.commit()
    _rule(db, name="Backup failed", metric="backup_failed", target_id=host.id)

    out = evaluate(db, utcnow())
    assert len(out) == 1 and out[0]["state"] == "firing"


def test_backup_failed_does_not_fire_when_the_latest_run_succeeded(tmp_path):
    """Only the LATEST run matters, an old failure already fixed is not a
    live alert."""
    db = make_db(tmp_path)
    host = seed_host_row(db)
    old = utcnow() - timedelta(hours=2)
    db.add(Job(kind="backup.run", status="failed", target_type="host",
               target_id=host.id, finished_at=old))
    db.add(Job(kind="backup.run", status="succeeded", target_type="host",
               target_id=host.id, finished_at=utcnow()))
    db.commit()
    _rule(db, metric="backup_failed", target_id=host.id)
    assert evaluate(db, utcnow()) == []


# --- message rendering ------------------------------------------------------

def test_message_reads_like_the_doc_05_example(tmp_path):
    msg = render_message("CPU high", "host-02", "cpu_pct", "gt", 85.0, 300,
                         92.4, "firing")
    assert msg == "host-02 CPU > 85% for 5m (now 92.4%)"


def test_a_resolved_message_says_so(tmp_path):
    msg = render_message("CPU high", "host-02", "cpu_pct", "gt", 85.0, 300,
                         12.0, "resolved")
    assert msg.startswith("Resolved: ")
    assert "host-02" in msg


def test_one_bad_rule_does_not_stop_the_others(tmp_path):
    """A metric the evaluator does not know (a downgrade, a hand-edited row)
    must be skipped, not raised."""
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _rule(db, name="nonsense", metric="phase_of_moon", target_id=host.id)
    _rule(db, name="real", metric="cpu_pct", target_id=host.id)
    now = utcnow()
    _samples(db, "host", host.id, "cpu_pct", [99.0], now)

    out = evaluate(db, now)
    assert [t["rule_name"] for t in out] == ["real"]
