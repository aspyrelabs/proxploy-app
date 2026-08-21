"""Firewall scope resolution and client selection.

Four scopes (cluster, node, guest, security group) share one rule schema, so
they share one set of client methods and differ only in the location dict built
here. Nothing in this module imports FastAPI: the API layer decides who may ask
for a scope, this module decides what that scope points at.

Spec: docs/superpowers/specs/2026-08-21-firewall-design.md
"""
from __future__ import annotations

from proxploy.models import Host
from proxploy.services.hostclient import client_for_host, guest_node

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
