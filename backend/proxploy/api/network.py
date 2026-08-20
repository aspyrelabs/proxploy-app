# backend/proxploy/api/network.py
"""Network reads + guest NIC edit (doc 05 §Network, doc 01 §6).

Doc 05 calls /network/bridges a "live passthrough" and this is exactly that:
no model, no cache, no migration; one GET /nodes/{node}/network per node of
the requested host(s), served straight back. Throughput is the opposite: it is
NOT a passthrough; it comes from the `host` target's existing `net_in_bps` /
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

import ipaddress
import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from proxploy.api.deps import (authorize, cluster_scope, get_db,
                               require_entitlement, scope_host)
from proxploy.api.jobs import enqueue_and_audit
from proxploy.models import App, Host, User, Vm, utcnow
from proxploy.services.audit import write_audit
from proxploy.services.hostclient import (client_for_host, dedupe_vms,
                                          guest_node)
from proxploy.services.metrics import pick_resolution, query_series
from proxploy.services.netconfig import build_net, nic_identity, parse_net
from proxploy.services.proxmox import ProxmoxError, routable_addresses

router = APIRouter(prefix="/network", tags=["network"])

# Singleton first in dependencies=[...] and reused as the parameter dep, so
# auth runs before the entitlement gate and FastAPI collapses the two
# (deps.py idiom; test_route_auth_invariant.py enforces it). Both reads below
# take `host` as a query param, not a path param, so there is nothing for
# scope_host() to resolve: global, same as before this had a scope.
_read = authorize("network", "read")

NET_KEY = re.compile(r"^net\d+$")


# Where a guest's address actually lives, which is NOT the same key for the two
# guest types. Read off PVE 9.2.10 itself rather than from memory:
#
#   pct set --net[n]  ... [,gw=<GatewayIPv4>] [,gw6=<GatewayIPv6>]
#                         [,ip=<(IPv4/CIDR|dhcp|manual)>]
#                         [,ip6=<(IPv6/CIDR|auto|dhcp|manual)>]
#   qm  set --net[n]  ... no ip, no gw, at all
#   qm  set --ipconfig[n]  [gw=] [,gw6=] [,ip=<IPv4/CIDR>] [,ip6=]
#                          "cloud-init: Specify IP addresses and gateways"
#
# So a container carries its address ON the NIC, and a VM carries it in a
# cloud-init key beside the NIC. The consequence that matters: `ipconfigN` is
# inert unless the VM has a cloud-init drive AND runs cloud-init, so writing it
# to a VM without one changes a config file and nothing inside the guest. That is
# refused rather than written, see _ipconfig_target below.
ADDRESS_KEYS = ("ip", "gw", "ip6", "gw6")

def _has_cloudinit_drive(cfg: dict, vmid: int) -> bool:
    """PVE writes the drive as a CDROM whose volume is named for the VM.
    Measured on PVE 9.2.10, 2026-08-19 (doc 12): creating one with
    `ide2: local-lvm:cloudinit` reads back as
    `ide2: local-lvm:vm-9911-cloudinit,media=cdrom`.

    Matched on that volume name, which carries the vmid, rather than on "does
    any value mention cloudinit": the loose version also matched a VM someone
    had called `probe-cloudinit`, which is how the probe found this out.
    """
    return any(f"vm-{vmid}-cloudinit" in str(v) for v in cfg.values())


def _configured_address(cfg: dict, iface: str, vmid: int) -> str | None:
    """The address PVE is configured to hand this VM's NIC, or None.

    This is the answer to "does Proxmox know this VM's address": for a STATIC
    cloud-init config it does, in `ipconfigN`, and no guest agent is needed to
    read it. Measured on hardware, PVE 9.2.10, 2026-08-19.

    None in the three cases where it does not know:

      * no cloud-init drive. PVE stores `ipconfigN` on a VM without one
        perfectly happily and it does nothing, so reading it back would invent
        an address the guest has no way of ever receiving.
      * `ip=dhcp`. PVE keeps the literal word; it is not a DHCP server and
        never learns the lease. That is a setting, not an address.
      * no `ipconfigN` for this NIC at all.

    Paired by index: net1 takes ipconfig1. Sharing index 0 across every NIC
    would report one NIC's address on another.
    """
    if not _has_cloudinit_drive(cfg, vmid):
        return None
    raw = cfg.get(f"ipconfig{iface[3:]}")
    if not raw:
        return None
    for part in str(raw).split(","):
        key, _, value = part.partition("=")
        if key.strip() == "ip" and value not in ("dhcp", "manual", ""):
            return value
    return None


def _valid_address(key: str, value: str) -> bool:
    """Shape check only, so a typo is a clean 422 here instead of PVE's own 400
    relayed as a 502. stdlib `ipaddress`, no dependency: PVE's grammar is
    literally a CIDR or one of a few words."""
    if key == "ip":
        if value in ("dhcp", "manual"):
            return True
        try:
            ipaddress.IPv4Interface(value)
        except ValueError:
            return False
        return "/" in value          # PVE wants CIDR, not a bare address
    if key == "ip6":
        if value in ("dhcp", "auto", "manual"):
            return True
        try:
            ipaddress.IPv6Interface(value)
        except ValueError:
            return False
        return "/" in value
    version = 4 if key == "gw" else 6
    try:
        return ipaddress.ip_address(value).version == version
    except ValueError:
        return False


class NicIn(BaseModel):
    """Every field optional; only fields PRESENT in the request body are
    applied, and an explicit null removes the key (that is how a VLAN tag or a
    rate limit is cleared). Absent != null here, hence exclude_unset below.

    `ip`/`gw`/`ip6`/`gw6` are the guest's address. They land on a different
    Proxmox key depending on the guest type (see ADDRESS_KEYS above), which the
    caller does not have to know about: this route routes them.
    """
    bridge: str | None = None
    tag: int | None = None
    ip: str | None = None
    gw: str | None = None
    ip6: str | None = None
    gw6: str | None = None
    # Accepted, and deliberately NOT offered by the UI (components/NicForm.tsx).
    # Proxploy has no firewall feature: no rules, security groups, aliases or IP
    # sets at guest, node or cluster level. A toggle implies one exists, and
    # enabling the flag can leave a guest unreachable with nothing in this
    # product able to permit traffic again. The field stays so an API caller can
    # still clear a flag PVE set, and so the read path can report it (doc 11).
    firewall: bool | None = None
    rate: float | None = None
    mtu: int | None = None
    link_down: bool | None = None


def _nic_out(iface: str, raw: str) -> dict:
    parts = parse_net(raw)
    return {
        "iface": iface, "raw": raw, **nic_identity(parts),
        # Present on a container's netN, absent on a VM's by PVE's own schema, so
        # these are None for a VM rather than a claim of "no address set".
        "ip": parts.get("ip"), "gw": parts.get("gw"),
        "ip6": parts.get("ip6"), "gw6": parts.get("gw6"),
        "bridge": parts.get("bridge"),
        "tag": int(parts["tag"]) if parts.get("tag") else None,
        "firewall": parts.get("firewall") == "1",
        "rate": parts.get("rate"), "mtu": parts.get("mtu"),
        "link_down": parts.get("link_down") == "1",
    }


def _container_addresses(client, node: str, vmid: int,
                         nics: list[dict]) -> None:
    """Fill each NIC's `addresses` with what the container actually holds.

    A configured address needs no lookup: it IS the answer, and asking the
    running guest as well would spend a per-guest call on something the config
    already states. Only a NIC with no usable `ip` (`dhcp`, `manual`, or
    nothing) sends us to PVE, and then ONE call serves every NIC on the guest.

    Matched on hardware address, which the config and the runtime rows both
    carry, rather than on interface name: `name=eth0` in a container's netN is
    the name INSIDE the guest and nothing stops it being renamed there.
    """
    needs_lookup = [n for n in nics
                    if not n.get("ip") or n["ip"] in ("dhcp", "manual")]
    for n in nics:
        ip = n.get("ip")
        n["addresses"] = [ip] if ip and ip not in ("dhcp", "manual") else None
    if not needs_lookup:
        return
    rows = client.lxc_interfaces(node, vmid)
    if rows is None:
        return                      # stopped, or PVE would not say: unknown
    by_mac = {str(r.get("hwaddr") or r.get("hardware-address") or "").lower(): r
              for r in rows}
    for n in needs_lookup:
        found = by_mac.get(str(n.get("macaddr") or "").lower())
        addresses = routable_addresses(found) if found else []
        n["addresses"] = addresses or None


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
    nics = [_nic_out(k, str(cfg[k])) for k in sorted(cfg) if NET_KEY.match(k)]
    if kind == "lxc":
        _container_addresses(client_for_host(request.app, db, host),
                             guest_node(host, row), vmid, nics)
    return nics


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
        reader = client_for_host(request.app, db, host, capability="monitoring")
        cfg = reader.guest_config(kind, node, vmid)
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

    # Addressing, and the guest type decides whether it is even expressible.
    # A container carries ip/gw on this very netN string, so it merges in below
    # like any other key. A VM's netN has no such field: PVE addresses VMs
    # through the cloud-init key `ipconfigN`, which does nothing unless the VM
    # has a cloud-init drive AND something in the guest reads it. Windows has no
    # cloud-init at all (Cloudbase-Init is a third-party port), and nothing here
    # can see inside a guest to know. So this refuses rather than writing a key
    # whose effect it cannot state. The VM path is READ ONLY today: guest_nics
    # reports the addresses the agent says the guest actually has.
    addressing = [k for k in ADDRESS_KEYS if k in changes]
    if addressing and kind != "lxc":
        raise HTTPException(409, {
            "error": "vm_addressing_not_editable",
            "detail": ("Proxmox does not keep a virtual machine's address on its "
                       "NIC. It uses cloud-init, which only takes effect when the "
                       "VM has a cloud-init drive and the guest reads it, so "
                       "Proxploy does not write it. Set the address inside the "
                       "guest, or with a DHCP reservation."),
        })
    bad = [k for k in addressing
           if changes[k] is not None and not _valid_address(k, str(changes[k]))]
    if bad:
        raise HTTPException(422, {
            "error": "invalid_address",
            "detail": (f"{', '.join(bad)}: an address is CIDR notation "
                       f"(192.168.1.50/24), or dhcp or manual. A gateway is a "
                       f"plain address."),
        })

    for key, val in changes.items():
        if val is None:
            parts.pop(key, None)
        elif isinstance(val, bool):
            parts[key] = "1" if val else "0"
        else:
            parts[key] = str(val)
    value = build_net(parts)
    try:
        client.guest_config_update(kind, node, vmid, {iface: value})
    except ProxmoxError as e:
        write_audit(db, actor_type="user", actor_id=user.id, action="network.guest_config",
                    target_type=target_type, target_id=target_id,
                    params={"iface": iface, **changes}, result="error", ip=ip)
        raise HTTPException(502, str(e))
    write_audit(db, actor_type="user", actor_id=user.id, action="network.guest_config",
                target_type=target_type, target_id=target_id,
                params={"iface": iface, **changes}, ip=ip)

    # Whether the running guest already has this NIC is a question ONLY the
    # guest's pending config can answer, so it is asked, after the write.
    #
    # This used to be `upid is not None`, on the belief that PVE returns a task
    # id when it files a config change under the pending section. It does not:
    # the PUT handler is the synchronous one and its schema returns null, so
    # that expression was always False and this route told every operator
    # "applied immediately, no reboot needed" even when the new bridge was
    # sitting in pending and the guest was still on the old one. See
    # ProxmoxClient.guest_config_update.
    try:
        pending_reboot = iface in reader.guest_pending(kind, node, vmid)
        unknown = False
    except ProxmoxError:
        # The write landed; only the follow-up question failed. Answering
        # "no reboot needed" here would be the same false reassurance again,
        # so this reports the cautious side and says why in `detail`.
        pending_reboot, unknown = True, True
    return {
        "iface": iface, "value": value,
        "pending_reboot": pending_reboot,
        "detail": ("The new settings were saved, but Proxmox could not be asked "
                   "whether the running guest already has them. Restart the guest "
                   "if the change does not show up." if unknown else
                   "Proxmox recorded this as a pending change; the guest keeps its "
                   "current NIC until it is rebooted (a shutdown/start, not a reset)."
                   if pending_reboot else
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
    vms_by_host: dict[int, list] = {}
    for v in dedupe_vms(db.query(Vm).all(), {h.id: h for h in db.query(Host).all()}):
        vms_by_host.setdefault(v.host_id, []).append(v)
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
            # Apps are read at their host's node (an app row IS its host's).
            # VMs carry their own node and are deduped across the cluster: the
            # mirror holds one row per (host, vmid), so this used to read the
            # same guest once per enrolled host AND read it at the wrong node
            # for every host but the owning one, which raised and dropped that
            # whole host's attachments into `errors` (doc 12 check 18).
            guests = ([("app", a.id, a.name, "lxc", a.ctid, node)
                       for a in db.query(App).filter_by(host_id=h.id).order_by(App.name)]
                      + [("vm", v.id, v.name, "qemu", v.vmid, guest_node(h, v))
                         for v in sorted(vms_by_host.get(h.id, []),
                                         key=lambda v: (v.name or "", v.id))])
            for gtype, gid, gname, kind, vmid, gnode in guests:
                cfg = client.guest_config(kind, gnode, vmid)
                # A VM's address is not on its netN the way a container's is, so
                # there are two places Proxmox might know it, and the agent is
                # asked first because it is the only one that reports what the
                # guest HAS rather than what was asked for. One call per VM, on
                # a route that is already one config read per guest and
                # explicitly human-triggered (see the ponytail note above).
                agent_ips = (client.agent_addresses(gnode, vmid)
                             if kind == "qemu" else None)
                for key in sorted(k for k in cfg if NET_KEY.match(k)):
                    # Falls back to the cloud-init config only when the agent
                    # gave us nothing, and stays None when neither source has an
                    # address: the UI shows nothing at all rather than
                    # explaining an absence nobody asked about.
                    addresses = agent_ips or None
                    if addresses is None and kind == "qemu":
                        configured = _configured_address(cfg, key, vmid)
                        addresses = [configured] if configured else None
                    attachments.append({"host_id": h.id, "node": gnode,
                                        "guest_type": gtype, "guest_id": gid,
                                        "name": gname, "vmid": vmid,
                                        "addresses": addresses,
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
#
# THE RULE FOR WHOEVER BUILDS THAT PREVIEW, and it is not optional: show PVE's
# OWN `changes` diff, never a rendering of the fields the operator edited. On
# real hardware (doc 12 check 8) staging one unused bridge produced a `.new`
# file in which PVE had ALSO rewritten unrelated stanzas: it added
# `iface nic1 inet manual` and `iface wlp0s20f3 inet manual`, added a comment
# block, and moved `nic1` above `vmbr0`. None of that was asked for, and all of
# it gets promoted by the same Apply. A preview showing only the edited field
# would therefore hide most of what is about to happen, on the one action in this
# product that can take a node off the network.
#
# Verified 2026-08-18 that `changes` is still absent from what this route
# returns: GET /network/bridges answers host_id, host_name, interfaces, node and
# nothing else, so there is no preview here yet, honest or otherwise.


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
