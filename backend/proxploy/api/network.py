# backend/proxploy/api/network.py
"""Network reads + guest NIC edit (doc 05 §Network, doc 01 §6).

Doc 05 calls /network/bridges a "live passthrough" and this is exactly that:
no model, no cache, no migration — one GET /nodes/{node}/network per node of
the requested host(s), served straight back. Throughput is the opposite: it is
NOT a passthrough, it comes from the `host` target's existing `net_in_bps` /
`net_out_bps` MetricSample rows the poller has been writing since Phase 2,
read through services/metrics.py::query_series — the same reader
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
from pydantic import BaseModel

from proxploy.api.deps import get_db, require_entitlement, require_role
from proxploy.models import App, Host, User, Vm, utcnow
from proxploy.services.audit import write_audit
from proxploy.services.hostclient import client_for_host
from proxploy.services.metrics import pick_resolution, query_series
from proxploy.services.netconfig import build_net, nic_identity, parse_net

router = APIRouter(prefix="/network", tags=["network"])

# Singletons first in dependencies=[...] and reused as the parameter dep, so
# auth/role runs before the entitlement gate and FastAPI collapses the two
# (deps.py idiom; test_route_auth_invariant.py enforces it).
_require_viewer = require_role("viewer")
_require_operator = require_role("operator")

NET_KEY = re.compile(r"^net\d+$")

# Keys a NIC edit may touch. The head token (model=MAC) and everything else in
# the string is passed through untouched by netconfig — see that module.
EDITABLE = ("bridge", "tag", "firewall", "rate", "mtu", "link_down")


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


def guest_nics(request: Request, db, host: Host, kind: str, vmid: int) -> list[dict]:
    """Every netN on one guest, newest PVE config read (no cache)."""
    cfg = client_for_host(request.app, db, host).guest_config(kind, host.node_name or "", vmid)
    return [_nic_out(k, str(cfg[k])) for k in sorted(cfg) if NET_KEY.match(k)]


def set_guest_nic(request: Request, db, user: User, *, target_type: str,
                  target_id: int, host: Host, kind: str, vmid: int,
                  iface: str, body: NicIn) -> dict:
    """Read-modify-write one netN. NOT a job — see ProxmoxClient.guest_config_update."""
    if not NET_KEY.match(iface):
        raise HTTPException(422, "iface must look like net0")
    node = host.node_name or ""
    client = client_for_host(request.app, db, host)
    cfg = client.guest_config(kind, node, vmid)
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
    upid = client.guest_config_update(kind, node, vmid, {iface: value})
    write_audit(db, actor_type="user", actor_id=user.id, action="network.guest_config",
                target_type=target_type, target_id=target_id,
                params={"iface": iface, **changes},
                ip=request.client.host if request.client else None)
    return {
        "iface": iface, "value": value, "upid": upid,
        "pending_reboot": upid is not None,
        # Honest, not reassuring: PVE handed back a UPID, which for a config
        # write means it filed the change under the guest's PENDING section.
        # The running guest still has the old NIC.
        "detail": ("Proxmox recorded this as a pending change — the guest keeps its "
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


@router.get("/bridges", dependencies=[Depends(_require_viewer),
                                      Depends(require_entitlement("network.view"))])
def list_bridges(request: Request, host: int | None = None, db=Depends(get_db),
                 user: User = Depends(_require_viewer)):
    """Bridges/bonds/VLANs/physical NICs per node + the guest attachment map.

    # ponytail: the attachment map costs one guest_config read per adopted app
    # and VM on the host — fine for a homelab, linear in guest count for a
    # 200-guest fleet. This is a human-triggered route, explicitly outside the
    # poller's O(nodes) budget (proxmox.py's "per-guest, user-triggered calls"
    # section). If it ever gets slow, cache netN in the poller's cluster_resources
    # pass; do not add per-guest calls to the poll loop to get it.
    """
    hosts = [h for h in db.query(Host).order_by(Host.name).all()
             if host is None or h.id == host]
    nodes, attachments = [], []
    for h in hosts:
        client = client_for_host(request.app, db, h)
        for node in _nodes_of(request, h):
            nodes.append({"host_id": h.id, "host_name": h.name, "node": node,
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
    return {"nodes": nodes, "attachments": attachments}


@router.get("/throughput", dependencies=[Depends(_require_viewer),
                                         Depends(require_entitlement("network.view"))])
def throughput(request: Request, hours: int = 1, db=Depends(get_db),
               user: User = Depends(_require_viewer)):
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
