"""A poll cycle that loses only its metrics read is not an unreachable host.

Found on real hardware: a privilege-separated token could read
/cluster/resources but not /nodes/<n>/rrddata, which needs Sys.Audit. The
403 propagated out of _poll_once, _host_loop caught it with a bare
`except Exception`, and a node that was answering perfectly well was
reported to the operator as "unreachable", with nothing logged anywhere
saying why.
"""
import json

from proxploy.models import Host, HostCredential


def _app_with(tmp_path, fake):
    """app.state.sessionmaker only exists once the lifespan has run, so the
    TestClient context is entered and handed back to the caller to close."""
    from fastapi.testclient import TestClient
    from tests.support import make_app, seed_host_row

    app = make_app(tmp_path, fake=fake)
    c = TestClient(app)
    c.__enter__()
    with app.state.sessionmaker() as db:
        h = seed_host_row(db)
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!mon", "token_secret": "s"}).encode())
        db.add(HostCredential(host_id=h.id, kind="api_token:monitoring",
                              encrypted_blob=blob, key_version=ver,
                              public_meta="proxploy@pve!mon"))
        db.commit()
        return app, c, h.id


def _host(app, host_id) -> Host:
    with app.state.sessionmaker() as db:
        return db.get(Host, host_id)


def test_a_metrics_403_does_not_make_the_host_unreachable(tmp_path):
    from tests.fakes.pve import FakePVE

    fake = FakePVE(resources=[{"type": "node", "node": "pve1", "status": "online",
                               "maxcpu": 4, "maxmem": 8589934592}],
                   rrd_fail=True)
    app, c, host_id = _app_with(tmp_path, fake)

    # Must not raise: raising is what _host_loop turns into "unreachable".
    app.state.poller._poll_once(host_id)

    h = _host(app, host_id)
    assert h.status == "connected", h.status
    # The half of the cycle that did work must still land, or the host stays
    # nameless on every page that reads node_name.
    assert h.node_name == "pve1"


def test_the_lost_metrics_read_is_recorded_as_a_reason(tmp_path):
    from tests.fakes.pve import FakePVE

    fake = FakePVE(resources=[{"type": "node", "node": "pve1", "status": "online",
                               "maxcpu": 4, "maxmem": 8589934592}],
                   rrd_fail=True)
    app, c, host_id = _app_with(tmp_path, fake)
    app.state.poller._poll_once(host_id)

    h = _host(app, host_id)
    assert h.last_error, "a degraded cycle must say what it lost"
    assert "rrddata" in h.last_error or "metrics" in h.last_error.lower()


def test_a_clean_cycle_clears_a_previous_reason(tmp_path):
    from tests.fakes.pve import FakePVE

    fake = FakePVE(resources=[{"type": "node", "node": "pve1", "status": "online",
                               "maxcpu": 4, "maxmem": 8589934592}],
                   rrd_fail=True)
    app, c, host_id = _app_with(tmp_path, fake)
    app.state.poller._poll_once(host_id)
    assert _host(app, host_id).last_error

    fake.rrd_fail = False
    app.state.poller._poll_once(host_id)
    assert _host(app, host_id).last_error is None


def test_a_real_connection_failure_still_records_why(tmp_path):
    from tests.fakes.pve import FakePVE

    fake = FakePVE(fail=True)
    app, c, host_id = _app_with(tmp_path, fake)

    app.state.poller._mark_unreachable(host_id, "boom: connection refused")
    h = _host(app, host_id)
    assert h.status == "unreachable"
    # "unreachable" with a blank reason is what made this undiagnosable.
    assert "connection refused" in h.last_error


def _seed_guests(app, host_id):
    """One App and one Vm on host_id, both looking like a healthy poll left
    them a moment ago: real status, real readings, a recent net sample."""
    from proxploy.models import App, Vm, utcnow

    with app.state.sessionmaker() as db:
        a = App(host_id=host_id, ctid=101, name="redis", slug=f"redis-101-h{host_id}",
               status_cached="running", cpu_pct_cached=12.0,
               mem_bytes_cached=500_000_000, uptime_s_cached=3600,
               disk_bytes_cached=1_000_000_000, disk_total_bytes_cached=5_000_000_000,
               net_in_cached=1000, net_out_cached=2000,
               net_in_bps_cached=10.0, net_out_bps_cached=20.0,
               net_sampled_at=utcnow())
        v = Vm(host_id=host_id, vmid=201, name="win11", status="running",
              os_type="win11", cpu_cores=4, mem_bytes=6_000_000_000,
              mem_total_bytes=8_589_934_592, disk_bytes=20_000_000_000,
              disk_total_bytes=50_000_000_000,
              net_in_cached=1000, net_out_cached=2000,
              net_in_bps_cached=10.0, net_out_bps_cached=20.0,
              net_sampled_at=utcnow(), uptime_s=7200, guest_agent_ok=False)
        db.add_all([a, v])
        db.commit()
        return a.id, v.id


def test_an_unreachable_host_marks_its_apps_and_vms_unknown(tmp_path):
    from proxploy.models import App, Vm
    from tests.fakes.pve import FakePVE

    fake = FakePVE(fail=True)
    app, c, host_id = _app_with(tmp_path, fake)
    app_id, vm_id = _seed_guests(app, host_id)

    app.state.poller._mark_unreachable(host_id, "boom: connection refused")

    with app.state.sessionmaker() as db:
        a = db.get(App, app_id)
        v = db.get(Vm, vm_id)
        assert a.status_cached == "unknown"
        assert a.cpu_pct_cached is None
        assert a.mem_bytes_cached is None
        assert a.uptime_s_cached is None
        assert a.disk_bytes_cached is None
        assert a.disk_total_bytes_cached is None
        assert a.net_in_bps_cached is None
        assert a.net_out_bps_cached is None
        # raw counters and their timestamp are left alone: see the comment on
        # _mark_unreachable for why the rate diff still needs them intact.
        assert a.net_in_cached == 1000
        assert a.net_out_cached == 2000
        assert a.net_sampled_at is not None

        assert v.status == "unknown"
        # Live measurements go, exactly as they do for an app above.
        assert v.uptime_s is None
        assert v.mem_bytes is None
        assert v.disk_bytes is None
        assert v.net_in_bps_cached is None
        assert v.net_out_bps_cached is None
        # The ALLOCATION stays. It is a fact about how the guest is
        # configured, not a reading, and it is the denominator the VMs page
        # draws its meters against: blanking it would turn "usage unknown"
        # into "this VM has no memory and no disk".
        assert v.cpu_cores == 4
        assert v.mem_total_bytes == 8_589_934_592
        assert v.disk_total_bytes == 50_000_000_000
        # os_type is held for the same reason, and more strongly: what a guest
        # runs is part of its identity, not a reading. Clearing it would lose
        # the OS icon on every VM of an unreachable host and force the config
        # read again on recovery, for a value that cannot have changed.
        assert v.os_type == "win11"
        # guest_agent_ok is held for the same reason, and it is the one that
        # would hurt most to lose: "this VM has no guest agent" is why its
        # storage reads unknown, and blanking it during an outage swaps a real
        # finding for "we have no idea" on every VM of that host. What is
        # installed inside a guest does not change because we lost the route
        # to its hypervisor, and the next cycle would answer identically.
        assert v.guest_agent_ok is False
        # Raw counters and their timestamp survive for the same reason the
        # app's do: _update_net_rates needs them to diff against.
        assert v.net_in_cached == 1000 and v.net_sampled_at is not None


def test_a_dead_host_retrying_does_not_restate_a_cleared_vm(tmp_path):
    """The sweep runs on every one of a dead host's retries, forever. A VM
    already fully cleared must produce no write and no event, which is what
    stops the same rows and the same events being republished every cycle."""
    from proxploy.models import Vm
    from tests.fakes.pve import FakePVE

    fake = FakePVE(fail=True)
    app, c, host_id = _app_with(tmp_path, fake)
    _app_id, vm_id = _seed_guests(app, host_id)

    app.state.poller._mark_unreachable(host_id, "boom: connection refused")
    events = app.state.poller._mark_unreachable(host_id, "boom: connection refused")

    assert not any(d.get("type") == "vm" for _, d in events)
    with app.state.sessionmaker() as db:
        assert db.get(Vm, vm_id).mem_bytes is None


def test_a_vm_already_unknown_with_a_stale_reading_gets_it_cleared(tmp_path):
    """Status alone is not proof a VM was swept: ingest_cycle's own absence
    path, or a restart, can leave a stale reading behind an unknown status."""
    from proxploy.models import Vm
    from tests.fakes.pve import FakePVE

    fake = FakePVE(fail=True)
    app, c, host_id = _app_with(tmp_path, fake)
    with app.state.sessionmaker() as db:
        v = Vm(host_id=host_id, vmid=202, name="ghost", status="unknown",
               uptime_s=None, mem_bytes=6_000_000_000,
               mem_total_bytes=8_589_934_592, net_in_bps_cached=10.0)
        db.add(v)
        db.commit()
        vm_id = v.id

    events = app.state.poller._mark_unreachable(host_id, "boom: connection refused")

    with app.state.sessionmaker() as db:
        v = db.get(Vm, vm_id)
        assert v.mem_bytes is None and v.net_in_bps_cached is None
        assert v.mem_total_bytes == 8_589_934_592
    # Its status did not change, so no event for it, but the write happened.
    assert not any(d.get("type") == "vm" for _, d in events)


def test_a_healthy_hosts_guests_are_untouched(tmp_path):
    """The most important guard here: marking ONE host unreachable must never
    touch a guest that belongs to a different, still-answering host."""
    from proxploy.models import App, Vm
    from tests.fakes.pve import FakePVE
    from tests.support import seed_host_row

    fake = FakePVE(fail=True)
    app, c, dead_host_id = _app_with(tmp_path, fake)
    with app.state.sessionmaker() as db:
        healthy = seed_host_row(db, name="host-02", node="pve2")
        healthy_id = healthy.id
    dead_app_id, dead_vm_id = _seed_guests(app, dead_host_id)
    healthy_app_id, healthy_vm_id = _seed_guests(app, healthy_id)

    app.state.poller._mark_unreachable(dead_host_id, "boom: connection refused")

    with app.state.sessionmaker() as db:
        assert db.get(App, dead_app_id).status_cached == "unknown"
        assert db.get(Vm, dead_vm_id).status == "unknown"
        # unrelated to the dead host: still exactly what _seed_guests wrote
        healthy_app = db.get(App, healthy_app_id)
        healthy_vm = db.get(Vm, healthy_vm_id)
        assert healthy_app.status_cached == "running"
        assert healthy_app.cpu_pct_cached == 12.0
        assert healthy_vm.status == "running"
        assert healthy_vm.uptime_s == 7200


def test_marking_unreachable_twice_does_not_republish_the_same_events(tmp_path):
    from proxploy.models import App, Vm
    from tests.fakes.pve import FakePVE

    fake = FakePVE(fail=True)
    app, c, host_id = _app_with(tmp_path, fake)
    app_id, vm_id = _seed_guests(app, host_id)

    first = app.state.poller._mark_unreachable(host_id, "boom: connection refused")
    # host + one app + one vm, all transitioning for the first time
    assert len(first) == 3

    second = app.state.poller._mark_unreachable(host_id, "boom: connection refused")
    assert second == []

    # Nothing left to clear, so the second call is a no-op: the guests still
    # read exactly what the first call left them at.
    with app.state.sessionmaker() as db:
        a = db.get(App, app_id)
        v = db.get(Vm, vm_id)
        assert a.status_cached == "unknown"
        assert a.cpu_pct_cached is None
        assert v.status == "unknown"
        assert v.uptime_s is None


def test_a_host_already_marked_unreachable_still_sweeps_stale_guests(tmp_path):
    """This is the test that would have caught the transition-only guard: a
    host that was already unreachable before this call (a backend restart
    landing on a host that was already down, or any later retry) must still
    get its guests cleared, not just the host that is transitioning right
    now. Before the fix, the early return on `already` skipped the sweep
    entirely and these guests stayed on their stale, healthy-looking values
    forever."""
    from proxploy.models import App, Host, Vm
    from tests.fakes.pve import FakePVE

    fake = FakePVE(fail=True)
    app, c, host_id = _app_with(tmp_path, fake)
    app_id, vm_id = _seed_guests(app, host_id)

    # Simulate the host already being marked unreachable, with the guest
    # sweep from that never having run (e.g. a restart between the two).
    with app.state.sessionmaker() as db:
        host = db.get(Host, host_id)
        host.status = "unreachable"
        db.commit()

    events = app.state.poller._mark_unreachable(host_id, "boom: connection refused")

    with app.state.sessionmaker() as db:
        a = db.get(App, app_id)
        v = db.get(Vm, vm_id)
        assert a.status_cached == "unknown"
        assert a.cpu_pct_cached is None
        assert a.mem_bytes_cached is None
        assert a.uptime_s_cached is None
        assert v.status == "unknown"
        assert v.uptime_s is None
    # No host event: the host was not transitioning. The two guest events are
    # the actual fix.
    assert ("resource", {"type": "app", "id": app_id,
                         "change": "status", "status": "unknown"}) in events
    assert ("resource", {"type": "vm", "id": vm_id,
                         "change": "status", "status": "unknown"}) in events
    assert not any(d.get("type") == "host" for _, d in events)


def test_a_guest_already_unknown_with_a_stale_reading_gets_it_cleared(tmp_path):
    """ingest_cycle's own absence path can leave status_cached == "unknown"
    while a reading is still stale. The sweep must not skip a guest just
    because its status already looks right."""
    from proxploy.models import App
    from tests.fakes.pve import FakePVE

    fake = FakePVE(fail=True)
    app, c, host_id = _app_with(tmp_path, fake)
    with app.state.sessionmaker() as db:
        a = App(host_id=host_id, ctid=101, name="redis", slug="redis-101",
               status_cached="unknown", cpu_pct_cached=12.0,
               mem_bytes_cached=500_000_000, uptime_s_cached=3600,
               disk_bytes_cached=1_000_000_000, disk_total_bytes_cached=5_000_000_000,
               net_in_bps_cached=10.0, net_out_bps_cached=20.0)
        db.add(a)
        db.commit()
        app_id = a.id

    events = app.state.poller._mark_unreachable(host_id, "boom: connection refused")

    with app.state.sessionmaker() as db:
        a = db.get(App, app_id)
        assert a.status_cached == "unknown"
        assert a.cpu_pct_cached is None
        assert a.mem_bytes_cached is None
        assert a.uptime_s_cached is None
        assert a.disk_bytes_cached is None
        assert a.disk_total_bytes_cached is None
        assert a.net_in_bps_cached is None
        assert a.net_out_bps_cached is None
    # Its status did not change, so no app event, but the write still happened.
    assert not any(d.get("type") == "app" for _, d in events)


def test_recovery_after_unreachable_restores_real_values(tmp_path):
    """ingest_cycle's fresh read is the recovery path, and it must not be
    second-guessed by anything _mark_unreachable left behind."""
    from proxploy.models import App, Vm, utcnow
    from proxploy.pollers import ingest_cycle
    from tests.fakes.pve import FakePVE

    fake = FakePVE(fail=True)
    app, c, host_id = _app_with(tmp_path, fake)
    app_id, vm_id = _seed_guests(app, host_id)
    app.state.poller._mark_unreachable(host_id, "boom: connection refused")

    resources = [
        {"type": "node", "node": "pve1", "status": "online", "cpu": 0.1,
         "maxcpu": 4, "mem": 1_000_000_000, "maxmem": 8_000_000_000, "uptime": 100},
        {"type": "lxc", "vmid": 101, "node": "pve1", "name": "redis",
         "status": "running", "cpu": 0.15, "maxcpu": 1,
         "mem": 600_000_000, "maxmem": 1_024_000_000, "maxdisk": 2_000_000_000,
         "disk": 1_200_000_000, "netin": 1500, "netout": 2500, "uptime": 90},
        {"type": "qemu", "vmid": 201, "node": "pve1", "name": "win11",
         "status": "running", "cpu": 0.2, "maxcpu": 4,
         "mem": 3_000_000_000, "maxmem": 8_589_934_592, "maxdisk": 50_000_000_000,
         "uptime": 120},
    ]
    with app.state.sessionmaker() as db:
        from proxploy.models import Host

        host = db.get(Host, host_id)
        ingest_cycle(db, host, resources, {"pve1": []}, utcnow())
        db.commit()

        a = db.get(App, app_id)
        v = db.get(Vm, vm_id)
        assert a.status_cached == "running"
        assert a.cpu_pct_cached == 15.0
        assert a.uptime_s_cached == 90
        assert v.status == "running"
        assert v.uptime_s == 120
