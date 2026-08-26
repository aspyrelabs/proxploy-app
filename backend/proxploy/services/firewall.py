"""Firewall scope resolution and client selection.

Four scopes (cluster, node, guest, security group) share one rule schema, so
they share one set of client methods and differ only in the location dict built
here. Nothing in this module imports FastAPI: the API layer decides who may ask
for a scope, this module decides what that scope points at.
"""
from __future__ import annotations

from proxploy.models import Host
from proxploy.services.hostclient import (client_for_host, cluster_scope,
                                          guest_node)
from proxploy.services.proxmox import ProxmoxError

# Which objects each scope actually carries, measured on pve-manager 9.2.11 on
# 2026-08-21 rather than assumed. Used to answer 404 for a scope/object pair
# that does not exist, instead of relaying PVE's 501 as a 502 and making a
# design fact look like an outage.
SCOPE_OBJECTS: dict[str, frozenset[str]] = {
    "cluster": frozenset({"rules", "options", "aliases", "ipsets", "groups",
                          "refs", "macros"}),
    "node": frozenset({"rules", "options", "log"}),
    "guest": frozenset({"rules", "options", "aliases", "ipsets", "refs", "log"}),
    # A security group holds rules and nothing else: PVE documents
    # GET /cluster/firewall/groups/{group} as "List rules".
    "group": frozenset({"rules"}),
}


def cluster_loc() -> dict:
    return {"kind": "cluster"}


def node_loc(node: str) -> dict:
    return {"kind": "node", "node": node}


def group_loc(group: str) -> dict:
    return {"kind": "group", "group": group}


def host_speaks_for_node(app, db, host: Host, node: str) -> bool:
    """May this host act on `node`'s own firewall?

    Its own node, always. Any OTHER node only if the host's last poll actually
    saw it and no other enrolled host is registered at it: a node somebody else
    enrolled as their host is that host's (and that host's team's), and reaching
    it through this one would walk straight past the team check, which is done
    on the Host row and never on the node named in the path.

    Answered from the poll snapshot and the hosts table, so a node request
    normally costs no extra call to Proxmox (see nodes_seen for the one case
    that does).

    Keyed on cluster_scope for the reason that helper exists: a node name is
    unique only WITHIN a cluster, so a same-named node on another cluster is a
    different machine and must not decide this.
    """
    if node == host.node_name:
        return True
    if node not in nodes_seen(app, db, host):
        return False
    scope = cluster_scope(host)
    owners = db.query(Host).filter(Host.node_name == node).all()
    return not any(h.id != host.id and cluster_scope(h) == scope for h in owners)


def nodes_seen(app, db, host: Host) -> set[str]:
    """Every node name this host's cluster reports, from the poll snapshot if
    there is one and from one live /cluster/resources if there is not.

    The fallback is not belt and braces, it closes a measured hole. The
    snapshot is empty for a whole poll interval after every backend start, and
    without this a peer node's firewall answered 404 for that entire window:
    measured against the lab cluster on 2026-08-22, where node2 was refused
    through node1's host until the first poll landed, which is a page that
    worked before this check existed going blank after a restart.

    So: one call, only on a cache miss, never on the hot path. A poll fills the
    snapshot within a cycle and this stops firing. It is also the same question
    the poller asks, so a miss cannot answer differently from a hit.

    A probe that fails answers "no node", never "every node": the host being
    unreachable is not a reason to widen what a caller may write, and the
    firewall call behind it would fail anyway.
    """
    poller = getattr(app.state, "poller", None)
    snap = poller.snapshots.get(host.id) if poller else None
    if snap and snap.nodes:
        return {n["node"] for n in snap.nodes}
    try:
        return {r["node"] for r in readers(app, db, host).cluster_resources()
                if r.get("type") == "node" and r.get("node")}
    except ProxmoxError:
        return set()


def guest_loc(host: Host, kind: str, vmid: int, row=None) -> dict:
    """`kind` is PVE's own word: "lxc" for a container, "qemu" for a VM.

    The node comes from guest_node(), never from host.node_name: on a cluster
    every polled host mirrors every guest, so the host's own entry node reaches
    the wrong machine for every guest but the ones it actually owns, and PVE
    answers 500 with a missing config path.
    """
    return {"kind": "guest", "node": guest_node(host, row),
            "guest_kind": kind, "vmid": int(vmid)}


def readers(app, db, host: Host):
    """Every firewall READ. The lifecycle token cannot do these: measured on
    2026-08-21, it returns 403 (/vms/100, VM.Audit), 403 (/nodes/node1,
    Sys.Audit) and 403 (/, Sys.Audit) while writing all three scopes happily.
    Monitoring is also the one capability every enrolled host is guaranteed to
    have, so this needs no token regenerated anywhere."""
    return client_for_host(app, db, host, capability="monitoring")


def writers(app, db, host: Host):
    """Every firewall WRITE. Needs Sys.Modify at cluster and node scope and
    VM.Config.Network at guest scope, which is exactly what the lifecycle
    capability already carries (services/pveum.py)."""
    return client_for_host(app, db, host, capability="lifecycle")
