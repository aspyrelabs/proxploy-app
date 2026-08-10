import asyncio
import hashlib

import pytest

from proxploy.jobs import JobContext, JobFailed
from proxploy.models import App, AppScript, CatalogEntry, Job
from proxploy.services.appstore import run_install
from tests.fakes.pve import FakePVE
from tests.fakes.ssh import FakeSSHConnection, make_fake_connect_factory
from tests.support import make_job_app, seed_host_row


def _seed_api_token(app, db, host_id):
    """run_install's before/after CT check reads /cluster/resources through
    client_for_host, exactly as run_update's guard already did."""
    from proxploy.models import HostCredential

    blob, ver = app.state.secretstore.encrypt(
        b'{"token_id": "root@pam!t", "token_secret": "s"}')
    db.add(HostCredential(host_id=host_id, kind="api_token",
                          encrypted_blob=blob, key_version=ver))


def _ssh_that_builds(fake_pve, ctid, *, creates=True, exit_status=0,
                     stdout_lines=("Setup Redis",)):
    """Fake SSH whose "script" also makes the container appear on the fake PVE,
    which is what a real catalog script does and what run_install's post-check
    reads back. `creates=False` reproduces build.func's cancel path: exit 0
    with nothing built.
    """
    def _on_create_process(command):
        if creates:
            fake_pve.add_ct(ctid, node="pve1", name="redis", status="running")

    return make_fake_connect_factory(FakeSSHConnection(
        host_key_fingerprint="SHA256:abc", stdout_lines=list(stdout_lines),
        stderr_lines=[], exit_status=exit_status,
        on_create_process=_on_create_process))


def _seed_job(db, job_id=1):
    # run_install is called directly here (not via backend.enqueue), but
    # ctx.log/ctx.progress still write job_events rows with a real FK to
    # jobs.id, so a Job row must exist first.
    db.add(Job(id=job_id, kind="app.install", status="running"))
    db.commit()


SHA = "d7bc6b59676456f7a8b3a20f24c3ca589d7fe2f6"


def _seed_catalog(db, installable=True, upstream_sha=SHA):
    db.add(CatalogEntry(slug="redis", name="Redis", category="Databases",
                        installable=installable, script_path="ct/redis.sh",
                        upstream_sha=upstream_sha,
                        unsupported_reason=None if installable else "install script requires interactive input, no non-interactive entrypoint",
                        default_cpu=1, default_ram_mb=1024, default_disk_gb=4,
                        default_os="debian", default_os_version="13",
                        raw={"ct_script": "...", "install_script": "msg_ok done"}))
    db.commit()


def _seed_installable_host(app, db):
    """Host + an enrolled ssh_key credential + catalog row + job row."""
    from proxploy.models import HostCredential
    host = seed_host_row(db)
    sblob, sver = app.state.secretstore.encrypt(
        b"-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----")
    db.add(HostCredential(host_id=host.id, kind="ssh_key", encrypted_blob=sblob,
                          key_version=sver, public_meta="ssh-ed25519 AAAA fake"))
    _seed_api_token(app, db, host.id)
    _seed_catalog(db)
    _seed_job(db)
    db.commit()
    return host.id


def test_install_pins_script_and_creates_app_row(tmp_path):
    async def scenario():
        pve = FakePVE()
        app = make_job_app(tmp_path, fake=pve)
        with app.state.sessionmaker() as db:
            host = seed_host_row(db)
            from proxploy.models import HostCredential
            sblob, sver = app.state.secretstore.encrypt(b"-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----")
            db.add(HostCredential(host_id=host.id, kind="ssh_key", encrypted_blob=sblob,
                                  key_version=sver, public_meta="ssh-ed25519 AAAA fake"))
            _seed_api_token(app, db, host.id)
            _seed_catalog(db)
            _seed_job(db)
            db.commit()
            host_id = host.id

        app.state.ssh_connect_factory = _ssh_that_builds(pve, 150)

        from proxploy.jobs import JobBackend
        backend = JobBackend(app)
        ctx = JobContext(backend, job_id=1)
        result = await run_install(ctx, {"catalog_slug": "redis", "host_id": host_id,
                                         "name": "Redis", "ctid": 150, "overrides": {}})

        with app.state.sessionmaker() as db:
            row = db.query(App).filter_by(slug=result["slug"]).one()
            assert row.catalog_slug == "redis" and row.ctid == 150 and row.host_id == host_id
            script = db.query(AppScript).filter_by(app_id=row.id, version=1).one()
            assert script.source == "upstream"
            assert script.content_sha256 == hashlib.sha256(b"msg_ok done").hexdigest()

    asyncio.run(scenario())


def test_install_sends_var_ctid_and_overrides_inline_on_the_command(tmp_path):
    """Critical #1: `ctid` was never sent to the remote script at all (so the
    CT landed on whatever ID build.func auto-picked), and the whole env dict
    went out as SSH env channel requests that a default sshd drops. Both are
    proved here by asserting on the real composed command string.

    Critical #2: that command must curl the pinned commit, not `main`.
    """
    async def scenario():
        pve = FakePVE()
        app = make_job_app(tmp_path, fake=pve)
        with app.state.sessionmaker() as db:
            host_id = _seed_installable_host(app, db)

        cmds: list[str] = []

        def _on_create_process(command):
            cmds.append(command)
            pve.add_ct(150, node="pve1", name="redis", status="running")

        fake = FakeSSHConnection(host_key_fingerprint="SHA256:abc", stdout_lines=[],
                                 stderr_lines=[], exit_status=0,
                                 on_create_process=_on_create_process)
        app.state.ssh_connect_factory = make_fake_connect_factory(fake)

        from proxploy.jobs import JobBackend
        ctx = JobContext(JobBackend(app), job_id=1)
        await run_install(ctx, {"catalog_slug": "redis", "host_id": host_id,
                                "name": "Redis", "ctid": 150,
                                "overrides": {"cpu": 2, "ram": 2048}})

        cmd = fake.last_command
        assert cmd is not None
        # Bug A: the operator's chosen CTID actually reaches build.func.
        assert "var_ctid=150" in cmd
        # Bug B: mode/PHS_SILENT/var_* are inlined on the command, not handed
        # to asyncssh's env= (which stock sshd silently discards).
        #
        # `mode` is lowercase and TERM is present for the reasons run_install
        # and executor/ssh.py document: build.func reads `${mode:-...}` and
        # never MODE, and a TERM=dumb session fails its `clear`. With the old
        # uppercase spelling this assertion passed while every real install
        # showed a menu and quietly did nothing.
        assert cmd.startswith("TERM=xterm mode=default PHS_SILENT=1 "
                              "var_cpu=2 var_ram=2048 var_ctid=150 bash -c ")
        # Critical #2: pinned commit, never the moving `main` ref.
        assert (f"https://raw.githubusercontent.com/community-scripts/ProxmoxVE/"
                f"{SHA}/ct/redis.sh") in cmd
        assert "/ProxmoxVE/main/" not in cmd

    asyncio.run(scenario())


def test_install_refuses_an_entry_with_no_pinned_commit(tmp_path):
    """No upstream_sha means there is no commit to execute that matches what
    was classified and diffed, refuse rather than fall back to `main`."""
    async def scenario():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            host = seed_host_row(db)
            _seed_catalog(db, upstream_sha=None)
            _seed_job(db)
            db.commit()
            host_id = host.id

        from proxploy.jobs import JobBackend
        ctx = JobContext(JobBackend(app), job_id=1)
        with pytest.raises(JobFailed, match="no pinned upstream commit"):
            await run_install(ctx, {"catalog_slug": "redis", "host_id": host_id,
                                    "name": "Redis", "ctid": 150, "overrides": {}})

    asyncio.run(scenario())


def test_install_refuses_an_unsupported_catalog_entry(tmp_path):
    async def scenario():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            host = seed_host_row(db)
            _seed_catalog(db, installable=False)
            _seed_job(db)
            db.commit()
            host_id = host.id

        from proxploy.jobs import JobBackend
        backend = JobBackend(app)
        ctx = JobContext(backend, job_id=1)
        with pytest.raises(JobFailed, match="not installable"):
            await run_install(ctx, {"catalog_slug": "redis", "host_id": host_id,
                                    "name": "Redis", "ctid": 150, "overrides": {}})

    asyncio.run(scenario())


def test_install_fails_without_an_enrolled_ssh_key(tmp_path):
    async def scenario():
        pve = FakePVE()
        app = make_job_app(tmp_path, fake=pve)
        with app.state.sessionmaker() as db:
            host = seed_host_row(db)
            # api_token only: the CT pre-check runs before the SSH step now, so
            # without one this would fail on the token instead of the key.
            _seed_api_token(app, db, host.id)
            _seed_catalog(db)
            _seed_job(db)
            db.commit()
            host_id = host.id

        from proxploy.jobs import JobBackend
        backend = JobBackend(app)
        ctx = JobContext(backend, job_id=1)
        with pytest.raises(JobFailed, match="ssh_key"):
            await run_install(ctx, {"catalog_slug": "redis", "host_id": host_id,
                                    "name": "Redis", "ctid": 150, "overrides": {}})

    asyncio.run(scenario())


def test_install_fails_when_the_script_exits_zero_without_building_the_ct(tmp_path):
    """The false success a real node exposed on 2026-08-10.

    build.func's own cancel path (`whiptail ... || exit_script`) exits 0. With
    the wrong `mode` spelling every install took it, so the script did nothing
    and this handler nonetheless filed an App row for a container that was
    never created. Exit status alone cannot tell the two apart; only reading
    the CT list back can.
    """
    async def scenario():
        pve = FakePVE()
        app = make_job_app(tmp_path, fake=pve)
        with app.state.sessionmaker() as db:
            host_id = _seed_installable_host(app, db)

        app.state.ssh_connect_factory = _ssh_that_builds(pve, 150, creates=False)

        from proxploy.jobs import JobBackend
        ctx = JobContext(JobBackend(app), job_id=1)
        with pytest.raises(JobFailed, match="does not exist"):
            await run_install(ctx, {"catalog_slug": "redis", "host_id": host_id,
                                    "name": "Redis", "ctid": 150, "overrides": {}})

        with app.state.sessionmaker() as db:
            assert db.query(App).count() == 0, "a phantom App row was filed"

    asyncio.run(scenario())


def test_install_refuses_a_ctid_that_already_exists(tmp_path):
    """Installing onto a live CTID would let the catalog script reconfigure a
    container Proxploy does not own, and then file an App row claiming it."""
    async def scenario():
        pve = FakePVE()
        pve.add_ct(150, node="pve1", name="somebody-elses", status="running")
        app = make_job_app(tmp_path, fake=pve)
        with app.state.sessionmaker() as db:
            host_id = _seed_installable_host(app, db)

        ran: list[str] = []
        app.state.ssh_connect_factory = make_fake_connect_factory(FakeSSHConnection(
            host_key_fingerprint="SHA256:abc", stdout_lines=[], stderr_lines=[],
            exit_status=0, on_create_process=ran.append))

        from proxploy.jobs import JobBackend
        ctx = JobContext(JobBackend(app), job_id=1)
        with pytest.raises(JobFailed, match="already exists"):
            await run_install(ctx, {"catalog_slug": "redis", "host_id": host_id,
                                    "name": "Redis", "ctid": 150, "overrides": {}})
        assert ran == [], "refused too late: the script had already run"

    asyncio.run(scenario())
