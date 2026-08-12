"""Lifecycle job handlers over the ProxmoxClient (doc 10 Phase 3)."""
import asyncio
import json

from proxploy.models import App, Host, HostCredential, Job, JobEvent, Vm


def _seed_host(app, fake_token="s3cret"):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.7:8006", node_name="pve1",
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
        import proxploy.services.lifecycle  # noqa: F401  (registers handlers)
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


def test_app_start_still_reports_the_10_to_100_bracket_unchanged(tmp_path):
    """run_lifecycle is a single-await_task caller that never opted into a
    band (no start_pct/end_pct passed): migrate.py's multi-phase fix must not
    change what a single-task job like this reports. Locks in pvetask.py's
    default bracket (10 then 100) as the behaviour every un-opted-in caller
    keeps."""
    from proxploy.jobs import JobBackend
    from tests.fakes.pve import FakePVE
    from tests.support import make_job_app

    async def run():
        fake = FakePVE()
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.lifecycle  # noqa: F401  (registers handlers)
        backend = JobBackend(app)
        host_id = _seed_host(app)
        app_id = _seed_app(app, host_id)
        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(db, kind="app.start", target_type="app",
                                     target_id=app_id,
                                     params={"target_id": app_id}).id
        q = backend.subscribe(job_id)
        await backend.wait(job_id, timeout=10)
        progress_pcts = []
        while not q.empty():
            frame = q.get_nowait()
            if frame["event"] == "progress":
                progress_pcts.append(frame["data"]["pct"])
        assert progress_pcts == [10, 100]

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


def test_job_bus_events_carry_target_type(tmp_path):
    """doc 05 §Streaming 4: the `job` SSE delta must carry target_type so a
    tab that didn't initiate the job (another tab, another user, the Phase 7
    scheduler) can still invalidate the right resource cache on completion."""
    from proxploy.jobs import JobBackend
    from tests.fakes.pve import FakePVE
    from tests.support import make_job_app

    async def run():
        fake = FakePVE()
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.lifecycle  # noqa: F401
        backend = JobBackend(app)
        host_id = _seed_host(app)
        app_id = _seed_app(app, host_id)
        q = app.state.bus.subscribe()
        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(db, kind="app.start", target_type="app",
                                     target_id=app_id, params={"target_id": app_id}).id
        await backend.wait(job_id, timeout=10)
        # Every status-bearing `job` delta (queued/running/succeeded) is
        # published from _spawn/_run/_finish and must carry target_type; the
        # bare progress_pct ticks from JobContext.progress() are a separate,
        # smaller delta and don't need it (applyJob only reads target_type
        # off a terminal delta).
        status_events = []
        while not q.empty():
            name, data = q.get_nowait()
            if name == "job" and "status" in data:
                status_events.append(data)
        assert status_events, "expected at least one status-bearing job bus event"
        assert all(d.get("target_type") == "app" for d in status_events)
        assert any(d.get("status") == "succeeded" for d in status_events)

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


# --- Fix round 1 (code review) -------------------------------------------


def test_task_log_lines_are_not_dropped_or_duplicated_across_polls(tmp_path):
    """A broken `seen` cursor would either re-send every line each poll
    (duplicates) or skip newly appended lines (drops). Assert the exact
    ordered job_events messages for a task log that grows across polls."""
    from proxploy.jobs import JobBackend
    from tests.fakes.pve import FakePVE
    from tests.support import make_job_app

    class GrowingLogPVE(FakePVE):
        """Appends one new task-log line per status poll (up to running_ticks),
        instead of a single static line, proves the cursor advances rather
        than reprocessing lines it already emitted."""

        def _task_status(self, upid):
            n = self._polls.get(upid, 0)
            if n < self.running_ticks:
                self.task_lines[upid].append(f"progress {n}")
            return super()._task_status(upid)

    async def run():
        fake = GrowingLogPVE(running_ticks=3)
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.lifecycle as lc
        backend = JobBackend(app)
        host_id = _seed_host(app)
        app_id = _seed_app(app, host_id)
        original = lc.TASK_POLL_S
        lc.TASK_POLL_S = 0.01
        try:
            with app.state.sessionmaker() as db:
                job_id = backend.enqueue(db, kind="app.start", target_type="app",
                                         target_id=app_id,
                                         params={"target_id": app_id}).id
            await backend.wait(job_id, timeout=10)
        finally:
            lc.TASK_POLL_S = original

        [upid] = fake.task_lines.keys()
        with app.state.sessionmaker() as db:
            job = db.get(Job, job_id)
            assert job.status == "succeeded"
            messages = [e.message for e in db.query(JobEvent)
                        .filter_by(job_id=job_id).order_by(JobEvent.seq)]
        assert messages[:2] == [
            "start Immich (lxc 150) on node pve1",
            f"proxmox task {upid}",
        ]
        # every task-log line the fake ever produced, in order, exactly once
        expected = fake.task_lines[upid]
        assert messages[2:2 + len(expected)] == expected

    asyncio.run(run())


def test_cancel_mid_poll_reports_the_proxmox_task_is_still_running(tmp_path):
    """A cancelled job must never claim the infra mutation was undone, the
    stop/start/etc POST already reached proxmox and keeps running there
    regardless of what happens to the local asyncio task."""
    from proxploy.jobs import JobBackend
    from tests.fakes.pve import FakePVE
    from tests.support import make_job_app

    async def run():
        fake = FakePVE(running_ticks=10_000)  # never finishes within the test
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.lifecycle as lc
        backend = JobBackend(app)
        host_id = _seed_host(app)
        app_id = _seed_app(app, host_id)
        original = lc.TASK_POLL_S
        lc.TASK_POLL_S = 0.02
        try:
            with app.state.sessionmaker() as db:
                job_id = backend.enqueue(db, kind="app.stop", target_type="app",
                                         target_id=app_id,
                                         params={"target_id": app_id}).id
            await asyncio.sleep(0.05)  # let it issue the action and start polling
            assert backend.cancel(job_id)
            await backend.wait(job_id, timeout=10)
        finally:
            lc.TASK_POLL_S = original

        assert fake.actions == [("lxc", 150, "stop")]  # the POST really fired
        with app.state.sessionmaker() as db:
            job = db.get(Job, job_id)
            assert job.status == "canceled"
            messages = [(e.message, e.stream) for e in db.query(JobEvent)
                        .filter_by(job_id=job_id).order_by(JobEvent.seq)]
        assert any("keeps running" in m and stream == "stderr"
                   for m, stream in messages)

    asyncio.run(run())


def test_task_timeout_fails_the_job(tmp_path):
    """TASK_TIMEOUT_S branch: a task that never stops must fail the job
    rather than poll forever, and must say the node-side task is untouched."""
    from proxploy.jobs import JobBackend
    from tests.fakes.pve import FakePVE
    from tests.support import make_job_app

    async def run():
        fake = FakePVE(running_ticks=10_000)
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.lifecycle as lc
        backend = JobBackend(app)
        host_id = _seed_host(app)
        app_id = _seed_app(app, host_id)
        orig_poll, orig_timeout = lc.TASK_POLL_S, lc.TASK_TIMEOUT_S
        lc.TASK_POLL_S, lc.TASK_TIMEOUT_S = 0.01, 0.0
        try:
            with app.state.sessionmaker() as db:
                job_id = backend.enqueue(db, kind="app.stop", target_type="app",
                                         target_id=app_id,
                                         params={"target_id": app_id}).id
            await backend.wait(job_id, timeout=10)
        finally:
            lc.TASK_POLL_S, lc.TASK_TIMEOUT_S = orig_poll, orig_timeout

        with app.state.sessionmaker() as db:
            job = db.get(Job, job_id)
            assert job.status == "failed"
            assert "still running" in job.error

    asyncio.run(run())


def test_missing_credential_fails_the_job(tmp_path):
    """_resolve's "no API token credential" branch: a host with no
    HostCredential row must fail the job cleanly instead of KeyError-ing on
    a missing token."""
    from proxploy.jobs import JobBackend
    from tests.fakes.pve import FakePVE
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path, fake=FakePVE())
        import proxploy.services.lifecycle  # noqa: F401
        backend = JobBackend(app)
        with app.state.sessionmaker() as db:
            host = Host(name="host-01", address="https://10.0.0.7:8006", node_name="pve1",
                       status="connected", pve_version="8.4.1")
            db.add(host)
            db.commit()
            host_id = host.id
        app_id = _seed_app(app, host_id)
        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(db, kind="app.start", target_type="app",
                                     target_id=app_id,
                                     params={"target_id": app_id}).id
        await backend.wait(job_id, timeout=10)
        with app.state.sessionmaker() as db:
            job = db.get(Job, job_id)
            assert job.status == "failed"
            assert "no API token credential" in job.error

    asyncio.run(run())


def _run_stop(tmp_path, action_error):
    from proxploy.jobs import JobBackend
    from tests.fakes.pve import FakePVE
    from tests.support import make_job_app

    async def run():
        fake = FakePVE()
        fake.action_error = action_error
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.lifecycle  # noqa: F401
        backend = JobBackend(app)
        host_id = _seed_host(app)
        app_id = _seed_app(app, host_id)
        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(db, kind="app.stop", target_type="app",
                                     target_id=app_id,
                                     params={"target_id": app_id}).id
        await backend.wait(job_id, timeout=10)
        with app.state.sessionmaker() as db:
            job = db.get(Job, job_id)
            msgs = [e.message for e in db.query(JobEvent)
                    .filter_by(job_id=job_id).order_by(JobEvent.seq)]
            return job.status, job.error, job.result, msgs

    return asyncio.run(run())


def test_stopping_an_already_stopped_guest_is_a_no_op_not_a_failure(tmp_path):
    """PVE answers `stop` on a stopped guest with a 500 "CT 150 not running",
    which surfaced as a red failed job for a no-op (PVE 9.2.6, 2026-08-10).
    Stop is idempotent: asking for stopped and getting stopped is success,
    whoever did the stopping. run_app_uninstall already tolerated this case."""
    status, error, result, msgs = _run_stop(tmp_path, "CT 150 not running")
    assert status == "succeeded", error
    assert result["noop"] == "already stopped"
    assert result["upid"] is None
    assert any("already stopped" in m for m in msgs)


def test_a_stop_that_fails_for_any_other_reason_still_fails(tmp_path):
    """The idempotency above must not swallow a real error."""
    status, error, _result, _msgs = _run_stop(tmp_path, "CT 150 is locked (backup)")
    assert status == "failed"
    assert "locked" in error
