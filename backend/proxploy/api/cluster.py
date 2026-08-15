"""Cluster overview endpoints (doc 05): read-only, snapshots + caches."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from proxploy.api.deps import authorize, cluster_scope, get_db, require_entitlement
from proxploy.models import Alert, AlertRule, App, AuditEvent, Host, Job, User, Vm, to_iso

router = APIRouter(prefix="/cluster", tags=["cluster"])

# Cluster reads are host-shaped aggregates, not a distinct "cluster" resource
#; there is no ("cluster", "read") entry in PERMISSIONS, so this reuses
# ("host", "read"). Same singleton for the route-level dependencies=[...] copy
# and the parameter-level copy (see _read's use on /activity below) so
# FastAPI's dependency cache collapses them into one call that runs first, 
# ordering fix, doc 10 "auth before entitlement" invariant.
_read = authorize("host", "read")


def _pct(used: float, total: float) -> float:
    return round(used / total * 100, 1) if total else 0.0


@router.get("/summary")
def cluster_summary(request: Request, db=Depends(get_db),
                    user: User = Depends(_read)):
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
            # RING: a single number, and the snapshot dict now carries
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
        "updated_at": to_iso(updated),
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
                  user: User = Depends(_read)):
    """One row per NODE, not per Host.

    A Proxploy Host is ONE Proxmox API endpoint; the cluster behind that
    endpoint is many nodes. `/cluster/resources` returns all of them and the
    poller stores all of them in `snap.nodes`, but this endpoint used to pick
    the one matching `host.node_name` and drop the rest, so a 3-node cluster
    rendered as a single card.

    `is_entry` marks the node we actually connect through (the `local: 1` node
    recorded at enrolment). Exactly one row per host carries it, including a
    host with no snapshot yet, so a consumer can always resolve a host to a
    node: `/hosts/{id}` redirects there, node shells open there, and the
    host-level metric series belongs to it.

    `apps`/`vms` stay HOST-level counts on every row: neither table records
    which node a guest sits on (App has host_id + ctid only), so a per-node
    split would be invented, not measured.

    `disk_*` IS per node, and a SHARED datastore counts on every node that can
    use it, because the question a node card answers is "how much storage can
    this node put a guest on". The consequence, stated here because a future
    reader will otherwise discover it as a bug: SUMMING disk_bytes /
    disk_total_bytes across these rows double-counts every shared pool. The
    cluster-wide figure is GET /cluster/summary (name-deduped), and the
    correctly deduped shared-vs-local aggregate is pollers._disk_pct, which is
    what the `disk_pct` metric series and therefore alerting use.

    Two Hosts can be two nodes of the SAME cluster; cluster_resources()
    returns the whole cluster from either one, so both snapshots list both
    nodes. A real node must appear once, attributed to the Host actually
    registered at it (`owner_by_node`); a node nobody is registered at (an
    unregistered cluster member) is attributed to whichever host's snapshot
    reports it first, same as before this had multiple hosts to consider.
    Both are keyed on cluster_scope(h) too: a node name is only unique
    WITHIN a cluster, so a same-named node on a different cluster (or
    another standalone host) must not be merged in.
    """
    snaps = request.app.state.poller.snapshots
    hosts = db.query(Host).order_by(Host.id).all()
    owner_by_node = {(cluster_scope(h), h.node_name): h
                     for h in hosts if h.node_name}
    reported: set[tuple] = set()
    out = []
    for h in hosts:
        scope = cluster_scope(h)
        snap = snaps.get(h.id)
        apps = db.query(App).filter_by(host_id=h.id).all()
        vms = db.query(Vm).filter_by(host_id=h.id).all()
        shared = {
            "host_id": h.id, "name": h.name, "cluster": h.cluster_name,
            "pve_version": h.pve_version,
            "apps": len(apps),
            "apps_running": sum(1 for a in apps if a.status_cached == "running"),
            "vms": len(vms),
            "vms_running": sum(1 for v in vms if v.status == "running"),
            "last_seen_at": to_iso(h.last_seen_at),
        }
        nodes = list(snap.nodes) if snap and snap.nodes else []
        if not nodes:
            # No snapshot yet (freshly enrolled, or unreachable): one row from
            # the DB, exactly as before, so a host never disappears from the
            # page just because the poller has not run.
            if (scope, h.node_name) in reported:
                continue
            reported.add((scope, h.node_name))
            out.append(shared | {
                "node": h.node_name, "is_entry": True, "status": h.status,
                "cpu_pct": None, "mem_pct": None, "mem_bytes": None,
                "mem_total_bytes": None, "uptime_s": None,
                "disk_pct": None, "disk_bytes": None,
                "disk_total_bytes": None})
            continue
        # Datastore rows are already one per (node, storage), so a node's own
        # slice needs no dedup: within one node a name appears once.
        disk: dict[str, tuple[int, int]] = {}
        for st in (snap.storage or []):
            used, total = disk.get(st["node"], (0, 0))
            disk[st["node"]] = (used + st["used_bytes"],
                                total + st["total_bytes"])
        # Same fallback the poller uses for `own`: if node_name names nothing
        # in this snapshot, the first node is the entry, so "exactly one entry
        # per host" holds even for a surprising cluster shape.
        names = [n["node"] for n in nodes]
        entry = h.node_name if h.node_name in names else names[0]
        for n in nodes:
            # A node registered as its OWN Host is reported once, by that
            # Host; a node this snapshot merely sees (another Host's node, or
            # nobody's) is reported by whichever host gets here first.
            owner = owner_by_node.get((scope, n["node"]), h)
            if owner is not h or (scope, n["node"]) in reported:
                continue
            reported.add((scope, n["node"]))
            # Host.status is per-ENDPOINT ("can Proxploy talk to this
            # address"), so it is the right answer for every node behind it
            #, except a node PVE itself calls offline, which is not up no
            # matter how healthy the endpoint is. Only an explicit "offline"
            # downgrades a row: an unfamiliar status must never turn a working
            # host red.
            status = ("unreachable" if n.get("status") == "offline"
                      else h.status)
            used, total = disk.get(n["node"], (0, 0))
            out.append(shared | {
                "disk_pct": _pct(used, total) if total else None,
                "disk_bytes": used if total else None,
                "disk_total_bytes": total if total else None,
                "node": n["node"], "is_entry": n["node"] == entry,
                "status": status,
                "cpu_pct": n["cpu_pct"],
                "mem_pct": _pct(n["mem_bytes"], n["mem_total_bytes"]),
                "mem_bytes": n["mem_bytes"],
                "mem_total_bytes": n["mem_total_bytes"],
                "uptime_s": n["uptime_s"]})
    return out


ACTIVITY_MAX = 100


@router.get("/activity",
            dependencies=[Depends(_read),
                          Depends(require_entitlement("cluster.activity_feed"))])
def activity(limit: int = 20, db=Depends(get_db),
            user: User = Depends(_read)):
    """Jobs + alerts + audit highlights, merged newest-first (doc 05, doc 06
    ActivityFeed).

    An audit row that spawned a job is skipped: the job entry already represents
    it, and showing both would double every lifecycle action. Alerts are the
    third source, the `kind` discriminator lets the frontend distinguish all
    three without extra endpoints.

    Paging: each source is independently queried with `LIMIT limit` (not
    `limit // 3`), so the merged-then-sliced result is always the true
    top-`limit` rows across all three kinds, the top `limit` merged rows can
    contain at most `limit` rows from any one source, and each source already
    supplies that many. A source can only return fewer than `limit` rows
    (including zero) than the feed asks for when it genuinely has fewer
    displayable rows, e.g. every audit row in view is a job-spawned dupe that
    gets skipped; that is the intended dedup, not starvation.

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
        "kind": "job", "id": j.id, "at": to_iso(j.created_at),
        "title": j.kind, "status": j.status, "target_type": j.target_type,
        "target_id": j.target_id, "actor": emails.get(j.requested_by),
        "job_id": j.id, "progress_pct": j.progress_pct,
        "severity": None, "message": None}) for j in jobs]

    audits = (db.query(AuditEvent).filter(AuditEvent.job_id.is_(None))
              .order_by(AuditEvent.ts.desc(), AuditEvent.id.desc())
              .limit(limit).all())
    audit_rows = [(a.ts, {
        "kind": "audit", "id": a.id, "at": to_iso(a.ts),
        "title": a.action, "status": a.result, "target_type": a.target_type,
        "target_id": a.target_id, "actor": emails.get(a.actor_id),
        "job_id": None, "progress_pct": None,
        "severity": None, "message": None}) for a in audits]

    # Third source (doc 05: "jobs + alerts + audit highlights, merged"). Like
    # the two above it is queried with the FULL `limit`, not `limit // 3`; 
    # that is what makes the merged-then-sliced result the true top-`limit`.
    alerts = (db.query(Alert).order_by(Alert.created_at.desc(), Alert.id.desc())
              .limit(limit).all())
    rule_names = {r.id: (r.name, r.severity) for r in db.query(AlertRule)
                  .filter(AlertRule.id.in_({a.rule_id for a in alerts})).all()
                  } if alerts else {}
    alert_rows = [(a.created_at, {
        "kind": "alert", "id": a.id, "at": to_iso(a.created_at),
        "title": rule_names.get(a.rule_id, (a.message, "warning"))[0],
        "status": a.state,
        "severity": rule_names.get(a.rule_id, (None, "warning"))[1],
        "target_type": a.target_type, "target_id": a.target_id,
        "actor": None,          # nobody triggers an alert; the evaluator does
        "job_id": None, "progress_pct": None,
        "message": a.message}) for a in alerts]

    merged = sorted(job_rows + audit_rows + alert_rows,
                    key=lambda pair: pair[0], reverse=True)
    return [row for _, row in merged[:limit]]
