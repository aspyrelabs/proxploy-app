"""ingest_cycle: one bulk read -> caches + samples + snapshot + SSE events."""
import json
from pathlib import Path

FIX = Path(__file__).parent / "fixtures" / "pve"


def _fixtures():
    resources = json.loads((FIX / "cluster_resources_basic.json").read_text())
    rrd = {"pve1": json.loads((FIX / "rrddata_hour.json").read_text())}
    return resources, rrd


def _ingest(db, host):
    from proxploy.models import utcnow
    from proxploy.pollers import ingest_cycle

    resources, rrd = _fixtures()
    return ingest_cycle(db, host, resources, rrd, utcnow())


def test_host_samples_and_snapshot(tmp_path):
    from proxploy.models import MetricSample
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db, status="unreachable")
    res = _ingest(db, host)

    assert host.status == "connected" and host.last_seen_at is not None
    metrics = {s.metric for s in db.query(MetricSample).filter_by(
        target_type="host", target_id=host.id)}
    assert metrics == {"cpu_pct", "mem_bytes", "mem_pct", "disk_pct",
                       "net_in_bps", "net_out_bps"}

    snap = res.snapshot
    assert snap.nodes[0]["node"] == "pve1" and snap.nodes[0]["cpu_cores"] == 8
    assert snap.nodes[0]["cpu_pct"] == 42.0
    assert len(snap.storage) == 2
    # per node, not a cluster-wide total on the snapshot: see HostSnapshot
    assert snap.nodes[0]["net_in_bps"] == 1300000.0  # latest rrd row
    # recovery from unreachable publishes a host resource event
    assert ("resource", {"type": "host", "id": host.id,
                         "change": "status", "status": "connected"}) in res.events
    # first event is always the metrics delta
    assert res.events[0][0] == "metrics"
    assert {t["t"] for t in res.events[0][1]["targets"]} >= {"host"}


def test_first_poll_learns_the_hosts_node_name(tmp_path):
    """A host created through POST /hosts has no way to learn its node name at
    create time (PVE's /version carries none), node_name sat at NULL forever
    until a poll ran, which /cluster/nodes and the VM-create wizard's node
    picker both read directly. Only tests/support.py's seed_host_row ever set
    it by hand; this is the real path."""
    from proxploy.models import Host
    from tests.support import make_db

    db = make_db(tmp_path)
    host = Host(name="host-01", address="https://10.0.0.9:8006", status="connected")
    db.add(host)
    db.commit()
    assert host.node_name is None

    _ingest(db, host)
    assert host.node_name == "pve1"


def test_first_poll_never_overwrites_an_already_known_node_name(tmp_path):
    """A real multi-node cluster's Host row names the node it was actually
    added on; a later poll cycle must not second-guess that against whichever
    node happens first in /cluster/resources."""
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db, node="pve2")
    _ingest(db, host)
    assert host.node_name == "pve2"


def test_vms_upserted_and_apps_cached_refreshed(tmp_path):
    from proxploy.models import App, MetricSample, Vm
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db)
    db.add(App(host_id=host.id, ctid=150, name="Immich", slug="immich",
               status_cached="stopped"))
    db.commit()

    res = _ingest(db, host)

    vm = db.query(Vm).filter_by(host_id=host.id, vmid=100).one()
    assert vm.status == "running" and vm.name == "win11"
    assert vm.mem_bytes == 8589934592 and vm.cpu_cores == 4
    app_row = db.query(App).filter_by(ctid=150).one()
    assert app_row.status_cached == "running"
    assert app_row.cpu_pct_cached == 12.0
    assert app_row.mem_bytes_cached == 2147483648
    # stopped->running transition emitted a resource event
    assert ("resource", {"type": "app", "id": app_row.id,
                         "change": "status", "status": "running"}) in res.events
    # guest samples reference DB ids, not vmids (cpu_pct, mem_bytes, mem_pct)
    assert db.query(MetricSample).filter_by(target_type="app",
                                            target_id=app_row.id).count() == 3
    assert db.query(MetricSample).filter_by(target_type="vm",
                                            target_id=vm.id).count() == 3


def test_quorum_loss_is_recorded_and_an_unreadable_probe_does_not_clear_it(tmp_path):
    """A host that cannot accept a single write must stop reading as healthy.

    Reached for real on 2026-08-18 (doc 12 check 12): quorum genuinely lost,
    /etc/pve read-only, every write refused with "cluster not ready - no
    quorum?", and every host in Proxploy still read `connected` because nothing
    looked at the one field that said so.

    The second half is the more subtle rule: a cycle that could not ask must
    leave the last answer alone. UNREAD is not None, because None is a real
    value here (standalone).
    """
    from proxploy.models import utcnow
    from proxploy.pollers import UNREAD, ingest_cycle
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db)
    resources, rrd = _fixtures()

    ingest_cycle(db, host, resources, rrd, utcnow(), quorate=True)
    assert host.quorate is True

    ingest_cycle(db, host, resources, rrd, utcnow(), quorate=False)
    assert host.quorate is False
    # Status is deliberately untouched: reads genuinely still work, which is
    # exactly why the flag has to carry this rather than `status`.
    assert host.status == "connected"

    # /cluster/status unreadable this cycle: keep the known answer
    ingest_cycle(db, host, resources, rrd, utcnow(), quorate=UNREAD)
    assert host.quorate is False

    # standalone is a legitimate answer to write, and clears the warning
    ingest_cycle(db, host, resources, rrd, utcnow(), quorate=None)
    assert host.quorate is None


def test_a_vm_on_another_cluster_node_records_that_node(tmp_path):
    """The mirror records where the guest RUNS, not who reported it.

    Every fixture in this file puts every guest on the polling host's own node,
    which is the shape a fake falls into and a cluster never has:
    /cluster/resources answers for the whole cluster from any member. Without
    the node, every action on a mirrored VM went to the polling host's node and
    PVE answered `500 Configuration file 'nodes/<other>/qemu-server/<id>.conf'
    does not exist` (doc 12 check 18, PVE 9.2.10).
    """
    from proxploy.models import Vm, utcnow
    from proxploy.pollers import ingest_cycle
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db)          # node_name pve1
    resources, rrd = _fixtures()
    for r in resources:               # the VM lives on the OTHER member
        if r.get("type") == "qemu":
            r["node"] = "pve2"
    ingest_cycle(db, host, resources, rrd, utcnow())

    vm = db.query(Vm).filter_by(host_id=host.id, vmid=100).one()
    assert vm.node_name == "pve2"

    # and a later cycle follows the guest when it moves
    for r in resources:
        if r.get("type") == "qemu":
            r["node"] = "pve1"
    ingest_cycle(db, host, resources, rrd, utcnow())
    db.refresh(vm)
    assert vm.node_name == "pve1", "a migrated guest kept its old node"


def test_vm_removed_upstream_is_deleted(tmp_path):
    from proxploy.models import Vm
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db)
    db.add(Vm(host_id=host.id, vmid=999, name="gone", status="running"))
    db.commit()
    res = _ingest(db, host)
    assert db.query(Vm).filter_by(vmid=999).count() == 0
    assert ("resource", {"type": "vm", "change": "list"}) in res.events


def test_discovered_cts_with_catalog_suggestion(tmp_path):
    from proxploy.models import App, CatalogEntry
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db)
    db.add(App(host_id=host.id, ctid=150, name="Immich", slug="immich"))
    db.add(CatalogEntry(slug="plex", name="Plex", script_path="ct/plex.sh"))
    db.commit()
    res = _ingest(db, host)
    disc = res.snapshot.discovered
    assert [d["ctid"] for d in disc] == [200]  # 150 is mapped, not discovered
    assert disc[0]["suggestion"] == "plex" and disc[0]["name"] == "plex"


def test_snapshot_storage_carries_type_content_shared_status(tmp_path):
    """/cluster/resources already returns plugintype/content/shared/status on
    every storage row; the poller used to drop all four. Keeping them costs
    zero extra PVE calls, which is the only reason the Storage page can be
    served from the snapshot at all (doc 02 §3's O(nodes) poll budget)."""
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db)
    snap = _ingest(db, host).snapshot

    by_name = {s["storage"]: s for s in snap.storage}
    assert by_name["local"] == {
        "storage": "local", "node": "pve1",
        "used_bytes": 107374182400, "total_bytes": 471859200000,
        "type": "dir", "content": ["iso", "vztmpl", "backup"],
        "shared": False, "status": "available"}
    assert by_name["pbs-datastore"]["type"] == "pbs"
    assert by_name["pbs-datastore"]["content"] == ["backup"]
    assert by_name["pbs-datastore"]["shared"] is True


def test_ingest_persists_mem_pct_for_host_app_and_vm(tmp_path):
    """Doc 04's alert_rules.metric enum names mem_pct; without a sample by
    that name a memory rule is created, enabled, and never fires."""
    from proxploy.models import App, MetricSample, utcnow
    from proxploy.pollers import ingest_cycle
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db, node="pve1")
    db.add(App(host_id=host.id, ctid=101, name="redis", slug="redis-1-101",
               web_protocol="http", web_path="/", adopted=True))
    db.commit()

    resources = [
        {"type": "node", "node": "pve1", "status": "online", "cpu": 0.5,
         "maxcpu": 8, "mem": 4_000_000_000, "maxmem": 8_000_000_000, "uptime": 100},
        {"type": "lxc", "vmid": 101, "node": "pve1", "name": "redis",
         "status": "running", "cpu": 0.1, "maxcpu": 1,
         "mem": 512_000_000, "maxmem": 1_024_000_000, "maxdisk": 0, "uptime": 50},
        {"type": "qemu", "vmid": 201, "node": "pve1", "name": "win",
         "status": "running", "cpu": 0.2, "maxcpu": 4,
         "mem": 2_000_000_000, "maxmem": 8_000_000_000, "maxdisk": 0, "uptime": 50},
    ]
    ingest_cycle(db, host, resources, {"pve1": []}, utcnow())

    got = {(s.target_type, s.metric): s.value
           for s in db.query(MetricSample).filter_by(metric="mem_pct").all()}
    assert got[("host", "mem_pct")] == 50.0      # 4G of 8G
    assert got[("app", "mem_pct")] == 50.0       # 512M of 1024M
    assert got[("vm", "mem_pct")] == 25.0        # 2G of 8G


def test_ingest_persists_a_host_disk_pct_from_its_datastores(tmp_path):
    from proxploy.models import MetricSample, utcnow
    from proxploy.pollers import ingest_cycle
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db, node="pve1")
    resources = [
        {"type": "node", "node": "pve1", "status": "online", "cpu": 0.1,
         "maxcpu": 4, "mem": 1, "maxmem": 2, "uptime": 1},
        {"type": "storage", "storage": "local", "node": "pve1",
         "disk": 30, "maxdisk": 100, "shared": 0},
        {"type": "storage", "storage": "local", "node": "pve2",
         "disk": 10, "maxdisk": 100, "shared": 0},
        # shared datastore, reported once per node: must count ONCE
        {"type": "storage", "storage": "nfs", "node": "pve1",
         "disk": 60, "maxdisk": 200, "shared": 1},
        {"type": "storage", "storage": "nfs", "node": "pve2",
         "disk": 60, "maxdisk": 200, "shared": 1},
    ]
    ingest_cycle(db, host, resources, {"pve1": []}, utcnow())

    s = db.query(MetricSample).filter_by(metric="disk_pct").one()
    assert s.target_type == "host" and s.target_id == host.id
    # (30 + 10 + 60) / (100 + 100 + 200) = 25%
    assert s.value == 25.0


def test_a_host_reporting_no_storage_writes_no_disk_pct_at_all(tmp_path):
    """This used to record a flat 0.0, which is what a monitoring token that
    has lost Datastore.Audit produces: /cluster/resources answers fine and
    every storage row is simply absent. "The disks emptied" and "we were not
    allowed to look" are not the same reading, and only one of them should
    fire a free-space alert. The other host metrics still land."""
    from proxploy.models import MetricSample, utcnow
    from proxploy.pollers import ingest_cycle
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db, node="pve1")
    ingest_cycle(db, host, [
        {"type": "node", "node": "pve1", "status": "online", "cpu": 0.1,
         "maxcpu": 4, "mem": 1, "maxmem": 2, "uptime": 1}], {"pve1": []}, utcnow())
    assert db.query(MetricSample).filter_by(metric="disk_pct").count() == 0
    assert db.query(MetricSample).filter_by(metric="cpu_pct").count() == 1


def test_mem_pct_and_disk_pct_are_queryable_metrics():
    """api/metrics.py rejects anything outside METRICS with a 422, so a chart
    of a metric the alert rules use would 422 without this."""
    from proxploy.services.metrics import METRICS
    assert "mem_pct" in METRICS
    assert "disk_pct" in METRICS


def test_a_pve_upgrade_reaches_the_host_row(tmp_path):
    """hosts.pve_version used to be written ONLY at enrolment and by the manual
    POST /hosts/{id}/test. After an in-place PVE upgrade the header subline
    (which reads this column via /cluster/nodes) kept reporting the old
    version, while the identity rail — which reads the node's live /status —
    reported the new one. The same page contradicted itself until somebody
    happened to click Test."""
    from proxploy.models import utcnow
    from proxploy.pollers import ingest_cycle
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db)
    host.pve_version = "9.2.10"
    resources, rrd = _fixtures()

    ingest_cycle(db, host, resources, rrd, utcnow(), version="9.3.1")
    assert host.pve_version == "9.3.1"


def test_a_version_probe_that_failed_does_not_erase_the_known_version(tmp_path):
    """The probe is the optional half of a cycle, like rrddata: a token that
    reads /cluster/resources can still 403 on /version. Losing it must cost the
    version refresh and nothing else — writing None would replace a true, if
    stale, version with 'unknown' on the host page."""
    from proxploy.models import utcnow
    from proxploy.pollers import ingest_cycle
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db)
    host.pve_version = "9.2.10"
    resources, rrd = _fixtures()

    ingest_cycle(db, host, resources, rrd, utcnow(), version=None)
    assert host.pve_version == "9.2.10"
    assert host.status == "connected"


def test_a_node_renamed_in_pve_gets_its_new_name_on_the_next_cycle(tmp_path):
    """hosts.node_name was written at enrolment and never again, so a node
    renamed in PVE kept its old name here forever. That is the name peer
    discovery compares against to decide a node is already enrolled, so a
    stale one would offer an enrolled node as a brand new peer."""
    from proxploy.models import utcnow
    from proxploy.pollers import ingest_cycle
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db, node="pve1")
    resources, rrd = _fixtures()

    ingest_cycle(db, host, resources, rrd, utcnow(), node_name="pve1-renamed")
    assert host.node_name == "pve1-renamed"


def test_a_cluster_status_read_that_failed_does_not_erase_the_node_name(tmp_path):
    """Same hazard as the version probe: /cluster/status can 403 on a token
    that still reads /cluster/resources. Losing it must cost the node name
    refresh and nothing else, because /cluster/nodes and the VM-create node
    picker read this column and would find it blank."""
    from proxploy.models import utcnow
    from proxploy.pollers import ingest_cycle
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db, node="pve2")
    resources, rrd = _fixtures()

    ingest_cycle(db, host, resources, rrd, utcnow(), node_name=None)
    assert host.node_name == "pve2"
    assert host.status == "connected"


def test_an_app_follows_its_ct_to_another_node(tmp_path):
    """An app's node was assumed to be its HOST's node.

    True while installs choose the host and the migration handler repoints the
    row, wrong the moment a CT is migrated in the Proxmox UI: every stop, console
    and vzdump then aims at the wrong node, which is the failure the VM side hit
    on real hardware (doc 12 check 18).
    """
    from proxploy.models import App, utcnow
    from proxploy.pollers import ingest_cycle
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db)           # node_name pve1
    db.add(App(host_id=host.id, ctid=150, name="Immich", slug="immich",
               status_cached="stopped"))
    db.commit()

    resources, rrd = _fixtures()       # CT 150 is on pve1 here
    ingest_cycle(db, host, resources, rrd, utcnow())
    app_row = db.query(App).filter_by(ctid=150).one()
    assert app_row.node_name == "pve1"

    # Somebody moves it in the Proxmox UI.
    for r in resources:
        if r.get("type") == "lxc" and r.get("vmid") == 150:
            r["node"] = "pve2"
    ingest_cycle(db, host, resources, rrd, utcnow())
    db.refresh(app_row)
    assert app_row.node_name == "pve2", "the app kept its host's node"


def test_guest_node_prefers_the_row_and_falls_back_to_the_host():
    """One helper serves apps and VMs, and NULL must mean "ask the host" so an
    unpolled row behaves exactly as it did before either column existed."""
    from proxploy.services.hostclient import guest_node

    class Row:
        def __init__(self, node): self.node_name = node

    class H:
        node_name = "pve1"

    assert guest_node(H(), Row("pve2")) == "pve2"
    assert guest_node(H(), Row(None)) == "pve1"
    assert guest_node(H(), None) == "pve1"


def test_a_pool_that_drops_out_of_one_cycle_does_not_move_disk_pct(tmp_path):
    """Reported from real use 2026-08-18: the storage graph flapped between
    ~29% and ~12% every few minutes while the disks sat untouched.

    Confirmed against the real cluster on 2026-08-19 by restricting one empty
    1.8 TB pool away from its node: disk_pct went 11.6% -> 27.6% -> 11.6% with
    no byte changed. A cycle loses storage rows for reasons that have nothing
    to do with the disks (a cluster member drops out of /cluster/resources
    during a corosync split, an NFS mount goes inactive), and a pool that
    leaves BOTH sums moves the percentage sharply.
    """
    from proxploy.models import MetricSample, utcnow
    from proxploy.pollers import PoolMemory, ingest_cycle
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db, node="pve1")
    node = {"type": "node", "node": "pve1", "status": "online", "cpu": 0.1,
            "maxcpu": 4, "mem": 1, "maxmem": 2, "uptime": 1}
    small = {"type": "storage", "storage": "local", "node": "pve1",
             "disk": 30, "maxdisk": 100, "shared": 0}
    # the big, nearly empty pool: losing it is what swings the ratio
    big = {"type": "storage", "storage": "big", "node": "pve2",
           "disk": 0, "maxdisk": 900, "shared": 0}
    pools = PoolMemory()

    ingest_cycle(db, host, [node, small, big], {"pve1": []}, utcnow(), pools=pools)
    ingest_cycle(db, host, [node, small], {"pve1": []}, utcnow(), pools=pools)

    values = [s.value for s in db.query(MetricSample)
              .filter_by(metric="disk_pct").order_by(MetricSample.id).all()]
    # 30/1000 both times. Without the carry-forward the second cycle reads
    # 30/100 = 30.0%, which is the reported flap.
    assert values == [3.0, 3.0]


def test_a_pool_gone_for_good_eventually_leaves_the_denominator(tmp_path):
    """Carrying a missing pool forever would mean a datastore somebody really
    did remove counts against the percentage until the backend restarts."""
    from datetime import timedelta

    from proxploy.models import MetricSample, utcnow
    from proxploy.pollers import POOL_FORGET_AFTER_S, PoolMemory, ingest_cycle
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db, node="pve1")
    node = {"type": "node", "node": "pve1", "status": "online", "cpu": 0.1,
            "maxcpu": 4, "mem": 1, "maxmem": 2, "uptime": 1}
    small = {"type": "storage", "storage": "local", "node": "pve1",
             "disk": 30, "maxdisk": 100, "shared": 0}
    big = {"type": "storage", "storage": "big", "node": "pve2",
           "disk": 0, "maxdisk": 900, "shared": 0}
    pools, now = PoolMemory(), utcnow()

    ingest_cycle(db, host, [node, small, big], {"pve1": []}, now, pools=pools)
    ingest_cycle(db, host, [node, small], {"pve1": []},
                 now + timedelta(seconds=POOL_FORGET_AFTER_S + 1), pools=pools)

    values = [s.value for s in db.query(MetricSample)
              .filter_by(metric="disk_pct").order_by(MetricSample.id).all()]
    assert values == [3.0, 30.0]


def test_an_inactive_pool_keeps_its_last_known_size(tmp_path):
    """PVE keeps listing a datastore whose mount is down but stops filling in
    disk/maxdisk. Read literally that is a zero-byte pool, which drops it out
    of both sums exactly like a missing row does."""
    from proxploy.models import MetricSample, utcnow
    from proxploy.pollers import PoolMemory, ingest_cycle
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db, node="pve1")
    node = {"type": "node", "node": "pve1", "status": "online", "cpu": 0.1,
            "maxcpu": 4, "mem": 1, "maxmem": 2, "uptime": 1}
    small = {"type": "storage", "storage": "local", "node": "pve1",
             "disk": 30, "maxdisk": 100, "shared": 0}
    nfs = {"type": "storage", "storage": "nfs", "node": "pve1",
           "disk": 0, "maxdisk": 900, "shared": 1, "status": "available"}
    dead = {"type": "storage", "storage": "nfs", "node": "pve1",
            "shared": 1, "status": "unavailable"}
    pools = PoolMemory()

    ingest_cycle(db, host, [node, small, nfs], {"pve1": []}, utcnow(), pools=pools)
    ingest_cycle(db, host, [node, small, dead], {"pve1": []}, utcnow(), pools=pools)

    values = [s.value for s in db.query(MetricSample)
              .filter_by(metric="disk_pct").order_by(MetricSample.id).all()]
    assert values == [3.0, 3.0]


def _cluster_status(nodes: int, online: int | None = None) -> list[dict]:
    online = nodes if online is None else online
    return [{"type": "cluster", "name": "c", "nodes": nodes, "quorate": 1}] + [
        {"type": "node", "name": f"pve{i}", "online": 1 if i <= online else 0,
         "local": 1 if i == 1 else 0}
        for i in range(1, nodes + 1)]


def test_a_cycle_missing_a_cluster_member_writes_no_network_sample(tmp_path):
    """net_in_bps/net_out_bps SUM the per-node rrd rows, so a member that drops
    out of /cluster/resources halves the number with no traffic change.

    Observed on 2026-08-18: the two Hosts of one cluster reported byte-identical
    net_in every cycle until 08:33 and never agreed again after 08:35, because
    each had fallen back to summing only its own node. Throughput is a rate,
    not a level, so the honest answer is no sample rather than a carried-over
    one: reporting last cycle's bytes invents traffic that never moved.
    """
    from proxploy.models import MetricSample, utcnow
    from proxploy.pollers import ingest_cycle
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db, node="pve1")
    resources = [{"type": "node", "node": "pve1", "status": "online", "cpu": 0.1,
                  "maxcpu": 4, "mem": 1, "maxmem": 2, "uptime": 1}]
    rrd = {"pve1": [{"netin": 100.0, "netout": 50.0}]}

    # the cluster has two members; only one is in this cycle's rows
    ingest_cycle(db, host, resources, rrd, utcnow(),
                 status_rows=_cluster_status(2))
    assert db.query(MetricSample).filter_by(metric="net_in_bps").count() == 0
    assert db.query(MetricSample).filter_by(metric="net_out_bps").count() == 0
    # the metrics that are genuinely per-node still land
    assert db.query(MetricSample).filter_by(metric="cpu_pct").count() == 1

    # both members present: the sum is complete and gets recorded
    resources.append({"type": "node", "node": "pve2", "status": "online",
                      "cpu": 0.1, "maxcpu": 4, "mem": 1, "maxmem": 2, "uptime": 1})
    rrd["pve2"] = [{"netin": 25.0, "netout": 5.0}]
    ingest_cycle(db, host, resources, rrd, utcnow(),
                 status_rows=_cluster_status(2))
    assert db.query(MetricSample).filter_by(metric="net_in_bps").one().value == 125.0


def test_a_degraded_cycle_writes_no_network_sample_rather_than_zero(tmp_path):
    """A token that reads /cluster/resources can still 403 on rrddata. The node
    is present, its rrd is not, and the sum silently contributed 0.0: a flat
    zero line that reads as measured idle traffic."""
    from proxploy.models import MetricSample, utcnow
    from proxploy.pollers import ingest_cycle
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db, node="pve1")
    ingest_cycle(db, host, [
        {"type": "node", "node": "pve1", "status": "online", "cpu": 0.1,
         "maxcpu": 4, "mem": 1, "maxmem": 2, "uptime": 1}], {}, utcnow(),
        status_rows=_cluster_status(1), degraded=True)

    assert db.query(MetricSample).filter_by(metric="net_in_bps").count() == 0
    assert db.query(MetricSample).filter_by(metric="cpu_pct").count() == 1


def test_a_vanished_cluster_member_is_not_proof_a_guest_is_gone(tmp_path):
    """_absence_is_trustworthy guards VM/App rows against "a cluster member is
    down" by testing `all(status == "online")` over the nodes PRESENT in the
    read. Measured on hardware 2026-08-19: an ordinary node outage keeps the
    row and marks it offline, so that check already handles the common case.
    A member that stops appearing at all leaves no row to test, and VM rows
    have no missing_since countdown, so one such cycle would delete every
    guest on it and take their alert rules with them. Not reproduced on this
    hardware; this pins the guard so it cannot regress."""
    from proxploy.models import Vm, utcnow
    from proxploy.pollers import ingest_cycle
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db, node="pve1")
    db.add(Vm(host_id=host.id, vmid=100, name="on-the-other-node",
              status="running", node_name="pve2"))
    db.commit()

    # pve2 and its guest have dropped out of /cluster/resources entirely
    ingest_cycle(db, host, [
        {"type": "node", "node": "pve1", "status": "online", "cpu": 0.1,
         "maxcpu": 4, "mem": 1, "maxmem": 2, "uptime": 1}], {"pve1": []},
        utcnow(), status_rows=_cluster_status(2))

    assert db.query(Vm).filter_by(vmid=100).count() == 1, \
        "a partial read deleted a guest that is still running"


def test_host_metrics_are_skipped_rather_than_taken_from_another_node(tmp_path):
    """`own` fell back to snap_nodes[0] when this host's node was not in the
    cycle, so cpu_pct/mem_pct for THIS host were recorded from whichever node
    happened to come first: a different machine's numbers under this host's
    identity."""
    from proxploy.models import MetricSample, utcnow
    from proxploy.pollers import ingest_cycle
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db, node="pve1")
    host.node_name = "pve1"
    db.commit()

    ingest_cycle(db, host, [
        {"type": "node", "node": "pve9", "status": "online", "cpu": 0.99,
         "maxcpu": 4, "mem": 8, "maxmem": 8, "uptime": 1}], {"pve9": []},
        utcnow(), status_rows=_cluster_status(1))

    got = [s.value for s in db.query(MetricSample).filter_by(
        target_type="host", metric="cpu_pct").all()]
    assert got == [], f"recorded another node's cpu as this host's: {got}"


def _ingest_at(db, host, now, netin, netout):
    """One cycle with the CT-150 counters and the clock both pinned.

    A rate needs two readings and the gap between them, so neither the
    counters nor the timestamp can come from the shared fixture.
    """
    from proxploy.pollers import ingest_cycle

    resources, rrd = _fixtures()
    for r in resources:
        if r.get("type") == "lxc" and r["vmid"] == 150:
            r["netin"], r["netout"] = netin, netout
    return ingest_cycle(db, host, resources, rrd, now)


def _seed_app(db, host):
    from proxploy.models import App

    db.add(App(host_id=host.id, ctid=150, name="Immich", slug="immich"))
    db.commit()
    return db.query(App).filter_by(ctid=150).one()


def test_app_caches_storage_from_the_bulk_read(tmp_path):
    """`disk` and `maxdisk` are already in the row the poller parses. Storage
    for an app therefore costs no extra PVE call, which is the only reason it
    fits the poll budget at all."""
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db)
    app = _seed_app(db, host)

    _ingest(db, host)

    assert app.disk_bytes_cached == 5368709120
    assert app.disk_total_bytes_cached == 17179869184


def test_first_poll_stores_the_counters_but_cannot_make_a_rate(tmp_path):
    """netin/netout are counters, not rates. One reading is one point, and a
    point has no slope, so the rate stays None until there are two."""
    from datetime import datetime
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db)
    app = _seed_app(db, host)

    t0 = datetime(2026, 8, 20, 12, 0, 0)
    _ingest_at(db, host, t0, netin=1_000_000, netout=200_000)

    assert app.net_in_cached == 1_000_000
    assert app.net_out_cached == 200_000
    assert app.net_sampled_at == t0
    assert app.net_in_bps_cached is None
    assert app.net_out_bps_cached is None


def test_second_poll_derives_the_rate_from_the_counter_delta(tmp_path):
    """300000 bytes over 30 seconds is 10000 bytes/s. The elapsed time is
    measured, not assumed to be poll_interval_s, because the poll loop backs
    off exponentially on a failing host."""
    from datetime import datetime, timedelta
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db)
    app = _seed_app(db, host)

    t0 = datetime(2026, 8, 20, 12, 0, 0)
    _ingest_at(db, host, t0, netin=1_000_000, netout=200_000)
    _ingest_at(db, host, t0 + timedelta(seconds=30),
               netin=1_300_000, netout=200_600)

    assert app.net_in_bps_cached == 10_000.0
    assert app.net_out_bps_cached == 20.0
    # The counters advance too, so the NEXT cycle diffs against these.
    assert app.net_in_cached == 1_300_000


def test_a_counter_reset_yields_no_rate_rather_than_a_spike(tmp_path):
    """Restarting a container zeroes netin/netout. Diffing across that
    boundary gives a large negative number, and abs() would draw a fabricated
    traffic spike at exactly the moment an operator is most likely to be
    watching. A negative delta is read as the reset it is."""
    from datetime import datetime, timedelta
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db)
    app = _seed_app(db, host)

    t0 = datetime(2026, 8, 20, 12, 0, 0)
    _ingest_at(db, host, t0, netin=1_000_000, netout=200_000)
    _ingest_at(db, host, t0 + timedelta(seconds=30), netin=5_000, netout=900)

    assert app.net_in_bps_cached is None
    assert app.net_out_bps_cached is None
    # Recovery: the reset reading becomes the new baseline, so the cycle
    # after it produces a rate again.
    _ingest_at(db, host, t0 + timedelta(seconds=60), netin=305_000, netout=1_500)
    assert app.net_in_bps_cached == 10_000.0
