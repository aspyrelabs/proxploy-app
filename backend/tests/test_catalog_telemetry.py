"""Install popularity from upstream telemetry: the terminal-events reading of
the response, the single-column write path, and the failure modes that must
write nothing at all.

Everything here is offline: the telemetry service is faked at
`catalog_telemetry._fetch`, so no test in this file touches the network.
"""
import httpx

from proxploy.models import CatalogEntry
from proxploy.services import catalog_telemetry as ct
from tests.support import make_db


def _row(app, success=0, failed=0, aborted=0, total=None, **over):
    """One telemetry row. `total` defaults to a value far above the terminal
    sum, because that is the real endpoint's behaviour (it counts progress
    pings, not installs) and a fixture where the two agree could not catch a
    read of the wrong field."""
    record = {"app": app, "type": "lxc",
              "total": total if total is not None else (success + failed + aborted) * 7,
              "success": success, "failed": failed, "aborted": aborted,
              "installing": 3, "success_rate": 90.0,
              # Structurally always 0 upstream: both are computed only when
              # knownScripts != nil and all four call sites pass nil. Present
              # in the fixture so nobody mistakes them for a usable signal.
              "days_old": 0, "installs_per_day": 0}
    record.update(over)
    return record


def fake_telemetry(rows=None, status=200, body=None, malformed=False, seen=None):
    def fake(url, **kw):
        if seen is not None:
            seen.append(url)
        if status != 200:
            return httpx.Response(status)
        if malformed:
            # A 200 carrying something that is not JSON at all, which is what
            # a captive portal or an upstream error page actually looks like.
            return httpx.Response(200, text="<html>502 Bad Gateway</html>")
        if body is not None:
            return httpx.Response(200, json=body)
        return httpx.Response(200, json={
            "total_scripts": len(rows or []), "total_installs": 0,
            "top_scripts": rows or [], "recent_scripts": []})
    return fake


def _seed(db, slug, entry_type="ct", **kw):
    row = CatalogEntry(slug=slug, entry_type=entry_type, **kw)
    db.add(row)
    db.commit()
    return row


# --- the reading of the response -------------------------------------------

def test_popularity_is_terminal_events_and_never_the_total_field(tmp_path, monkeypatch):
    """success + failed + aborted, deduped one row per execution_id upstream.
    `total` is a raw count() over an append-only event table, so it counts
    intermediate progress pings: upstream fixed this exact bug in their own
    dashboard (a plain count() "inflated the number ~5x") and never migrated
    the endpoint we call."""
    db = make_db(tmp_path)
    _seed(db, "redis")
    monkeypatch.setattr(ct, "_fetch", fake_telemetry(rows=[
        _row("redis", success=800, failed=150, aborted=50, total=99999)]))

    out = ct.sync_popularity(db)

    row = db.query(CatalogEntry).filter_by(slug="redis").one()
    assert row.popularity == 1000
    assert row.popularity_synced_at is not None
    assert out["ok"] and out["matched"] == 1


def test_in_flight_runs_are_not_counted(tmp_path, monkeypatch):
    """`installing` is a run that has not resolved into any terminal state
    yet. Counting it would make popularity drift up and back down."""
    db = make_db(tmp_path)
    _seed(db, "redis")
    monkeypatch.setattr(ct, "_fetch", fake_telemetry(rows=[
        _row("redis", success=10, failed=1, aborted=1, installing=500)]))

    ct.sync_popularity(db)

    assert db.query(CatalogEntry).filter_by(slug="redis").one().popularity == 12


def test_terminal_events_reads_a_partial_row_and_refuses_an_unreadable_one():
    """None, never 0, for a row we cannot read: 0 is a claim that nobody has
    ever run it. `True` is excluded explicitly because bool subclasses int in
    Python, so a JSON `true` would otherwise count as one install."""
    assert ct.terminal_events({"success": 5, "failed": 2, "aborted": 1}) == 8
    assert ct.terminal_events({"success": 5}) == 5          # partial is fine
    assert ct.terminal_events({"total": 900}) is None       # no terminal keys
    assert ct.terminal_events({"success": "many"}) is None
    assert ct.terminal_events({"success": True}) is None
    assert ct.terminal_events({"success": -3}) is None
    assert ct.terminal_events({"success": 0}) == 0          # a real zero stands


def test_the_five_dual_variant_slugs_rank_by_terminal_events_not_by_total(tmp_path, monkeypatch):
    """coolify, runtipi, dockge, komodo and dokploy are the slugs this whole
    catalog's design turns on (services/catalog.py::_classify_path,
    catalog_metadata.py::apply_writable_fields), and they are exactly the ones
    `total` misreads worst: an addon-shaped script emits ~1 event per run
    while a full LXC install emits ~7.5, so ranking by `total` demotes them by
    a factor that has nothing to do with how often anyone runs them.

    The fixture encodes that mechanism rather than a captured leaderboard: the
    five genuinely outrank the noisy app on terminal events and are all beaten
    by it on `total`. A run that read `total` would invert every one of them.
    """
    five = ["coolify", "runtipi", "dockge", "komodo", "dokploy"]
    db = make_db(tmp_path)
    for slug in five:
        _seed(db, slug)
    _seed(db, "chatty")
    monkeypatch.setattr(ct, "_fetch", fake_telemetry(rows=[
        # ~1 event per run: terminal count IS very close to total.
        *[_row(s, success=5000, failed=100, aborted=50, total=5200)
          for s in five],
        # ~7.5 events per run: a far less popular app that dwarfs them on the
        # raw event count, which is precisely the trap.
        _row("chatty", success=900, failed=50, aborted=50, total=30000),
    ]))

    ct.sync_popularity(db)

    ranked = [r.slug for r in db.query(CatalogEntry)
              .order_by(CatalogEntry.popularity.desc()).all()]
    assert ranked[-1] == "chatty", ranked
    for slug in five:
        row = db.query(CatalogEntry).filter_by(slug=slug).one()
        assert row.popularity == 5150, slug
        assert row.popularity > 1000, slug   # chatty's terminal count
    # ...and by `total` the order would have been exactly the other way round.
    assert 30000 > 5200


def test_the_join_is_the_app_field_against_our_slug_with_no_normalisation(tmp_path, monkeypatch):
    """Exact match, no case folding, no fuzzy matching. Verified upstream:
    case-insensitive matching buys 0 extra matches, and a normaliser would be
    the same foot-gun catalog_metadata.py warns about on its own slug join."""
    db = make_db(tmp_path)
    _seed(db, "pocket-id")
    monkeypatch.setattr(ct, "_fetch", fake_telemetry(rows=[
        _row("Pocket-ID", success=99), _row("pocket-id", success=42)]))

    ct.sync_popularity(db)

    assert db.query(CatalogEntry).filter_by(slug="pocket-id").one().popularity == 42


def test_a_telemetry_slug_with_no_catalog_row_creates_nothing(tmp_path, monkeypatch):
    """Same rule as the metadata sync: the scripts tree decides what exists.
    The response carries 1545 rows against our 669, most of them things we
    never discovered."""
    db = make_db(tmp_path)
    _seed(db, "redis")
    monkeypatch.setattr(ct, "_fetch", fake_telemetry(rows=[
        _row("redis", success=10), _row("never-discovered", success=9999)]))

    out = ct.sync_popularity(db)

    assert out["matched"] == 1 and out["telemetry_only"] == 1
    assert db.query(CatalogEntry).count() == 1


# --- the write set is one column -------------------------------------------

UNTOUCHED = ("slug", "name", "description", "category", "entry_type",
             "script_path", "website", "docs_url", "icon_url", "installable",
             "unsupported_reason", "upstream_state", "metadata_source",
             "metadata_synced_at", "upstream_updated_at", "upstream_sha",
             "default_cpu", "default_ram_mb", "default_disk_gb", "default_os",
             "default_os_version", "deprecated", "synced_at", "raw")


def test_a_sync_changes_popularity_and_its_stamp_and_nothing_else(tmp_path, monkeypatch):
    """Popularity measures how often people RUN a script. It is not evidence
    about what the script IS, so it may never reach entry_type, installable or
    upstream_state, and it is not presentation either, so it may never reach
    name or description. The fixture hands it fields for all of those on
    purpose."""
    db = make_db(tmp_path)
    _seed(db, "redis", name="Redis", description="An in-memory data store.",
          category="Databases", script_path="ct/redis.sh", installable=True,
          upstream_state="listed", metadata_source="pocketbase",
          default_cpu=1, default_ram_mb=1024, raw={"metadata": {"slug": "redis"}})
    before = {f: getattr(db.query(CatalogEntry).filter_by(slug="redis").one(), f)
              for f in UNTOUCHED}
    monkeypatch.setattr(ct, "_fetch", fake_telemetry(rows=[
        _row("redis", success=10, failed=1, aborted=1, name="NOT THE NAME",
             entry_type="addon", installable=False, upstream_state="unlisted",
             description="not the description")]))

    ct.sync_popularity(db)

    row = db.query(CatalogEntry).filter_by(slug="redis").one()
    assert {f: getattr(row, f) for f in UNTOUCHED} == before
    assert row.popularity == 12 and row.popularity_synced_at is not None


def test_apply_popularity_writes_one_column_by_name(tmp_path):
    """The structural half of the guarantee: the write path is a single
    assignment to POPULARITY_FIELD, so it cannot grow into a second metadata
    path without someone deliberately adding a line to it."""
    db = make_db(tmp_path)
    row = _seed(db, "redis", name="Redis", installable=True)

    ct.apply_popularity(row, 41)

    assert ct.POPULARITY_FIELD == "popularity"
    assert row.popularity == 41
    assert row.name == "Redis" and row.installable is True
    # The stamp is provenance, written by the sync, not by the write path.
    assert row.popularity_synced_at is None


# --- failure writes nothing at all ------------------------------------------

def _warm(db, monkeypatch):
    """A catalog with a real previous reading, which is the only state in
    which a bad write is actually destructive."""
    _seed(db, "redis")
    _seed(db, "grafana")
    monkeypatch.setattr(ct, "_fetch", fake_telemetry(rows=[
        _row("redis", success=1000), _row("grafana", success=500)]))
    assert ct.sync_popularity(db)["ok"]
    return {r.slug: (r.popularity, r.popularity_synced_at)
            for r in db.query(CatalogEntry).all()}


def test_a_non_200_writes_nothing_and_keeps_every_previous_count(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    before = _warm(db, monkeypatch)
    monkeypatch.setattr(ct, "_fetch", fake_telemetry(status=503))

    out = ct.sync_popularity(db)

    assert out["ok"] is False and out["matched"] == 0
    assert "telemetry unavailable" in out["reason"] and "503" in out["reason"]
    db.expire_all()
    assert {r.slug: (r.popularity, r.popularity_synced_at)
            for r in db.query(CatalogEntry).all()} == before


def test_a_200_that_is_not_json_writes_nothing(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    before = _warm(db, monkeypatch)
    monkeypatch.setattr(ct, "_fetch", fake_telemetry(malformed=True))

    out = ct.sync_popularity(db)

    assert out["ok"] is False
    db.expire_all()
    assert {r.slug: (r.popularity, r.popularity_synced_at)
            for r in db.query(CatalogEntry).all()} == before


def test_an_empty_or_missing_top_scripts_writes_nothing(tmp_path, monkeypatch):
    """THE GUARD. Popularity is applied by PRESENCE in the payload, so an
    empty corpus read as authoritative is indistinguishable from "nobody has
    installed anything" and would blank the signal on every card in the Store
    off one upstream outage."""
    db = make_db(tmp_path)
    before = _warm(db, monkeypatch)

    for body in ({"top_scripts": []}, {"total_scripts": 0}, {}):
        monkeypatch.setattr(ct, "_fetch", fake_telemetry(body=body))

        out = ct.sync_popularity(db)

        assert out["ok"] is False, body
        assert "no top_scripts" in out["reason"], body
        db.expire_all()
        assert {r.slug: (r.popularity, r.popularity_synced_at)
                for r in db.query(CatalogEntry).all()} == before, body


def test_a_response_of_rows_we_cannot_read_writes_nothing(tmp_path, monkeypatch):
    """A non-empty list that yields no usable count is the same non-event as
    an empty one, and must not be mistaken for a corpus."""
    db = make_db(tmp_path)
    before = _warm(db, monkeypatch)
    monkeypatch.setattr(ct, "_fetch", fake_telemetry(
        rows=[{"app": "redis", "total": 900}, {"nope": True}, "not a dict"]))

    out = ct.sync_popularity(db)

    assert out["ok"] is False and "no usable rows" in out["reason"]
    db.expire_all()
    assert {r.slug: (r.popularity, r.popularity_synced_at)
            for r in db.query(CatalogEntry).all()} == before


def test_an_app_absent_from_the_response_keeps_its_count_and_is_never_zeroed(tmp_path, monkeypatch):
    """Absence is NO NEW INFORMATION, not a zero. Telemetry is strictly
    opt-in upstream (gated on DIAGNOSTICS in
    /usr/local/community-scripts/diagnostics), so an app missing from one
    response is silence, never evidence that nobody runs it."""
    db = make_db(tmp_path)
    before = _warm(db, monkeypatch)
    # A perfectly successful sync, in which grafana simply is not mentioned.
    monkeypatch.setattr(ct, "_fetch", fake_telemetry(rows=[
        _row("redis", success=1200)]))

    out = ct.sync_popularity(db)

    assert out["ok"] and out["matched"] == 1 and out["unmatched"] == 1
    grafana = db.query(CatalogEntry).filter_by(slug="grafana").one()
    assert grafana.popularity == before["grafana"][0] == 500
    assert grafana.popularity_synced_at == before["grafana"][1]
    assert db.query(CatalogEntry).filter_by(slug="redis").one().popularity == 1200


def test_a_row_that_never_had_a_count_stays_none_rather_than_zero(tmp_path, monkeypatch):
    """The other end of the same rule: never-measured is not zero installs."""
    db = make_db(tmp_path)
    _seed(db, "redis")
    _seed(db, "obscure")
    monkeypatch.setattr(ct, "_fetch", fake_telemetry(rows=[_row("redis", success=5)]))

    ct.sync_popularity(db)

    row = db.query(CatalogEntry).filter_by(slug="obscure").one()
    assert row.popularity is None and row.popularity_synced_at is None


def test_there_is_no_fallback_source_and_one_request_per_sync(tmp_path, monkeypatch):
    """No cold-start fallback by design: there is no second telemetry source,
    and a Store with no popularity is a fine Store. Also proves the module
    never loops per slug over someone else's service."""
    db = make_db(tmp_path)
    _seed(db, "redis")
    seen: list[str] = []
    monkeypatch.setattr(ct, "_fetch", fake_telemetry(status=503, seen=seen))

    assert ct.sync_popularity(db)["ok"] is False

    assert len(seen) == 1

    seen.clear()
    monkeypatch.setattr(ct, "_fetch",
                        fake_telemetry(rows=[_row("redis", success=5)], seen=seen))
    ct.sync_popularity(db)
    assert len(seen) == 1


def test_a_sync_never_touches_api_github_com(tmp_path, monkeypatch):
    """The refresh's 2-call GitHub API ceiling is absolute. Telemetry is a
    third host, distinct from api.github.com and db.community-scripts.org."""
    db = make_db(tmp_path)
    _seed(db, "redis")
    seen: list[str] = []
    monkeypatch.setattr(ct, "_fetch",
                        fake_telemetry(rows=[_row("redis", success=5)], seen=seen))

    ct.sync_popularity(db)

    assert seen and not any("api.github.com" in u for u in seen)
    assert all(u.startswith("https://telemetry.community-scripts.org") for u in seen)
