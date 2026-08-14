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
