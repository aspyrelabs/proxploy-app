# backend/tests/test_storage_api.py
"""GET /storage reads: list from the poller snapshot, detail + content live."""
import json


def _seed(tmp_path, fake=None):
    # ponytail: app.state.sessionmaker is only set inside the FastAPI lifespan
    # (proxploy/main.py), so seeding must happen inside a `with client:` block
    # rather than before it. TestClient tolerates re-entry (each entry reruns
    # lifespan startup/shutdown against the same sqlite file), so we seed here
    # and hand back an unentered client for the test body to enter itself.
    from fastapi.testclient import TestClient
    from proxploy.models import HostCredential
    from tests.support import make_app, seed_host_row

    app = make_app(tmp_path, fake=fake)
    c = TestClient(app)
    with c:
        with app.state.sessionmaker() as db:
            host = seed_host_row(db)
            blob, ver = app.state.secretstore.encrypt(json.dumps(
                {"token_id": "proxploy@pve!store", "token_secret": "s3cret"}).encode())
            db.add(HostCredential(host_id=host.id, kind="api_token:monitoring",
                                  encrypted_blob=blob, key_version=ver,
                                  public_meta="proxploy@pve!store"))
            db.commit()
            hid = host.id
    return app, c, hid


LOCAL_PVE1 = {"storage": "local", "node": "pve1", "used_bytes": 100,
              "total_bytes": 400, "type": "dir",
              "content": ["iso", "vztmpl"], "shared": False, "status": "available"}
LOCAL_PVE2 = {**LOCAL_PVE1, "node": "pve2", "used_bytes": 50}
PBS_PVE1 = {"storage": "pbs-main", "node": "pve1", "used_bytes": 10,
            "total_bytes": 1000, "type": "pbs", "content": ["backup"],
            "shared": True, "status": "available"}
PBS_PVE2 = {**PBS_PVE1, "node": "pve2"}


def test_list_serves_the_enriched_snapshot_fields(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import seed_snapshot

    app, c, hid = _seed(tmp_path)
    with c:
        bootstrap_admin(c)
        seed_snapshot(app, hid, storage=[LOCAL_PVE1])
        rows = c.get("/api/v1/storage").json()
        assert rows == [{"host_id": hid, "host_name": "host-01", "node": "pve1",
                         "storage": "local", "type": "dir",
                         "content": ["iso", "vztmpl"], "shared": False,
                         "status": "available", "used_bytes": 100,
                         "total_bytes": 400, "used_pct": 25.0}]


def test_list_dedupes_shared_storage_but_keeps_local_per_node(tmp_path, csrf_header,
                                                              bootstrap_admin):
    """A shared datastore is reported once per node and is ONE datastore; a
    local one with the same name on two nodes is two. `shared` came off the
    same poll row, so this is exact rather than a heuristic."""
    from tests.support import seed_snapshot

    app, c, hid = _seed(tmp_path)
    with c:
        bootstrap_admin(c)
        seed_snapshot(app, hid,
                      storage=[LOCAL_PVE1, LOCAL_PVE2, PBS_PVE1, PBS_PVE2])
        rows = c.get("/api/v1/storage").json()
        assert [(r["storage"], r["node"]) for r in rows] == [
            ("local", "pve1"), ("local", "pve2"), ("pbs-main", "pve1")]


def test_detail_is_a_live_passthrough_and_lists_every_serving_node(tmp_path, csrf_header,
                                                                   bootstrap_admin):
    from tests.fakes.pve import FakePVE
    from tests.support import seed_snapshot

    fake = FakePVE()
    fake.storage_status_response = {"type": "pbs", "content": "backup",
                                    "active": 1, "enabled": 1, "shared": 1,
                                    "used": 10, "avail": 990, "total": 1000}
    app, c, hid = _seed(tmp_path, fake=fake)
    with c:
        bootstrap_admin(c)
        seed_snapshot(app, hid, storage=[PBS_PVE1, PBS_PVE2])
        d = c.get(f"/api/v1/storage/{hid}/pbs-main").json()
        assert d["type"] == "pbs" and d["content"] == ["backup"]
        assert d["shared"] is True and d["status"] == "available"
        assert d["used_bytes"] == 10 and d["avail_bytes"] == 990
        assert d["total_bytes"] == 1000 and d["used_pct"] == 1.0
        assert d["nodes"] == ["pve1", "pve2"]


def test_detail_404s_an_unknown_host(tmp_path, csrf_header, bootstrap_admin):
    app, c, hid = _seed(tmp_path)
    with c:
        bootstrap_admin(c)
        assert c.get("/api/v1/storage/9999/local").status_code == 404


def test_content_passes_the_filter_through_and_normalises_rows(tmp_path, csrf_header,
                                                               bootstrap_admin):
    from tests.fakes.pve import FakePVE
    from tests.support import seed_snapshot

    fake = FakePVE()
    fake.content_by_storage = {"local": [
        {"volid": "local:iso/ubuntu-24.04.iso", "format": "iso", "size": 6000,
         "content": "iso", "ctime": 1730000000},
        {"volid": "local:backup/vzdump-qemu-100.vma.zst", "format": "vma.zst",
         "size": 900, "content": "backup", "vmid": 100, "ctime": 1730000100,
         "notes": "nightly", "verification": {"state": "ok"}},
    ]}
    app, c, hid = _seed(tmp_path, fake=fake)
    with c:
        bootstrap_admin(c)
        seed_snapshot(app, hid, storage=[LOCAL_PVE1])
        rows = c.get(f"/api/v1/storage/{hid}/local/content?content=iso").json()
        assert rows == [{"volid": "local:iso/ubuntu-24.04.iso", "format": "iso",
                         "size": 6000, "used": 0, "vmid": None,
                         "ctime": 1730000000, "content": "iso", "notes": None,
                         "verification": None}]
        all_rows = c.get(f"/api/v1/storage/{hid}/local/content").json()
        assert len(all_rows) == 2
        assert all_rows[1]["verification"] == {"state": "ok"}


def test_storage_reads_require_a_session(tmp_path):
    app, c, hid = _seed(tmp_path)
    with c:
        assert c.get("/api/v1/storage").status_code == 401
        assert c.get(f"/api/v1/storage/{hid}/local").status_code == 401
        assert c.get(f"/api/v1/storage/{hid}/local/content").status_code == 401
