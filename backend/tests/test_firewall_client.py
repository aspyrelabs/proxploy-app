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


CLUSTER = {"kind": "cluster"}
GROUP = {"kind": "group", "group": "web"}


def test_rules_read_returns_what_pve_gave():
    fake = FakePVE()
    fake.firewall_data["cluster/firewall/rules"] = [
        {"pos": 0, "type": "in", "action": "ACCEPT", "enable": 1},
    ]
    assert _client(fake).firewall_rules(CLUSTER)[0]["action"] == "ACCEPT"


def test_rule_create_posts_to_the_rules_node():
    fake = FakePVE()
    _client(fake).firewall_rule_create(
        CLUSTER, {"type": "in", "action": "ACCEPT", "proto": "tcp", "dport": "22"})
    verb, path, params = fake.firewall_writes[0]
    assert (verb, path) == ("post", "cluster/firewall/rules")
    assert params["dport"] == "22"


def test_group_rule_create_posts_to_the_group_itself():
    fake = FakePVE()
    _client(fake).firewall_rule_create(GROUP, {"type": "in", "action": "DROP"})
    verb, path, _ = fake.firewall_writes[0]
    assert (verb, path) == ("post", "cluster/firewall/groups/web")


def test_icmp_type_survives_as_a_hyphenated_key():
    """`icmp-type` is not a valid Python identifier, so it can only travel as a
    dict key. A method signature naming it, or any snake_case translation on
    the way through, silently drops the field."""
    fake = FakePVE()
    _client(fake).firewall_rule_create(
        CLUSTER, {"type": "in", "action": "ACCEPT", "proto": "icmp",
                  "icmp-type": "echo-request"})
    _, _, params = fake.firewall_writes[0]
    assert params["icmp-type"] == "echo-request"


def test_rule_move_sends_moveto_and_nothing_else():
    """PVE: 'Move rule to new position. Other arguments are ignored.' Sending
    the rest alongside it reads as an edit that silently did not happen."""
    fake = FakePVE()
    _client(fake).firewall_rule_move(CLUSTER, 3, 1, digest="abc")
    verb, path, params = fake.firewall_writes[0]
    assert (verb, path) == ("put", "cluster/firewall/rules/3")
    assert params == {"moveto": 1, "digest": "abc"}


def test_rule_delete_carries_the_digest():
    fake = FakePVE()
    _client(fake).firewall_rule_delete(CLUSTER, 2, digest="abc")
    verb, path, params = fake.firewall_writes[0]
    assert (verb, path) == ("delete", "cluster/firewall/rules/2")
    assert params == {"digest": "abc"}


def test_rule_delete_without_a_digest_sends_no_digest_key():
    """None must not travel as digest=None: PVE would compare against the
    string 'None' and refuse every delete."""
    fake = FakePVE()
    _client(fake).firewall_rule_delete(CLUSTER, 2, digest=None)
    assert fake.firewall_writes[0][2] == {}


def test_unreachable_pve_becomes_a_proxmox_error():
    fake = FakePVE(fail=True)
    with pytest.raises(ProxmoxError):
        _client(fake).firewall_rules(CLUSTER)


GUEST = {"kind": "guest", "node": "pve1", "guest_kind": "lxc", "vmid": 150}


def test_options_read_and_write():
    fake = FakePVE()
    fake.firewall_data["cluster/firewall/options"] = {"enable": 1, "digest": "d1"}
    c = _client(fake)
    assert c.firewall_options(CLUSTER)["enable"] == 1
    c.firewall_options_update(CLUSTER, {"policy_in": "DROP", "digest": "d1"})
    verb, path, params = fake.firewall_writes[0]
    assert (verb, path) == ("put", "cluster/firewall/options")
    assert params == {"policy_in": "DROP", "digest": "d1"}


def test_alias_lifecycle_paths():
    fake = FakePVE()
    c = _client(fake)
    c.firewall_alias_create(CLUSTER, {"name": "office", "cidr": "10.0.0.0/24"})
    c.firewall_alias_update(CLUSTER, "office", {"cidr": "10.0.1.0/24"})
    c.firewall_alias_delete(CLUSTER, "office", digest="d1")
    assert [(v, p) for v, p, _ in fake.firewall_writes] == [
        ("post", "cluster/firewall/aliases"),
        ("put", "cluster/firewall/aliases/office"),
        ("delete", "cluster/firewall/aliases/office"),
    ]


def test_ipset_member_cidr_is_percent_encoded_in_the_path():
    """The member's CIDR is a path segment, so its slash must be escaped or
    PVE routes the call somewhere else entirely and answers 404."""
    fake = FakePVE()
    _client(fake).firewall_ipset_member_delete(
        GUEST, "trusted", "10.0.0.0/8", digest=None)
    _, path, _ = fake.firewall_writes[0]
    assert path == "nodes/pve1/lxc/150/firewall/ipset/trusted/10.0.0.0%2F8"


def test_ipset_member_add_posts_to_the_set_not_the_member():
    fake = FakePVE()
    _client(fake).firewall_ipset_member_add(
        GUEST, "trusted", {"cidr": "10.0.0.5", "nomatch": 1})
    verb, path, params = fake.firewall_writes[0]
    assert (verb, path) == ("post", "nodes/pve1/lxc/150/firewall/ipset/trusted")
    assert params["nomatch"] == 1


def test_ipset_delete_passes_force():
    fake = FakePVE()
    _client(fake).firewall_ipset_delete(CLUSTER, "trusted", force=True, digest=None)
    _, path, params = fake.firewall_writes[0]
    assert path == "cluster/firewall/ipset/trusted"
    assert params == {"force": 1}


def test_group_create_and_delete_are_cluster_paths():
    fake = FakePVE()
    c = _client(fake)
    c.firewall_group_create({"group": "web", "comment": "public"})
    c.firewall_group_delete("web", digest=None)
    assert [(v, p) for v, p, _ in fake.firewall_writes] == [
        ("post", "cluster/firewall/groups"),
        ("delete", "cluster/firewall/groups/web"),
    ]


def test_refs_filters_by_type_when_asked():
    fake = FakePVE()
    _client(fake).firewall_refs(CLUSTER, ref_type="ipset")
    path, params = fake.firewall_reads[0]
    assert path == "cluster/firewall/refs"
    assert params == {"type": "ipset"}


def test_log_passes_the_line_cursor_and_time_bounds():
    fake = FakePVE()
    fake.firewall_data["nodes/pve1/firewall/log"] = [{"n": 1, "t": "line one"}]
    rows = _client(fake).firewall_log({"kind": "node", "node": "pve1"},
                                      start=10, limit=50, since=1700000000,
                                      until=None)
    assert rows[0]["t"] == "line one"
    _, params = fake.firewall_reads[0]
    assert params == {"start": 10, "limit": 50, "since": 1700000000}
