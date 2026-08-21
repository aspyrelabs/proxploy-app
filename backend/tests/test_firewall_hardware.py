"""Firewall against the real cluster. Excluded from the default run:

    pytest tests/ -m "not pve_integration and not e2e"

What only hardware can answer: whether the narrow lifecycle token can write and
the monitoring token can read, at every scope. Every other test in this feature
passes against tests/fakes/pve.py::make_fake_factory, which returns the SAME
fake object whatever capability token is requested, so no test above this one
can detect a reads-through-the-write-client mistake.

Creates one rule at each of the four scopes, one alias, one IP set with a
member, and one security group (with a rule inside it), then deletes all of
them through try/finally. Never enables a firewall: rules are writable and
readable with the firewall off, and an enabled default-deny policy on a lab
node is a trip to the machine.

Uses the enrolled host's own stored, encrypted credentials from the dev
database (Settings() resolves relative to cwd, so this only works run from
backend/), never PROXPLOY_TEST_PVE_* env vars: those exist for a harness that
hands the SAME token to every capability (tests/livepve.py), which would hide
exactly the asymmetry this file exists to prove.
"""
from __future__ import annotations

import json

import pytest

from proxploy.config import Settings
from proxploy.db import make_engine, make_sessionmaker
from proxploy.models import Host, HostCredential
from proxploy.secretstore import SecretStore
from proxploy.services.firewall import cluster_loc, group_loc, guest_loc, node_loc
from proxploy.services.proxmox import ProxmoxClient, ProxmoxError

pytestmark = pytest.mark.pve_integration

PROBE = "proxploy hardware check"


@pytest.fixture(scope="module")
def rig():
    """(host, monitoring client, lifecycle client), built from the first
    enrolled host's own stored tokens. Skips cleanly rather than erroring when
    the dev database or a token is missing, matching every other
    pve_integration suite in this repo."""
    s = Settings()
    db = make_sessionmaker(make_engine(s))()
    store = SecretStore(s.master_key_file)
    host = db.query(Host).first()
    if host is None:
        pytest.skip("no enrolled host in the dev database")

    def client(capability: str) -> ProxmoxClient:
        cred = db.query(HostCredential).filter_by(
            host_id=host.id, kind=f"api_token:{capability}").one_or_none()
        if cred is None:
            pytest.skip(f"host has no {capability} token configured")
        tok = json.loads(store.decrypt(cred.encrypted_blob))
        return ProxmoxClient(host.address, tok["token_id"], tok["token_secret"],
                             verify_tls=host.verify_tls,
                             tls_fingerprint=host.tls_fingerprint)

    return host, client("monitoring"), client("lifecycle")


@pytest.fixture(scope="module")
def host(rig) -> Host:
    return rig[0]


@pytest.fixture(scope="module")
def monitor(rig) -> ProxmoxClient:
    return rig[1]


@pytest.fixture(scope="module")
def lifecycle(rig) -> ProxmoxClient:
    return rig[2]


@pytest.fixture(scope="module")
def guest(host, monitor) -> dict:
    """An existing lxc container on this host's own node, read through the
    monitoring client since that is the only one that can list them."""
    for row in monitor.cluster_resources():
        if row.get("type") == "lxc" and row.get("node") == host.node_name:
            return row
    pytest.skip(f"no lxc container found on node {host.node_name!r}")


def _delete_matching_rules(monitor, lifecycle, loc) -> None:
    """Deletes every PROBE rule at `loc`, re-reading positions each time since
    a delete shifts every later position. Safe to call with zero matches."""
    while True:
        remaining = [r for r in monitor.firewall_rules(loc) if r.get("comment") == PROBE]
        if not remaining:
            return
        lifecycle.firewall_rule_delete(loc, remaining[0]["pos"])


def _assert_rule_roundtrip(monitor, lifecycle, loc) -> None:
    before = monitor.firewall_rules(loc)
    lifecycle.firewall_rule_create(loc, {"type": "in", "action": "ACCEPT", "comment": PROBE})
    try:
        after = monitor.firewall_rules(loc)
        added = [r for r in after if r.get("comment") == PROBE]
        assert len(added) == 1
        assert len(after) == len(before) + 1
    finally:
        _delete_matching_rules(monitor, lifecycle, loc)
    assert len(monitor.firewall_rules(loc)) == len(before)


def test_rule_cluster_scope(monitor, lifecycle):
    _assert_rule_roundtrip(monitor, lifecycle, cluster_loc())


def test_rule_node_scope(host, monitor, lifecycle):
    _assert_rule_roundtrip(monitor, lifecycle, node_loc(host.node_name))


def test_rule_guest_scope(host, guest, monitor, lifecycle):
    loc = guest_loc(host, "lxc", guest["vmid"])
    _assert_rule_roundtrip(monitor, lifecycle, loc)


def test_group_with_rule(monitor, lifecycle):
    group = "pxphwgroup"
    groups_before = monitor.firewall_groups()
    lifecycle.firewall_group_create({"group": group, "comment": PROBE})
    try:
        groups_after = monitor.firewall_groups()
        assert any(g.get("group") == group for g in groups_after)
        loc = group_loc(group)
        _assert_rule_roundtrip(monitor, lifecycle, loc)
    finally:
        if any(g.get("group") == group for g in monitor.firewall_groups()):
            lifecycle.firewall_group_delete(group)
    assert len(monitor.firewall_groups()) == len(groups_before)


def test_alias(monitor, lifecycle):
    loc = cluster_loc()
    name = "pxphwalias"
    before = monitor.firewall_aliases(loc)
    lifecycle.firewall_alias_create(loc, {"name": name, "cidr": "10.99.99.99/32",
                                          "comment": PROBE})
    try:
        after = monitor.firewall_aliases(loc)
        added = [a for a in after if a.get("name") == name]
        assert len(added) == 1
        assert added[0].get("comment") == PROBE
    finally:
        if any(a.get("name") == name for a in monitor.firewall_aliases(loc)):
            lifecycle.firewall_alias_delete(loc, name)
    assert len(monitor.firewall_aliases(loc)) == len(before)


def test_ipset_member_cidr_with_slash(monitor, lifecycle):
    """The member CIDR is a URL path segment. `firewall_ipset_members` calls
    GET .../ipset/{name} (no member in the path, so nothing to encode there),
    but adding, updating and deleting one member/{cidr} all go through
    ProxmoxClient._segment, which quotes the slash. A CIDR without a
    slash (a bare /32 host) would pass even with that quoting missing, so this
    uses a real subnet to prove it."""
    loc = cluster_loc()
    name = "pxphwipset"
    cidr = "10.99.0.0/16"
    before = monitor.firewall_ipsets(loc)
    lifecycle.firewall_ipset_create(loc, {"name": name, "comment": PROBE})
    try:
        after = monitor.firewall_ipsets(loc)
        assert any(i.get("name") == name for i in after)
        lifecycle.firewall_ipset_member_add(loc, name, {"cidr": cidr, "comment": PROBE})
        members = monitor.firewall_ipset_members(loc, name)
        assert any(m.get("cidr") == cidr for m in members)
    finally:
        if any(i.get("name") == name for i in monitor.firewall_ipsets(loc)):
            lifecycle.firewall_ipset_delete(loc, name, force=True)
    assert len(monitor.firewall_ipsets(loc)) == len(before)


def test_lifecycle_client_cannot_read(lifecycle):
    """Measured on this cluster on 2026-08-21: the lifecycle token writes
    every firewall scope but returns 403 on every read. That asymmetry is why
    services/firewall.py splits readers()/writers() by capability instead of
    using one token for both. If this test ever starts passing, someone has
    widened the lifecycle role's privileges and the two-client split has
    become dead weight worth removing."""
    with pytest.raises(ProxmoxError) as exc:
        lifecycle.firewall_rules(cluster_loc())
    message = str(exc.value)
    assert "VM.Audit" in message or "Sys.Audit" in message
