"""Cluster overview endpoints (doc 05): read-only, snapshots + caches."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from proxploy.api.deps import authorize, cluster_scope, dedupe_vms, get_db
from proxploy.pollers import pool_key
from proxploy.models import App, Host, User, Vm, to_iso

router = APIRouter(prefix="/cluster", tags=["cluster"])

# Cluster reads are host-shaped aggregates, not a distinct "cluster" resource
#; there is no ("cluster", "read") entry in PERMISSIONS, so this reuses
# ("host", "read").
_read = authorize("host", "read")


def _pct(used: float, total: float) -> float | None:
    """None when nothing was measured, never 0.0.

    A total of zero means no data reached this cycle or genuinely no capacity;
    both are "unknown", not "0% used".
    """
    return round(used / total * 100, 1) if total else None


@router.get("/summary")
def cluster_summary(request: Request, db=Depends(get_db),
                    user: User = Depends(_read)):
    snaps = request.app.state.poller.snapshots
    nodes: dict[tuple, dict] = {}
    storage: dict[tuple, dict] = {}
    updated = None
    # A node name and a datastore name are only unique WITHIN a cluster, so
    # every key here is scoped the way /cluster/nodes below already scopes
    # its own. Without it two standalone hosts collapse into one, and `pve`
    # is the PVE installer's default node name rather than an exotic clash.
    scopes = {h.id: cluster_scope(h) for h in db.query(Host).all()}
    for host_id, snap in snaps.items():
        scope = scopes.get(host_id, (host_id,))
        updated = max(updated, snap.ts) if updated else snap.ts
        for n in snap.nodes:
            # Two Host rows on one cluster each report the whole cluster, so
            # every node must count once however many hosts saw it.
            nodes[(scope, n["node"])] = n
        for st in snap.storage:
            # Keyed the same way pollers.disk_pct keys it, so the ring and the
            # host page cannot disagree about what one pool is: a SHARED
            # datastore is reported once per node and counts once, a LOCAL one
            # sharing a name across nodes is two pools. This used to key on the
            # name alone, which undercounted every cluster with a same-named
            # local pool on more than one node. Per-datastore truth is still
            # GET /storage (api/storage.py::list_storage).
            storage[(scope, pool_key(st))] = st

    # Summed over the DEDUPED nodes, never over the snapshots: each snapshot's
    # net is already a whole-cluster total, so adding those together reported
    # one cluster's traffic once per enrolled Host.
    net_in = sum(n.get("net_in_bps") or 0.0 for n in nodes.values())
    net_out = sum(n.get("net_out_bps") or 0.0 for n in nodes.values())

    total_cores = sum(n["cpu_cores"] for n in nodes.values())
    used_cores = sum(n["cpu_pct"] / 100 * n["cpu_cores"] for n in nodes.values())
    mem_used = sum(n["mem_bytes"] for n in nodes.values())
    mem_total = sum(n["mem_total_bytes"] for n in nodes.values())
    st_used = sum(s["used_bytes"] for s in storage.values())
    st_total = sum(s["total_bytes"] for s in storage.values())

    hosts = db.query(Host).all()
    apps = db.query(App).all()
    # Deduped: one row per (host, vmid) means a clustered pair counted every
    # guest twice, so "2 VMs" for one VM (doc 12 check 18).
    vms = dedupe_vms(db.query(Vm).all(), {h.id: h for h in hosts})
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
            # Host-level, like the counts below: quorum belongs to the cluster
            # behind this endpoint, not to one node of it. False ONLY when PVE
            # said so, so the sidebar's "All systems healthy" can stop being
            # true for a cluster that cannot accept a write (doc 12 check 12).
            "quorate": h.quorate,
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
        # If node_name names nothing in this snapshot, the first node is the
        # entry, so "exactly one entry per host" holds even for a surprising
        # cluster shape. NOT the same as the poller, which used to fall back
        # this way for `own` and no longer does: there the fallback attributed
        # one node's cpu and memory to a host sitting on another, which is a
        # false measurement. Here it only decides which card is flagged as the
        # way in, so a nearby answer beats no answer.
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
