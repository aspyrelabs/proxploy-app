"""An install interrupted after the script reached a root shell.

`failed` is a claim: it tells an operator the node was not changed. An install
dispatches a pinned community script to a root shell, so a connection that dies
after the dispatch leaves a node that may be untouched, halfway through, or
fully built. Reporting that as failed is what turned one partial install into
two containers: the operator installs again, the ctid field is blank by the
dialog's own advice, the node hands out the next free id, and the container the
first run really built is orphaned.

These cover the machinery on fakes. The two hardware tests in
test_apps_pve_integration.py are what prove it against a real node, which is
where the failure class actually lives.
"""
import asyncio

import pytest

from proxploy.jobs import JobBackend, JobContext, JobFailed, JobUnknown
from proxploy.models import App, Job
from proxploy.services.appstore import run_install, run_install_reconcile
from tests.fakes.pve import FakePVE
from tests.fakes.ssh import FakeSSHConnection, make_fake_connect_factory
from tests.support import make_job_app, seed_host_row

CTID = 150


def _seed(app, pve):
    from proxploy.models import CatalogEntry, HostCredential

    with app.state.sessionmaker() as db:
        host = seed_host_row(db)
        sblob, sver = app.state.secretstore.encrypt(
            b"-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----")
        db.add(HostCredential(host_id=host.id, kind="ssh_key", encrypted_blob=sblob,
                              key_version=sver, public_meta="ssh-ed25519 AAAA fake"))
        tblob, tver = app.state.secretstore.encrypt(
            b'{"token_id": "root@pam!t", "token_secret": "s"}')
        db.add(HostCredential(host_id=host.id, kind="api_token:monitoring",
                              encrypted_blob=tblob, key_version=tver))
        db.add(CatalogEntry(slug="redis", name="Redis", category="Databases",
                            installable=True, upstream_sha="a" * 40,
                            script_path="ct/redis.sh",
                            default_cpu=1, default_ram_mb=1024, default_disk_gb=4,
                            default_os="debian", default_os_version="13",
                            raw={"ct_script": "...", "install_script": "msg_ok done"}))
        db.add(Job(id=1, kind="app.install", status="running"))
        db.commit()
        return host.id


def _seed_storage(pve, node="pve1"):
    """One candidate per content type, so resolve_storage_pools takes its sole
    candidate branch. Same shape as test_appstore_install's own helper: without
    it every scenario here fails before it composes an SSH command."""
    pve.storages_by_node[node] = [
        {"storage": "local", "content": "vztmpl", "enabled": 1, "active": 1},
        {"storage": "local-lvm", "content": "rootdir", "enabled": 1, "active": 1},
    ]


class _Dropped(OSError):
    """Stands in for asyncssh losing the channel mid-command."""


def _ssh_that_builds_then_drops(pve, ctid):
    """The script really creates the container, then the connection dies.

    This is the shape that matters: the effect landed on the node and the
    process that dispatched it never found out.
    """
    def _on_create_process(command):
        pve.add_ct(ctid, node="pve1", name="redis", status="running")
        raise _Dropped("connection lost")

    return make_fake_connect_factory(FakeSSHConnection(
        host_key_fingerprint="SHA256:abc", stdout_lines=[], stderr_lines=[],
        exit_status=0, on_create_process=_on_create_process))


def _ssh_that_drops_building_nothing():
    def _on_create_process(command):
        raise _Dropped("connection lost")

    return make_fake_connect_factory(FakeSSHConnection(
        host_key_fingerprint="SHA256:abc", stdout_lines=[], stderr_lines=[],
        exit_status=0, on_create_process=_on_create_process))


def _run(coro_fn):
    return asyncio.run(coro_fn())


def test_a_lost_connection_after_dispatch_is_unknown_not_failed(tmp_path):
    async def scenario():
        pve = FakePVE(); _seed_storage(pve)
        app = make_job_app(tmp_path, fake=pve)
        host_id = _seed(app, pve)
        app.state.ssh_connect_factory = _ssh_that_builds_then_drops(pve, CTID)

        ctx = JobContext(JobBackend(app), job_id=1)
        with pytest.raises(JobUnknown):
            await run_install(ctx, {"catalog_slug": "redis", "host_id": host_id,
                                    "name": "Redis", "ctid": CTID, "overrides": {}})

        # The checkpoint is what makes the answer recoverable at all.
        with app.state.sessionmaker() as db:
            cp = db.get(Job, 1).checkpoint
        assert cp and cp["dispatched"] is True
        assert cp["host_id"] == host_id and cp["ctid"] == CTID
        assert CTID not in cp["before_ctids"], (
            "before_ctids must be the state BEFORE the script ran")
    _run(scenario)


def test_a_connection_that_never_opened_is_failed(tmp_path):
    """SSHUnreachable is raised before `async with conn`, so the script never
    ran and there is nothing on the node to reconcile. Calling that unknown
    would block the App Store on installs that provably did nothing."""
    async def scenario():
        pve = FakePVE(); _seed_storage(pve)
        app = make_job_app(tmp_path, fake=pve)
        host_id = _seed(app, pve)

        async def refuse(host, key, *, pinned_fingerprint, on_new_fingerprint):
            from proxploy.executor.ssh import SSHUnreachable
            raise SSHUnreachable("could not open an SSH connection")
        app.state.ssh_connect_factory = refuse

        ctx = JobContext(JobBackend(app), job_id=1)
        with pytest.raises(JobFailed):
            await run_install(ctx, {"catalog_slug": "redis", "host_id": host_id,
                                    "name": "Redis", "ctid": CTID, "overrides": {}})
    _run(scenario)


def test_reconcile_finds_the_container_and_records_the_app(tmp_path):
    """The install did complete. Reconciliation asks the node, files the App
    row the interrupted run never got to file, and moves the job to succeeded.

    Filing the row is the point: it is what makes catalog.py's existing
    (host_id, ctid) guard refuse a duplicate from then on.
    """
    async def scenario():
        pve = FakePVE(); _seed_storage(pve)
        app = make_job_app(tmp_path, fake=pve)
        host_id = _seed(app, pve)
        app.state.ssh_connect_factory = _ssh_that_builds_then_drops(pve, CTID)

        backend = JobBackend(app)
        with pytest.raises(JobUnknown):
            await run_install(JobContext(backend, job_id=1),
                              {"catalog_slug": "redis", "host_id": host_id,
                               "name": "Redis", "ctid": CTID, "overrides": {}})
        with app.state.sessionmaker() as db:
            db.get(Job, 1).status = "unknown"
            db.add(Job(id=2, kind="app.install.reconcile", status="running"))
            db.commit()

        out = await run_install_reconcile(JobContext(backend, job_id=2),
                                          {"job_id": 1})
        assert out["outcome"] == "container found" and out["ctid"] == CTID

        with app.state.sessionmaker() as db:
            assert db.get(Job, 1).status == "succeeded"
            row = db.query(App).filter_by(host_id=host_id, ctid=CTID).one()
            # Left NULL on purpose: the success path reads the URL from the
            # script's last lines, and those went with the connection.
            assert row.installed_url is None
    _run(scenario)


def test_reconcile_says_failed_when_nothing_was_built(tmp_path):
    """No container appeared, so the install really did nothing. `failed` is
    correct here, and now it is said after asking the node rather than assumed
    from an exception."""
    async def scenario():
        pve = FakePVE(); _seed_storage(pve)
        app = make_job_app(tmp_path, fake=pve)
        host_id = _seed(app, pve)
        app.state.ssh_connect_factory = _ssh_that_drops_building_nothing()

        backend = JobBackend(app)
        with pytest.raises(JobUnknown):
            await run_install(JobContext(backend, job_id=1),
                              {"catalog_slug": "redis", "host_id": host_id,
                               "name": "Redis", "ctid": CTID, "overrides": {}})
        with app.state.sessionmaker() as db:
            db.get(Job, 1).status = "unknown"
            db.add(Job(id=2, kind="app.install.reconcile", status="running"))
            db.commit()

        out = await run_install_reconcile(JobContext(backend, job_id=2), {"job_id": 1})
        assert out["outcome"] == "nothing was built"
        with app.state.sessionmaker() as db:
            assert db.get(Job, 1).status == "failed"
            assert db.query(App).count() == 0
    _run(scenario)


def test_reconcile_is_idempotent(tmp_path):
    """Running it twice must not file two App rows. This is the guard that
    matters for TEST 2: a recovery path is where duplicate work hides."""
    async def scenario():
        pve = FakePVE(); _seed_storage(pve)
        app = make_job_app(tmp_path, fake=pve)
        host_id = _seed(app, pve)
        app.state.ssh_connect_factory = _ssh_that_builds_then_drops(pve, CTID)

        backend = JobBackend(app)
        with pytest.raises(JobUnknown):
            await run_install(JobContext(backend, job_id=1),
                              {"catalog_slug": "redis", "host_id": host_id,
                               "name": "Redis", "ctid": CTID, "overrides": {}})
        with app.state.sessionmaker() as db:
            db.get(Job, 1).status = "unknown"
            db.add(Job(id=2, kind="app.install.reconcile", status="running"))
            db.add(Job(id=3, kind="app.install.reconcile", status="running"))
            db.commit()

        first = await run_install_reconcile(JobContext(backend, job_id=2), {"job_id": 1})
        second = await run_install_reconcile(JobContext(backend, job_id=3), {"job_id": 1})
        assert first["outcome"] == "container found"
        assert second["outcome"] == "already resolved"
        with app.state.sessionmaker() as db:
            assert db.query(App).filter_by(host_id=host_id, ctid=CTID).count() == 1
    _run(scenario)


def test_sweep_orphans_splits_dispatched_from_never_started(tmp_path):
    """Proxploy dying is the other way to be interrupted, and it lands on the
    same reconciler through the same checkpoint. A job that never dispatched
    stays `interrupted`, which still honestly means nothing happened."""
    async def scenario():
        app = make_job_app(tmp_path, fake=FakePVE())
        with app.state.sessionmaker() as db:
            db.add(Job(id=10, kind="app.install", status="running",
                       checkpoint={"dispatched": True, "before_ctids": [],
                                   "host_id": 1, "ctid": CTID,
                                   "catalog_slug": "redis"}))
            db.add(Job(id=11, kind="app.install", status="running"))
            db.add(Job(id=12, kind="host.sync", status="queued"))
            db.commit()

        JobBackend(app).sweep_orphans()
        with app.state.sessionmaker() as db:
            assert db.get(Job, 10).status == "unknown"
            assert db.get(Job, 11).status == "interrupted"
            assert db.get(Job, 12).status == "interrupted"
            queued = (db.query(Job)
                      .filter_by(kind="app.install.reconcile").all())
            assert [j.params["job_id"] for j in queued] == [10], (
                "exactly the dispatched install should be reconciled")
    _run(scenario)
