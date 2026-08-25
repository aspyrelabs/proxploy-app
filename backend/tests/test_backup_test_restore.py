"""backup.test_restore: restore into a throwaway id, then destroy it.

The strongest proof available without PBS, and the one that must never leave
anything behind.
"""
import asyncio
import json

import pytest

from proxploy.jobs.backend import JobFailed
from proxploy.models import Backup, Host, HostCredential, Job

STORE_10TB = [{"storage": "local-lvm", "type": "lvmthin", "content": "images",
               "active": 1, "enabled": 1, "avail": 10 ** 12}]

# A bare FakePVE() reports an EMPTY /cluster/resources, which is what an
# under-permissioned token looks like, and _scratch_vmid now refuses to pick an
# id off one of those rather than assuming nothing is in use. A real cluster
# always has storage rows, so these stand in for "readable, and genuinely has
# no guests".
READABLE = [{"type": "node", "node": "pve1"},
            {"type": "storage", "storage": "local-lvm", "node": "pve1"}]


def _seed(app, size_bytes=1024):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.7:8006", node_name="pve1",
                    status="connected")
        db.add(host)
        db.commit()
        # A real-shaped token id: unlike the route tests, this handler actually
        # builds a ProxmoxClient, which validates it.
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!life", "token_secret": "s"}).encode())
        for kind in ("api_token:backup", "api_token:lifecycle"):
            db.add(HostCredential(host_id=host.id, kind=kind,
                                  encrypted_blob=blob, key_version=ver))
        b = Backup(host_id=host.id, storage="nfs-bk", guest_type="vm", guest_vmid=201,
                   guest_name="win11", size_bytes=size_bytes,
                   volid="nfs-bk:backup/vzdump-qemu-201-x.vma.zst")
        db.add(b)
        # The handler is called directly here, not through backend.enqueue, but
        # ctx.log still writes job_events rows with a real FK to jobs.id.
        db.add(Job(id=1, kind="backup.test_restore", status="running"))
        db.commit()
        return host.id, b.id


def _ctx(app):
    from proxploy.jobs import JobBackend, JobContext

    return JobContext(JobBackend(app), job_id=1)


def test_the_scratch_id_starts_at_900_and_skips_what_is_in_use():
    from proxploy.services.backupjobs import _scratch_vmid_from
    from proxploy.services.proxmox import ProxmoxClient
    from tests.fakes.pve import FakePVE, make_fake_factory

    fake = FakePVE(resources=[
        {"type": "qemu", "vmid": 900}, {"type": "lxc", "vmid": 901},
        {"type": "qemu", "vmid": 150},
    ])
    client = ProxmoxClient("https://10.0.0.7:8006", "proxploy@pve!life", "s",
                           factory=make_fake_factory(fake))
    assert _scratch_vmid_from(client, "host-01") == 902


def test_a_blind_resource_list_refuses_rather_than_handing_back_the_floor():
    """/cluster/resources is filtered by the token's own permissions, so a
    client that cannot read guests gets an empty list rather than an error.

    Measured on node1 2026-08-25: the lifecycle token returned 2 rows (both
    nodes, no guests, no storage) on a cluster running twelve guests, while
    the monitoring token returned 22. _scratch_vmid read that as "nothing is
    in use" and answered 900 every time, on any cluster, which is not the
    lowest free id and is only safe while 900 happens to be free.
    """
    from proxploy.services.backupjobs import _scratch_vmid_from
    from proxploy.services.proxmox import ProxmoxClient
    from tests.fakes.pve import FakePVE, make_fake_factory

    # What an under-permissioned token actually sends back: nodes, nothing else.
    blind = ProxmoxClient("https://10.0.0.7:8006", "proxploy@pve!life", "s",
                          factory=make_fake_factory(FakePVE(resources=[
                              {"type": "node", "node": "pve1"},
                              {"type": "node", "node": "pve2"}])))
    with pytest.raises(JobFailed) as e:
        _scratch_vmid_from(blind, "host-01")
    assert "cannot tell" in str(e.value).lower()


def test_a_genuinely_empty_cluster_is_not_mistaken_for_a_blind_one():
    """An empty node is a real state, and it must still get an id.

    The tell is not "no guests", it is "no guests AND no storage": a token
    that can read the cluster at all sees the storage rows, so a list with
    storage in it and no guests is an honest answer about an empty node.
    """
    from proxploy.services.backupjobs import _scratch_vmid_from
    from proxploy.services.proxmox import ProxmoxClient
    from tests.fakes.pve import FakePVE, make_fake_factory

    empty = ProxmoxClient("https://10.0.0.7:8006", "proxploy@pve!life", "s",
                          factory=make_fake_factory(FakePVE(resources=[
                              {"type": "node", "node": "pve1"},
                              {"type": "storage", "storage": "local"}])))
    assert _scratch_vmid_from(empty, "host-01") == 900


def test_a_passing_test_restore_destroys_the_copy_and_marks_the_archive(tmp_path):
    from proxploy.services.backupjobs import test_restore_backup
    from tests.fakes.pve import FakePVE
    from tests.support import make_job_app

    async def run():
        fake = FakePVE(resources=list(READABLE))
        fake.storages_by_node = {"pve1": STORE_10TB}
        app = make_job_app(tmp_path, fake=fake)
        _, bid = _seed(app)
        out = await test_restore_backup(_ctx(app),
                                        {"backup_id": bid, "storage": "local-lvm"})
        assert out["verdict"] == "ok"
        assert fake.guest_deletes == [("qemu", "pve1", out["scratch_vmid"])]
        with app.state.sessionmaker() as db:
            row = db.get(Backup, bid)
            assert row.verify_state == "ok" and row.checked_at is not None

    asyncio.run(run())


def test_a_failed_restore_still_destroys_the_scratch_guest(tmp_path):
    """The half-built guest is exactly the leftover this must never produce."""
    from proxploy.jobs import JobFailed
    from proxploy.services.backupjobs import test_restore_backup
    from tests.fakes.pve import FakePVE
    from tests.support import make_job_app

    async def run():
        fake = FakePVE(resources=list(READABLE),
                       task_exit="restore failed: archive is corrupt")
        fake.storages_by_node = {"pve1": STORE_10TB}
        app = make_job_app(tmp_path, fake=fake)
        _, bid = _seed(app)
        try:
            await test_restore_backup(_ctx(app),
                                      {"backup_id": bid, "storage": "local-lvm"})
            raise AssertionError("expected JobFailed")
        except JobFailed:
            pass
        assert len(fake.guest_deletes) == 1, "the scratch guest was left behind"
        with app.state.sessionmaker() as db:
            assert db.get(Backup, bid).verify_state == "failed"

    asyncio.run(run())


def test_a_destroy_that_fails_fails_the_job_and_names_the_guest(tmp_path):
    """A throwaway guest nobody knows about, still holding a disk, is worse
    than a red job. The restore itself passed, so the verdict still stands."""
    from proxploy.jobs import JobFailed
    from proxploy.services.backupjobs import test_restore_backup
    from tests.fakes.pve import FakePVE
    from tests.support import make_job_app

    async def run():
        fake = FakePVE(resources=list(READABLE))
        fake.storages_by_node = {"pve1": STORE_10TB}
        fake.delete_error = "VM is locked (create)"
        app = make_job_app(tmp_path, fake=fake)
        _, bid = _seed(app)
        try:
            await test_restore_backup(_ctx(app),
                                      {"backup_id": bid, "storage": "local-lvm"})
            raise AssertionError("expected JobFailed")
        except JobFailed as e:
            assert "900" in str(e) and "pve1" in str(e)
        with app.state.sessionmaker() as db:
            assert db.get(Backup, bid).verify_state == "ok"

    asyncio.run(run())


def test_it_refuses_before_touching_pve_when_the_store_is_too_small(tmp_path):
    from proxploy.jobs import JobFailed
    from proxploy.services.backupjobs import test_restore_backup
    from tests.fakes.pve import FakePVE
    from tests.support import make_job_app

    async def run():
        fake = FakePVE(resources=list(READABLE))
        fake.storages_by_node = {"pve1": [{"storage": "local-lvm", "type": "lvmthin",
                                           "content": "images", "active": 1,
                                           "enabled": 1, "avail": 10}]}
        app = make_job_app(tmp_path, fake=fake)
        _, bid = _seed(app, size_bytes=10 ** 9)
        try:
            await test_restore_backup(_ctx(app),
                                      {"backup_id": bid, "storage": "local-lvm"})
            raise AssertionError("expected JobFailed")
        except JobFailed as e:
            assert "free" in str(e)
        assert fake.creates == [], "it created a guest before checking for room"
        assert fake.guest_deletes == []

    asyncio.run(run())
