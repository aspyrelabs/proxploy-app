"""Read-only Apps/VMs endpoints: cached rows + snapshot enrichment + filters."""


def _seeded(tmp_path):
    from fastapi.testclient import TestClient
    from proxploy.models import App, Vm
    from tests.support import make_app, seed_snapshot

    app = make_app(tmp_path)
    c = TestClient(app)

    def seed():
        from tests.support import seed_host_row
        with app.state.sessionmaker() as db:
            h = seed_host_row(db)
            db.add(App(host_id=h.id, ctid=150, name="Immich", slug="immich",
                       status_cached="running", cpu_pct_cached=12.0,
                       mem_bytes_cached=2147483648, uptime_s_cached=86400))
            db.add(App(host_id=h.id, ctid=151, name="Paperless", slug="paperless",
                       status_cached="stopped"))
            # mem_bytes/disk_bytes are USED and *_total_bytes are ALLOCATED,
            # the same way round as on an App row (migration a1f4d80c3e69).
            db.add(Vm(host_id=h.id, vmid=100, name="win11", status="running",
                      cpu_cores=4, mem_bytes=6442450944,
                      mem_total_bytes=8589934592,
                      disk_bytes=21474836480, disk_total_bytes=68719476736,
                      net_in_bps_cached=1500.0, net_out_bps_cached=250.0,
                      uptime_s=172800))
            db.commit()
            hid = h.id
        seed_snapshot(app, hid, guests={
            ("lxc", 150): {"name": "immich", "node": "pve1", "status": "running",
                           "cpu_pct": 12.0, "cpu_cores": 4,
                           "mem_bytes": 2147483648, "mem_total_bytes": 4294967296,
                           "disk_bytes": 0, "uptime_s": 86400},
            ("qemu", 100): {"name": "win11", "node": "pve1", "status": "running",
                            "cpu_pct": 31.0, "cpu_cores": 4,
                            "mem_bytes": 6442450944, "mem_total_bytes": 8589934592,
                            "disk_bytes": 68719476736, "uptime_s": 172800}},
            discovered=[{"ctid": 200, "name": "plex", "node": "pve1",
                         "status": "running", "suggestion": "plex"}])
        return hid
    return app, c, seed


def test_apps_list_filters_and_enrichment(tmp_path, csrf_header, bootstrap_admin):
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()
        rows = c.get("/api/v1/apps").json()
        assert len(rows) == 2
        immich = next(r for r in rows if r["slug"] == "immich")
        assert immich["status"] == "running" and immich["cpu_pct"] == 12.0
        assert immich["mem_total_bytes"] == 4294967296  # snapshot-enriched
        assert immich["host_name"] == "host-01" and immich["node"] == "pve1"
        assert [r["slug"] for r in c.get("/api/v1/apps?q=paper").json()] == ["paperless"]
        assert [r["slug"] for r in c.get("/api/v1/apps?status=running").json()] == ["immich"]
        assert c.get("/api/v1/apps?host=999").json() == []


def test_app_detail_and_404(tmp_path, csrf_header, bootstrap_admin):
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()
        aid = c.get("/api/v1/apps").json()[0]["id"]
        assert c.get(f"/api/v1/apps/{aid}").json()["id"] == aid
        assert c.get("/api/v1/apps/99999").status_code == 404


def test_app_out_carries_storage_and_network(tmp_path, csrf_header, bootstrap_admin):
    """The four fields the Apps views read. The raw netin/netout counters are
    NOT among them: they exist so the poller can compute the next rate, and a
    client has nothing to do with a number that only means something next to
    the previous one."""
    from proxploy.models import App

    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()
        with app.state.sessionmaker() as db:
            row = db.query(App).filter_by(ctid=150).one()
            row.disk_bytes_cached = 5_368_709_120
            row.disk_total_bytes_cached = 17_179_869_184
            row.net_in_bps_cached = 10_000.0
            row.net_out_bps_cached = 20.0
            db.commit()

        immich = next(r for r in c.get("/api/v1/apps").json() if r["slug"] == "immich")

        assert immich["disk_bytes"] == 5_368_709_120
        assert immich["disk_total_bytes"] == 17_179_869_184
        assert immich["net_in_bps"] == 10_000.0
        assert immich["net_out_bps"] == 20.0
        assert "net_in_cached" not in immich and "net_sampled_at" not in immich


def test_an_unpolled_app_serializes_null_metrics_not_zero(tmp_path, csrf_header,
                                                          bootstrap_admin):
    """Null is the honest answer for an app the poller has not reached. Zero
    would claim a container is idle when nothing has looked at it yet.

    CT 151 (Paperless) is seeded with no cached metrics at all, which is
    exactly that case."""
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()

        row = next(r for r in c.get("/api/v1/apps").json() if r["slug"] == "paperless")

        assert row["disk_bytes"] is None and row["disk_total_bytes"] is None
        assert row["net_in_bps"] is None and row["net_out_bps"] is None


def test_apps_carry_their_catalog_entrys_icon(tmp_path, csrf_header, bootstrap_admin):
    """An installed app shows the icon of the Store entry it came from, and the
    two absences that are normal rather than errors both serve null so the card
    falls back to its initials tile: a slug the catalog no longer has, and an
    entry upstream has no logo for."""
    from proxploy.models import App, CatalogEntry

    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        hid = seed()
        with app.state.sessionmaker() as db:
            db.add(CatalogEntry(slug="immich", name="Immich",
                                icon_url="https://cdn.example/immich.webp",
                                icon_cache_path="immich.webp"))
            db.add(CatalogEntry(slug="paperless", name="Paperless"))
            for a in db.query(App).all():
                a.catalog_slug = a.slug
            db.add(App(host_id=hid, ctid=152, name="Gone", slug="gone",
                       catalog_slug="removed-from-upstream"))
            db.commit()
        rows = {r["slug"]: r["icon_url"] for r in c.get("/api/v1/apps").json()}
        assert rows["immich"] == "/api/v1/catalog/immich/icon"
        assert rows["paperless"] is None
        assert rows["gone"] is None
        # The detail route resolves it too, and must agree with the grid.
        aid = next(r["id"] for r in c.get("/api/v1/apps").json()
                   if r["slug"] == "immich")
        assert c.get(f"/api/v1/apps/{aid}").json()["icon_url"] == rows["immich"]


def test_open_ui_port_comes_from_the_catalog_entry_not_the_app_row(tmp_path, csrf_header,
                                                                   bootstrap_admin):
    """PXP-85: the "Open web UI" button keys off `catalog_port`, resolved
    through this app's catalog entry on every request, same as the icon
    (test_apps_carry_their_catalog_entrys_icon). No entry, or an entry with
    no port, must serve None -- that is what hides the button client-side,
    never a fallback port and never a prompt."""
    from proxploy.models import App, CatalogEntry

    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        hid = seed()
        with app.state.sessionmaker() as db:
            db.add(CatalogEntry(slug="immich", name="Immich", port=2283))
            db.add(CatalogEntry(slug="paperless", name="Paperless"))  # no port
            for a in db.query(App).all():
                a.catalog_slug = a.slug
            db.add(App(host_id=hid, ctid=152, name="Gone", slug="gone",
                       catalog_slug="removed-from-upstream"))
            db.commit()
        rows = {r["slug"]: r["catalog_port"] for r in c.get("/api/v1/apps").json()}
        assert rows["immich"] == 2283
        assert rows["paperless"] is None
        assert rows["gone"] is None
        # The detail route resolves it the same way.
        aid = next(r["id"] for r in c.get("/api/v1/apps").json()
                   if r["slug"] == "immich")
        assert c.get(f"/api/v1/apps/{aid}").json()["catalog_port"] == 2283


def test_discovered_lists_unadopted_cts(tmp_path, csrf_header, bootstrap_admin):
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()
        disc = c.get("/api/v1/apps/discovered").json()
        assert disc == [{"host_id": disc[0]["host_id"], "host_name": "host-01",
                         "ctid": 200, "name": "plex", "node": "pve1",
                         "status": "running", "suggestion": "plex"}]


def test_discovered_is_not_duplicated_across_hosts_on_one_cluster(tmp_path, csrf_header,
                                                                   bootstrap_admin):
    """Two Hosts can be two nodes of the SAME Proxmox cluster; each one's poll
    sees the whole cluster's guest list (root cause: cluster_resources()
    returns every node's guests from any node asked), so both snapshots list
    the same unadopted CT. It must be offered once, attributed to the node
    that actually owns it, not the host that happened to poll it."""
    from fastapi.testclient import TestClient
    from proxploy.models import Host
    from tests.support import make_app, seed_host_row, seed_snapshot

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        with app.state.sessionmaker() as db:
            hid1 = seed_host_row(db, name="host-01", node="pve1").id
            hid2 = seed_host_row(db, name="host-02", node="pve2").id
            # Both Hosts are the SAME real cluster (Host.cluster_name, set by
            # the poller in production); that is what makes their two
            # snapshots the same cluster-wide view, not two unrelated hosts.
            db.get(Host, hid1).cluster_name = "lab-cluster"
            db.get(Host, hid2).cluster_name = "lab-cluster"
            db.commit()
        plex = {"ctid": 200, "name": "plex", "node": "pve2",
               "status": "running", "suggestion": "plex"}
        seed_snapshot(app, hid1, discovered=[plex])
        seed_snapshot(app, hid2, discovered=[plex])
        disc = c.get("/api/v1/apps/discovered").json()
        assert len(disc) == 1
        assert disc[0]["host_id"] == hid2  # owning node, not the polling host
        assert disc[0]["node"] == "pve2"


def test_an_already_adopted_ct_is_not_offered_again_from_another_host(tmp_path, csrf_header,
                                                                       bootstrap_admin):
    """CT 101 is tracked as an app on host-02. host-01's own poll cycle only
    checks App rows with host_id == its own id (mapped_ctids is host-scoped),
    so host-01's snapshot still lists CT 101 as discovered even though it is
    already adopted. It must not be offered for adoption a second time."""
    from fastapi.testclient import TestClient
    from proxploy.models import App, Host
    from tests.support import make_app, seed_host_row, seed_snapshot

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        with app.state.sessionmaker() as db:
            hid1 = seed_host_row(db, name="host-01", node="pve1").id
            hid2 = seed_host_row(db, name="host-02", node="pve2").id
            db.get(Host, hid1).cluster_name = "lab-cluster"
            db.get(Host, hid2).cluster_name = "lab-cluster"
            db.add(App(host_id=hid2, ctid=101, name="2fauth", slug="2fauth-2-101"))
            db.commit()
        ct = {"ctid": 101, "name": "2fauth", "node": "pve2",
             "status": "running", "suggestion": None}
        seed_snapshot(app, hid1, discovered=[ct])
        seed_snapshot(app, hid2, discovered=[])
        assert c.get("/api/v1/apps/discovered").json() == []


def test_discovered_does_not_merge_the_same_ctid_across_different_clusters(tmp_path, csrf_header,
                                                                            bootstrap_admin):
    """A ctid is only unique WITHIN one cluster. Two different clusters can
    each have an undiscovered CT 200; both must be offered, attributed to
    their own cluster's host, and adopting the one on cluster A must not hide
    cluster B's CT 200."""
    from fastapi.testclient import TestClient
    from proxploy.models import App, Host
    from tests.support import make_app, seed_host_row, seed_snapshot

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        with app.state.sessionmaker() as db:
            hid_a = seed_host_row(db, name="host-a", node="pve1").id
            hid_b = seed_host_row(db, name="host-b", node="pve1").id
            db.get(Host, hid_a).cluster_name = "cluster-a"
            db.get(Host, hid_b).cluster_name = "cluster-b"
            db.commit()
        ct_a = {"ctid": 200, "name": "plex", "node": "pve1",
               "status": "running", "suggestion": "plex"}
        ct_b = {**ct_a}
        seed_snapshot(app, hid_a, discovered=[ct_a])
        seed_snapshot(app, hid_b, discovered=[ct_b])
        disc = c.get("/api/v1/apps/discovered").json()
        assert len(disc) == 2
        assert {r["host_id"] for r in disc} == {hid_a, hid_b}

        # Adopting cluster A's CT 200 must not hide cluster B's CT 200.
        with app.state.sessionmaker() as db:
            db.add(App(host_id=hid_a, ctid=200, name="plex", slug="plex-a-200"))
            db.commit()
        disc = c.get("/api/v1/apps/discovered").json()
        assert len(disc) == 1
        assert disc[0]["host_id"] == hid_b


def test_discovered_does_not_merge_two_standalone_hosts_with_the_same_ctid(tmp_path, csrf_header,
                                                                            bootstrap_admin):
    """cluster_name is None for a standalone host, and None means "not
    clustered", not "unknown cluster" -- two standalone hosts with the same
    ctid are not each other and must both be offered."""
    from fastapi.testclient import TestClient
    from tests.support import make_app, seed_host_row, seed_snapshot

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        with app.state.sessionmaker() as db:
            hid1 = seed_host_row(db, name="host-01", node="pve1").id  # standalone
            hid2 = seed_host_row(db, name="host-02", node="pve1").id  # also standalone
        ct = {"ctid": 200, "name": "plex", "node": "pve1",
             "status": "running", "suggestion": "plex"}
        seed_snapshot(app, hid1, discovered=[dict(ct)])
        seed_snapshot(app, hid2, discovered=[dict(ct)])
        disc = c.get("/api/v1/apps/discovered").json()
        assert len(disc) == 2
        assert {r["host_id"] for r in disc} == {hid1, hid2}


def test_vms_list_and_detail(tmp_path, csrf_header, bootstrap_admin):
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()
        rows = c.get("/api/v1/vms").json()
        assert len(rows) == 1
        vm = rows[0]
        assert vm["name"] == "win11" and vm["cpu_pct"] == 31.0  # snapshot-enriched
        assert vm["os_type"] is None  # plan decision 5
        assert c.get(f"/api/v1/vms/{vm['id']}").json()["vmid"] == 100
        assert c.get("/api/v1/vms?host=999").json() == []
        assert c.get("/api/v1/vms/99999").status_code == 404


def test_vm_out_carries_usage_the_same_way_app_out_does(tmp_path, csrf_header,
                                                        bootstrap_admin):
    """The VMs page could draw a CPU meter and nothing else, because a VM row
    stored only the guest's ALLOCATION and served it under names that meant
    USAGE on an app. Memory and storage are now a used/allocated pair each and
    network is two rates, exactly as apps.py::_app_out serves them.
    """
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()

        vm = c.get("/api/v1/vms").json()[0]

        assert vm["mem_bytes"] == 6442450944         # used
        assert vm["mem_total_bytes"] == 8589934592   # allocated
        assert vm["disk_bytes"] == 21474836480       # used, via the guest agent
        assert vm["disk_total_bytes"] == 68719476736  # allocated, maxdisk
        assert vm["net_in_bps"] == 1500.0 and vm["net_out_bps"] == 250.0
        # Every field the endpoint served before is still served.
        assert {"id", "host_id", "host_name", "vmid", "name", "status",
                "os_type", "cpu_cores", "cpu_pct", "uptime_s", "template",
                "node", "guest_agent_ok"} <= set(vm)
        # Raw counters stay on the row: they only mean something next to the
        # previous reading, which is the poller's business, not a client's.
        assert "net_in_cached" not in vm and "net_sampled_at" not in vm


def test_an_unpolled_vm_serializes_null_usage_not_zero(tmp_path, csrf_header,
                                                       bootstrap_admin):
    """Null is the honest answer for a VM nothing has measured, and for
    disk_bytes it is the PERMANENT answer for a guest with no QEMU agent
    installed. Zero would draw an empty bar under a full disk."""
    from proxploy.models import Vm
    from tests.support import seed_host_row

    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()
        with app.state.sessionmaker() as db:
            h = seed_host_row(db, name="host-02", node="pve2")
            db.add(Vm(host_id=h.id, vmid=300, name="fresh", status="running"))
            db.commit()

        row = next(r for r in c.get("/api/v1/vms").json() if r["vmid"] == 300)

        assert row["mem_bytes"] is None and row["mem_total_bytes"] is None
        assert row["disk_bytes"] is None and row["disk_total_bytes"] is None
        assert row["net_in_bps"] is None and row["net_out_bps"] is None


def test_a_vm_is_listed_once_per_cluster_not_once_per_host(tmp_path, csrf_header,
                                                          bootstrap_admin):
    """The `vms` mirror holds one row per (host, vmid), and every host of a
    cluster reports every guest, so one VM had two rows with two ids.

    Observed on real hardware, where it was worse than cosmetic: the row under
    the host that does not own the guest failed every action with
    `500 Configuration file 'nodes/node1/qemu-server/100.conf' does not exist`
    (doc 12 check 18). The row kept is the one belonging to the host registered
    AT the guest's node.
    """
    from fastapi.testclient import TestClient
    from proxploy.models import Host, Vm
    from tests.support import make_app, seed_host_row

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        with app.state.sessionmaker() as db:
            hid1 = seed_host_row(db, name="host-01", node="pve1").id
            hid2 = seed_host_row(db, name="host-02", node="pve2").id
            for hid in (hid1, hid2):
                db.get(Host, hid).cluster_name = "lab-cluster"
            # One guest, on pve2, mirrored by both hosts' polls.
            for hid in (hid1, hid2):
                db.add(Vm(host_id=hid, vmid=100, name="win11", status="running",
                          node_name="pve2"))
            db.commit()

        rows = c.get("/api/v1/vms").json()
        assert len(rows) == 1, f"one guest listed {len(rows)} times"
        assert rows[0]["host_id"] == hid2, "kept the non-owning host's row"

        # and the cluster summary counts it once
        counts = c.get("/api/v1/cluster/summary").json()["counts"]
        assert counts["vms"] == 1 and counts["vms_running"] == 1


def test_two_standalone_hosts_with_the_same_vmid_are_both_listed(tmp_path, csrf_header,
                                                                bootstrap_admin):
    """The dedupe key is the CLUSTER, not the vmid: a vmid is unique only within
    one cluster, so two unrelated standalone hosts each running VM 100 are two
    real guests and both must survive."""
    from fastapi.testclient import TestClient
    from proxploy.models import Vm
    from tests.support import make_app, seed_host_row

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        with app.state.sessionmaker() as db:
            hid1 = seed_host_row(db, name="host-01", node="pve1").id
            hid2 = seed_host_row(db, name="host-02", node="pve2").id
            db.add(Vm(host_id=hid1, vmid=100, name="win11", status="running",
                      node_name="pve1"))
            db.add(Vm(host_id=hid2, vmid=100, name="ubuntu", status="running",
                      node_name="pve2"))
            db.commit()

        rows = c.get("/api/v1/vms").json()
        assert len(rows) == 2, "two standalone hosts merged into one guest"
        assert {r["host_id"] for r in rows} == {hid1, hid2}
