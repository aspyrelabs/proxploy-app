"""ProxmoxClient.agent_fsinfo: the only honest read of a VM's used storage.

/cluster/resources' `disk` field is a flat 0 for a QEMU guest, because the
hypervisor sees a block device and cannot see the filesystem written into it
(measured on the lab cluster, PVE 9.2.10, 2026-08-20: VM 108 running, maxdisk
34359738368, `disk: 0`). Only the guest agent can answer, so these tests are
about parsing its answer without double-counting and about turning every way
of not getting one into None rather than into zero bytes used.

The call answers two things from the one request, `(agent_ok, used_bytes)`,
because whether the guest agent answered is exactly what "we could not read
the filesystems" already knew and used to throw away.
"""
import pytest

# A qemu-ga guest-get-fsinfo answer as PVE wraps it, trimmed to the keys the
# code reads. The last two entries are the two traps: /mnt/data is a bind mount
# of the same sda2 already counted, and the snap mount is a read-only squashfs
# loop whose used == total.
FSINFO = {"result": [
    {"name": "sda1", "mountpoint": "/boot/efi", "type": "vfat",
     "used-bytes": 6_000_000, "total-bytes": 536_870_912},
    {"name": "sda2", "mountpoint": "/", "type": "ext4",
     "used-bytes": 8_000_000_000, "total-bytes": 32_000_000_000},
    {"name": "sda2", "mountpoint": "/mnt/data", "type": "ext4",
     "used-bytes": 8_000_000_000, "total-bytes": 32_000_000_000},
    {"name": "loop0", "mountpoint": "/snap/core22/1122", "type": "squashfs",
     "used-bytes": 78_000_000, "total-bytes": 78_000_000},
]}


class _Agent:
    def __init__(self, answer):
        self._answer = answer

    def get(self):
        if isinstance(self._answer, Exception):
            raise self._answer
        return self._answer


class _Qemu:
    def __init__(self, answer):
        self._answer = answer

    def agent(self, command):
        assert command == "get-fsinfo"
        return _Agent(self._answer)


class _Nodes:
    def __init__(self, answer):
        self._answer = answer

    def __call__(self, node):
        return self

    def qemu(self, vmid):
        return _Qemu(self._answer)


class _Api:
    def __init__(self, answer):
        self.nodes = _Nodes(answer)


def _client(answer):
    from proxploy.services.proxmox import ProxmoxClient

    c = ProxmoxClient("https://10.0.0.7:8006", "proxploy@pve!mon", "s3cret")
    c._api = _Api(answer)   # pre-connected, so no socket is ever opened
    return c


def test_filesystems_are_summed_once_each():
    """A bind mount reports the SAME filesystem twice and adding both counts
    the same bytes twice, so the sum is deduped on the guest's device name."""
    assert _client(FSINFO).agent_fsinfo("pve1", 100) == (True, 8_006_000_000)


def test_pseudo_filesystems_do_not_inflate_the_figure():
    """Every snap package is its own read-only squashfs loop mount reporting
    used == total. Counting them adds a gigabyte or two of nothing to a number
    an operator reads as "how full is this VM"."""
    only_snaps = {"result": [FSINFO["result"][3]]}
    assert _client(only_snaps).agent_fsinfo("pve1", 100) == (True, None)


def test_no_agent_installed_is_a_false_verdict_and_never_raises():
    """The common case, and not a fault: the lab VM answers
    `500 No QEMU guest agent configured`. It must not raise, because it runs
    inside the poll cycle and losing the cycle over it would be absurd. False,
    not None: Proxmox told us something true about this guest, and an operator
    can act on it by installing the agent."""
    boom = RuntimeError("500 Internal Server Error: No QEMU guest agent configured")
    assert _client(boom).agent_fsinfo("pve1", 100) == (False, None)


def test_an_agent_that_is_not_running_is_also_a_false_verdict():
    """PVE's other wording, for a guest whose config declares an agent that is
    not answering inside it. Same actionable meaning to an operator: no working
    guest agent in this VM."""
    boom = RuntimeError("500 Internal Server Error: QEMU guest agent is not running")
    assert _client(boom).agent_fsinfo("pve1", 100) == (False, None)


@pytest.mark.parametrize("boom", [
    ConnectionError("connection refused"),
    RuntimeError("401 Unauthorized: permission check failed"),
    TimeoutError("timed out"),
])
def test_a_failure_that_is_not_about_the_agent_is_unknown_not_false(boom):
    """The distinction the whole tri-state exists for. A refused connection or
    a token missing a permission says NOTHING about what is installed inside
    the guest, and recording "no agent" off the back of one would send an
    operator to install something that is already there."""
    assert _client(boom).agent_fsinfo("pve1", 100) == (None, None)


@pytest.mark.parametrize("answer", [
    None,
    {"result": []},
    {"result": [{"name": "sda1", "type": "ext4"}]},     # no used-bytes reported
    {"result": ["not a dict"]},
])
def test_nothing_usable_is_none_not_zero(answer):
    """0 would draw an empty disk bar under a full disk. A VM whose every
    filesystem was skipped has not been measured. The agent still ANSWERED,
    which is the pair the old single return could not express."""
    assert _client(answer).agent_fsinfo("pve1", 100) == (True, None)
