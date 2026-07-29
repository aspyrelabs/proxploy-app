"""Lifecycle job handlers over the ProxmoxClient (doc 10 Phase 3)."""
import asyncio
import json

from proxploy.models import App, Host, HostCredential, Job, JobEvent, Vm


def _seed_host(app, fake_token="s3cret"):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://pve1:8006", node_name="pve1",
                    status="connected", pve_version="8.4.1")
        db.add(host)
        db.commit()
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!life", "token_secret": fake_token}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token",
                              encrypted_blob=blob, key_version=ver,
                              public_meta="proxploy@pve!life"))
        db.commit()
        return host.id


def _seed_app(app, host_id, ctid=150):
    with app.state.sessionmaker() as db:
        row = App(host_id=host_id, ctid=ctid, name="Immich", slug="immich")
        db.add(row)
        db.commit()
        return row.id


def _seed_vm(app, host_id, vmid=201):
    with app.state.sessionmaker() as db:
        row = Vm(host_id=host_id, vmid=vmid, name="win11", status="running")
        db.add(row)
        db.commit()
        return row.id


def test_kinds_cover_every_documented_verb():
    from proxploy.jobs import HANDLERS
    from proxploy.services.lifecycle import APP_ACTIONS, VM_ACTIONS, job_kind

    assert APP_ACTIONS == ("start", "stop", "restart", "shutdown")
    assert VM_ACTIONS == ("start", "stop", "restart", "shutdown", "pause", "resume")
    assert job_kind("app", "start") == "app.start"
    for verb in APP_ACTIONS:
        assert f"app.{verb}" in HANDLERS
    for verb in VM_ACTIONS:
        assert f"vm.{verb}" in HANDLERS


def test_restart_maps_to_proxmox_reboot_and_pause_to_suspend():
    from proxploy.services.lifecycle import PVE_VERB

    assert PVE_VERB["restart"] == "reboot"
    assert PVE_VERB["pause"] == "suspend"
    assert PVE_VERB["resume"] == "resume"
    assert PVE_VERB["stop"] == "stop" and PVE_VERB["shutdown"] == "shutdown"


def test_app_start_calls_proxmox_and_archives_the_task_log(tmp_path):
    from proxploy.jobs import JobBackend
    from tests.fakes.pve import FakePVE
    from tests.support import make_job_app

    async def run():
        fake = FakePVE()
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.lifecycle  # noqa: F401 — registers handlers
        backend = JobBackend(app)
        host_id = _seed_host(app)
        app_id = _seed_app(app, host_id)
        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(db, kind="app.start", target_type="app",
                                     target_id=app_id,
                                     params={"target_id": app_id}).id
        await backend.wait(job_id, timeout=10)
        assert fake.actions == [("lxc", 150, "start")]
        with app.state.sessionmaker() as db:
            job = db.get(Job, job_id)
            assert job.status == "succeeded"
            assert job.result["exitstatus"] == "OK"
            assert job.result["vmid"] == 150 and job.result["node"] == "pve1"
            messages = [e.message for e in db.query(JobEvent)
                        .filter_by(job_id=job_id).order_by(JobEvent.seq)]
            assert any("start lxc 150" in m for m in messages)

    asyncio.run(run())


def test_vm_pause_uses_qemu_and_the_suspend_verb(tmp_path):
    from proxploy.jobs import JobBackend
    from tests.fakes.pve import FakePVE
    from tests.support import make_job_app

    async def run():
        fake = FakePVE()
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.lifecycle  # noqa: F401
        backend = JobBackend(app)
        host_id = _seed_host(app)
        vm_id = _seed_vm(app, host_id)
        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(db, kind="vm.pause", target_type="vm",
                                     target_id=vm_id, params={"target_id": vm_id}).id
        await backend.wait(job_id, timeout=10)
        assert fake.actions == [("qemu", 201, "suspend")]

    asyncio.run(run())


def test_nonzero_exitstatus_fails_the_job(tmp_path):
    from proxploy.jobs import JobBackend
    from tests.fakes.pve import FakePVE
    from tests.support import make_job_app

    async def run():
        fake = FakePVE(task_exit="CT 150 is locked (snapshot)")
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.lifecycle  # noqa: F401
        backend = JobBackend(app)
        host_id = _seed_host(app)
        app_id = _seed_app(app, host_id)
        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(db, kind="app.stop", target_type="app",
                                     target_id=app_id, params={"target_id": app_id}).id
        await backend.wait(job_id, timeout=10)
        with app.state.sessionmaker() as db:
            job = db.get(Job, job_id)
            assert job.status == "failed"
            assert "locked" in job.error

    asyncio.run(run())


def test_a_running_task_is_polled_until_it_stops(tmp_path):
    from proxploy.jobs import JobBackend
    from tests.fakes.pve import FakePVE
    from tests.support import make_job_app

    async def run():
        fake = FakePVE(running_ticks=2)
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.lifecycle as lc
        backend = JobBackend(app)
        host_id = _seed_host(app)
        app_id = _seed_app(app, host_id)
        original = lc.TASK_POLL_S
        lc.TASK_POLL_S = 0.01
        try:
            with app.state.sessionmaker() as db:
                job_id = backend.enqueue(db, kind="app.restart", target_type="app",
                                         target_id=app_id,
                                         params={"target_id": app_id}).id
            await backend.wait(job_id, timeout=10)
        finally:
            lc.TASK_POLL_S = original
        with app.state.sessionmaker() as db:
            assert db.get(Job, job_id).status == "succeeded"

    asyncio.run(run())


def test_terminal_success_publishes_a_resource_delta(tmp_path):
    from proxploy.jobs import JobBackend
    from tests.fakes.pve import FakePVE
    from tests.support import make_job_app

    async def run():
        fake = FakePVE()
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.lifecycle  # noqa: F401
        backend = JobBackend(app)
        q = app.state.bus.subscribe()
        host_id = _seed_host(app)
        app_id = _seed_app(app, host_id)
        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(db, kind="app.start", target_type="app",
                                     target_id=app_id, params={"target_id": app_id}).id
        await backend.wait(job_id, timeout=10)
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        resource = [d for name, d in events if name == "resource"]
        assert {"type": "app", "id": app_id, "change": "lifecycle"} in resource

    asyncio.run(run())


def test_a_missing_target_fails_the_job_instead_of_crashing_the_runner(tmp_path):
    from proxploy.jobs import JobBackend
    from tests.fakes.pve import FakePVE
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path, fake=FakePVE())
        import proxploy.services.lifecycle  # noqa: F401
        backend = JobBackend(app)
        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(db, kind="app.start", target_type="app",
                                     target_id=999, params={"target_id": 999}).id
        await backend.wait(job_id, timeout=10)
        with app.state.sessionmaker() as db:
            job = db.get(Job, job_id)
            assert job.status == "failed" and "not found" in job.error

    asyncio.run(run())


def test_app_lifespan_registers_lifecycle_handlers(tmp_path):
    """Step 8 correction: main.py's lifespan must import proxploy.services.lifecycle
    so the module-level handler registration actually runs for the real app.

    Runs in a fresh subprocess rather than this test process: by the time this
    file's own tests run, something has already imported
    proxploy.services.lifecycle (module-level registration is a one-time,
    process-wide side effect, HANDLERS is never cleared) so an in-process
    check would pass even if main.py's import were deleted again. Only a
    clean interpreter that reaches HANDLERS solely through create_app()'s
    lifespan actually proves the wiring.
    """
    import subprocess
    import sys
    from pathlib import Path

    script = f"""
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from proxploy.config import Settings
from proxploy.jobs import HANDLERS
from proxploy.main import create_app

assert "app.start" not in HANDLERS, "handlers already registered before create_app ran"

with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    s = Settings(db_url=f"sqlite:///{{d}}/t.db", data_dir=d, master_key_file=d / "master.key")
    with TestClient(create_app(s)):
        assert "app.start" in HANDLERS
        assert "vm.pause" in HANDLERS
print("OK")
"""
    backend_dir = Path(__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, "-c", script], capture_output=True,
                       text=True, cwd=backend_dir)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK" in r.stdout
