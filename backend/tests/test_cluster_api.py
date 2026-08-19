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
        "uptime_s": 864000, "net_in_bps": 1300000.0, "net_out_bps": 5000000.0}],
        storage=[{"storage": "nfs", "node": "pve1", "shared": True,
                  "used_bytes": 100, "total_bytes": 400},
                 {"storage": "nfs", "node": "pve2", "shared": True,
                  "used_bytes": 100, "total_bytes": 400}])
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
        # a SHARED datastore is reported once per node and counts once. The
        # fixture used to use `local` with no `shared` flag and assert the same
        # 400, which is the undercount this dedupe used to have: two nodes'
        # `local` are two pools, and there is now a test for that below.
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
        # a standalone host is still exactly one row, and it is the entry
        assert one["node"] == "pve1" and one["is_entry"] is True
        # a host with no snapshot at all still gets its one row, from the DB
        assert two["node"] == "pve2" and two["is_entry"] is True


def test_a_three_node_cluster_is_three_rows_not_one(tmp_path, csrf_header,
                                                    bootstrap_admin):
    """A Host is ONE API endpoint; the cluster behind it is many nodes.

    /cluster/resources already returns every node and the poller stores them
    all, but this endpoint used to pick `own` and throw the rest away, so a
    3-node cluster rendered as a single card.
    """
    app, c = _setup(tmp_path)
    with c:
        bootstrap_admin(c)
        from tests.support import seed_host_row, seed_snapshot
        with app.state.sessionmaker() as db:
            h = seed_host_row(db, name="host-01", node="pve2")
            h.cluster_name = "prod"
            db.commit()
            hid = h.id
        seed_snapshot(app, hid, nodes=[
            {"node": "pve1", "status": "online", "cpu_pct": 10.0, "cpu_cores": 4,
             "mem_bytes": 1000, "mem_total_bytes": 4000, "uptime_s": 100},
            {"node": "pve2", "status": "online", "cpu_pct": 20.0, "cpu_cores": 8,
             "mem_bytes": 2000, "mem_total_bytes": 4000, "uptime_s": 200},
            {"node": "pve3", "status": "online", "cpu_pct": 30.0, "cpu_cores": 8,
             "mem_bytes": 3000, "mem_total_bytes": 4000, "uptime_s": 300},
        ])
        rows = c.get("/api/v1/cluster/nodes").json()
        assert [r["node"] for r in rows] == ["pve1", "pve2", "pve3"]
        assert {r["host_id"] for r in rows} == {hid}
        assert {r["cluster"] for r in rows} == {"prod"}
        # per-node metrics, not the entry node's repeated three times
        assert [r["cpu_pct"] for r in rows] == [10.0, 20.0, 30.0]
        assert [r["mem_pct"] for r in rows] == [25.0, 50.0, 75.0]
        assert [r["uptime_s"] for r in rows] == [100, 200, 300]
        # exactly one entry: the node whose name is the one we connect through
        assert [r["is_entry"] for r in rows] == [False, True, False]


def test_two_hosts_on_one_cluster_are_two_node_rows_not_four(tmp_path, csrf_header,
                                                              bootstrap_admin):
    """Two Hosts can be two nodes of the SAME Proxmox cluster; each one's poll
    sees the whole cluster's node list (root cause: cluster_resources()
    returns every node from any node asked), so both snapshots list both
    pve1 and pve2. A real node must appear once, attributed to the Host
    actually registered at that node."""
    app, c = _setup(tmp_path)
    with c:
        bootstrap_admin(c)
        from proxploy.models import Host
        from tests.support import seed_host_row, seed_snapshot
        with app.state.sessionmaker() as db:
            hid1 = seed_host_row(db, name="host-01", node="pve1").id
            hid2 = seed_host_row(db, name="host-02", node="pve2").id
            # Both Hosts are the SAME real cluster (Host.cluster_name, set by
            # the poller in production); that is what makes their two
            # snapshots the same cluster-wide view, not two unrelated hosts.
            db.get(Host, hid1).cluster_name = "lab-cluster"
            db.get(Host, hid2).cluster_name = "lab-cluster"
            db.commit()
        both_nodes = [
            {"node": "pve1", "status": "online", "cpu_pct": 10.0, "cpu_cores": 4,
             "mem_bytes": 1000, "mem_total_bytes": 4000, "uptime_s": 100},
            {"node": "pve2", "status": "online", "cpu_pct": 20.0, "cpu_cores": 8,
             "mem_bytes": 2000, "mem_total_bytes": 4000, "uptime_s": 200},
        ]
        seed_snapshot(app, hid1, nodes=both_nodes)
        seed_snapshot(app, hid2, nodes=both_nodes)
        rows = c.get("/api/v1/cluster/nodes").json()
        assert {r["node"] for r in rows} == {"pve1", "pve2"}
        assert len(rows) == 2
        by_node = {r["node"]: r for r in rows}
        assert by_node["pve1"]["host_id"] == hid1
        assert by_node["pve2"]["host_id"] == hid2
        assert by_node["pve1"]["is_entry"] is True
        assert by_node["pve2"]["is_entry"] is True


def test_two_hosts_on_different_clusters_with_the_same_node_name_are_not_merged(
        tmp_path, csrf_header, bootstrap_admin):
    """A node name is only unique WITHIN one cluster. Two different clusters
    (here: two standalone hosts, cluster_name None) can each have a node
    called pve1; both rows must survive, one per Host."""
    app, c = _setup(tmp_path)
    with c:
        bootstrap_admin(c)
        from tests.support import seed_host_row, seed_snapshot
        with app.state.sessionmaker() as db:
            hid1 = seed_host_row(db, name="host-01", node="pve1").id
            hid2 = seed_host_row(db, name="host-02", node="pve1").id  # standalone too
        node_row = [{"node": "pve1", "status": "online", "cpu_pct": 1.0,
                    "cpu_cores": 4, "mem_bytes": 1, "mem_total_bytes": 4,
                    "uptime_s": 1}]
        seed_snapshot(app, hid1, nodes=node_row)
        seed_snapshot(app, hid2, nodes=node_row)
        rows = c.get("/api/v1/cluster/nodes").json()
        assert len(rows) == 2
        assert {r["host_id"] for r in rows} == {hid1, hid2}
        assert all(r["node"] == "pve1" for r in rows)
        assert all(r["is_entry"] for r in rows)


def test_node_rows_carry_that_node_s_storage(tmp_path, csrf_header,
                                             bootstrap_admin):
    """Storage is per NODE, and a shared datastore counts on every node that
    can use it.

    That is a deliberate choice with a consequence: summing these rows
    double-counts a shared pool across a cluster, which is why the cluster
    total comes from /cluster/summary and never from adding these up.
    """
    app, c = _setup(tmp_path)
    with c:
        bootstrap_admin(c)
        from tests.support import seed_host_row, seed_snapshot
        with app.state.sessionmaker() as db:
            hid = seed_host_row(db, name="host-01", node="pve1").id
        seed_snapshot(app, hid, nodes=[
            {"node": "pve1", "status": "online", "cpu_pct": 1.0, "cpu_cores": 4,
             "mem_bytes": 1, "mem_total_bytes": 4, "uptime_s": 1},
            {"node": "pve2", "status": "online", "cpu_pct": 2.0, "cpu_cores": 4,
             "mem_bytes": 2, "mem_total_bytes": 4, "uptime_s": 2},
        ], storage=[
            # same NAME on both nodes, but local: two distinct pools
            {"storage": "local", "node": "pve1", "used_bytes": 100,
             "total_bytes": 400, "shared": False},
            {"storage": "local", "node": "pve2", "used_bytes": 200,
             "total_bytes": 400, "shared": False},
            # one shared pool, reported once per node
            {"storage": "ceph", "node": "pve1", "used_bytes": 500,
             "total_bytes": 1000, "shared": True},
            {"storage": "ceph", "node": "pve2", "used_bytes": 500,
             "total_bytes": 1000, "shared": True},
        ])
        rows = {r["node"]: r for r in c.get("/api/v1/cluster/nodes").json()}
        # pve1 sees its own 100/400 plus the shared 500/1000
        assert rows["pve1"]["disk_bytes"] == 600
        assert rows["pve1"]["disk_total_bytes"] == 1400
        assert rows["pve1"]["disk_pct"] == 42.9
        # pve2's local pool is a different one, with a different fill
        assert rows["pve2"]["disk_bytes"] == 700
        assert rows["pve2"]["disk_total_bytes"] == 1400
        assert rows["pve2"]["disk_pct"] == 50.0


def test_a_host_with_no_snapshot_has_unknown_storage(tmp_path, csrf_header,
                                                     bootstrap_admin):
    """Nulled like cpu_pct and mem_pct: unknown must not render as 0% full."""
    app, c = _setup(tmp_path)
    with c:
        bootstrap_admin(c)
        from tests.support import seed_host_row
        with app.state.sessionmaker() as db:
            seed_host_row(db, name="host-01", node="pve1")
        row = c.get("/api/v1/cluster/nodes").json()[0]
        assert row["disk_pct"] is None
        assert row["disk_bytes"] is None and row["disk_total_bytes"] is None


def test_an_offline_cluster_node_is_not_reported_as_connected(tmp_path,
                                                              csrf_header,
                                                              bootstrap_admin):
    """Host status is per-endpoint; a node PVE calls `offline` is not up.

    Only an explicit `offline` downgrades a row, so a snapshot that reports an
    unfamiliar status can never make a working host look broken.
    """
    app, c = _setup(tmp_path)
    with c:
        bootstrap_admin(c)
        from tests.support import seed_host_row, seed_snapshot
        with app.state.sessionmaker() as db:
            hid = seed_host_row(db, name="host-01", node="pve1").id
        seed_snapshot(app, hid, nodes=[
            {"node": "pve1", "status": "online", "cpu_pct": 1.0, "cpu_cores": 4,
             "mem_bytes": 1, "mem_total_bytes": 4, "uptime_s": 1},
            {"node": "pve2", "status": "offline", "cpu_pct": 0.0, "cpu_cores": 4,
             "mem_bytes": 0, "mem_total_bytes": 0, "uptime_s": 0},
            {"node": "pve3", "status": "unknown", "cpu_pct": 0.0, "cpu_cores": 4,
             "mem_bytes": 0, "mem_total_bytes": 0, "uptime_s": 0},
        ])
        rows = {r["node"]: r["status"] for r in
                c.get("/api/v1/cluster/nodes").json()}
        assert rows == {"pve1": "connected", "pve2": "unreachable",
                        "pve3": "connected"}


def test_cluster_requires_auth(tmp_path):
    _, c = _setup(tmp_path)
    with c:
        assert c.get("/api/v1/cluster/summary").status_code == 401


def _node(name, **kw):
    d = {"node": name, "status": "online", "cpu_pct": 10.0, "cpu_cores": 4,
         "mem_bytes": 1, "mem_total_bytes": 2, "uptime_s": 1,
         "net_in_bps": 100.0, "net_out_bps": 50.0}
    d.update(kw)
    return d


def test_summary_counts_a_local_pool_per_node_and_a_shared_pool_once(
        tmp_path, csrf_header, bootstrap_admin):
    """The ring keyed storage on NAME alone, so `local` on two nodes counted
    once and the cluster looked smaller than it is. On the real cluster that
    is 2936 GB against an actual 3161 GB, and the ring then disagreed with the
    host page's disk_pct, which has always keyed on `shared`."""
    app, c = _setup(tmp_path)
    from tests.support import seed_host_row, seed_snapshot

    with c:
        bootstrap_admin(c)
        with app.state.sessionmaker() as db:
            hid = seed_host_row(db).id
        seed_snapshot(app, hid, nodes=[_node("pve1")], storage=[
            {"storage": "local", "node": "pve1", "shared": False,
             "used_bytes": 10, "total_bytes": 100},
            {"storage": "local", "node": "pve2", "shared": False,
             "used_bytes": 20, "total_bytes": 200},
            {"storage": "nfs", "node": "pve1", "shared": True,
             "used_bytes": 5, "total_bytes": 50},
            {"storage": "nfs", "node": "pve2", "shared": True,
             "used_bytes": 5, "total_bytes": 50},
        ])

        s = c.get("/api/v1/cluster/summary").json()
        # two distinct local pools (100 + 200) plus the shared one counted once
        assert s["storage"]["total_bytes"] == 350
        assert s["storage"]["used_bytes"] == 35


def test_summary_does_not_double_count_traffic_across_hosts_of_one_cluster(
        tmp_path, csrf_header, bootstrap_admin):
    """Every host's snapshot already sums the WHOLE cluster's per-node rrd, so
    adding the snapshots together reported one cluster's traffic once per
    enrolled Host. nodes, storage and vms are all deduped here; net was not."""
    app, c = _setup(tmp_path)
    from tests.support import seed_host_row, seed_snapshot

    with c:
        bootstrap_admin(c)
        with app.state.sessionmaker() as db:
            a = seed_host_row(db, name="h1", node="pve1")
            b = seed_host_row(db, name="h2", node="pve2")
            a.cluster_name = b.cluster_name = "lab-cluster"
            db.commit()
            aid, bid = a.id, b.id
        # both Hosts see the same two nodes, which is what /cluster/resources
        # returns from either member
        both = [_node("pve1"), _node("pve2")]
        for hid in (aid, bid):
            seed_snapshot(app, hid, nodes=both, storage=[])

        s = c.get("/api/v1/cluster/summary").json()
        assert s["counts"]["nodes"] == 2
        assert s["net"]["in_bps"] == 200.0, "counted one cluster's traffic twice"
        assert s["net"]["out_bps"] == 100.0


def test_summary_keeps_same_named_nodes_on_different_clusters_apart(
        tmp_path, csrf_header, bootstrap_admin):
    """Nodes were deduped on bare name across every snapshot. A node name is
    only unique WITHIN a cluster, and `pve` is the PVE installer's default, so
    two standalone hosts collapsed into one node card's worth of capacity.
    /cluster/nodes already keys on cluster_scope for exactly this reason."""
    app, c = _setup(tmp_path)
    from tests.support import seed_host_row, seed_snapshot

    with c:
        bootstrap_admin(c)
        with app.state.sessionmaker() as db:
            a = seed_host_row(db, name="h1", node="pve")
            b = seed_host_row(db, name="h2", node="pve")
            b.address = "https://10.0.0.10:8006"
            db.commit()
            aid, bid = a.id, b.id
        for hid in (aid, bid):
            seed_snapshot(app, hid, nodes=[_node("pve")], storage=[])

        s = c.get("/api/v1/cluster/summary").json()
        assert s["counts"]["nodes"] == 2, "two standalone hosts collapsed to one node"
        assert s["cpu"]["total_cores"] == 8
