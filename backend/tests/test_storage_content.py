"""Storage content mutations: streamed ISO upload + volume delete, both jobs."""
import asyncio
import json
import os
from pathlib import Path


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


def _api(tmp_path, fake=None, **overrides):
    # ponytail: app.state.sessionmaker only exists inside the FastAPI lifespan
    # (proxploy/main.py), so seeding must happen inside a `with client:` block
    # rather than before it — same precedent as test_storage_api.py::_seed.
    # TestClient tolerates re-entry (each entry reruns lifespan startup/shutdown
    # against the same sqlite file), so we seed here and hand back an unentered
    # client for the test body to enter itself.
    from fastapi.testclient import TestClient
    from tests.support import make_app

    app = make_app(tmp_path, fake=fake, **overrides)
    c = TestClient(app)
    with c:
        hid = _seed(app)
    return app, c, hid


def test_upload_spools_to_disk_and_enqueues_a_job(tmp_path, csrf_header, bootstrap_admin):
    from proxploy.models import Job
    from tests.fakes.pve import FakePVE

    app, c, hid = _api(tmp_path, fake=FakePVE())
    with c:
        bootstrap_admin(c)
        payload = b"\x00" * (3 * 1024 * 1024)  # 3 MiB, larger than one chunk
        r = c.post(f"/api/v1/storage/{hid}/local/content",
                   files={"file": ("ubuntu.iso", payload, "application/octet-stream")},
                   data={"content": "iso", "node": "pve1"},
                   headers=csrf_header(c))
        assert r.status_code == 202
        job = r.json()["job"]
        assert job["kind"] == "storage.upload"
        assert job["target_type"] == "storage" and job["target_id"] == hid
        with app.state.sessionmaker() as db:
            row = db.get(Job, job["id"])
            assert row.params["filename"] == "ubuntu.iso"
            assert row.params["size_bytes"] == len(payload)
            spooled = Path(row.params["path"])
            assert spooled.parent == app.state.settings.data_dir / "uploads"
            # the bytes really are on disk, not in the request object
            assert spooled.stat().st_size == len(payload)


def test_upload_over_the_cap_is_413_and_leaves_no_temp_file(tmp_path, csrf_header,
                                                            bootstrap_admin):
    from tests.fakes.pve import FakePVE

    app, c, hid = _api(tmp_path, fake=FakePVE(), storage_upload_max_bytes=1024)
    with c:
        bootstrap_admin(c)
        r = c.post(f"/api/v1/storage/{hid}/local/content",
                   files={"file": ("big.iso", b"x" * 5000)},
                   data={"content": "iso", "node": "pve1"},
                   headers=csrf_header(c))
        assert r.status_code == 413
        assert "1024" in r.text
        uploads = app.state.settings.data_dir / "uploads"
        assert not uploads.exists() or list(uploads.iterdir()) == []


def test_the_upload_route_never_buffers_the_whole_body_in_memory(tmp_path):
    """A one-line `await file.read()` turns a 5 GB ISO into 5 GB of RSS. The
    streaming loop is the point of this route, so guard it like a lint rather
    than trusting review (tests/test_isolation_lint.py precedent)."""
    import proxploy.api.storage as mod

    src = Path(mod.__file__).read_text()
    assert "file.read()" not in src
    assert "await file.read" not in src
    assert "file.file.read(" in src  # the chunked loop


def test_upload_job_posts_to_proxmox_and_always_deletes_the_temp_file(tmp_path):
    from proxploy.jobs import JobBackend
    from proxploy.models import Job
    from tests.fakes.pve import FakePVE
    from tests.support import make_job_app

    async def run():
        fake = FakePVE()
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.storagejobs  # noqa: F401 — registers handlers
        backend = JobBackend(app)
        hid = _seed(app)
        spool = tmp_path / "ubuntu.iso"
        spool.write_bytes(b"ISO-BYTES")
        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(db, kind="storage.upload", target_type="storage",
                                     target_id=hid,
                                     params={"host_id": hid, "node": "pve1",
                                             "storage": "local", "content": "iso",
                                             "filename": "ubuntu.iso",
                                             "path": str(spool), "size_bytes": 9}).id
        await backend.wait(job_id, timeout=10)
        assert fake.uploads == [{"node": "pve1", "storage": "local", "content": "iso",
                                 "filename": "ubuntu.iso", "bytes": b"ISO-BYTES"}]
        with app.state.sessionmaker() as db:
            job = db.get(Job, job_id)
            assert job.status == "succeeded"
            assert job.result["volid"] == "local:iso/ubuntu.iso"
            assert job.result["exitstatus"] == "OK"
        assert not spool.exists()  # deleted in the finally

    asyncio.run(run())


def test_upload_job_deletes_the_temp_file_even_when_proxmox_fails(tmp_path):
    from proxploy.jobs import JobBackend
    from proxploy.models import Job
    from tests.fakes.pve import FakePVE
    from tests.support import make_job_app

    async def run():
        fake = FakePVE(task_exit="upload failed: no space left on device")
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.storagejobs  # noqa: F401
        backend = JobBackend(app)
        hid = _seed(app)
        spool = tmp_path / "doomed.iso"
        spool.write_bytes(b"x")
        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(db, kind="storage.upload", target_type="storage",
                                     target_id=hid,
                                     params={"host_id": hid, "node": "pve1",
                                             "storage": "local", "content": "iso",
                                             "filename": "doomed.iso",
                                             "path": str(spool), "size_bytes": 1}).id
        await backend.wait(job_id, timeout=10)
        with app.state.sessionmaker() as db:
            assert db.get(Job, job_id).status == "failed"
        assert not spool.exists()

    asyncio.run(run())


def test_delete_volume_route_enqueues_and_audits_the_volid(tmp_path, csrf_header,
                                                           bootstrap_admin):
    from proxploy.models import AuditEvent
    from tests.fakes.pve import FakePVE

    app, c, hid = _api(tmp_path, fake=FakePVE())
    with c:
        bootstrap_admin(c)
        volid = "local:iso/ubuntu-24.04.iso"
        r = c.delete(f"/api/v1/storage/{hid}/local/content/{volid}?node=pve1",
                     headers=csrf_header(c))
        assert r.status_code == 202
        job = r.json()["job"]
        assert job["kind"] == "storage.delete_volume"
        assert job["params"]["volid"] == volid
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="storage.delete_volume").one()
            assert row.target_type == "storage" and row.target_id == hid
            assert row.params["volid"] == volid
            assert row.job_id == job["id"]


def test_delete_volume_job_calls_delete_and_awaits_the_task(tmp_path):
    from proxploy.jobs import JobBackend
    from proxploy.models import Job
    from tests.fakes.pve import FakePVE
    from tests.support import make_job_app

    async def run():
        fake = FakePVE()
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.storagejobs  # noqa: F401
        backend = JobBackend(app)
        hid = _seed(app)
        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(
                db, kind="storage.delete_volume", target_type="storage", target_id=hid,
                params={"host_id": hid, "node": "pve1", "storage": "local",
                        "volid": "local:iso/old.iso"}).id
        await backend.wait(job_id, timeout=10)
        assert fake.deleted_volumes == [("pve1", "local", "local:iso/old.iso")]
        with app.state.sessionmaker() as db:
            job = db.get(Job, job_id)
            assert job.status == "succeeded"
            assert job.result["volid"] == "local:iso/old.iso"

    asyncio.run(run())
