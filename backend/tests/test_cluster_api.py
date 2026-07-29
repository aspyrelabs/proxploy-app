"""Cluster summary + node cards from DB caches and poller snapshots."""


def _setup(tmp_path):
    from fastapi.testclient import TestClient
    from tests.support import make_app

    app = make_app(tmp_path)
    return app, TestClient(app)


def _seed(app):
    from proxploy.models import App, Vm
    from tests.support import seed_snapshot

    with app.state.sessionmaker() as db:
        from tests.support import seed_host_row
        h = seed_host_row(db)
        db.add(App(host_id=h.id, ctid=150, name="Immich", slug="immich",
                   status_cached="running"))
        db.add(Vm(host_id=h.id, vmid=100, name="win11", status="running"))
        db.commit()
        hid = h.id
    seed_snapshot(app, hid, nodes=[{
        "node": "pve1", "status": "online", "cpu_pct": 42.0, "cpu_cores": 8,
        "mem_bytes": 13743895347, "mem_total_bytes": 33822867456,
        "uptime_s": 864000}],
        storage=[{"storage": "local", "node": "pve1",
                  "used_bytes": 100, "total_bytes": 400},
                 {"storage": "local", "node": "pve2",
                  "used_bytes": 100, "total_bytes": 400}],
        net={"in_bps": 1300000.0, "out_bps": 5000000.0})
    return hid


def test_summary_aggregates_and_dedupes_storage(tmp_path, csrf_header, bootstrap_admin):
    app, c = _setup(tmp_path)
    with c:
        bootstrap_admin(c)
        _seed(app)
        r = c.get("/api/v1/cluster/summary")
        assert r.status_code == 200
        s = r.json()
        assert s["cpu"]["total_cores"] == 8 and s["cpu"]["pct"] == 42.0
        assert s["counts"] == {"hosts": 1, "hosts_online": 1, "nodes": 1,
                               "apps": 1, "apps_running": 1,
                               "vms": 1, "vms_running": 1}
        # same-named storage counted once (shared-storage dedupe)
        assert s["storage"]["total_bytes"] == 400
        assert s["net"]["in_bps"] == 1300000.0
        assert s["updated_at"] is not None


def test_nodes_cards_and_snapshotless_host(tmp_path, csrf_header, bootstrap_admin):
    app, c = _setup(tmp_path)
    with c:
        bootstrap_admin(c)
        _seed(app)
        with app.state.sessionmaker() as db:
            from tests.support import seed_host_row
            seed_host_row(db, name="host-02", node="pve2", status="unreachable")
        rows = c.get("/api/v1/cluster/nodes").json()
        assert len(rows) == 2
        one = next(r for r in rows if r["name"] == "host-01")
        two = next(r for r in rows if r["name"] == "host-02")
        assert one["cpu_pct"] == 42.0 and one["mem_pct"] == 40.6
        assert one["apps_running"] == 1 and one["vms_running"] == 1
        assert two["status"] == "unreachable" and two["cpu_pct"] is None


def test_cluster_requires_auth(tmp_path):
    _, c = _setup(tmp_path)
    with c:
        assert c.get("/api/v1/cluster/summary").status_code == 401
