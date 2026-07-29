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
    assert metrics == {"cpu_pct", "mem_bytes", "net_in_bps", "net_out_bps"}

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
    # guest samples reference DB ids, not vmids
    assert db.query(MetricSample).filter_by(target_type="app",
                                            target_id=app_row.id).count() == 2
    assert db.query(MetricSample).filter_by(target_type="vm",
                                            target_id=vm.id).count() == 2


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
