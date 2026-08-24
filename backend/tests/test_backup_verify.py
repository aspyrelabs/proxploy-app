"""backup.verify: read an archive back and say whether it is intact.

Neither `pvesm path` nor `vma verify` is on the PVE HTTP API, so this is the
one backup path that runs over SSH.
"""
import asyncio
import json

from proxploy.models import Backup, Host, HostCredential, Job

VOLID_VM = "nfs-bk:backup/vzdump-qemu-201-2026_07_30-03_00_00.vma.zst"
VOLID_CT = "nfs-bk:backup/vzdump-lxc-150-2026_07_30-02_00_00.tar.zst"


def _seed(app, volid=VOLID_VM, guest_type="vm"):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.7:8006", node_name="pve1",
                    status="connected", ssh_host_key_fingerprint="SHA256:abc")
        db.add(host)
        db.commit()
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!bk", "token_secret": "s"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token:backup",
                              encrypted_blob=blob, key_version=ver))
        db.add(HostCredential(host_id=host.id, kind="ssh_key",
                              encrypted_blob=blob, key_version=ver))
        b = Backup(host_id=host.id, volid=volid, storage="nfs-bk",
                   guest_type=guest_type, guest_vmid=201, size_bytes=1024)
        db.add(b)
        # verify_backup is called directly here, not through backend.enqueue,
        # but ctx.log still writes job_events rows with a real FK to jobs.id.
        db.add(Job(id=1, kind="backup.verify", status="running"))
        db.commit()
        return host.id, b.id


def _ctx(app, job_id=1):
    from proxploy.jobs import JobBackend, JobContext

    return JobContext(JobBackend(app), job_id=job_id)


def test_the_vm_command_resolves_the_path_and_pipes_into_vma_verify():
    from proxploy.services.backupjobs import _verify_command

    cmd = _verify_command(VOLID_VM, "vm")
    assert "pvesm path" in cmd and VOLID_VM in cmd
    assert "vma verify -v -" in cmd
    # Without pipefail a truncated archive exits 0 through the decompressor.
    assert "set -o pipefail" in cmd


def test_the_container_command_reads_the_whole_tar_instead():
    from proxploy.services.backupjobs import _verify_command

    cmd = _verify_command(VOLID_CT, "ct")
    assert "tar -tf -" in cmd
    assert "vma verify" not in cmd


def test_a_clean_verify_marks_the_archive_ok(tmp_path):
    from proxploy.services.backupjobs import verify_backup
    from tests.fakes.ssh import FakeSSHConnection, make_fake_connect_factory
    from tests.support import make_job_app

    async def run():
        ssh = FakeSSHConnection(host_key_fingerprint="SHA256:abc",
                                stdout_lines=["CFG: size: 462 name: qemu-server.conf",
                                              "verify done"],
                                stderr_lines=[], exit_status=0)
        app = make_job_app(tmp_path, ssh_factory=make_fake_connect_factory(ssh))
        _, bid = _seed(app)
        out = await verify_backup(_ctx(app), {"backup_id": bid})
        assert out["verdict"] == "ok"
        with app.state.sessionmaker() as db:
            row = db.get(Backup, bid)
            assert row.verify_state == "ok" and row.checked_at is not None

    asyncio.run(run())


def test_a_corrupt_archive_is_a_finished_job_with_a_failed_archive(tmp_path):
    """The check RAN. Failing the job here would report a broken checker."""
    from proxploy.services.backupjobs import verify_backup
    from tests.fakes.ssh import FakeSSHConnection, make_fake_connect_factory
    from tests.support import make_job_app

    async def run():
        ssh = FakeSSHConnection(host_key_fingerprint="SHA256:abc", stdout_lines=[],
                                stderr_lines=["vma: verify failed - wrong magic"],
                                exit_status=1)
        app = make_job_app(tmp_path, ssh_factory=make_fake_connect_factory(ssh))
        _, bid = _seed(app)
        out = await verify_backup(_ctx(app), {"backup_id": bid})
        assert out["verdict"] == "failed"
        with app.state.sessionmaker() as db:
            assert db.get(Backup, bid).verify_state == "failed"

    asyncio.run(run())


def test_an_unresolvable_path_fails_the_job_and_marks_nothing(tmp_path):
    """Exit 90 is the command's own "pvesm path said nothing" signal: the check
    could not run, which is not the same as an archive that failed it."""
    from proxploy.jobs import JobFailed
    from proxploy.services.backupjobs import verify_backup
    from tests.fakes.ssh import FakeSSHConnection, make_fake_connect_factory
    from tests.support import make_job_app

    async def run():
        ssh = FakeSSHConnection(host_key_fingerprint="SHA256:abc", stdout_lines=[],
                                stderr_lines=["pvesm path returned nothing"],
                                exit_status=90)
        app = make_job_app(tmp_path, ssh_factory=make_fake_connect_factory(ssh))
        _, bid = _seed(app)
        try:
            await verify_backup(_ctx(app), {"backup_id": bid})
            raise AssertionError("expected JobFailed")
        except JobFailed as e:
            assert "could not be read" in str(e)
        with app.state.sessionmaker() as db:
            assert db.get(Backup, bid).verify_state is None

    asyncio.run(run())


def _fake_listing_the_seeded_archive():
    """A run ends in a resync, which DELETES any archive PVE no longer lists.
    So the fake has to report the seeded one back, or the row the chained check
    is supposed to name is gone before it is queued."""
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    fake.storages_by_node = {"pve1": [{"storage": "nfs-bk", "type": "nfs",
                                       "content": "backup"}]}
    fake.content_by_storage = {"nfs-bk": [
        {"volid": VOLID_VM, "ctime": 1753844400, "size": 1024,
         "format": "vma.zst", "content": "backup"}]}
    return fake


def test_a_run_with_verify_set_enqueues_a_check_for_what_it_wrote(tmp_path):
    """A separate job, not an inline check: a backup that succeeded must read
    as succeeded even when the check that follows it finds a bad archive, and
    the two take very different amounts of time."""
    from proxploy.services.backupjobs import run_backup
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path, fake=_fake_listing_the_seeded_archive())
        hid, bid = _seed(app)
        with app.state.sessionmaker() as db:
            db.add(Job(id=2, kind="backup.run", status="running"))
            db.commit()
        await run_backup(_ctx(app, 2),
                         {"host_id": hid, "vmids": [201], "verify": True})
        with app.state.sessionmaker() as db:
            # status, because _seed's own stand-in job is a backup.verify too.
            queued = db.query(Job).filter_by(kind="backup.verify",
                                             status="queued").all()
            assert len(queued) == 1
            assert queued[0].params["backup_id"] == bid

    asyncio.run(run())


def test_a_run_without_the_flag_queues_nothing(tmp_path):
    from proxploy.services.backupjobs import run_backup
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path, fake=_fake_listing_the_seeded_archive())
        hid, _ = _seed(app)
        with app.state.sessionmaker() as db:
            db.add(Job(id=2, kind="backup.run", status="running"))
            db.commit()
        await run_backup(_ctx(app, 2), {"host_id": hid, "vmids": [201]})
        with app.state.sessionmaker() as db:
            assert db.query(Job).filter_by(kind="backup.verify",
                                           status="queued").count() == 0

    asyncio.run(run())
