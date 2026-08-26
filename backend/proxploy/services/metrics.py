"""MetricsStore (doc 04, doc 11 §4): raw 30s samples, 5m/1h rollups, retention.

The seam VictoriaMetrics swaps in behind for big fleets (doc 03). Writers
batch: write_samples() never commits, the poll cycle owns its one
transaction. Rollups recompute a short lookback window idempotently
(delete+insert), so a missed tick self-heals on the next one.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from proxploy.jobs import HANDLERS
from proxploy.models import MetricRollup, MetricSample, utcnow

# mem_pct/disk_pct must stay listed here: api/metrics.py 422s any metric not
# in this tuple, so a metric an alert fired on would otherwise be unqueryable.
METRICS = ("cpu_pct", "mem_pct", "disk_pct", "mem_bytes", "disk_bytes",
           "net_in_bps", "net_out_bps", "io_read_bps", "io_write_bps")

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
    db.add_all(samples)  # caller commits, one txn per poll cycle (doc 11 §4)


def rollup(db, resolution: str, now: datetime, lookback: int = 3) -> int:
    """Recompute the last `lookback` fully-elapsed buckets from raw samples."""
    secs = _RES_SECONDS[resolution]
    end = _bucket(now, secs)  # current, still-filling bucket; excluded
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


async def maintain(ctx, params: dict) -> dict:
    """`metrics.maintain`, hourly rollups + retention prune, as a real job
    (replacing Phase 2's silent `metrics_loop`). Running hourly instead of
    every five minutes is why the 5m lookback is 13: thirteen five-minute
    buckets cover the full hour plus overlap. Rollups are idempotent
    (delete+insert over the window), so a missed run self-heals. Charts under
    six hours read raw samples (`pick_resolution`), so nothing user-visible
    lags on the 5m cadence move.
    """
    app = ctx.backend.app

    def work() -> dict:
        with app.state.sessionmaker() as db:
            now = utcnow()
            rollups = {"5m": rollup(db, "5m", now, lookback=13),
                       "1h": rollup(db, "1h", now, lookback=2)}
            return {"rollups": rollups, "pruned": prune(db, now)}

    ctx.log("rolling up metric samples and applying retention")
    out = await asyncio.to_thread(work)
    ctx.log(f"5m buckets: {out['rollups']['5m']}, 1h buckets: {out['rollups']['1h']}")
    ctx.log(f"pruned raw={out['pruned']['raw']} 5m={out['pruned']['5m']} "
            f"1h={out['pruned']['1h']}")
    ctx.progress(100)
    return out


HANDLERS["metrics.maintain"] = maintain
