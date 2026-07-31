"""Cluster overview endpoints (doc 05): read-only, snapshots + caches."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from proxploy.api.deps import get_db, require_entitlement, require_role
from proxploy.models import App, AuditEvent, Host, Job, User, Vm

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
            # ponytail: name-keyed dedupe, which is exact for a shared datastore
            # (one datastore reported once per node) and undercounts a LOCAL
            # storage that happens to share a name across nodes (`local` on pve1
            # and pve2 is 2x the capacity, counted once). This is the cluster
            # RING — a single number — and the snapshot dict now carries
            # `shared`, so the fix is one line (`key = st["storage"] if
            # st["shared"] else (st["node"], st["storage"])`) if the ring is ever
            # shown to disagree with the page. Per-datastore truth, which does
            # key on `shared`, is GET /storage (api/storage.py::list_storage).
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


ACTIVITY_MAX = 100


# Reused as BOTH the route-level dependency and the parameter-level one so
# FastAPI's dependency cache (keyed on the callable) collapses them into a
# single call that runs first. A bare `dependencies=[Depends(require_entitlement(...))]`
# would sit at position 0 of the dependant and run BEFORE this auth/role check,
# leaking 403 to an anonymous caller who should see 401 (Tasks 3, 5, 7 hit this
# in jobs.py/apps.py/notifications.py — see apps.py._require_operator).
_require_viewer = require_role("viewer")


@router.get("/activity",
            dependencies=[Depends(_require_viewer),
                          Depends(require_entitlement("cluster.activity_feed"))])
def activity(limit: int = 20, db=Depends(get_db),
            user: User = Depends(_require_viewer)):
    """Jobs + audit highlights, merged newest-first (doc 05, doc 06 ActivityFeed).

    An audit row that spawned a job is skipped: the job entry already represents
    it, and showing both would double every lifecycle action. Alerts join this
    feed in Phase 7 when the evaluator exists — the `kind` discriminator is here
    so that is additive.

    Paging: each source is independently queried with `LIMIT limit` (not
    `limit // 2`), so the merged-then-sliced result is always the true
    top-`limit` rows across both kinds — the top `limit` merged rows can
    contain at most `limit` rows from either source, and each source already
    supplies that many. A source can only return fewer than `limit` rows
    (including zero) than the feed asks for when it genuinely has fewer
    displayable rows, e.g. every audit row in view is a job-spawned dupe that
    gets skipped — that is the intended dedup, not starvation.

    The merge sorts on the raw `datetime`, not the serialized `.isoformat()`
    string used for the `at` field: Python's `isoformat()` drops the
    microsecond component when it is exactly 0, which would make a same-instant
    row from one source sort inconsistently against a row from the other if
    compared as strings.
    """
    limit = max(1, min(limit, ACTIVITY_MAX))
    emails = {u.id: u.email for u in db.query(User).all()}

    jobs = (db.query(Job).order_by(Job.created_at.desc(), Job.id.desc())
            .limit(limit).all())
    job_rows = [(j.created_at, {
        "kind": "job", "id": j.id, "at": j.created_at.isoformat() + "Z",
        "title": j.kind, "status": j.status, "target_type": j.target_type,
        "target_id": j.target_id, "actor": emails.get(j.requested_by),
        "job_id": j.id, "progress_pct": j.progress_pct}) for j in jobs]

    audits = (db.query(AuditEvent).filter(AuditEvent.job_id.is_(None))
              .order_by(AuditEvent.ts.desc(), AuditEvent.id.desc())
              .limit(limit).all())
    audit_rows = [(a.ts, {
        "kind": "audit", "id": a.id, "at": a.ts.isoformat() + "Z",
        "title": a.action, "status": a.result, "target_type": a.target_type,
        "target_id": a.target_id, "actor": emails.get(a.actor_id),
        "job_id": None, "progress_pct": None}) for a in audits]

    merged = sorted(job_rows + audit_rows, key=lambda pair: pair[0], reverse=True)
    return [row for _, row in merged[:limit]]
