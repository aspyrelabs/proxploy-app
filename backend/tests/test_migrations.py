import os
import re

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

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


def test_entitlement_cache_has_cert_column(tmp_path):
    """PXP-14 Option C: the cert that verifies a cached token's leaf key
    rides alongside it, un-encrypted (see EntitlementCache.cert)."""
    from proxploy.config import Settings
    from proxploy.db import run_migrations

    db_url = f"sqlite:///{tmp_path}/m.db"
    run_migrations(Settings(db_url=db_url))
    eng = create_engine(db_url)
    try:
        cols = {c["name"] for c in inspect(eng).get_columns("entitlement_cache")}
        assert "cert" in cols
    finally:
        eng.dispose()


def test_sqlite_wal(tmp_path):
    from proxploy.config import Settings
    from proxploy.db import make_engine, run_migrations

    s = Settings(db_url=f"sqlite:///{tmp_path}/w.db")
    run_migrations(s)
    eng = make_engine(s)
    with eng.connect() as c:
        assert c.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"


# --- Postgres leg of the dual-DB claim -------------------------------------
#
# Docs 02 §3 and 04 promise "Postgres via a single DSN change". That promise
# went unverified from Phase 1 until now because this leg silently skipped:
# `apps.ctid` collided with PostgreSQL's `ctid` system column, so migration
# 0001 had literally never run on Postgres. The skip reason below spells out
# that a skipped run has NOT verified anything, and the tests themselves now
# assert the schema objects exist rather than only that `upgrade()` returned.

PG_DSN = os.environ.get("PROXPLOY_TEST_PG_DSN")
requires_pg = pytest.mark.skipif(
    not PG_DSN,
    reason=("PROXPLOY_TEST_PG_DSN is unset, the Postgres half of the dual-DB "
            "claim (docs 02 §3, 04) is UNVERIFIED in this run, not passing. "
            "Set it to e.g. postgresql+psycopg://user:pw@host:5432/db."),
)


@pytest.fixture
def pg_engine():
    """A blank Postgres database, torn down after the test."""
    eng = create_engine(PG_DSN)
    with eng.begin() as c:
        c.exec_driver_sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    try:
        yield eng
    finally:
        eng.dispose()


@requires_pg
def test_migration_0001_postgres(pg_engine):
    """0001 creates every table on Postgres, and `apps` uses the physical
    column `ct_id`, `ctid` is a Postgres system column and would make the
    CREATE TABLE fail outright."""
    tables = _upgraded_tables(PG_DSN)
    assert EXPECTED <= tables

    insp = inspect(pg_engine)
    cols = {c["name"] for c in insp.get_columns("apps")}
    assert "ct_id" in cols and "ctid" not in cols
    [ux] = [u for u in insp.get_unique_constraints("apps")
            if u["name"] == "ux_apps_host_ctid"]
    assert ux["column_names"] == ["host_id", "ct_id"]

    # The constraint is not just declared, it bites.
    add_app = text(
        "INSERT INTO apps (host_id, ct_id, name, slug, web_protocol, web_path, "
        "adopted, created_at, updated_at) SELECT id, 150, 'Immich', :slug, "
        "'http', '/', false, now(), now() FROM hosts LIMIT 1")
    with pg_engine.begin() as c:
        c.execute(text("INSERT INTO hosts (name, address, verify_tls, status, "
                       "created_at, updated_at) VALUES ('h', 'https://x', true, "
                       "'connected', now(), now())"))
        c.execute(add_app, {"slug": "immich"})
    with pytest.raises(IntegrityError):
        with pg_engine.begin() as c:
            c.execute(add_app, {"slug": "immich-2"})  # same (host_id, ct_id)


@requires_pg
def test_migration_0002_postgres_applies_and_enforces_the_allowlist(pg_engine):
    """0002 uses `batch_alter_table`, which on Postgres must degrade to a
    plain ALTER TABLE ADD CONSTRAINT rather than SQLite's table-recreate.
    Prove it: step 0001 -> 0002 with a row already present, then check
    `pg_constraint` really carries the allowlist and really rejects."""
    from alembic import command

    from proxploy.models import ALLOWED_NOTIFICATION_KINDS

    cfg = _alembic_cfg(PG_DSN)
    command.upgrade(cfg, "9f3cd187d023")  # 0001 only
    _insert_raw_channel(pg_engine, "telegram")
    command.upgrade(cfg, "head")  # 0001 -> 0002, in place

    with pg_engine.connect() as c:
        assert c.execute(text("SELECT name, kind FROM notification_channels")
                         ).all() == [("leak-test", "telegram")]
        sqltext = c.execute(text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'ck_notification_channels_kind_allowlist'"
        )).scalar_one()
    assert set(re.findall(r"'([^']*)'", sqltext)) == set(ALLOWED_NOTIFICATION_KINDS)

    with pytest.raises(IntegrityError):
        _insert_raw_channel(pg_engine, "AAH-SUPERSECRETBOTTOKEN")
    for kind in [*sorted(ALLOWED_NOTIFICATION_KINDS), None]:
        _insert_raw_channel(pg_engine, kind)


# --- 0002: notification_channels.kind CHECK constraint ---------------------
#
# The prior fix made `kind_for()` an application-level allowlist. These tests
# pin the follow-up: the same allowlist enforced *by the database*, so the
# guarantee survives a writer that bypasses `kind_for()` entirely.

def _alembic_cfg(db_url):
    from pathlib import Path

    import proxploy
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(Path(proxploy.__file__).parent / "migrations"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _insert_raw_channel(engine, kind):
    """Raw SQL insert -- bypasses `kind_for()` entirely, which is the whole
    point: the constraint must hold even when the application layer doesn't."""
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO notification_channels "
                "(name, kind, url_enc, key_version, events, enabled, "
                "created_at, updated_at) VALUES "
                "(:name, :kind, :blob, 1, '[]', :enabled, "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            ),
            # `enabled` is bound, not a literal 1: Postgres rejects an integer
            # for a boolean column.
            {"name": "leak-test", "kind": kind, "blob": b"\x00", "enabled": True},
        )


def test_migration_0002_kind_constraint_matches_the_python_allowlist(tmp_path):
    """The CHECK constraint 0002 adds is built from
    `proxploy.models.ALLOWED_NOTIFICATION_KINDS` -- assert the *actually
    applied* DB constraint still names exactly that set. If a scheme is ever
    added to `KIND_FROM_SCHEME` without a follow-up migration to widen an
    already-deployed database's constraint, this is the test that would have
    caught the drift on a fresh database (an already-migrated production
    database stays correctly frozen at whatever 0002 baked in -- that's the
    point of a real migration, not a live-recomputed constraint)."""
    from proxploy.models import ALLOWED_NOTIFICATION_KINDS

    db_url = f"sqlite:///{tmp_path}/m.db"
    _upgraded_tables(db_url)
    eng = create_engine(db_url)
    try:
        constraints = inspect(eng).get_check_constraints("notification_channels")
        [kind_constraint] = [c for c in constraints
                             if c["name"] == "ck_notification_channels_kind_allowlist"]
        values = set(re.findall(r"'([^']*)'", kind_constraint["sqltext"]))
        assert values == set(ALLOWED_NOTIFICATION_KINDS)
    finally:
        eng.dispose()


def test_direct_sql_insert_of_a_disallowed_kind_is_rejected_by_the_database(tmp_path):
    """Proves the guarantee is structural, not just `kind_for`'s behaviour:
    a raw INSERT that never calls `kind_for` at all is still rejected."""
    db_url = f"sqlite:///{tmp_path}/m.db"
    _upgraded_tables(db_url)
    eng = create_engine(db_url)
    try:
        with pytest.raises(IntegrityError):
            _insert_raw_channel(eng, "AAH-SUPERSECRETBOTTOKEN")
    finally:
        eng.dispose()


def test_direct_orm_insert_of_a_disallowed_kind_is_rejected_by_the_database(tmp_path):
    """Same claim as above, through the ORM with `kind` set directly (never
    via `kind_for`) -- proves the constraint isn't something only raw SQL
    happens to trip."""
    from proxploy.models import NotificationChannel
    from tests.support import make_db

    db = make_db(tmp_path)
    row = NotificationChannel(name="leak-test", kind="AAH-SUPERSECRETBOTTOKEN",
                              url_enc=b"\x00", key_version=1)
    db.add(row)
    with pytest.raises(IntegrityError):
        db.commit()


def test_every_allowlisted_kind_and_null_are_accepted_by_the_database(tmp_path):
    """The flip side of the two rejection tests above: the constraint isn't
    over-restrictive either -- every value `kind_for` can legitimately
    return, plus NULL (kind is nullable), inserts cleanly."""
    from proxploy.models import ALLOWED_NOTIFICATION_KINDS

    db_url = f"sqlite:///{tmp_path}/m.db"
    _upgraded_tables(db_url)
    eng = create_engine(db_url)
    try:
        for kind in [*sorted(ALLOWED_NOTIFICATION_KINDS), None]:
            _insert_raw_channel(eng, kind)
    finally:
        eng.dispose()


def test_migration_0002_applies_cleanly_on_top_of_an_existing_0001_database(tmp_path):
    """`run_migrations` at startup runs against real, already-migrated
    production databases, not just fresh ones -- confirm 0002 upgrades an
    existing 0001 database in place, preserving its data, rather than only
    working in a from-scratch `head` run."""
    from alembic import command

    db_url = f"sqlite:///{tmp_path}/existing.db"
    cfg = _alembic_cfg(db_url)
    command.upgrade(cfg, "9f3cd187d023")  # 0001 only

    eng = create_engine(db_url)
    _insert_raw_channel(eng, "telegram")
    eng.dispose()

    command.upgrade(cfg, "head")  # 0001 -> 0002, in place

    eng = create_engine(db_url)
    try:
        rows = eng.connect().execute(
            text("SELECT name, kind FROM notification_channels")).all()
        assert rows == [("leak-test", "telegram")]
        with pytest.raises(IntegrityError):
            _insert_raw_channel(eng, "STILL-A-SECRET")
    finally:
        eng.dispose()
