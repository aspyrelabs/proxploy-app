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
        # upload/delete_content (job) run under "lifecycle"
        # (Datastore.AllocateSpace); the pre-upload overwrite check
        # (api/storage.py::_refuse_silent_overwrite) is a plain read, monitoring.
        for cap in ("monitoring", "lifecycle"):
            blob, ver = app.state.secretstore.encrypt(json.dumps(
                {"token_id": f"proxploy@pve!store-{cap}",
                 "token_secret": "s3cret"}).encode())
            db.add(HostCredential(host_id=host.id, kind=f"api_token:{cap}",
                                  encrypted_blob=blob, key_version=ver,
                                  public_meta=f"proxploy@pve!store-{cap}"))
        db.commit()
        return host.id


def _api(tmp_path, fake=None, **overrides):
    # ponytail: app.state.sessionmaker only exists inside the FastAPI lifespan
    # (proxploy/main.py), so seeding must happen inside a `with client:` block
    # rather than before it: same precedent as test_storage_api.py::_seed.
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
            spooled = Path(row.params["spool_path"])
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
        import proxploy.services.storagejobs  # noqa: F401  (registers handlers)
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
                                             "spool_path": str(spool), "size_bytes": 9}).id
        await backend.wait(job_id, timeout=10)
        assert fake.uploads == [{"node": "pve1", "storage": "local", "content": "iso",
                                 "filename": "ubuntu.iso", "bytes": b"ISO-BYTES"}]
        with app.state.sessionmaker() as db:
            job = db.get(Job, job_id)
            assert job.status == "succeeded"
            assert job.result["volid"] == "local:iso/ubuntu.iso"
            assert job.result["exitstatus"] == "OK"
        assert not spool.exists()  # deleted by the runner on exit

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
                                             "spool_path": str(spool), "size_bytes": 1}).id
        await backend.wait(job_id, timeout=10)
        with app.state.sessionmaker() as db:
            assert db.get(Job, job_id).status == "failed"
        assert not spool.exists()

    asyncio.run(run())


def test_an_upload_cancelled_while_still_queued_deletes_its_spool_file(
        tmp_path, monkeypatch):
    """Cancel an upload that is still waiting behind MAX_CONCURRENT other jobs
    and the handler never runs at all, so it cannot be the thing that removes
    the spool file: the job settles `canceled`, and a multi-GB ISO would sit in
    data_dir/uploads until the next restart cleared it.

    Both no-handler cancel windows are exercised, because they leave the runner
    at two different places: `victim_a` is cancelled in the same breath as the
    enqueue, before `_spawn` has had a loop turn (`_cancel_requested`, an early
    return); `victim_b` is cancelled once it already has a Task blocked on the
    semaphore (a CancelledError out of the acquire). Neither ever reaches
    `HANDLERS["storage.upload"]`.
    """
    from proxploy.jobs import HANDLERS, JobBackend
    from proxploy.jobs.backend import MAX_CONCURRENT
    from proxploy.models import Job
    from tests.fakes.pve import FakePVE
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path, fake=FakePVE())
        import proxploy.services.storagejobs  # noqa: F401  (registers handlers)
        backend = JobBackend(app)
        hid = _seed(app)

        gate = asyncio.Event()
        started = [asyncio.Event() for _ in range(MAX_CONCURRENT)]

        async def hog(ctx, params):
            started[params["i"]].set()
            await gate.wait()
            return {}

        monkeypatch.setitem(HANDLERS, "test.hog", hog)

        async def never(ctx, params):
            raise AssertionError("the upload handler must not run for a "
                                 "job cancelled while it was still queued")

        monkeypatch.setitem(HANDLERS, "storage.upload", never)

        with app.state.sessionmaker() as db:
            hog_ids = [backend.enqueue(db, kind="test.hog", params={"i": i}).id
                       for i in range(MAX_CONCURRENT)]
        await asyncio.gather(*(asyncio.wait_for(e.wait(), timeout=5) for e in started))

        updir = app.state.settings.data_dir / "uploads"
        updir.mkdir(parents=True, exist_ok=True)

        def enqueue_upload(name):
            spool = updir / name
            spool.write_bytes(b"pretend-multi-gb-iso")
            with app.state.sessionmaker() as db:
                job_id = backend.enqueue(
                    db, kind="storage.upload", target_type="storage", target_id=hid,
                    params={"host_id": hid, "node": "pve1", "storage": "local",
                            "content": "iso", "filename": name,
                            "spool_path": str(spool), "size_bytes": 20}).id
            return job_id, spool

        job_a, spool_a = enqueue_upload("pre-spawn.iso")
        assert backend.cancel(job_a) is True   # no await since enqueue: _pending

        job_b, spool_b = enqueue_upload("queued.iso")
        await asyncio.sleep(0.02)              # let _spawn block it on the semaphore
        assert backend.cancel(job_b) is True

        for job_id, spool in ((job_a, spool_a), (job_b, spool_b)):
            assert await backend.wait(job_id, timeout=5) is True
            with app.state.sessionmaker() as db:
                assert db.get(Job, job_id).status == "canceled"
            assert not spool.exists(), f"{spool.name} was left behind"

        gate.set()  # release the hogs; the pool must still work for them
        for hid_ in hog_ids:
            assert await backend.wait(hid_, timeout=5) is True

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


def test_startup_clears_stale_spool_files_left_by_a_crash(tmp_path):
    """The in-process job runner never resumes a job across a restart, 
    sweep_orphans (proxploy/jobs/backend.py) only ever marks a queued/running
    job `interrupted`, full stop. So a spool file left in `data_dir/uploads`
    at boot provably belongs to a job that can never run again; leaving it
    there strands a multi-GB temp file forever after every crash/OOM/deploy
    mid-upload. main.py's lifespan clears the whole directory at startup."""
    from fastapi.testclient import TestClient
    from tests.support import make_app

    app = make_app(tmp_path)
    stale_dir = tmp_path / "uploads"
    stale_dir.mkdir()
    stale = stale_dir / "abandoned.upload"
    stale.write_bytes(b"orphaned bytes from a dead process")

    with TestClient(app):
        pass  # lifespan startup/shutdown ran

    assert not stale.exists()


def test_proxmoxer_streams_large_uploads_via_requests_toolbelt(monkeypatch):
    """Covers the leg the fakes cannot see: FakePVE.upload replaces
    `self._connect()` entirely, so the browser->spool leg (chunked, proven
    above) is real but the spool->PVE leg goes through proxmoxer's actual
    `requests` backend even in tests, and that backend silently buffers (or
    outright refuses, `OverflowError`, above ~2 GiB) any upload over 10 MiB
    unless `requests_toolbelt` is importable. This asserts the dependency is
    present AND that proxmoxer picks the true streaming branch (a
    `MultipartEncoder` body, never a bare dict) for a file above that
    threshold, by intercepting `requests.Session.request` before it would hit
    the network. What remains unproven without a real PVE: actual bytes
    reaching the wire and PVE accepting them; that is exercised by the
    `pve_integration`-marked tests, not this one.
    """
    import requests_toolbelt

    assert hasattr(requests_toolbelt, "MultipartEncoder")

    import io
    from types import SimpleNamespace

    import proxmoxer.backends.https as pveh

    captured = {}

    def fake_request(self, method, url, params=None, data=None, headers=None,
                     *rest, **kw):
        captured["data"] = data
        captured["headers"] = headers
        return SimpleNamespace(ok=True)

    monkeypatch.setattr(pveh.requests.Session, "request", fake_request)

    session = pveh.ProxmoxHttpSession()
    session.auth = SimpleNamespace(verify_ssl=True, timeout=5, get_cookies=lambda: None)
    big = io.BytesIO(b"x" * (pveh.STREAMING_SIZE_THRESHOLD + 1))
    big.name = "big.iso"
    session.request("POST", "https://pve.example/nodes/pve1/storage/local/upload",
                    data={"filename": big, "content": "iso"})

    assert isinstance(captured["data"], requests_toolbelt.MultipartEncoder)
    assert captured["headers"]["Content-Type"].startswith("multipart/form-data")


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


def _fake_with_volume(volid, size=4242):
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    fake.content_by_storage = {"local": [{"volid": volid, "size": size,
                                          "content": "iso", "ctime": 1}]}
    return fake


def test_upload_onto_an_existing_name_stops_and_asks_for_confirmation(
        tmp_path, csrf_header, bootstrap_admin):
    """An upload whose name already exists REPLACES the volume and PVE does it
    silently: the second of two uploads under one name simply wins (seen on PVE
    9.2.6, 2026-08-10). An ISO a VM is booting from can be swapped underneath
    it. A collision now stops and asks, naming what would be replaced."""
    app, c, hid = _api(tmp_path, fake=_fake_with_volume("local:iso/ubuntu.iso"))
    with c:
        bootstrap_admin(c)
        r = c.post(f"/api/v1/storage/{hid}/local/content",
                   files={"file": ("ubuntu.iso", b"x" * 16)},
                   data={"content": "iso", "node": "pve1"},
                   headers=csrf_header(c))
        assert r.status_code == 409, r.text
        body = r.json()
        assert body["error"] == "volume_exists"
        # Named parts, so a Replace/Skip/Cancel dialog can show the file
        # without parsing the sentence.
        assert body["volid"] == "local:iso/ubuntu.iso"
        assert body["filename"] == "ubuntu.iso"
        assert body["size_bytes"] == 4242
        assert "local:iso/ubuntu.iso" in body["detail"]
        # nothing spooled: the check runs before the body is read to disk
        uploads = app.state.settings.data_dir / "uploads"
        assert not list(uploads.glob("*.upload")) if uploads.exists() else True


def test_upload_onto_an_existing_name_proceeds_when_replace_is_chosen(
        tmp_path, csrf_header, bootstrap_admin):
    """A plain boolean, not a typed phrase. Typed confirmation is reserved for
    deletions, which cannot be undone; replacing a file the operator is already
    uploading does not warrant that weight."""
    app, c, hid = _api(tmp_path, fake=_fake_with_volume("local:iso/ubuntu.iso"))
    with c:
        bootstrap_admin(c)
        r = c.post(f"/api/v1/storage/{hid}/local/content",
                   files={"file": ("ubuntu.iso", b"x" * 16)},
                   data={"content": "iso", "node": "pve1", "overwrite": "true"},
                   headers=csrf_header(c))
        assert r.status_code == 202, r.text


def test_a_brand_new_upload_name_needs_no_confirmation(tmp_path, csrf_header,
                                                       bootstrap_admin):
    """No collision means nothing is destroyed, so it stays frictionless."""
    app, c, hid = _api(tmp_path, fake=_fake_with_volume("local:iso/something-else.iso"))
    with c:
        bootstrap_admin(c)
        r = c.post(f"/api/v1/storage/{hid}/local/content",
                   files={"file": ("ubuntu.iso", b"x" * 16)},
                   data={"content": "iso", "node": "pve1"},
                   headers=csrf_header(c))
        assert r.status_code == 202, r.text
