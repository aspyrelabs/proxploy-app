"""netN= round-tripping (doc 01 §6 guest network config).

The MAC lives in the head token — `virtio=AA:BB:CC:DD:EE:FF` — so a parser
that keeps only the keys it understands and rebuilds from those loses it.
These are the strings PVE actually emits; every one must survive
build_net(parse_net(s)) == s exactly.
"""
import pytest

from proxploy.services.netconfig import build_net, nic_identity, parse_net

REAL_WORLD = [
    # plain qemu virtio NIC
    "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0",
    # VLAN-tagged + firewalled
    "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0,tag=10,firewall=1",
    # intel model, rate limited, jumbo frames
    "e1000=DE:AD:BE:EF:00:01,bridge=vmbr1,rate=12.5,mtu=9000",
    # multiqueue + admin-down link
    "virtio=52:54:00:12:34:56,bridge=vmbr0,queues=8,link_down=1",
    # every awkward key at once, in PVE's own order
    "vmxnet3=00:0C:29:AB:CD:EF,bridge=vmbr2,tag=4094,firewall=0,"
    "mtu=1400,rate=1,queues=4,link_down=0",
    # lxc shape: no model=MAC head token at all
    "name=eth0,bridge=vmbr0,firewall=1,hwaddr=BC:24:11:00:11:22,ip=dhcp,type=veth",
    # lxc with a static v4 + v6 and a gateway (colons and slashes in values)
    "name=eth0,bridge=vmbr0,hwaddr=BC:24:11:AA:BB:CC,ip=10.0.0.9/24,"
    "gw=10.0.0.1,ip6=fd00::9/64,type=veth",
]


@pytest.mark.parametrize("s", REAL_WORLD)
def test_round_trip_is_byte_for_byte(s):
    assert build_net(parse_net(s)) == s


@pytest.mark.parametrize("s", REAL_WORLD)
def test_round_trip_is_idempotent(s):
    once = build_net(parse_net(s))
    assert build_net(parse_net(once)) == once


def test_head_token_carries_the_mac_and_is_never_regenerated():
    parts = parse_net("virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0,tag=10")
    assert parts["virtio"] == "AA:BB:CC:DD:EE:FF"
    # editing an unrelated key must not disturb it
    parts["tag"] = "20"
    assert build_net(parts) == "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0,tag=20"


def test_unknown_keys_survive_an_edit():
    """A future PVE release adding `foo=bar` must not lose it on a bridge change."""
    parts = parse_net("virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0,foo=bar,queues=4")
    parts["bridge"] = "vmbr9"
    assert build_net(parts) == "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr9,foo=bar,queues=4"


def test_key_order_is_preserved_not_sorted():
    s = "virtio=AA:BB:CC:DD:EE:FF,tag=10,bridge=vmbr0"
    assert build_net(parse_net(s)) == s  # would fail if the dict were sorted


def test_valueless_token_survives():
    """PVE has emitted bare flags before; a bare token must not become `k=`."""
    assert build_net(parse_net("virtio=AA:BB:CC:DD:EE:FF,trunks")) == \
        "virtio=AA:BB:CC:DD:EE:FF,trunks"


def test_nic_identity_reads_qemu_and_lxc_shapes():
    q = nic_identity(parse_net("virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0"))
    assert q == {"model": "virtio", "macaddr": "AA:BB:CC:DD:EE:FF"}
    c = nic_identity(parse_net("name=eth0,bridge=vmbr0,hwaddr=BC:24:11:00:11:22,type=veth"))
    assert c == {"model": "veth", "macaddr": "BC:24:11:00:11:22"}
