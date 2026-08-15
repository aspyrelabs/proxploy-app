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
            db.add(Vm(host_id=h.id, vmid=100, name="win11", status="running",
                      cpu_cores=4, mem_bytes=8589934592,
                      disk_bytes=68719476736, uptime_s=172800))
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
