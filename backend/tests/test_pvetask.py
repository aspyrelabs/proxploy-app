"""Phase 6 Task 2: the shared UPID poll-and-drain loop, extracted out of
services/lifecycle.py so twelve new job handlers don't each re-derive it."""
import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient

from proxploy.jobs import HANDLERS, JobBackend
from proxploy.models import AuditEvent, Job, JobEvent, User
from proxploy.services.proxmox import ProxmoxClient
from proxploy.services.pvetask import await_task
from tests.fakes.pve import FakePVE, make_fake_factory
from tests.support import make_app, make_job_app


def _client(fake):
    return ProxmoxClient("https://10.0.0.7:8006", "proxploy@pve!task", "s3cret",
                         verify_tls=False, factory=make_fake_factory(fake))


def _run_probe(tmp_path, fake, *, body, kind="test.await"):
    """Register a throwaway handler that drives await_task, run it, return the
    settled Job row plus its ordered job_events messages."""
    async def go():
        app = make_job_app(tmp_path, fake=fake)
        backend = JobBackend(app)

        async def probe(ctx, params):
            client = _client(fake)
            upid = client.guest_action("lxc", "pve1", 150, "start")
            return await body(ctx, client, upid)

        HANDLERS[kind] = probe
        try:
            with app.state.sessionmaker() as db:
                job_id = backend.enqueue(db, kind=kind, params={}).id
            await backend.wait(job_id, timeout=15)
        finally:
            HANDLERS.pop(kind, None)
        with app.state.sessionmaker() as db:
            job = db.get(Job, job_id)
            events = [(e.message, e.stream) for e in db.query(JobEvent)
                      .filter_by(job_id=job_id).order_by(JobEvent.seq)]
            return SimpleNamespace(status=job.status, error=job.error,
                                   result=job.result, progress=job.progress_pct,
                                   events=events)

    return asyncio.run(go())


def test_await_task_logs_the_upid_drains_the_log_and_returns_the_status(tmp_path):
    fake = FakePVE(running_ticks=2)

    async def body(ctx, client, upid):
        status = await await_task(ctx, client, "pve1", upid, poll_s=0.01)
        assert status["exitstatus"] == "OK"
        return {"upid": upid}

    out = _run_probe(tmp_path, fake, body=body)
    assert out.status == "succeeded"
    [upid] = fake.task_lines.keys()
    messages = [m for m, _ in out.events]
    assert messages[0] == f"proxmox task {upid}"
    assert "start lxc 150" in messages  # the task log was drained into job_events
    assert messages.count("start lxc 150") == 1  # exactly once, cursor advanced
    assert out.progress == 100


def test_await_task_fails_closed_on_a_missing_exitstatus(tmp_path):
    """A stopped task with no exitstatus is an UNKNOWN outcome, not a success."""
    fake = FakePVE(task_exit=None)

    async def body(ctx, client, upid):
        return await await_task(ctx, client, "pve1", upid, poll_s=0.01)

    out = _run_probe(tmp_path, fake, body=body)
    assert out.status == "failed"
    assert "no exitstatus reported" in out.error


def test_await_task_fails_on_a_nonzero_exitstatus(tmp_path):
    fake = FakePVE(task_exit="CT 150 is locked (snapshot)")

    async def body(ctx, client, upid):
        return await await_task(ctx, client, "pve1", upid, poll_s=0.01)

    out = _run_probe(tmp_path, fake, body=body)
    assert out.status == "failed"
    assert "locked" in out.error


def test_await_task_times_out_and_says_the_node_task_is_untouched(tmp_path):
    fake = FakePVE(running_ticks=10_000)

    async def body(ctx, client, upid):
        return await await_task(ctx, client, "pve1", upid, timeout_s=0.0, poll_s=0.01)

    out = _run_probe(tmp_path, fake, body=body)
    assert out.status == "failed"
    assert "still running" in out.error and "untouched" in out.error


def test_cancel_mid_poll_leaves_the_still_running_breadcrumb(tmp_path):
    """Verbatim from run_lifecycle: a locally cancelled job must never imply
    the proxmox-side task was undone."""
    fake = FakePVE(running_ticks=10_000)

    async def go():
        app = make_job_app(tmp_path, fake=fake)
        backend = JobBackend(app)

        async def probe(ctx, params):
            client = _client(fake)
            upid = client.guest_action("lxc", "pve1", 150, "start")
            return await await_task(ctx, client, "pve1", upid, poll_s=0.02)

        HANDLERS["test.cancel"] = probe
        try:
            with app.state.sessionmaker() as db:
                job_id = backend.enqueue(db, kind="test.cancel", params={}).id
            await asyncio.sleep(0.05)
            assert backend.cancel(job_id)
            await backend.wait(job_id, timeout=15)
        finally:
            HANDLERS.pop("test.cancel", None)
        with app.state.sessionmaker() as db:
            job = db.get(Job, job_id)
            events = [(e.message, e.stream) for e in db.query(JobEvent)
                      .filter_by(job_id=job_id).order_by(JobEvent.seq)]
        assert job.status == "canceled"
        assert any("keeps running" in m and s == "stderr" for m, s in events)

    asyncio.run(go())


def test_lifecycle_uses_the_shared_helper_rather_than_its_own_copy():
    """Root-cause DRY proof: run_lifecycle must reference the one await_task,
    not a re-pasted loop."""
    import inspect

    from proxploy.services import lifecycle, pvetask

    assert lifecycle.await_task is pvetask.await_task
    src = inspect.getsource(lifecycle.run_lifecycle)
    assert "await_task(" in src
    assert "task_status" not in src  # the poll loop lives in pvetask only


def test_pve_task_timeout_is_configurable(tmp_path, monkeypatch):
    from proxploy.config import Settings

    assert Settings(data_dir=tmp_path).pve_task_timeout_s == 300.0
    monkeypatch.setenv("PROXPLOY_PVE_TASK_TIMEOUT_S", "45")
    assert Settings(data_dir=tmp_path).pve_task_timeout_s == 45.0


def test_enqueue_and_audit_writes_the_job_the_audit_row_and_the_202_body(tmp_path):
    from proxploy.api.jobs import enqueue_and_audit

    async def noop(ctx, params):
        return {}

    HANDLERS["test.enqueue"] = noop
    app = make_app(tmp_path, fake=FakePVE())
    try:
        with TestClient(app):
            with app.state.sessionmaker() as db:
                u = User(email="op@example.com", display_name="Op")
                db.add(u)
                db.commit()
                req = SimpleNamespace(app=app,
                                      client=SimpleNamespace(host="10.9.9.9"))
                out = enqueue_and_audit(req, db, SimpleNamespace(id=u.id),
                                        kind="test.enqueue", target_type="storage",
                                        target_id=7, params={"volid": "local:iso/x.iso"},
                                        action="storage.upload")
                job_id = out["job"]["id"]
                assert out["job"]["kind"] == "test.enqueue"
                assert db.get(Job, job_id).requested_by == u.id
                row = db.query(AuditEvent).filter_by(action="storage.upload").one()
                assert row.job_id == job_id
                assert row.target_type == "storage" and row.target_id == 7
                assert row.ip == "10.9.9.9" and row.actor_id == u.id
    finally:
        HANDLERS.pop("test.enqueue", None)
