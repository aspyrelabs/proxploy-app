import os

import pytest
from sqlalchemy import create_engine, inspect

EXPECTED = {
    "users", "sessions", "api_keys", "teams", "team_members", "casbin_rules",
    "hosts", "host_credentials", "apps", "app_scripts", "vms", "catalog_entries",
    "jobs", "job_events", "schedules", "notification_channels", "alert_rules",
    "alerts", "metric_samples", "metric_rollups", "backups", "audit_events",
    "entitlement_cache", "settings",
}


def _upgraded_tables(db_url):
    from proxploy.config import Settings
    from proxploy.db import run_migrations

    run_migrations(Settings(db_url=db_url))
    eng = create_engine(db_url)
    try:
        return set(inspect(eng).get_table_names())
    finally:
        eng.dispose()


def test_migration_0001_sqlite(tmp_path):
    tables = _upgraded_tables(f"sqlite:///{tmp_path}/m.db")
    assert EXPECTED <= tables


def test_sqlite_wal(tmp_path):
    from proxploy.config import Settings
    from proxploy.db import make_engine, run_migrations

    s = Settings(db_url=f"sqlite:///{tmp_path}/w.db")
    run_migrations(s)
    eng = make_engine(s)
    with eng.connect() as c:
        assert c.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"


@pytest.mark.skipif(not os.environ.get("PROXPLOY_TEST_PG_DSN"), reason="no Postgres DSN")
def test_migration_0001_postgres():
    tables = _upgraded_tables(os.environ["PROXPLOY_TEST_PG_DSN"])
    assert EXPECTED <= tables
