# backend/tests/test_proxmox_infra_reads.py
"""Phase 6 Task 1: the infra-read half of ProxmoxClient, plus the one
decrypt-then-construct helper both routers and job handlers now share."""
import json

import pytest
from fastapi.testclient import TestClient

from proxploy.models import Host, HostCredential
from proxploy.services.hostclient import client_for_host
from proxploy.services.proxmox import ProxmoxClient, ProxmoxError
from tests.fakes.pve import FakePVE, make_fake_factory


def _client(fake):
    return ProxmoxClient("https://10.0.0.9:8006", "proxploy@pve!infra",
                         "sekret", verify_tls=False,
                         factory=make_fake_factory(fake))


def _seed_host_with_token(app, secret="s3cret"):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.7:8006",
                    node_name="pve1", status="connected")
        db.add(host)
        db.commit()
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!infra", "token_secret": secret}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token:monitoring",
                              encrypted_blob=blob, key_version=ver))
        db.commit()
        return host.id


# --- storage reads --------------------------------------------------------

def test_storages_lists_the_nodes_datastores():
    fake = FakePVE()
    fake.storages_by_node = {"pve1": [
        {"storage": "local", "type": "dir", "content": "iso,vztmpl",
         "active": 1, "shared": 0, "used": 5, "avail": 95, "total": 100},
        {"storage": "local-lvm", "type": "lvmthin", "content": "images,rootdir",
         "active": 1, "shared": 0, "used": 20, "avail": 80, "total": 100},
    ]}
    rows = _client(fake).storages("pve1")
    assert [r["storage"] for r in rows] == ["local", "local-lvm"]


def test_storage_status_returns_the_per_datastore_detail():
    fake = FakePVE()
    fake.storage_status_response = {"type": "lvmthin", "content": "images,rootdir",
                                    "active": 1, "enabled": 1, "shared": 0,
                                    "used": 20, "avail": 80, "total": 100}
    out = _client(fake).storage_status("pve1", "local-lvm")
    assert out == fake.storage_status_response
    assert fake.last_storage_status_call == ("pve1", "local-lvm")


def test_storage_content_passes_the_content_filter_through():
    fake = FakePVE()
    fake.content_by_storage = {"local": [
        {"volid": "local:iso/debian-12.iso", "format": "iso", "size": 700,
         "used": 700, "vmid": None, "ctime": 1, "content": "iso",
         "notes": None, "verification": None},
    ]}
    rows = _client(fake).storage_content("pve1", "local", content="iso")
    assert rows[0]["volid"] == "local:iso/debian-12.iso"
    assert fake.last_content_call == ("pve1", "local", "iso")


def test_storage_content_without_a_filter_sends_no_content_kwarg():
    """PVE treats `content=` as a filter; sending content=None would filter on
    the literal string "None" rather than listing everything."""
    fake = FakePVE()
    fake.content_by_storage = {"local": [{"volid": "local:iso/x.iso"}]}
    assert _client(fake).storage_content("pve1", "local") == [{"volid": "local:iso/x.iso"}]
    assert fake.last_content_call == ("pve1", "local", None)


def test_cluster_storage_reads_the_cluster_level_config():
    fake = FakePVE()
    fake.cluster_storage_rows = [{"storage": "nfs-backup", "type": "nfs",
                                  "content": "backup", "shared": 1}]
    assert _client(fake).cluster_storage() == fake.cluster_storage_rows


# --- network reads --------------------------------------------------------

def test_node_networks_lists_every_interface():
    fake = FakePVE()
    fake.networks_by_node = {"pve1": [
        {"iface": "vmbr0", "type": "bridge", "method": "static",
         "cidr": "192.168.1.10/24", "gateway": "192.168.1.1",
         "bridge_ports": "eno1", "active": 1, "autostart": 1},
        {"iface": "eno1", "type": "eth", "method": "manual", "active": 1},
    ]}
    assert [r["iface"] for r in _client(fake).node_networks("pve1")] == ["vmbr0", "eno1"]


def test_node_networks_filters_by_type():
    fake = FakePVE()
    fake.networks_by_node = {"pve1": [
        {"iface": "vmbr0", "type": "bridge"},
        {"iface": "eno1", "type": "eth"},
    ]}
    rows = _client(fake).node_networks("pve1", iface_type="bridge")
    assert [r["iface"] for r in rows] == ["vmbr0"]


# --- guest config + snapshots + nextid ------------------------------------

def test_guest_config_reads_both_lxc_and_qemu():
    fake = FakePVE()
    fake.guest_configs = {
        ("lxc", 150): {"hostname": "immich", "net0": "name=eth0,bridge=vmbr0,ip=dhcp"},
        ("qemu", 201): {"name": "win11", "net0": "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0"},
    }
    c = _client(fake)
    assert c.guest_config("lxc", "pve1", 150)["hostname"] == "immich"
    assert c.guest_config("qemu", "pve1", 201)["name"] == "win11"


def test_snapshots_lists_the_guests_snapshots():
    fake = FakePVE()
    fake.snapshots_by_guest = {("qemu", 201): [
        {"name": "pre-update", "description": "before 24.04", "snaptime": 1,
         "vmstate": 0, "parent": None},
        {"name": "current", "description": "You are here!"},
    ]}
    names = [s["name"] for s in _client(fake).snapshots("qemu", "pve1", 201)]
    assert names == ["pre-update", "current"]


def test_cluster_nextid_returns_an_int():
    """PVE answers /cluster/nextid with a JSON string; every caller wants an int."""
    fake = FakePVE()
    fake.nextid = "205"
    assert _client(fake).cluster_nextid() == 205


def test_a_failing_infra_read_wraps_and_redacts_the_secret():
    """fail=True on a brand-new client fails inside _connect() itself (the
    factory call raises before any leaf is reached), same as every other
    ProxmoxClient method's `fail=True` test in this repo (see
    test_proxmox_console_calls.py::test_termproxy_wraps_and_redacts_secret_on_failure),
    and that path's message never carries the node name, only the address.
    Connect first, then flip `fail`, so the failure happens inside the leaf and
    exercises storages()'s own "on {node}" wrap instead of _connect()'s."""
    fake = FakePVE()
    client = _client(fake)
    client.version()
    fake.fail = True
    with pytest.raises(ProxmoxError) as exc:
        client.storages("pve1")
    assert "sekret" not in str(exc.value)
    assert "pve1" in str(exc.value)


# --- the shared decrypt-then-construct helper -----------------------------

def test_client_for_host_builds_a_client_from_the_stored_token(tmp_path):
    from tests.support import make_app

    fake = FakePVE(version={"version": "8.4.1", "release": "8.4"})
    app = make_app(tmp_path, fake=fake)
    with TestClient(app):
        host_id = _seed_host_with_token(app)
        with app.state.sessionmaker() as db:
            client = client_for_host(app, db, db.get(Host, host_id))
            assert client.version()["release"] == "8.4"
    assert fake.kwargs["user"] == "proxploy@pve"
    assert fake.kwargs["token_name"] == "infra"
    assert fake.kwargs["token_value"] == "s3cret"


def test_client_for_host_raises_when_the_host_has_no_api_token(tmp_path):
    from tests.support import make_app

    app = make_app(tmp_path, fake=FakePVE())
    with TestClient(app):
        with app.state.sessionmaker() as db:
            host = Host(name="bare", address="https://10.0.0.8:8006", node_name="pve1")
            db.add(host)
            db.commit()
            with pytest.raises(ProxmoxError, match="no monitoring API token configured"):
                client_for_host(app, db, host)


def test_consoles_no_longer_carries_its_own_copy_of_the_helper():
    """Root-cause DRY, not a third copy: the duplicate in api/consoles.py is
    deleted outright, so a future reader cannot pick the stale one."""
    from proxploy.api import consoles

    assert not hasattr(consoles, "_proxmox_client_for_host")
    assert consoles.client_for_host is client_for_host
