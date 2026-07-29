"""/metrics/query: shapes, defaults, validation, 48h entitlement gate."""
from datetime import timedelta


def _setup(tmp_path):
    from fastapi.testclient import TestClient
    from proxploy.models import MetricSample, utcnow
    from tests.support import make_app

    app = make_app(tmp_path)
    c = TestClient(app)

    def seed():
        from proxploy.services.metrics import write_samples
        now = utcnow()
        with app.state.sessionmaker() as db:
            write_samples(db, [
                MetricSample(target_type="host", target_id=1, metric="cpu_pct",
                             value=50.0, ts=now - timedelta(seconds=30 * i))
                for i in range(1, 61)])
            db.commit()
        return now
    return app, c, seed


def test_query_raw_default_hour(tmp_path, csrf_header, bootstrap_admin):
    app, c, seed = _setup(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()
        r = c.get("/api/v1/metrics/query?target=host:1&metric=cpu_pct")
        assert r.status_code == 200
        body = r.json()
        assert body["resolution"] == "raw" and len(body["ts"]) == 60
        assert body["ts"] == sorted(body["ts"])


def test_query_validation(tmp_path, csrf_header, bootstrap_admin):
    app, c, seed = _setup(tmp_path)
    with c:
        bootstrap_admin(c)
        assert c.get("/api/v1/metrics/query?target=bogus&metric=cpu_pct").status_code == 422
        assert c.get("/api/v1/metrics/query?target=disk:1&metric=cpu_pct").status_code == 422
        assert c.get("/api/v1/metrics/query?target=host:1&metric=nope").status_code == 422
        assert c.get("/api/v1/metrics/query?target=host:1&metric=cpu_pct"
                     "&resolution=2m").status_code == 422


def test_history_gate_beyond_48h(tmp_path, csrf_header, bootstrap_admin):
    from datetime import timedelta
    from proxploy.models import utcnow

    app, c, seed = _setup(tmp_path)
    with c:
        bootstrap_admin(c)
        frm = (utcnow() - timedelta(hours=72)).isoformat()
        # dormant default map: all flags ON -> allowed
        assert c.get(f"/api/v1/metrics/query?target=host:1&metric=cpu_pct"
                     f"&from={frm}").status_code == 200
        # flip the flag off (test seam used by test_hosts.py:88)
        c.app.state.entitlements._features["metrics.history"] = False
        r = c.get(f"/api/v1/metrics/query?target=host:1&metric=cpu_pct&from={frm}")
        assert r.status_code == 403
        assert r.json()["feature"] == "metrics.history"
