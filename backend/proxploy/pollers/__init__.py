"""Poller subsystem.

ingest_cycle() is the pure-ish core: given one host's bulk reads it updates
caches, batches metric samples (ONE commit per cycle), and returns the fresh
in-memory snapshot plus the SSE deltas to publish. The Poller class (task
loops, backoff, degradation) lives below it and is the only caller.
"""
from __future__ import annotations

import asyncio
import json as jsonlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import or_ as sa_or

from proxploy.services.lifecycle import freshly_confirmed
from proxploy.models import (App, CatalogEntry, Host, HostCredential, Job,
                             MetricSample, Vm, to_iso, utcnow)
from proxploy.services.audit import write_audit
from proxploy.services.hostclient import (capability_gaps,
                                          cluster_identity_from,
                                          cluster_member_count,
                                          cluster_quorate)
from proxploy.services.metrics import write_samples
from proxploy.services.proxmox import (ProxmoxClient, ProxmoxError,
                                       routable_addresses)

POLL_BACKOFF_CAP_S = 300

# How often the poll loop re-checks each host's tokens against their roles.
# Not every cycle: it costs one /access/permissions per configured token, and
# privileges change when an operator re-runs the setup script, not every 30
# seconds. Kept in memory, so a restart re-checks immediately, which is the
# useful direction.
CAPABILITY_GAP_INTERVAL_S = 1800

# Two things opt out of the cycle's 5s cadence.
#
# RRD_INTERVAL_S: node network throughput exists only in PVE's RRD, whose
# finest series buckets at exactly 60s (measured on node1: 59 points, 60s
# apart). Between fetches the last answer is carried forward, because the
# reading is still the current one, not a gap.
#
# METRIC_SAMPLE_INTERVAL_S: the charts read MetricSample, and its resolution
# is a storage decision, not a freshness one. At 5s the table would take six
# times the rows to draw the same lines. The UI's live numbers come off the
# snapshot and the cached columns, which DO refresh every cycle.
RRD_INTERVAL_S = 60
METRIC_SAMPLE_INTERVAL_S = 30

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


def _update_net_rates(row: App | Vm, g: dict, now: datetime) -> None:
    """Turn this cycle's netin/netout counters into a rate on a guest row.

    Shared by the app and VM blocks below, which is why Vm carries App's net_*
    column names: PVE reports both guest types the same way.

    PVE reports bytes since the guest booted, so a rate is a diff against the
    previous reading over the time between the two, and both the reading and
    its timestamp are stored for the next cycle.

    Two cases produce no rate rather than a wrong one: a first reading has
    nothing to diff against, and a guest restart zeroes the counters, so the
    delta goes negative and its absolute value would draw a fabricated traffic
    spike at exactly the moment an operator is watching. Either way the rate is
    None for one cycle and recovers on the next.
    """
    prev_in, prev_out, prev_at = (row.net_in_cached, row.net_out_cached,
                                  row.net_sampled_at)
    now_in, now_out = g["net_in"], g["net_out"]
    elapsed = (now - prev_at).total_seconds() if prev_at else 0.0
    if prev_in is None or prev_out is None or elapsed <= 0:
        row.net_in_bps_cached = row.net_out_bps_cached = None
    elif now_in < prev_in or now_out < prev_out:
        row.net_in_bps_cached = row.net_out_bps_cached = None
    else:
        row.net_in_bps_cached = (now_in - prev_in) / elapsed
        row.net_out_bps_cached = (now_out - prev_out) / elapsed
    row.net_in_cached, row.net_out_cached, row.net_sampled_at = now_in, now_out, now


# How often a container's address is re-read, and why it is not every cycle.
#
# /cluster/resources carries NO address field for an lxc row (confirmed
# against PVE 9.2.10 on 2026-08-20), so an address costs one per-container
# call, which doc 02 section 3's budget forbids doing every cycle.
#
# A container with no known address is asked on the very next cycle, so a
# freshly adopted app shows its address within one interval and a DHCP lease
# that has not landed keeps being retried. One that already has an address is
# asked again only every 15 minutes, which bounds how long a renumbered
# container can show its old one.
#
# Kept in memory rather than in a column: a restart re-reads every address
# straight away, and it saves a migration for a value nothing else reads.
APP_IP_REFRESH_INTERVAL_S = 900


def _refresh_ip(a: App, g: dict, client, checked: dict[int, datetime],
                now: datetime) -> bool:
    """Keep `a.ip_cached` current. Returns True when the address changed.

    The rule everywhere here is: write through what we KNOW, hold what we
    could not ask.

      * a container that is not running has no address. That is an answer, so
        it is written through as None. It also drops out of `checked`, so
        starting it again reads the new address on the next cycle rather than
        up to 15 minutes later, which matters because a DHCP container
        usually comes back on a different lease.
      * lxc_interfaces() returning None means PVE would not tell us. That is a
        gap, so the last known address stands untouched, the same rule
        _mark_unreachable applies to this column.
      * PVE answering with no routable address (a lease that has not arrived,
        or only loopback and link-local) IS an answer, so it clears the column
        and the next cycle asks again.
    """
    if g["status"] != "running":
        checked.pop(a.id, None)
        if a.ip_cached is None:
            return False
        a.ip_cached = None
        return True
    if client is None:
        return False
    last = checked.get(a.id)
    if a.ip_cached and last and (now - last).total_seconds() < APP_IP_REFRESH_INTERVAL_S:
        return False
    rows = client.lxc_interfaces(g["node"] or a.node_name, a.ctid)
    if rows is None:
        return False
    checked[a.id] = now
    found = [addr for r in rows for addr in routable_addresses(r)]
    # Stored bare, without the prefix length: this column is what the app card
    # shows and what an operator copies into a browser, and "/24" is neither.
    # IPv4 wins when a container has both, because routable_addresses reads
    # `inet` before `inet6` on each row.
    ip = found[0].split("/")[0] if found else None
    if ip == a.ip_cached:
        return False
    a.ip_cached = ip
    return True


# How often a VM's filesystem usage is re-read from its guest agent, and why
# it is not every cycle.
#
# /cluster/resources has a `disk` field and for a QEMU guest it is routinely a
# flat 0: the hypervisor sees a block device, not the filesystem written into
# it (measured on the lab cluster, PVE 9.2.10: VM 108 running, maxdisk
# 34359738368, `disk: 0`). So `maxdisk` is the allocation and the only honest
# source for usage is the guest itself, via
# /nodes/{node}/qemu/{vmid}/agent/get-fsinfo, a per-VM call doc 02 section 3's
# budget forbids doing every cycle.
#
# The cadence gate is PURELY time-based, which is where this differs from
# _refresh_ip. A missing address is usually a DHCP lease about to arrive; a
# missing disk reading usually means the guest agent is NOT INSTALLED, which
# never resolves on its own, so retrying every cycle would cost a call per VM
# forever and buy nothing. A stopped VM is not asked at all and drops out of
# the map, so starting one is measured on the next cycle.
#
# Kept in memory rather than in a column: a restart re-reads every VM straight
# away.
VM_DISK_REFRESH_INTERVAL_S = 900


def _refresh_vm_disk(v: Vm, g: dict, client, checked: dict[int, datetime],
                     now: datetime) -> None:
    """Keep `v.disk_bytes` (USED bytes) and `v.guest_agent_ok` current.

    Both come out of ONE get-fsinfo call, because whether the agent answered is
    something that call already knew. See ProxmoxClient.agent_fsinfo.

    Unlike an address, filesystem usage is a live MEASUREMENT, so "we could not
    ask" is written through as None rather than held. That is why the column
    stays NULL rather than dropping to 0 for the many VMs that will never have
    an agent: the UI renders unknown instead of an empty disk bar under a full
    one, and nothing is logged or marked degraded.

    guest_agent_ok follows the same rule with one difference: it is only ever
    written when the probe produced a verdict. A probe that failed for a reason
    PVE did not attribute to the agent leaves the previous verdict standing,
    because a connection error says nothing about what is installed inside the
    guest.
    """
    if g["status"] != "running":
        # No agent runs in a guest that is not running, so there is nothing to
        # ask and nothing to hold. Dropping out of `checked` is what makes a
        # VM that gets started measured on the next cycle.
        checked.pop(v.id, None)
        v.disk_bytes = None
        # Unknown, NOT False. A stopped guest cannot answer whatever it has
        # installed, so "no guest agent" here would be a claim nobody checked,
        # and an operator reading it would go install something that is
        # already there. The verdict comes back on the cycle after it starts.
        v.guest_agent_ok = None
        return
    if client is None:
        return
    last = checked.get(v.id)
    # The cadence gate is skipped while the verdict is unknown, mirroring what
    # _refresh_ip does for a container with no address yet. An unknown verdict
    # means the last probe never reached PVE, so waiting out 15 minutes would
    # leave a brand new VM, or every VM on a host that has just come back,
    # reading "unknown" for a quarter of an hour when one cheap call settles
    # it. Once the answer is True or False it is a fact about the guest, not a
    # measurement, and rides the same 15 minute cadence as the bytes.
    # ponytail: a host that keeps failing this call for some reason PVE never
    # attributes to the agent gets asked once per VM per cycle. Bound it with a
    # short retry interval if that is ever seen, rather than pre-emptively.
    if (v.guest_agent_ok is not None and last
            and (now - last).total_seconds() < VM_DISK_REFRESH_INTERVAL_S):
        return
    # Recorded before the answer is looked at, on purpose: a VM with no agent
    # must wait out the same interval as one with a working agent, or the
    # common case becomes the expensive one. See the constant above.
    checked[v.id] = now
    agent_ok, used = client.agent_fsinfo(g["node"] or v.node_name, v.vmid)
    v.disk_bytes = used
    if agent_ok is not None:
        v.guest_agent_ok = agent_ok


def _refresh_os_type(v: Vm, g: dict, client) -> None:
    """Fill in `v.os_type` once, from the guest's config.

    /cluster/resources carries no ostype (confirmed on the lab cluster, PVE
    9.2.10, 2026-08-20), so this costs a per-VM config read.

    THE CADENCE IS "ONCE", not a slow refresh, and that is what makes it fit
    the budget: ostype is fixed at create time and only changes if somebody
    hand-edits the config, so a known value is never re-read. Steady state for
    an established fleet is ZERO calls. Deliberately unlike _refresh_ip, which
    re-asks on a timer because a DHCP lease genuinely moves under you. The
    consequence: a guest whose ostype is edited by hand in the Proxmox UI
    keeps the old value here until the row is recreated.

    A failed read leaves the column NULL and the cycle otherwise untouched,
    and is retried next cycle, which is free: the only VMs asked at all are
    the ones still missing a value.

    PVE's RAW value is stored (`l26`, `win11`, `other`, ...), deliberately not
    collapsed to "linux"/"windows": that mapping is the client's job, and
    doing it here throws away a value the API cannot recover.
    """
    if v.os_type or client is None:
        return
    try:
        cfg = client.guest_config("qemu", g["node"] or v.node_name, v.vmid)
    except ProxmoxError:
        return
    # `or None` rather than the bare get: PVE omitting the key and PVE
    # answering with an empty string both mean "no answer", and an empty
    # string stored here would look like a known ostype and stop this from
    # ever asking again.
    v.os_type = cfg.get("ostype") or None


# How long a datastore has to stay out of the reads before it stops counting
# against disk_pct. 15 minutes, and for the same reason APP_REAP_AFTER_S is 15
# minutes: far longer than any burst of bad reads, short enough that a pool an
# operator really did remove is out of the percentage while they are still
# looking at the graph.
POOL_FORGET_AFTER_S = 900


def storage_snapshot_rows(resources: list[dict]) -> list[dict]:
    """The snapshot's storage shape, from raw /cluster/resources rows.

    `type`, `content`, `shared` and `status` ride on the SAME row the two
    byte counts come from, and reading them here is what lets GET /storage
    answer from the snapshot instead of adding a per-datastore PVE call,
    which doc 02 §3's O(nodes) budget forbids.

    Module-level and shared with api/storage.py, which rebuilds these rows
    after a mutation rather than waiting out a poll interval. One transform,
    one shape: a second copy that wrote RAW resource rows had every datastore
    reporting type "storage" and 0 bytes until the next cycle corrected it.
    """
    return [
        {"storage": r.get("storage"), "node": r.get("node"),
         "used_bytes": int(r.get("disk") or 0),
         "total_bytes": int(r.get("maxdisk") or 0),
         "type": r.get("plugintype"),
         "content": [c for c in str(r.get("content") or "").split(",") if c],
         "shared": bool(r.get("shared")),
         "status": r.get("status") or "unknown"}
        for r in resources if r.get("type") == "storage"
    ]


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

    Without it the storage graph flaps: confirmed on the real cluster
    (2026-08-19) by restricting one empty 1.8 TB pool away from its node,
    disk_pct went 11.6% -> 27.6% -> 11.6% with no byte changed.

    A cycle loses storage rows for reasons that have nothing to do with the
    disks, and none look like an error at the call site: a member dropping out
    during a corosync split takes its pools with it, so the two Hosts of one
    cluster report different numbers for the same disks; PVE keeps listing a
    datastore whose mount is down but stops filling in disk/maxdisk, which read
    literally is a zero-byte pool; and a token that loses Datastore.Audit makes
    EVERY storage row disappear at once, once recorded as a flat 0.0%.

    A percentage is only a measurement if its denominator holds still, so a
    pool absent from this cycle keeps the last size we actually measured: an
    unreachable disk still holds the bytes it held. Kept in memory per host, so
    the first cycle after a restart reports what it can read.
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
    ring error, it is an alert that fires at the wrong number.

    None means "no datastore has been readable recently", a gap in the series
    rather than a host whose disks are 0% full.
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
    least four causes and only one is "somebody destroyed it":

      * the host was unreachable. That cannot reach here at all: _poll_once
        raises before ingest_cycle, and _host_loop turns the raise into
        status=unreachable without ever calling us.
      * the cycle was degraded (a read 403'd, timed out, or came back short).
        A half-answer is not evidence of anything, so we hold what we have.
      * a CLUSTER MEMBER is down. This is the dangerous one: the endpoint we
        asked answered fine, the host is "connected", the cycle is not
        degraded, and an entire node's worth of guests has silently dropped
        out. App rows carry host_id + ctid and no node, so "this app lived on
        the node that just went down" and "this app was destroyed" look
        identical; the only safe move is to distrust the whole cycle unless
        every node in it reports online.

        `complete` covers the hole in that check. A node that goes down KEEPS
        its row and flips it to `status: "offline"` (measured on hardware,
        2026-08-19), so the online test already catches an ordinary outage.
        What it cannot catch is a member that stops appearing at all, since
        then there is no row left to test. That has not been reproduced here,
        so it is a guard rather than a fix, and it costs nothing when the
        member count is unknown.
      * an empty or truncated response. A resource list with no node rows is a
        broken read, never a genuinely empty cluster.

    One trustworthy cycle is still not enough to delete anything: the caller
    additionally requires the absence to persist across trustworthy cycles for
    APP_REAP_AFTER_S, and a backend restart does not shorten that window, since
    the countdown lives in apps.missing_since.
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
                 status_rows: list[dict] | None = None,
                 client=None,
                 ip_checked: dict[int, datetime] | None = None,
                 fs_checked: dict[int, datetime] | None = None,
                 record_samples: bool = True) -> CycleResult:
    # A fresh PoolMemory has nothing to carry forward, so a caller that does
    # not keep one across cycles gets exactly what this cycle's rows say.
    pools = pools if pools is not None else PoolMemory()
    # Guests a targeted per-guest read has just confirmed. This cycle's
    # /cluster/resources answer was taken BEFORE that read and lags a finished
    # task by seconds, so writing `status` for these would put them back to
    # their pre-action state and re-engage the hold. Newer reading wins;
    # everything else this cycle measures is still written.
    fresh = freshly_confirmed(db, now)
    # `client` is optional so the bulk-read-in, caches-out contract still
    # holds without one: no client means addresses are simply not refreshed
    # this cycle, everything else behaves identically. `ip_checked` is the
    # per-app "last asked at" behind APP_IP_REFRESH_INTERVAL_S; a caller that
    # does not keep one across cycles asks every time. `fs_checked` is the
    # same thing for VM_DISK_REFRESH_INTERVAL_S, keyed on vm id rather than
    # app id, which is why it cannot share ip_checked's map.
    ip_checked = ip_checked if ip_checked is not None else {}
    fs_checked = fs_checked if fs_checked is not None else {}
    events: list[tuple[str, dict]] = []
    samples: list[MetricSample] = []
    targets: list[dict] = []

    node_rows = [r for r in resources if r.get("type") == "node"]
    storage_rows = [r for r in resources if r.get("type") == "storage"]

    # Did this cycle see the whole cluster? A member that stops appearing in
    # /cluster/resources leaves no row to notice it by, so the only check is
    # against the configured member count, which /cluster/status carries
    # whether or not the member is up (confirmed on hardware: `nodes` stayed 2
    # across a node reboot while that node's own row read `online: 0`).
    # Unknown counts as complete: this must never make a healthy host look
    # partial.
    expected = cluster_member_count(status_rows or [])
    complete = expected is None or len(node_rows) >= expected

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
    # whose rrddata 403'd contributes a silent 0.0. Nothing honest can be
    # carried forward, because throughput is a rate: last cycle's bytes are
    # traffic that did not happen. Only the recorded series is gated, since
    # the snapshot answers "what can this host see right now".
    sample_net_in = None if (degraded or not complete) else net_in
    sample_net_out = None if (degraded or not complete) else net_out

    # host.node_name is otherwise write-never: POST /hosts has no way to learn
    # it (PVE's /version carries no node name), so a host added through the
    # real wizard sat at NULL forever while /cluster/nodes and the VM-create
    # wizard's node picker read this column directly, not the snapshot. The
    # snap_nodes guess is written once and only as a fallback: it is whichever
    # node came first in /cluster/resources, which is not a real cluster's
    # "home" node. `node_name` from the caller is not a guess (/cluster/status
    # marks the node at this host's own address) so it is refreshed every
    # cycle: a node renamed in PVE otherwise keeps its old name here forever,
    # and peer discovery compares against this column to decide a node is
    # already enrolled. Falsy means the read failed, and a stale name beats a
    # blank one.
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
    # written at enrolment and by POST /hosts/{id}/test, and by nothing else,
    # so the host page's header subline and the identity rail's live /status
    # disagreed after every upgrade.
    #
    # `version is None` means the probe failed, not that the node has no
    # version. Writing it through would replace a true-but-stale version with
    # "unknown", which is strictly worse.
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
    # answer; None is legitimate (standalone, no cluster row). Without quorum
    # /etc/pve is read-only and every write fails while /cluster/resources
    # answers perfectly, so this is the only thing that makes an unwritable
    # host look different from a healthy one.
    if quorate is not UNREAD and quorate != host.quorate:
        host.quorate = quorate

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
        # Always written, mid-action or not. This column is the OBSERVATION,
        # and busy_guests reads it to decide when an action has actually
        # landed, so skipping the write while a guest is held deadlocked the
        # two: the poller would not write because the guest was held, and the
        # hold would not lift because the poller had not written. A guest
        # stopped on the node sat on "Working" for ever.
        #
        # Nothing is lost by writing it. The API never serves this column raw
        # during an action; api/apps.py::_app_out puts busy_guests over the
        # top, which is where "do not show a stale running" is enforced now.
        if ("app", a.id) in fresh:
            a.cpu_pct_cached = g["cpu_pct"]
        else:
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
        if _refresh_ip(a, g, client, ip_checked, now):
            # No `status` on this one: it is not a status change, and the
            # client's applyResource falls through an unrecognised `change` to
            # a plain refetch of the apps list, which is exactly right here.
            events.append(("resource", {"type": "app", "id": a.id,
                                        "change": "ip"}))
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
        elif v.status != g["status"] and ("vm", v.id) not in fresh:
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
        # Written every cycle, held or not, for the reason spelled out in the
        # app branch above: busy_guests releases on this value, so a poller
        # that declines to write it while the guest is held can never release
        # it. The hold lives in the API's overlay, not in a gap in the truth.
        # `fresh` is the one exception, and it is not a hold: it is a newer
        # reading of the same column outranking this older one.
        if ("vm", v.id) not in fresh:
            v.status = g["status"]
        v.uptime_s = g["uptime_s"]
        # ALLOCATION, against the short names mem_bytes and disk_bytes which
        # mean USAGE on both App and Vm. Migration a1f4d80c3e69 split the two
        # apart; before it these names held the allocation.
        v.cpu_cores, v.mem_total_bytes = g["cpu_cores"], g["mem_total_bytes"]
        # Same honesty rule as the app block above: 0 from PVE means "no
        # reading". A stopped guest reports mem 0, and a maxdisk of 0 is a row
        # we could not read rather than a VM with no disk.
        v.mem_bytes = g["mem_bytes"] or None
        v.disk_total_bytes = g["disk_bytes"] or None
        _update_net_rates(v, g, now)
    for vmid, v in existing.items():
        if vmid not in seen and trustworthy:
            # Same evidence rule the app loop above applies: with one cluster
            # member down, that node's guests vanish from /cluster/resources
            # while the cycle otherwise looks healthy. Deleting here took the
            # alert rules with it, since targets_for() resolves a vm rule to
            # nothing once the row is gone and the orphan sweep then resolves
            # any firing alert as "target removed".
            # ponytail: no missing_since countdown for VMs like apps have, so
            # a trustworthy cycle still deletes at once. Add the column if a VM
            # is ever seen disappearing from a fully-online cluster.
            db.delete(v)
            membership_changed = True
    db.flush()  # new Vm rows need ids before sampling
    for v in db.query(Vm).filter_by(host_id=host.id).all():
        g = guests.get(("qemu", v.vmid))
        if not g:
            continue
        # After the flush, not up in the upsert loop above: this one is keyed
        # on the VM's DB id and a row inserted this cycle does not have one
        # yet, so every new VM would share the key None.
        _refresh_vm_disk(v, g, client, fs_checked, now)
        # Asks once per VM ever, not on a timer. See _refresh_os_type.
        _refresh_os_type(v, g, client)
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

    # discovered CTs + adoption heuristic. Nothing here auto-adopts.
    catalog = {_norm(c.slug): c.slug for c in db.query(CatalogEntry).all()}
    discovered = [
        {"ctid": vmid, "name": g["name"], "node": g["node"],
         "status": g["status"], "suggestion": _suggest(catalog, g["name"] or "")}
        for (kind, vmid), g in sorted(guests.items())
        if kind == "lxc" and vmid not in mapped_ctids
    ]

    snap_storage = storage_snapshot_rows(storage_rows)

    # Reaping: the CT behind these apps is gone, so the app is gone. The row is
    # DELETED rather than flagged, which is what makes it disappear everywhere
    # at once: GET /apps, the host page's app list and /cluster/nodes' per-host
    # counts all read the apps table directly. A re-created CT with the same
    # ctid comes back as `discovered` and can be adopted.
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

    # Default True so every existing caller records exactly as it did; the
    # poller passes False on the cycles between recordings. The cached columns
    # and the snapshot are written either way, so the UI is fresh on a cycle
    # that stored nothing.
    if record_samples:
        write_samples(db, samples)
    db.commit()

    events.insert(0, ("metrics", {"targets": targets}))
    snapshot = HostSnapshot(host_id=host.id, ts=now, nodes=snap_nodes,
                            storage=snap_storage,
                            guests=guests, discovered=discovered)
    return CycleResult(snapshot=snapshot, events=events)


class Poller:
    """Supervisor + one long-lived task per host.

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
        # host_id -> when the RRD was last fetched, and the last answer. The
        # answer is KEPT, not discarded: between fetches it is still the
        # current reading, and dropping it would zero the network figures for
        # eleven cycles out of twelve.
        self._rrd_at: dict[int, datetime] = {}
        self._rrd_cache: dict[int, dict[str, list[dict]]] = {}
        self._rrd_degraded: dict[int, str | None] = {}
        # host_id -> when MetricSample rows were last written for it.
        self._metrics_at: dict[int, datetime] = {}
        # host_id -> the datastore sizes disk_pct divides by. Has to outlive a
        # cycle or a pool that drops out of one read moves the percentage; see
        # PoolMemory.
        self._pools: dict[int, PoolMemory] = {}
        # host_id -> {app_id: when its address was last read}. Same shape and
        # same reason as _pools: the cadence in APP_IP_REFRESH_INTERVAL_S only
        # means anything if it outlives a cycle, and it goes away with the host.
        self._ip_checked: dict[int, dict[int, datetime]] = {}
        # host_id -> {vm_id: when its guest agent was last asked for disk
        # usage}, behind VM_DISK_REFRESH_INTERVAL_S.
        self._fs_checked: dict[int, dict[int, datetime]] = {}
        # host_id -> "poll this host now" flag, set by wake(). One Event per
        # host is the whole burst guard: an Event that is already set stays a
        # single wake, so five creates in a row still cost one extra cycle.
        self._wakes: dict[int, asyncio.Event] = {}

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
                        self._ip_checked.pop(hid, None)
                        self._fs_checked.pop(hid, None)
                        self._wakes.pop(hid, None)
                        self._rrd_at.pop(hid, None)
                        self._rrd_cache.pop(hid, None)
                        self._rrd_degraded.pop(hid, None)
                        self._metrics_at.pop(hid, None)
            except Exception:  # noqa: BLE001  (supervisor never dies)
                pass
            # Here rather than in _host_loop: this supervisor already ticks
            # exactly once per interval no matter how many hosts exist, and
            # every rule's answer is global, so evaluating per host would be N
            # times the queries for the same result. Wrapped separately from
            # the block above so an alerting failure can never stop the
            # supervisor from respawning host loops.
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

    def wake(self, host_id: int) -> None:
        """Poll this host on the next iteration instead of waiting out
        poll_interval_s. Called by anything that has just created or destroyed
        a guest on it.

        Worth making: measured against the lab cluster (PVE 9.2.11), a new
        guest appears in /cluster/resources under 20 ms after its create task
        reports finished. PVE's status cache is not what made a new VM take 10
        to 20 seconds to show up; our own 30 s interval was the entire delay.

        The mirror stays the poller's alone (Proxmox is the truth): a wake asks
        for a normal cycle sooner, it does not write a row.

        Safe to call before the host has a loop (the flag is picked up when one
        starts), while it is mid-cycle (the wait at the end of _host_loop
        consumes it), and repeatedly. Must be called from the event loop
        thread, which every job handler already runs on.
        """
        self._wakes.setdefault(host_id, asyncio.Event()).set()

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
                # A 403 on a privilege the token was never granted, a TLS
                # failure and a genuinely dead node must not all collapse into
                # the bare word "unreachable" with nothing logged, or there is
                # no way to tell them apart from the UI or the server log.
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
            wake = self._wakes.setdefault(host_id, asyncio.Event())
            if fails:
                # The backoff owns the delay while this host is failing. A wake
                # must never shorten it, or a create attempted against a dead
                # host turns its loop into a hot retry against the thing that
                # is already not answering. The wake is cleared below all the
                # same: the cycle that runs when the backoff expires covers it.
                await asyncio.sleep(delay)
            else:
                try:
                    await asyncio.wait_for(wake.wait(), delay)
                except TimeoutError:
                    pass
            wake.clear()

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
            # default.
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
            # Fetched only when the 60s bucket could have turned over;
            # otherwise the previous answer is reused verbatim, and `degraded`
            # is carried with it, since "we could not read the metrics" is
            # still true on a cycle that did not try. `_rrd_at` is only ever
            # stamped by a clean fetch, so "never fetched" and "last fetch
            # failed" both land here as due.
            rrd_due = (self._rrd_at.get(host_id) is None
                       or (utcnow() - self._rrd_at[host_id]).total_seconds()
                       >= RRD_INTERVAL_S)
            if rrd_due:
                rrd, lost = {}, []
                for n in node_names:
                    try:
                        rrd[n] = client.node_rrddata(n)
                    except ProxmoxError as e:
                        lost.append(f"{n}: {e}")
                degraded = (f"metrics unavailable, {'; '.join(lost)}"
                            if lost else None)
                # The 60s hold is earned by SUCCESS only: it exists because we
                # already hold this minute's numbers, and a failed fetch holds
                # nothing. Latching a failure would leave the host flagged
                # degraded for up to 60s after it recovered, so a failure
                # retries on the next cycle instead, like version() and
                # cluster_status().
                if not lost:
                    self._rrd_at[host_id] = utcnow()
                self._rrd_cache[host_id] = rrd
                self._rrd_degraded[host_id] = degraded
            else:
                rrd = self._rrd_cache.get(host_id, {})
                degraded = self._rrd_degraded.get(host_id)

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
            m_at = self._metrics_at.get(host_id)
            record = (m_at is None
                      or (utcnow() - m_at).total_seconds() >= METRIC_SAMPLE_INTERVAL_S)
            if record:
                self._metrics_at[host_id] = utcnow()
            result = ingest_cycle(db, host, resources, rrd, utcnow(),
                                  version=version, node_name=node_name,
                                  cluster_name=cluster_name, quorate=quorate,
                                  degraded=bool(degraded),
                                  pools=self._pools.setdefault(host_id, PoolMemory()),
                                  status_rows=status_rows,
                                  client=client,
                                  ip_checked=self._ip_checked.setdefault(host_id, {}),
                                  fs_checked=self._fs_checked.setdefault(host_id, {}),
                                  record_samples=record)
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
        """Every failed cycle lands here, so this is the one place that already
        knows a host is gone and already holds a session on it. The cached
        status/metric columns on App and Vm are what cluster.py's running
        counts, consoles.py's launch guard and backups.py's target picker all
        read, and none of them ever finds out the host went away: ingest_cycle,
        the only other writer, never runs for a host that raised before it got
        there. Clearing the cache here, once, is correct for all four; a guard
        at each of them could drift out of sync.

        The host loop retries a dead host forever, just slower each time, so
        this runs on every retry. The host's own flip to "unreachable" is worth
        an SSE event only on the transition (the `already` check below), but
        the guest sweep cannot key off that flag: a restart can leave a guest
        stale while the host row already reads "unreachable". So the sweep runs
        every call and checks each guest on its own. A guest already fully
        cleared (status unknown and every cached reading null) is skipped with
        no write and no event, which is what stops a dead host from restating
        the same rows forever; one whose status reads unknown but still has a
        stale reading is not cleared and gets nulled too.
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
                # ip_cached is deliberately NOT cleared, and deliberately not
                # part of already_cleared above. The readings above are live
                # measurements that go stale the instant nobody can take them;
                # an address is a fact about the container that stays true
                # while its host is unreachable and almost always survives the
                # outage. _refresh_ip applies the same rule from the other side.
                #
                # net_in_cached, net_out_cached and net_sampled_at are left as
                # they were: not readings shown to anyone, only the counters
                # _update_net_rates diffs against, and it already handles a
                # stale sample. A guest that rebooted with its host trips the
                # now_in < prev_in guard and loses one cycle's rate; one that
                # kept running gives a genuine average over the outage rather
                # than a fabricated spike.

            for v in db.query(Vm).filter_by(host_id=host_id).all():
                already_cleared = (
                    v.status == "unknown"
                    and v.uptime_s is None
                    and v.mem_bytes is None
                    and v.disk_bytes is None
                    and v.net_in_bps_cached is None
                    and v.net_out_bps_cached is None
                )
                if already_cleared:
                    continue
                if v.status != "unknown":
                    events.append(("resource", {"type": "vm", "id": v.id,
                                                "change": "status", "status": "unknown"}))
                v.status = "unknown"
                # Split exactly the way the app sweep above splits it: a live
                # MEASUREMENT nobody can take right now is unknown, and a fact
                # about how the guest is configured stays true while its host
                # is off the air. All five cleared below are readings.
                v.uptime_s = None
                v.mem_bytes = None
                v.disk_bytes = None
                v.net_in_bps_cached = None
                v.net_out_bps_cached = None
                # Held: cpu_cores, mem_total_bytes and disk_total_bytes are the
                # guest's configured allocation (maxcpu/maxmem/maxdisk), a fact
                # rather than a reading. guest_agent_ok is held for the same
                # reason even though it sits next to disk_bytes and comes from
                # the same call: nulling it would replace a real finding ("no
                # agent, that is why storage is unknown") with "unknown" for
                # the whole outage. os_type is held too, and it is read exactly
                # once per VM (see _refresh_os_type), so clearing it would lose
                # the OS icon and force the config read again on recovery.
                #
                # This is a DELIBERATE difference from the app sweep, which
                # does null disk_total_bytes_cached: an app's allocation is
                # only read back out of the same poll that measures its usage,
                # while on a VM the allocation is the meter's denominator, and
                # blanking it turns "usage unknown" into "this VM has no memory
                # and no disk".
                #
                # net_in_cached, net_out_cached and net_sampled_at are left as
                # they were, for the reason given in the app sweep.

            db.commit()
            return events
