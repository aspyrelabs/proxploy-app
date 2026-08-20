"""Poller subsystem (doc 10 Phase 2, doc 02 §3).

ingest_cycle() is the pure-ish core: given one host's bulk reads it updates
caches, batches metric samples (ONE commit per cycle, doc 11 §4), and returns
the fresh in-memory snapshot plus the SSE deltas to publish. The Poller class
(task loops, backoff, degradation) lives below it and is the only caller.
"""
from __future__ import annotations

import asyncio
import json as jsonlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

from proxploy.models import App, CatalogEntry, Host, HostCredential, MetricSample, Vm, to_iso, utcnow
from proxploy.services.audit import write_audit
from proxploy.services.hostclient import (capability_gaps,
                                          cluster_identity_from,
                                          cluster_member_count,
                                          cluster_quorate)
from proxploy.services.metrics import write_samples
from proxploy.services.proxmox import ProxmoxClient, ProxmoxError

POLL_BACKOFF_CAP_S = 300

# How often the poll loop re-checks each host's tokens against their roles.
# Not every cycle: it costs one /access/permissions per configured token, and
# privileges change when an operator re-runs the setup script, not every 30
# seconds. Half an hour is slow enough to be free and fast enough that a
# re-generated token clears the warning without anyone pressing a button. Kept
# in memory, so a restart re-checks immediately, which is the useful direction.
CAPABILITY_GAP_INTERVAL_S = 1800


log = logging.getLogger(__name__)


@dataclass
class HostSnapshot:
    host_id: int
    ts: datetime
    nodes: list[dict] = field(default_factory=list)
    storage: list[dict] = field(default_factory=list)
    # No cluster-wide `net` total here. It used to carry one, and because every
    # Host of a cluster reports the WHOLE cluster, /cluster/summary adding
    # those up counted one cluster's traffic once per enrolled Host. The
    # per-node figures on `nodes` are the same data in a shape that can be
    # deduped, which is the only shape that adds up correctly.
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


def _update_net_rates(a: App, g: dict, now: datetime) -> None:
    """Turn this cycle's netin/netout counters into a rate on the app row.

    PVE reports bytes since the container booted, so a rate is a diff against
    the previous reading over the time between the two. Both the reading and
    its timestamp are stored for the next cycle to diff against.

    Two cases produce no rate rather than a wrong one. The first reading has
    nothing to diff against: one point has no slope. And a container restart
    zeroes the counters, so the delta goes negative; taking its absolute value
    would draw a fabricated traffic spike at exactly the moment an operator is
    most likely to be watching. Either way the rate is None for one cycle and
    recovers on the next, once there are two readings from the same boot.
    """
    prev_in, prev_out, prev_at = a.net_in_cached, a.net_out_cached, a.net_sampled_at
    now_in, now_out = g["net_in"], g["net_out"]
    elapsed = (now - prev_at).total_seconds() if prev_at else 0.0
    if prev_in is None or prev_out is None or elapsed <= 0:
        a.net_in_bps_cached = a.net_out_bps_cached = None
    elif now_in < prev_in or now_out < prev_out:
        a.net_in_bps_cached = a.net_out_bps_cached = None
    else:
        a.net_in_bps_cached = (now_in - prev_in) / elapsed
        a.net_out_bps_cached = (now_out - prev_out) / elapsed
    a.net_in_cached, a.net_out_cached, a.net_sampled_at = now_in, now_out, now


# How long a datastore has to stay out of the reads before it stops counting
# against disk_pct. 15 minutes, and for the same reason APP_REAP_AFTER_S is 15
# minutes: far longer than any burst of bad reads, short enough that a pool an
# operator really did remove is out of the percentage while they are still
# looking at the graph.
POOL_FORGET_AFTER_S = 900


def pool_key(row: dict) -> tuple:
    """A SHARED datastore is reported once per node and is ONE pool; a LOCAL
    datastore with the same name on two nodes is two distinct pools.

    Takes either a raw /cluster/resources row or a snapshot storage dict:
    both carry `storage`, `node` and `shared`. Shared so the cluster ring and
    the host's disk_pct cannot drift apart on what counts as one pool.
    """
    return ((row.get("storage"),) if row.get("shared")
            else (row.get("node"), row.get("storage")))


class PoolMemory:
    """Last-known size of every datastore, so a pool that drops out of one
    /cluster/resources read does not silently leave disk_pct's denominator.

    Reported from real use on 2026-08-18: the storage graph flapped between
    ~29% and ~12% every few minutes while the disks sat untouched. Confirmed
    against the real cluster on 2026-08-19 by restricting one empty 1.8 TB
    pool away from its node; disk_pct went 11.6% -> 27.6% -> 11.6% with no
    byte changed.

    A cycle loses storage rows for reasons that have nothing to do with the
    disks, and none of them look like an error at the call site:

      * a cluster member drops out of /cluster/resources during a corosync
        split. Its pools go with it, and the two Hosts of one cluster start
        reporting different numbers for the same disks.
      * PVE keeps listing a datastore whose mount is down but stops filling
        in disk/maxdisk. Read literally that is a zero-byte pool, which
        leaves both sums exactly like a missing row does.
      * the monitoring token loses Datastore.Audit and EVERY storage row
        disappears at once, which used to be recorded as a flat 0.0%.

    A percentage is only a measurement if its denominator holds still, so a
    pool absent from this cycle keeps the last size we actually measured: an
    unreachable disk still holds the bytes it held. Kept in memory per host,
    which is the useful direction on restart -- the first cycle after a
    restart has nothing to carry forward and simply reports what it can read.
    """

    def __init__(self) -> None:
        # key -> (last measured at, used bytes, total bytes)
        self._pools: dict[tuple, tuple[datetime, int, int]] = {}

    def measure(self, storage_rows: list[dict], now: datetime) -> dict[tuple, tuple[int, int]]:
        """Fold this cycle's rows in and return every pool still counting."""
        for r in storage_rows:
            total = int(r.get("maxdisk") or 0)
            if not total:
                # Listed but unreadable. Not evidence of a zero-byte pool, so
                # it neither updates nor refreshes what we last measured.
                continue
            self._pools[pool_key(r)] = (now, int(r.get("disk") or 0), total)
        self._pools = {
            k: v for k, v in self._pools.items()
            if (now - v[0]).total_seconds() < POOL_FORGET_AFTER_S}
        return {k: (used, total) for k, (_, used, total) in self._pools.items()}


def _disk_pct(storage_rows: list[dict], pools: PoolMemory,
              now: datetime) -> float | None:
    """Aggregate used/total across this host's datastores, over a pool set
    that survives a bad read (see PoolMemory).

    Deduped correctly, unlike the cluster ring's deliberate shortcut in
    api/cluster.py::cluster_summary. Doing it wrong here is not a cosmetic
    ring error; it is an alert that fires at the wrong number.

    None means "no datastore has been readable recently", which is a gap in
    the series rather than a host whose disks are 0% full.
    """
    counting = pools.measure(storage_rows, now)
    used = sum(u for u, _ in counting.values())
    total = sum(t for _, t in counting.values())
    return round(used / total * 100, 1) if total else None


# `None` is a real, meaningful cluster_name: it means "standalone". So a
# cycle that could not read cluster status needs a THIRD value, or a single
# hiccup would clear a live cluster name and every node card would fall back
# to claiming standalone. Same hazard the `version` handling calls out below,
# except there None was safely reusable as "not read" and here it is not.
UNREAD = object()


# How long an app's CT must stay absent from cycles we are willing to trust
# before the App row is deleted. 15 minutes is ~15 default poll intervals: far
# longer than any burst of bad reads, short enough that `pct destroy 150`
# clears the app out of the UI while the operator who ran it is still looking.
APP_REAP_AFTER_S = 900


def _absence_is_trustworthy(node_rows: list[dict], degraded: bool,
                            complete: bool = True) -> bool:
    """Can this cycle's guest list be used as PROOF that a CT is gone?

    Usually the honest answer is no, and getting this wrong deletes a user's
    app records because a node rebooted. "Not in /cluster/resources" has at
    least four causes and only one of them is "somebody destroyed it":

      * the host was unreachable. That case cannot reach here at all:
        _poll_once raises before ingest_cycle, and _host_loop turns the raise
        into status=unreachable without ever calling us.
      * the cycle was degraded (a read 403'd, timed out, or came back short).
        A half-answer is not evidence of anything, so we hold what we have.
      * a CLUSTER MEMBER is down. This is the dangerous one, because nothing
        else about the cycle looks wrong: the endpoint we asked answered
        fine, the host is "connected", the cycle is not degraded -- and an
        entire node's worth of guests has silently dropped out of
        /cluster/resources. App rows carry host_id + ctid and no node, so we
        cannot tell "this app lived on the node that just went down" from
        "this app was destroyed"; the only safe move is to distrust the whole
        cycle unless every node in it reports online.

        `complete` covers the remaining hole in that check. Measured against
        real hardware on 2026-08-19 by rebooting a cluster member: a node that
        goes down KEEPS its /cluster/resources row and flips it to
        `status: "offline"`, and its storage rows stay too, so the online test
        above already catches an ordinary outage and that is the common case.
        What it cannot catch is a member that stops appearing in the response
        at all, because then there is no row left to test: `all(... online)`
        is trivially true for a read missing half the cluster. We have not
        reproduced that on this hardware (a reboot does not do it), so treat
        this as a guard rather than a fix for an observed failure. It costs
        nothing when the count is unknown and it cannot invent a partial
        cycle, since expected can only be compared against nodes we did see.
      * an empty or truncated response. A resource list with no node rows in
        it is a broken read, never a genuinely empty cluster.

    Clearing all of that makes ONE cycle trustworthy, which is still not
    enough to delete anything: the caller additionally requires the absence to
    persist across trustworthy cycles for APP_REAP_AFTER_S, so even a
    plausible-looking bad read has to repeat for a quarter of an hour before a
    single row is removed. Restarting the backend does not shorten that
    window either -- the countdown lives in apps.missing_since, in the DB.
    """
    return (bool(node_rows) and not degraded and complete
            and all(r.get("status") == "online" for r in node_rows))


def ingest_cycle(db, host: Host, resources: list[dict],
                 rrd_by_node: dict[str, list[dict]], now: datetime,
                 version: str | None = None,
                 node_name: str | None = None,
                 cluster_name: str | None | object = UNREAD,
                 quorate: bool | None | object = UNREAD,
                 degraded: bool = False,
                 pools: PoolMemory | None = None,
                 status_rows: list[dict] | None = None) -> CycleResult:
    # A fresh PoolMemory has nothing to carry forward, so a caller that does
    # not keep one across cycles (every test that drives a single cycle) gets
    # exactly what this cycle's rows say.
    pools = pools if pools is not None else PoolMemory()
    events: list[tuple[str, dict]] = []
    samples: list[MetricSample] = []
    targets: list[dict] = []

    node_rows = [r for r in resources if r.get("type") == "node"]
    storage_rows = [r for r in resources if r.get("type") == "storage"]

    # Did this cycle see the whole cluster? A member that stops appearing in
    # /cluster/resources leaves no row behind to notice it by, so the only
    # check available is against the configured member count. /cluster/status
    # carries that whether or not the member is up: confirmed on hardware on
    # 2026-08-19, where `nodes` stayed 2 across a node reboot while that node's
    # own row read `online: 0`. Unknown (a standalone node, or a failed status
    # read) counts as complete: this must never make a healthy host look partial.
    expected = cluster_member_count(status_rows or [])
    complete = expected is None or len(node_rows) >= expected

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
            # Per node, not just folded into the host-level sum below: two
            # Hosts of one cluster each report the WHOLE cluster's nodes, so
            # the only way for /cluster/summary to add traffic up once is to
            # dedupe by node first and sum after.
            "net_in_bps": float(last.get("netin") or 0.0),
            "net_out_bps": float(last.get("netout") or 0.0),
        })
        net_in += float(last.get("netin") or 0.0)
        net_out += float(last.get("netout") or 0.0)

    # These two are SUMS over the nodes, so they are only a measurement when
    # every node is in them: a missing member halves the number and a node
    # whose rrddata 403'd (degraded) contributes a silent 0.0. Unlike disk_pct
    # there is nothing honest to carry forward, because throughput is a rate
    # rather than a level: last cycle's bytes are traffic that did not happen.
    # Only the recorded series is gated. The snapshot keeps the raw sum,
    # because it answers "what can this host see right now", and zeroing it
    # would trade a halved number in the cluster ring for an emptier one.
    sample_net_in = None if (degraded or not complete) else net_in
    sample_net_out = None if (degraded or not complete) else net_out

    # host.node_name is otherwise write-never: POST /hosts has no way to learn
    # it (PVE's /version carries no node name), so a host added through the
    # real wizard sat at NULL forever: /cluster/nodes and the VM-create
    # wizard's node picker both read this column directly, not the snapshot,
    # so they silently had nothing to offer. Only tests/support.py's
    # seed_host_row ever set it, which is why this never showed up until the
    # onboarding journey actually drove host creation through the UI (Task 16).
    # The guess from snap_nodes is written once: it is whichever node happened
    # to come first in /cluster/resources, so a real multi-node cluster's
    # actual "home" node for this Host row is not something it should
    # second-guess. `node_name` from the caller is not a guess: /cluster/status
    # marks the node at this host's own address, so it is refreshed every
    # cycle, for the same reason pve_version and cluster_name below are. A node
    # renamed in PVE otherwise keeps its old name here forever, and peer
    # discovery compares against this column to decide a node is already
    # enrolled. Falsy means the read failed or the cluster shape was
    # surprising, and a stale name beats a blank one.
    if node_name:
        host.node_name = node_name
    elif not host.node_name and snap_nodes:
        host.node_name = snap_nodes[0]["node"]

    # No fallback to snap_nodes[0]. host.node_name is always set by the block
    # above when this cycle has any node at all, so the fallback could only
    # ever fire when the named node was MISSING from the read -- and it then
    # recorded whichever node happened to come first in /cluster/resources as
    # this host's cpu_pct, mem_bytes and mem_pct. A different machine's numbers
    # under this host's identity is worse than no numbers.
    own = next((n for n in snap_nodes if n["node"] == host.node_name), None)
    if own:
        for metric, value in (("cpu_pct", own["cpu_pct"]),
                              ("mem_bytes", float(own["mem_bytes"])),
                              ("mem_pct", _mem_pct(own["mem_bytes"],
                                                   own["mem_total_bytes"])),
                              ("disk_pct", _disk_pct(storage_rows, pools, now)),
                              ("net_in_bps", sample_net_in),
                              ("net_out_bps", sample_net_out)):
            # None means this cycle could not measure that metric: disk_pct
            # with no readable datastore, net_*_bps with a node missing from
            # the sum. A gap in the series is the honest answer; a 0.0 there
            # reads as measured (the disks emptied, the traffic stopped) and
            # fires every alert written against it.
            if value is None:
                continue
            samples.append(MetricSample(target_type="host", target_id=host.id,
                                        metric=metric, value=value, ts=now))
        targets.append({"t": "host", "id": host.id, "cpu_pct": own["cpu_pct"],
                        "mem_pct": _mem_pct(own["mem_bytes"], own["mem_total_bytes"])})

    if host.status != "connected":
        events.append(("resource", {"type": "host", "id": host.id,
                                    "change": "status", "status": "connected"}))
    host.status, host.last_seen_at = "connected", now

    # An in-place PVE upgrade otherwise never reaches this column: it was
    # written at enrolment and by POST /hosts/{id}/test, and by nothing else.
    # The host page reads it for the header subline while the identity rail
    # reads the node's live /status, so the two disagreed after every upgrade
    # until somebody happened to click Test.
    #
    # `version is None` means the probe failed, not that the node has no
    # version — same shape as rrddata above. Writing it through would replace a
    # true-but-stale version with "unknown", which is strictly worse.
    if version and version != host.pve_version:
        host.pve_version = version

    # Cluster membership was written at enrolment and by nothing else, so
    # clustering two standalone hosts (or splitting a cluster) never reached
    # this column: both nodes went on reporting whatever they were when they
    # were added. Refreshed every cycle for the same reason pve_version is,
    # and guarded by UNREAD rather than a falsy check because standalone is a
    # legitimate value to write.
    if cluster_name is not UNREAD and cluster_name != host.cluster_name:
        host.cluster_name = cluster_name

    # Quorum, from the same /cluster/status read as the two above. UNREAD when
    # that read failed, since "we could not ask" must not overwrite a known
    # answer; None is a legitimate value to write (standalone, no cluster row).
    # Without quorum /etc/pve is read-only and every write fails while
    # /cluster/resources answers perfectly, so this is the only thing that
    # makes an unwritable host look different from a healthy one (doc 12
    # check 12).
    if quorate is not UNREAD and quorate != host.quorate:
        host.quorate = quorate

    # guests map ----------------------------------------------------------------
    guests: dict[tuple[str, int], dict] = {}
    for r in resources:
        if r.get("type") not in ("lxc", "qemu"):
            continue
        guests[(r["type"], int(r["vmid"]))] = {
            "name": r.get("name"), "node": r.get("node"),
            "status": r.get("status", "unknown"),
            # PVE reports 1 for a template and omits the key otherwise.
            "template": bool(r.get("template")),
            "cpu_pct": round(float(r.get("cpu") or 0.0) * 100, 1),
            "cpu_cores": int(r.get("maxcpu") or 0),
            "mem_bytes": int(r.get("mem") or 0),
            "mem_total_bytes": int(r.get("maxmem") or 0),
            "disk_bytes": int(r.get("maxdisk") or 0),
            # `disk` is USED, against `disk_bytes` above which is ALLOCATED.
            "disk_used_bytes": int(r.get("disk") or 0),
            "net_in": int(r.get("netin") or 0),
            "net_out": int(r.get("netout") or 0),
            "uptime_s": int(r.get("uptime") or 0),
        }

    # apps cache refresh (identity is ours; state is cached: doc 04) ----------
    trustworthy = _absence_is_trustworthy(node_rows, degraded, complete)
    reaped: list[App] = []
    mapped_ctids: set[int] = set()
    for a in db.query(App).filter_by(host_id=host.id).all():
        mapped_ctids.add(a.ctid)
        g = guests.get(("lxc", a.ctid))
        if g is None:
            if trustworthy:
                if a.missing_since is None:
                    a.missing_since = now
                elif (now - a.missing_since).total_seconds() >= APP_REAP_AFTER_S:
                    reaped.append(a)
                    continue
            # An untrustworthy cycle leaves missing_since exactly as it was:
            # it neither starts nor advances the countdown, and it must not
            # reset one either, or a host that flaps between good and degraded
            # cycles would never reap anything.
            if a.status_cached != "unknown":
                a.status_cached = "unknown"
                events.append(("resource", {"type": "app", "id": a.id,
                                            "change": "status", "status": "unknown"}))
            continue
        a.missing_since = None
        if a.status_cached != g["status"]:
            events.append(("resource", {"type": "app", "id": a.id,
                                        "change": "status", "status": g["status"]}))
        a.status_cached, a.cpu_pct_cached = g["status"], g["cpu_pct"]
        a.mem_bytes_cached, a.uptime_s_cached = g["mem_bytes"], g["uptime_s"]
        # 0 from PVE means "no reading", not "zero bytes used": a stopped
        # container reports 0 disk. None keeps that distinguishable from a
        # container that genuinely uses nothing.
        a.disk_bytes_cached = g["disk_used_bytes"] or None
        a.disk_total_bytes_cached = g["disk_bytes"] or None
        _update_net_rates(a, g, now)
        # Follows the guest: a CT migrated in the Proxmox UI rather than through
        # Proxploy changes node without the app row being rewritten, and every
        # call site then aimed at the host's node instead (doc 12 check 18).
        a.node_name = g["node"] or a.node_name
        samples.append(MetricSample(target_type="app", target_id=a.id,
                                    metric="cpu_pct", value=g["cpu_pct"], ts=now))
        samples.append(MetricSample(target_type="app", target_id=a.id,
                                    metric="mem_bytes", value=float(g["mem_bytes"]), ts=now))
        samples.append(MetricSample(target_type="app", target_id=a.id,
                                    metric="mem_pct",
                                    value=_mem_pct(g["mem_bytes"],
                                                   g["mem_total_bytes"]), ts=now))
        # ponytail: no disk_pct SAMPLE for apps or VMs. Apps now cache a disk
        # reading (disk_bytes_cached above), but that is a current value on
        # the row, not a series: /cluster/resources' `disk` field is
        # meaningful for LXC and routinely 0 for QEMU, so a guest disk_pct
        # series would be silently wrong for every VM. Task 12's rule
        # validation rejects disk_pct on app/vm targets with an explanatory
        # 422 instead.
        targets.append({"t": "app", "id": a.id, "cpu_pct": g["cpu_pct"],
                        "mem_pct": _mem_pct(g["mem_bytes"], g["mem_total_bytes"])})

    # vms cache upsert (droppable mirror: doc 04) ------------------------------
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
                   status=g["status"], node_name=g["node"],
                   template=g["template"])
            db.add(v)
            membership_changed = True
        elif v.status != g["status"]:
            events.append(("resource", {"type": "vm", "id": v.id,
                                        "change": "status", "status": g["status"]}))
        v.name = g["name"] or v.name
        # Refreshed every cycle, not only on insert: a cluster migration moves
        # the guest to another node and this is the only record of where it is
        # (doc 12 check 18).
        v.node_name = g["node"] or v.node_name
        # Refreshed every cycle: `qm template <id>` converts a guest in place,
        # so this changes without the row being recreated.
        v.template = g["template"]
        v.status, v.uptime_s, v.synced_at = g["status"], g["uptime_s"], now
        v.cpu_cores, v.mem_bytes, v.disk_bytes = (
            g["cpu_cores"], g["mem_total_bytes"], g["disk_bytes"])
    for vmid, v in existing.items():
        if vmid not in seen and trustworthy:
            # Same evidence rule the app loop above applies, and for the same
            # reason: with one cluster member down, that node's guests vanish
            # from /cluster/resources while the cycle otherwise looks healthy.
            # Deleting here took the alert rules with it, since targets_for()
            # resolves a vm rule to nothing once the row is gone and the orphan
            # sweep then resolves any firing alert as "target removed".
            # ponytail: no missing_since countdown for VMs like apps have, so a
            # trustworthy cycle still deletes at once. Add the column if a VM
            # is ever seen disappearing from a fully-online cluster.
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
        samples.append(MetricSample(target_type="vm", target_id=v.id,
                                    metric="mem_pct",
                                    value=_mem_pct(g["mem_bytes"],
                                                   g["mem_total_bytes"]), ts=now))
        targets.append({"t": "vm", "id": v.id, "cpu_pct": g["cpu_pct"],
                        "mem_pct": _mem_pct(g["mem_bytes"], g["mem_total_bytes"])})
    if membership_changed:
        events.append(("resource", {"type": "vm", "change": "list"}))

    # discovered CTs + adoption heuristic (NOT auto-adopted: Phase 4 owns that)
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
         "total_bytes": int(r.get("maxdisk") or 0),
         # These four ride on the SAME /cluster/resources row the two above come
         # from: the poller used to discard them. Reading them here is what
         # lets GET /storage answer from the snapshot instead of adding a
         # per-datastore PVE call, which doc 02 §3's O(nodes) budget forbids.
         "type": r.get("plugintype"),
         "content": [c for c in str(r.get("content") or "").split(",") if c],
         "shared": bool(r.get("shared")),
         "status": r.get("status") or "unknown"}
        for r in storage_rows
    ]

    # Reaping: the CT behind these apps is gone, so the app is gone. The row is
    # DELETED rather than flagged, which is what makes it disappear everywhere
    # at once (GET /apps, the host page's app list, and the per-host app counts
    # on /cluster/nodes all read the apps table directly, so there is nothing
    # to teach about a new "orphaned" state). A re-created CT with the same
    # ctid comes back as a `discovered` container and can be adopted, which is
    # the recovery path that already exists.
    for a in reaped:
        log.warning("host %s (%s): CT %s behind app '%s' has been absent since "
                    "%s; removing the app record", host.id, host.name, a.ctid,
                    a.name, a.missing_since)
        # Audited because this is Proxploy deleting a user's record on its own
        # initiative; write_audit commits, which is why the reap block sits
        # here rather than inside the apps loop above.
        write_audit(db, actor_type="system", action="app.reaped",
                    target_type="app", target_id=a.id,
                    params={"ctid": a.ctid, "host_id": host.id,
                            "missing_since": to_iso(a.missing_since)})
        events.append(("resource", {"type": "app", "id": a.id,
                                    "change": "removed"}))
        db.delete(a)
    if reaped:
        # Node cards count apps per host (api/cluster.py::cluster_nodes) and
        # the hosts page reads those counts; only a `host` resource event
        # invalidates that cache on the client, an `app` one does not.
        events.append(("resource", {"type": "host", "id": host.id,
                                    "change": "apps"}))

    write_samples(db, samples)
    db.commit()

    events.insert(0, ("metrics", {"targets": targets}))
    snapshot = HostSnapshot(host_id=host.id, ts=now, nodes=snap_nodes,
                            storage=snap_storage,
                            guests=guests, discovered=discovered)
    return CycleResult(snapshot=snapshot, events=events)


class Poller:
    """Supervisor + one long-lived task per host (doc 02 §3).

    All blocking work (proxmoxer, SQLAlchemy) runs in asyncio.to_thread with a
    per-host timeout, so one slow/dead host can never stall the event loop or
    its sibling loops.
    """

    def __init__(self, app) -> None:
        self.app = app
        self.snapshots: dict[int, HostSnapshot] = {}
        self._tasks: dict[int, asyncio.Task] = {}
        # host_id -> when its tokens were last checked against their roles. In
        # memory on purpose: a restart re-checks straight away.
        self._gaps_checked_at: dict[int, datetime] = {}
        # host_id -> the datastore sizes disk_pct divides by. Has to outlive a
        # cycle or a pool that drops out of one read moves the percentage; see
        # PoolMemory.
        self._pools: dict[int, PoolMemory] = {}

    async def run(self) -> None:
        interval = self.app.state.settings.poll_interval_s
        while True:
            try:
                ids = await asyncio.to_thread(self._host_ids)
                for hid in ids:
                    if hid not in self._tasks or self._tasks[hid].done():
                        self._tasks[hid] = asyncio.create_task(self._host_loop(hid))
                for hid in list(self._tasks):
                    if hid not in ids:
                        self._tasks.pop(hid).cancel()
                        self.snapshots.pop(hid, None)
                        self._pools.pop(hid, None)
            except Exception:  # noqa: BLE001  (supervisor never dies)
                pass
            # Doc 10 Phase 7: "alert_rules CRUD + evaluator riding the poll
            # loop". Here rather than in _host_loop: this supervisor already
            # ticks exactly once per interval no matter how many hosts exist,
            # and every rule's answer is global: evaluating per host would be
            # N times the queries for the same result. Wrapped separately from
            # the block above so an alerting failure can never stop the
            # supervisor from (re)spawning host loops.
            if self.app.state.settings.alerts_enabled:
                await self._evaluate_alerts()
            await asyncio.sleep(interval)

    async def _evaluate_alerts(self) -> None:
        """Evaluate, publish on the loop, notify off it.

        `evaluate` and `notify_transitions` are blocking (SQLAlchemy, then
        Apprise's ~8 s-per-channel network I/O) so both go to a thread;
        `bus.publish` runs on the loop, matching _poll_once's contract that a
        worker thread returns events rather than publishing them itself.

        The SSE publish happens BEFORE notification and in its own try: a dead
        webhook must not cost the UI its badge update.
        """
        from proxploy.services import alerts as alerts_svc

        try:
            def work():
                with self.app.state.sessionmaker() as db:
                    return alerts_svc.evaluate(db, utcnow())

            transitions = await asyncio.to_thread(work)
        except Exception:  # noqa: BLE001  (one bad pass, not the end of polling)
            return
        if not transitions:
            return
        for t in transitions:
            self.app.state.bus.publish("alert", alerts_svc.sse_frame(t))
        try:
            await asyncio.to_thread(alerts_svc.notify_transitions, self.app,
                                    transitions)
        except Exception:  # noqa: BLE001  (a notification is a courtesy)
            pass

    def stop(self) -> None:
        for t in self._tasks.values():
            t.cancel()
        self._tasks.clear()

    def _host_ids(self) -> list[int]:
        with self.app.state.sessionmaker() as db:
            return [h.id for h in db.query(Host).all()]

    async def _host_loop(self, host_id: int) -> None:
        settings = self.app.state.settings
        fails = 0
        while True:
            try:
                events = await asyncio.wait_for(
                    asyncio.to_thread(self._poll_once, host_id),
                    timeout=settings.poll_timeout_s)
                fails = 0
                for name, data in events:
                    self.app.state.bus.publish(name, data)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001  (degrade this host only)
                fails += 1
                # This used to swallow the exception whole. A 403 on a
                # privilege the token was never granted, a TLS failure and a
                # genuinely dead node all became the bare word "unreachable",
                # with nothing logged, so there was no way to tell them apart
                # from either the UI or the server log.
                reason = (f"{type(e).__name__}: {e}" if str(e)
                          else f"{type(e).__name__} (no detail)")
                log.warning("host %s poll failed (attempt %s): %s",
                            host_id, fails, reason, exc_info=fails == 1)
                unreachable_events = await asyncio.to_thread(
                    self._mark_unreachable, host_id, reason)
                for evt in unreachable_events:
                    self.app.state.bus.publish(*evt)
            delay = (min(settings.poll_interval_s * (2 ** min(fails, 4)),
                         POLL_BACKOFF_CAP_S)
                     if fails else settings.poll_interval_s)
            await asyncio.sleep(delay)

    def _poll_once(self, host_id: int) -> list[tuple[str, dict]]:
        """Blocking: one full cycle for one host. Runs in a worker thread."""
        app = self.app
        with app.state.sessionmaker() as db:
            host = db.get(Host, host_id)
            if host is None:
                return []
            # Monitoring is the one capability every enrolled host is
            # guaranteed to have (mandatory at enrolment, api/hosts.py::
            # create_host), so the poller keeps reading it directly rather
            # than going through client_for_host's capability="monitoring"
            # default; this is the same row, just addressed the way it has
            # always been addressed, renamed per the per-capability token
            # encoding (host-token-privileges-step-one-report.md).
            cred = (db.query(HostCredential)
                    .filter_by(host_id=host.id, kind="api_token:monitoring").one())
            tok = jsonlib.loads(app.state.secretstore.decrypt(cred.encrypted_blob))
            client = ProxmoxClient(host.address, tok["token_id"], tok["token_secret"],
                                  verify_tls=host.verify_tls,
                                  tls_fingerprint=host.tls_fingerprint,
                                  factory=app.state.proxmox_factory)
            resources = client.cluster_resources()
            node_names = [r["node"] for r in resources if r.get("type") == "node"]
            # Metrics are the optional half of a cycle. On real hardware a
            # privsep token that can read /cluster/resources still 403s on
            # /nodes/<n>/rrddata (Sys.Audit), and letting that escape cost the
            # whole cycle: discovery, node_name and status all went with it,
            # and the host was reported unreachable while answering fine.
            rrd, lost = {}, []
            for n in node_names:
                try:
                    rrd[n] = client.node_rrddata(n)
                except ProxmoxError as e:
                    lost.append(f"{n}: {e}")
            degraded = (f"metrics unavailable, {'; '.join(lost)}" if lost else None)

            # Optional, like rrddata above: a token that reads
            # /cluster/resources can still 403 on /version, and losing the
            # version refresh must not cost the cycle. None means "not read
            # this time", and ingest_cycle keeps the version it already had.
            try:
                version = client.version().get("version")
            except ProxmoxError:
                version = None

            # Optional in exactly the way version() above is: one extra
            # constant-cost call per host per cycle, which the doc 02 section 3
            # budget allows (it forbids per-GUEST calls, not per-host ones).
            try:
                status_rows = client.cluster_status()
                node_name, cluster_name = cluster_identity_from(status_rows)
                quorate = cluster_quorate(status_rows)
            except ProxmoxError:
                status_rows = []
                node_name, cluster_name, quorate = None, UNREAD, UNREAD

            # Privilege drift, on a slow cadence (see the interval above). Best
            # effort in every direction: a failure here must not cost the cycle,
            # since this is a warning about tokens, not the poll itself.
            last = self._gaps_checked_at.get(host_id)
            if last is None or (utcnow() - last).total_seconds() >= CAPABILITY_GAP_INTERVAL_S:
                try:
                    host.capability_gaps = capability_gaps(app, db, host)
                    self._gaps_checked_at[host_id] = utcnow()
                    db.commit()
                except Exception:  # noqa: BLE001
                    log.debug("capability gap probe failed for host %s", host_id,
                              exc_info=True)

            prev = self.snapshots.get(host_id)
            result = ingest_cycle(db, host, resources, rrd, utcnow(),
                                  version=version, node_name=node_name,
                                  cluster_name=cluster_name, quorate=quorate,
                                  degraded=bool(degraded),
                                  pools=self._pools.setdefault(host_id, PoolMemory()),
                                  status_rows=status_rows)
            # ingest_cycle owns status/last_seen_at, so this is set after it and
            # committed below with the rest of the cycle. A clean cycle clears
            # it, or a one-off blip would look permanent.
            if host.last_error != degraded:
                host.last_error = degraded
                db.commit()
            if degraded:
                log.warning("host %s (%s) polled with degraded data: %s",
                            host_id, host.name, degraded)
            events = result.events
            if prev is not None and (
                    {d["ctid"] for d in prev.discovered}
                    != {d["ctid"] for d in result.snapshot.discovered}):
                events.append(("resource", {"type": "app", "change": "discovered"}))
            self.snapshots[host_id] = result.snapshot
            return events

    def _mark_unreachable(self, host_id: int, reason: str = "") -> list[tuple[str, dict]]:
        """Every failed cycle lands here, so this is also the one place that
        already knows a host is gone and already holds a session on it. The
        cached status/metric columns on App and Vm are exactly what
        cluster.py's running counts, consoles.py's launch guard and
        backups.py's target picker all read, and none of those four call
        sites ever finds out the host went away: ingest_cycle, the only other
        writer of those columns, never runs for a host that raised before it
        got there. Clearing the cache here, once, is correct for all four
        readers; a guard added at each of them instead could drift out of
        sync with the other three.

        The host loop keeps retrying a dead host forever, just slower each
        time (the backoff above), so this runs on every one of those retries,
        including every retry after a backend restart that comes back to a
        host still down. The host's own status flip to "unreachable" is only
        worth an SSE event on the transition (the `already` check below), but
        the guest sweep cannot use that same host-level flag to decide
        whether it has work to do: a guest can be left stale by a restart
        even though the host row already reads "unreachable" from before the
        restart. So the sweep runs every call, and each guest is checked on
        its own: a guest already fully cleared (status unknown and every
        cached reading already null) is skipped with no write and no event,
        which is what stops a dead host retrying every cycle from restating
        the same rows or republishing the same events forever. A guest whose
        status already reads unknown but still has a stale reading (set by
        ingest_cycle's own absence path, or left over some other way) is not
        considered cleared and gets its readings nulled too.
        """
        with self.app.state.sessionmaker() as db:
            host = db.get(Host, host_id)
            if host is None:
                return []
            already = host.status == "unreachable"
            host.status = "unreachable"
            # Written even when the status is unchanged: the reason can change
            # between cycles (a timeout becoming a 403), and the operator needs
            # the current one, not the first one ever recorded.
            host.last_error = reason or None

            events: list[tuple[str, dict]] = []
            if not already:
                events.append(("resource", {"type": "host", "id": host_id,
                                            "change": "status", "status": "unreachable"}))

            for a in db.query(App).filter_by(host_id=host_id).all():
                already_cleared = (
                    a.status_cached == "unknown"
                    and a.cpu_pct_cached is None
                    and a.mem_bytes_cached is None
                    and a.uptime_s_cached is None
                    and a.disk_bytes_cached is None
                    and a.disk_total_bytes_cached is None
                    and a.net_in_bps_cached is None
                    and a.net_out_bps_cached is None
                )
                if already_cleared:
                    continue
                if a.status_cached != "unknown":
                    events.append(("resource", {"type": "app", "id": a.id,
                                                "change": "status", "status": "unknown"}))
                a.status_cached = "unknown"
                # A stale reading here is the same lie a stale "running" is:
                # nobody knows this app's CPU, memory, disk or uptime while
                # its host cannot be reached.
                a.cpu_pct_cached = None
                a.mem_bytes_cached = None
                a.uptime_s_cached = None
                a.disk_bytes_cached = None
                a.disk_total_bytes_cached = None
                a.net_in_bps_cached = None
                a.net_out_bps_cached = None
                # net_in_cached, net_out_cached and net_sampled_at are left
                # exactly as they were. They are not a reading shown to
                # anyone, only the raw counters _update_net_rates diffs
                # against, and that function already treats a stale
                # net_sampled_at correctly on its own: if the guest rebooted
                # with its host (the common case, since "host unreachable"
                # usually means the hardware is off), PVE's counters reset to
                # a value below what is stored here and the existing
                # now_in < prev_in guard throws the rate away for one cycle,
                # same as any other reboot. If the guest somehow kept running
                # untouched through the outage, the counters kept climbing
                # and the first post-recovery rate is a genuine average over
                # the outage window, not a fabricated spike, so there is
                # nothing here worth guarding against. Nulling net_sampled_at
                # instead would only turn that second, harmless case into a
                # silently wrong one for one extra cycle, for no benefit in
                # the common case.

            for v in db.query(Vm).filter_by(host_id=host_id).all():
                if v.status == "unknown" and v.uptime_s is None:
                    continue
                if v.status != "unknown":
                    events.append(("resource", {"type": "vm", "id": v.id,
                                                "change": "status", "status": "unknown"}))
                v.status = "unknown"
                # cpu_cores, mem_bytes and disk_bytes are the guest's
                # configured allocation (maxcpu/maxmem/maxdisk), not a live
                # measurement, so they stay true whether or not the host can
                # be reached right now. uptime_s is the one live reading Vm
                # caches (how long the guest has been up), and that becomes
                # exactly as wrong as App's status the moment the host stops
                # answering.
                v.uptime_s = None

            db.commit()
            return events
