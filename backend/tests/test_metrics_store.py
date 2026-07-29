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
