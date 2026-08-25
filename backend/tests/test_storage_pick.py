"""Which pool a restore lands on when the caller did not name one.

`storage_for_content` used to answer "the first one PVE happened to list",
which is how a test restore on a real host wrote a 32 GiB scratch disk across
NFS while a local LVM pool with nearly three times the room sat next to it.
Worse, test_restore_backup picks first and checks free space second, so an
archive that fits perfectly well somewhere on the host was refused with
"choose another storage or make room".
"""
from proxploy.services.backupjobs import storage_for_content
from proxploy.services.proxmox import ProxmoxClient
from tests.fakes.pve import FakePVE, make_fake_factory

GiB = 1024 ** 3


def _client(rows):
    fake = FakePVE()
    fake.storages_by_node = {"pve1": rows}
    return ProxmoxClient("https://10.0.0.7:8006", "proxploy@pve!x", "s",
                         factory=make_fake_factory(fake))


def test_the_roomiest_eligible_pool_wins_not_the_first_listed():
    c = _client([
        {"storage": "nfs-first", "content": "images,backup", "active": 1,
         "avail": 606 * GiB},
        {"storage": "local-lvm", "content": "rootdir,images", "active": 1,
         "avail": 1685 * GiB},
    ])
    assert storage_for_content(c, "pve1", "images") == "local-lvm"


def test_a_pool_that_cannot_hold_the_content_is_never_picked():
    """The roomiest storage on a host is often the one for ISOs and templates."""
    c = _client([
        {"storage": "huge-iso", "content": "iso,vztmpl", "active": 1,
         "avail": 9000 * GiB},
        {"storage": "local-lvm", "content": "images", "active": 1, "avail": 10 * GiB},
    ])
    assert storage_for_content(c, "pve1", "images") == "local-lvm"


def test_an_inactive_pool_is_never_picked_however_roomy():
    c = _client([
        {"storage": "offline", "content": "images", "active": 0, "avail": 9000 * GiB},
        {"storage": "local-lvm", "content": "images", "active": 1, "avail": 10 * GiB},
    ])
    assert storage_for_content(c, "pve1", "images") == "local-lvm"


def test_a_pool_that_does_not_report_free_space_loses_to_one_that_does():
    """Unknown is not "infinite". It still beats nothing at all, below."""
    c = _client([
        {"storage": "quiet", "content": "images", "active": 1},
        {"storage": "known", "content": "images", "active": 1, "avail": 1 * GiB},
    ])
    assert storage_for_content(c, "pve1", "images") == "known"


def test_a_pool_that_does_not_report_free_space_is_still_better_than_none():
    c = _client([{"storage": "quiet", "content": "images", "active": 1}])
    assert storage_for_content(c, "pve1", "images") == "quiet"


def test_content_may_arrive_as_a_list_rather_than_a_comma_string():
    """rootfs_candidates in services/migrate.py already defends against this,
    reading the same field from the same call; this one did not."""
    c = _client([{"storage": "local-lvm", "content": ["rootdir", "images"],
                  "active": 1, "avail": 5 * GiB}])
    assert storage_for_content(c, "pve1", "images") == "local-lvm"


def test_no_eligible_pool_is_still_none():
    c = _client([{"storage": "iso-only", "content": "iso", "active": 1,
                  "avail": 9000 * GiB}])
    assert storage_for_content(c, "pve1", "images") is None
