"""Firewall path resolution and the two call-shape traps (spec: 2026-08-21)."""
import pytest

from proxploy.services.proxmox import ProxmoxClient, ProxmoxError
from tests.fakes.pve import FakePVE


def _client(fake):
    return ProxmoxClient("https://10.0.0.9:8006", "proxploy@pve!t", "s3cret",
                         factory=lambda **kw: fake)


def test_cluster_scope_resolves_to_cluster_firewall():
    fake = FakePVE()
    c = _client(fake)
    root = c._firewall_root({"kind": "cluster"})
    assert root is fake.cluster.firewall


def test_group_scope_rules_node_is_the_group_itself():
    """PVE documents GET /cluster/firewall/groups/{g} as 'List rules', so the
    group node IS the rule list. Every other scope hangs rules off .rules."""
    fake = FakePVE()
    c = _client(fake)
    node = c._rules_node({"kind": "group", "group": "web"})
    assert node.path == "cluster/firewall/groups/web"


def test_node_scope_rules_node_hangs_off_rules():
    fake = FakePVE()
    c = _client(fake)
    node = c._rules_node({"kind": "node", "node": "pve1"})
    assert node.path == "nodes/pve1/firewall/rules"


def test_guest_scope_uses_guest_kind_and_vmid():
    fake = FakePVE()
    c = _client(fake)
    node = c._rules_node({"kind": "guest", "node": "pve1",
                          "guest_kind": "lxc", "vmid": 150})
    assert node.path == "nodes/pve1/lxc/150/firewall/rules"


def test_unknown_scope_raises_proxmox_error():
    c = _client(FakePVE())
    with pytest.raises(ProxmoxError):
        c._firewall_root({"kind": "wat"})
