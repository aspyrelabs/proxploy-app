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
    (tmp / "master.key").write_bytes(b"\x00" * 32)
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

    # Clean up temp dir
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()