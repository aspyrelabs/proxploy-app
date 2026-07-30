import asyncio
import hashlib

import pytest

from proxploy.jobs import JobContext, JobFailed
from proxploy.models import App, AppScript, CatalogEntry, Job
from proxploy.services.appstore import run_install
from tests.fakes.ssh import FakeSSHConnection, make_fake_connect_factory
from tests.support import make_job_app, seed_host_row


def _seed_job(db, job_id=1):
    # run_install is called directly here (not via backend.enqueue), but
    # ctx.log/ctx.progress still write job_events rows with a real FK to
    # jobs.id, so a Job row must exist first.
    db.add(Job(id=job_id, kind="app.install", status="running"))
    db.commit()


def _seed_catalog(db, installable=True):
    db.add(CatalogEntry(slug="redis", name="Redis", category="Databases",
                        installable=installable,
                        unsupported_reason=None if installable else "install script requires interactive input, no non-interactive entrypoint",
                        default_cpu=1, default_ram_mb=1024, default_disk_gb=4,
                        default_os="debian", default_os_version="13",
                        raw={"ct_script": "...", "install_script": "msg_ok done"}))
    db.commit()


def test_install_pins_script_and_creates_app_row(tmp_path):
    async def scenario():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            host = seed_host_row(db)
            from proxploy.models import HostCredential
            sblob, sver = app.state.secretstore.encrypt(b"-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----")
            db.add(HostCredential(host_id=host.id, kind="ssh_key", encrypted_blob=sblob,
                                  key_version=sver, public_meta="ssh-ed25519 AAAA fake"))
            _seed_catalog(db)
            _seed_job(db)
            db.commit()
            host_id = host.id

        fake = FakeSSHConnection(host_key_fingerprint="SHA256:abc", stdout_lines=["Setup Redis"],
                                 stderr_lines=[], exit_status=0)
        app.state.ssh_connect_factory = make_fake_connect_factory(fake)

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
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            host = seed_host_row(db)
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
