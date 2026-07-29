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
| 1×20 | 44 | 4.1ms | 4.2ms | 7.6ms | 231ms | 15ms |
| 4×50 | 416 | 34.6ms | 54.2ms | 60.3ms | 2333ms | 166ms |
| 8×100 | 1,632 | 154.7ms | 185.8ms | 219.6ms | 9185ms | 1596ms |

Reading: cycle writes stay well under the 30s budget at every tested size on
SQLite-WAL. Recommend Postgres in docs at the point where p95 cycle write
exceeds ~1s (extrapolated: ~40 hosts × 500 guests). The 5m rollup at 8×100
took 9.2s — acceptable for a background task but a flag for production ops.

## Deviations / deferred (all carried in the plan's decision log)

- Discovered CTs are surfaced read-only; explicit adoption is Phase 4.
- `/metrics/latest`, `/cluster/activity`: not in Phase 2's endpoint list; deferred.
- `vms.os_type` NULL until a user-triggered detail refresh exists (Phase 3).
- Rollup/prune on lifespan loops until APScheduler lands (Phase 7).
- SSE metrics events invalidate chart queries instead of appending points.
- Storage/network snapshots are in-memory; Phase 6 owns durable storage views.