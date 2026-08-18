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
        # This file exercises both reads (guest_nics/list_bridges, monitoring)
        # and the guest NIC write (set_guest_nic, lifecycle -- see
        # api/network.py's docstring on why the read+write share one client).
        for cap in ("monitoring", "lifecycle"):
            blob, ver = app.state.secretstore.encrypt(json.dumps(
                {"token_id": f"proxploy@pve!net-{cap}",
                 "token_secret": "s3cret"}).encode())
            db.add(HostCredential(host_id=host.id, kind=f"api_token:{cap}",
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
    token credential, a routine state, not an outage; and network.py never
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
                                   "error": ("host-02 has no monitoring API token "
                                             "configured; add one in Settings -> "
                                             "Hosts before this operation can run.")}]


def test_bridges_reports_each_real_node_once_across_hosts_on_one_cluster(tmp_path, csrf_header,
                                                                          bootstrap_admin):
    """Two Hosts can be two nodes of the SAME Proxmox cluster; _nodes_of reads
    snap.nodes, and each host's poll sees the whole cluster's node list (root
    cause: cluster_resources() returns every node from any node asked), so
    both snapshots list both pve1 and pve2. A real node's interfaces must be
    reported once, attributed to the host actually registered at that node."""
    from proxploy.models import Host, HostCredential
    from tests.support import make_app, seed_snapshot

    fake = _fake()
    fake.networks_by_node["pve2"] = [
        {"iface": "vmbr0", "type": "bridge", "method": "static",
         "address": "10.0.0.10", "netmask": "255.255.255.0",
         "cidr": "10.0.0.10/24", "active": 1, "autostart": 1},
    ]
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        hid1, _, _ = _seed(app)
        with app.state.sessionmaker() as db:
            h2 = Host(name="host-02", address="https://10.0.0.10:8006",
                      node_name="pve2", status="connected", pve_version="8.4.1")
            db.add(h2)
            db.commit()
            blob, ver = app.state.secretstore.encrypt(json.dumps(
                {"token_id": "proxploy@pve!net2-monitoring",
                 "token_secret": "s3cret"}).encode())
            db.add(HostCredential(host_id=h2.id, kind="api_token:monitoring",
                                  encrypted_blob=blob, key_version=ver))
            # Both Hosts are the SAME real cluster (Host.cluster_name, set by
            # the poller in production); that is what makes their two
            # snapshots the same cluster-wide view, not two unrelated hosts.
            db.get(Host, hid1).cluster_name = "lab-cluster"
            h2.cluster_name = "lab-cluster"
            db.commit()
            hid2 = h2.id
        seed_snapshot(app, hid1, nodes=[{"node": "pve1", "status": "online"},
                                        {"node": "pve2", "status": "online"}])
        seed_snapshot(app, hid2, nodes=[{"node": "pve1", "status": "online"},
                                        {"node": "pve2", "status": "online"}])
        r = c.get("/api/v1/network/bridges")
        assert r.status_code == 200
        body = r.json()
        assert len(body["nodes"]) == 2
        by_node = {n["node"]: n for n in body["nodes"]}
        assert by_node["pve1"]["host_id"] == hid1
        assert by_node["pve2"]["host_id"] == hid2


def test_bridges_does_not_merge_same_named_node_across_different_clusters(tmp_path, csrf_header,
                                                                          bootstrap_admin):
    """A node name is only unique WITHIN one cluster. Two different, standalone
    clusters can each have a node called pve1; both must be reported, one row
    per Host, not deduped into one."""
    from proxploy.models import Host, HostCredential
    from tests.support import make_app, seed_snapshot

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        hid1, _, _ = _seed(app)  # host-01, standalone, node pve1
        with app.state.sessionmaker() as db:
            h2 = Host(name="host-02", address="https://10.0.0.10:8006",
                      node_name="pve1", status="connected", pve_version="8.4.1")
            db.add(h2)
            db.commit()
            blob, ver = app.state.secretstore.encrypt(json.dumps(
                {"token_id": "proxploy@pve!net2-monitoring",
                 "token_secret": "s3cret"}).encode())
            db.add(HostCredential(host_id=h2.id, kind="api_token:monitoring",
                                  encrypted_blob=blob, key_version=ver))
            db.commit()
            hid2 = h2.id  # also standalone: cluster_name left None on both
        seed_snapshot(app, hid1, nodes=[{"node": "pve1", "status": "online"}])
        seed_snapshot(app, hid2, nodes=[{"node": "pve1", "status": "online"}])
        r = c.get("/api/v1/network/bridges")
        assert r.status_code == 200
        body = r.json()
        assert len(body["nodes"]) == 2
        assert {n["host_id"] for n in body["nodes"]} == {hid1, hid2}


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
    """Same MetricsStore rows /metrics/query serves, no second reader."""
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
    """BLOCKING 3: guest_nics() never caught ProxmoxError either, a bare 500
    instead of the 502 every other read in this phase returns."""
    from tests.support import make_app

    fake = _fake()
    fake.fail = True
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, _, vm_id = _seed(app)
        assert c.get(f"/api/v1/vms/{vm_id}/network").status_code == 502


def test_a_failed_read_is_not_recorded_as_a_configuration_attempt(tmp_path, csrf_header,
                                                                  bootstrap_admin):
    """The read half of set_guest_nic()'s read-modify-write failing means
    NOTHING was sent to the guest, so it must not land in the log under the
    action that means "this guest's network was configured". Its own
    identifier, and the config one absent entirely."""
    from tests.support import make_app

    fake = _fake()
    fake.fail = True          # fails guest_config(), i.e. the read
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, _, vm_id = _seed(app)
        r = c.put(f"/api/v1/vms/{vm_id}/network/net0", json={"bridge": "vmbr9"},
                  headers=csrf_header(c))
        assert r.status_code == 502
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(
                action="network.guest_config_read").one()
            assert row.result == "error"
            assert row.target_type == "vm" and row.target_id == vm_id
            assert db.query(AuditEvent).filter_by(
                action="network.guest_config").count() == 0
        assert fake.config_updates == []   # nothing reached the guest


def test_guest_nic_write_failure_is_a_502_with_an_error_audit_row(tmp_path, csrf_header,
                                                                  bootstrap_admin,
                                                                  monkeypatch):
    """BLOCKING 3: set_guest_nic() is a mutation with no ProxmoxError handling, 
    a failed write must still leave an audit trace, matching storage.py. The
    read succeeds here, so this is the real write path, and it keeps the
    `network.guest_config` identifier the successful write uses."""
    from proxploy.services.proxmox import ProxmoxClient, ProxmoxError
    from tests.support import make_app

    def boom(*a, **kw):
        raise ProxmoxError("fake PVE refused the write")

    monkeypatch.setattr(ProxmoxClient, "guest_config_update", boom)
    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, _, vm_id = _seed(app)
        r = c.put(f"/api/v1/vms/{vm_id}/network/net0", json={"bridge": "vmbr9"},
                  headers=csrf_header(c))
        assert r.status_code == 502
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="network.guest_config").one()
            assert row.result == "error"
            assert row.params["bridge"] == "vmbr9"


def test_missing_session_is_401_not_403(tmp_path, csrf_header):
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        _, _, vm_id = _seed(app)
        assert c.get("/api/v1/network/bridges").status_code == 401
        assert c.put(f"/api/v1/vms/{vm_id}/network/net0", json={"bridge": "vmbr0"},
                     headers=csrf_header(c)).status_code == 401


# --- guest addressing: a container's is on its NIC, a VM's is not -------------

def test_a_container_ip_and_gateway_are_written_onto_its_netN(tmp_path, csrf_header,
                                                              bootstrap_admin):
    """PVE's own schema: `pct set --net[n] ... [,gw=<GatewayIPv4>]
    [,ip=<(IPv4/CIDR|dhcp|manual)>]`. So this is a normal key merge onto the same
    string, and the MAC and every unmodelled option survive it.
    """
    from fastapi.testclient import TestClient
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _hid, app_id, _vm_id = _seed(app)
        r = c.put(f"/api/v1/apps/{app_id}/network/net0",
                  json={"ip": "192.168.1.50/24", "gw": "192.168.1.1"},
                  headers=csrf_header(c))
        assert r.status_code == 200, r.text
        value = r.json()["value"]

    assert "ip=192.168.1.50/24" in value and "gw=192.168.1.1" in value
    # The identity tokens are untouched: a dropped hwaddr means PVE mints a new
    # MAC at next start and every DHCP reservation for that guest breaks.
    assert "hwaddr=BC:24:11:00:11:22" in value
    assert "name=eth0" in value


def test_dhcp_and_clearing_are_both_expressible_on_a_container(tmp_path, csrf_header,
                                                               bootstrap_admin):
    from fastapi.testclient import TestClient
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _hid, app_id, _vm_id = _seed(app)
        dhcp = c.put(f"/api/v1/apps/{app_id}/network/net0", json={"ip": "dhcp"},
                     headers=csrf_header(c))
        assert dhcp.status_code == 200, dhcp.text
        assert "ip=dhcp" in dhcp.json()["value"]

        # An explicit null clears the key, which is "not configured", a state PVE
        # has and an operator can want back. Not the same as dhcp.
        cleared = c.put(f"/api/v1/apps/{app_id}/network/net0", json={"ip": None},
                        headers=csrf_header(c))
        assert cleared.status_code == 200, cleared.text
        assert "ip=" not in cleared.json()["value"]


def test_a_vm_address_is_refused_with_the_reason_not_written_to_netN(
        tmp_path, csrf_header, bootstrap_admin):
    """`qm set --net[n]` has NO ip or gw field. PVE addresses a VM through the
    cloud-init key `ipconfigN`, which does nothing unless the VM has a cloud-init
    drive and the guest reads it, and Windows has no cloud-init at all. Writing
    it would be a config change with no stateable effect, so it is refused.
    """
    from fastapi.testclient import TestClient
    from proxploy.models import AuditEvent
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _hid, _app_id, vm_id = _seed(app)
        r = c.put(f"/api/v1/vms/{vm_id}/network/net0",
                  json={"ip": "192.168.1.50/24"}, headers=csrf_header(c))
        assert r.status_code == 409, r.text
        body = r.json()
        detail = body.get("detail") if isinstance(body.get("detail"), dict) else body
        assert detail["error"] == "vm_addressing_not_editable"
        assert "cloud-init" in detail["detail"]

        # Nothing reached the guest, and no row claims a NIC was configured.
        assert fake.config_updates == []
        with app.state.sessionmaker() as db:
            assert db.query(AuditEvent).filter_by(action="network.guest_config").count() == 0

    # A VM's other NIC fields still work: only addressing is refused.
    fake2 = _fake()
    app2 = make_app(tmp_path / "second", fake=fake2)
    with TestClient(app2) as c:
        bootstrap_admin(c)
        _hid, _app_id, vm_id = _seed(app2)
        ok = c.put(f"/api/v1/vms/{vm_id}/network/net0", json={"tag": 42},
                   headers=csrf_header(c))
        assert ok.status_code == 200, ok.text


def test_a_malformed_address_is_a_422_here_not_a_502_from_proxmox(tmp_path, csrf_header,
                                                                 bootstrap_admin):
    """A bare address without a prefix is the mistake an operator actually makes,
    and PVE answers it with a 400 that this would relay as a 502. Shape-checked
    locally so the message can name what a valid one looks like."""
    from fastapi.testclient import TestClient
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _hid, app_id, _vm_id = _seed(app)
        for bad in ({"ip": "192.168.1.50"}, {"ip": "not-an-ip"},
                    {"gw": "192.168.1.0/24"}, {"ip6": "192.168.1.50/24"}):
            r = c.put(f"/api/v1/apps/{app_id}/network/net0", json=bad,
                      headers=csrf_header(c))
            assert r.status_code == 422, f"{bad}: {r.text}"
        assert fake.config_updates == []
