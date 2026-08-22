"""Reboot / power off a Proxmox NODE (host actions menu), doc 02 SS9 / doc 08
SS1 and SS9 row 14.

New surface, no plan ever added it. Proxmox exposes one call for both,
POST /nodes/{node}/status?command=reboot|shutdown; Proxploy gates it far
harder than a guest lifecycle action because it can take the whole node
down, and possibly Proxploy's own recovery path with it.

Both actions run through the job engine now (same reasoning as every other
destructive PVE call: a job leaves a transcript in `job_events` and shows up
in the bell popover via GET /jobs, a synchronous 200 with a bare UPID does
not). The typed-confirmation gate and the self-guard warning still run
BEFORE anything is enqueued, at the API layer, and nothing about them
changed; only what happens after confirmation moved onto the job engine.
"""
import asyncio
import json

from proxploy.jobs import TERMINAL
from proxploy.models import Job
from proxploy.services.settings import set_setting


def _app(tmp_path, fail=False):
    from fastapi.testclient import TestClient
    from proxploy.models import HostCredential
    from tests.fakes.pve import FakePVE
    from tests.support import make_app, seed_host_row

    fake = FakePVE(fail=fail)
    app = make_app(tmp_path, fake=fake)
    c = TestClient(app)
    c.__enter__()
    with app.state.sessionmaker() as db:
        h = seed_host_row(db, node="pve1")
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!mon", "token_secret": "s"}).encode())
        db.add(HostCredential(host_id=h.id, kind="api_token:monitoring",
                              encrypted_blob=blob, key_version=ver,
                              public_meta="proxploy@pve!mon"))
        db.commit()
        return app, c, fake, h.id


def test_an_unknown_host_is_404(tmp_path, bootstrap_admin, csrf_header):
    app, c, fake, hid = _app(tmp_path)
    bootstrap_admin(c)
    r = c.post("/api/v1/hosts/9999/nodes/pve1/power",
               json={"command": "reboot", "confirm": "pve1"}, headers=csrf_header(c))
    assert r.status_code == 404


def test_reboot_requires_the_node_name_typed_back(tmp_path, bootstrap_admin, csrf_header):
    """No confirm at all: refused, and nothing was sent to Proxmox, and no job
    was even created."""
    app, c, fake, hid = _app(tmp_path)
    bootstrap_admin(c)
    r = c.post(f"/api/v1/hosts/{hid}/nodes/pve1/power",
               json={"command": "reboot"}, headers=csrf_header(c))
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["error"] == "confirm_required"
    assert body["confirm_phrase"] == "pve1"
    assert fake.node_power_calls == []
    with app.state.sessionmaker() as db:
        assert db.query(Job).count() == 0


def test_reboot_is_refused_on_a_near_miss_confirm(tmp_path, bootstrap_admin, csrf_header):
    """The gate is the whole safety mechanism: "close enough" must never pass
    it, and must never enqueue a job either."""
    app, c, fake, hid = _app(tmp_path)
    bootstrap_admin(c)
    r = c.post(f"/api/v1/hosts/{hid}/nodes/pve1/power",
               json={"command": "reboot", "confirm": "pve1 "}, headers=csrf_header(c))
    assert r.status_code == 409
    assert fake.node_power_calls == []
    with app.state.sessionmaker() as db:
        assert db.query(Job).count() == 0


def test_reboot_enqueues_a_job_rather_than_acting_synchronously(
        tmp_path, bootstrap_admin, csrf_header):
    """The whole point of this change: a 202 and a job row, not a synchronous
    200 with a bare UPID and no transcript."""
    app, c, fake, hid = _app(tmp_path)
    bootstrap_admin(c)
    r = c.post(f"/api/v1/hosts/{hid}/nodes/pve1/power",
               json={"command": "reboot", "confirm": "pve1"}, headers=csrf_header(c))
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["is_self"] is False
    job = body["job"]
    assert job["kind"] == "host.reboot"
    assert job["target_type"] == "host" and job["target_id"] == hid
    with app.state.sessionmaker() as db:
        assert db.query(Job).count() == 1


def test_power_off_enqueues_a_job_with_the_shutdown_command(
        tmp_path, bootstrap_admin, csrf_header):
    """Proxmox's own node-status verb for "power off" is `shutdown` (a clean
    ACPI power-down), never `stop`, which is a guest-only lifecycle verb."""
    app, c, fake, hid = _app(tmp_path)
    bootstrap_admin(c)
    r = c.post(f"/api/v1/hosts/{hid}/nodes/pve1/power",
               json={"command": "shutdown", "confirm": "pve1"}, headers=csrf_header(c))
    assert r.status_code == 202, r.text
    assert r.json()["job"]["kind"] == "host.shutdown"


def test_reboot_job_actually_reboots_the_node_and_reaches_a_terminal_status(tmp_path):
    """Handler-level: the job really calls Proxmox with the right command and
    the right node, drains the task log, and settles `succeeded`."""
    from proxploy.jobs import JobBackend
    from tests.support import make_job_app, seed_host_row

    async def run():
        from tests.fakes.pve import FakePVE

        fake = FakePVE()
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.guestjobs  # noqa: F401  (registers host.reboot)
        backend = JobBackend(app)
        with app.state.sessionmaker() as db:
            h = seed_host_row(db, node="pve1")
            from proxploy.models import HostCredential
            blob, ver = app.state.secretstore.encrypt(json.dumps(
                {"token_id": "proxploy@pve!mon", "token_secret": "s"}).encode())
            db.add(HostCredential(host_id=h.id, kind="api_token:monitoring",
                                  encrypted_blob=blob, key_version=ver))
            db.commit()
            job_id = backend.enqueue(
                db, kind="host.reboot", target_type="host", target_id=h.id,
                params={"host_id": h.id, "node": "pve1", "command": "reboot"}).id
        await backend.wait(job_id, timeout=10)
        with app.state.sessionmaker() as db:
            job = db.get(Job, job_id)
            assert job.status == "succeeded", job.error
            assert job.result["node"] == "pve1"
            # No UPID, and so no exitstatus: Proxmox forks no task for a node
            # reboot. See the null-UPID test below for why that is the point
            # rather than a gap.
            assert job.result["upid"] is None
            assert job.result["exitstatus"] is None
            from proxploy.models import JobEvent
            messages = [e.message for e in db.query(JobEvent)
                       .filter_by(job_id=job_id).order_by(JobEvent.seq)]
            assert any("rebooting node pve1" in m for m in messages)
        assert fake.node_power_calls == [("pve1", "reboot")]

    asyncio.run(run())


def test_power_off_job_calls_proxmox_with_shutdown_and_succeeds(tmp_path):
    from proxploy.jobs import JobBackend
    from tests.support import make_job_app, seed_host_row

    async def run():
        from tests.fakes.pve import FakePVE

        fake = FakePVE()
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.guestjobs  # noqa: F401  (registers host.shutdown)
        backend = JobBackend(app)
        with app.state.sessionmaker() as db:
            h = seed_host_row(db, node="pve1")
            from proxploy.models import HostCredential
            blob, ver = app.state.secretstore.encrypt(json.dumps(
                {"token_id": "proxploy@pve!mon", "token_secret": "s"}).encode())
            db.add(HostCredential(host_id=h.id, kind="api_token:monitoring",
                                  encrypted_blob=blob, key_version=ver))
            db.commit()
            job_id = backend.enqueue(
                db, kind="host.shutdown", target_type="host", target_id=h.id,
                params={"host_id": h.id, "node": "pve1", "command": "shutdown"}).id
        await backend.wait(job_id, timeout=10)
        with app.state.sessionmaker() as db:
            assert db.get(Job, job_id).status == "succeeded"
        assert fake.node_power_calls == [("pve1", "shutdown")]

    asyncio.run(run())


def test_a_power_off_never_asks_proxmox_for_the_log_of_a_task_it_did_not_start(
        tmp_path, monkeypatch):
    """The hardware bug: POST /nodes/{node}/status returns null, not a UPID,
    so run_host_power called GET /nodes/pve1/tasks/None/log on every power
    off. The node shut down exactly as asked and the job then died with "task
    log failed for None: 400 Bad Request: Parameter verification failed -
    limit/start not defined in schema", which reads as a shutdown that did not
    work.

    Watches the client rather than the result: a UPID reappearing in the
    result is caught by the test above, but a task read against a stale or
    invented UPID would not be, and that read is the thing that must not
    happen.
    """
    from proxploy.jobs import JobBackend
    from proxploy.services.proxmox import ProxmoxClient
    from tests.support import make_job_app, seed_host_row

    looked: list[tuple[str, object]] = []
    for name in ("task_log", "task_status"):
        orig = getattr(ProxmoxClient, name)

        def spy(self, node, upid, *a, _n=name, _o=orig, **kw):
            looked.append((_n, upid))
            return _o(self, node, upid, *a, **kw)

        monkeypatch.setattr(ProxmoxClient, name, spy)

    async def run():
        from tests.fakes.pve import FakePVE

        fake = FakePVE()
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.guestjobs  # noqa: F401
        backend = JobBackend(app)
        with app.state.sessionmaker() as db:
            h = seed_host_row(db, node="pve1")
            from proxploy.models import HostCredential
            blob, ver = app.state.secretstore.encrypt(json.dumps(
                {"token_id": "proxploy@pve!mon", "token_secret": "s"}).encode())
            db.add(HostCredential(host_id=h.id, kind="api_token:monitoring",
                                  encrypted_blob=blob, key_version=ver))
            db.commit()
            job_id = backend.enqueue(
                db, kind="host.shutdown", target_type="host", target_id=h.id,
                params={"host_id": h.id, "node": "pve1",
                        "command": "shutdown"}).id
        await backend.wait(job_id, timeout=10)

        with app.state.sessionmaker() as db:
            job = db.get(Job, job_id)
            assert job.status == "succeeded", job.error
            from proxploy.models import JobEvent
            messages = [e.message for e in db.query(JobEvent)
                        .filter_by(job_id=job_id).order_by(JobEvent.seq)]
            # The transcript says what happened rather than going quiet: an
            # operator reading this log should not be left wondering where the
            # usual "proxmox task UPID:..." line went.
            assert any("with no task to follow" in m for m in messages)
            assert not any("proxmox task" in m for m in messages)
        assert fake.node_power_calls == [("pve1", "shutdown")]
        assert looked == []

    asyncio.run(run())


def test_reboot_job_reports_no_fake_progress(tmp_path, monkeypatch):
    """Do not fake it: a reboot has no honest percentage, so the real handler
    must never call ctx.progress while it runs (services/guestjobs.py::
    run_host_power passes report_progress=False through to pvetask.await_task).
    """
    from proxploy.jobs import JobBackend
    from proxploy.jobs import backend as jobs_backend
    from tests.support import make_job_app, seed_host_row

    async def run():
        from tests.fakes.pve import FakePVE

        calls = []
        orig = jobs_backend.JobContext.progress

        def spy(self, pct):
            calls.append(pct)
            return orig(self, pct)

        monkeypatch.setattr(jobs_backend.JobContext, "progress", spy)

        fake = FakePVE()
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.guestjobs  # noqa: F401
        backend = JobBackend(app)
        with app.state.sessionmaker() as db:
            h = seed_host_row(db, node="pve1")
            from proxploy.models import HostCredential
            blob, ver = app.state.secretstore.encrypt(json.dumps(
                {"token_id": "proxploy@pve!mon", "token_secret": "s"}).encode())
            db.add(HostCredential(host_id=h.id, kind="api_token:monitoring",
                                  encrypted_blob=blob, key_version=ver))
            db.commit()
            job_id = backend.enqueue(
                db, kind="host.reboot", target_type="host", target_id=h.id,
                params={"host_id": h.id, "node": "pve1", "command": "reboot"}).id
        await backend.wait(job_id, timeout=10)
        with app.state.sessionmaker() as db:
            assert db.get(Job, job_id).status == "succeeded"
        assert calls == []

    asyncio.run(run())


def test_a_proxmox_error_fails_the_job_rather_than_ending_the_request(tmp_path):
    """The route now enqueues before Proxmox is ever called; an unreachable
    node surfaces as a failed job, not an immediate 502 (same shape as
    services/guestjobs.py::run_network_apply, api/network.py::apply_network)."""
    from proxploy.jobs import JobBackend
    from tests.support import make_job_app, seed_host_row

    async def run():
        from tests.fakes.pve import FakePVE

        fake = FakePVE(fail=True)
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.guestjobs  # noqa: F401
        backend = JobBackend(app)
        with app.state.sessionmaker() as db:
            h = seed_host_row(db, node="pve1")
            from proxploy.models import HostCredential
            blob, ver = app.state.secretstore.encrypt(json.dumps(
                {"token_id": "proxploy@pve!mon", "token_secret": "s"}).encode())
            db.add(HostCredential(host_id=h.id, kind="api_token:monitoring",
                                  encrypted_blob=blob, key_version=ver))
            db.commit()
            job_id = backend.enqueue(
                db, kind="host.reboot", target_type="host", target_id=h.id,
                params={"host_id": h.id, "node": "pve1", "command": "reboot"}).id
        await backend.wait(job_id, timeout=10)
        with app.state.sessionmaker() as db:
            job = db.get(Job, job_id)
            assert job.status == "failed"

    asyncio.run(run())


def test_a_host_power_job_stuck_running_is_marked_interrupted_on_restart(tmp_path):
    """The case this design has to answer: if the job runs on the node it is
    powering off, the job engine dies with it mid-poll, no in-process code
    ever runs to write a terminal row. This is not special-cased in the
    handler; it relies on the SAME orphan sweep every job kind already gets
    at boot (jobs/backend.py::sweep_orphans), which marks any row still
    `queued`/`running` `interrupted` and never resumes it. Proven directly
    here: a `host.shutdown` row left `running` (simulating the process having
    died mid-job) is swept to a real terminal status on the next start."""
    from proxploy.jobs import JobBackend
    from tests.support import make_job_app, seed_host_row

    async def run():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            h = seed_host_row(db, node="pve1")
            job = Job(kind="host.shutdown", status="running", target_type="host",
                      target_id=h.id,
                      params={"host_id": h.id, "node": "pve1", "command": "shutdown"})
            db.add(job)
            db.commit()
            job_id = job.id
        backend = JobBackend(app)
        n = backend.sweep_orphans()
        assert n == 1
        # Drain the fire-and-forget notify task before the loop closes, same
        # hermetic-teardown reasoning as test_job_backend.py's own sweep test.
        for _ in range(50):
            if not backend._side:
                break
            await asyncio.sleep(0.05)
        with app.state.sessionmaker() as db:
            row = db.get(Job, job_id)
            assert row.status == "interrupted"
            assert row.status in TERMINAL
            assert row.finished_at is not None

    asyncio.run(run())


def test_an_unknown_command_is_a_422(tmp_path, bootstrap_admin, csrf_header):
    app, c, fake, hid = _app(tmp_path)
    bootstrap_admin(c)
    r = c.post(f"/api/v1/hosts/{hid}/nodes/pve1/power",
               json={"command": "stop", "confirm": "pve1"}, headers=csrf_header(c))
    assert r.status_code == 422


def test_power_is_owner_gated(tmp_path, bootstrap_admin, csrf_header):
    """Same severity class as host.remove/host.credentials: it can take the
    whole node, and every guest on it, down."""
    app, c, fake, hid = _app(tmp_path)
    bootstrap_admin(c)
    c.post("/api/v1/users", json={"email": "admin2@example.com",
                                  "password": "correct-horse-battery",
                                  "display_name": "A2", "role": "admin"},
           headers=csrf_header(c))
    c.post("/api/v1/auth/login", json={"email": "admin2@example.com",
                                       "password": "correct-horse-battery"},
           headers=csrf_header(c))
    r = c.post(f"/api/v1/hosts/{hid}/nodes/pve1/power",
               json={"command": "reboot", "confirm": "pve1"}, headers=csrf_header(c))
    assert r.status_code == 403


def test_reboot_writes_an_audit_event(tmp_path, bootstrap_admin, csrf_header):
    from proxploy.models import AuditEvent

    app, c, fake, hid = _app(tmp_path)
    bootstrap_admin(c)
    r = c.post(f"/api/v1/hosts/{hid}/nodes/pve1/power",
              json={"command": "reboot", "confirm": "pve1"}, headers=csrf_header(c))
    job_id = r.json()["job"]["id"]
    with app.state.sessionmaker() as db:
        row = db.query(AuditEvent).filter_by(action="host.reboot").one()
        assert row.target_type == "host" and row.target_id == hid
        assert row.result == "ok"
        assert row.params["node"] == "pve1"
        assert row.job_id == job_id


def test_a_denied_confirm_is_still_audited(tmp_path, bootstrap_admin, csrf_header):
    from proxploy.models import AuditEvent

    app, c, fake, hid = _app(tmp_path)
    bootstrap_admin(c)
    c.post(f"/api/v1/hosts/{hid}/nodes/pve1/power",
          json={"command": "reboot"}, headers=csrf_header(c))
    with app.state.sessionmaker() as db:
        row = db.query(AuditEvent).filter_by(action="host.reboot").one()
        assert row.result == "denied"


# --- self-guard: the node Proxploy itself runs on --------------------------

def test_the_confirm_gate_names_the_self_warning_before_the_action_runs(
        tmp_path, bootstrap_admin, csrf_header):
    """The whole point: an operator must never be surprised by this. The 409
    the typed gate returns (client shows this BEFORE the operator can type
    anything) already carries the self warning, not just the eventual 200."""
    app, c, fake, hid = _app(tmp_path)
    with app.state.sessionmaker() as db:
        set_setting(db, "self.host_id", hid)
    bootstrap_admin(c)
    r = c.post(f"/api/v1/hosts/{hid}/nodes/pve1/power",
               json={"command": "shutdown"}, headers=csrf_header(c))
    assert r.status_code == 409
    body = r.json()
    assert body["is_self"] is True
    assert "no in-band way back" in body["detail"] or "physical" in body["detail"]


def test_confirmed_self_power_off_still_goes_through(tmp_path, bootstrap_admin, csrf_header):
    """Doc 08 SS9 row 14: self-management is a typed-confirmation backstop,
    not a hard refusal -- an operator who really means it can still do it.
    The gate still runs before anything is enqueued; only what happens after
    confirmation (a synchronous PVE call) moved onto the job engine."""
    app, c, fake, hid = _app(tmp_path)
    with app.state.sessionmaker() as db:
        set_setting(db, "self.host_id", hid)
    bootstrap_admin(c)
    r = c.post(f"/api/v1/hosts/{hid}/nodes/pve1/power",
               json={"command": "shutdown", "confirm": "pve1"}, headers=csrf_header(c))
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["is_self"] is True
    assert body["job"]["kind"] == "host.shutdown"


# --- Sys.PowerMgmt missing: a real 403, but a message worth reading --------

def test_a_missing_node_power_privilege_names_it_and_how_to_grant_it(tmp_path):
    """The bug this whole feature closes: a token that cannot power the node
    used to fail with a bare Proxmox 403 in job.error. It should now name
    Sys.PowerMgmt and where to grant it, without losing the original Proxmox
    text (still useful evidence)."""
    from proxploy.jobs import JobBackend
    from tests.support import make_job_app, seed_host_row

    async def run():
        from tests.fakes.pve import FakePVE

        fake = FakePVE()
        fake.power_forbidden_nodes = {"pve1"}
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.guestjobs  # noqa: F401
        backend = JobBackend(app)
        with app.state.sessionmaker() as db:
            h = seed_host_row(db, node="pve1")
            from proxploy.models import HostCredential
            # NOT the single-char "s" other tests in this file use: _wrap's
            # secret-scrubbing replaces every occurrence of the literal
            # secret, and "s" appears inside "Sys.PowerMgmt" and
            # "docs.proxploy.com" themselves, which this test asserts on.
            blob, ver = app.state.secretstore.encrypt(json.dumps(
                {"token_id": "proxploy@pve!mon", "token_secret": "t0k3n-99xz"}).encode())
            db.add(HostCredential(host_id=h.id, kind="api_token:monitoring",
                                  encrypted_blob=blob, key_version=ver))
            db.commit()
            job_id = backend.enqueue(
                db, kind="host.shutdown", target_type="host", target_id=h.id,
                params={"host_id": h.id, "node": "pve1", "command": "shutdown"}).id
        await backend.wait(job_id, timeout=10)
        with app.state.sessionmaker() as db:
            job = db.get(Job, job_id)
            assert job.status == "failed"
            assert "Sys.PowerMgmt" in job.error
            assert "docs.proxploy.com" in job.error

    asyncio.run(run())


def test_reboot_is_not_blocked_by_a_stale_node_power_missing_flag(
        tmp_path, bootstrap_admin, csrf_header):
    """node_power_missing (computed at enrolment/test time) is informational,
    never a pre-emptive gate: it can go stale the moment an operator grants
    the privilege without re-testing, and refusing on a maybe-stale cache
    would be a worse failure than the real 403 this whole feature exists to
    explain."""
    app, c, fake, hid = _app(tmp_path)
    with app.state.sessionmaker() as db:
        from proxploy.models import Host
        db.get(Host, hid).node_power_missing = True
        db.commit()
    bootstrap_admin(c)
    r = c.post(f"/api/v1/hosts/{hid}/nodes/pve1/power",
               json={"command": "reboot", "confirm": "pve1"}, headers=csrf_header(c))
    assert r.status_code == 202, r.text


def test_a_sibling_node_of_the_same_cluster_host_is_not_flagged_self(
        tmp_path, bootstrap_admin, csrf_header):
    app, c, fake, hid = _app(tmp_path)
    with app.state.sessionmaker() as db:
        set_setting(db, "self.host_id", hid)  # entry node is pve1, not pve2
    bootstrap_admin(c)
    r = c.post(f"/api/v1/hosts/{hid}/nodes/pve2/power",
               json={"command": "reboot"}, headers=csrf_header(c))
    assert r.status_code == 409
    assert r.json()["is_self"] is False
