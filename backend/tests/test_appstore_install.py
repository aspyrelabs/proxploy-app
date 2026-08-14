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
    db.add(HostCredential(host_id=host_id, kind="api_token:monitoring",
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


def _seed_single_storage(pve, node="pve1"):
    """One candidate per content type: matches every real single-pool dev
    host today, so resolve_storage_pools takes its "sole candidate" branch
    instead of refusing. Task 4 made run_install call resolve_storage_pools
    on EVERY install, so any test whose scenario reaches the SSH step now
    needs a storage list here or it fails on "host has no storage carrying
    'rootdir'" before ever composing a command.
    """
    pve.storages_by_node[node] = [
        {"storage": "local", "content": "vztmpl", "enabled": 1, "active": 1},
        {"storage": "local-lvm", "content": "rootdir", "enabled": 1, "active": 1},
    ]


def _seed_job(db, job_id=1):
    # run_install is called directly here (not via backend.enqueue), but
    # ctx.log/ctx.progress still write job_events rows with a real FK to
    # jobs.id, so a Job row must exist first.
    db.add(Job(id=job_id, kind="app.install", status="running"))
    db.commit()


SHA = "d7bc6b59676456f7a8b3a20f24c3ca589d7fe2f6"


def _seed_catalog(db, installable=True, upstream_sha=SHA, raw=None):
    db.add(CatalogEntry(slug="redis", name="Redis", category="Databases",
                        installable=installable, script_path="ct/redis.sh",
                        upstream_sha=upstream_sha,
                        unsupported_reason=None if installable else "install script requires interactive input, no non-interactive entrypoint",
                        default_cpu=1, default_ram_mb=1024, default_disk_gb=4,
                        default_os="debian", default_os_version="13",
                        raw=raw if raw is not None else
                        {"ct_script": "...", "install_script": "msg_ok done"}))
    db.commit()


def _seed_installable_host(app, db, raw=None):
    """Host + an enrolled ssh_key credential + catalog row + job row."""
    from proxploy.models import HostCredential
    host = seed_host_row(db)
    sblob, sver = app.state.secretstore.encrypt(
        b"-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----")
    db.add(HostCredential(host_id=host.id, kind="ssh_key", encrypted_blob=sblob,
                          key_version=sver, public_meta="ssh-ed25519 AAAA fake"))
    _seed_api_token(app, db, host.id)
    _seed_catalog(db, raw=raw)
    _seed_job(db)
    db.commit()
    return host.id


def test_install_pins_script_and_creates_app_row(tmp_path):
    async def scenario():
        pve = FakePVE()
        _seed_single_storage(pve)
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
        _seed_single_storage(pve)
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
        #
        # `mode` is `generated`, not `default`: `default` is the one branch
        # that reaches build.func's interactive storage picker, and both
        # storage variables are sent on every install, never left for
        # build.func to auto-pick or ask about.
        assert cmd.startswith("TERM=xterm mode=generated PHS_SILENT=1 "
                              "var_cpu=2 var_ram=2048 "
                              "var_container_storage=local-lvm "
                              "var_template_storage=local "
                              "var_ctid=150 bash -c ")
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
        _seed_single_storage(pve)
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
        _seed_single_storage(pve)
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
        _seed_single_storage(pve)
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


# --- the payload script is recorded whatever shape upstream ships it in -----
#
# A normal app pins install/<slug>-install.sh under raw["install_script"].
# Five apps (coolify, dockge, dokploy, komodo, runtipi) instead delegate to
# tools/addon/<slug>.sh, pinned under raw["addon_script"]. Reading only the
# first key filed an AppScript row with EMPTY content and the sha256 of the
# empty string, so the script viewer showed nothing and the version diff
# compared against nothing.

ADDON_PAYLOAD = "msg_info \"Installing via addon\"\n$STD docker compose up -d\n"


def test_install_records_the_addon_script_when_that_is_the_payload(tmp_path):
    async def scenario():
        pve = FakePVE()
        _seed_single_storage(pve)
        app = make_job_app(tmp_path, fake=pve)
        with app.state.sessionmaker() as db:
            host_id = _seed_installable_host(
                app, db, raw={"ct_script": "...", "addon_script": ADDON_PAYLOAD})
        app.state.ssh_connect_factory = _ssh_that_builds(pve, 150)

        from proxploy.jobs import JobBackend
        result = await run_install(JobContext(JobBackend(app), job_id=1),
                                   {"catalog_slug": "redis", "host_id": host_id,
                                    "name": "Redis", "ctid": 150, "overrides": {}})

        with app.state.sessionmaker() as db:
            row = db.query(App).filter_by(slug=result["slug"]).one()
            script = db.query(AppScript).filter_by(app_id=row.id, version=1).one()
            assert script.content == ADDON_PAYLOAD
            assert script.content_sha256 == hashlib.sha256(
                ADDON_PAYLOAD.encode()).hexdigest()
            # The bug being closed: not empty, and not the sha of "".
            assert script.content_sha256 != hashlib.sha256(b"").hexdigest()

    asyncio.run(scenario())


def test_install_still_records_a_normal_install_script_unchanged(tmp_path):
    """The other half: the ordinary shape is untouched, and install_script
    wins if both keys are somehow present."""
    async def scenario():
        pve = FakePVE()
        _seed_single_storage(pve)
        app = make_job_app(tmp_path, fake=pve)
        with app.state.sessionmaker() as db:
            host_id = _seed_installable_host(
                app, db, raw={"ct_script": "...", "install_script": "msg_ok done",
                              "addon_script": ADDON_PAYLOAD})
        app.state.ssh_connect_factory = _ssh_that_builds(pve, 150)

        from proxploy.jobs import JobBackend
        result = await run_install(JobContext(JobBackend(app), job_id=1),
                                   {"catalog_slug": "redis", "host_id": host_id,
                                    "name": "Redis", "ctid": 150, "overrides": {}})

        with app.state.sessionmaker() as db:
            row = db.query(App).filter_by(slug=result["slug"]).one()
            script = db.query(AppScript).filter_by(app_id=row.id, version=1).one()
            assert script.content == "msg_ok done"
            assert script.content_sha256 == hashlib.sha256(b"msg_ok done").hexdigest()

    asyncio.run(scenario())


def test_the_executed_command_is_the_ct_script_either_way(tmp_path):
    """Recording changed; EXECUTION did not. An addon-delegating app still
    runs the pinned ct script, which performs the delegation itself at
    runtime. We never curl the addon script ourselves."""
    async def scenario():
        pve = FakePVE()
        _seed_single_storage(pve)
        app = make_job_app(tmp_path, fake=pve)
        with app.state.sessionmaker() as db:
            host_id = _seed_installable_host(
                app, db, raw={"ct_script": "...", "addon_script": ADDON_PAYLOAD})

        def _on_create_process(command):
            pve.add_ct(150, node="pve1", name="redis", status="running")

        fake = FakeSSHConnection(host_key_fingerprint="SHA256:abc", stdout_lines=[],
                                 stderr_lines=[], exit_status=0,
                                 on_create_process=_on_create_process)
        app.state.ssh_connect_factory = make_fake_connect_factory(fake)

        from proxploy.jobs import JobBackend
        await run_install(JobContext(JobBackend(app), job_id=1),
                          {"catalog_slug": "redis", "host_id": host_id,
                           "name": "Redis", "ctid": 150, "overrides": {}})

        cmd = fake.last_command
        assert f"/{SHA}/ct/redis.sh" in cmd
        assert "tools/addon/" not in cmd

    asyncio.run(scenario())


# --- Task 5: the CTID is optional -------------------------------------------
#
# Requiring an operator-typed container id was a bug: build.func assigns the
# next free one itself (`local requested_id="${var_ctid:-$NEXTID}"`) when
# told nothing. The contract that matters is ABSENCE, not emptiness: :1086
# separately reads `[[ -n "${var_ctid:-}" ]]`, which branches on non-empty,
# so an empty string would satisfy the first read and silently fail the
# second the moment build.func drops the colon form. Nothing here sends
# `ctid` any other way than fully absent from `params` or explicitly None.


def test_install_without_a_ctid_omits_var_ctid_and_records_the_id_the_node_picked(tmp_path):
    async def scenario():
        pve = FakePVE()
        _seed_single_storage(pve)
        app = make_job_app(tmp_path, fake=pve)
        with app.state.sessionmaker() as db:
            host_id = _seed_installable_host(app, db)

        def _on_create_process(command):
            # Stands in for the node auto-picking the next free id via
            # NEXTID, exactly what happens when var_ctid was never sent.
            pve.add_ct(151, node="pve1", name="redis", status="running")

        fake = FakeSSHConnection(host_key_fingerprint="SHA256:abc", stdout_lines=[],
                                 stderr_lines=[], exit_status=0,
                                 on_create_process=_on_create_process)
        app.state.ssh_connect_factory = make_fake_connect_factory(fake)

        from proxploy.jobs import JobBackend
        ctx = JobContext(JobBackend(app), job_id=1)
        result = await run_install(ctx, {"catalog_slug": "redis", "host_id": host_id,
                                         "name": "Redis", "ctid": None, "overrides": {}})

        cmd = fake.last_command
        assert cmd is not None
        assert "var_ctid" not in cmd

        with app.state.sessionmaker() as db:
            row = db.query(App).filter_by(slug=result["slug"]).one()
            assert row.ctid == 151, "the id build.func actually picked must be recorded"

    asyncio.run(scenario())


def test_install_without_a_ctid_fails_loudly_when_more_than_one_container_appears(tmp_path):
    """Stated weakness, implemented as written: the diff-based id inference
    assumes an install creates exactly one container. True for every ct/
    script today; this proves the failure is loud (JobFailed, no App row)
    rather than silently recording the wrong id."""
    async def scenario():
        pve = FakePVE()
        _seed_single_storage(pve)
        app = make_job_app(tmp_path, fake=pve)
        with app.state.sessionmaker() as db:
            host_id = _seed_installable_host(app, db)

        def _on_create_process(command):
            pve.add_ct(151, node="pve1", name="redis", status="running")
            pve.add_ct(152, node="pve1", name="redis-extra", status="running")

        fake = FakeSSHConnection(host_key_fingerprint="SHA256:abc", stdout_lines=[],
                                 stderr_lines=[], exit_status=0,
                                 on_create_process=_on_create_process)
        app.state.ssh_connect_factory = make_fake_connect_factory(fake)

        from proxploy.jobs import JobBackend
        ctx = JobContext(JobBackend(app), job_id=1)
        with pytest.raises(JobFailed, match="2 containers appeared"):
            await run_install(ctx, {"catalog_slug": "redis", "host_id": host_id,
                                    "name": "Redis", "ctid": None, "overrides": {}})

        with app.state.sessionmaker() as db:
            assert db.query(App).count() == 0, "a phantom App row was filed"

    asyncio.run(scenario())


def test_install_without_a_ctid_fails_when_the_script_exits_zero_without_building_anything(tmp_path):
    """Same false-success shape as the pinned-ctid case, just with nothing to
    diff against: zero containers appeared, so there is no id to record."""
    async def scenario():
        pve = FakePVE()
        _seed_single_storage(pve)
        app = make_job_app(tmp_path, fake=pve)
        with app.state.sessionmaker() as db:
            host_id = _seed_installable_host(app, db)

        app.state.ssh_connect_factory = _ssh_that_builds(pve, 151, creates=False)

        from proxploy.jobs import JobBackend
        ctx = JobContext(JobBackend(app), job_id=1)
        with pytest.raises(JobFailed, match="0 containers appeared"):
            await run_install(ctx, {"catalog_slug": "redis", "host_id": host_id,
                                    "name": "Redis", "ctid": None, "overrides": {}})

        with app.state.sessionmaker() as db:
            assert db.query(App).count() == 0

    asyncio.run(scenario())


def test_install_declines_telemetry_before_the_script_can_ask(tmp_path):
    """build.func's diagnostics_check() draws an interactive whiptail radiolist
    ("TELEMETRY & DIAGNOSTICS") whenever /usr/local/community-scripts/diagnostics
    is absent. That is the select_storage failure shape again, in a third
    place, and it arrived from upstream with no change on our side.

    There is no environment variable to assert on here, and that is the point:
    variables() does a hard `DIAGNOSTICS="no"` assignment rather than
    `${DIAGNOSTICS:-no}`, so an exported value is overwritten before
    diagnostics_check() runs, and that function branches on the FILE, not the
    variable. So the only thing that can be proved is that the file is put in
    place first, and that it is created rather than overwritten.

    It must also be its own SSH command: `env` is inlined as a `KEY=value ...`
    prefix, and those assignments apply only to the first simple command, so a
    guard glued onto the install with `;` would strip mode/PHS_SILENT/var_*
    off the install itself. Asserting on the ORDER and the SEPARATION is what
    stops a future refactor from folding them together.
    """
    async def scenario():
        pve = FakePVE()
        _seed_single_storage(pve)
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
                                "name": "Redis", "ctid": 150, "overrides": {}})

        assert len(cmds) == 2, f"expected opt-out then install, got {cmds}"
        opt_out, install = cmds

        # First, and before anything can prompt.
        assert "/usr/local/community-scripts/diagnostics" in opt_out
        assert "DIAGNOSTICS=no" in opt_out
        # Created only when absent: an operator who opted IN from the node's
        # own shell keeps their answer. This refuses to be ASKED the question
        # in a session with no terminal, it does not answer it for them.
        assert "[ -e /usr/local/community-scripts/diagnostics ]" in opt_out

        # Separate commands, and the install keeps its inlined env.
        assert "bash -c " not in opt_out
        assert install.startswith("TERM=xterm mode=generated PHS_SILENT=1 ")
        assert "/usr/local/community-scripts" not in install

    asyncio.run(scenario())
