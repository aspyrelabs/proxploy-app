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

from proxploy.models import App, CatalogEntry, Host, HostCredential, MetricSample, Vm, utcnow
from proxploy.services.metrics import write_samples
from proxploy.services.proxmox import ProxmoxClient, ProxmoxError

POLL_BACKOFF_CAP_S = 300


log = logging.getLogger(__name__)


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


def _disk_pct(host_node: str, storage_rows: list[dict]) -> float:
    """Aggregate used/total across this host's datastores.

    Deduped correctly, unlike the cluster ring's deliberate shortcut in
    api/cluster.py::cluster_summary: a SHARED datastore is reported once per
    node and must count once, a LOCAL datastore with the same name on two
    nodes is two distinct pools. Doing it wrong here is not a cosmetic ring
    error; it is an alert that fires at the wrong number.
    """
    pools: dict[tuple, dict] = {}
    for r in storage_rows:
        key = (r.get("storage"),) if r.get("shared") else (r.get("node"),
                                                           r.get("storage"))
        pools[key] = r
    used = sum(int(r.get("disk") or 0) for r in pools.values())
    total = sum(int(r.get("maxdisk") or 0) for r in pools.values())
    return round(used / total * 100, 1) if total else 0.0


def ingest_cycle(db, host: Host, resources: list[dict],
                 rrd_by_node: dict[str, list[dict]], now: datetime,
                 version: str | None = None) -> CycleResult:
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

    # host.node_name is otherwise write-never: POST /hosts has no way to learn
    # it (PVE's /version carries no node name), so a host added through the
    # real wizard sat at NULL forever: /cluster/nodes and the VM-create
    # wizard's node picker both read this column directly, not the snapshot,
    # so they silently had nothing to offer. Only tests/support.py's
    # seed_host_row ever set it, which is why this never showed up until the
    # onboarding journey actually drove host creation through the UI (Task 16).
    # Written once, like main.py's self.ctid: a later operator correction must
    # survive restarts, and a real multi-node cluster's actual "home" node for
    # this Host row is not something a later poll should second-guess.
    if not host.node_name and snap_nodes:
        host.node_name = snap_nodes[0]["node"]

    own = next((n for n in snap_nodes if n["node"] == host.node_name),
               snap_nodes[0] if snap_nodes else None)
    if own:
        for metric, value in (("cpu_pct", own["cpu_pct"]),
                              ("mem_bytes", float(own["mem_bytes"])),
                              ("mem_pct", _mem_pct(own["mem_bytes"],
                                                   own["mem_total_bytes"])),
                              ("disk_pct", _disk_pct(host.node_name, storage_rows)),
                              ("net_in_bps", net_in), ("net_out_bps", net_out)):
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

    # apps cache refresh (identity is ours; state is cached: doc 04) ----------
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
        samples.append(MetricSample(target_type="app", target_id=a.id,
                                    metric="mem_pct",
                                    value=_mem_pct(g["mem_bytes"],
                                                   g["mem_total_bytes"]), ts=now))
        # ponytail: no disk_pct for apps/vms: /cluster/resources' `disk` field
        # is meaningful for LXC but routinely 0 for QEMU, so a guest disk_pct
        # would be silently wrong for every VM. Task 12's rule validation
        # rejects disk_pct on app/vm targets with an explanatory 422 instead.
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

    write_samples(db, samples)
    db.commit()

    events.insert(0, ("metrics", {"targets": targets}))
    snapshot = HostSnapshot(host_id=host.id, ts=now, nodes=snap_nodes,
                            storage=snap_storage,
                            net={"in_bps": net_in, "out_bps": net_out},
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
                evt = await asyncio.to_thread(self._mark_unreachable, host_id, reason)
                if evt:
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

            prev = self.snapshots.get(host_id)
            result = ingest_cycle(db, host, resources, rrd, utcnow(), version=version)
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

    def _mark_unreachable(self, host_id: int, reason: str = ""):
        with self.app.state.sessionmaker() as db:
            host = db.get(Host, host_id)
            if host is None:
                return None
            already = host.status == "unreachable"
            host.status = "unreachable"
            # Written even when the status is unchanged: the reason can change
            # between cycles (a timeout becoming a 403), and the operator needs
            # the current one, not the first one ever recorded.
            host.last_error = reason or None
            db.commit()
            if already:
                return None
            return ("resource", {"type": "host", "id": host_id,
                                 "change": "status", "status": "unreachable"})
