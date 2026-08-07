"""Per-guest lifecycle + task reads (doc 05 lifecycle rows, doc 02 §4).

These are user-triggered calls and deliberately live OUTSIDE the poller's
O(nodes) budget (doc 02 §3), nothing here may be called from pollers/.
"""
import pytest

from proxploy.services.proxmox import ProxmoxClient, ProxmoxError
from tests.fakes.pve import FakePVE, make_fake_factory


def _client(fake):
    return ProxmoxClient("https://10.0.0.7:8006", "proxploy@pve!life", "s3cret",
                         factory=make_fake_factory(fake))


def test_guest_action_returns_upid_and_records_the_call():
    fake = FakePVE()
    upid = _client(fake).guest_action("lxc", "pve1", 150, "start")
    assert upid.startswith("UPID:pve1:")
    assert fake.actions == [("lxc", 150, "start")]


def test_guest_action_rejects_actions_the_guest_type_does_not_have():
    fake = FakePVE()
    with pytest.raises(ProxmoxError, match="not a lxc lifecycle action"):
        _client(fake).guest_action("lxc", "pve1", 150, "reset")


def test_task_status_reports_running_then_stopped():
    fake = FakePVE(running_ticks=2)
    c = _client(fake)
    upid = c.guest_action("qemu", "pve1", 201, "stop")
    assert c.task_status("pve1", upid)["status"] == "running"
    assert c.task_status("pve1", upid)["status"] == "running"
    done = c.task_status("pve1", upid)
    assert done["status"] == "stopped" and done["exitstatus"] == "OK"


def test_task_log_returns_numbered_lines_from_a_start_cursor():
    fake = FakePVE()
    c = _client(fake)
    upid = c.guest_action("lxc", "pve1", 150, "start")
    fake.task_lines[upid] = ["starting CT 150", "CT 150 started"]
    assert [r["t"] for r in c.task_log("pve1", upid)] == ["starting CT 150", "CT 150 started"]
    assert [r["n"] for r in c.task_log("pve1", upid, start=1)] == [2]


def test_transport_failures_surface_as_ProxmoxError():
    fake = FakePVE(fail=True)
    with pytest.raises(ProxmoxError):
        _client(fake).guest_action("lxc", "pve1", 150, "start")
