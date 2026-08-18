"""Audit export, API and CLI (PXP-17).

docs 04 and 05 both describe an export and doc 04 names a
`proxploy audit export` CLI. Neither existed.
"""
import csv
import io
import json


def _app_with_events(tmp_path, csrf_header, bootstrap_admin):
    from fastapi.testclient import TestClient
    from tests.support import make_app

    app = make_app(tmp_path)
    c = TestClient(app)
    c.__enter__()
    bootstrap_admin(c)
    # Two distinct actions so a filter has something to exclude.
    from proxploy.services.audit import write_audit
    with app.state.sessionmaker() as db:
        write_audit(db, actor_type="user", actor_id=1, action="app.uninstall",
                    target_type="app", target_id=7, params={"ctid": 150})
        write_audit(db, actor_type="user", actor_id=1, action="host.remove",
                    target_type="host", target_id=3, params={"name": "host-01"})
    return app, c


def test_csv_export_has_a_header_and_json_encoded_params(tmp_path, csrf_header,
                                                         bootstrap_admin):
    app, c = _app_with_events(tmp_path, csrf_header, bootstrap_admin)
    with c:
        r = c.get("/api/v1/audit/export")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        assert "attachment" in r.headers["content-disposition"]
        rows = list(csv.DictReader(io.StringIO(r.text)))
        assert {row["action"] for row in rows} >= {"app.uninstall", "host.remove"}
        # A bare str(dict) would be Python repr with single quotes, which is
        # not JSON and not reliably re-parseable by whoever gets the file.
        row = next(r for r in rows if r["action"] == "app.uninstall")
        assert json.loads(row["params"]) == {"ctid": 150}


def test_jsonl_export_is_one_object_per_line(tmp_path, csrf_header, bootstrap_admin):
    app, c = _app_with_events(tmp_path, csrf_header, bootstrap_admin)
    with c:
        r = c.get("/api/v1/audit/export", params={"format": "jsonl"})
        assert r.status_code == 200
        lines = [json.loads(x) for x in r.text.strip().split("\n")]
        assert len(lines) >= 2
        assert all("action" in x and "ts" in x for x in lines)


def test_export_honours_the_same_filters_as_the_viewer(tmp_path, csrf_header,
                                                       bootstrap_admin):
    """An export that answers a different question than the list above it is
    worse than no export."""
    app, c = _app_with_events(tmp_path, csrf_header, bootstrap_admin)
    with c:
        listed = c.get("/api/v1/audit", params={"action": "host.remove"}).json()
        exported = list(csv.DictReader(io.StringIO(
            c.get("/api/v1/audit/export",
                  params={"action": "host.remove"}).text)))
        assert len(exported) == len(listed) == 1
        assert exported[0]["action"] == "host.remove"


def test_export_honours_the_item_or_action_search_too(tmp_path, csrf_header,
                                                     bootstrap_admin):
    """Every filter the table shows has to reach the export, or the file
    answers a different question than the screen did."""
    app, c = _app_with_events(tmp_path, csrf_header, bootstrap_admin)
    with c:
        listed = c.get("/api/v1/audit", params={"search": "uninstall"}).json()
        exported = list(csv.DictReader(io.StringIO(
            c.get("/api/v1/audit/export", params={"search": "uninstall"}).text)))
        assert len(exported) == len(listed) == 1
        assert exported[0]["action"] == "app.uninstall"


def test_export_columns_are_not_touched_by_the_screens_labels(tmp_path, csrf_header,
                                                              bootstrap_admin):
    """EXPORT_COLUMNS is a machine-readable contract. The Date/User/Action/Item
    renaming was about the screen, and the human labels the screen needs are
    added to the LIST payload only: a JSONL line gaining two keys would change
    a file someone else already parses."""
    from proxploy.api.audit import EXPORT_COLUMNS

    app, c = _app_with_events(tmp_path, csrf_header, bootstrap_admin)
    with c:
        reader = csv.DictReader(io.StringIO(c.get("/api/v1/audit/export").text))
        assert tuple(reader.fieldnames) == EXPORT_COLUMNS
        line = json.loads(c.get("/api/v1/audit/export",
                                params={"format": "jsonl"}).text.strip().split("\n")[0])
        assert set(line) == set(EXPORT_COLUMNS)


def test_export_is_not_paginated(tmp_path, csrf_header, bootstrap_admin):
    """An export that stops at page one is a trap."""
    from fastapi.testclient import TestClient
    from proxploy.services.audit import write_audit
    from tests.support import make_app

    app = make_app(tmp_path)
    c = TestClient(app)
    with c:
        bootstrap_admin(c)
        with app.state.sessionmaker() as db:
            for i in range(120):   # more than the list route's per_page of 50
                write_audit(db, actor_type="user", actor_id=1,
                            action="app.start", target_type="app", target_id=i)
        rows = list(csv.DictReader(io.StringIO(
            c.get("/api/v1/audit/export", params={"action": "app.start"}).text)))
        assert len(rows) == 120


def test_a_bad_format_is_422(tmp_path, csrf_header, bootstrap_admin):
    app, c = _app_with_events(tmp_path, csrf_header, bootstrap_admin)
    with c:
        assert c.get("/api/v1/audit/export",
                     params={"format": "xlsx"}).status_code == 422


def test_export_needs_a_session(tmp_path, csrf_header, bootstrap_admin):
    from fastapi.testclient import TestClient
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        assert c.get("/api/v1/audit/export").status_code == 401


# --- the CLI --------------------------------------------------------------

def test_cli_exports_without_a_web_session(tmp_path, monkeypatch, capsys):
    """The whole point of the CLI: recover the trail when nobody can log in."""
    from proxploy.config import Settings, get_settings
    from proxploy.db import make_engine, make_sessionmaker, run_migrations
    from proxploy.services.audit import write_audit

    s = Settings(db_url=f"sqlite:///{tmp_path}/cli.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key")
    run_migrations(s)
    with make_sessionmaker(make_engine(s))() as db:
        write_audit(db, actor_type="user", actor_id=1, action="user.delete",
                    target_type="user", target_id=9, params={"email": "x@y.z"})

    monkeypatch.setenv("PROXPLOY_DB_URL", s.db_url)
    monkeypatch.setenv("PROXPLOY_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        from proxploy.cli import main
        assert main(["audit", "export", "--format", "jsonl"]) == 0
        out = capsys.readouterr().out
        rows = [json.loads(x) for x in out.strip().split("\n")]
        assert rows[0]["action"] == "user.delete"
        assert rows[0]["params"] == {"email": "x@y.z"}
    finally:
        get_settings.cache_clear()


def test_cli_writes_a_file_and_filters(tmp_path, monkeypatch):
    from proxploy.config import Settings, get_settings
    from proxploy.db import make_engine, make_sessionmaker, run_migrations
    from proxploy.services.audit import write_audit

    s = Settings(db_url=f"sqlite:///{tmp_path}/cli2.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key")
    run_migrations(s)
    with make_sessionmaker(make_engine(s))() as db:
        write_audit(db, actor_type="user", actor_id=1, action="app.start",
                    target_type="app", target_id=1)
        write_audit(db, actor_type="user", actor_id=1, action="app.stop",
                    target_type="app", target_id=1)

    monkeypatch.setenv("PROXPLOY_DB_URL", s.db_url)
    monkeypatch.setenv("PROXPLOY_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        from proxploy.cli import main
        dest = tmp_path / "audit.csv"
        assert main(["audit", "export", "--out", str(dest),
                     "--action", "app.stop"]) == 0
        rows = list(csv.DictReader(dest.open()))
        assert [r["action"] for r in rows] == ["app.stop"]
    finally:
        get_settings.cache_clear()


def test_cli_rejects_a_bad_timestamp_instead_of_silently_ignoring_it(tmp_path,
                                                                     monkeypatch):
    """A filter that is silently dropped produces an export that looks right
    and covers the wrong window."""
    import pytest

    from proxploy.config import get_settings
    monkeypatch.setenv("PROXPLOY_DB_URL", f"sqlite:///{tmp_path}/cli3.db")
    get_settings.cache_clear()
    try:
        from proxploy.cli import main
        with pytest.raises(SystemExit):
            main(["audit", "export", "--since", "last-tuesday"])
    finally:
        get_settings.cache_clear()
