"""Poller subsystem (doc 10 Phase 2, doc 02 §3).

ingest_cycle() is the pure-ish core: given one host's bulk reads it updates
caches, batches metric samples (ONE commit per cycle, doc 11 §4), and returns
the fresh in-memory snapshot plus the SSE deltas to publish. The Poller class
(task loops, backoff, degradation) lives below it and is the only caller.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from proxploy.models import App, CatalogEntry, Host, MetricSample, Vm
from proxploy.services.metrics import write_samples


@dataclass
class HostSnapshot:
    host_id: int
    ts: datetime
    nodes: list[dict] = field(default_factory=list)
    storage: list[dict] = field(default_factory=list)
    net: dict = field(default_factory=lambda: {"in_bps": 0.0, "out_bps": 0.0})
    guests: dict[tuple[str, int], dict] = field(default_factory=dict)
    discovered: list[dict] = field(default_factory=list)


@dataclass
class CycleResult:
    snapshot: HostSnapshot
    events: list[tuple[str, dict]]


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _suggest(catalog: dict[str, str], name: str) -> str | None:
    # ponytail: exact normalized-name match only; fuzzier heuristics land with
    # Phase 4's adoption UX where a human confirms the match anyway.
    return catalog.get(_norm(name))


def _mem_pct(used: int, total: int) -> float:
    return round(used / total * 100, 1) if total else 0.0


def ingest_cycle(db, host: Host, resources: list[dict],
                 rrd_by_node: dict[str, list[dict]], now: datetime) -> CycleResult:
    events: list[tuple[str, dict]] = []
    samples: list[MetricSample] = []
    targets: list[dict] = []

    node_rows = [r for r in resources if r.get("type") == "node"]
    storage_rows = [r for r in resources if r.get("type") == "storage"]

    # nodes + host-level samples ------------------------------------------------
    snap_nodes: list[dict] = []
    net_in = net_out = 0.0
    for r in node_rows:
        rrd = rrd_by_node.get(r["node"]) or []
        last = rrd[-1] if rrd else {}
        snap_nodes.append({
            "node": r["node"], "status": r.get("status", "unknown"),
            "cpu_pct": round(float(r.get("cpu") or 0.0) * 100, 1),
            "cpu_cores": int(r.get("maxcpu") or 0),
            "mem_bytes": int(r.get("mem") or 0),
            "mem_total_bytes": int(r.get("maxmem") or 0),
            "uptime_s": int(r.get("uptime") or 0),
        })
        net_in += float(last.get("netin") or 0.0)
        net_out += float(last.get("netout") or 0.0)

    own = next((n for n in snap_nodes if n["node"] == host.node_name),
               snap_nodes[0] if snap_nodes else None)
    if own:
        for metric, value in (("cpu_pct", own["cpu_pct"]),
                              ("mem_bytes", float(own["mem_bytes"])),
                              ("net_in_bps", net_in), ("net_out_bps", net_out)):
            samples.append(MetricSample(target_type="host", target_id=host.id,
                                        metric=metric, value=value, ts=now))
        targets.append({"t": "host", "id": host.id, "cpu_pct": own["cpu_pct"],
                        "mem_pct": _mem_pct(own["mem_bytes"], own["mem_total_bytes"])})

    if host.status != "connected":
        events.append(("resource", {"type": "host", "id": host.id,
                                    "change": "status", "status": "connected"}))
    host.status, host.last_seen_at = "connected", now

    # guests map ----------------------------------------------------------------
    guests: dict[tuple[str, int], dict] = {}
    for r in resources:
        if r.get("type") not in ("lxc", "qemu"):
            continue
        guests[(r["type"], int(r["vmid"]))] = {
            "name": r.get("name"), "node": r.get("node"),
            "status": r.get("status", "unknown"),
            "cpu_pct": round(float(r.get("cpu") or 0.0) * 100, 1),
            "cpu_cores": int(r.get("maxcpu") or 0),
            "mem_bytes": int(r.get("mem") or 0),
            "mem_total_bytes": int(r.get("maxmem") or 0),
            "disk_bytes": int(r.get("maxdisk") or 0),
            "uptime_s": int(r.get("uptime") or 0),
        }

    # apps cache refresh (identity is ours; state is cached — doc 04) ----------
    mapped_ctids: set[int] = set()
    for a in db.query(App).filter_by(host_id=host.id).all():
        mapped_ctids.add(a.ctid)
        g = guests.get(("lxc", a.ctid))
        if g is None:
            if a.status_cached != "unknown":
                a.status_cached = "unknown"
                events.append(("resource", {"type": "app", "id": a.id,
                                            "change": "status", "status": "unknown"}))
            continue
        if a.status_cached != g["status"]:
            events.append(("resource", {"type": "app", "id": a.id,
                                        "change": "status", "status": g["status"]}))
        a.status_cached, a.cpu_pct_cached = g["status"], g["cpu_pct"]
        a.mem_bytes_cached, a.uptime_s_cached = g["mem_bytes"], g["uptime_s"]
        samples.append(MetricSample(target_type="app", target_id=a.id,
                                    metric="cpu_pct", value=g["cpu_pct"], ts=now))
        samples.append(MetricSample(target_type="app", target_id=a.id,
                                    metric="mem_bytes", value=float(g["mem_bytes"]), ts=now))
        targets.append({"t": "app", "id": a.id, "cpu_pct": g["cpu_pct"],
                        "mem_pct": _mem_pct(g["mem_bytes"], g["mem_total_bytes"])})

    # vms cache upsert (droppable mirror — doc 04) ------------------------------
    existing = {v.vmid: v for v in db.query(Vm).filter_by(host_id=host.id).all()}
    seen: set[int] = set()
    membership_changed = False
    for (kind, vmid), g in guests.items():
        if kind != "qemu":
            continue
        seen.add(vmid)
        v = existing.get(vmid)
        if v is None:
            v = Vm(host_id=host.id, vmid=vmid, name=g["name"] or f"vm-{vmid}",
                   status=g["status"])
            db.add(v)
            membership_changed = True
        elif v.status != g["status"]:
            events.append(("resource", {"type": "vm", "id": v.id,
                                        "change": "status", "status": g["status"]}))
        v.name = g["name"] or v.name
        v.status, v.uptime_s, v.synced_at = g["status"], g["uptime_s"], now
        v.cpu_cores, v.mem_bytes, v.disk_bytes = (
            g["cpu_cores"], g["mem_total_bytes"], g["disk_bytes"])
    for vmid, v in existing.items():
        if vmid not in seen:
            db.delete(v)
            membership_changed = True
    db.flush()  # new Vm rows need ids before sampling
    for v in db.query(Vm).filter_by(host_id=host.id).all():
        g = guests.get(("qemu", v.vmid))
        if not g:
            continue
        samples.append(MetricSample(target_type="vm", target_id=v.id,
                                    metric="cpu_pct", value=g["cpu_pct"], ts=now))
        samples.append(MetricSample(target_type="vm", target_id=v.id,
                                    metric="mem_bytes", value=float(g["mem_bytes"]), ts=now))
        targets.append({"t": "vm", "id": v.id, "cpu_pct": g["cpu_pct"],
                        "mem_pct": _mem_pct(g["mem_bytes"], g["mem_total_bytes"])})
    if membership_changed:
        events.append(("resource", {"type": "vm", "change": "list"}))

    # discovered CTs + adoption heuristic (NOT auto-adopted — Phase 4 owns that)
    catalog = {_norm(c.slug): c.slug for c in db.query(CatalogEntry).all()}
    discovered = [
        {"ctid": vmid, "name": g["name"], "node": g["node"],
         "status": g["status"], "suggestion": _suggest(catalog, g["name"] or "")}
        for (kind, vmid), g in sorted(guests.items())
        if kind == "lxc" and vmid not in mapped_ctids
    ]

    snap_storage = [
        {"storage": r.get("storage"), "node": r.get("node"),
         "used_bytes": int(r.get("disk") or 0),
         "total_bytes": int(r.get("maxdisk") or 0)}
        for r in storage_rows
    ]

    write_samples(db, samples)
    db.commit()

    events.insert(0, ("metrics", {"targets": targets}))
    snapshot = HostSnapshot(host_id=host.id, ts=now, nodes=snap_nodes,
                            storage=snap_storage,
                            net={"in_bps": net_in, "out_bps": net_out},
                            guests=guests, discovered=discovered)
    return CycleResult(snapshot=snapshot, events=events)
