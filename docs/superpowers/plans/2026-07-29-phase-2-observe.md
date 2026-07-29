# Phase 2 — Observe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This is an unattended run: no human checkpoints — on ambiguity make the best spec-supported call, note it in the commit message, and keep going.

**Goal:** Land Phase 2 of `docs/10-build-sequence.md`: the per-host 30s poller (bulk `/cluster/resources` + per-node `rrddata`, O(nodes) call budget), MetricsStore (batched `metric_samples`, 5m/1h rollups, retention pruning, range query), read-only caches (`apps` cached columns, `vms` upsert, storage/network snapshots, discovered-CT list with adoption heuristics), the SSE event stream, the six Phase-2 endpoints, and the read-only Cluster / node-detail / Apps / VMs pages with uPlot charts and SSE-driven TanStack Query invalidation.

**Architecture:** The poller is a supervisor asyncio task (started in `create_app`'s lifespan, like the entitlement refresh loop) that keeps one long-lived task per host; each cycle runs the blocking proxmoxer + SQLAlchemy work in `asyncio.to_thread` with a per-host timeout, writes one batched transaction, refreshes the in-memory `HostSnapshot`, and publishes deltas on an in-process `EventBus` (plain asyncio queues) that the SSE endpoint fans out. REST endpoints read DB caches + snapshots; history comes from `metric_samples`/`metric_rollups` via `services/metrics.py`. Everything follows the Phase 1 shapes: sync SQLAlchemy, `app.state` as DI container, hand-built response dicts, `require_role("viewer")` on reads, no audit rows for reads.

**Tech Stack:** Existing Phase 1 stack (FastAPI, sync SQLAlchemy 2, proxmoxer, TanStack Query/Router, Tailwind v4 tokens) plus exactly one new frontend dependency: **uPlot (MIT)**. No new backend dependencies — SSE is a hand-rolled `StreamingResponse` (no sse-starlette), the bus is stdlib asyncio.

## Global Constraints

- Specs: docs/00–11 in this repo are the approved source of truth; doc numbers cited per task. Phase 2 scope is doc 10 lines 80–105 only.
- **Poll budget is O(nodes), never O(guests)** (doc 02 §3): per cycle per host, exactly one `cluster/resources` call plus one `rrddata` call per node. **No per-guest calls in the poll loop, ever.**
- Every proxmoxer call lives in `backend/proxploy/services/proxmox.py` (`ProxmoxClient`) — never in pollers, routers, or services (doc 02 §4, enforced convention from `proxmox.py:1-4`).
- All datetimes are **naive UTC** via `proxploy.models.utcnow()` (Phase 1 convention). Metric `ts` included.
- One DB transaction per poll cycle (doc 11 §4: batched sample writes); SQLite stays in WAL mode (already set in `db.py`).
- Phase 2 routes are read-only: `require_role("viewer")`, **no audit rows** (Phase 1 precedent: reads don't audit). The only entitlement gate is `metrics.history` beyond 48 h (doc 05), checked inline like the `hosts.multi` precedent in `hosts.py:55`.
- SSE for one-way streams, session-cookie auth (doc 05 §Streaming); event names/payloads exactly as doc 05 §Streaming 4 (`metrics`, `resource`).
- Query keys and refetch intervals per doc 06 §(d): `['cluster','summary']` 30s, `['cluster','nodes']` 30s, `['apps', filters]` 30s, `['apps', id]` 15s, `['vms', …]` 30s/15s, `['metrics', …]` none (SSE-invalidated). Polling is the fallback; SSE is primary.
- The fixed nav (8 items) never changes; `tests/nav.test.tsx` enforces it and must keep passing.
- Design tokens are frozen (`styles/tokens.css`, asserted by `login.test.tsx`); components use existing utilities (`bg-panel`, `border-line-soft`, `font-mono`, `rounded-card`, …). Terminal/code panels stay dark in both themes.
- Frontend: paths passed to `api()` are relative to `/api/v1`. `import type` for type-only imports (`verbatimModuleSyntax`). New route files export their routes and are imported mid-file in `router.tsx` (settings.tsx precedent); `as never` casts on `to:` props are the accepted workaround, with comment.
- No module outside `backend/proxploy/executor/` imports asyncssh or SSH-key accessors — `scripts/check_executor_isolation.py` must stay green (trivially: Phase 2 never touches SSH).
- Licenses: uPlot is MIT — passes the frontend `license-checker-rseidelsohn` allowlist. Nothing else is added.
- Git: commit directly to `main` after each task (standing rule; no branches, no PRs). Conventional-commit messages as given per task.
- Working dir: `~/workspace/aspyrelabs/proxploy/proxploy-app`. Backend commands run from `backend/` with `.venv` active (`source .venv/bin/activate` or `./.venv/bin/python`); frontend commands from `frontend/`.
- Test invocations: `python -m pytest tests/ -q -m "not pve_integration and not e2e"` (backend), `npm test` + `npm run build` (frontend; `tsc -b` inside build is the typecheck gate). No live PVE on this box: everything runs against the FakePVE layer.
- **No new Alembic migration expected**: `metric_samples`, `metric_rollups`, `apps` cached columns, `vms` all exist in migration 0001. If any column turns out missing, add migration `0002_<slug>` following the 0001 naming pattern — but verify against `models/__init__.py` first.

## Decisions made for the spec's open points (best-supported calls, unattended run)

1. **Discovered CTs are NOT auto-adopted.** Doc 10 Phase 4 owns explicit adoption (`apps.adopt`); if Phase 2 auto-adopted, Phase 4's discovered-panel would be dead on arrival. Phase 2 ships `GET /api/v1/apps/discovered` (already specified in doc 05) fed from poller snapshots + heuristics, and the Apps page renders the DiscoveredPanel **read-only** (list + catalog-match suggestions, with an honest "Adoption arrives with the App Store phase" note instead of an Adopt button). This satisfies the Phase 2 DoD "apps and VMs discovered and rendered".
2. **Storage/network snapshots live in memory** (`HostSnapshot` on `app.state.poller`), not new tables — doc 04 defines no table for them, caches are droppable by definition, and a restart repopulates within one 30s cycle. History-quality series live in `metric_samples` as specced.
3. **Node detail route is `/cluster/$hostId`.** Doc 10 lists a node-detail page; doc 06's route table predates it (prototype had none). NodeCard body click still goes to `/apps?host=…` per doc 06; the mono hostname link inside the card goes to node detail.
4. **`GET /api/v1/metrics/latest` and `/cluster/activity` are NOT built** — doc 10 Phase 2 names exactly six endpoints; latest values ride on `/apps`, `/vms`, `/cluster/*` responses (cached columns + snapshots), and the activity feed is Phase 3 (jobs). The dashboard renders an honest empty state for activity.
5. **`vms.os_type` stays NULL in Phase 2** (generic icon): `cluster/resources` doesn't carry ostype and fetching it would need per-guest calls the poll budget forbids. Doc 05's "detail (cache + live status refresh)" per-guest enrichment is user-triggered work that lands with Phase 3's per-VM actions.
6. **Rollup/prune run on a plain asyncio loop** (`metrics_loop`) in lifespan — APScheduler arrives Phase 7 ("Scheduler … in production"); doc 10 Phase 2 only requires the jobs to run. Retention windows are constants (48h/14d/400d per doc 04) with a `ponytail:` note; the settings knob ships with Phase 7's schedule UI.
7. **Both rollup resolutions aggregate from raw samples** with a short recompute lookback (idempotent delete+insert per bucket window) — valid because raw retention (48h) far exceeds the lookback; simpler than chaining 1h-from-5m.
8. **VM table has no sort/TanStack Table yet** — the prototype's VM table spec (doc 06) shows hover actions, not sorting; TanStack Table arrives when a page actually sorts (Phase 6 tables). Plain styled `<table>` now.
9. **SSE `metrics` events invalidate `['metrics']` queries rather than appending points** to live uPlot series — visually identical at 30s cadence, far less code; doc 06's append optimization is noted as the upgrade path.

## File structure (what Phase 2 creates/modifies)

```
backend/
├── proxploy/
│   ├── config.py                     # MODIFY: + poll_enabled, poll_interval_s, poll_timeout_s
│   ├── main.py                       # MODIFY: lifespan starts EventBus, Poller, metrics_loop
│   ├── events.py                     # NEW: EventBus (in-process pub/sub, asyncio queues)
│   ├── pollers/__init__.py           # NEW: HostSnapshot, CycleResult, ingest_cycle, Poller
│   ├── services/
│   │   ├── proxmox.py                # MODIFY: + cluster_resources(), node_rrddata()
│   │   └── metrics.py                # NEW: MetricsStore — write/rollup/prune/query + metrics_loop
│   └── api/
│       ├── __init__.py               # MODIFY: register cluster, apps, vms, metrics, events routers
│       ├── cluster.py                # NEW: GET /cluster/summary, /cluster/nodes
│       ├── apps.py                   # NEW: GET /apps, /apps/discovered, /apps/{id}
│       ├── vms.py                    # NEW: GET /vms, /vms/{id}
│       ├── metrics.py                # NEW: GET /metrics/query
│       └── events.py                 # NEW: GET /events/stream (SSE)
├── scripts/bench_metrics.py          # NEW: synthetic-fleet benchmark (doc 11 §4)
└── tests/
    ├── support.py                    # NEW: make_app / seed_host / seed_snapshot helpers
    ├── fakes/pve.py                  # MODIFY: cluster.resources + callable nodes(x).rrddata
    ├── fixtures/pve/cluster_resources_basic.json   # NEW
    ├── fixtures/pve/rrddata_hour.json              # NEW
    └── test_{proxmox_poll,metrics_store,poller_ingest,events_sse,poller_loop,
           cluster_api,apps_vms_api,metrics_api}.py # NEW

frontend/
├── package.json                      # MODIFY: + uplot
└── src/
    ├── api/hooks.ts                  # MODIFY: + useMetrics
    ├── api/live.ts                   # NEW: applyMetrics/applyResource (SSE → Query cache)
    ├── lib/format.ts                 # NEW: fmtBytes/fmtUptime/fmtPct/fmtBps
    ├── components/
    │   ├── LiveProvider.tsx          # NEW: EventSource wiring + LivePulse
    │   ├── StatusPill.tsx  UsageBar.tsx  KVGrid.tsx  StatRings.tsx  # NEW
    │   ├── NodeCard.tsx  AppCard.tsx                                # NEW
    │   └── charts/Sparkline.tsx      # NEW: uPlot wrapper (spark + range chart)
    ├── routes/
    │   ├── cluster.tsx               # NEW: ClusterPage + NodeDetailPage (+ routes)
    │   ├── apps.tsx                  # NEW: AppsPage + AppDetail (+ tab child routes)
    │   └── vms.tsx                   # NEW: VmsPage + VmDetail (+ tab child routes)
    ├── router.tsx                    # MODIFY: real routes replace cluster/apps/vms placeholders
    └── tests/{format.test.ts, live.test.ts, cluster.test.tsx}      # NEW

docs/notes/phase-2-observe.md         # NEW: DoD verification map + bench numbers + deviations
```

---

### Task 1: ProxmoxClient bulk-poll reads + FakePVE poll surface + fixtures

Doc refs: 02 §3 (poll budget, bulk endpoints), 02 §4 / 03 (one client layer), 10 Phase 2.

**Files:**
- Modify: `backend/proxploy/services/proxmox.py` (append two methods to `ProxmoxClient`)
- Modify: `backend/tests/fakes/pve.py` (add `cluster`/`nodes` namespaces)
- Create: `backend/tests/fixtures/pve/cluster_resources_basic.json`, `backend/tests/fixtures/pve/rrddata_hour.json`
- Test: `backend/tests/test_proxmox_poll.py`

**Interfaces:**
- Consumes: `ProxmoxClient` (Phase 1: `_connect()`, `ProxmoxError`, exception-wrap idiom at `proxmox.py:74-88`), `FakePVE`/`make_fake_factory` (Phase 1).
- Produces:
  - `ProxmoxClient.cluster_resources() -> list[dict]` — raw `/cluster/resources` rows (types `node`/`lxc`/`qemu`/`storage`).
  - `ProxmoxClient.node_rrddata(node: str, timeframe: str = "hour") -> list[dict]` — raw rrd rows, oldest→newest.
  - `FakePVE(version=None, permissions=None, fail=False, resources=None, rrddata=None)` — `resources` is the `/cluster/resources` list, `rrddata` is `dict[node_name, list[rrd_row]]`. Failure toggles used by later tasks: `fake.cluster.resources._fail = True`, and the existing `fake.version._fail` (which also makes the factory itself raise).
  - Fixture `cluster_resources_basic.json`: one node `pve1` (host-01), CTs 150 (`immich`, running) and 200 (`plex`, running, unadopted), VM 100 (`win11`, running), storages `local` + `pbs-datastore`.

- [ ] **Step 1: Write the fixtures**

`backend/tests/fixtures/pve/cluster_resources_basic.json` (shapes match real PVE 8/9 `/cluster/resources` output; `cpu` is a 0–1 fraction, `mem`/`maxmem`/`disk`/`maxdisk` bytes, `uptime` seconds):

```json
[
  {"type": "node", "node": "pve1", "status": "online", "cpu": 0.42, "maxcpu": 8,
   "mem": 13743895347, "maxmem": 33822867456, "uptime": 864000, "id": "node/pve1", "level": ""},
  {"type": "lxc", "vmid": 150, "name": "immich", "node": "pve1", "status": "running",
   "cpu": 0.12, "maxcpu": 4, "mem": 2147483648, "maxmem": 4294967296,
   "disk": 5368709120, "maxdisk": 17179869184, "uptime": 86400, "id": "lxc/150"},
  {"type": "lxc", "vmid": 200, "name": "plex", "node": "pve1", "status": "running",
   "cpu": 0.05, "maxcpu": 2, "mem": 1073741824, "maxmem": 2147483648,
   "disk": 3221225472, "maxdisk": 8589934592, "uptime": 43200, "id": "lxc/200"},
  {"type": "qemu", "vmid": 100, "name": "win11", "node": "pve1", "status": "running",
   "cpu": 0.31, "maxcpu": 4, "mem": 6442450944, "maxmem": 8589934592,
   "disk": 0, "maxdisk": 68719476736, "uptime": 172800, "id": "qemu/100"},
  {"type": "storage", "storage": "local", "node": "pve1", "status": "available",
   "disk": 107374182400, "maxdisk": 471859200000, "id": "storage/pve1/local"},
  {"type": "storage", "storage": "pbs-datastore", "node": "pve1", "status": "available",
   "disk": 214748364800, "maxdisk": 1099511627776, "id": "storage/pve1/pbs-datastore"}
]
```

`backend/tests/fixtures/pve/rrddata_hour.json` (per-node rrd rows; `netin`/`netout` are bytes/s):

```json
[
  {"time": 1753759800, "cpu": 0.40, "maxcpu": 8, "memtotal": 33822867456,
   "memused": 13500000000, "netin": 1250000.5, "netout": 4800000.25,
   "iowait": 0.01, "loadavg": 1.2},
  {"time": 1753759860, "cpu": 0.42, "maxcpu": 8, "memtotal": 33822867456,
   "memused": 13743895347, "netin": 1300000.0, "netout": 5000000.0,
   "iowait": 0.01, "loadavg": 1.3}
]
```

- [ ] **Step 2: Extend the fake** — `backend/tests/fakes/pve.py`. Keep `_Leaf` untouched; add kwargs-tolerant leaves and callable node namespace (proxmoxer path segments are callable: `api.nodes("pve1").rrddata.get(timeframe="hour")`):

```python
class _KwLeaf:
    """Like _Leaf but tolerates .get(**kwargs) (rrddata takes timeframe=...)."""

    def __init__(self, value, fail=False):
        self._value, self._fail = value, fail

    def get(self, **kwargs):
        if self._fail:
            raise ConnectionError("fake PVE unreachable")
        return self._value


class _ClusterNS:
    def __init__(self, resources, fail):
        self.resources = _KwLeaf(resources, fail)


class _NodeNS:
    def __init__(self, rrddata, fail):
        self.rrddata = _KwLeaf(rrddata, fail)


class _NodesNS:
    def __init__(self, rrd_by_node, fail):
        self._rrd, self._fail = rrd_by_node, fail

    def __call__(self, name):
        return _NodeNS(self._rrd.get(name, []), self._fail)
```

and in `FakePVE.__init__`, extend the signature and body:

```python
    def __init__(self, version=None, permissions=None, fail=False,
                 resources=None, rrddata=None):
        self.version = _Leaf(version or {"version": "8.4.1", "release": "8.4"}, fail)
        self.access = _Access(permissions or {}, fail)
        self.cluster = _ClusterNS(resources or [], fail)
        self.nodes = _NodesNS(rrddata or {}, fail)
        self.kwargs = {}
```

(`make_fake_factory` is unchanged — it already raises when `fake.version._fail` is set.)

- [ ] **Step 3: Write the failing test** — `backend/tests/test_proxmox_poll.py`:

```python
"""ProxmoxClient bulk-poll reads (doc 02 §3: cluster/resources + per-node rrddata)."""
import json
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures" / "pve"


def _client(fake):
    from proxploy.services.proxmox import ProxmoxClient
    from tests.fakes.pve import make_fake_factory

    return ProxmoxClient("https://pve1:8006", "proxploy@pve!mon", "s3cret",
                         factory=make_fake_factory(fake))


def test_cluster_resources_returns_rows():
    from tests.fakes.pve import FakePVE

    rows = json.loads((FIX / "cluster_resources_basic.json").read_text())
    fake = FakePVE(resources=rows)
    got = _client(fake).cluster_resources()
    assert got == rows
    assert {r["type"] for r in got} == {"node", "lxc", "qemu", "storage"}


def test_node_rrddata_passes_timeframe():
    from tests.fakes.pve import FakePVE

    rrd = json.loads((FIX / "rrddata_hour.json").read_text())
    fake = FakePVE(rrddata={"pve1": rrd})
    got = _client(fake).node_rrddata("pve1")
    assert got == rrd
    assert _client(fake).node_rrddata("missing-node") == []


def test_poll_reads_wrap_errors_as_proxmox_error():
    from proxploy.services.proxmox import ProxmoxError
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    fake.cluster.resources._fail = True
    fake.nodes._fail = True
    with pytest.raises(ProxmoxError):
        _client(fake).cluster_resources()
    with pytest.raises(ProxmoxError):
        _client(fake).node_rrddata("pve1")
```

- [ ] **Step 4: Run it to make sure it fails**

Run (from `backend/`): `python -m pytest tests/test_proxmox_poll.py -q`
Expected: FAIL — `AttributeError: 'ProxmoxClient' object has no attribute 'cluster_resources'`.

- [ ] **Step 5: Implement** — append to `ProxmoxClient` in `backend/proxploy/services/proxmox.py`, following the existing wrap idiom exactly:

```python
    def cluster_resources(self) -> list[dict]:
        """One bulk call: every node/CT/VM/storage row for this endpoint.

        The poll loop's only guest-state source — per-guest calls are
        forbidden in the poller (doc 02 §3 O(nodes) budget).
        """
        try:
            return self._connect().cluster.resources.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001 — one wrap point, like version()
            raise ProxmoxError(f"cluster/resources failed: {e}") from e

    def node_rrddata(self, node: str, timeframe: str = "hour") -> list[dict]:
        """History-quality per-node series (netin/netout/cpu/mem), doc 02 §11.1."""
        try:
            return self._connect().nodes(node).rrddata.get(timeframe=timeframe)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise ProxmoxError(f"rrddata failed for node {node!r}: {e}") from e
```

- [ ] **Step 6: Run the tests and make sure they pass**

Run: `python -m pytest tests/test_proxmox_poll.py tests/test_proxmox.py tests/test_hosts.py -q`
Expected: all PASS (new file green, no regression in the existing fake's consumers).

- [ ] **Step 7: Commit**

```bash
git add backend/proxploy/services/proxmox.py backend/tests/fakes/pve.py \
        backend/tests/fixtures/pve/cluster_resources_basic.json \
        backend/tests/fixtures/pve/rrddata_hour.json backend/tests/test_proxmox_poll.py
git commit -m "feat(backend): ProxmoxClient bulk poll reads + fake PVE poll surface"
```

---

### Task 2: MetricsStore — batched writes, 5m/1h rollups, retention pruning, range query

Doc refs: 04 (`metric_samples`/`metric_rollups`, retention table), 11 §4 (batching), 05 (`/metrics/query` semantics), 02 §11.1 (raw-vs-rollup pick).

**Files:**
- Create: `backend/proxploy/services/metrics.py`
- Test: `backend/tests/test_metrics_store.py`

**Interfaces:**
- Consumes: `MetricSample`, `MetricRollup`, `utcnow` from `proxploy.models` (tables exist in migration 0001 — no new migration).
- Produces (all consumed by Tasks 3, 5, 8, 14):
  - `METRICS: tuple[str, ...]` — the doc-04 metric names.
  - `write_samples(db, samples: list[MetricSample]) -> None` — `add_all`, **no commit** (caller owns the one-transaction-per-cycle rule).
  - `rollup(db, resolution: str, now: datetime, lookback: int = 3) -> int` — recompute the last `lookback` fully-elapsed buckets (`"5m"`|`"1h"`) from raw samples; idempotent (delete+insert); commits; returns bucket count.
  - `prune(db, now: datetime) -> dict[str, int]` — retention deletes (raw 48h, 5m 14d, 1h 400d); commits.
  - `pick_resolution(frm: datetime, to: datetime) -> str` — ≤6h → `raw`, ≤3d → `5m`, else `1h`.
  - `query_series(db, target_type, target_id, metric, frm, to, resolution) -> dict` — columnar `{"resolution", "ts": [epoch...], "value": [...]}`, plus `"min"`/`"max"` arrays for rollups (value = avg).
  - `metrics_loop(app) -> None` — async: every 5 min roll up 5m; every 12th tick roll up 1h + prune. Never dies on error.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_metrics_store.py`:

```python
"""MetricsStore: batched writes, idempotent rollups, retention, columnar query."""
from datetime import timedelta
from pathlib import Path


def _db(tmp_path: Path):
    from proxploy.config import Settings
    from proxploy.db import make_engine, make_sessionmaker, run_migrations

    s = Settings(db_url=f"sqlite:///{tmp_path}/m.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key")
    run_migrations(s)
    return make_sessionmaker(make_engine(s))()


def _seed(db, hours: float, step_s: int = 30, value: float = 50.0):
    from proxploy.models import MetricSample, utcnow
    from proxploy.services.metrics import write_samples

    now = utcnow()
    n = int(hours * 3600 // step_s)
    write_samples(db, [
        MetricSample(target_type="host", target_id=1, metric="cpu_pct",
                     value=value, ts=now - timedelta(seconds=step_s * i))
        for i in range(1, n + 1)
    ])
    db.commit()
    return now


def test_rollup_5m_aggregates_and_is_idempotent(tmp_path):
    from proxploy.models import MetricRollup, utcnow
    from proxploy.services.metrics import rollup

    db = _db(tmp_path)
    _seed(db, hours=1)
    n1 = rollup(db, "5m", utcnow(), lookback=12)
    assert n1 >= 10  # ~12 buckets of 10 samples each
    n2 = rollup(db, "5m", utcnow(), lookback=12)  # re-run: delete+insert, no dupes
    assert n2 == n1
    row = db.query(MetricRollup).filter_by(resolution="5m").first()
    assert row.min == row.max == row.avg == 50.0 and row.sample_count == 10


def test_rollup_1h_from_raw(tmp_path):
    from proxploy.models import utcnow
    from proxploy.services.metrics import rollup

    db = _db(tmp_path)
    _seed(db, hours=3)
    assert rollup(db, "1h", utcnow(), lookback=3) >= 2


def test_prune_respects_retention_windows(tmp_path):
    from proxploy.models import MetricSample, utcnow
    from proxploy.services.metrics import prune

    db = _db(tmp_path)
    now = _seed(db, hours=50)  # 2h of samples older than the 48h raw window
    out = prune(db, now)
    assert out["raw"] > 0
    oldest = db.query(MetricSample).order_by(MetricSample.ts).first()
    assert oldest.ts >= now - timedelta(hours=48, minutes=1)


def test_query_series_raw_and_rollup_shapes(tmp_path):
    from proxploy.models import utcnow
    from proxploy.services.metrics import pick_resolution, query_series, rollup

    db = _db(tmp_path)
    now = _seed(db, hours=1)
    raw = query_series(db, "host", 1, "cpu_pct", now - timedelta(hours=1), now, "raw")
    assert raw["resolution"] == "raw"
    assert len(raw["ts"]) == len(raw["value"]) > 100
    assert raw["ts"] == sorted(raw["ts"])

    rollup(db, "5m", now, lookback=12)
    r5 = query_series(db, "host", 1, "cpu_pct", now - timedelta(hours=1), now, "5m")
    assert r5["resolution"] == "5m" and len(r5["ts"]) == len(r5["min"]) == len(r5["max"])

    assert pick_resolution(now - timedelta(hours=2), now) == "raw"
    assert pick_resolution(now - timedelta(hours=24), now) == "5m"
    assert pick_resolution(now - timedelta(days=30), now) == "1h"
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/test_metrics_store.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'proxploy.services.metrics'`.

- [ ] **Step 3: Implement** — `backend/proxploy/services/metrics.py`:

```python
"""MetricsStore (doc 04, doc 11 §4): raw 30s samples, 5m/1h rollups, retention.

The seam VictoriaMetrics swaps in behind for big fleets (doc 03). Writers
batch: write_samples() never commits — the poll cycle owns its one
transaction. Rollups recompute a short lookback window idempotently
(delete+insert), so a missed tick self-heals on the next one.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from proxploy.models import MetricRollup, MetricSample, utcnow

METRICS = ("cpu_pct", "mem_bytes", "disk_bytes", "net_in_bps", "net_out_bps",
           "io_read_bps", "io_write_bps")

# ponytail: retention constants; the settings-table knob (doc 04) ships with
# Phase 7's scheduler UI, which is where users would actually edit it.
RAW_RETENTION_H = 48
ROLLUP_5M_RETENTION_D = 14
ROLLUP_1H_RETENTION_D = 400

_RES_SECONDS = {"5m": 300, "1h": 3600}


def _epoch(ts: datetime) -> int:
    return int(ts.replace(tzinfo=timezone.utc).timestamp())


def _bucket(ts: datetime, seconds: int) -> datetime:
    e = _epoch(ts)
    return datetime.fromtimestamp(e - e % seconds, tz=timezone.utc).replace(tzinfo=None)


def write_samples(db, samples: list[MetricSample]) -> None:
    db.add_all(samples)  # caller commits — one txn per poll cycle (doc 11 §4)


def rollup(db, resolution: str, now: datetime, lookback: int = 3) -> int:
    """Recompute the last `lookback` fully-elapsed buckets from raw samples."""
    secs = _RES_SECONDS[resolution]
    end = _bucket(now, secs)  # current, still-filling bucket — excluded
    start = end - timedelta(seconds=secs * lookback)
    rows = (db.query(MetricSample)
            .filter(MetricSample.ts >= start, MetricSample.ts < end).all())
    groups: dict[tuple, list[float]] = {}
    for s in rows:
        key = (s.target_type, s.target_id, s.metric, _bucket(s.ts, secs))
        groups.setdefault(key, []).append(s.value)
    (db.query(MetricRollup)
     .filter(MetricRollup.resolution == resolution,
             MetricRollup.bucket_ts >= start, MetricRollup.bucket_ts < end)
     .delete())
    for (tt, tid, metric, bucket), vals in groups.items():
        db.add(MetricRollup(target_type=tt, target_id=tid, metric=metric,
                            resolution=resolution, bucket_ts=bucket,
                            min=min(vals), max=max(vals),
                            avg=sum(vals) / len(vals), sample_count=len(vals)))
    db.commit()
    return len(groups)


def prune(db, now: datetime) -> dict[str, int]:
    n_raw = (db.query(MetricSample)
             .filter(MetricSample.ts < now - timedelta(hours=RAW_RETENTION_H))
             .delete())
    n_5m = (db.query(MetricRollup)
            .filter(MetricRollup.resolution == "5m",
                    MetricRollup.bucket_ts < now - timedelta(days=ROLLUP_5M_RETENTION_D))
            .delete())
    n_1h = (db.query(MetricRollup)
            .filter(MetricRollup.resolution == "1h",
                    MetricRollup.bucket_ts < now - timedelta(days=ROLLUP_1H_RETENTION_D))
            .delete())
    db.commit()
    return {"raw": n_raw, "5m": n_5m, "1h": n_1h}


def pick_resolution(frm: datetime, to: datetime) -> str:
    """Chart queries pick raw vs rollup by range (doc 02 §11.1)."""
    span = (to - frm).total_seconds()
    if span <= 6 * 3600:
        return "raw"
    if span <= 3 * 86400:
        return "5m"
    return "1h"


def query_series(db, target_type: str, target_id: int, metric: str,
                 frm: datetime, to: datetime, resolution: str) -> dict:
    """Columnar series for uPlot: aligned ts/value arrays (doc 05 /metrics/query)."""
    if resolution == "raw":
        rows = (db.query(MetricSample)
                .filter_by(target_type=target_type, target_id=target_id, metric=metric)
                .filter(MetricSample.ts >= frm, MetricSample.ts <= to)
                .order_by(MetricSample.ts).all())
        return {"resolution": "raw",
                "ts": [_epoch(r.ts) for r in rows],
                "value": [r.value for r in rows]}
    rows = (db.query(MetricRollup)
            .filter_by(target_type=target_type, target_id=target_id,
                       metric=metric, resolution=resolution)
            .filter(MetricRollup.bucket_ts >= frm, MetricRollup.bucket_ts <= to)
            .order_by(MetricRollup.bucket_ts).all())
    return {"resolution": resolution,
            "ts": [_epoch(r.bucket_ts) for r in rows],
            "value": [r.avg for r in rows],
            "min": [r.min for r in rows],
            "max": [r.max for r in rows]}


async def metrics_loop(app) -> None:
    """5m rollup every 5 min; 1h rollup + prune hourly.

    Plain lifespan task for now — Phase 7 moves these onto APScheduler so
    they appear in the activity feed like any other job (doc 10 Phase 7).
    """
    tick = 0
    while True:
        await asyncio.sleep(300)
        tick += 1
        try:
            def work() -> None:
                with app.state.sessionmaker() as db:
                    rollup(db, "5m", utcnow())
                    if tick % 12 == 0:
                        rollup(db, "1h", utcnow())
                        prune(db, utcnow())
            await asyncio.to_thread(work)
        except Exception:  # noqa: BLE001 — a failed tick never kills the loop
            continue
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `python -m pytest tests/test_metrics_store.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/proxploy/services/metrics.py backend/tests/test_metrics_store.py
git commit -m "feat(backend): MetricsStore — batched samples, 5m/1h rollups, retention, query"
```

---

### Task 3: Poller ingest — caches, samples, discovery heuristics, snapshot, events

Doc refs: 10 Phase 2 (caches), 04 (`apps` cached cols, `vms` CACHE), 02 §3/§11.1 (what a cycle writes), 05 §Streaming 4 (event payloads), plan decision 1 (no auto-adopt).

**Files:**
- Create: `backend/proxploy/pollers/__init__.py` (this task: dataclasses + `ingest_cycle`; Task 5 appends `Poller`)
- Create: `backend/tests/support.py`
- Test: `backend/tests/test_poller_ingest.py`

**Interfaces:**
- Consumes: `write_samples` (Task 2), models (`Host`, `App`, `Vm`, `CatalogEntry`, `MetricSample`, `utcnow`).
- Produces (consumed by Tasks 5–8):
  - `HostSnapshot` dataclass: `host_id: int`, `ts: datetime`, `nodes: list[dict]` (`{"node","status","cpu_pct","cpu_cores","mem_bytes","mem_total_bytes","uptime_s"}`), `storage: list[dict]` (`{"storage","node","used_bytes","total_bytes"}`), `net: dict` (`{"in_bps","out_bps"}`), `guests: dict[tuple[str,int], dict]` (key `("lxc"|"qemu", vmid)`; value `{"name","node","status","cpu_pct","cpu_cores","mem_bytes","mem_total_bytes","disk_bytes","uptime_s"}`), `discovered: list[dict]` (`{"ctid","name","node","status","suggestion"}`).
  - `CycleResult` dataclass: `snapshot: HostSnapshot`, `events: list[tuple[str, dict]]` (SSE `(event_name, payload)` pairs; first is always the `metrics` event).
  - `ingest_cycle(db, host: Host, resources: list[dict], rrd_by_node: dict[str, list[dict]], now: datetime) -> CycleResult` — updates host status/last_seen, refreshes `apps.*_cached`, upserts/deletes `vms`, writes samples, **commits once**.
  - `tests/support.py`: `make_app(tmp_path, fake=None, **overrides) -> FastAPI` (poller **off** by default via `poll_enabled=False` — Task 5 adds the setting; until then the kwarg is simply accepted by `Settings`... see Step 1 note), `seed_host(app, ...) -> int`, `seed_snapshot(app, host_id, **kw)`.
  - Note: `make_app`/`seed_snapshot` reference `poll_enabled` and `app.state.poller`, which land in Task 5. **In this task**, `support.py` is created with `make_app`/`seed_host` only using a plain `Settings(...)` without `poll_enabled`; Task 5's steps add the kwarg and `seed_snapshot`. The ingest tests below use a bare sessionmaker, not the app.

- [ ] **Step 1: Create `backend/tests/support.py`** (shared builders; extended in Task 5):

```python
"""Shared Phase 2 test builders."""
from pathlib import Path


def make_db(tmp_path: Path):
    """Migrated bare session for service-level tests."""
    from proxploy.config import Settings
    from proxploy.db import make_engine, make_sessionmaker, run_migrations

    s = Settings(db_url=f"sqlite:///{tmp_path}/t.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key")
    run_migrations(s)
    return make_sessionmaker(make_engine(s))()


def seed_host_row(db, name="host-01", node="pve1", status="connected"):
    from proxploy.models import Host

    h = Host(name=name, address=f"https://{name}:8006", node_name=node,
             status=status, pve_version="8.4.1")
    db.add(h)
    db.commit()
    return h
```

- [ ] **Step 2: Write the failing test** — `backend/tests/test_poller_ingest.py`:

```python
"""ingest_cycle: one bulk read -> caches + samples + snapshot + SSE events."""
import json
from pathlib import Path

FIX = Path(__file__).parent / "fixtures" / "pve"


def _fixtures():
    resources = json.loads((FIX / "cluster_resources_basic.json").read_text())
    rrd = {"pve1": json.loads((FIX / "rrddata_hour.json").read_text())}
    return resources, rrd


def _ingest(db, host):
    from proxploy.models import utcnow
    from proxploy.pollers import ingest_cycle

    resources, rrd = _fixtures()
    return ingest_cycle(db, host, resources, rrd, utcnow())


def test_host_samples_and_snapshot(tmp_path):
    from proxploy.models import MetricSample
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db, status="unreachable")
    res = _ingest(db, host)

    assert host.status == "connected" and host.last_seen_at is not None
    metrics = {s.metric for s in db.query(MetricSample).filter_by(
        target_type="host", target_id=host.id)}
    assert metrics == {"cpu_pct", "mem_bytes", "net_in_bps", "net_out_bps"}

    snap = res.snapshot
    assert snap.nodes[0]["node"] == "pve1" and snap.nodes[0]["cpu_cores"] == 8
    assert snap.nodes[0]["cpu_pct"] == 42.0
    assert len(snap.storage) == 2
    assert snap.net["in_bps"] == 1300000.0  # latest rrd row
    # recovery from unreachable publishes a host resource event
    assert ("resource", {"type": "host", "id": host.id,
                         "change": "status", "status": "connected"}) in res.events
    # first event is always the metrics delta
    assert res.events[0][0] == "metrics"
    assert {t["t"] for t in res.events[0][1]["targets"]} >= {"host"}


def test_vms_upserted_and_apps_cached_refreshed(tmp_path):
    from proxploy.models import App, MetricSample, Vm
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db)
    db.add(App(host_id=host.id, ctid=150, name="Immich", slug="immich",
               status_cached="stopped"))
    db.commit()

    res = _ingest(db, host)

    vm = db.query(Vm).filter_by(host_id=host.id, vmid=100).one()
    assert vm.status == "running" and vm.name == "win11"
    assert vm.mem_bytes == 8589934592 and vm.cpu_cores == 4
    app_row = db.query(App).filter_by(ctid=150).one()
    assert app_row.status_cached == "running"
    assert app_row.cpu_pct_cached == 12.0
    assert app_row.mem_bytes_cached == 2147483648
    # stopped->running transition emitted a resource event
    assert ("resource", {"type": "app", "id": app_row.id,
                         "change": "status", "status": "running"}) in res.events
    # guest samples reference DB ids, not vmids
    assert db.query(MetricSample).filter_by(target_type="app",
                                            target_id=app_row.id).count() == 2
    assert db.query(MetricSample).filter_by(target_type="vm",
                                            target_id=vm.id).count() == 2


def test_vm_removed_upstream_is_deleted(tmp_path):
    from proxploy.models import Vm
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db)
    db.add(Vm(host_id=host.id, vmid=999, name="gone", status="running"))
    db.commit()
    res = _ingest(db, host)
    assert db.query(Vm).filter_by(vmid=999).count() == 0
    assert ("resource", {"type": "vm", "change": "list"}) in res.events


def test_discovered_cts_with_catalog_suggestion(tmp_path):
    from proxploy.models import App, CatalogEntry
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db)
    db.add(App(host_id=host.id, ctid=150, name="Immich", slug="immich"))
    db.add(CatalogEntry(slug="plex", name="Plex", script_path="ct/plex.sh"))
    db.commit()
    res = _ingest(db, host)
    disc = res.snapshot.discovered
    assert [d["ctid"] for d in disc] == [200]  # 150 is mapped, not discovered
    assert disc[0]["suggestion"] == "plex" and disc[0]["name"] == "plex"
```

- [ ] **Step 3: Run it to make sure it fails**

Run: `python -m pytest tests/test_poller_ingest.py -q`
Expected: FAIL — `ImportError` (no `proxploy.pollers`).

Note: if `CatalogEntry(...)` or `App(...)` raise on missing NOT-NULL columns, check `models/__init__.py` for required fields and add the minimal ones to the test seeds — the models are authoritative.

- [ ] **Step 4: Implement** — `backend/proxploy/pollers/__init__.py`:

```python
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
```

- [ ] **Step 5: Run the tests and make sure they pass**

Run: `python -m pytest tests/test_poller_ingest.py -q`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/proxploy/pollers/__init__.py backend/tests/support.py \
        backend/tests/test_poller_ingest.py
git commit -m "feat(backend): poller ingest — caches, samples, discovery heuristics"
```

---

### Task 4: EventBus + SSE `GET /api/v1/events/stream`

Doc refs: 05 §Streaming 4 (protocol, auth, payloads), 02 §11.1 (invalidation bus), 06 §(d) (client contract).

**Files:**
- Create: `backend/proxploy/events.py`
- Create: `backend/proxploy/api/events.py`
- Modify: `backend/proxploy/api/__init__.py` (register router)
- Modify: `backend/proxploy/main.py` (this task: `app.state.bus = EventBus()` in lifespan, before `yield`)
- Test: `backend/tests/test_events_sse.py`

**Interfaces:**
- Consumes: `resolve_session` (the same import `api/deps.py` uses — `from proxploy.services.authn import resolve_session`; verify against `deps.py` and match it), `app.state.sessionmaker`, settings `session_cookie`.
- Produces:
  - `EventBus`: `subscribe() -> asyncio.Queue`, `unsubscribe(q)`, `publish(event: str, data: dict)` (non-blocking; drops to slow consumers).
  - Route `GET /api/v1/events/stream` — `text/event-stream`; frames `event: <name>\ndata: <json>\n\n`; `: ping` comment every 15 s idle; 401 without a session. **Auth is resolved with a short-lived DB session before streaming starts** (never hold `get_db` open for the stream's lifetime).

- [ ] **Step 1: Write the failing test** — `backend/tests/test_events_sse.py`:

```python
"""In-process event bus + SSE fanout endpoint (doc 05 §Streaming 4)."""
import asyncio


def test_bus_fanout_and_slow_consumer_drop():
    from proxploy.events import EventBus

    async def run():
        bus = EventBus()
        q1, q2 = bus.subscribe(), bus.subscribe()
        bus.publish("metrics", {"targets": []})
        assert q1.get_nowait() == ("metrics", {"targets": []})
        assert q2.get_nowait() == ("metrics", {"targets": []})
        bus.unsubscribe(q2)
        bus.publish("resource", {"type": "app"})
        assert q1.get_nowait()[0] == "resource"
        assert q2.empty()
        # a full queue drops instead of blocking the publisher
        small = bus.subscribe()
        for _ in range(500):
            bus.publish("metrics", {})
        assert small.full()

    asyncio.run(run())


def test_sse_requires_session(tmp_path):
    from fastapi.testclient import TestClient
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        r = c.get("/api/v1/events/stream")
        assert r.status_code == 401


def test_sse_streams_published_events(tmp_path, csrf_header, bootstrap_admin):
    from fastapi.testclient import TestClient
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        # publish from the app's own loop once the subscriber is attached
        async def publish_soon():
            await asyncio.sleep(0.2)
            app.state.bus.publish("metrics", {"targets": [{"t": "host", "id": 1}]})
        import anyio
        with c.stream("GET", "/api/v1/events/stream") as r:
            assert r.headers["content-type"].startswith("text/event-stream")
            app.state.loop.call_soon_threadsafe(asyncio.ensure_future, publish_soon())
            lines = []
            for line in r.iter_lines():
                lines.append(line)
                if any(ln.startswith("data:") for ln in lines):
                    break
            assert any(ln == "event: metrics" for ln in lines)
            assert any('"t": "host"' in ln or '"t":"host"' in ln
                       for ln in lines if ln.startswith("data:"))
```

Note for the implementer: the test needs the app's running loop to schedule the publish — expose it as `app.state.loop` in lifespan (one line, set before `yield`). Drop the unused `anyio` import if the linter/typecheck complains; it's not needed.

Also extend `backend/tests/support.py` with the app builder used above:

```python
def make_app(tmp_path, fake=None, **overrides):
    """App with poller/metrics loops OFF by default; FakePVE optional."""
    from proxploy.api.auth import limiter
    from proxploy.config import Settings
    from proxploy.main import create_app

    limiter.reset()
    kwargs = {}
    if fake is not None:
        from tests.fakes.pve import make_fake_factory
        kwargs["proxmox_factory"] = make_fake_factory(fake)
    s = Settings(db_url=f"sqlite:///{tmp_path}/t.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key",
                 poll_enabled=False, **overrides)
    return create_app(s, **kwargs)
```

`poll_enabled` doesn't exist on `Settings` until Task 5 — **add it now** in `backend/proxploy/config.py` alongside the other fields (Task 5 wires the behavior):

```python
    poll_enabled: bool = True
    poll_interval_s: float = 30.0
    poll_timeout_s: float = 20.0
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/test_events_sse.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'proxploy.events'`.

- [ ] **Step 3: Implement `backend/proxploy/events.py`**:

```python
"""In-process pub/sub bus (doc 02 §11.1): plain asyncio queues, no broker.

Zero subscribers costs nothing; a slow consumer loses deltas, and the UI's
interval refetch heals it (doc 06 §d — SSE is a hint channel, never the
source of truth).
"""
from __future__ import annotations

import asyncio


class EventBus:
    def __init__(self) -> None:
        self._subs: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def publish(self, event: str, data: dict) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait((event, data))
            except asyncio.QueueFull:
                pass
```

- [ ] **Step 4: Implement `backend/proxploy/api/events.py`**:

```python
"""SSE live-events endpoint (doc 05 §Streaming 4): one-way JSON deltas."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from proxploy.services.authn import resolve_session

router = APIRouter(prefix="/events", tags=["events"])

PING_S = 15


@router.get("/stream")
async def events_stream(request: Request):
    # Resolve auth with a short-lived session — never hold a DB connection
    # open for the lifetime of the stream.
    raw = request.cookies.get(request.app.state.settings.session_cookie)

    def check():
        with request.app.state.sessionmaker() as db:
            return resolve_session(db, raw) if raw else None

    user = await asyncio.to_thread(check)
    if user is None:
        raise HTTPException(401, "authentication required")

    bus = request.app.state.bus

    async def gen():
        q = bus.subscribe()
        try:
            yield ": connected\n\n"
            while True:
                try:
                    event, data = await asyncio.wait_for(q.get(), timeout=PING_S)
                    yield f"event: {event}\ndata: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
```

- [ ] **Step 5: Wire into the app.** In `backend/proxploy/api/__init__.py` add `events` to the import and `api_router.include_router(events.router)`. In `main.py`'s lifespan, before `yield`:

```python
        from proxploy.events import EventBus

        app.state.bus = EventBus()
        app.state.loop = asyncio.get_running_loop()  # test seam for cross-thread publishes
```

- [ ] **Step 6: Run the tests and make sure they pass**

Run: `python -m pytest tests/test_events_sse.py -q`
Expected: 3 passed. If the stream test hangs, the publish never reached the loop — check `app.state.loop` is set and the `call_soon_threadsafe` line matches.

- [ ] **Step 7: Commit**

```bash
git add backend/proxploy/events.py backend/proxploy/api/events.py \
        backend/proxploy/api/__init__.py backend/proxploy/main.py \
        backend/proxploy/config.py backend/tests/support.py backend/tests/test_events_sse.py
git commit -m "feat(backend): in-process event bus + SSE /events/stream"
```

---

### Task 5: Poller supervisor — per-host loops, backoff, degradation, lifespan wiring

Doc refs: 02 §3 (per-host loops, timeout + backoff, degrade only its own loop), 10 Phase 2 DoD (≤35 s staleness; killed host → `unreachable` without breaking the UI).

**Files:**
- Modify: `backend/proxploy/pollers/__init__.py` (append `Poller`)
- Modify: `backend/proxploy/main.py` (lifespan: start/stop poller + metrics loop)
- Modify: `backend/tests/support.py` (append `seed_snapshot`)
- Test: `backend/tests/test_poller_loop.py`

**Interfaces:**
- Consumes: `ingest_cycle`/`HostSnapshot` (Task 3), `EventBus` (Task 4), `metrics_loop` (Task 2), `ProxmoxClient.cluster_resources/node_rrddata` (Task 1), credential-fetch idiom from `hosts.py:137-142`, `Settings.poll_enabled/poll_interval_s/poll_timeout_s` (added in Task 4).
- Produces (consumed by Tasks 6–8 endpoints and their tests):
  - `Poller(app)` with `snapshots: dict[int, HostSnapshot]`, `async run()` (supervisor: sync per-host tasks with the hosts table every interval), `stop()` (cancel all host tasks). Always constructed in lifespan (`app.state.poller`), even when `poll_enabled=False` — endpoints read `snapshots` unconditionally.
  - Failure behavior: a failing/hanging host marks only itself `unreachable` (commit + `resource` event `{"type":"host",...}`), backs off `interval * 2**fails` capped at 300 s, and recovers to `connected` on the next good cycle (event emitted by `ingest_cycle`).
  - `tests/support.py`: `seed_snapshot(app, host_id, **kw)` — stuffs a `HostSnapshot` into `app.state.poller.snapshots` for endpoint tests that don't run loops.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_poller_loop.py`:

```python
"""Poller loops end-to-end against FakePVE: populate, stream, degrade, recover."""
import json
import time
from pathlib import Path

FIX = Path(__file__).parent / "fixtures" / "pve"
HOST = {"name": "host-01", "address": "https://pve1:8006",
        "token_id": "proxploy@pve!mon", "token_secret": "s3cret",
        "verify_tls": True}


def _wait(fn, timeout=8.0, msg="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fn():
            return
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {msg}")


def test_poller_populates_degrades_recovers(tmp_path, csrf_header, bootstrap_admin):
    from fastapi.testclient import TestClient
    from tests.fakes.pve import FakePVE
    from tests.support import make_app

    fake = FakePVE(
        resources=json.loads((FIX / "cluster_resources_basic.json").read_text()),
        rrddata={"pve1": json.loads((FIX / "rrddata_hour.json").read_text())})
    app = make_app(tmp_path, fake=fake, poll_enabled=True, poll_interval_s=0.2)
    with TestClient(app) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/hosts", json=HOST, headers=csrf_header(c))
        assert r.status_code == 201, r.text
        hid = r.json()["id"]

        # within a few cycles the VM cache and snapshot populate
        _wait(lambda: c.get("/api/v1/hosts").json()[0]["status"] == "connected",
              msg="first successful cycle")
        _wait(lambda: hid in app.state.poller.snapshots, msg="snapshot")
        snap = app.state.poller.snapshots[hid]
        assert {d["ctid"] for d in snap.discovered} == {150, 200}

        # SSE carries the poller's metrics events
        with c.stream("GET", "/api/v1/events/stream") as s:
            seen = []
            for line in s.iter_lines():
                seen.append(line)
                if any(ln == "event: metrics" for ln in seen):
                    break

        # kill the host: only this host degrades, UI keeps serving
        fake.cluster.resources._fail = True
        _wait(lambda: c.get("/api/v1/hosts").json()[0]["status"] == "unreachable",
              msg="degradation to unreachable")
        assert c.get("/api/v1/hosts").status_code == 200  # UI not broken

        # recovery flips it back
        fake.cluster.resources._fail = False
        _wait(lambda: c.get("/api/v1/hosts").json()[0]["status"] == "connected",
              timeout=12.0, msg="recovery")  # generous: backoff may be in effect
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/test_poller_loop.py -q`
Expected: FAIL — snapshot never populates (`Poller` doesn't exist / isn't started).

- [ ] **Step 3: Implement `Poller`** — append to `backend/proxploy/pollers/__init__.py`:

```python
import asyncio
import json as jsonlib

from proxploy.models import HostCredential, utcnow
from proxploy.services.proxmox import ProxmoxClient

POLL_BACKOFF_CAP_S = 300


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
            except Exception:  # noqa: BLE001 — supervisor never dies
                pass
            await asyncio.sleep(interval)

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
            except Exception:  # noqa: BLE001 — degrade this host only
                fails += 1
                evt = await asyncio.to_thread(self._mark_unreachable, host_id)
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
            cred = (db.query(HostCredential)
                    .filter_by(host_id=host.id, kind="api_token").one())
            tok = jsonlib.loads(app.state.secretstore.decrypt(cred.encrypted_blob))
            client = ProxmoxClient(host.address, tok["token_id"], tok["token_secret"],
                                  verify_tls=host.verify_tls,
                                  tls_fingerprint=host.tls_fingerprint,
                                  factory=app.state.proxmox_factory)
            resources = client.cluster_resources()
            node_names = [r["node"] for r in resources if r.get("type") == "node"]
            rrd = {n: client.node_rrddata(n) for n in node_names}

            prev = self.snapshots.get(host_id)
            result = ingest_cycle(db, host, resources, rrd, utcnow())
            events = result.events
            if prev is not None and (
                    {d["ctid"] for d in prev.discovered}
                    != {d["ctid"] for d in result.snapshot.discovered}):
                events.append(("resource", {"type": "app", "change": "discovered"}))
            self.snapshots[host_id] = result.snapshot
            return events

    def _mark_unreachable(self, host_id: int):
        with self.app.state.sessionmaker() as db:
            host = db.get(Host, host_id)
            if host is None or host.status == "unreachable":
                return None
            host.status = "unreachable"
            db.commit()
            return ("resource", {"type": "host", "id": host_id,
                                 "change": "status", "status": "unreachable"})
```

(Adjust the imports at the top of the file into one block — `asyncio`, `json as jsonlib`, `re`, dataclasses, models, `ProxmoxClient`, `write_samples` — rather than a second import section mid-file.)

- [ ] **Step 4: Wire lifespan** — in `backend/proxploy/main.py`, after the bus/entitlement setup and before `yield` (mirroring the entitlement-refresh pattern):

```python
        from proxploy.pollers import Poller
        from proxploy.services.metrics import metrics_loop

        app.state.poller = Poller(app)
        poller_task = metrics_task = None
        if settings.poll_enabled:
            poller_task = asyncio.create_task(app.state.poller.run())
            metrics_task = asyncio.create_task(metrics_loop(app))
```

and after `yield`, next to the existing refresh-task cancel:

```python
        if poller_task:
            poller_task.cancel()
        if metrics_task:
            metrics_task.cancel()
        app.state.poller.stop()
```

- [ ] **Step 5: Extend `tests/support.py`** with the snapshot seeder used by Tasks 6–8:

```python
def seed_snapshot(app, host_id, **kw):
    """Endpoint tests stuff a snapshot instead of running poll loops."""
    from proxploy.models import utcnow
    from proxploy.pollers import HostSnapshot

    snap = HostSnapshot(host_id=host_id, ts=kw.pop("ts", utcnow()), **kw)
    app.state.poller.snapshots[host_id] = snap
    return snap
```

- [ ] **Step 6: Run the tests and make sure they pass**

Run: `python -m pytest tests/test_poller_loop.py -q` then the full suite
`python -m pytest tests/ -q -m "not pve_integration and not e2e"`
Expected: new test passes; **no regressions** (existing tests build apps via `create_app` with default `poll_enabled=True` but no hosts — the supervisor idles harmlessly; if any Phase 1 test flakes from the background task, that test's Settings gains `poll_enabled=False` via its fixture — prefer fixing the fixture over weakening the poller).

- [ ] **Step 7: Commit**

```bash
git add backend/proxploy/pollers/__init__.py backend/proxploy/main.py \
        backend/tests/support.py backend/tests/test_poller_loop.py
git commit -m "feat(backend): per-host poll loops with backoff, degradation, lifespan wiring"
```

---

### Task 6: Cluster endpoints — `GET /cluster/summary`, `GET /cluster/nodes`

Doc refs: 05 (Cluster & nodes table), 06 §(a) Cluster page (rings `x / y` subtotals, node cards), 10 Phase 2.

**Files:**
- Create: `backend/proxploy/api/cluster.py`
- Modify: `backend/proxploy/api/__init__.py`
- Test: `backend/tests/test_cluster_api.py`

**Interfaces:**
- Consumes: `app.state.poller.snapshots` (Task 5), `get_db`/`require_role` (Phase 1 deps), models.
- Produces (consumed by frontend Tasks 11):
  - `GET /api/v1/cluster/summary` →
    ```json
    {"updated_at": "…Z"|null,
     "cpu": {"pct": 42.0, "used_cores": 3.4, "total_cores": 8},
     "mem": {"pct": 40.6, "used_bytes": 0, "total_bytes": 0},
     "storage": {"pct": 20.5, "used_bytes": 0, "total_bytes": 0},
     "net": {"in_bps": 0.0, "out_bps": 0.0},
     "counts": {"hosts": 1, "hosts_online": 1, "nodes": 1,
                "apps": 0, "apps_running": 0, "vms": 1, "vms_running": 1}}
    ```
  - `GET /api/v1/cluster/nodes` → list of
    ```json
    {"host_id": 1, "name": "host-01", "node": "pve1", "status": "connected",
     "cluster": null, "pve_version": "8.4.1", "cpu_pct": 42.0, "mem_pct": 40.6,
     "mem_bytes": 0, "mem_total_bytes": 0, "uptime_s": 864000,
     "apps": 1, "apps_running": 1, "vms": 1, "vms_running": 1,
     "last_seen_at": "…Z"|null}
    ```
    (`cpu_pct`/`mem_pct`/`uptime_s` are `null` when no snapshot exists yet, e.g. host unreachable since boot.)

- [ ] **Step 1: Write the failing test** — `backend/tests/test_cluster_api.py`:

```python
"""Cluster summary + node cards from DB caches and poller snapshots."""


def _setup(tmp_path):
    from fastapi.testclient import TestClient
    from tests.support import make_app

    app = make_app(tmp_path)
    return app, TestClient(app)


def _seed(app):
    from proxploy.models import App, Vm
    from tests.support import seed_snapshot

    with app.state.sessionmaker() as db:
        from tests.support import seed_host_row
        h = seed_host_row(db)
        db.add(App(host_id=h.id, ctid=150, name="Immich", slug="immich",
                   status_cached="running"))
        db.add(Vm(host_id=h.id, vmid=100, name="win11", status="running"))
        db.commit()
        hid = h.id
    seed_snapshot(app, hid, nodes=[{
        "node": "pve1", "status": "online", "cpu_pct": 42.0, "cpu_cores": 8,
        "mem_bytes": 13743895347, "mem_total_bytes": 33822867456,
        "uptime_s": 864000}],
        storage=[{"storage": "local", "node": "pve1",
                  "used_bytes": 100, "total_bytes": 400},
                 {"storage": "local", "node": "pve2",
                  "used_bytes": 100, "total_bytes": 400}],
        net={"in_bps": 1300000.0, "out_bps": 5000000.0})
    return hid


def test_summary_aggregates_and_dedupes_storage(tmp_path, csrf_header, bootstrap_admin):
    app, c = _setup(tmp_path)
    with c:
        bootstrap_admin(c)
        _seed(app)
        r = c.get("/api/v1/cluster/summary")
        assert r.status_code == 200
        s = r.json()
        assert s["cpu"]["total_cores"] == 8 and s["cpu"]["pct"] == 42.0
        assert s["counts"] == {"hosts": 1, "hosts_online": 1, "nodes": 1,
                               "apps": 1, "apps_running": 1,
                               "vms": 1, "vms_running": 1}
        # same-named storage counted once (shared-storage dedupe)
        assert s["storage"]["total_bytes"] == 400
        assert s["net"]["in_bps"] == 1300000.0
        assert s["updated_at"] is not None


def test_nodes_cards_and_snapshotless_host(tmp_path, csrf_header, bootstrap_admin):
    app, c = _setup(tmp_path)
    with c:
        bootstrap_admin(c)
        _seed(app)
        with app.state.sessionmaker() as db:
            from tests.support import seed_host_row
            seed_host_row(db, name="host-02", node="pve2", status="unreachable")
        rows = c.get("/api/v1/cluster/nodes").json()
        assert len(rows) == 2
        one = next(r for r in rows if r["name"] == "host-01")
        two = next(r for r in rows if r["name"] == "host-02")
        assert one["cpu_pct"] == 42.0 and one["mem_pct"] == 40.6
        assert one["apps_running"] == 1 and one["vms_running"] == 1
        assert two["status"] == "unreachable" and two["cpu_pct"] is None


def test_cluster_requires_auth(tmp_path):
    _, c = _setup(tmp_path)
    with c:
        assert c.get("/api/v1/cluster/summary").status_code == 401
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/test_cluster_api.py -q`
Expected: FAIL — 404 on `/api/v1/cluster/*` (router missing).

- [ ] **Step 3: Implement** — `backend/proxploy/api/cluster.py`:

```python
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
```

Register in `backend/proxploy/api/__init__.py` (import `cluster`, `include_router(cluster.router)`).

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `python -m pytest tests/test_cluster_api.py -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/proxploy/api/cluster.py backend/proxploy/api/__init__.py \
        backend/tests/test_cluster_api.py
git commit -m "feat(backend): cluster summary + node card endpoints"
```

---

### Task 7: Apps + VMs read endpoints (`/apps`, `/apps/discovered`, `/apps/{id}`, `/vms`, `/vms/{id}`)

Doc refs: 05 (Apps/VMs tables — Phase 2 rows only), 04 (`apps` cached cols, `vms` CACHE), 06 §(a) Apps grid + VM table fields, plan decisions 1 & 5.

**Files:**
- Create: `backend/proxploy/api/apps.py`, `backend/proxploy/api/vms.py`
- Modify: `backend/proxploy/api/__init__.py`
- Test: `backend/tests/test_apps_vms_api.py`

**Interfaces:**
- Consumes: snapshots (`guests` map for `mem_total_bytes`/live `cpu_pct` enrichment), models, deps.
- Produces (consumed by frontend Tasks 12–13):
  - `GET /api/v1/apps?host=&q=&status=` → list of
    ```json
    {"id": 1, "name": "Immich", "slug": "immich", "host_id": 1,
     "host_name": "host-01", "node": "pve1", "ctid": 150,
     "category": null, "icon_initials": null, "icon_colors": null,
     "web_port": null, "web_protocol": "http", "web_path": "/",
     "status": "running", "ip": null, "cpu_pct": 12.0,
     "mem_bytes": 2147483648, "mem_total_bytes": 4294967296,
     "uptime_s": 86400, "update_available": null, "adopted": false}
    ```
    (`status` serves `status_cached` with `"unknown"` fallback; `mem_total_bytes` is snapshot-enriched, `null` without a snapshot. `q` matches name/slug case-insensitively.)
  - `GET /api/v1/apps/discovered` → list of `{"host_id", "host_name", "ctid", "name", "node", "status", "suggestion"}` — **declared before** `/apps/{app_id}` so the path literal wins.
  - `GET /api/v1/apps/{app_id}` → the list shape (404 problem+json when missing).
  - `GET /api/v1/vms?host=` → list of
    ```json
    {"id": 1, "host_id": 1, "host_name": "host-01", "vmid": 100,
     "name": "win11", "status": "running", "os_type": null,
     "cpu_cores": 4, "cpu_pct": 31.0, "mem_bytes": 8589934592,
     "disk_bytes": 68719476736, "uptime_s": 172800, "synced_at": "…Z"}
    ```
    (`cpu_pct` snapshot-enriched, else `null`.)
  - `GET /api/v1/vms/{vm_id}` → same shape.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_apps_vms_api.py`:

```python
"""Read-only Apps/VMs endpoints: cached rows + snapshot enrichment + filters."""


def _seeded(tmp_path):
    from fastapi.testclient import TestClient
    from proxploy.models import App, Vm
    from tests.support import make_app, seed_snapshot

    app = make_app(tmp_path)
    c = TestClient(app)

    def seed():
        from tests.support import seed_host_row
        with app.state.sessionmaker() as db:
            h = seed_host_row(db)
            db.add(App(host_id=h.id, ctid=150, name="Immich", slug="immich",
                       status_cached="running", cpu_pct_cached=12.0,
                       mem_bytes_cached=2147483648, uptime_s_cached=86400))
            db.add(App(host_id=h.id, ctid=151, name="Paperless", slug="paperless",
                       status_cached="stopped"))
            db.add(Vm(host_id=h.id, vmid=100, name="win11", status="running",
                      cpu_cores=4, mem_bytes=8589934592,
                      disk_bytes=68719476736, uptime_s=172800))
            db.commit()
            hid = h.id
        seed_snapshot(app, hid, guests={
            ("lxc", 150): {"name": "immich", "node": "pve1", "status": "running",
                           "cpu_pct": 12.0, "cpu_cores": 4,
                           "mem_bytes": 2147483648, "mem_total_bytes": 4294967296,
                           "disk_bytes": 0, "uptime_s": 86400},
            ("qemu", 100): {"name": "win11", "node": "pve1", "status": "running",
                            "cpu_pct": 31.0, "cpu_cores": 4,
                            "mem_bytes": 6442450944, "mem_total_bytes": 8589934592,
                            "disk_bytes": 68719476736, "uptime_s": 172800}},
            discovered=[{"ctid": 200, "name": "plex", "node": "pve1",
                         "status": "running", "suggestion": "plex"}])
        return hid
    return app, c, seed


def test_apps_list_filters_and_enrichment(tmp_path, csrf_header, bootstrap_admin):
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()
        rows = c.get("/api/v1/apps").json()
        assert len(rows) == 2
        immich = next(r for r in rows if r["slug"] == "immich")
        assert immich["status"] == "running" and immich["cpu_pct"] == 12.0
        assert immich["mem_total_bytes"] == 4294967296  # snapshot-enriched
        assert immich["host_name"] == "host-01" and immich["node"] == "pve1"
        assert [r["slug"] for r in c.get("/api/v1/apps?q=paper").json()] == ["paperless"]
        assert [r["slug"] for r in c.get("/api/v1/apps?status=running").json()] == ["immich"]
        assert c.get("/api/v1/apps?host=999").json() == []


def test_app_detail_and_404(tmp_path, csrf_header, bootstrap_admin):
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()
        aid = c.get("/api/v1/apps").json()[0]["id"]
        assert c.get(f"/api/v1/apps/{aid}").json()["id"] == aid
        assert c.get("/api/v1/apps/99999").status_code == 404


def test_discovered_lists_unadopted_cts(tmp_path, csrf_header, bootstrap_admin):
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()
        disc = c.get("/api/v1/apps/discovered").json()
        assert disc == [{"host_id": disc[0]["host_id"], "host_name": "host-01",
                         "ctid": 200, "name": "plex", "node": "pve1",
                         "status": "running", "suggestion": "plex"}]


def test_vms_list_and_detail(tmp_path, csrf_header, bootstrap_admin):
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()
        rows = c.get("/api/v1/vms").json()
        assert len(rows) == 1
        vm = rows[0]
        assert vm["name"] == "win11" and vm["cpu_pct"] == 31.0  # snapshot-enriched
        assert vm["os_type"] is None  # plan decision 5
        assert c.get(f"/api/v1/vms/{vm['id']}").json()["vmid"] == 100
        assert c.get("/api/v1/vms?host=999").json() == []
        assert c.get("/api/v1/vms/99999").status_code == 404
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/test_apps_vms_api.py -q`
Expected: FAIL — 404 (routers missing).

- [ ] **Step 3: Implement `backend/proxploy/api/apps.py`**:

```python
"""Apps read endpoints (doc 05, Phase 2 rows). Identity is ours; state is cache."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from proxploy.api.deps import get_db, require_role
from proxploy.models import App, Host, User

router = APIRouter(prefix="/apps", tags=["apps"])


def _app_out(a: App, host: Host, snapshots) -> dict:
    snap = snapshots.get(a.host_id)
    g = snap.guests.get(("lxc", a.ctid)) if snap else None
    return {
        "id": a.id, "name": a.name, "slug": a.slug,
        "host_id": a.host_id, "host_name": host.name, "node": host.node_name,
        "ctid": a.ctid, "category": a.category,
        "icon_initials": a.icon_initials, "icon_colors": a.icon_colors,
        "web_port": a.web_port, "web_protocol": a.web_protocol,
        "web_path": a.web_path,
        "status": a.status_cached or "unknown", "ip": a.ip_cached,
        "cpu_pct": a.cpu_pct_cached, "mem_bytes": a.mem_bytes_cached,
        "mem_total_bytes": g["mem_total_bytes"] if g else None,
        "uptime_s": a.uptime_s_cached,
        "update_available": a.update_available, "adopted": a.adopted,
    }


@router.get("")
def list_apps(request: Request, host: int | None = None, q: str | None = None,
              status: str | None = None, db=Depends(get_db),
              user: User = Depends(require_role("viewer"))):
    hosts = {h.id: h for h in db.query(Host).all()}
    query = db.query(App)
    if host is not None:
        query = query.filter(App.host_id == host)
    rows = []
    for a in query.order_by(App.name).all():
        if q and q.lower() not in f"{a.name} {a.slug}".lower():
            continue
        if status and (a.status_cached or "unknown") != status:
            continue
        h = hosts.get(a.host_id)
        if h is None:
            continue
        rows.append(_app_out(a, h, request.app.state.poller.snapshots))
    return rows


@router.get("/discovered")
def discovered(request: Request, db=Depends(get_db),
               user: User = Depends(require_role("viewer"))):
    """Pre-existing CTs not yet adopted (doc 05). Read-only until Phase 4."""
    hosts = {h.id: h for h in db.query(Host).all()}
    out = []
    for host_id, snap in sorted(request.app.state.poller.snapshots.items()):
        h = hosts.get(host_id)
        if h is None:
            continue
        for d in snap.discovered:
            out.append({"host_id": host_id, "host_name": h.name, **d})
    return out


@router.get("/{app_id}")
def app_detail(request: Request, app_id: int, db=Depends(get_db),
               user: User = Depends(require_role("viewer"))):
    a = db.get(App, app_id)
    if a is None:
        raise HTTPException(404, "app not found")
    host = db.get(Host, a.host_id)
    return _app_out(a, host, request.app.state.poller.snapshots)
```

- [ ] **Step 4: Implement `backend/proxploy/api/vms.py`**:

```python
"""VM read endpoints (doc 05, Phase 2 rows). Pure cache mirror + snapshot cpu."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from proxploy.api.deps import get_db, require_role
from proxploy.models import Host, User, Vm

router = APIRouter(prefix="/vms", tags=["vms"])


def _vm_out(v: Vm, host: Host, snapshots) -> dict:
    snap = snapshots.get(v.host_id)
    g = snap.guests.get(("qemu", v.vmid)) if snap else None
    return {
        "id": v.id, "host_id": v.host_id, "host_name": host.name,
        "vmid": v.vmid, "name": v.name, "status": v.status,
        "os_type": v.os_type,  # NULL in Phase 2 (plan decision 5)
        "cpu_cores": v.cpu_cores,
        "cpu_pct": g["cpu_pct"] if g else None,
        "mem_bytes": v.mem_bytes, "disk_bytes": v.disk_bytes,
        "uptime_s": v.uptime_s,
        "synced_at": v.synced_at.isoformat() + "Z" if v.synced_at else None,
    }


@router.get("")
def list_vms(request: Request, host: int | None = None, db=Depends(get_db),
             user: User = Depends(require_role("viewer"))):
    hosts = {h.id: h for h in db.query(Host).all()}
    query = db.query(Vm)
    if host is not None:
        query = query.filter(Vm.host_id == host)
    return [_vm_out(v, hosts[v.host_id], request.app.state.poller.snapshots)
            for v in query.order_by(Vm.name).all() if v.host_id in hosts]


@router.get("/{vm_id}")
def vm_detail(request: Request, vm_id: int, db=Depends(get_db),
              user: User = Depends(require_role("viewer"))):
    v = db.get(Vm, vm_id)
    if v is None:
        raise HTTPException(404, "vm not found")
    return _vm_out(v, db.get(Host, v.host_id), request.app.state.poller.snapshots)
```

Register both routers in `backend/proxploy/api/__init__.py`.

- [ ] **Step 5: Run the tests and make sure they pass**

Run: `python -m pytest tests/test_apps_vms_api.py -q`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/proxploy/api/apps.py backend/proxploy/api/vms.py \
        backend/proxploy/api/__init__.py backend/tests/test_apps_vms_api.py
git commit -m "feat(backend): apps/vms read endpoints + discovered CTs"
```

---

### Task 8: `GET /api/v1/metrics/query` with the 48 h history gate

Doc refs: 05 (Metrics table: `?target=host:2&metric=cpu_pct&from=&to=&resolution=raw|5m|1h`, viewer, `metrics.history` beyond 48 h), 02 §11.1.

**Files:**
- Create: `backend/proxploy/api/metrics.py`
- Modify: `backend/proxploy/api/__init__.py`
- Test: `backend/tests/test_metrics_api.py`

**Interfaces:**
- Consumes: `query_series`/`pick_resolution`/`METRICS` (Task 2), entitlement inline-check idiom (`hosts.py:55` precedent), `utcnow`.
- Produces: `GET /api/v1/metrics/query` → `{"target": "host:1", "metric": "cpu_pct", "resolution": "raw", "ts": [...], "value": [...]}` (+`min`/`max` for rollups). Defaults: `to`=now, `from`=to−1h, `resolution`=auto by range. 422 on malformed target/metric/range; 403 `entitlement_required`/`metrics.history` when `from` is older than 48 h and the flag is off.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_metrics_api.py`:

```python
"""/metrics/query: shapes, defaults, validation, 48h entitlement gate."""
from datetime import timedelta


def _setup(tmp_path):
    from fastapi.testclient import TestClient
    from proxploy.models import MetricSample, utcnow
    from tests.support import make_app

    app = make_app(tmp_path)
    c = TestClient(app)

    def seed():
        from proxploy.services.metrics import write_samples
        now = utcnow()
        with app.state.sessionmaker() as db:
            write_samples(db, [
                MetricSample(target_type="host", target_id=1, metric="cpu_pct",
                             value=50.0, ts=now - timedelta(seconds=30 * i))
                for i in range(1, 61)])
            db.commit()
        return now
    return app, c, seed


def test_query_raw_default_hour(tmp_path, csrf_header, bootstrap_admin):
    app, c, seed = _setup(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()
        r = c.get("/api/v1/metrics/query?target=host:1&metric=cpu_pct")
        assert r.status_code == 200
        body = r.json()
        assert body["resolution"] == "raw" and len(body["ts"]) == 60
        assert body["ts"] == sorted(body["ts"])


def test_query_validation(tmp_path, csrf_header, bootstrap_admin):
    app, c, seed = _setup(tmp_path)
    with c:
        bootstrap_admin(c)
        assert c.get("/api/v1/metrics/query?target=bogus&metric=cpu_pct").status_code == 422
        assert c.get("/api/v1/metrics/query?target=disk:1&metric=cpu_pct").status_code == 422
        assert c.get("/api/v1/metrics/query?target=host:1&metric=nope").status_code == 422
        assert c.get("/api/v1/metrics/query?target=host:1&metric=cpu_pct"
                     "&resolution=2m").status_code == 422


def test_history_gate_beyond_48h(tmp_path, csrf_header, bootstrap_admin):
    from datetime import timedelta
    from proxploy.models import utcnow

    app, c, seed = _setup(tmp_path)
    with c:
        bootstrap_admin(c)
        frm = (utcnow() - timedelta(hours=72)).isoformat()
        # dormant default map: all flags ON -> allowed
        assert c.get(f"/api/v1/metrics/query?target=host:1&metric=cpu_pct"
                     f"&from={frm}").status_code == 200
        # flip the flag off (test seam used by test_hosts.py:88)
        c.app.state.entitlements._features["metrics.history"] = False
        r = c.get(f"/api/v1/metrics/query?target=host:1&metric=cpu_pct&from={frm}")
        assert r.status_code == 403
        assert r.json()["feature"] == "metrics.history"
```

(If `entitlements._features` is named differently, mirror whatever `tests/test_hosts.py` pokes — that test is the precedent.)

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/test_metrics_api.py -q`
Expected: FAIL — 404 (router missing).

- [ ] **Step 3: Implement** — `backend/proxploy/api/metrics.py`:

```python
"""Metrics range query (doc 05): series for uPlot, raw vs rollup by range."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from proxploy.api.deps import get_db, require_role
from proxploy.models import User, utcnow
from proxploy.services.metrics import METRICS, pick_resolution, query_series

router = APIRouter(prefix="/metrics", tags=["metrics"])

TARGET_TYPES = ("host", "app", "vm")


def _parse_ts(raw: str) -> datetime:
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(422, f"bad timestamp {raw!r}")
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


@router.get("/query")
def metrics_query(request: Request, target: str, metric: str,
                  frm: str | None = Query(None, alias="from"),
                  to: str | None = None, resolution: str | None = None,
                  db=Depends(get_db),
                  user: User = Depends(require_role("viewer"))):
    try:
        ttype, raw_id = target.split(":", 1)
        tid = int(raw_id)
    except ValueError:
        raise HTTPException(422, "target must look like host:1 / app:3 / vm:2")
    if ttype not in TARGET_TYPES:
        raise HTTPException(422, f"unknown target type {ttype!r}")
    if metric not in METRICS:
        raise HTTPException(422, f"unknown metric {metric!r}")
    if resolution is not None and resolution not in ("raw", "5m", "1h"):
        raise HTTPException(422, "resolution must be raw|5m|1h")

    now = utcnow()
    to_dt = _parse_ts(to) if to else now
    frm_dt = _parse_ts(frm) if frm else to_dt - timedelta(hours=1)
    if frm_dt >= to_dt:
        raise HTTPException(422, "from must be before to")

    # metrics.history gates only the deep past (doc 05) — inline conditional
    # check, hosts.multi precedent
    if (frm_dt < now - timedelta(hours=48)
            and not request.app.state.entitlements.enabled("metrics.history")):
        raise HTTPException(403, {"error": "entitlement_required",
                                  "feature": "metrics.history"})

    res = resolution or pick_resolution(frm_dt, to_dt)
    out = query_series(db, ttype, tid, metric, frm_dt, to_dt, res)
    return {"target": target, "metric": metric, **out}
```

Register in `backend/proxploy/api/__init__.py`. Full backend suite check:
`python -m pytest tests/ -q -m "not pve_integration and not e2e"` — everything green, `python scripts/check_executor_isolation.py` → OK.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `python -m pytest tests/test_metrics_api.py -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/proxploy/api/metrics.py backend/proxploy/api/__init__.py \
        backend/tests/test_metrics_api.py
git commit -m "feat(backend): metrics query endpoint with 48h history gate"
```

---

### Task 9: Frontend — uPlot, format helpers, shared observe components

Doc refs: 06 §(b) component inventory (StatRings, NodeCard, UsageBar, AppCard, StatusPill, KVGrid, Sparkline), 06 §(c) tokens/gradients, 03 (uPlot MIT).

**Files:**
- Modify: `frontend/package.json` (add `uplot`)
- Create: `frontend/src/lib/format.ts`, `frontend/src/components/charts/Sparkline.tsx`,
  `frontend/src/components/{StatusPill,UsageBar,KVGrid,StatRings,NodeCard,AppCard}.tsx`
- Modify: `frontend/src/api/hooks.ts` (add `useMetrics` + row types)
- Test: `frontend/src/tests/format.test.ts`

**Interfaces:**
- Consumes: `api<T>()` client, token utilities (`bg-panel`, `text-text-2`, `font-mono`, …), existing `Button`.
- Produces (consumed by Tasks 11–13):
  - `fmtBytes(n?: number|null): string`, `fmtUptime(s?: number|null): string`, `fmtPct(n?: number|null): string`, `fmtBps(bytesPerSec?: number|null): string` (bytes/s → Mbps text).
  - `Sparkline({ ts, values, color, width?, height? })` — uPlot area+line, prototype spark look (2px stroke, gradient fill 35%→0 alpha); renders an empty box when `ts` is empty (safe under jsdom).
  - `StatusPill({ status })`, `UsageBar({ pct, gradient? })` + exported gradient constants `CPU_GRADIENT`, `RAM_GRADIENT`, `STORAGE_GRADIENT`, `KVGrid({ items })`, `Ring({ label, pct, sub, stops })` (prototype dasharray math, `CIRC = 326.7`).
  - `NodeCard({ node })` (a `/cluster/nodes` row: body click → `/apps?host=`, hostname link → `/cluster/$hostId` — plan decision 3), `AppCard({ app })` (an `/apps` row; card click → `/apps/$appId`; actions arrive Phase 3).
  - `useMetrics(target: string | null, metric: string, hours?: number)` → query on key `['metrics', target, metric, hours]`, `refetchInterval: false` (SSE-invalidated per doc 06); exported `Series`, `AppRow`, `VmRow`, `NodeRow`, `Summary` types in `hooks.ts` matching the Task 6/7 response shapes exactly.

- [ ] **Step 1: Install uPlot** (from `frontend/`): `npm install uplot`
Expected: `uplot` (^1.6.x) in `dependencies`.

- [ ] **Step 2: Write the failing test** — `frontend/src/tests/format.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { fmtBps, fmtBytes, fmtPct, fmtUptime } from '../lib/format'

describe('format helpers', () => {
  it('formats bytes with binary units', () => {
    expect(fmtBytes(0)).toBe('0.0 B')
    expect(fmtBytes(4294967296)).toBe('4.0 GiB')
    expect(fmtBytes(null)).toBe('—')
  })
  it('formats uptime coarsely', () => {
    expect(fmtUptime(90)).toBe('1m')
    expect(fmtUptime(7260)).toBe('2h 1m')
    expect(fmtUptime(864000)).toBe('10d 0h')
    expect(fmtUptime(null)).toBe('—')
  })
  it('formats percents and throughput', () => {
    expect(fmtPct(41.6)).toBe('42%')
    expect(fmtPct(null)).toBe('—')
    expect(fmtBps(1250000)).toBe('10.0 Mbps')
  })
})
```

- [ ] **Step 3: Run it to make sure it fails**

Run (from `frontend/`): `npm test`
Expected: FAIL — `../lib/format` not found.

- [ ] **Step 4: Implement `frontend/src/lib/format.ts`**:

```ts
export function fmtBytes(n?: number | null): string {
  if (n == null) return '—'
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(1)} ${units[i]}`
}

export function fmtUptime(s?: number | null): string {
  if (s == null || s <= 0) return '—'
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (d > 0) return `${d}d ${h}h`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

export function fmtPct(n?: number | null): string {
  return n == null ? '—' : `${Math.round(n)}%`
}

/** bytes/s → Mbps display (network cards, doc 06 Network/throughput). */
export function fmtBps(n?: number | null): string {
  return n == null ? '—' : `${((n * 8) / 1e6).toFixed(1)} Mbps`
}
```

- [ ] **Step 5: Implement the components.**

`frontend/src/components/charts/Sparkline.tsx`:

```tsx
import { useEffect, useRef } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'

/** Prototype spark look (doc 06 §b): 2px line, gradient fill 35%→0 alpha. */
export function Sparkline({ ts, values, color, width = 300, height = 52 }: {
  ts: number[]
  values: (number | null)[]
  color: string
  width?: number
  height?: number
}) {
  const ref = useRef<HTMLDivElement>(null)
  const plot = useRef<uPlot | null>(null)
  useEffect(() => {
    if (!ref.current || ts.length === 0) return
    const opts: uPlot.Options = {
      width, height,
      legend: { show: false },
      cursor: { show: false },
      axes: [{ show: false }, { show: false }],
      scales: { x: { time: true } },
      series: [{}, {
        stroke: color,
        width: 2,
        fill: (u) => {
          const g = u.ctx.createLinearGradient(0, 0, 0, u.bbox.height)
          g.addColorStop(0, color + '59') // 35% alpha
          g.addColorStop(1, color + '00')
          return g
        },
      }],
    }
    // ponytail: destroy+recreate on data change; setData() upgrade if it flickers
    plot.current = new uPlot(opts, [ts, values], ref.current)
    return () => { plot.current?.destroy(); plot.current = null }
  }, [ts, values, color, width, height])
  if (ts.length === 0) return <div style={{ height }} className="w-full" />
  return <div ref={ref} />
}
```

`frontend/src/components/StatusPill.tsx`:

```tsx
const STYLES: Record<string, string> = {
  running: 'bg-green-dim text-green',
  connected: 'bg-green-dim text-green',
  online: 'bg-green-dim text-green',
  stopped: 'bg-panel-2 text-text-3',
  paused: 'bg-amber-dim text-amber',
  unreachable: 'bg-red-dim text-red',
  error: 'bg-red-dim text-red',
  unknown: 'bg-panel-2 text-text-3',
}

export function StatusPill({ status }: { status: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-mono text-[10.5px] uppercase ${STYLES[status] ?? STYLES.unknown}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {status}
    </span>
  )
}
```

`frontend/src/components/UsageBar.tsx` (prototype `.bar`: 6px rounded track `#1d2733`; gradients are component-level constants, doc 06 §c):

```tsx
export const CPU_GRADIENT = 'linear-gradient(90deg,#F5B544,#E0862B)'
export const RAM_GRADIENT = 'linear-gradient(90deg,#34D3C6,#5B9DF9)'
export const STORAGE_GRADIENT = 'linear-gradient(90deg,#A78BFA,#6D5AE6)'
export const DANGER_GRADIENT = 'linear-gradient(90deg,#F26D6D,#c93b3b)'

export function UsageBar({ pct, gradient = CPU_GRADIENT }: {
  pct: number | null | undefined
  gradient?: string
}) {
  const w = Math.min(100, Math.max(0, pct ?? 0))
  return (
    <div className="h-1.5 overflow-hidden rounded-full" style={{ background: '#1d2733' }}>
      <div
        className="h-full rounded-full transition-[width] duration-500 motion-reduce:transition-none"
        style={{ width: `${w}%`, background: gradient }}
      />
    </div>
  )
}
```

`frontend/src/components/KVGrid.tsx`:

```tsx
import type { ReactNode } from 'react'

export function KVGrid({ items }: { items: [string, ReactNode][] }) {
  return (
    <div className="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-4">
      {items.map(([k, v]) => (
        <div key={k}>
          <div className="text-[10.5px] uppercase tracking-wide text-text-3">{k}</div>
          <div className="mt-1 font-mono text-[13px] text-text">{v}</div>
        </div>
      ))}
    </div>
  )
}
```

`frontend/src/components/StatRings.tsx` (prototype math: `circ=326.7`, offset `circ*(1-pct/100)`, doc 06 §b):

```tsx
const CIRC = 326.7

export function Ring({ label, pct, sub, stops }: {
  label: string
  pct: number
  sub: string
  stops: [string, string]
}) {
  const id = `ring-${label.toLowerCase().replace(/\W/g, '')}`
  return (
    <div className="flex flex-col items-center gap-1.5">
      <svg width="96" height="96" viewBox="0 0 120 120" role="img" aria-label={`${label} ${Math.round(pct)}%`}>
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor={stops[0]} />
            <stop offset="100%" stopColor={stops[1]} />
          </linearGradient>
        </defs>
        <circle cx="60" cy="60" r="52" fill="none" stroke="#1d2733" strokeWidth="10" />
        <circle
          cx="60" cy="60" r="52" fill="none" stroke={`url(#${id})`} strokeWidth="10"
          strokeLinecap="round" strokeDasharray={CIRC}
          strokeDashoffset={CIRC * (1 - Math.min(100, pct) / 100)}
          transform="rotate(-90 60 60)"
          className="transition-[stroke-dashoffset] duration-700 motion-reduce:transition-none"
        />
        <text x="60" y="66" textAnchor="middle" fontSize="20" className="fill-text font-mono">
          {Math.round(pct)}%
        </text>
      </svg>
      <div className="text-[12px] text-text-2">{label}</div>
      <div className="font-mono text-[11px] text-text-3">{sub}</div>
    </div>
  )
}
```

`frontend/src/components/NodeCard.tsx`:

```tsx
import { Link, useNavigate } from '@tanstack/react-router'
import type { NodeRow } from '../api/hooks'
import { fmtPct, fmtUptime } from '../lib/format'
import { StatusPill } from './StatusPill'
import { CPU_GRADIENT, RAM_GRADIENT, UsageBar } from './UsageBar'

export function NodeCard({ node }: { node: NodeRow }) {
  const navigate = useNavigate()
  return (
    <div
      className="cursor-pointer rounded-card border border-line-soft bg-panel p-4 transition-transform hover:-translate-y-0.5 motion-reduce:transform-none"
      // body click → apps filtered by host (doc 06 NodeCard)
      onClick={() => navigate({ to: '/apps' as never, search: { host: node.host_id } as never })}
    >
      <div className="flex items-center justify-between">
        <Link
          to={'/cluster/$hostId' as never} // node detail (plan decision 3)
          params={{ hostId: String(node.host_id) } as never}
          onClick={(e) => e.stopPropagation()}
          className="font-mono text-[13px] text-text hover:text-amber"
        >
          {node.name}
        </Link>
        <StatusPill status={node.status} />
      </div>
      <div className="mt-1 text-[11px] text-text-3">
        {node.cluster ? `cluster · ${node.cluster}` : 'standalone'} · {node.node}
      </div>
      <div className="mt-3 flex gap-4 font-mono text-[11px] text-text-2">
        <span>{node.vms} VMs</span>
        <span>{node.apps} Apps</span>
        <span>{fmtUptime(node.uptime_s)}</span>
      </div>
      <div className="mt-3 space-y-2">
        <div className="flex items-center gap-2">
          <span className="w-8 text-[10.5px] uppercase text-text-3">CPU</span>
          <div className="flex-1"><UsageBar pct={node.cpu_pct} gradient={CPU_GRADIENT} /></div>
          <span className="w-9 text-right font-mono text-[11px] text-text-2">{fmtPct(node.cpu_pct)}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-8 text-[10.5px] uppercase text-text-3">RAM</span>
          <div className="flex-1"><UsageBar pct={node.mem_pct} gradient={RAM_GRADIENT} /></div>
          <span className="w-9 text-right font-mono text-[11px] text-text-2">{fmtPct(node.mem_pct)}</span>
        </div>
      </div>
    </div>
  )
}
```

`frontend/src/components/AppCard.tsx`:

```tsx
import { useNavigate } from '@tanstack/react-router'
import type { AppRow } from '../api/hooks'
import { fmtPct } from '../lib/format'
import { StatusPill } from './StatusPill'
import { CPU_GRADIENT, RAM_GRADIENT, UsageBar } from './UsageBar'

function initials(app: AppRow): string {
  return app.icon_initials ?? app.name.slice(0, 2).toUpperCase()
}

export function AppCard({ app }: { app: AppRow }) {
  const navigate = useNavigate()
  const memPct = app.mem_bytes != null && app.mem_total_bytes
    ? (app.mem_bytes / app.mem_total_bytes) * 100 : null
  const stopped = app.status !== 'running'
  return (
    <div
      className={`cursor-pointer rounded-card border border-line-soft bg-panel p-4 transition-transform hover:-translate-y-[3px] motion-reduce:transform-none ${stopped ? 'opacity-70' : ''}`}
      onClick={() => navigate({ to: '/apps/$appId' as never, params: { appId: String(app.id) } as never })}
    >
      <div className="flex items-start justify-between">
        <div
          className="flex h-10 w-10 items-center justify-center rounded-tile font-display text-[14px] font-semibold text-white"
          style={{
            background: app.icon_colors
              ? `linear-gradient(135deg, ${app.icon_colors.c1}, ${app.icon_colors.c2})`
              : 'linear-gradient(135deg,#F5B544,#E0862B)',
          }}
        >
          {initials(app)}
        </div>
        {app.update_available && (
          <span className="rounded bg-amber-dim px-1.5 py-0.5 font-mono text-[9.5px] uppercase text-amber">
            update
          </span>
        )}
      </div>
      <div className="mt-2 text-[14px] font-semibold text-text">{app.name}</div>
      <div className="font-mono text-[11px] text-text-3">
        {app.host_name} · CT {app.ctid}
      </div>
      <div className="mt-2"><StatusPill status={app.status} /></div>
      <div className="mt-3 space-y-2">
        <div className="flex items-center gap-2">
          <span className="w-8 text-[10.5px] uppercase text-text-3">CPU</span>
          <div className="flex-1"><UsageBar pct={app.cpu_pct} gradient={CPU_GRADIENT} /></div>
          <span className="w-9 text-right font-mono text-[11px] text-text-2">{fmtPct(app.cpu_pct)}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-8 text-[10.5px] uppercase text-text-3">RAM</span>
          <div className="flex-1"><UsageBar pct={memPct} gradient={RAM_GRADIENT} /></div>
          <span className="w-9 text-right font-mono text-[11px] text-text-2">{fmtPct(memPct)}</span>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 6: Add types + `useMetrics` to `frontend/src/api/hooks.ts`** (append; keep existing exports untouched):

```ts
// ---- Phase 2 (Observe) row types — mirror the backend response shapes -------
export type Summary = {
  updated_at: string | null
  cpu: { pct: number; used_cores: number; total_cores: number }
  mem: { pct: number; used_bytes: number; total_bytes: number }
  storage: { pct: number; used_bytes: number; total_bytes: number }
  net: { in_bps: number; out_bps: number }
  counts: { hosts: number; hosts_online: number; nodes: number; apps: number
    apps_running: number; vms: number; vms_running: number }
}

export type NodeRow = {
  host_id: number; name: string; node: string; status: string
  cluster: string | null; pve_version: string | null
  cpu_pct: number | null; mem_pct: number | null
  mem_bytes: number | null; mem_total_bytes: number | null
  uptime_s: number | null; apps: number; apps_running: number
  vms: number; vms_running: number; last_seen_at: string | null
}

export type AppRow = {
  id: number; name: string; slug: string; host_id: number; host_name: string
  node: string; ctid: number; category: string | null
  icon_initials: string | null; icon_colors: { c1: string; c2: string } | null
  web_port: number | null; web_protocol: string | null; web_path: string | null
  status: string; ip: string | null; cpu_pct: number | null
  mem_bytes: number | null; mem_total_bytes: number | null
  uptime_s: number | null; update_available: string | null; adopted: boolean
}

export type DiscoveredRow = {
  host_id: number; host_name: string; ctid: number; name: string | null
  node: string | null; status: string; suggestion: string | null
}

export type VmRow = {
  id: number; host_id: number; host_name: string; vmid: number; name: string
  status: string; os_type: string | null; cpu_cores: number | null
  cpu_pct: number | null; mem_bytes: number | null; disk_bytes: number | null
  uptime_s: number | null; synced_at: string | null
}

export type Series = {
  target: string; metric: string; resolution: string
  ts: number[]; value: number[]; min?: number[]; max?: number[]
}

export function useMetrics(target: string | null, metric: string, hours = 24) {
  return useQuery({
    queryKey: ['metrics', target, metric, hours],
    enabled: !!target,
    refetchInterval: false, // SSE-invalidated (doc 06 §d)
    queryFn: () => {
      const to = new Date()
      const from = new Date(to.getTime() - hours * 3600_000)
      return api<Series>(
        `/metrics/query?target=${target}&metric=${metric}` +
        `&from=${from.toISOString()}&to=${to.toISOString()}`,
      )
    },
  })
}
```

- [ ] **Step 7: Run the tests and the build**

Run: `npm test && npm run build`
Expected: all tests pass (new `format.test.ts` green, existing 5 untouched); `tsc -b` clean. Unused-symbol errors (`noUnusedLocals`) mean a component imports something it doesn't use — fix the import, don't disable the rule.

- [ ] **Step 8: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/lib/format.ts \
        frontend/src/components/charts/Sparkline.tsx frontend/src/components/StatusPill.tsx \
        frontend/src/components/UsageBar.tsx frontend/src/components/KVGrid.tsx \
        frontend/src/components/StatRings.tsx frontend/src/components/NodeCard.tsx \
        frontend/src/components/AppCard.tsx frontend/src/api/hooks.ts \
        frontend/src/tests/format.test.ts
git commit -m "feat(frontend): uPlot sparkline + shared observe components"
```

---

### Task 10: Frontend — LiveProvider: SSE → TanStack Query cache binding

Doc refs: 06 §(d) (one EventSource per tab, patch-vs-invalidate rules, LivePulse), 05 §Streaming 4 (event shapes), plan decision 9.

**Files:**
- Create: `frontend/src/api/live.ts`, `frontend/src/components/LiveProvider.tsx`
- Modify: `frontend/src/router.tsx` (wrap the shell in `LiveProvider`)
- Test: `frontend/src/tests/live.test.ts`

**Interfaces:**
- Consumes: `QueryClient`, Task 6/7 row shapes.
- Produces (consumed by Tasks 11–13):
  - `applyMetrics(qc, data)` — patches `cpu_pct`/`mem_pct` into `['cluster','nodes']` rows and `cpu_pct` into `['apps'…]`/`['vms'…]` list caches; invalidates `['cluster','summary']` and `['metrics']` (decision 9).
  - `applyResource(qc, d)` — `change === 'status'` on app/vm → patch `status` in list + detail caches; `type === 'host'` → invalidate `['cluster']` + `['hosts']`; `change === 'discovered'` → invalidate `['apps','discovered']`; anything else → invalidate that resource family.
  - `LiveProvider({ children })` — one `EventSource('/api/v1/events/stream')`; safe no-op when `EventSource` is undefined (jsdom); exposes `useLive() → { lastEventAt }`.
  - `LivePulse` — "Live · updated Ns ago" (green pulse dot) or "Polling every 30s" fallback.

- [ ] **Step 1: Write the failing test** — `frontend/src/tests/live.test.ts`:

```ts
import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import { applyMetrics, applyResource } from '../api/live'

function client() {
  const qc = new QueryClient()
  qc.setQueryData(['cluster', 'nodes'], [
    { host_id: 1, cpu_pct: 10, mem_pct: 20 },
  ])
  qc.setQueryData(['apps', { host: undefined, q: undefined }], [
    { id: 5, status: 'stopped', cpu_pct: 0 },
  ])
  qc.setQueryData(['apps', 5], { id: 5, status: 'stopped', cpu_pct: 0 })
  qc.setQueryData(['vms', {}], [{ id: 7, status: 'running', cpu_pct: 3 }])
  return qc
}

describe('applyMetrics', () => {
  it('patches node and guest cpu/mem in place', () => {
    const qc = client()
    applyMetrics(qc, { targets: [
      { t: 'host', id: 1, cpu_pct: 55, mem_pct: 66 },
      { t: 'app', id: 5, cpu_pct: 12, mem_pct: 40 },
      { t: 'vm', id: 7, cpu_pct: 31, mem_pct: 75 },
    ] })
    expect((qc.getQueryData(['cluster', 'nodes']) as any)[0]).toMatchObject({ cpu_pct: 55, mem_pct: 66 })
    expect((qc.getQueryData(['apps', { host: undefined, q: undefined }]) as any)[0].cpu_pct).toBe(12)
    expect((qc.getQueryData(['vms', {}]) as any)[0].cpu_pct).toBe(31)
  })
})

describe('applyResource', () => {
  it('patches status deltas into list and detail caches', () => {
    const qc = client()
    applyResource(qc, { type: 'app', id: 5, change: 'status', status: 'running' })
    expect((qc.getQueryData(['apps', { host: undefined, q: undefined }]) as any)[0].status).toBe('running')
    expect((qc.getQueryData(['apps', 5]) as any).status).toBe('running')
  })
  it('leaves unrelated rows untouched', () => {
    const qc = client()
    applyResource(qc, { type: 'vm', id: 999, change: 'status', status: 'paused' })
    expect((qc.getQueryData(['vms', {}]) as any)[0].status).toBe('running')
  })
})
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `npm test`
Expected: FAIL — `../api/live` not found.

- [ ] **Step 3: Implement `frontend/src/api/live.ts`**:

```ts
import type { QueryClient } from '@tanstack/react-query'

type MetricTarget = { t: 'host' | 'app' | 'vm'; id: number; cpu_pct: number; mem_pct: number }
type ResourceEvent = { type: string; id?: number; change: string; status?: string }

/** SSE `metrics` event → patch caches (doc 06 §d: patch when the delta is complete). */
export function applyMetrics(qc: QueryClient, data: { targets: MetricTarget[] }) {
  const by = new Map(data.targets.map((t) => [`${t.t}:${t.id}`, t]))
  qc.setQueriesData({ queryKey: ['cluster', 'nodes'] }, (rows: unknown) =>
    Array.isArray(rows)
      ? rows.map((r: any) => {
          const t = by.get(`host:${r.host_id}`)
          return t ? { ...r, cpu_pct: t.cpu_pct, mem_pct: t.mem_pct } : r
        })
      : rows)
  for (const [key, kind] of [['apps', 'app'], ['vms', 'vm']] as const) {
    qc.setQueriesData({ queryKey: [key] }, (v: unknown) =>
      Array.isArray(v)
        ? v.map((r: any) => {
            const t = by.get(`${kind}:${r.id}`)
            return t ? { ...r, cpu_pct: t.cpu_pct } : r
          })
        : v)
  }
  // deltas that need recomputation → invalidate (rings, chart series).
  // ponytail: invalidating ['metrics'] refetches open charts each cycle;
  // doc 06's append-points optimization is the upgrade if it ever matters.
  qc.invalidateQueries({ queryKey: ['cluster', 'summary'] })
  qc.invalidateQueries({ queryKey: ['metrics'] })
}

/** SSE `resource` event → patch status, invalidate everything else (doc 06 §d). */
export function applyResource(qc: QueryClient, d: ResourceEvent) {
  if (d.type === 'host') {
    qc.invalidateQueries({ queryKey: ['cluster'] })
    qc.invalidateQueries({ queryKey: ['hosts'] })
    return
  }
  const key = d.type === 'app' ? 'apps' : 'vms'
  if (d.change === 'status' && d.id != null) {
    qc.setQueriesData({ queryKey: [key] }, (v: unknown) => {
      if (Array.isArray(v)) {
        return v.map((r: any) => (r.id === d.id ? { ...r, status: d.status } : r))
      }
      const row = v as { id?: number } | undefined
      return row && row.id === d.id ? { ...row, status: d.status } : v
    })
    return
  }
  if (d.change === 'discovered') {
    qc.invalidateQueries({ queryKey: ['apps', 'discovered'] })
    return
  }
  qc.invalidateQueries({ queryKey: [key] })
}
```

- [ ] **Step 4: Implement `frontend/src/components/LiveProvider.tsx`**:

```tsx
import { useQueryClient } from '@tanstack/react-query'
import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { applyMetrics, applyResource } from '../api/live'

const LiveCtx = createContext<{ lastEventAt: number | null }>({ lastEventAt: null })

export function useLive() {
  return useContext(LiveCtx)
}

/** One EventSource per tab (doc 06 §d). Query polling is the fallback if SSE dies. */
export function LiveProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const [lastEventAt, setLastEventAt] = useState<number | null>(null)
  useEffect(() => {
    if (typeof EventSource === 'undefined') return // jsdom / stripped proxies
    const es = new EventSource('/api/v1/events/stream')
    const wire = (name: string, fn: (d: any) => void) =>
      es.addEventListener(name, (e) => {
        setLastEventAt(Date.now())
        fn(JSON.parse((e as MessageEvent).data))
      })
    wire('metrics', (d) => applyMetrics(qc, d))
    wire('resource', (d) => applyResource(qc, d))
    return () => es.close()
  }, [qc])
  return <LiveCtx.Provider value={{ lastEventAt }}>{children}</LiveCtx.Provider>
}

/** Prototype `.live` badge: "Live · updated Ns ago" bound to the last SSE event. */
export function LivePulse() {
  const { lastEventAt } = useLive()
  const [, force] = useState(0)
  useEffect(() => {
    const t = setInterval(() => force((n) => n + 1), 5000)
    return () => clearInterval(t)
  }, [])
  if (!lastEventAt) {
    return <span className="font-mono text-[11px] text-text-3">Polling every 30s</span>
  }
  const secs = Math.max(0, Math.round((Date.now() - lastEventAt) / 1000))
  return (
    <span className="flex items-center gap-2 font-mono text-[11px] text-text-2">
      <span className="h-2 w-2 animate-pulse rounded-full bg-green motion-reduce:animate-none" />
      Live · updated {secs}s ago
    </span>
  )
}
```

- [ ] **Step 5: Wrap the shell.** In `frontend/src/router.tsx`, change `shellRoute`'s component so every authed page gets the stream:

```tsx
import { LiveProvider } from './components/LiveProvider'
// …
component: () => (
  <LiveProvider>
    <AppShell />
  </LiveProvider>
),
```

(Keep `beforeLoad` untouched.)

- [ ] **Step 6: Run the tests and the build**

Run: `npm test && npm run build`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/live.ts frontend/src/components/LiveProvider.tsx \
        frontend/src/router.tsx frontend/src/tests/live.test.ts
git commit -m "feat(frontend): LiveProvider — SSE to query-cache binding + LivePulse"
```

---

### Task 11: Frontend — Cluster page + node detail

Doc refs: 06 §(a) Cluster row (rings card, node cards, apps section, VM footer, throughput, activity), doc 01 §1 (`cluster.node_detail` contents), plan decisions 3 & 4.

**Files:**
- Create: `frontend/src/routes/cluster.tsx`
- Modify: `frontend/src/router.tsx` (replace the cluster placeholder; add node detail)
- Test: `frontend/src/tests/cluster.test.tsx`

**Interfaces:**
- Consumes: `Summary`/`NodeRow`/`AppRow`/`VmRow`/`Series`/`useMetrics` (Task 9), `Ring`, `NodeCard`, `AppCard`, `StatusPill`, `KVGrid`, `Sparkline`, `LivePulse`, `EmptyState`, `api`, `fmt*`.
- Produces: `clusterRoute` (`/cluster`), `nodeDetailRoute` (`/cluster/$hostId`) — both exported for `router.tsx`.

- [ ] **Step 1: Write the failing test** — `frontend/src/tests/cluster.test.tsx` (mock the api module; smoke-render the page):

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../api/client', () => ({
  api: vi.fn((path: string) => {
    if (path === '/cluster/summary') {
      return Promise.resolve({
        updated_at: '2026-07-29T00:00:00Z',
        cpu: { pct: 42, used_cores: 3.4, total_cores: 8 },
        mem: { pct: 41, used_bytes: 137, total_bytes: 338 },
        storage: { pct: 21, used_bytes: 1, total_bytes: 4 },
        net: { in_bps: 1300000, out_bps: 5000000 },
        counts: { hosts: 1, hosts_online: 1, nodes: 1, apps: 1, apps_running: 1, vms: 1, vms_running: 1 },
      })
    }
    if (path === '/cluster/nodes') {
      return Promise.resolve([{
        host_id: 1, name: 'host-01', node: 'pve1', status: 'connected',
        cluster: null, pve_version: '8.4.1', cpu_pct: 42, mem_pct: 41,
        mem_bytes: 137, mem_total_bytes: 338, uptime_s: 864000,
        apps: 1, apps_running: 1, vms: 1, vms_running: 1, last_seen_at: null,
      }])
    }
    if (path.startsWith('/apps')) return Promise.resolve([])
    if (path.startsWith('/vms')) return Promise.resolve([])
    if (path.startsWith('/hosts')) return Promise.resolve([])
    if (path.startsWith('/metrics/query')) {
      return Promise.resolve({ target: 'host:1', metric: 'net_in_bps', resolution: 'raw', ts: [], value: [] })
    }
    return Promise.resolve(null)
  }),
  ApiError: class extends Error {},
}))

// Router-dependent bits (Link/useNavigate) need a real router in tests; mock them thin.
vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ children }: { children?: unknown }) => <a>{children as never}</a>,
  useNavigate: () => () => {},
}))

import { ClusterPage } from '../routes/cluster'

describe('ClusterPage', () => {
  it('renders rings, counts and node cards from the API', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={qc}><ClusterPage /></QueryClientProvider>)
    expect(await screen.findByText('host-01')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /CPU 42%/ })).toBeInTheDocument()
    expect(screen.getByText(/Activity feed lands in Phase 3/)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `npm test`
Expected: FAIL — `../routes/cluster` has no `ClusterPage`.

- [ ] **Step 3: Implement `frontend/src/routes/cluster.tsx`**:

```tsx
import { useQuery } from '@tanstack/react-query'
import { createRoute, useParams } from '@tanstack/react-router'
import { api } from '../api/client'
import type { AppRow, NodeRow, Series, Summary, VmRow } from '../api/hooks'
import { useMetrics } from '../api/hooks'
import { AppCard } from '../components/AppCard'
import { EmptyState } from '../components/EmptyState'
import { KVGrid } from '../components/KVGrid'
import { LivePulse } from '../components/LiveProvider'
import { NodeCard } from '../components/NodeCard'
import { Sparkline } from '../components/charts/Sparkline'
import { Ring } from '../components/StatRings'
import { StatusPill } from '../components/StatusPill'
import { fmtBps, fmtBytes, fmtUptime } from '../lib/format'

const card = 'rounded-card border border-line-soft bg-panel p-5'

function useSummary() {
  return useQuery({
    queryKey: ['cluster', 'summary'],
    queryFn: () => api<Summary>('/cluster/summary'),
    refetchInterval: 30_000,
  })
}

function useNodes() {
  return useQuery({
    queryKey: ['cluster', 'nodes'],
    queryFn: () => api<NodeRow[]>('/cluster/nodes'),
    refetchInterval: 30_000,
  })
}

/** Sum per-host series into one cluster series (bucketed by shared ts). */
function sumSeries(series: (Series | undefined)[]): { ts: number[]; value: number[] } {
  const acc = new Map<number, number>()
  for (const s of series) {
    if (!s) continue
    s.ts.forEach((t, i) => acc.set(t, (acc.get(t) ?? 0) + s.value[i]))
  }
  const ts = [...acc.keys()].sort((a, b) => a - b)
  return { ts, value: ts.map((t) => acc.get(t)!) }
}

export function ClusterPage() {
  const { data: summary } = useSummary()
  const { data: nodes } = useNodes()
  const { data: apps } = useQuery({
    queryKey: ['apps', {}],
    queryFn: () => api<AppRow[]>('/apps'),
    refetchInterval: 30_000,
  })
  const { data: vms } = useQuery({
    queryKey: ['vms', {}],
    queryFn: () => api<VmRow[]>('/vms'),
    refetchInterval: 30_000,
  })
  const firstHost = nodes?.[0]?.host_id ?? null
  // ponytail: throughput sparkline charts the first host's series; multi-host
  // summed series lands when a real fleet shows it matters (net figures in the
  // header are already fleet-wide from /cluster/summary).
  const net = useMetrics(firstHost ? `host:${firstHost}` : null, 'net_in_bps', 1)

  return (
    <div>
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h1 className="font-display text-[22px] font-semibold">Cluster</h1>
          <div className="text-[12px] text-text-3">
            {summary
              ? `${summary.counts.nodes} nodes · ${summary.counts.apps} apps · ${summary.counts.vms} VMs`
              : '…'}
          </div>
        </div>
        <LivePulse />
      </div>

      <div className={`${card} flex justify-around`}>
        <Ring label="CPU" pct={summary?.cpu.pct ?? 0}
          sub={summary ? `${summary.cpu.used_cores} / ${summary.cpu.total_cores} cores` : '—'}
          stops={['#F5B544', '#E0862B']} />
        <Ring label="Memory" pct={summary?.mem.pct ?? 0}
          sub={summary ? `${fmtBytes(summary.mem.used_bytes)} / ${fmtBytes(summary.mem.total_bytes)}` : '—'}
          stops={['#34D3C6', '#5B9DF9']} />
        <Ring label="Storage" pct={summary?.storage.pct ?? 0}
          sub={summary ? `${fmtBytes(summary.storage.used_bytes)} / ${fmtBytes(summary.storage.total_bytes)}` : '—'}
          stops={['#A78BFA', '#6D5AE6']} />
      </div>

      <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-3">
        {(nodes ?? []).map((n) => <NodeCard key={n.host_id} node={n} />)}
      </div>

      <div className="mt-6">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-display text-[16px] font-semibold">Apps</h2>
          {/* as never: route typing workaround, see router.tsx */}
          <a href="/apps" className="text-[12px] text-amber hover:underline">View all</a>
        </div>
        {apps && apps.length > 0 ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {apps.slice(0, 8).map((a) => <AppCard key={a.id} app={a} />)}
          </div>
        ) : (
          <EmptyState title="No apps yet"
            note="Installed or adopted apps appear here. The App Store lands in Phase 4." />
        )}
      </div>

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className={card}>
          <h2 className="mb-3 font-display text-[16px] font-semibold">Virtual machines</h2>
          {vms && vms.length > 0 ? (
            <table className="w-full text-left text-[13px]">
              <thead>
                <tr className="text-[11px] uppercase text-text-3">
                  <th className="pb-2 font-medium">Name</th>
                  <th className="pb-2 font-medium">Node</th>
                  <th className="pb-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {vms.slice(0, 4).map((v) => (
                  <tr key={v.id} className="border-t border-line-soft hover:bg-panel-2">
                    <td className="py-2 font-mono">{v.name}</td>
                    <td className="py-2 text-text-2">{v.host_name}</td>
                    <td className="py-2"><StatusPill status={v.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <EmptyState title="No VMs discovered" note="QEMU guests on connected hosts appear here." />
          )}
        </div>
        <div className={card}>
          <h2 className="mb-1 font-display text-[16px] font-semibold">Network</h2>
          <div className="mb-2 font-mono text-[12px] text-text-2">
            ↓ {fmtBps(summary?.net.in_bps)} · ↑ {fmtBps(summary?.net.out_bps)}
          </div>
          <Sparkline ts={net.data?.ts ?? []} values={net.data?.value ?? []} color="#5B9DF9" />
          <div className="mt-4 border-t border-line-soft pt-3">
            <EmptyState title="Activity feed lands in Phase 3 (Act)"
              note="Jobs, lifecycle actions and alerts stream here once the JobBackend exists." />
          </div>
        </div>
      </div>
    </div>
  )
}

export function NodeDetailPage() {
  const { hostId } = useParams({ strict: false }) as { hostId: string }
  const id = Number(hostId)
  const { data: nodes } = useNodes()
  const node = nodes?.find((n) => n.host_id === id)
  const cpu = useMetrics(`host:${id}`, 'cpu_pct', 24)
  const mem = useMetrics(`host:${id}`, 'mem_bytes', 24)
  const { data: apps } = useQuery({
    queryKey: ['apps', { host: id }],
    queryFn: () => api<AppRow[]>(`/apps?host=${id}`),
    refetchInterval: 30_000,
  })
  const { data: vms } = useQuery({
    queryKey: ['vms', { host: id }],
    queryFn: () => api<VmRow[]>(`/vms?host=${id}`),
    refetchInterval: 30_000,
  })
  if (!node) return <EmptyState title="Node not found" note="It may have been removed." />
  return (
    <div>
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h1 className="font-mono text-[20px] font-semibold">{node.name}</h1>
          <div className="text-[12px] text-text-3">
            {node.cluster ? `cluster · ${node.cluster}` : 'standalone'} · PVE {node.pve_version ?? '?'}
          </div>
        </div>
        <StatusPill status={node.status} />
      </div>
      <div className={card}>
        <KVGrid items={[
          ['Node', node.node],
          ['PVE version', node.pve_version ?? '—'],
          ['Uptime', fmtUptime(node.uptime_s)],
          ['Memory', `${fmtBytes(node.mem_bytes)} / ${fmtBytes(node.mem_total_bytes)}`],
          ['Apps', `${node.apps_running}/${node.apps} running`],
          ['VMs', `${node.vms_running}/${node.vms} running`],
        ]} />
      </div>
      <div className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className={card}>
          <h2 className="mb-2 text-[13px] uppercase text-text-3">CPU · 24h</h2>
          <Sparkline ts={cpu.data?.ts ?? []} values={cpu.data?.value ?? []} color="#F5B544" width={480} height={120} />
        </div>
        <div className={card}>
          <h2 className="mb-2 text-[13px] uppercase text-text-3">Memory · 24h</h2>
          <Sparkline ts={mem.data?.ts ?? []} values={mem.data?.value ?? []} color="#34D3C6" width={480} height={120} />
        </div>
      </div>
      <div className="mt-5">
        <h2 className="mb-3 font-display text-[16px] font-semibold">
          Guests on this node ({(apps?.length ?? 0) + (vms?.length ?? 0)})
        </h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {(apps ?? []).map((a) => <AppCard key={a.id} app={a} />)}
        </div>
        {vms && vms.length > 0 && (
          <div className={`${card} mt-4`}>
            <table className="w-full text-left text-[13px]">
              <tbody>
                {vms.map((v) => (
                  <tr key={v.id} className="border-t border-line-soft first:border-t-0">
                    <td className="py-2 font-mono">{v.name}</td>
                    <td className="py-2 text-text-2">VMID {v.vmid}</td>
                    <td className="py-2"><StatusPill status={v.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

// Route objects — imported by router.tsx (settings.tsx precedent; circular
// import breaks `to:` inference, hence `as never` at call sites).
import { shellRoute } from '../router'

export const clusterRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/cluster',
  component: ClusterPage,
})

export const nodeDetailRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/cluster/$hostId',
  component: NodeDetailPage,
})
```

- [ ] **Step 4: Update `frontend/src/router.tsx`**: delete the `clusterRoute = page('/cluster', …)` placeholder; add `import { clusterRoute, nodeDetailRoute } from './routes/cluster'` next to the existing mid-file `settingsRoute` import; add `nodeDetailRoute` to `shellRoute.addChildren([...])` alongside `clusterRoute`.

- [ ] **Step 5: Run the tests and the build**

Run: `npm test && npm run build`
Expected: cluster test green; `nav.test.tsx` still green (nav list untouched); build clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/cluster.tsx frontend/src/router.tsx frontend/src/tests/cluster.test.tsx
git commit -m "feat(frontend): Cluster page + node detail"
```

---

### Task 12: Frontend — Apps grid + app detail (overview tab + tab shell)

Doc refs: 06 §(a) Apps row + app-detail row (tabs as child routes), 06 §(b) DiscoveredPanel/SegmentedControl/FilterInput, plan decision 1 (read-only panel).

**Files:**
- Create: `frontend/src/routes/apps.tsx`
- Modify: `frontend/src/router.tsx`
- Test: extend `frontend/src/tests/cluster.test.tsx` pattern — new file `frontend/src/tests/apps.test.tsx`

**Interfaces:**
- Consumes: `AppRow`/`DiscoveredRow`/`useMetrics` (Task 9), `AppCard`, `StatusPill`, `KVGrid`, `UsageBar`+gradients, `Sparkline`, `EmptyState`, `api`, `fmt*`, existing `Button`.
- Produces: `appsRoute` (`/apps`, search params `{host?, q?}`), `appDetailRoute` (`/apps/$appId`) with children `appOverviewRoute` (index), `appLogsRoute` (`logs`), `appConsoleRoute` (`console`), `appConfigRoute` (`config`) — the last three render honest phase notes (Logs/Console → Phase 5, Config → Phase 4) so deep links exist from day one (doc 06: tabs are child routes).

- [ ] **Step 1: Write the failing test** — `frontend/src/tests/apps.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const APP = {
  id: 1, name: 'Immich', slug: 'immich', host_id: 1, host_name: 'host-01',
  node: 'pve1', ctid: 150, category: 'Media', icon_initials: 'IM',
  icon_colors: null, web_port: 8080, web_protocol: 'http', web_path: '/',
  status: 'running', ip: '10.0.0.5', cpu_pct: 12, mem_bytes: 100,
  mem_total_bytes: 400, uptime_s: 86400, update_available: null, adopted: false,
}

vi.mock('../api/client', () => ({
  api: vi.fn((path: string) => {
    if (path.startsWith('/apps/discovered')) {
      return Promise.resolve([{ host_id: 1, host_name: 'host-01', ctid: 200,
        name: 'plex', node: 'pve1', status: 'running', suggestion: 'plex' }])
    }
    if (path.startsWith('/apps?') || path === '/apps') return Promise.resolve([APP])
    if (path.startsWith('/hosts')) {
      return Promise.resolve([{ id: 1, name: 'host-01' }])
    }
    return Promise.resolve(null)
  }),
  ApiError: class extends Error {},
}))

vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ children }: { children?: unknown }) => <a>{children as never}</a>,
  useNavigate: () => () => {},
  useSearch: () => ({}),
}))

import { AppsPage } from '../routes/apps'

describe('AppsPage', () => {
  it('renders the grid, the shown-count and the discovered panel', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={qc}><AppsPage /></QueryClientProvider>)
    expect(await screen.findByText('Immich')).toBeInTheDocument()
    expect(screen.getByText('1 shown')).toBeInTheDocument()
    expect(await screen.findByText(/plex/)).toBeInTheDocument()
    expect(screen.getByText(/Adoption arrives with the App Store phase/)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `npm test` — Expected: FAIL (`AppsPage` missing).

- [ ] **Step 3: Implement `frontend/src/routes/apps.tsx`**:

```tsx
import { useQuery } from '@tanstack/react-query'
import { createRoute, Link, Outlet, useNavigate, useParams, useSearch } from '@tanstack/react-router'
import { useState } from 'react'
import { api } from '../api/client'
import type { AppRow, DiscoveredRow } from '../api/hooks'
import { useMetrics } from '../api/hooks'
import { AppCard } from '../components/AppCard'
import { EmptyState } from '../components/EmptyState'
import { KVGrid } from '../components/KVGrid'
import { Sparkline } from '../components/charts/Sparkline'
import { StatusPill } from '../components/StatusPill'
import { RAM_GRADIENT, UsageBar } from '../components/UsageBar'
import { fmtBytes, fmtPct, fmtUptime } from '../lib/format'

const card = 'rounded-card border border-line-soft bg-panel p-5'
const inputCls = 'rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px] text-text placeholder:text-text-3 focus:outline-none focus:ring-1 focus:ring-amber'

type HostRow = { id: number; name: string }

export function AppsPage() {
  const search = useSearch({ strict: false }) as { host?: number; q?: string }
  const navigate = useNavigate()
  const [dismissed, setDismissed] = useState(false)
  const { data: hosts } = useQuery({
    queryKey: ['hosts'],
    queryFn: () => api<HostRow[]>('/hosts'),
  })
  const { data: apps } = useQuery({
    queryKey: ['apps', { host: search.host, q: search.q }],
    queryFn: () => {
      const p = new URLSearchParams()
      if (search.host != null) p.set('host', String(search.host))
      if (search.q) p.set('q', search.q)
      const qs = p.toString()
      return api<AppRow[]>(qs ? `/apps?${qs}` : '/apps')
    },
    refetchInterval: 30_000,
  })
  const { data: discovered } = useQuery({
    queryKey: ['apps', 'discovered'],
    queryFn: () => api<DiscoveredRow[]>('/apps/discovered'),
    refetchInterval: 30_000,
  })

  const setSearch = (patch: Partial<{ host?: number; q?: string }>) =>
    navigate({ to: '/apps' as never, search: { ...search, ...patch } as never, replace: true })

  return (
    <div>
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h1 className="font-display text-[22px] font-semibold">Apps</h1>
          <div className="text-[12px] text-text-3">
            {apps ? `${apps.length} installed across ${hosts?.length ?? 0} hosts` : '…'}
          </div>
        </div>
      </div>

      {discovered && discovered.length > 0 && !dismissed && (
        <div className={`${card} mb-5 border-amber-dim`}>
          <div className="flex items-center justify-between">
            <h2 className="text-[14px] font-semibold text-text">
              {discovered.length} existing container{discovered.length > 1 ? 's' : ''} discovered
            </h2>
            <button className="text-[12px] text-text-3 hover:text-text" onClick={() => setDismissed(true)}>
              Dismiss
            </button>
          </div>
          <div className="mt-2 space-y-1">
            {discovered.map((d) => (
              <div key={`${d.host_id}:${d.ctid}`} className="flex items-center gap-3 font-mono text-[12px] text-text-2">
                <span>CT {d.ctid}</span>
                <span className="text-text">{d.name ?? '—'}</span>
                <span className="text-text-3">{d.host_name}</span>
                <StatusPill status={d.status} />
                {d.suggestion && (
                  <span className="rounded bg-amber-dim px-1.5 py-0.5 text-[10px] uppercase text-amber">
                    matches “{d.suggestion}”
                  </span>
                )}
              </div>
            ))}
          </div>
          <div className="mt-3 text-[12px] text-text-3">
            Adoption arrives with the App Store phase (Phase 4) — these containers keep running untouched.
          </div>
        </div>
      )}

      <div className="mb-4 flex items-center gap-3">
        <div className="flex overflow-hidden rounded-ctl border border-line">
          <button
            className={`px-3 py-1.5 text-[12px] ${search.host == null ? 'bg-elev text-text' : 'text-text-2 hover:bg-panel-2'}`}
            onClick={() => setSearch({ host: undefined })}
          >
            All hosts
          </button>
          {(hosts ?? []).map((h) => (
            <button
              key={h.id}
              className={`border-l border-line px-3 py-1.5 text-[12px] ${search.host === h.id ? 'bg-elev text-text' : 'text-text-2 hover:bg-panel-2'}`}
              onClick={() => setSearch({ host: h.id })}
            >
              {h.name}
            </button>
          ))}
        </div>
        <input
          className={inputCls}
          placeholder="Filter apps…"
          defaultValue={search.q ?? ''}
          onChange={(e) => setSearch({ q: e.target.value || undefined })}
        />
        <span className="rounded-full bg-panel-2 px-2 py-0.5 font-mono text-[11px] text-text-2">
          {apps?.length ?? 0} shown
        </span>
      </div>

      {apps && apps.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {apps.map((a) => <AppCard key={a.id} app={a} />)}
        </div>
      ) : (
        <EmptyState title="No apps match your filter."
          note="Install from the App Store (Phase 4) or adopt discovered containers." />
      )}
    </div>
  )
}

const TABS = [
  { path: '.', label: 'Overview' },
  { path: 'logs', label: 'Logs' },
  { path: 'console', label: 'Console' },
  { path: 'config', label: 'Config' },
] as const

export function AppDetail() {
  const { appId } = useParams({ strict: false }) as { appId: string }
  const { data: app } = useQuery({
    queryKey: ['apps', Number(appId)],
    queryFn: () => api<AppRow>(`/apps/${appId}`),
    refetchInterval: 15_000,
  })
  if (!app) return <EmptyState title="Loading…" note="" />
  return (
    <div>
      <Link to={'/apps' as never} className="text-[12px] text-text-3 hover:text-text">← Apps</Link>
      <div className="mt-2 mb-4 flex items-center gap-4">
        <div
          className="flex h-14 w-14 items-center justify-center rounded-card font-display text-[18px] font-semibold text-white"
          style={{
            background: app.icon_colors
              ? `linear-gradient(135deg, ${app.icon_colors.c1}, ${app.icon_colors.c2})`
              : 'linear-gradient(135deg,#F5B544,#E0862B)',
          }}
        >
          {app.icon_initials ?? app.name.slice(0, 2).toUpperCase()}
        </div>
        <div>
          <h1 className="font-display text-[22px] font-semibold">{app.name}</h1>
          <div className="font-mono text-[12px] text-text-3">
            CT {app.ctid} · {app.host_name}{app.ip ? ` · ${app.ip}${app.web_port ? `:${app.web_port}` : ''}` : ''}
          </div>
        </div>
        <div className="ml-auto"><StatusPill status={app.status} /></div>
      </div>
      <div className="mb-5 flex gap-1 border-b border-line-soft">
        {TABS.map((t) => (
          <Link
            key={t.path}
            to={t.path as never}
            from={'/apps/$appId' as never}
            activeOptions={{ exact: t.path === '.' }}
            className="px-3 py-2 text-[13px] text-text-2 hover:text-text [&.active]:border-b-2 [&.active]:border-amber [&.active]:text-text"
          >
            {t.label}
          </Link>
        ))}
      </div>
      <Outlet />
    </div>
  )
}

export function AppOverview() {
  const { appId } = useParams({ strict: false }) as { appId: string }
  const id = Number(appId)
  const { data: app } = useQuery({
    queryKey: ['apps', id],
    queryFn: () => api<AppRow>(`/apps/${id}`),
  })
  const cpu = useMetrics(`app:${id}`, 'cpu_pct', 24)
  if (!app) return null
  const memPct = app.mem_bytes != null && app.mem_total_bytes
    ? (app.mem_bytes / app.mem_total_bytes) * 100 : null
  return (
    <div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className={card}>
          <h2 className="mb-2 text-[13px] uppercase text-text-3">CPU · 24h</h2>
          <Sparkline ts={cpu.data?.ts ?? []} values={cpu.data?.value ?? []} color="#F5B544" />
        </div>
        <div className={card}>
          <h2 className="mb-2 text-[13px] uppercase text-text-3">Memory</h2>
          <div className="mb-2 font-mono text-[13px] text-text">
            {fmtBytes(app.mem_bytes)} / {fmtBytes(app.mem_total_bytes)} ({fmtPct(memPct)})
          </div>
          <UsageBar pct={memPct} gradient={RAM_GRADIENT} />
        </div>
        <div className={card}>
          <h2 className="mb-2 text-[13px] uppercase text-text-3">Status</h2>
          <StatusPill status={app.status} />
          <div className="mt-2 font-mono text-[12px] text-text-2">up {fmtUptime(app.uptime_s)}</div>
        </div>
      </div>
      <div className={`${card} mt-4`}>
        <KVGrid items={[
          ['CTID', app.ctid],
          ['Node', app.node],
          ['IP', app.ip ?? '—'],
          ['Category', app.category ?? '—'],
          ['Web port', app.web_port ?? '—'],
          ['Update', app.update_available ?? 'Up to date'],
        ]} />
      </div>
    </div>
  )
}

// Routes (settings.tsx precedent for the circular import)
import { shellRoute } from '../router'

export const appsRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/apps',
  validateSearch: (s: Record<string, unknown>) => ({
    host: s.host != null ? Number(s.host) : undefined,
    q: typeof s.q === 'string' && s.q ? s.q : undefined,
  }),
  component: AppsPage,
})

export const appDetailRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/apps/$appId',
  component: AppDetail,
})

const phaseTab = (path: string, phase: string, note: string) =>
  createRoute({
    getParentRoute: () => appDetailRoute,
    path,
    component: () => <EmptyState title={`This tab lands in ${phase}`} note={note} />,
  })

export const appOverviewRoute = createRoute({
  getParentRoute: () => appDetailRoute,
  path: '/',
  component: AppOverview,
})
export const appLogsRoute = phaseTab('logs', 'Phase 5 (Console)',
  'Live CT logs share the log-viewer with job transcripts.')
export const appConsoleRoute = phaseTab('console', 'Phase 5 (Console)',
  'xterm.js over the proxied Proxmox termproxy websocket.')
export const appConfigRoute = phaseTab('config', 'Phase 4 (Store)',
  'The pinned community script becomes viewable and editable here.')
```

- [ ] **Step 4: Update `frontend/src/router.tsx`**: remove the apps placeholder; import `{ appsRoute, appDetailRoute, appOverviewRoute, appLogsRoute, appConsoleRoute, appConfigRoute }` from `./routes/apps`; children: `appDetailRoute.addChildren([appOverviewRoute, appLogsRoute, appConsoleRoute, appConfigRoute])`, both `appsRoute` and the detail tree added to `shellRoute.addChildren`. **Route-order note:** `/apps/$appId` and `/apps` are distinct paths; TanStack matches static-over-dynamic, so no shadowing.

- [ ] **Step 5: Run the tests and the build**

Run: `npm test && npm run build` — Expected: green.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/apps.tsx frontend/src/router.tsx frontend/src/tests/apps.test.tsx
git commit -m "feat(frontend): Apps grid + discovered panel + app detail overview"
```

---

### Task 13: Frontend — VMs table + VM detail (overview tab + tab shell)

Doc refs: 06 §(a) VMs row + VM-detail row, plan decisions 5 & 8.

**Files:**
- Create: `frontend/src/routes/vms.tsx`
- Modify: `frontend/src/router.tsx`

**Interfaces:**
- Consumes: `VmRow`/`useMetrics` (Task 9), `StatusPill`, `KVGrid`, `Sparkline`, `EmptyState`, `api`, `fmt*`.
- Produces: `vmsRoute` (`/vms`), `vmDetailRoute` (`/vms/$vmId`) with `vmOverviewRoute` (index), `vmConsoleRoute` (`console` → Phase 5 note), `vmSnapshotsRoute` (`snapshots` → Phase 6 note).

- [ ] **Step 1: Implement `frontend/src/routes/vms.tsx`** (pattern-match Task 12; smaller):

```tsx
import { useQuery } from '@tanstack/react-query'
import { createRoute, Link, Outlet, useNavigate, useParams } from '@tanstack/react-router'
import { api } from '../api/client'
import type { VmRow } from '../api/hooks'
import { useMetrics } from '../api/hooks'
import { EmptyState } from '../components/EmptyState'
import { KVGrid } from '../components/KVGrid'
import { Sparkline } from '../components/charts/Sparkline'
import { StatusPill } from '../components/StatusPill'
import { fmtBytes, fmtPct, fmtUptime } from '../lib/format'

const card = 'rounded-card border border-line-soft bg-panel p-5'

export function VmsPage() {
  const navigate = useNavigate()
  const { data: vms } = useQuery({
    queryKey: ['vms', {}],
    queryFn: () => api<VmRow[]>('/vms'),
    refetchInterval: 30_000,
  })
  const running = vms?.filter((v) => v.status === 'running').length ?? 0
  return (
    <div>
      <div className="mb-5">
        <h1 className="font-display text-[22px] font-semibold">Virtual Machines</h1>
        <div className="text-[12px] text-text-3">
          {vms ? `${vms.length} VMs · ${running} running` : '…'}
        </div>
      </div>
      {vms && vms.length > 0 ? (
        <div className={card}>
          <table className="w-full text-left text-[13px]">
            <thead>
              <tr className="text-[11px] uppercase text-text-3">
                <th scope="col" className="pb-2 font-medium">Name</th>
                <th scope="col" className="pb-2 font-medium">Node</th>
                <th scope="col" className="pb-2 font-medium">vCPU / RAM</th>
                <th scope="col" className="pb-2 font-medium">CPU</th>
                <th scope="col" className="pb-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {vms.map((v) => (
                <tr
                  key={v.id}
                  className="cursor-pointer border-t border-line-soft hover:bg-panel-2"
                  onClick={() => navigate({ to: '/vms/$vmId' as never, params: { vmId: String(v.id) } as never })}
                >
                  <td className="py-2.5 font-mono">{v.name}</td>
                  <td className="py-2.5 text-text-2">{v.host_name}</td>
                  <td className="py-2.5 font-mono text-text-2">
                    {v.cpu_cores ?? '—'} / {fmtBytes(v.mem_bytes)}
                  </td>
                  <td className="py-2.5 font-mono text-text-2">{fmtPct(v.cpu_pct)}</td>
                  <td className="py-2.5"><StatusPill status={v.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="No VMs discovered"
          note="QEMU guests on connected hosts are mirrored here by the poller." />
      )}
    </div>
  )
}

const TABS = [
  { path: '.', label: 'Overview' },
  { path: 'console', label: 'Console' },
  { path: 'snapshots', label: 'Snapshots' },
] as const

export function VmDetail() {
  const { vmId } = useParams({ strict: false }) as { vmId: string }
  const { data: vm } = useQuery({
    queryKey: ['vms', Number(vmId)],
    queryFn: () => api<VmRow>(`/vms/${vmId}`),
    refetchInterval: 15_000,
  })
  if (!vm) return <EmptyState title="Loading…" note="" />
  return (
    <div>
      <Link to={'/vms' as never} className="text-[12px] text-text-3 hover:text-text">← Virtual Machines</Link>
      <div className="mt-2 mb-4 flex items-center gap-4">
        <div>
          <h1 className="font-display text-[22px] font-semibold">{vm.name}</h1>
          <div className="font-mono text-[12px] text-text-3">
            VMID {vm.vmid} · {vm.host_name} · {vm.cpu_cores ?? '?'} vCPU / {fmtBytes(vm.mem_bytes)}
          </div>
        </div>
        <div className="ml-auto"><StatusPill status={vm.status} /></div>
      </div>
      <div className="mb-5 flex gap-1 border-b border-line-soft">
        {TABS.map((t) => (
          <Link
            key={t.path}
            to={t.path as never}
            from={'/vms/$vmId' as never}
            activeOptions={{ exact: t.path === '.' }}
            className="px-3 py-2 text-[13px] text-text-2 hover:text-text [&.active]:border-b-2 [&.active]:border-amber [&.active]:text-text"
          >
            {t.label}
          </Link>
        ))}
      </div>
      <Outlet />
    </div>
  )
}

export function VmOverview() {
  const { vmId } = useParams({ strict: false }) as { vmId: string }
  const id = Number(vmId)
  const { data: vm } = useQuery({ queryKey: ['vms', id], queryFn: () => api<VmRow>(`/vms/${id}`) })
  const cpu = useMetrics(`vm:${id}`, 'cpu_pct', 24)
  if (!vm) return null
  return (
    <div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className={card}>
          <h2 className="mb-2 text-[13px] uppercase text-text-3">CPU · 24h</h2>
          <Sparkline ts={cpu.data?.ts ?? []} values={cpu.data?.value ?? []} color="#F5B544" />
        </div>
        <div className={card}>
          <h2 className="mb-2 text-[13px] uppercase text-text-3">Status</h2>
          <StatusPill status={vm.status} />
          <div className="mt-2 font-mono text-[12px] text-text-2">up {fmtUptime(vm.uptime_s)}</div>
        </div>
        <div className={card}>
          <h2 className="mb-2 text-[13px] uppercase text-text-3">Resources</h2>
          <div className="font-mono text-[12px] text-text-2">
            {vm.cpu_cores ?? '—'} vCPU · {fmtBytes(vm.mem_bytes)} RAM · {fmtBytes(vm.disk_bytes)} disk
          </div>
        </div>
      </div>
      <div className={`${card} mt-4`}>
        <KVGrid items={[
          ['VMID', vm.vmid],
          ['Node', vm.host_name],
          ['Disk', fmtBytes(vm.disk_bytes)],
          ['OS type', vm.os_type ?? 'unknown'],
          ['Synced', vm.synced_at ?? '—'],
        ]} />
      </div>
    </div>
  )
}

import { shellRoute } from '../router'

export const vmsRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/vms',
  component: VmsPage,
})

export const vmDetailRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/vms/$vmId',
  component: VmDetail,
})

const phaseTab = (path: string, phase: string, note: string) =>
  createRoute({
    getParentRoute: () => vmDetailRoute,
    path,
    component: () => <EmptyState title={`This tab lands in ${phase}`} note={note} />,
  })

export const vmOverviewRoute = createRoute({
  getParentRoute: () => vmDetailRoute,
  path: '/',
  component: VmOverview,
})
export const vmConsoleRoute = phaseTab('console', 'Phase 5 (Console)',
  'noVNC over the proxied Proxmox vncwebsocket.')
export const vmSnapshotsRoute = phaseTab('snapshots', 'Phase 6 (Infra pages)',
  'List, create, roll back and delete snapshots.')
```

- [ ] **Step 2: Update `frontend/src/router.tsx`**: remove the vms placeholder; wire `vmsRoute` + `vmDetailRoute.addChildren([vmOverviewRoute, vmConsoleRoute, vmSnapshotsRoute])` exactly as in Task 12.

- [ ] **Step 3: Run the tests and the build**

Run: `npm test && npm run build` — Expected: green (VMs page has no dedicated test; the route wiring is exercised by `nav.test.tsx` rendering and `tsc`).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/vms.tsx frontend/src/router.tsx
git commit -m "feat(frontend): VMs table + VM detail overview"
```

---

### Task 14: Synthetic-fleet benchmark + DoD verification sweep + phase notes

Doc refs: 11 §4 ("synthetic fleet benchmark is part of Observe's DoD hardening" — produces the Postgres-recommendation numbers), 10 Phase 2 DoD.

**Files:**
- Create: `backend/scripts/bench_metrics.py`
- Create: `docs/notes/phase-2-observe.md`

- [ ] **Step 1: Implement `backend/scripts/bench_metrics.py`**:

```python
"""Synthetic-fleet MetricsStore benchmark (doc 11 §4 — Phase 2 DoD hardening).

Answers: at what fleet size does SQLite metric writing start to hurt?
Usage: python scripts/bench_metrics.py [hosts] [guests_per_host] [cycles]
"""
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path

from proxploy.config import Settings
from proxploy.db import make_engine, make_sessionmaker, run_migrations
from proxploy.models import MetricSample, utcnow
from proxploy.services.metrics import prune, rollup, write_samples


def main() -> None:
    hosts = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    guests = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    cycles = int(sys.argv[3]) if len(sys.argv) > 3 else 120  # one hour of 30s cycles

    tmp = Path(tempfile.mkdtemp(prefix="proxploy-bench-"))
    s = Settings(db_url=f"sqlite:///{tmp}/bench.db", data_dir=tmp,
                 master_key_file=tmp / "master.key")
    run_migrations(s)
    db = make_sessionmaker(make_engine(s))()

    now = utcnow()
    write_times: list[float] = []
    rows: list[MetricSample] = []
    for c in range(cycles):
        ts = now - timedelta(seconds=30 * (cycles - c))
        rows = []
        for h in range(hosts):
            for m in ("cpu_pct", "mem_bytes", "net_in_bps", "net_out_bps"):
                rows.append(MetricSample(target_type="host", target_id=h,
                                         metric=m, value=1.0, ts=ts))
            for g in range(guests):
                for m in ("cpu_pct", "mem_bytes"):
                    rows.append(MetricSample(target_type="app",
                                             target_id=h * 1000 + g,
                                             metric=m, value=1.0, ts=ts))
        t0 = time.perf_counter()
        write_samples(db, rows)
        db.commit()
        write_times.append(time.perf_counter() - t0)

    t0 = time.perf_counter()
    n5 = rollup(db, "5m", now, lookback=cycles // 10 + 2)
    t_roll = time.perf_counter() - t0
    t0 = time.perf_counter()
    pruned = prune(db, now + timedelta(hours=49))
    t_prune = time.perf_counter() - t0

    wt = sorted(write_times)
    print(f"fleet: {hosts} hosts x {guests} guests, {cycles} cycles of 30s")
    print(f"rows/cycle: {len(rows)}")
    print(f"cycle write: p50={wt[len(wt) // 2] * 1000:.1f}ms "
          f"p95={wt[int(len(wt) * 0.95)] * 1000:.1f}ms max={wt[-1] * 1000:.1f}ms")
    print(f"5m rollup: {n5} buckets in {t_roll * 1000:.0f}ms")
    print(f"prune: {pruned} in {t_prune * 1000:.0f}ms")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the benchmark at three fleet sizes** (from `backend/`):

```bash
python scripts/bench_metrics.py 1 20 120
python scripts/bench_metrics.py 4 50 120
python scripts/bench_metrics.py 8 100 120
```

Expected: completes without error; record every printed line.

- [ ] **Step 3: Run the full verification sweep**

```bash
# backend, from backend/
python -m pytest tests/ -q -m "not pve_integration and not e2e"
python scripts/check_executor_isolation.py
# frontend, from frontend/
npm test
npm run build
npm run lint
```

Expected: backend all pass (39 Phase 1 tests + ~20 new, 2 skipped as before); isolation OK; frontend tests pass; build clean. `npm run lint` (oxlint) is advisory — fix what's trivial, note the rest.

- [ ] **Step 4: Write `docs/notes/phase-2-observe.md`** — the Phase 9 docs-assembly note (doc 10 preamble) plus the doc 11 §4 numbers. Contents, with the real measured values substituted:

```markdown
# Phase 2 (Observe) — verification notes

## DoD verification map (doc 10 Phase 2)

| DoD clause | Proof |
|---|---|
| Dashboard reflects a multi-host lab live (≤35s staleness) | `tests/test_poller_loop.py` (FakePVE, 0.2s interval, populate within cycles); 30s interval + SSE push in production; live-PVE leg stays env-gated (`pve_integration`) — no PVE on this box |
| Apps and VMs discovered and rendered | `tests/test_poller_ingest.py`, `tests/test_apps_vms_api.py`; Apps grid + discovered panel + VMs table pages |
| Charts show 24h of history from rollups | `tests/test_metrics_store.py` (rollup + query), `useMetrics(…, 24)` on detail pages picks `5m` via `pick_resolution` |
| Killed host degrades to "unreachable" without breaking the UI | `tests/test_poller_loop.py` degradation + recovery assertions |

## Synthetic fleet benchmark (doc 11 §4 — Postgres recommendation data)

| Fleet | rows/cycle | write p50 | write p95 | write max | 5m rollup | prune |
|---|---|---|---|---|---|---|
| 1×20 | … | …ms | …ms | …ms | …ms | …ms |
| 4×50 | … | …ms | …ms | …ms | …ms | …ms |
| 8×100 | … | …ms | …ms | …ms | …ms | …ms |

Reading: cycle writes stay well under the 30s budget at every tested size on
SQLite-WAL. Recommend Postgres in docs at the point where p95 cycle write
exceeds ~1s (extrapolated: >N hosts / >M guests — fill from the numbers above).

## Deviations / deferred (all carried in the plan's decision log)

- Discovered CTs are surfaced read-only; explicit adoption is Phase 4.
- `/metrics/latest`, `/cluster/activity`: not in Phase 2's endpoint list; deferred.
- `vms.os_type` NULL until a user-triggered detail refresh exists (Phase 3).
- Rollup/prune on lifespan loops until APScheduler lands (Phase 7).
- SSE metrics events invalidate chart queries instead of appending points.
- Storage/network snapshots are in-memory; Phase 6 owns durable storage views.
```

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/bench_metrics.py docs/notes/phase-2-observe.md
git commit -m "chore: phase 2 synthetic-fleet benchmark + DoD verification notes"
```

---

## Plan self-review record

Checked against docs 10/05/06/04/02 before saving:

- **Spec coverage.** Doc 10 Phase 2 bullets → tasks: poller subsystem (1, 3, 5); MetricsStore writes/rollups/pruning/query (2, 8); read-only caches incl. adoption heuristics + vms + storage/network snapshots (3); pages Cluster/node-detail/Apps grid/VMs table/detail overview tabs with uPlot + SSE (4, 9–13); endpoints `/cluster/summary`, `/cluster/nodes`, `/apps`, `/vms`, `/metrics/query`, `/events/stream` (4, 6, 7, 8); DoD hardening bench (14). Deliberate exclusions are logged as decisions 1–9 with doc citations.
- **Type consistency.** `HostSnapshot` field names (`nodes/storage/net/guests/discovered`) match between Tasks 3, 5, 6, 7; response field names in Task 6/7 `Interfaces` blocks match the `hooks.ts` types in Task 9 and the page code in 11–13; `write_samples/rollup/prune/query_series/pick_resolution` signatures match between Tasks 2, 3, 8, 14; `make_app/seed_host_row/seed_snapshot` match between Tasks 3–8.
- **Placeholders.** None: every step carries runnable code or an exact command. The two intentionally-open values are measured outputs (bench table cells), which cannot be pre-filled.
