"""Cluster overview endpoints (doc 05): read-only, snapshots + caches."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from proxploy.api.deps import get_db, require_role
from proxploy.models import App, Host, User, Vm

router = APIRouter(prefix="/cluster", tags=["cluster"])


def _iso(dt):
    return dt.isoformat() + "Z" if dt else None


def _pct(used: float, total: float) -> float:
    return round(used / total * 100, 1) if total else 0.0


@router.get("/summary")
def cluster_summary(request: Request, db=Depends(get_db),
                    user: User = Depends(require_role("viewer"))):
    snaps = request.app.state.poller.snapshots
    nodes: dict[str, dict] = {}
    storage: dict[str, dict] = {}
    net_in = net_out = 0.0
    updated = None
    for snap in snaps.values():
        updated = max(updated, snap.ts) if updated else snap.ts
        for n in snap.nodes:
            # dedupe by node name: two Host rows on one cluster count each node once
            nodes[n["node"]] = n
        for st in snap.storage:
            # ponytail: shared storage repeats per node — dedupe by name, keep
            # first; per-datastore truth arrives with the Phase 6 Storage page
            storage.setdefault(st["storage"], st)
        net_in += snap.net["in_bps"]
        net_out += snap.net["out_bps"]

    total_cores = sum(n["cpu_cores"] for n in nodes.values())
    used_cores = sum(n["cpu_pct"] / 100 * n["cpu_cores"] for n in nodes.values())
    mem_used = sum(n["mem_bytes"] for n in nodes.values())
    mem_total = sum(n["mem_total_bytes"] for n in nodes.values())
    st_used = sum(s["used_bytes"] for s in storage.values())
    st_total = sum(s["total_bytes"] for s in storage.values())

    hosts = db.query(Host).all()
    apps = db.query(App).all()
    vms = db.query(Vm).all()
    return {
        "updated_at": _iso(updated),
        "cpu": {"pct": _pct(used_cores, total_cores),
                "used_cores": round(used_cores, 1), "total_cores": total_cores},
        "mem": {"pct": _pct(mem_used, mem_total),
                "used_bytes": mem_used, "total_bytes": mem_total},
        "storage": {"pct": _pct(st_used, st_total),
                    "used_bytes": st_used, "total_bytes": st_total},
        "net": {"in_bps": net_in, "out_bps": net_out},
        "counts": {
            "hosts": len(hosts),
            "hosts_online": sum(1 for h in hosts if h.status == "connected"),
            "nodes": len(nodes),
            "apps": len(apps),
            "apps_running": sum(1 for a in apps if a.status_cached == "running"),
            "vms": len(vms),
            "vms_running": sum(1 for v in vms if v.status == "running"),
        },
    }


@router.get("/nodes")
def cluster_nodes(request: Request, db=Depends(get_db),
                  user: User = Depends(require_role("viewer"))):
    snaps = request.app.state.poller.snapshots
    out = []
    for h in db.query(Host).order_by(Host.id).all():
        snap = snaps.get(h.id)
        own = None
        if snap and snap.nodes:
            own = next((n for n in snap.nodes if n["node"] == h.node_name),
                       snap.nodes[0])
        apps = db.query(App).filter_by(host_id=h.id).all()
        vms = db.query(Vm).filter_by(host_id=h.id).all()
        out.append({
            "host_id": h.id, "name": h.name, "node": h.node_name,
            "status": h.status, "cluster": h.cluster_name,
            "pve_version": h.pve_version,
            "cpu_pct": own["cpu_pct"] if own else None,
            "mem_pct": (_pct(own["mem_bytes"], own["mem_total_bytes"])
                        if own else None),
            "mem_bytes": own["mem_bytes"] if own else None,
            "mem_total_bytes": own["mem_total_bytes"] if own else None,
            "uptime_s": own["uptime_s"] if own else None,
            "apps": len(apps),
            "apps_running": sum(1 for a in apps if a.status_cached == "running"),
            "vms": len(vms),
            "vms_running": sum(1 for v in vms if v.status == "running"),
            "last_seen_at": _iso(h.last_seen_at),
        })
    return out
