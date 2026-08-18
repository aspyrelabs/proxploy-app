# backend/proxploy/api/network.py
"""Network reads + guest NIC edit (doc 05 §Network, doc 01 §6).

Doc 05 calls /network/bridges a "live passthrough" and this is exactly that:
no model, no cache, no migration; one GET /nodes/{node}/network per node of
the requested host(s), served straight back. Throughput is the opposite: it is
NOT a passthrough, it comes from the `host` target's existing `net_in_bps` /
`net_out_bps` MetricSample rows the poller has been writing since Phase 2,
read through services/metrics.py::query_series, the same reader
api/metrics.py::metrics_query uses. There is deliberately no second metrics
path in this codebase.

Deviation from doc 05 recorded in the phase notes: doc 05 leaves the
entitlement column blank on both GETs. Doc 01 §6 defines `network.view` as a
real feature with a real key and doc 07 §3 says a feature without a key does
not merge, so both reads are gated on it. Functionally identical today (the
key defaults ON).
"""
from __future__ import annotations

import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from proxploy.api.deps import (authorize, cluster_scope, get_db,
                               require_entitlement, scope_host)
from proxploy.api.jobs import enqueue_and_audit
from proxploy.models import App, Host, User, Vm, utcnow
from proxploy.services.audit import write_audit
from proxploy.services.hostclient import client_for_host, guest_node
from proxploy.services.metrics import pick_resolution, query_series
from proxploy.services.netconfig import build_net, nic_identity, parse_net
from proxploy.services.proxmox import ProxmoxError

router = APIRouter(prefix="/network", tags=["network"])

# Singleton first in dependencies=[...] and reused as the parameter dep, so
# auth runs before the entitlement gate and FastAPI collapses the two
# (deps.py idiom; test_route_auth_invariant.py enforces it). Both reads below
# take `host` as a query param, not a path param, so there is nothing for
# scope_host() to resolve: global, same as before this had a scope.
_read = authorize("network", "read")

NET_KEY = re.compile(r"^net\d+$")


class NicIn(BaseModel):
    """Every field optional; only fields PRESENT in the request body are
    applied, and an explicit null removes the key (that is how a VLAN tag or a
    rate limit is cleared). Absent != null here, hence exclude_unset below."""
    bridge: str | None = None
    tag: int | None = None
    firewall: bool | None = None
    rate: float | None = None
    mtu: int | None = None
    link_down: bool | None = None


def _nic_out(iface: str, raw: str) -> dict:
    parts = parse_net(raw)
    return {
        "iface": iface, "raw": raw, **nic_identity(parts),
        "bridge": parts.get("bridge"),
        "tag": int(parts["tag"]) if parts.get("tag") else None,
        "firewall": parts.get("firewall") == "1",
        "rate": parts.get("rate"), "mtu": parts.get("mtu"),
        "link_down": parts.get("link_down") == "1",
    }


def guest_nics(request: Request, db, host: Host, kind: str, vmid: int,
               row=None) -> list[dict]:
    """Every netN on one guest, newest PVE config read (no cache).

    `row` is the App or Vm being read, and it is what supplies the guest's own
    node: on a cluster the host's node is the wrong one for a mirrored VM
    (see services/hostclient.py::guest_node).
    """
    try:
        cfg = client_for_host(request.app, db, host).guest_config(
            kind, guest_node(host, row), vmid)
    except ProxmoxError as e:
        raise HTTPException(502, str(e))
    return [_nic_out(k, str(cfg[k])) for k in sorted(cfg) if NET_KEY.match(k)]


def set_guest_nic(request: Request, db, user: User, *, target_type: str,
                  target_id: int, host: Host, kind: str, vmid: int,
                  iface: str, body: NicIn, row=None) -> dict:
    """Read-modify-write one netN. NOT a job, see ProxmoxClient.guest_config_update.

    TWO clients, and the split is load-bearing. The read half
    (`guest_config`) needs monitoring's VM.Audit; the write half
    (`guest_config_update`) needs VM.Config.Network, a lifecycle privilege.
    Neither role carries the other's, so running both halves through one
    client 403s whichever half that client is not entitled to.

    This used to run both on the lifecycle client, on the reasoning that the
    write is the privileged half. Against a real narrow token that fails at the
    READ, before anything is even attempted on the guest:
    `403 (/vms/100, VM.Audit)`, PVE 9.2.10, 2026-08-18 (doc 12 check 18).
    Reads on monitoring is what services/migrate.py already does and monitoring
    is the one capability every enrolled host is guaranteed to have, so this
    also needs no token regenerated.
    """
    if not NET_KEY.match(iface):
        raise HTTPException(422, "iface must look like net0")
    node = guest_node(host, row)
    ip = request.client.host if request.client else None
    try:
        client = client_for_host(request.app, db, host, capability="lifecycle")
        cfg = client_for_host(request.app, db, host,
                              capability="monitoring").guest_config(kind, node, vmid)
    except ProxmoxError as e:
        # A DIFFERENT action from the two below, and the reason is the whole
        # point of an audit log: nothing has been sent to the guest at this
        # point. This is the read half of the read-modify-write failing, so
        # the operator reading the log must not see a row that says a network
        # configuration was attempted on that guest. Same identifier for both
        # halves is what made a plain unreachable-host read look like a
        # half-applied NIC change.
        write_audit(db, actor_type="user", actor_id=user.id,
                    action="network.guest_config_read",
                    target_type=target_type, target_id=target_id,
                    params={"iface": iface}, result="error", ip=ip)
        raise HTTPException(502, str(e))
    if iface not in cfg:
        raise HTTPException(404, f"{iface} is not configured on this guest")
    parts = parse_net(str(cfg[iface]))
    changes = body.model_dump(exclude_unset=True)
    for key, val in changes.items():
        if val is None:
            parts.pop(key, None)
        elif isinstance(val, bool):
            parts[key] = "1" if val else "0"
        else:
            parts[key] = str(val)
    value = build_net(parts)
    try:
        upid = client.guest_config_update(kind, node, vmid, {iface: value})
    except ProxmoxError as e:
        write_audit(db, actor_type="user", actor_id=user.id, action="network.guest_config",
                    target_type=target_type, target_id=target_id,
                    params={"iface": iface, **changes}, result="error", ip=ip)
        raise HTTPException(502, str(e))
    write_audit(db, actor_type="user", actor_id=user.id, action="network.guest_config",
                target_type=target_type, target_id=target_id,
                params={"iface": iface, **changes}, ip=ip)
    return {
        "iface": iface, "value": value, "upid": upid,
        "pending_reboot": upid is not None,
        # Honest, not reassuring: PVE handed back a UPID, which for a config
        # write means it filed the change under the guest's PENDING section.
        # The running guest still has the old NIC.
        "detail": ("Proxmox recorded this as a pending change, the guest keeps its "
                   "current NIC until it is rebooted (a shutdown/start, not a reset)."
                   if upid is not None else
                   "Applied immediately; no reboot needed."),
    }


def _nodes_of(request: Request, host: Host) -> list[str]:
    snap = request.app.state.poller.snapshots.get(host.id)
    names = [n["node"] for n in (snap.nodes if snap else []) if n.get("node")]
    return names or ([host.node_name] if host.node_name else [])


def _iface_out(row: dict) -> dict:
    return {
        "iface": row.get("iface"), "type": row.get("type"),
        "method": row.get("method"), "address": row.get("address"),
        "netmask": row.get("netmask"), "cidr": row.get("cidr"),
        "gateway": row.get("gateway"), "bridge_ports": row.get("bridge_ports"),
        "slaves": row.get("slaves"),
        "vlan_aware": bool(row.get("bridge_vlan_aware")),
        "vlan_id": row.get("vlan-id"), "vlan_raw_device": row.get("vlan-raw-device"),
        "active": bool(row.get("active")), "autostart": bool(row.get("autostart")),
        "comments": row.get("comments"),
    }


@router.get("/bridges", dependencies=[Depends(_read),
                                      Depends(require_entitlement("network.view"))])
def list_bridges(request: Request, host: int | None = None, db=Depends(get_db),
                 user: User = Depends(_read)):
    """Bridges/bonds/VLANs/physical NICs per node + the guest attachment map.

    # ponytail: the attachment map costs one guest_config read per adopted app
    # and VM on the host: fine for a homelab, linear in guest count for a
    # 200-guest fleet. This is a human-triggered route, explicitly outside the
    # poller's O(nodes) budget (proxmox.py's "per-guest, user-triggered calls"
    # section). If it ever gets slow, cache netN in the poller's cluster_resources
    # pass; do not add per-guest calls to the poll loop to get it.

    One bad host (unreachable, or missing its API token credential; a
    routine state, not an outage) must not 500 the whole page: it is degraded
    out into `errors` and every other host is still served.
    """
    all_hosts = db.query(Host).order_by(Host.name).all()
    hosts = [h for h in all_hosts if host is None or h.id == host]
    # Two Hosts can be two nodes of the SAME cluster; _nodes_of reads
    # snap.nodes, and cluster_resources() returns the whole cluster from
    # either one (see pollers/__init__.py), so both snapshots list both
    # nodes. `owner_by_node` is built from every registered host, not just
    # the ones in scope for this request, so a real node's interfaces are
    # reported once, attributed to the host actually registered at that
    # node, regardless of the ?host= filter. Keyed on cluster_scope(h) too:
    # a node name is only unique WITHIN a cluster, so a same-named node on a
    # different cluster (or another standalone host) must not be merged in.
    owner_by_node = {(cluster_scope(h), h.node_name): h
                     for h in all_hosts if h.node_name}
    nodes, attachments, errors = [], [], []
    reported_nodes: set[tuple] = set()
    for h in hosts:
        try:
            client = client_for_host(request.app, db, h)
            scope = cluster_scope(h)
            for node in _nodes_of(request, h):
                key = (scope, node)
                if key in reported_nodes:
                    continue
                reported_nodes.add(key)
                owner = owner_by_node.get(key, h)
                nodes.append({"host_id": owner.id, "host_name": owner.name, "node": node,
                              "interfaces": [_iface_out(r) for r in client.node_networks(node)]})
            node = h.node_name or ""
            guests = ([("app", a.id, a.name, "lxc", a.ctid)
                       for a in db.query(App).filter_by(host_id=h.id).order_by(App.name)]
                      + [("vm", v.id, v.name, "qemu", v.vmid)
                         for v in db.query(Vm).filter_by(host_id=h.id).order_by(Vm.name)])
            for gtype, gid, gname, kind, vmid in guests:
                cfg = client.guest_config(kind, node, vmid)
                for key in sorted(k for k in cfg if NET_KEY.match(k)):
                    attachments.append({"host_id": h.id, "node": node,
                                        "guest_type": gtype, "guest_id": gid,
                                        "name": gname, "vmid": vmid,
                                        **_nic_out(key, str(cfg[key]))})
        except ProxmoxError as e:
            errors.append({"host_id": h.id, "host_name": h.name, "error": str(e)})
    return {"nodes": nodes, "attachments": attachments, "errors": errors}


@router.get("/throughput", dependencies=[Depends(_read),
                                         Depends(require_entitlement("network.view"))])
def throughput(request: Request, hours: int = 1, db=Depends(get_db),
               user: User = Depends(_read)):
    """Per-host in/out series from the MetricsStore rows the poller already writes.

    Same reader as /metrics/query (services/metrics.py::query_series); this
    endpoint only exists so the Network page can ask for both metrics across
    every host in one round trip instead of 2N.
    """
    if not 1 <= hours <= 48:
        raise HTTPException(422, "hours must be between 1 and 48")
    to_dt = utcnow()
    frm_dt = to_dt - timedelta(hours=hours)
    res = pick_resolution(frm_dt, to_dt)
    out = []
    for h in db.query(Host).order_by(Host.name).all():
        out.append({
            "host_id": h.id, "host_name": h.name,
            "in": query_series(db, "host", h.id, "net_in_bps", frm_dt, to_dt, res),
            "out": query_series(db, "host", h.id, "net_out_bps", frm_dt, to_dt, res),
        })
    return {"hours": hours, "resolution": res, "hosts": out}


# create_bridge's host_id is body-carried (no id in the path yet), so it stays
# global-domain, mirroring apps.py catalog install's ponytail comment. The
# other three host-config mutations all carry host_id in the path.
_host_global = authorize("network", "host")
_host = authorize("network", "host", scope_of=scope_host())

# PVE option names are lowercase words with dashes/underscores and digits.
# The config dict is unpacked straight into a proxmoxer kwargs call, so the
# key space is a trust boundary even though the values are PVE's problem.
_SAFE_KEY = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def _check_config(config: dict) -> dict:
    bad = [k for k in config if not _SAFE_KEY.match(str(k))]
    if bad:
        raise HTTPException(422, f"unsupported network option(s): {', '.join(map(str, bad))}")
    return config


def _host_or_404(db, host_id: int) -> Host:
    host = db.get(Host, host_id)
    if host is None:
        raise HTTPException(404, "host not found")
    return host


class BridgeIn(BaseModel):
    host_id: int
    node: str
    iface: str
    type: str = "bridge"
    config: dict = Field(default_factory=dict)


class BridgePatchIn(BaseModel):
    config: dict = Field(default_factory=dict)


class ApplyIn(BaseModel):
    confirm: str | None = None


# Every route below stages or promotes /etc/network/interfaces.new.
#
# ponytail: Proxploy does not detect whether staged changes exist, so Apply and
# Revert are always offered rather than enabled-when-dirty. PVE reports pending
# state as a `changes` property SIBLING to `data` on GET /nodes/{node}/network,
# and proxmoxer's .get() unwraps `data` and throws the rest away: reading it
# would mean bypassing the client layer, which proxmox.py's module docstring
# forbids outright. A no-op apply is handled gracefully by PVE (it reloads the
# unchanged config), so the cost of not knowing is one wasted ifreload.
# Upgrade path: a raw-response accessor on ProxmoxClient if the UI ever needs a
# "you have unsaved changes" badge.


@router.post("/bridges", status_code=201,
             dependencies=[Depends(_host_global),
                           Depends(require_entitlement("network.host_config"))])
def create_bridge(request: Request, body: BridgeIn, db=Depends(get_db),
                  user: User = Depends(_host_global)):
    host = _host_or_404(db, body.host_id)
    # Route-controlled keys (iface/type) go LAST in the unpack so a
    # caller-supplied config.iface or config.type: both admitted by
    # _SAFE_KEY: can never override what this route says it is staging.
    cfg = {**_check_config(body.config), "iface": body.iface, "type": body.type}
    ip = request.client.host if request.client else None
    try:
        client_for_host(request.app, db, host, capability="lifecycle").network_create(body.node, cfg)
    except ProxmoxError as e:
        write_audit(db, actor_type="user", actor_id=user.id, action="network.host_config",
                    target_type="host", target_id=host.id,
                    params={"op": "create", "node": body.node, "iface": body.iface,
                            "config": body.config}, result="error", ip=ip)
        raise HTTPException(502, str(e))
    write_audit(db, actor_type="user", actor_id=user.id, action="network.host_config",
                target_type="host", target_id=host.id,
                params={"op": "create", "node": body.node, "iface": body.iface,
                        "config": body.config}, ip=ip)
    return {"staged": True, "node": body.node, "iface": body.iface}


@router.put("/bridges/{host_id}/{node}/{iface}",
            dependencies=[Depends(_host),
                          Depends(require_entitlement("network.host_config"))])
def update_bridge(request: Request, host_id: int, node: str, iface: str,
                  body: BridgePatchIn, db=Depends(get_db),
                  user: User = Depends(_host)):
    host = _host_or_404(db, host_id)
    ip = request.client.host if request.client else None
    try:
        client_for_host(request.app, db, host, capability="lifecycle").network_update(
            node, iface, _check_config(body.config))
    except ProxmoxError as e:
        write_audit(db, actor_type="user", actor_id=user.id, action="network.host_config",
                    target_type="host", target_id=host.id,
                    params={"op": "update", "node": node, "iface": iface,
                            "config": body.config}, result="error", ip=ip)
        raise HTTPException(502, str(e))
    write_audit(db, actor_type="user", actor_id=user.id, action="network.host_config",
                target_type="host", target_id=host.id,
                params={"op": "update", "node": node, "iface": iface,
                        "config": body.config}, ip=ip)
    return {"staged": True, "node": node, "iface": iface}


@router.delete("/bridges/{host_id}/{node}/{iface}",
               dependencies=[Depends(_host),
                             Depends(require_entitlement("network.host_config"))])
def delete_bridge(request: Request, host_id: int, node: str, iface: str,
                  db=Depends(get_db), user: User = Depends(_host)):
    host = _host_or_404(db, host_id)
    ip = request.client.host if request.client else None
    try:
        client_for_host(request.app, db, host, capability="lifecycle").network_delete(node, iface)
    except ProxmoxError as e:
        write_audit(db, actor_type="user", actor_id=user.id, action="network.host_config",
                    target_type="host", target_id=host.id,
                    params={"op": "delete", "node": node, "iface": iface},
                    result="error", ip=ip)
        raise HTTPException(502, str(e))
    write_audit(db, actor_type="user", actor_id=user.id, action="network.host_config",
                target_type="host", target_id=host.id,
                params={"op": "delete", "node": node, "iface": iface}, ip=ip)
    return {"staged": True, "node": node, "iface": iface}


@router.post("/{host_id}/{node}/apply", status_code=202,
             dependencies=[Depends(_host),
                           Depends(require_entitlement("network.host_config"))])
def apply_network(request: Request, host_id: int, node: str, body: ApplyIn,
                  db=Depends(get_db), user: User = Depends(_host)):
    """Promote the staged config. Typed confirmation required.

    Doc 08 §1's typed-name guardrail, reused verbatim from selfguard's
    self_target shape so the frontend has one confirm dialog, not two. The
    phrase is the NODE NAME because the node is what is at risk: `ifreload -a`
    with a broken bridge takes the node off the network until someone reaches
    its physical console. Unlike a stopped CT this has no in-band undo.
    """
    host = _host_or_404(db, host_id)
    ip = request.client.host if request.client else None
    if (body.confirm or "") != node:
        write_audit(db, actor_type="user", actor_id=user.id, action="network.apply",
                    target_type="host", target_id=host.id,
                    params={"node": node}, result="denied", ip=ip)
        raise HTTPException(409, {
            "error": "confirm_required", "confirm_phrase": node,
            "detail": (f"Applying the staged network config reloads {node}'s "
                       f"interfaces. If the staged bridge is wrong, {node} loses "
                       f"its network and can only be recovered from its physical "
                       f"console. Type the node name to confirm."),
        })
    return enqueue_and_audit(request, db, user, kind="network.apply",
                             target_type="host", target_id=host.id,
                             params={"host_id": host.id, "node": node},
                             action="network.apply")


@router.post("/{host_id}/{node}/revert",
             dependencies=[Depends(_host),
                           Depends(require_entitlement("network.host_config"))])
def revert_network(request: Request, host_id: int, node: str, db=Depends(get_db),
                   user: User = Depends(_host)):
    """Discard /etc/network/interfaces.new. No confirmation and no job: this
    deletes a staged file and cannot disturb the running config."""
    host = _host_or_404(db, host_id)
    ip = request.client.host if request.client else None
    try:
        client_for_host(request.app, db, host, capability="lifecycle").network_revert(node)
    except ProxmoxError as e:
        write_audit(db, actor_type="user", actor_id=user.id, action="network.revert",
                    target_type="host", target_id=host.id, params={"node": node},
                    result="error", ip=ip)
        raise HTTPException(502, str(e))
    write_audit(db, actor_type="user", actor_id=user.id, action="network.revert",
                target_type="host", target_id=host.id, params={"node": node}, ip=ip)
    return {"reverted": True, "node": node}
