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
        # attach/edit/detach all run under "lifecycle" (Datastore.Allocate).
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!store", "token_secret": "s3cret"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token:lifecycle",
                              encrypted_blob=blob, key_version=ver,
                              public_meta="proxploy@pve!store"))
        # Mandatory at enrolment, and the ONLY token that may audit
        # /cluster/resources: the post-write snapshot refresh reads on this one,
        # never on the lifecycle token it wrote with (see _resync_snapshot).
        db.add(HostCredential(host_id=host.id, kind="api_token:monitoring",
                              encrypted_blob=blob, key_version=ver,
                              public_meta="proxploy@pve!audit"))
        db.commit()
        return host.id


def _api(tmp_path, fake=None):
    # ponytail: app.state.sessionmaker only exists inside the FastAPI lifespan
    # (proxploy/main.py), so seeding must happen inside a `with client:` block
    # rather than before it: same precedent as test_storage_content.py::_api.
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
    `config.storage`/`config.type` used to silently override the route's own, 
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
            # 4. these routes are synchronous: no job row, so no jobs.params copy
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
    """Doc 05: POST/PATCH are admin, DELETE is owner; detaching is the one that
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


def _schedule(app, host_id, name="Nightly backup", enabled=True):
    from proxploy.models import Schedule

    with app.state.sessionmaker() as db:
        db.add(Schedule(name=name, job_kind="backup.run", cron="0 2 * * *",
                        timezone="UTC", params={"host_id": host_id}, enabled=enabled))
        db.commit()


def test_detach_is_refused_when_it_would_strand_a_backup_job(tmp_path, csrf_header,
                                                             bootstrap_admin):
    """A scheduled backup.run names no storage of its own, so PVE writes to
    whichever one accepts `backup` content. Detaching the last of those leaves
    the job with nowhere to write, and it only finds out at 2am."""
    from tests.fakes.pve import FakePVE
    from tests.support import seed_snapshot

    fake = FakePVE()
    app, c, hid = _api(tmp_path, fake=fake)
    with c:
        bootstrap_admin(c)
        _schedule(app, hid)
        seed_snapshot(app, hid, storage=[
            {"type": "storage", "storage": "pbs-ds", "content": "backup"},
            {"type": "storage", "storage": "local-lvm", "content": "rootdir,images"},
        ])
        r = c.delete(f"/api/v1/storage/{hid}/pbs-ds", headers=csrf_header(c))
        assert r.status_code == 409
        assert "Nightly backup" in r.json()["detail"]
        assert fake.storage_removes == []


def test_detach_allows_one_of_several_backup_datastores(tmp_path, csrf_header,
                                                        bootstrap_admin):
    """The guard is about stranding the job, not about the content type: with
    another datastore still accepting backups the job keeps running."""
    from tests.fakes.pve import FakePVE
    from tests.support import seed_snapshot

    fake = FakePVE()
    app, c, hid = _api(tmp_path, fake=fake)
    with c:
        bootstrap_admin(c)
        _schedule(app, hid)
        seed_snapshot(app, hid, storage=[
            {"type": "storage", "storage": "pbs-ds", "content": "backup"},
            {"type": "storage", "storage": "nfs-media", "content": "backup,iso"},
        ])
        r = c.delete(f"/api/v1/storage/{hid}/pbs-ds", headers=csrf_header(c))
        assert r.status_code == 200
        assert fake.storage_removes == ["pbs-ds"]


def test_edit_refreshes_the_snapshot_the_list_is_served_from(tmp_path, csrf_header,
                                                             bootstrap_admin):
    """GET "" reads the poll snapshot, so without this the Backups page kept
    counting a datastore whose `backup` content had just been unticked, until
    the next poll came round. Asserted through the LIST, in the snapshot's own
    row shape: writing raw /cluster/resources rows back into that field reported
    every datastore as type "storage" (the resource type, not the plugin) with
    0 bytes."""
    from tests.fakes.pve import FakePVE
    from tests.support import seed_snapshot

    fake = FakePVE(resources=[{"type": "storage", "storage": "nfs-media", "node": "pve1",
                               "plugintype": "nfs", "content": "iso", "shared": 1,
                               "status": "available", "disk": 10, "maxdisk": 100}])
    app, c, hid = _api(tmp_path, fake=fake)
    with c:
        bootstrap_admin(c)
        seed_snapshot(app, hid, storage=[{"storage": "nfs-media", "node": "pve1",
                                          "type": "nfs", "content": ["backup", "iso"],
                                          "shared": True, "status": "available",
                                          "used_bytes": 10, "total_bytes": 100}])
        r = c.patch(f"/api/v1/storage/{hid}/nfs-media",
                    json={"config": {"content": "iso"}}, headers=csrf_header(c))
        assert r.status_code == 200
        row = c.get("/api/v1/storage").json()[0]
        assert row["content"] == ["iso"]          # the edit, without waiting for a poll
        assert row["type"] == "nfs"               # the plugin, not the resource type
        assert row["total_bytes"] == 100


def test_edit_refreshes_the_snapshot_of_every_member_of_the_cluster(tmp_path, csrf_header,
                                                                    bootstrap_admin):
    """GET "" dedupes storage across every enrolled member's snapshot and keeps
    whichever it sees first, so refreshing only the host that was written to
    left a peer's stale copy to win that race on a two-node cluster."""
    from proxploy.models import Host, HostCredential
    from tests.fakes.pve import FakePVE
    from tests.support import seed_snapshot

    stale = {"storage": "nfs-media", "node": "pve1", "type": "nfs",
             "content": ["iso"], "shared": True, "status": "available",
             "used_bytes": 10, "total_bytes": 100}
    fake = FakePVE(resources=[{"type": "storage", "storage": "nfs-media", "node": "pve1",
                               "plugintype": "nfs", "content": "iso,backup", "shared": 1,
                               "status": "available", "disk": 10, "maxdisk": 100}])
    app, c, hid = _api(tmp_path, fake=fake)
    with c:
        bootstrap_admin(c)
        with app.state.sessionmaker() as db:
            db.get(Host, hid).cluster_name = "lab"
            peer = Host(name="host-02", address="https://10.0.0.10:8006", node_name="pve2",
                        status="connected", cluster_name="lab")
            db.add(peer)
            db.commit()
            peer_id = peer.id
            blob, ver = app.state.secretstore.encrypt(json.dumps(
                {"token_id": "proxploy@pve!store", "token_secret": "s3cret"}).encode())
            db.add(HostCredential(host_id=peer_id, kind="api_token:lifecycle",
                                  encrypted_blob=blob, key_version=ver,
                                  public_meta="proxploy@pve!store"))
            db.add(HostCredential(host_id=peer_id, kind="api_token:monitoring",
                                  encrypted_blob=blob, key_version=ver,
                                  public_meta="proxploy@pve!audit"))
            db.commit()
        # The peer is seeded FIRST, so its copy is the one the dedupe keeps.
        seed_snapshot(app, peer_id, storage=[dict(stale)])
        seed_snapshot(app, hid, storage=[dict(stale)])
        r = c.patch(f"/api/v1/storage/{hid}/nfs-media",
                    json={"config": {"content": "iso,backup"}}, headers=csrf_header(c))
        assert r.status_code == 200
        assert c.get("/api/v1/storage").json()[0]["content"] == ["iso", "backup"]


def test_a_read_that_sees_no_storage_never_wipes_the_snapshot(tmp_path, csrf_header,
                                                              bootstrap_admin):
    """The refresh reads /cluster/resources, which returns only what the token
    may audit. Reading it on the LIFECYCLE token (no Datastore.Audit) came back
    empty, and writing that emptiness into the snapshot took every datastore off
    the Storage page until the next poll. An empty read changes nothing."""
    from tests.fakes.pve import FakePVE
    from tests.support import seed_snapshot

    had = [{"storage": "local-lvm", "node": "pve1", "type": "lvmthin",
            "content": ["rootdir", "images"], "shared": False,
            "status": "available", "used_bytes": 10, "total_bytes": 100}]
    app, c, hid = _api(tmp_path, fake=FakePVE(resources=[]))
    with c:
        bootstrap_admin(c)
        seed_snapshot(app, hid, storage=[dict(had[0])])
        r = c.patch(f"/api/v1/storage/{hid}/local-lvm",
                    json={"config": {"content": "rootdir,images"}}, headers=csrf_header(c))
        assert r.status_code == 200
        assert app.state.poller.snapshots[hid].storage == had
        assert len(c.get("/api/v1/storage").json()) == 1
