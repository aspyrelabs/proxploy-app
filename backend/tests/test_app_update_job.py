"""`app.update`, same pin/stream/archive path as install (doc 10 Phase 7)."""
import asyncio

import pytest

from proxploy.jobs import HANDLERS, JobBackend, JobContext, JobFailed
from proxploy.models import App, AppScript, CatalogEntry, Host, HostCredential, Job, utcnow
from proxploy.services import appstore as _appstore  # noqa: F401  (registers app.update)
from tests.fakes.pve import FakePVE
from tests.fakes.ssh import FakeSSHConnection, make_fake_connect_factory
from tests.support import make_job_app, seed_host_row


def _seed(app, *, ctid=101, pinned="a" * 40, upstream="b" * 40, script_source="upstream"):
    with app.state.sessionmaker() as db:
        host = seed_host_row(db)
        # api_token: client_for_host()/_lxc_ids' live /cluster/resources guard.
        ablob, aver = app.state.secretstore.encrypt(
            b'{"token_id": "root@pam!t", "token_secret": "s"}')
        db.add(HostCredential(host_id=host.id, kind="api_token:monitoring",
                              encrypted_blob=ablob, key_version=aver))
        # ssh_key: SSHExecutor.run_for_host's get_ssh_private_key.
        sblob, sver = app.state.secretstore.encrypt(
            b"-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----")
        db.add(HostCredential(host_id=host.id, kind="ssh_key",
                              encrypted_blob=sblob, key_version=sver,
                              public_meta="ssh-ed25519 AAAA fake"))
        db.add(CatalogEntry(slug="redis", name="Redis", script_path="ct/redis.sh",
                            upstream_sha=upstream, installable=True,
                            raw={"install_script": "#!/bin/bash\n"}))
        a = App(host_id=host.id, ctid=ctid, name="Redis", slug=f"redis-{host.id}-{ctid}",
                catalog_slug="redis", web_protocol="http", web_path="/",
                adopted=True, update_available=upstream[:7])
        db.add(a)
        db.flush()
        db.add(AppScript(app_id=a.id, version=1, content="#!/bin/bash\n",
                         content_sha256="0" * 64, source=script_source,
                         upstream_ref=pinned))
        db.commit()
        return host.id, a.id


def _job(app, app_id):
    with app.state.sessionmaker() as db:
        j = Job(kind="app.update", status="running", target_type="app",
                target_id=app_id, params={"app_id": app_id})
        db.add(j)
        db.commit()
        return j.id


def _ssh(recorder, exit_status=0, lines=("updating...",), on_run=None):
    """Fake asyncssh connect factory: records the composed command into
    `recorder` (matching FakeSSHConnection.last_command, captured because env
    vars are inlined onto the command string) and, if given, calls `on_run`
    right after the command is issued, used to simulate the catalog script
    creating a stray CT mid-run, before the post-check reads back."""
    def _on_create_process(command):
        recorder.append(command)
        if on_run is not None:
            on_run(command)

    fake = FakeSSHConnection(host_key_fingerprint="SHA256:abc",
                             stdout_lines=list(lines), stderr_lines=[],
                             exit_status=exit_status,
                             on_create_process=_on_create_process)
    return make_fake_connect_factory(fake)


def test_update_runs_the_new_pinned_commit_and_advances_the_script_pin(tmp_path):
    async def go():
        fake = FakePVE()
        fake.add_ct(101, node="pve1", name="redis", status="running")
        cmds: list[str] = []
        app = make_job_app(tmp_path, fake=fake, ssh_factory=_ssh(cmds))
        app.state.jobs = JobBackend(app)
        host_id, app_id = _seed(app)

        ctx = JobContext(app.state.jobs, _job(app, app_id))
        out = await HANDLERS["app.update"](ctx, {"app_id": app_id})

        assert out["from_ref"] == "a" * 40
        assert out["to_ref"] == "b" * 40
        # Pinned to the NEW commit, never to `main`: same rule as install.
        assert "b" * 40 in cmds[0]
        assert "/main/" not in cmds[0].split("build.func")[0]

        with app.state.sessionmaker() as db:
            a = db.get(App, app_id)
            assert a.update_available is None          # cleared on success
            latest = (db.query(AppScript).filter_by(app_id=app_id)
                      .order_by(AppScript.version.desc()).first())
            assert latest.version == 2
            assert latest.upstream_ref == "b" * 40
            assert latest.source == "upstream"
        assert out["script_version"] == 2

    asyncio.run(go())


def test_update_refuses_when_the_container_is_missing(tmp_path):
    """Without this the script takes its install branch and builds a SECOND
    container while the apps row keeps pointing at the old CTID."""
    async def go():
        fake = FakePVE()                              # no CT 101 anywhere
        cmds: list[str] = []
        app = make_job_app(tmp_path, fake=fake, ssh_factory=_ssh(cmds))
        app.state.jobs = JobBackend(app)
        _, app_id = _seed(app)

        ctx = JobContext(app.state.jobs, _job(app, app_id))
        with pytest.raises(JobFailed) as e:
            await HANDLERS["app.update"](ctx, {"app_id": app_id})
        assert "101" in str(e.value)
        assert cmds == []                             # nothing ever ran over SSH

    asyncio.run(go())


def test_update_fails_loudly_if_a_new_container_appeared(tmp_path):
    """The post-check. The script decided to install; say so and name the CTID
    rather than report success over a stray container.

    Review B1/B2: the message must (a) never issue a bare "remove it"
    instruction; this is a whole-cluster snapshot diff and JobBackend runs
    jobs concurrently, so a stray id is not proof of what built it; and (b)
    warn that a bare retry will likely hit the same install branch again."""
    async def go():
        fake = FakePVE()
        fake.add_ct(101, node="pve1", name="redis", status="running")
        cmds: list[str] = []

        def on_run(_cmd):
            fake.add_ct(999, node="pve1", name="redis", status="running")

        app = make_job_app(tmp_path, fake=fake,
                           ssh_factory=_ssh(cmds, lines=("done",), on_run=on_run))
        app.state.jobs = JobBackend(app)
        _, app_id = _seed(app)

        ctx = JobContext(app.state.jobs, _job(app, app_id))
        with pytest.raises(JobFailed) as e:
            await HANDLERS["app.update"](ctx, {"app_id": app_id})
        msg = str(e.value)
        assert "999" in msg
        assert "removed by hand" not in msg.lower()     # B1: no destroy order
        assert "may have been created" in msg           # B1: attribution is uncertain
        assert "verify" in msg.lower()
        assert "retry" in msg.lower() or "retrying" in msg.lower()  # B2
        assert "resolve" in msg.lower()

        with app.state.sessionmaker() as db:
            a = db.get(App, app_id)
            assert a.update_available == "b" * 7        # B2: still offered, honestly

    asyncio.run(go())


def test_update_does_not_blame_a_concurrent_app_install_for_the_stray(tmp_path):
    """Review B1: JobBackend's MAX_CONCURRENT means an id appearing in `after`
    may belong to an unrelated app.install that landed in the same window, not
    to this update's script taking the install branch. A CT this handler can
    attribute to another job's params["ctid"] must not fail the update."""
    async def go():
        fake = FakePVE()
        fake.add_ct(101, node="pve1", name="redis", status="running")
        cmds: list[str] = []

        def on_run(_cmd):
            fake.add_ct(300, node="pve1", name="other-app", status="running")

        app = make_job_app(tmp_path, fake=fake,
                           ssh_factory=_ssh(cmds, on_run=on_run))
        app.state.jobs = JobBackend(app)
        host_id, app_id = _seed(app)

        with app.state.sessionmaker() as db:
            db.add(Job(kind="app.install", status="running", target_type="app",
                      params={"ctid": 300, "host_id": host_id,
                              "catalog_slug": "other", "name": "other-app"},
                      started_at=utcnow()))
            db.commit()

        ctx = JobContext(app.state.jobs, _job(app, app_id))
        out = await HANDLERS["app.update"](ctx, {"app_id": app_id})
        assert out["to_ref"] == "b" * 40                # succeeded despite CT 300

    asyncio.run(go())


def test_update_still_fails_for_a_stray_no_concurrent_job_can_account_for(tmp_path):
    """The concurrency exclusion must not swallow a real stray: an app.install
    job for a DIFFERENT ctid running at the same time must not excuse CT 999."""
    async def go():
        fake = FakePVE()
        fake.add_ct(101, node="pve1", name="redis", status="running")
        cmds: list[str] = []

        def on_run(_cmd):
            fake.add_ct(999, node="pve1", name="redis", status="running")

        app = make_job_app(tmp_path, fake=fake,
                           ssh_factory=_ssh(cmds, on_run=on_run))
        app.state.jobs = JobBackend(app)
        host_id, app_id = _seed(app)

        with app.state.sessionmaker() as db:
            db.add(Job(kind="app.install", status="running", target_type="app",
                      params={"ctid": 300, "host_id": host_id,
                              "catalog_slug": "other", "name": "other-app"},
                      started_at=utcnow()))
            db.commit()

        ctx = JobContext(app.state.jobs, _job(app, app_id))
        with pytest.raises(JobFailed) as e:
            await HANDLERS["app.update"](ctx, {"app_id": app_id})
        assert "999" in str(e.value)

    asyncio.run(go())


def test_a_nonzero_exit_fails_the_job_and_leaves_the_pin_alone(tmp_path):
    async def go():
        fake = FakePVE()
        fake.add_ct(101, node="pve1", name="redis", status="running")
        cmds: list[str] = []
        app = make_job_app(tmp_path, fake=fake, ssh_factory=_ssh(cmds, exit_status=2))
        app.state.jobs = JobBackend(app)
        _, app_id = _seed(app)

        ctx = JobContext(app.state.jobs, _job(app, app_id))
        with pytest.raises(JobFailed) as e:
            await HANDLERS["app.update"](ctx, {"app_id": app_id})
        assert "exited 2" in str(e.value)

        with app.state.sessionmaker() as db:
            a = db.get(App, app_id)
            assert a.update_available == "b" * 7      # still offered, correctly
            assert db.query(AppScript).filter_by(app_id=app_id).count() == 1

    asyncio.run(go())


def test_update_refuses_an_app_already_on_the_catalog_commit(tmp_path):
    async def go():
        fake = FakePVE()
        fake.add_ct(101, node="pve1", name="redis", status="running")
        cmds: list[str] = []
        app = make_job_app(tmp_path, fake=fake, ssh_factory=_ssh(cmds))
        app.state.jobs = JobBackend(app)
        _, app_id = _seed(app, pinned="a" * 40, upstream="a" * 40)

        ctx = JobContext(app.state.jobs, _job(app, app_id))
        with pytest.raises(JobFailed) as e:
            await HANDLERS["app.update"](ctx, {"app_id": app_id})
        assert "already" in str(e.value).lower()
        assert cmds == []

    asyncio.run(go())


def test_update_refuses_an_app_with_no_catalog_entry(tmp_path):
    async def go():
        fake = FakePVE()
        fake.add_ct(101, node="pve1", name="custom", status="running")
        app = make_job_app(tmp_path, fake=fake, ssh_factory=_ssh([]))
        app.state.jobs = JobBackend(app)
        with app.state.sessionmaker() as db:
            host = seed_host_row(db)
            a = App(host_id=host.id, ctid=101, name="custom", slug="custom-1-101",
                    catalog_slug=None, web_protocol="http", web_path="/",
                    adopted=True)
            db.add(a)
            db.commit()
            app_id = a.id

        ctx = JobContext(app.state.jobs, _job(app, app_id))
        with pytest.raises(JobFailed) as e:
            await HANDLERS["app.update"](ctx, {"app_id": app_id})
        assert "catalog" in str(e.value).lower()

    asyncio.run(go())


def test_a_missing_credential_reports_as_a_failed_job_not_a_handler_bug(tmp_path):
    """ProxmoxError -> JobFailed, matching every Phase 6 handler."""
    async def go():
        fake = FakePVE()
        fake.add_ct(101, node="pve1", name="redis", status="running")
        app = make_job_app(tmp_path, fake=fake, ssh_factory=_ssh([]))
        app.state.jobs = JobBackend(app)
        _, app_id = _seed(app)
        with app.state.sessionmaker() as db:
            db.query(HostCredential).filter_by(kind="api_token:monitoring").delete()
            db.commit()

        ctx = JobContext(app.state.jobs, _job(app, app_id))
        with pytest.raises(JobFailed):
            await HANDLERS["app.update"](ctx, {"app_id": app_id})

    asyncio.run(go())


def test_update_refuses_an_app_whose_script_was_edited_locally(tmp_path):
    """api/apps.py::put_app_script writes source="edited" WITHOUT an
    upstream_ref (verified live, Task 4 review finding). Re-running the
    upstream script over an edited one would silently discard the operator's
    edits; this must fail before anything reaches SSH.

    Task 6 built api/apps.py::revert_app_script as the way out, so the
    message now points at it by name (`POST .../script/revert`) instead of
    the old "Proxploy has no way to revert" wording, which stopped being true
    the moment that route shipped."""
    async def go():
        fake = FakePVE()
        fake.add_ct(101, node="pve1", name="redis", status="running")
        cmds: list[str] = []
        app = make_job_app(tmp_path, fake=fake, ssh_factory=_ssh(cmds))
        app.state.jobs = JobBackend(app)
        _, app_id = _seed(app, script_source="edited")

        ctx = JobContext(app.state.jobs, _job(app, app_id))
        with pytest.raises(JobFailed) as e:
            await HANDLERS["app.update"](ctx, {"app_id": app_id})
        msg = str(e.value).lower()
        assert "edit" in msg
        assert "script/revert" in msg
        assert "no way to revert" not in msg           # the old, now-false claim
        assert cmds == []                             # never reached the SSH executor

    asyncio.run(go())


def test_update_runs_the_script_inside_the_container_not_on_the_host(tmp_path):
    """The bug a real node exposed on 2026-08-10: `app.update` installed a
    duplicate container instead of updating anything.

    build.func's start() chooses install-vs-update purely by where it runs:

        if command -v pveversion; then install_script     # on the PVE host
        elif [ "$PHS_SILENT" == 1 ]; then update_script   # inside the CT

    `pveversion` exists on the host, so running the catalog script over plain
    host SSH always took the install branch and built a SECOND container. No
    env var changes that. The command must therefore enter the container.
    """
    async def go():
        fake = FakePVE()
        fake.add_ct(101, node="pve1", name="redis", status="running")
        cmds: list[str] = []
        app = make_job_app(tmp_path, fake=fake, ssh_factory=_ssh(cmds))
        app.state.jobs = JobBackend(app)
        _host_id, app_id = _seed(app)

        ctx = JobContext(app.state.jobs, _job(app, app_id))
        await HANDLERS["app.update"](ctx, {"app_id": app_id})

        cmd = cmds[0]
        assert cmd.startswith("pct exec 101 -- "), f"ran on the host: {cmd}"
        # PHS_SILENT has to be inside the container, not a host-side prefix:
        # the executor's env= never crosses the pct exec boundary.
        inner = cmd.split("pct exec 101 -- ", 1)[1]
        assert "PHS_SILENT=1" in inner
        assert "TERM=xterm" in inner
        assert not cmd.startswith("TERM="), "env set outside the container"

    asyncio.run(go())
