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
    assert snap.net["in_bps"] == 1300000.0  # latest rrd row
    # recovery from unreachable publishes a host resource event
    assert ("resource", {"type": "host", "id": host.id,
                         "change": "status", "status": "connected"}) in res.events
    # first event is always the metrics delta
    assert res.events[0][0] == "metrics"
    assert {t["t"] for t in res.events[0][1]["targets"]} >= {"host"}


def test_first_poll_learns_the_hosts_node_name(tmp_path):
    """A host created through POST /hosts has no way to learn its node name at
    create time (PVE's /version carries none) — node_name sat at NULL forever
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
        # shared datastore, reported once per node — must count ONCE
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


def test_disk_pct_is_zero_rather_than_a_crash_when_a_host_reports_no_storage(tmp_path):
    from proxploy.models import MetricSample, utcnow
    from proxploy.pollers import ingest_cycle
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db, node="pve1")
    ingest_cycle(db, host, [
        {"type": "node", "node": "pve1", "status": "online", "cpu": 0.1,
         "maxcpu": 4, "mem": 1, "maxmem": 2, "uptime": 1}], {"pve1": []}, utcnow())
    assert db.query(MetricSample).filter_by(metric="disk_pct").one().value == 0.0


def test_mem_pct_and_disk_pct_are_queryable_metrics():
    """api/metrics.py rejects anything outside METRICS with a 422, so a chart
    of a metric the alert rules use would 422 without this."""
    from proxploy.services.metrics import METRICS
    assert "mem_pct" in METRICS
    assert "disk_pct" in METRICS
