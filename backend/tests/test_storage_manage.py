# backend/tests/test_storage_manage.py
"""Attach/edit/detach storage. Credentials pass through, never persist."""
import json

PBS_PASSWORD = "pbs-sup3r-s3cret-do-not-leak"


def _seed(app):
    from proxploy.models import Host, HostCredential

    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.9:8006", node_name="pve1",
                    status="connected", pve_version="8.4.1")
        db.add(host)
        db.commit()
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!store", "token_secret": "s3cret"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token",
                              encrypted_blob=blob, key_version=ver,
                              public_meta="proxploy@pve!store"))
        db.commit()
        return host.id


def _api(tmp_path, fake=None):
    # ponytail: app.state.sessionmaker only exists inside the FastAPI lifespan
    # (proxploy/main.py), so seeding must happen inside a `with client:` block
    # rather than before it — same precedent as test_storage_content.py::_api.
    from fastapi.testclient import TestClient
    from tests.support import make_app

    app = make_app(tmp_path, fake=fake)
    c = TestClient(app)
    with c:
        hid = _seed(app)
    return app, c, hid


def test_attach_creates_the_storage_upstream_and_audits(tmp_path, csrf_header,
                                                        bootstrap_admin):
    from proxploy.models import AuditEvent
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    app, c, hid = _api(tmp_path, fake=fake)
    with c:
        bootstrap_admin(c)
        r = c.post("/api/v1/storage",
                   json={"host_id": hid, "storage": "nfs-media", "type": "nfs",
                         "config": {"server": "10.0.0.30", "export": "/media",
                                    "content": "iso,vztmpl"}},
                   headers=csrf_header(c))
        assert r.status_code == 201
        assert r.json() == {"host_id": hid, "storage": "nfs-media", "type": "nfs"}
        assert fake.storage_creates == [{"storage": "nfs-media", "type": "nfs",
                                         "server": "10.0.0.30", "export": "/media",
                                         "content": "iso,vztmpl"}]
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="storage.create").one()
            assert row.target_type == "storage" and row.target_id == hid
            assert row.params["storage"] == "nfs-media"


def test_config_storage_collision_does_not_override_the_route_storage(tmp_path, csrf_header,
                                                                       bootstrap_admin):
    """BLOCKING 2 regression: storage.py applies NO key filter at all (a
    deliberate free-form plugin passthrough), so a caller-supplied
    `config.storage`/`config.type` used to silently override the route's own —
    verified live: `{"storage": "newpbs", ..., "config": {"storage": "local",
    "type": "dir", ...}}` returned 201 saying newpbs while creating local.
    Asserted against what FakePVE actually recorded, not the response body."""
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    app, c, hid = _api(tmp_path, fake=fake)
    with c:
        bootstrap_admin(c)
        r = c.post("/api/v1/storage",
                   json={"host_id": hid, "storage": "newpbs", "type": "pbs",
                         "config": {"storage": "local", "type": "dir",
                                    "path": "/mnt/x"}},
                   headers=csrf_header(c))
        assert r.status_code == 201, r.text
        assert fake.storage_creates == [
            {"path": "/mnt/x", "storage": "newpbs", "type": "pbs"}]


def test_pbs_attach_never_persists_or_echoes_the_password(tmp_path, csrf_header,
                                                          bootstrap_admin):
    """The storage-shaped sibling of tests/test_no_secret_echo.py. A PBS attach
    is the one Phase 6 request body carrying a live credential; it must reach
    Proxmox verbatim and reach durable storage nowhere."""
    from proxploy.models import AuditEvent, Job
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    app, c, hid = _api(tmp_path, fake=fake)
    with c:
        bootstrap_admin(c)
        r = c.post("/api/v1/storage",
                   json={"host_id": hid, "storage": "pbs-main", "type": "pbs",
                         "config": {"server": "10.0.0.20", "datastore": "backups",
                                    "username": "proxploy@pbs",
                                    "password": PBS_PASSWORD,
                                    "fingerprint": "AA:BB:CC:DD"}},
                   headers=csrf_header(c))
        assert r.status_code == 201
        # 1. it reached Proxmox unmodified
        assert fake.storage_creates[0]["password"] == PBS_PASSWORD
        # 2. it is not in the response body (which echoes no config at all)
        assert PBS_PASSWORD not in r.text
        assert "config" not in r.json()
        with app.state.sessionmaker() as db:
            rows = db.query(AuditEvent).all()
            # 3. not in ANY audit row's params, and the nested key is masked
            assert PBS_PASSWORD not in json.dumps([x.params for x in rows])
            attach = next(x for x in rows if x.action == "storage.create")
            assert attach.params["config"]["password"] == "[redacted]"
            assert attach.params["config"]["server"] == "10.0.0.20"  # not over-redacted
            # 4. these routes are synchronous — no job row, so no jobs.params copy
            assert db.query(Job).count() == 0
        # 5. and it does not come back out of GET /audit either
        assert PBS_PASSWORD not in c.get("/api/v1/audit").text


def test_edit_sends_only_the_given_keys_and_audits_key_names(tmp_path, csrf_header,
                                                             bootstrap_admin):
    from proxploy.models import AuditEvent
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    app, c, hid = _api(tmp_path, fake=fake)
    with c:
        bootstrap_admin(c)
        r = c.patch(f"/api/v1/storage/{hid}/nfs-media",
                    json={"config": {"content": "iso,backup", "password": PBS_PASSWORD}},
                    headers=csrf_header(c))
        assert r.status_code == 200
        assert r.json() == {"host_id": hid, "storage": "nfs-media",
                            "updated": ["content", "password"]}
        assert PBS_PASSWORD not in r.text
        assert fake.storage_updates == [("nfs-media", {"content": "iso,backup",
                                                       "password": PBS_PASSWORD})]
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="storage.update").one()
            assert row.params["keys"] == ["content", "password"]
            assert PBS_PASSWORD not in json.dumps(row.params)


def test_detach_removes_upstream_and_audits(tmp_path, csrf_header, bootstrap_admin):
    from proxploy.models import AuditEvent
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    app, c, hid = _api(tmp_path, fake=fake)
    with c:
        bootstrap_admin(c)  # the bootstrap user is an OWNER
        r = c.delete(f"/api/v1/storage/{hid}/nfs-media", headers=csrf_header(c))
        assert r.status_code == 200
        assert r.json() == {"host_id": hid, "storage": "nfs-media", "detached": True}
        assert fake.storage_removes == ["nfs-media"]
        with app.state.sessionmaker() as db:
            assert db.query(AuditEvent).filter_by(action="storage.remove").count() == 1


def test_detach_is_owner_only_while_attach_is_admin(tmp_path, csrf_header,
                                                    bootstrap_admin):
    """Doc 05: POST/PATCH are admin, DELETE is owner — detaching is the one that
    can strand a guest's disks behind a removed definition."""
    from fastapi.testclient import TestClient
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    app, c, hid = _api(tmp_path, fake=fake)
    with c:
        bootstrap_admin(c)
        c.post("/api/v1/users",
               json={"email": "admin2@example.com", "password": "correct-horse-battery",
                     "display_name": "Admin Two", "role": "admin"},
               headers=csrf_header(c))
        c2 = TestClient(app)
        c2.post("/api/v1/auth/login",
                json={"email": "admin2@example.com", "password": "correct-horse-battery"},
                headers=csrf_header(c2))
        ok = c2.post("/api/v1/storage",
                     json={"host_id": hid, "storage": "dir-scratch", "type": "dir",
                           "config": {"path": "/mnt/scratch"}},
                     headers=csrf_header(c2))
        assert ok.status_code == 201
        denied = c2.delete(f"/api/v1/storage/{hid}/dir-scratch", headers=csrf_header(c2))
        assert denied.status_code == 403
        assert fake.storage_removes == []


def test_upstream_failure_is_a_502_that_leaks_no_secret(tmp_path, csrf_header,
                                                        bootstrap_admin):
    from tests.fakes.pve import FakePVE

    fake = FakePVE(fail=True)
    app, c, hid = _api(tmp_path, fake=fake)
    with c:
        bootstrap_admin(c)
        r = c.post("/api/v1/storage",
                   json={"host_id": hid, "storage": "pbs-main", "type": "pbs",
                         "config": {"server": "10.0.0.20", "datastore": "backups",
                                    "password": PBS_PASSWORD}},
                   headers=csrf_header(c))
        assert r.status_code == 502
        assert PBS_PASSWORD not in r.text
        assert "s3cret" not in r.text  # the host API token, scrubbed by _wrap
