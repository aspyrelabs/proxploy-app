"""Backups on a sibling node of a cluster are listed, not silently missing.

sync_host_backups read `host.node_name` and nothing else, so on a cluster whose
nodes each keep a LOCAL dump dir, only the enrolled node's archives were ever
mirrored. Shared datastores (PBS, NFS, CephFS) report identically from any node
and were always complete, which is why this hid: it is invisible to anyone with
a shared store and total to a non-PBS multi-node user.

Two things had to move with it. The same volid on two nodes is two DIFFERENT
files for a node-local store, so ux_backups(host_id, volid) could not hold
both; and verify/restore/test-restore all ran on `host.node_name`, so they
would have acted on the wrong node for a sibling's archive.
"""
import json

from proxploy.models import Backup, Host, HostCredential
from proxploy.pollers import HostSnapshot
from tests.fakes.pve import FakePVE
from tests.support import make_app


LOCAL = {"storage": "local", "type": "dir", "content": "backup",
         "shared": 0, "active": 1}


def _boot(tmp_path, fake, cluster="lab-cluster"):
    from fastapi.testclient import TestClient

    app = make_app(tmp_path, fake=fake)
    c = TestClient(app)
    c.__enter__()
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.7:8006",
                    node_name="pve1", cluster_name=cluster, status="connected")
        db.add(host)
        db.commit()
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!bk", "token_secret": "s"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token:backup",
                              encrypted_blob=blob, key_version=ver))
        db.commit()
        hid = host.id
    # The poller's node list is the source for which nodes to read.
    app.state.poller.snapshots[hid] = HostSnapshot(
        host_id=hid, ts=None, nodes=[{"node": "pve1"}, {"node": "pve2"}])
    return app, c, hid


def _fake_local_on_both_nodes():
    """One local dump dir per node, each holding its OWN vzdump of CT 110.

    The volids are IDENTICAL strings. That is the whole trap: `local` is
    node-scoped, so `local:backup/vzdump-lxc-110-a.tar.zst` on pve1 and the
    same string on pve2 are two different files on two different disks.
    """
    fake = FakePVE()
    fake.storages_by_node = {"pve1": [LOCAL], "pve2": [LOCAL]}
    fake.content_by_storage = {}
    fake.content_by_node_storage = {
        ("pve1", "local"): [{"volid": "local:backup/vzdump-lxc-110-a.tar.zst",
                             "ctime": 1753840800, "size": 111, "format": "tar.zst",
                             "content": "backup"}],
        ("pve2", "local"): [{"volid": "local:backup/vzdump-lxc-110-a.tar.zst",
                             "ctime": 1753840900, "size": 222, "format": "tar.zst",
                             "content": "backup"}],
    }
    return fake


def test_a_local_archive_on_a_sibling_node_is_listed(tmp_path):
    from proxploy.services.backupjobs import sync_host_backups

    app, c, hid = _boot(tmp_path, _fake_local_on_both_nodes())
    sync_host_backups(app, hid)

    with app.state.sessionmaker() as db:
        rows = db.query(Backup).order_by(Backup.node).all()
        # Two files, two rows, told apart by the node they live on.
        assert [r.node for r in rows] == ["pve1", "pve2"]
        assert {r.size_bytes for r in rows} == {111, 222}
    c.__exit__(None, None, None)


def test_a_shared_datastore_is_still_recorded_once(tmp_path):
    """A shared store reports the SAME archive from every node, so reading two
    nodes must not turn one backup into two rows."""
    from proxploy.services.backupjobs import sync_host_backups

    shared = {"storage": "nfs-bk", "type": "nfs", "content": "backup",
              "shared": 1, "active": 1}
    fake = FakePVE()
    fake.storages_by_node = {"pve1": [shared], "pve2": [shared]}
    fake.content_by_storage = {}
    one = [{"volid": "nfs-bk:backup/vzdump-qemu-201-x.vma.zst", "ctime": 1753840800,
            "size": 999, "format": "vma.zst", "content": "backup"}]
    fake.content_by_node_storage = {("pve1", "nfs-bk"): one, ("pve2", "nfs-bk"): one}

    app, c, hid = _boot(tmp_path, fake)
    sync_host_backups(app, hid)

    with app.state.sessionmaker() as db:
        assert db.query(Backup).count() == 1
    c.__exit__(None, None, None)


def test_verify_and_restore_run_on_the_archives_own_node(tmp_path):
    """_backup_target used to answer host.node_name for every row, so a
    sibling's archive would have been read on the wrong node."""
    from proxploy.services.backupjobs import _backup_target, sync_host_backups

    app, c, hid = _boot(tmp_path, _fake_local_on_both_nodes())
    sync_host_backups(app, hid)

    with app.state.sessionmaker() as db:
        sibling = db.query(Backup).filter_by(node="pve2").one()
        bid = sibling.id
    _, node, info = _backup_target(app, bid)
    assert node == "pve2"
    assert info["node"] == "pve2"
    c.__exit__(None, None, None)


def test_an_archive_that_disappears_from_one_node_only_drops_that_row(tmp_path):
    """The resync deletes what PVE no longer lists. Scoped per node, or one
    node's sweep would drop the sibling's rows with it."""
    from proxploy.services.backupjobs import sync_host_backups

    fake = _fake_local_on_both_nodes()
    app, c, hid = _boot(tmp_path, fake)
    sync_host_backups(app, hid)
    fake.content_by_node_storage[("pve1", "local")] = []
    sync_host_backups(app, hid)

    with app.state.sessionmaker() as db:
        rows = db.query(Backup).all()
        assert [r.node for r in rows] == ["pve2"]
    c.__exit__(None, None, None)


def test_a_host_with_no_snapshot_yet_still_syncs_its_own_node(tmp_path):
    """Before the first poll there is no node list, and a backup page that
    showed nothing until a poll landed would be a worse bug than the one this
    fixes."""
    from proxploy.services.backupjobs import sync_host_backups

    app, c, hid = _boot(tmp_path, _fake_local_on_both_nodes())
    app.state.poller.snapshots.pop(hid)
    sync_host_backups(app, hid)

    with app.state.sessionmaker() as db:
        rows = db.query(Backup).all()
        assert [r.node for r in rows] == ["pve1"]
    c.__exit__(None, None, None)


def test_a_row_from_before_the_node_column_is_adopted_not_duplicated(tmp_path):
    """The first sync after upgrade must not rebuild every archive.

    Rows written before `node` existed carry NULL. Matching on (node, volid)
    alone misses them, builds a second row for the same archive and drops the
    first, so every verdict this install had recorded would go with it: the
    Backups page would come back from the upgrade with nothing verified.
    """
    from proxploy.models import utcnow
    from proxploy.services.backupjobs import sync_host_backups

    fake = _fake_local_on_both_nodes()
    # One node only, so the pre-upgrade row is unambiguous.
    fake.storages_by_node = {"pve1": [LOCAL]}
    app, c, hid = _boot(tmp_path, fake)
    app.state.poller.snapshots[hid].nodes = [{"node": "pve1"}]
    checked = utcnow()
    with app.state.sessionmaker() as db:
        db.add(Backup(host_id=hid, volid="local:backup/vzdump-lxc-110-a.tar.zst",
                      storage="local", node=None, guest_type="ct",
                      verify_state="ok", checked_at=checked))
        db.commit()
        before = db.query(Backup).one().id

    sync_host_backups(app, hid)

    with app.state.sessionmaker() as db:
        row = db.query(Backup).one()          # one, not two
        assert row.id == before               # the same row, not a rebuild
        assert row.node == "pve1"             # now placed
        assert row.verify_state == "ok"       # and its verdict survived
        assert row.checked_at is not None
    c.__exit__(None, None, None)
