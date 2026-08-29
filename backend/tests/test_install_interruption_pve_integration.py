"""Interrupting a real install, on real hardware.

The whole failure class lives in the gap between what the node did and what
Proxploy recorded, so fakes cannot prove it closed. tests/fakes/ssh.py never
runs build.func, never creates a container, and cannot be interrupted halfway
through doing so. These two kill a real connection to a real node partway
through a real community script and then ask the node what happened.

Both stay inside the declared scratch CTID range and destroy what they create.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from tests import livepve
from tests.livepve import live_only

pytestmark = pytest.mark.pve_integration

SLUG = os.environ.get("PROXPLOY_TEST_PVE_APP_SLUG", "adguard")
APPEAR_BUDGET_S = 420.0


def _storage_overrides() -> dict:
    out = {}
    if os.environ.get("PROXPLOY_TEST_PVE_STORAGE_ROOTFS"):
        out["container_storage"] = os.environ["PROXPLOY_TEST_PVE_STORAGE_ROOTFS"]
    if os.environ.get("PROXPLOY_TEST_PVE_STORAGE_TEMPLATE"):
        out["template_storage"] = os.environ["PROXPLOY_TEST_PVE_STORAGE_TEMPLATE"]
    return out


def _ingest(app):
    from proxploy.services.catalog import ensure_classified, run_discovery

    with app.state.sessionmaker() as db:
        try:
            run_discovery(db)
        except Exception as e:
            pytest.skip(f"catalog discovery failed (no GitHub access?): {e}")
        entry = ensure_classified(db, SLUG)
        if entry is None or not entry.installable:
            pytest.skip(f"{SLUG} is not installable here")


def _seed_job(app, kind="app.install"):
    from proxploy.models import Job

    with app.state.sessionmaker() as db:
        job = Job(kind=kind, status="running")
        db.add(job)
        db.commit()
        return job.id


async def _kill_ssh_once_the_container_exists(app, host_id, ctid, conns, done):
    """Abort the live SSH connection the moment the node really has the CT.

    This is the whole point of running on hardware: the script has genuinely
    changed the node by the time the connection dies, so `failed` would be a
    false statement about a real container rather than a hypothetical one.
    """
    deadline = asyncio.get_running_loop().time() + APPEAR_BUDGET_S
    while asyncio.get_running_loop().time() < deadline and not done.is_set():
        try:
            ids = await asyncio.to_thread(livepve.lxc_ids, app, host_id)
        except Exception:
            ids = set()
        if ctid in ids and conns:
            conns[-1].abort()
            return True
        await asyncio.sleep(2.0)
    return False


def _capture_connections(app, conns):
    real = app.state.ssh_connect_factory

    async def factory(host, private_key_pem, **kw):
        conn = await real(host, private_key_pem, **kw)
        conns.append(conn)
        return conn

    app.state.ssh_connect_factory = factory


async def _cleanup(app, host_id, ctid) -> None:
    """Destroy the scratch container, unlocking it first.

    A container whose creation was aborted keeps PVE's `create` lock, and
    `pct destroy` refuses while it is held, so best-effort cleanup silently
    leaves it behind and the next run fails on "already in use". Interrupting
    a create is the entire point of this suite, so its cleanup has to handle
    the state it deliberately produces.
    """
    livepve.assert_scratch(ctid)
    await livepve.ssh_run(
        f"pct unlock {ctid} 2>/dev/null || true; "
        f"pct stop {ctid} 2>/dev/null || true; "
        f"pct destroy {ctid} --purge 2>/dev/null || true")


@live_only
def test_ssh_dies_mid_install_and_the_node_is_asked_what_happened(tmp_path):
    """TEST 1. Kill SSH after the script has built the container but before
    Proxploy records anything, then reconnect and reconcile.

    What this pins, in the order it matters:
      the run ends `unknown`, not `failed` and not `succeeded`;
      the checkpoint names how far it got, so an operator is not guessing;
      a second install is REFUSED while it is unresolved, which is the one
        that turns one partial root install into two containers;
      reconciliation reads the node rather than inferring from exit status.
    """
    from proxploy.jobs import JobBackend, JobContext, JobUnknown
    from proxploy.models import App, Job
    from proxploy.services.appstore import run_install, run_install_reconcile

    app, host_id = livepve.live_app(tmp_path)
    ctid = livepve.assert_scratch(livepve.scratch_range()[0])
    _ingest(app)

    async def go():
        before = livepve.lxc_ids(app, host_id)
        assert ctid not in before, f"scratch id {ctid} is already in use"

        conns: list = []
        _capture_connections(app, conns)
        done = asyncio.Event()
        killer = asyncio.create_task(
            _kill_ssh_once_the_container_exists(app, host_id, ctid, conns, done))

        job_id = _seed_job(app)
        backend = JobBackend(app)
        try:
            with pytest.raises(JobUnknown) as caught:
                await run_install(
                    JobContext(backend, job_id=job_id),
                    {"catalog_slug": SLUG, "host_id": host_id, "ctid": ctid,
                     "name": f"int-{SLUG}", "overrides": _storage_overrides()})
            done.set()
            killed = await killer
            assert killed, ("the container never appeared, so the connection was "
                            "never killed mid-install and this test proved nothing")
            assert "does not know" in str(caught.value)

            # The container is REAL. Read over SSH, not through the API the
            # installer just used, so this is the node's own answer.
            rc, listing = await livepve.ssh_run("pct list")
            assert rc == 0 and str(ctid) in listing, (
                f"CT {ctid} is not on the node, so nothing was interrupted:\n{listing}")

            # 1. unknown, not failed and not succeeded.
            with app.state.sessionmaker() as db:
                job = db.get(Job, job_id)
                job.status = "unknown"   # what _finish does; run_install only raises
                db.commit()
                cp = dict(job.checkpoint or {})

            # 2. the checkpoint names how far it got.
            assert cp.get("dispatched") is True
            assert cp["host_id"] == host_id and cp["ctid"] == ctid
            assert ctid not in cp["before_ctids"]

            # 3. a second install is refused while this is unresolved. This is
            #    the assertion the whole exercise is for.
            status, body = _install_route_refuses(app, host_id)
            assert status == 409, (
                f"the App Store answered {status} to a second install of the same "
                f"app on the same host while the first was unknown. That is how "
                f"one partial install becomes two containers.\n{body[:400]}")
            assert "interrupted" in body, (
                f"refused, but not for the unresolved-install reason: {body[:400]}")

            # 4. reconciliation asks the node.
            rid = _seed_job(app, "app.install.reconcile")
            out = await run_install_reconcile(JobContext(backend, job_id=rid),
                                              {"job_id": job_id})
            assert out["outcome"] == "container found" and out["ctid"] == ctid
            with app.state.sessionmaker() as db:
                assert db.get(Job, job_id).status == "succeeded"
                row = db.query(App).filter_by(host_id=host_id, ctid=ctid).one()
                assert row.catalog_slug == SLUG
            # and the refusal is no longer the unresolved-install one once the
            # job has an answer. It may still refuse for the tracked-CT reason,
            # which is the guard that now owns this container permanently.
            status2, body2 = _install_route_refuses(app, host_id)
            assert "interrupted" not in body2, (
                f"still blocked on an unresolved install after reconciliation "
                f"resolved it: {status2} {body2[:300]}")
        finally:
            done.set()
            killer.cancel()
            await _cleanup(app, host_id, ctid)

    asyncio.run(go())


@live_only
def test_proxploy_dies_during_reconciliation_and_does_not_redo_the_work(tmp_path):
    """TEST 2. Kill Proxploy while it is reconciling that partial install,
    restart, and prove the recovery path does not duplicate anything.

    Recovery code is where duplicate work hides, so the recovery path needs its
    own recovery test. A restart must reopen the SAME unresolved operation
    rather than starting a fresh install.
    """
    from proxploy.jobs import JobBackend, JobContext, JobUnknown
    from proxploy.models import App, Job
    from proxploy.services.appstore import run_install, run_install_reconcile

    app, host_id = livepve.live_app(tmp_path)
    ctid = livepve.assert_scratch(livepve.scratch_range()[1])
    _ingest(app)

    async def go():
        assert ctid not in livepve.lxc_ids(app, host_id)
        conns: list = []
        _capture_connections(app, conns)
        done = asyncio.Event()
        killer = asyncio.create_task(
            _kill_ssh_once_the_container_exists(app, host_id, ctid, conns, done))

        job_id = _seed_job(app)
        backend = JobBackend(app)
        try:
            with pytest.raises(JobUnknown):
                await run_install(
                    JobContext(backend, job_id=job_id),
                    {"catalog_slug": SLUG, "host_id": host_id, "ctid": ctid,
                     "name": f"int-{SLUG}", "overrides": _storage_overrides()})
            done.set()
            assert await killer, "the connection was never killed mid-install"
            with app.state.sessionmaker() as db:
                db.get(Job, job_id).status = "unknown"
                db.commit()

            # Proxploy dies WHILE reconciling: the reconcile job exists and is
            # running, and the process never returns from it.
            rid = _seed_job(app, "app.install.reconcile")

            # The restart. sweep_orphans is what boot runs.
            JobBackend(app).sweep_orphans()

            with app.state.sessionmaker() as db:
                # reopens the same unresolved operation, does not start a new install
                assert db.get(Job, job_id).status == "unknown", (
                    "the interrupted install must still be unresolved after a restart")
                assert db.get(Job, rid).status == "interrupted"
                installs = db.query(Job).filter_by(kind="app.install").all()
                assert [j.id for j in installs] == [job_id], (
                    "a restart created a second install job")
                # Not filtered on `queued`: enqueue hops to the loop and the
                # job may already be running by the time this reads it, which
                # is a scheduling race and not the behaviour under test. What
                # matters is that a reconciliation exists, that it names the
                # SAME install job, and that there is exactly one.
                requeued = [j for j in db.query(Job)
                            .filter(Job.kind == "app.install.reconcile").all()
                            if j.id != rid]
                assert [j.params["job_id"] for j in requeued] == [job_id], (
                    "the restart did not reopen the same unknown operation")
                new_rid = requeued[0].id

            # No second container was built by any of that. Counted as ROWS
            # whose first column is the id: `pct list` renders the row as
            # "9001 ... CT9001", so a substring count says two for one
            # container and would have failed on a product that was correct.
            rc, listing = await livepve.ssh_run("pct list")
            rows = [ln for ln in listing.splitlines()
                    if ln.split() and ln.split()[0] == str(ctid)]
            assert len(rows) == 1, f"expected exactly one CT {ctid}:\n{listing}"

            # The reopened reconciliation finishes the job the first one never
            # did, and it does so on its own: the restart queued it and the
            # backend ran it. Waited for rather than driven, because driving it
            # here would prove this test can call a function, not that a
            # restart recovers.
            deadline = asyncio.get_running_loop().time() + 60.0
            while asyncio.get_running_loop().time() < deadline:
                with app.state.sessionmaker() as db:
                    if db.get(Job, job_id).status != "unknown":
                        break
                await asyncio.sleep(1.0)

            with app.state.sessionmaker() as db:
                assert db.get(Job, job_id).status == "succeeded", (
                    "the restart did not resolve the interrupted install")
                assert db.query(App).filter_by(host_id=host_id, ctid=ctid).count() == 1, (
                    "reconciliation after a restart filed a duplicate App row")
                # And still exactly one install, so nothing re-ran the script.
                assert db.query(Job).filter_by(kind="app.install").count() == 1

            # A second reconciliation is a no-op rather than a second App row.
            # This is the assertion that matters most for a recovery path:
            # recovery code is where duplicate work hides.
            again = await run_install_reconcile(JobContext(backend, job_id=new_rid),
                                                {"job_id": job_id})
            assert again["outcome"] == "already resolved"
            with app.state.sessionmaker() as db:
                assert db.query(App).filter_by(host_id=host_id, ctid=ctid).count() == 1
        finally:
            done.set()
            killer.cancel()
            await _cleanup(app, host_id, ctid)

    asyncio.run(go())


def _install_route_refuses(app, host_id) -> tuple[int, str]:
    """POST the real route and report (status, body).

    Through the route on purpose. The route is where an operator actually
    re-installs, and a guard that lives only in the handler runs after the
    script has already been dispatched to a root shell, which is far too late
    to prevent a second container.

    Deliberately NOT a re-implementation of the guard's own query: a test that
    restates the thing it is testing passes whatever the product does.
    """
    from fastapi.testclient import TestClient

    c = TestClient(app)
    c.get("/api/v1/meta/health")
    csrf = c.cookies.get("pp_csrf")
    h = {"X-CSRF-Token": csrf} if csrf else {}
    pw = "Correct-Horse-Battery-9"
    c.post("/api/v1/users", json={"email": "int@x.io", "password": pw}, headers=h)
    c.post("/api/v1/auth/login", json={"email": "int@x.io", "password": pw}, headers=h)
    csrf = c.cookies.get("pp_csrf") or csrf
    h = {"X-CSRF-Token": csrf} if csrf else {}
    r = c.post(f"/api/v1/catalog/{SLUG}/install", headers=h,
               json={"host_id": host_id, "name": f"int-{SLUG}-again",
                     "consent": True})
    return r.status_code, r.text
