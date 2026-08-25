"""The Verify action, and the one archive it refuses: PBS verifies its own."""
from fastapi.testclient import TestClient

import json

from proxploy.models import Backup, Host, HostCredential, Job
from tests.support import make_app, seed_snapshot


def _seed(app, storage="nfs-bk"):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.7:8006",
                    node_name="pve1", status="connected")
        db.add(host)
        db.commit()
        # Test restore creates a guest, so its route now checks for the
        # lifecycle token before queueing rather than letting the handler
        # discover it is missing. Verify itself does not need this (it goes
        # over SSH), but one seed serves both files' tests.
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!lc", "token_secret": "s3cret"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token:lifecycle",
                              encrypted_blob=blob, key_version=ver,
                              public_meta="proxploy@pve!lc"))
        db.commit()
        b = Backup(host_id=host.id, storage=storage, guest_type="vm", guest_vmid=201,
                   volid=f"{storage}:backup/vzdump-qemu-201-x.vma.zst")
        db.add(b)
        db.commit()
        return host.id, b.id


def _snapshot(app, host_id, storage="nfs-bk", type_="nfs"):
    seed_snapshot(app, host_id, storage=[{"storage": storage, "node": "pve1",
                                          "type": type_, "content": ["backup"],
                                          "shared": True, "status": "available",
                                          "used_bytes": 1, "total_bytes": 100}])


def test_verify_enqueues_a_job_for_an_archive_on_a_plain_store(tmp_path, csrf_header,
                                                               bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        hid, bid = _seed(app)
        _snapshot(app, hid)
        r = c.post(f"/api/v1/backups/{bid}/verify", headers=csrf_header(c))
        assert r.status_code == 202, r.text
        with app.state.sessionmaker() as db:
            job = db.query(Job).filter_by(kind="backup.verify").one()
            assert job.params["backup_id"] == bid
            assert job.target_id == hid


def test_a_pbs_archive_is_refused_before_the_first_poll_lands(tmp_path, csrf_header,
                                                              bootstrap_admin):
    """The refusal must not depend on having polled yet.

    _refuse_on_pbs read the storage type out of poller.snapshots, so between
    boot and the first poll there is no snapshot, every archive looks like a
    plain store, and a PBS archive is accepted for a full read-back over the
    network. The scheduler starts in that same window, so a sweep due at boot
    would do it to every PBS archive on the host. The type is recorded on the
    row at sync time instead, where PVE already told us.
    """
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        hid, bid = _seed(app, storage="pbs-ds")
        with app.state.sessionmaker() as db:
            db.get(Backup, bid).storage_type = "pbs"
            db.commit()
        # Deliberately NO _snapshot(): this is the cold window.
        assert not app.state.poller.snapshots.get(hid)
        r = c.post(f"/api/v1/backups/{bid}/verify", headers=csrf_header(c))
        assert r.status_code == 409, r.text
        assert "Backup Server" in r.json()["detail"]
        with app.state.sessionmaker() as db:
            assert db.query(Job).filter_by(kind="backup.verify").count() == 0


def test_a_plain_archive_is_still_offered_before_the_first_poll(tmp_path, csrf_header,
                                                                bootstrap_admin):
    """The cold window must not refuse everything, only what PBS owns."""
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        hid, bid = _seed(app)
        with app.state.sessionmaker() as db:
            db.get(Backup, bid).storage_type = "nfs"
            db.commit()
        assert not app.state.poller.snapshots.get(hid)
        r = c.post(f"/api/v1/backups/{bid}/verify", headers=csrf_header(c))
        assert r.status_code == 202, r.text


def test_verify_404s_on_an_archive_that_is_gone(tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        assert c.post("/api/v1/backups/999/verify",
                      headers=csrf_header(c)).status_code == 404


def test_a_host_sweep_can_be_asked_for_without_naming_an_archive(tmp_path,
                                                                csrf_header,
                                                                bootstrap_admin):
    """The verify half of "back up now, verify separately".

    The sweep handler shipped with the schedule and had no door of its own:
    /{backup_id}/verify is one archive, so a Verify Backup with no backup to
    name it against could only be scheduled, never run. This is that door.
    """
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        hid, _ = _seed(app)
        _snapshot(app, hid)
        r = c.post("/api/v1/backups/verify", json={"host_id": hid},
                   headers=csrf_header(c))
        assert r.status_code == 202, r.text
        with app.state.sessionmaker() as db:
            job = db.query(Job).filter_by(kind="backup.verify").one()
            # No backup_id is the whole point: that is what the handler reads
            # as "sweep this host" rather than "read this one archive".
            assert "backup_id" not in job.params
            assert job.params["host_id"] == hid
            assert job.target_id == hid


def test_a_sweep_on_an_unknown_host_is_a_404(tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        assert c.post("/api/v1/backups/verify", json={"host_id": 999},
                      headers=csrf_header(c)).status_code == 404


def test_a_sweep_waits_for_the_check_already_running_on_that_host(tmp_path,
                                                                  csrf_header,
                                                                  bootstrap_admin):
    """Same door the per-archive route stands behind, and for the same reason:
    two full read-backs on one host halve each other and double nothing."""
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        hid, _ = _seed(app)
        _snapshot(app, hid)
        with app.state.sessionmaker() as db:
            db.add(Job(kind="backup.verify", status="running", target_type="host",
                       target_id=hid, params={"host_id": hid}))
            db.commit()
        r = c.post("/api/v1/backups/verify", json={"host_id": hid},
                   headers=csrf_header(c))
        assert r.status_code == 409, r.text


def test_only_one_check_runs_on_a_host_at_a_time(tmp_path, csrf_header,
                                                 bootstrap_admin):
    """A check reads the whole archive off the share. Two at once on one host
    means two full reads competing for the same link.

    The in-flight job is seeded rather than started by a first POST: a real one
    would run and finish on the loop thread while this test is still going, so
    the second POST would sometimes find nothing to refuse.
    """
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        hid, bid = _seed(app)
        _snapshot(app, hid)
        with app.state.sessionmaker() as db:
            db.add(Job(kind="backup.verify", status="running",
                       target_type="host", target_id=hid))
            db.commit()
        r = c.post(f"/api/v1/backups/{bid}/verify", headers=csrf_header(c))
        assert r.status_code == 409
        assert "already" in r.json()["detail"]


def test_verify_is_refused_on_a_pbs_archive(tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        hid, bid = _seed(app, storage="pbs-ds")
        _snapshot(app, hid, storage="pbs-ds", type_="pbs")
        r = c.post(f"/api/v1/backups/{bid}/verify", headers=csrf_header(c))
        assert r.status_code == 409
        assert "Proxmox Backup Server" in r.json()["detail"]
        with app.state.sessionmaker() as db:
            assert db.query(Job).filter_by(kind="backup.verify").count() == 0


def test_test_restore_enqueues_with_the_chosen_storage(tmp_path, csrf_header,
                                                       bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        hid, bid = _seed(app)
        _snapshot(app, hid)
        r = c.post(f"/api/v1/backups/{bid}/test-restore",
                   json={"storage": "local-lvm"}, headers=csrf_header(c))
        assert r.status_code == 202, r.text
        with app.state.sessionmaker() as db:
            job = db.query(Job).filter_by(kind="backup.test_restore").one()
            assert job.params == {"backup_id": bid, "storage": "local-lvm"}
            assert job.target_id == hid


def test_test_restore_is_refused_on_a_pbs_archive(tmp_path, csrf_header,
                                                  bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        hid, bid = _seed(app, storage="pbs-ds")
        _snapshot(app, hid, storage="pbs-ds", type_="pbs")
        r = c.post(f"/api/v1/backups/{bid}/test-restore", json={},
                   headers=csrf_header(c))
        assert r.status_code == 409
        assert "Proxmox Backup Server" in r.json()["detail"]
        with app.state.sessionmaker() as db:
            assert db.query(Job).filter_by(kind="backup.test_restore").count() == 0
