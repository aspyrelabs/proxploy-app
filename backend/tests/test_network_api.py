"""Network reads + guest NIC read/edit (doc 05 §Network, doc 01 §6)."""
import json

from fastapi.testclient import TestClient

from proxploy.models import App, AuditEvent, Host, HostCredential, Job, MetricSample, Vm

NETWORKS = {
    "pve1": [
        {"iface": "vmbr0", "type": "bridge", "method": "static",
         "address": "10.0.0.9", "netmask": "255.255.255.0", "cidr": "10.0.0.9/24",
         "gateway": "10.0.0.1", "bridge_ports": "bond0", "bridge_vlan_aware": 1,
         "active": 1, "autostart": 1, "comments": "management"},
        {"iface": "bond0", "type": "bond", "method": "manual",
         "slaves": "enp1s0 enp2s0", "active": 1, "autostart": 1},
        {"iface": "enp1s0", "type": "eth", "method": "manual", "active": 1},
        {"iface": "vmbr0.10", "type": "vlan", "method": "manual",
         "vlan-id": 10, "vlan-raw-device": "vmbr0", "active": 1},
    ],
}


def _seed(app, *, ct_net="virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0,tag=10,firewall=1"):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.9:8006", node_name="pve1",
                    status="connected", pve_version="8.4.1")
        db.add(host)
        db.commit()
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!net", "token_secret": "s3cret"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token",
                              encrypted_blob=blob, key_version=ver))
        a = App(host_id=host.id, ctid=150, name="Immich", slug="immich")
        v = Vm(host_id=host.id, vmid=201, name="win11", status="running")
        db.add_all([a, v])
        db.commit()
        return host.id, a.id, v.id


def _fake():
    from tests.fakes.pve import FakePVE

    f = FakePVE()
    f.networks_by_node = dict(NETWORKS)
    f.guest_configs = {
        ("lxc", 150): {"hostname": "immich",
                       "net0": "name=eth0,bridge=vmbr0,hwaddr=BC:24:11:00:11:22,"
                               "ip=dhcp,type=veth"},
        ("qemu", 201): {"name": "win11",
                        "net0": "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0,tag=10,firewall=1",
                        "net1": "e1000=DE:AD:BE:EF:00:01,bridge=vmbr1,mtu=9000"},
    }
    return f


def test_bridges_is_a_live_passthrough_with_an_attachment_map(tmp_path, csrf_header,
                                                              bootstrap_admin):
    from tests.support import make_app, seed_snapshot

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id, app_id, vm_id = _seed(app)
        seed_snapshot(app, host_id, nodes=[{"node": "pve1", "status": "online"}])
        r = c.get("/api/v1/network/bridges")
        assert r.status_code == 200
        body = r.json()
        node = body["nodes"][0]
        assert node["node"] == "pve1" and node["host_id"] == host_id
        kinds = {i["iface"]: i["type"] for i in node["interfaces"]}
        assert kinds == {"vmbr0": "bridge", "bond0": "bond",
                         "enp1s0": "eth", "vmbr0.10": "vlan"}
        br = next(i for i in node["interfaces"] if i["iface"] == "vmbr0")
        assert br["cidr"] == "10.0.0.9/24" and br["bridge_ports"] == "bond0"
        assert br["vlan_aware"] is True and br["active"] is True
        # guest attachment map, from per-guest config reads
        att = {(x["guest_type"], x["iface"]): x for x in body["attachments"]}
        assert att[("app", "net0")]["bridge"] == "vmbr0"
        assert att[("app", "net0")]["macaddr"] == "BC:24:11:00:11:22"
        assert att[("vm", "net0")]["tag"] == 10
        assert att[("vm", "net1")]["bridge"] == "vmbr1"


def test_bridges_degrades_one_bad_host_instead_of_500ing_the_page(tmp_path, csrf_header,
                                                                   bootstrap_admin):
    """BLOCKING 3: `client_for_host` raises ProxmoxError for a host with no API
    token credential — a routine state, not an outage — and network.py never
    caught it, so one such host 500'd the whole page. Now it is degraded out
    into `errors` and the reachable host still serves its nodes."""
    from proxploy.models import Host
    from tests.support import make_app, seed_snapshot

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id, _, _ = _seed(app)
        seed_snapshot(app, host_id, nodes=[{"node": "pve1", "status": "online"}])
        with app.state.sessionmaker() as db:
            bad = Host(name="host-02", address="https://10.0.0.10:8006",
                      node_name="pve2", status="connected", pve_version="8.4.1")
            db.add(bad)
            db.commit()
            bad_id = bad.id  # no HostCredential row at all
        r = c.get("/api/v1/network/bridges")
        assert r.status_code == 200
        body = r.json()
        assert body["nodes"][0]["host_id"] == host_id  # the good host still served
        assert body["errors"] == [{"host_id": bad_id, "host_name": "host-02",
                                   "error": "host host-02 has no API token credential"}]


def test_bridges_filters_by_host(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app, seed_snapshot

    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id, _, _ = _seed(app)
        seed_snapshot(app, host_id, nodes=[{"node": "pve1", "status": "online"}])
        assert c.get(f"/api/v1/network/bridges?host={host_id}").json()["nodes"]
        assert c.get(f"/api/v1/network/bridges?host={host_id + 99}").json()["nodes"] == []


def test_throughput_reads_the_existing_host_metric_series(tmp_path, csrf_header,
                                                          bootstrap_admin):
    """Same MetricsStore rows /metrics/query serves — no second reader."""
    from proxploy.models import utcnow
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id, _, _ = _seed(app)
        now = utcnow()
        with app.state.sessionmaker() as db:
            for i in range(3):
                db.add(MetricSample(target_type="host", target_id=host_id,
                                    metric="net_in_bps", value=100.0 + i, ts=now))
                db.add(MetricSample(target_type="host", target_id=host_id,
                                    metric="net_out_bps", value=10.0 + i, ts=now))
            db.commit()
        r = c.get("/api/v1/network/throughput?hours=1")
        assert r.status_code == 200
        body = r.json()
        assert body["resolution"] == "raw"
        h = body["hosts"][0]
        assert h["host_id"] == host_id and h["host_name"] == "host-01"
        assert h["in"]["value"] == [100.0, 101.0, 102.0]
        assert h["out"]["value"] == [10.0, 11.0, 12.0]


def test_guest_network_read_lists_every_nic(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, app_id, vm_id = _seed(app)
        nics = c.get(f"/api/v1/vms/{vm_id}/network").json()
        assert [n["iface"] for n in nics] == ["net0", "net1"]
        assert nics[0]["model"] == "virtio"
        assert nics[0]["macaddr"] == "AA:BB:CC:DD:EE:FF"
        assert nics[0]["tag"] == 10 and nics[0]["firewall"] is True
        assert nics[1]["mtu"] == "9000"
        ct = c.get(f"/api/v1/apps/{app_id}/network").json()
        assert ct[0]["macaddr"] == "BC:24:11:00:11:22" and ct[0]["model"] == "veth"


def test_guest_nic_edit_preserves_the_mac_and_unknown_keys(tmp_path, csrf_header,
                                                           bootstrap_admin):
    """The regression this whole task exists to prevent."""
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, _, vm_id = _seed(app)
        r = c.put(f"/api/v1/vms/{vm_id}/network/net1",
                  json={"bridge": "vmbr7", "tag": 42}, headers=csrf_header(c))
        assert r.status_code == 200, r.text
        assert r.json()["value"] == \
            "e1000=DE:AD:BE:EF:00:01,bridge=vmbr7,mtu=9000,tag=42"
        assert fake.config_updates == [
            ("qemu", 201, {"net1": "e1000=DE:AD:BE:EF:00:01,bridge=vmbr7,mtu=9000,tag=42"})]


def test_guest_nic_edit_can_clear_a_key_with_an_explicit_null(tmp_path, csrf_header,
                                                              bootstrap_admin):
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, _, vm_id = _seed(app)
        r = c.put(f"/api/v1/vms/{vm_id}/network/net0", json={"tag": None},
                  headers=csrf_header(c))
        assert r.json()["value"] == "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0,firewall=1"


def test_guest_nic_edit_is_not_a_job_and_reports_pending(tmp_path, csrf_header,
                                                         bootstrap_admin):
    """A config PUT is not long-running. It returns directly, with the UPID PVE
    handed back for a running qemu guest and an honest pending-until-reboot flag."""
    from tests.support import make_app

    fake = _fake()
    fake.config_update_upid = "UPID:pve1:00001234:...:qmconfig:201:proxploy@pve:"
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, _, vm_id = _seed(app)
        r = c.put(f"/api/v1/vms/{vm_id}/network/net0", json={"bridge": "vmbr3"},
                  headers=csrf_header(c))
        assert r.status_code == 200
        body = r.json()
        assert body["upid"] == fake.config_update_upid
        assert body["pending_reboot"] is True
        assert "reboot" in body["detail"].lower()
        with app.state.sessionmaker() as db:
            assert db.query(Job).count() == 0  # NOT a job


def test_guest_nic_edit_audits_without_a_job_id(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, app_id, _ = _seed(app)
        c.put(f"/api/v1/apps/{app_id}/network/net0", json={"bridge": "vmbr5"},
              headers=csrf_header(c))
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="network.guest_config").one()
            assert row.target_type == "app" and row.target_id == app_id
            assert row.job_id is None
            assert row.params["iface"] == "net0" and row.params["bridge"] == "vmbr5"


def test_unknown_iface_is_404_not_a_new_nic(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, _, vm_id = _seed(app)
        r = c.put(f"/api/v1/vms/{vm_id}/network/net9", json={"bridge": "vmbr0"},
                  headers=csrf_header(c))
        assert r.status_code == 404


def _all_paths(app):
    """Flatten app.routes in registration order.

    This FastAPI build (0.140.x) defers `include_router` into a lazy
    `_IncludedRouter` node rather than eagerly copying child routes onto
    `app.routes`, so a plain `[r.path for r in app.routes if hasattr(r, "path")]`
    silently returns only the 4 top-level doc routes and none of api_router's
    children. `_IncludedRouter.effective_route_contexts()` is the same
    recursive walk Starlette's own dispatch uses to pick a route at request
    time, so reading it here reflects the real match order.
    """
    paths = []
    for r in app.routes:
        if hasattr(r, "effective_route_contexts"):
            paths.extend(c.path for c in r.effective_route_contexts())
        elif hasattr(r, "path"):
            paths.append(r.path)
    return paths


def test_network_routes_are_registered_above_the_lifecycle_wildcards(tmp_path):
    """Starlette matches in registration order (apps.py:266-271). If
    /{id}/network lands after /{id}/{action}, the wildcard eats it and the
    action string arrives as "network"."""
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())
    paths = _all_paths(app)
    assert paths.index("/api/v1/vms/{vm_id}/network") < \
        paths.index("/api/v1/vms/{vm_id}/{action}")
    assert paths.index("/api/v1/vms/{vm_id}/network/{iface}") < \
        paths.index("/api/v1/vms/{vm_id}/{action}")
    assert paths.index("/api/v1/apps/{app_id}/network") < \
        paths.index("/api/v1/apps/{app_id}/{action}")
    assert paths.index("/api/v1/apps/{app_id}/network/{iface}") < \
        paths.index("/api/v1/apps/{app_id}/{action}")


def test_put_network_does_not_enqueue_a_lifecycle_job(tmp_path, csrf_header,
                                                      bootstrap_admin):
    """The behavioural half of the ordering assertion above: if the wildcard
    swallowed this, we would get a 422 "action must be one of ..." or a queued
    lifecycle job instead of a config write."""
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, _, vm_id = _seed(app)
        r = c.put(f"/api/v1/vms/{vm_id}/network/net0", json={"bridge": "vmbr4"},
                  headers=csrf_header(c))
        assert r.status_code == 200
        assert "action must be one of" not in r.text
        with app.state.sessionmaker() as db:
            assert db.query(Job).count() == 0
        assert fake.actions == []  # no guest_action ever reached PVE


def test_guest_network_read_failure_is_a_502(tmp_path, csrf_header, bootstrap_admin):
    """BLOCKING 3: guest_nics() never caught ProxmoxError either — a bare 500
    instead of the 502 every other read in this phase returns."""
    from tests.support import make_app

    fake = _fake()
    fake.fail = True
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, _, vm_id = _seed(app)
        assert c.get(f"/api/v1/vms/{vm_id}/network").status_code == 502


def test_guest_nic_edit_failure_is_a_502_with_an_error_audit_row(tmp_path, csrf_header,
                                                                 bootstrap_admin):
    """BLOCKING 3: set_guest_nic() is a mutation with no ProxmoxError handling —
    a failed write must still leave an audit trace, matching storage.py."""
    from tests.support import make_app

    fake = _fake()
    fake.fail = True
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, _, vm_id = _seed(app)
        r = c.put(f"/api/v1/vms/{vm_id}/network/net0", json={"bridge": "vmbr9"},
                  headers=csrf_header(c))
        assert r.status_code == 502
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="network.guest_config").one()
            assert row.result == "error"


def test_missing_session_is_401_not_403(tmp_path, csrf_header):
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        _, _, vm_id = _seed(app)
        assert c.get("/api/v1/network/bridges").status_code == 401
        assert c.put(f"/api/v1/vms/{vm_id}/network/net0", json={"bridge": "vmbr0"},
                     headers=csrf_header(c)).status_code == 401
