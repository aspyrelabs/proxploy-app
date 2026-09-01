"""VM usage: used memory and network come free with the bulk read, disk does not.

A VM row used to store only the guest's ALLOCATION, so the VMs page could draw
a CPU meter and nothing else. Memory and network usage were already in the
/cluster/resources row the poller parses and were simply thrown away. Storage
was not there at all: that row's `disk` field is a flat 0 for a QEMU guest
because the hypervisor sees a block device and cannot see the filesystem on it
(measured on the lab cluster, PVE 9.2.10, 2026-08-20: VM 108 running, maxdisk
34359738368, `disk: 0`). Only the guest agent can answer, that is a per-VM
call, and most of these tests are about how rarely it is allowed to make one
and about never turning "cannot tell" into "zero bytes used".
"""
import json
from datetime import timedelta
from pathlib import Path

FIX = Path(__file__).parent / "fixtures" / "pve"


class FakeClient:
    """Counts calls, because "does not ask every cycle" is the whole point.

    `answer` is the (agent_ok, used_bytes) pair agent_fsinfo returns.
    (False, None) is what the real wrapper returns for a guest with no agent,
    which is the common case: the lab VM answers
    `500 No QEMU guest agent configured`. (None, None) is a probe that never
    got an answer at all, which is a different thing and has to stay different.
    """

    def __init__(self, answer=(True, 12_884_901_888), config=None):
        self.answer = answer
        self.calls = []
        # What guest_config returns, or an exception to raise. The lab VM
        # answers ostype 'l26' (PVE 9.2.10, 2026-08-20).
        self.config = {"ostype": "l26"} if config is None else config
        self.config_calls = []

    def agent_fsinfo(self, node, vmid):
        self.calls.append((node, vmid))
        return self.answer

    def guest_config(self, kind, node, vmid):
        self.config_calls.append((kind, node, vmid))
        if isinstance(self.config, Exception):
            raise self.config
        return self.config

    def lxc_interfaces(self, node, vmid):
        return None


def _resources(status="running", netin=0, netout=0):
    rows = json.loads((FIX / "cluster_resources_basic.json").read_text())
    out = []
    for r in rows:
        if r.get("type") == "qemu":
            # PVE zeroes the live readings for a guest that is not running,
            # which is exactly the 0-is-not-a-measurement case, so the fixture
            # has to zero them too or the stopped-VM tests test nothing.
            live = ({} if status == "running"
                    else {"cpu": 0, "mem": 0, "uptime": 0})
            r = {**r, "status": status, "netin": netin, "netout": netout, **live}
        out.append(r)
    return out


def _seed(tmp_path):
    from proxploy.models import utcnow
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    return db, seed_host_row(db), utcnow()


def _cycle(db, host, now, client=None, checked=None, status="running",
           netin=0, netout=0):
    from proxploy.pollers import ingest_cycle

    return ingest_cycle(db, host, _resources(status, netin, netout), {}, now,
                        client=client,
                        fs_checked=checked if checked is not None else {})


def _vm(db, host):
    from proxploy.models import Vm

    return db.query(Vm).filter_by(host_id=host.id, vmid=100).one()


def test_used_memory_is_persisted_beside_the_allocation(tmp_path):
    """`mem` is USED and `maxmem` is ALLOCATED, and both are on the row the
    poller already parses. Only the second one used to be kept, under the name
    an App row gives the first."""
    db, host, now = _seed(tmp_path)

    _cycle(db, host, now)

    v = _vm(db, host)
    assert v.mem_bytes == 6442450944
    assert v.mem_total_bytes == 8589934592
    assert v.disk_total_bytes == 68719476736


def test_a_stopped_vm_reports_no_usage_rather_than_zero_usage(tmp_path):
    """0 from PVE means "no reading", not "zero bytes used". A meter drawn at
    zero claims a measurement nobody took."""
    db, host, now = _seed(tmp_path)

    _cycle(db, host, now, status="stopped")

    v = _vm(db, host)
    assert v.mem_bytes is None
    # The allocation is a fact about the guest and survives it being stopped.
    assert v.mem_total_bytes == 8589934592
    assert v.disk_total_bytes == 68719476736


def test_a_stopped_vm_reports_no_cpu_reading(tmp_path):
    db, host, now = _seed(tmp_path)

    res = _cycle(db, host, now, status="stopped")

    assert res.snapshot.guests[("qemu", 100)]["cpu_pct"] is None


def test_a_stopped_vms_unmoving_network_counters_still_give_no_rate(tmp_path):
    db, host, now = _seed(tmp_path)

    _cycle(db, host, now, netin=1_000_000, netout=200_000)
    _cycle(db, host, now + timedelta(seconds=30), status="stopped",
           netin=1_000_000, netout=200_000)

    v = _vm(db, host)
    assert v.net_in_bps_cached is None
    assert v.net_out_bps_cached is None


def test_a_stopped_vm_appends_no_metric_samples(tmp_path):
    from proxploy.models import MetricSample

    db, host, now = _seed(tmp_path)
    _cycle(db, host, now)
    v = _vm(db, host)
    running_count = db.query(MetricSample).filter_by(
        target_type="vm", target_id=v.id).count()
    assert running_count == 3

    _cycle(db, host, now + timedelta(seconds=30), status="stopped")
    assert db.query(MetricSample).filter_by(
        target_type="vm", target_id=v.id).count() == running_count


def test_a_running_vm_records_cpu_mem_and_network_normally(tmp_path):
    db, host, now = _seed(tmp_path)

    res = _cycle(db, host, now, netin=1_000_000, netout=200_000)

    assert res.snapshot.guests[("qemu", 100)]["cpu_pct"] == 31.0
    v = _vm(db, host)
    assert v.mem_bytes == 6442450944
    assert v.cpu_cores == 4


def test_first_cycle_stores_the_counters_but_cannot_make_a_rate(tmp_path):
    """netin/netout are counters, not rates. One reading is one point, and a
    point has no slope. Shared with the app path: same _update_net_rates."""
    db, host, now = _seed(tmp_path)

    _cycle(db, host, now, netin=1_000_000, netout=200_000)

    v = _vm(db, host)
    assert v.net_in_cached == 1_000_000 and v.net_out_cached == 200_000
    assert v.net_in_bps_cached is None and v.net_out_bps_cached is None


def test_two_cycles_make_a_rate(tmp_path):
    db, host, now = _seed(tmp_path)

    _cycle(db, host, now, netin=1_000_000, netout=200_000)
    _cycle(db, host, now + timedelta(seconds=30),
           netin=1_060_000, netout=200_600)

    v = _vm(db, host)
    assert v.net_in_bps_cached == 2000.0
    assert v.net_out_bps_cached == 20.0


def test_a_newly_discovered_vm_is_not_probed_until_the_cycle_after(tmp_path):
    db, host, now = _seed(tmp_path)
    client = FakeClient()

    _cycle(db, host, now, client=client)
    assert client.calls == []
    assert _vm(db, host).guest_agent_ok is None

    _cycle(db, host, now + timedelta(seconds=30), client=client)
    assert client.calls == [("pve1", 100)]
    assert _vm(db, host).disk_bytes == 12_884_901_888


def test_the_guest_agent_fills_in_used_disk(tmp_path):
    db, host, now = _seed(tmp_path)
    client = FakeClient()

    _cycle(db, host, now, client=client)
    _cycle(db, host, now + timedelta(seconds=30), client=client)

    v = _vm(db, host)
    assert v.disk_bytes == 12_884_901_888
    # asked on the node the guest actually runs on, not the polling host's
    assert client.calls == [("pve1", 100)]


def test_a_vm_without_the_guest_agent_stays_null_and_is_not_an_error(tmp_path):
    """The agent is frequently not installed and PVE answers with an error.
    That is a NORMAL condition: the wrapper returns None, the cycle completes
    untouched, and the column stays null rather than dropping to 0."""
    db, host, now = _seed(tmp_path)
    client = FakeClient(answer=(False, None))

    _cycle(db, host, now, client=client)
    res = _cycle(db, host, now + timedelta(seconds=30), client=client)

    v = _vm(db, host)
    assert v.disk_bytes is None
    assert v.disk_total_bytes == 68719476736   # allocation needs no agent
    assert host.status == "connected"          # nothing degraded by this
    assert client.calls == [("pve1", 100)]
    assert res.events[0][0] == "metrics"       # an ordinary, complete cycle


def test_a_stopped_vm_is_never_asked(tmp_path):
    """No agent runs in a guest that is not running, so there is nothing to
    ask. The last reading goes with it: usage is a measurement, and one nobody
    can take is unknown."""
    db, host, now = _seed(tmp_path)
    client = FakeClient()
    checked = {}

    _cycle(db, host, now, client=client, checked=checked)
    _cycle(db, host, now + timedelta(seconds=30), client=client, checked=checked)
    assert _vm(db, host).disk_bytes == 12_884_901_888

    _cycle(db, host, now + timedelta(seconds=60), client=client,
           checked=checked, status="stopped")

    assert _vm(db, host).disk_bytes is None
    assert len(client.calls) == 1
    # Dropped out of the cadence map, so starting it again is measured on the
    # next cycle rather than up to VM_DISK_REFRESH_INTERVAL_S later.
    assert checked == {}


def test_used_disk_is_not_re_read_every_cycle(tmp_path):
    """A per-VM call on every 30 s cycle is what doc 02 section 3's budget
    forbids. Filesystem usage is a level that creeps, so it rides a slow
    cadence instead."""
    from proxploy.pollers import VM_DISK_REFRESH_INTERVAL_S

    db, host, now = _seed(tmp_path)
    client = FakeClient()
    checked = {}

    for i in range(10):
        _cycle(db, host, now + timedelta(seconds=30 * i), client=client,
               checked=checked)
    assert len(client.calls) == 1

    _cycle(db, host, now + timedelta(seconds=30 + VM_DISK_REFRESH_INTERVAL_S + 1),
           client=client, checked=checked)
    assert len(client.calls) == 2


def test_a_vm_with_no_agent_is_not_retried_every_cycle_either(tmp_path):
    """The one place this deliberately differs from _refresh_ip, which retries
    on the very next cycle whenever it has no address. A missing address is
    usually a DHCP lease about to arrive; a missing disk reading is usually an
    agent that is not installed and never will be, so retrying it costs a call
    per VM per cycle forever and buys nothing."""
    db, host, now = _seed(tmp_path)
    client = FakeClient(answer=(False, None))
    checked = {}

    for i in range(10):
        _cycle(db, host, now + timedelta(seconds=30 * i), client=client,
               checked=checked)

    assert len(client.calls) == 1
    assert _vm(db, host).disk_bytes is None


def test_os_type_is_read_for_a_vm_that_has_none(tmp_path):
    """os_type shipped in the first migration and nothing ever wrote it, so it
    was NULL for every VM including ones Proxploy created itself. PVE's raw
    value is stored: mapping it to an icon is the client's job."""
    db, host, now = _seed(tmp_path)
    client = FakeClient()

    _cycle(db, host, now, client=client)

    assert _vm(db, host).os_type == "l26"
    assert client.config_calls == [("qemu", "pve1", 100)]


def test_a_vm_that_already_knows_its_os_costs_no_call(tmp_path):
    """The cadence is "once", not a slow refresh: an ostype is set at creation
    and does not drift the way a DHCP lease does, so steady state for an
    established fleet is zero calls."""
    db, host, now = _seed(tmp_path)
    client = FakeClient()

    for i in range(10):
        _cycle(db, host, now + timedelta(seconds=30 * i), client=client)

    assert _vm(db, host).os_type == "l26"
    assert len(client.config_calls) == 1


def test_pve_refusing_the_config_leaves_os_type_null_and_does_not_error(tmp_path):
    """One optional extra on top of the bulk read, like version() and
    cluster_status() in _poll_once. Losing it must never cost a cycle."""
    from proxploy.services.proxmox import ProxmoxError

    db, host, now = _seed(tmp_path)
    client = FakeClient(config=ProxmoxError("403 Permission check failed"))

    res = _cycle(db, host, now, client=client)

    assert _vm(db, host).os_type is None
    assert host.status == "connected"      # nothing degraded by this
    assert res.events[0][0] == "metrics"   # an ordinary, complete cycle
    # Retried next cycle, which is free: only VMs still missing a value ask.
    _cycle(db, host, now + timedelta(seconds=30), client=client)
    assert len(client.config_calls) == 2


def test_an_empty_ostype_is_not_mistaken_for_an_answer(tmp_path):
    """An empty string stored here would look like a known ostype and stop
    this from ever asking again."""
    db, host, now = _seed(tmp_path)
    client = FakeClient(config={"ostype": ""})

    _cycle(db, host, now)
    _cycle(db, host, now + timedelta(seconds=30), client=client)

    assert _vm(db, host).os_type is None
    _cycle(db, host, now + timedelta(seconds=60), client=client)
    assert len(client.config_calls) == 2


def test_no_client_means_the_disk_reading_is_simply_not_refreshed(tmp_path):
    """ingest_cycle's bulk-read-in, caches-out contract still holds without a
    client: everything else on the row is written exactly as usual."""
    db, host, now = _seed(tmp_path)

    _cycle(db, host, now, client=None)

    v = _vm(db, host)
    assert v.disk_bytes is None
    assert v.mem_bytes == 6442450944 and v.disk_total_bytes == 68719476736


def test_the_agent_verdict_is_recorded_when_it_answers(tmp_path):
    """True means the agent answered, and it comes out of the SAME get-fsinfo
    call the disk reading does. No extra request per cycle buys this."""
    db, host, now = _seed(tmp_path)
    client = FakeClient()

    _cycle(db, host, now, client=client)
    _cycle(db, host, now + timedelta(seconds=30), client=client)

    v = _vm(db, host)
    assert v.guest_agent_ok is True
    assert v.disk_bytes == 12_884_901_888
    assert len(client.calls) == 1


def test_no_agent_configured_is_recorded_as_false_not_unknown(tmp_path):
    """The interesting case, and the one the whole column exists for. Proxmox
    answering `No QEMU guest agent configured` is a finding an operator can act
    on: it is the reason this VM's storage reads unknown. Recording it as
    unknown instead would throw that away."""
    db, host, now = _seed(tmp_path)
    client = FakeClient(answer=(False, None))

    _cycle(db, host, now, client=client)
    _cycle(db, host, now + timedelta(seconds=30), client=client)

    v = _vm(db, host)
    assert v.guest_agent_ok is False
    assert v.disk_bytes is None
    assert host.status == "connected"      # not a fault, nothing degraded


def test_an_agent_that_answers_nothing_usable_is_still_installed(tmp_path):
    """The pair the old single return could not express: the agent answered,
    so it is installed and responding, but every filesystem in the answer was
    skipped so there are no bytes to report."""
    db, host, now = _seed(tmp_path)
    client = FakeClient(answer=(True, None))

    _cycle(db, host, now, client=client)
    _cycle(db, host, now + timedelta(seconds=30), client=client)

    v = _vm(db, host)
    assert v.guest_agent_ok is True
    assert v.disk_bytes is None


def test_a_stopped_vm_is_unknown_not_uninstalled(tmp_path):
    """A guest that is not running cannot answer whatever it has installed, so
    "not installed" would be a claim nobody checked. Unknown is the truth, and
    the verdict comes back on the cycle after it starts again."""
    db, host, now = _seed(tmp_path)
    client = FakeClient()
    checked = {}

    _cycle(db, host, now, client=client, checked=checked)
    _cycle(db, host, now + timedelta(seconds=30), client=client, checked=checked)
    assert _vm(db, host).guest_agent_ok is True

    _cycle(db, host, now + timedelta(seconds=60), client=client,
           checked=checked, status="stopped")

    assert _vm(db, host).guest_agent_ok is None


def test_a_known_verdict_is_not_re_asked_every_cycle(tmp_path):
    """Whether an agent is installed is a fact about the guest, not a reading,
    so it rides the same 15 minute cadence the disk figure does. Asking every
    30 s would be a per-VM call for an answer that almost never changes."""
    from proxploy.pollers import VM_DISK_REFRESH_INTERVAL_S

    db, host, now = _seed(tmp_path)
    client = FakeClient(answer=(False, None))
    checked = {}

    for i in range(10):
        _cycle(db, host, now + timedelta(seconds=30 * i), client=client,
               checked=checked)
    assert len(client.calls) == 1
    assert _vm(db, host).guest_agent_ok is False

    _cycle(db, host, now + timedelta(seconds=30 + VM_DISK_REFRESH_INTERVAL_S + 1),
           client=client, checked=checked)
    assert len(client.calls) == 2


def test_an_unknown_verdict_is_retried_on_the_next_cycle(tmp_path):
    """The one place this leaves the pure time cadence, mirroring _refresh_ip's
    handling of a container with no address yet. (None, None) means the probe
    never reached PVE, so nothing was learned about the guest; waiting out 15
    minutes would leave a whole host's VMs reading unknown for a quarter of an
    hour after a blip that one cheap call settles."""
    db, host, now = _seed(tmp_path)
    client = FakeClient(answer=(None, None))
    checked = {}

    for i in range(4):
        _cycle(db, host, now + timedelta(seconds=30 * i), client=client,
               checked=checked)

    assert len(client.calls) == 3
    assert _vm(db, host).guest_agent_ok is None

    # And the moment PVE answers, it settles and stops being asked.
    client.answer = (False, None)
    _cycle(db, host, now + timedelta(seconds=120), client=client, checked=checked)
    _cycle(db, host, now + timedelta(seconds=150), client=client, checked=checked)
    assert len(client.calls) == 4
    assert _vm(db, host).guest_agent_ok is False


def test_a_probe_that_could_not_be_made_keeps_the_last_verdict(tmp_path):
    """Same rule _mark_unreachable applies from the other side: a failure PVE
    never attributed to the agent says nothing about what is installed inside
    the guest, so the previous finding stands rather than being wiped."""
    db, host, now = _seed(tmp_path)
    client = FakeClient(answer=(False, None))
    checked = {}

    _cycle(db, host, now, client=client, checked=checked)
    _cycle(db, host, now + timedelta(seconds=30), client=client, checked=checked)
    assert _vm(db, host).guest_agent_ok is False

    client.answer = (None, None)
    _cycle(db, host, now + timedelta(seconds=931), client=client, checked=checked)

    assert _vm(db, host).guest_agent_ok is False
