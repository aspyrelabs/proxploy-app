"""POST /apps/update-all (doc 05 §Apps, doc 06 cluster "Update all")."""
from fastapi.testclient import TestClient

from proxploy.models import App, AppScript, AuditEvent, CatalogEntry, Job
from tests.support import make_app, seed_host_row


def _seed_app(db, host, slug, ctid, pinned, upstream):
    if db.query(CatalogEntry).filter_by(slug=slug).one_or_none() is None:
        db.add(CatalogEntry(slug=slug, name=slug, script_path=f"ct/{slug}.sh",
                            upstream_sha=upstream, installable=True,
                            raw={"install_script": "#!/bin/bash\n"}))
    a = App(host_id=host.id, ctid=ctid, name=slug, slug=f"{slug}-{host.id}-{ctid}",
            catalog_slug=slug, web_protocol="http", web_path="/", adopted=True,
            update_available=upstream[:7] if pinned != upstream else None)
    db.add(a)
    db.flush()
    db.add(AppScript(app_id=a.id, version=1, content="x", content_sha256="0" * 64,
                     source="upstream", upstream_ref=pinned))
    db.commit()
    return a.id


def _seed(c):
    with c.app.state.sessionmaker() as db:
        host = seed_host_row(db)
        stale = _seed_app(db, host, "redis", 101, "a" * 40, "b" * 40)
        current = _seed_app(db, host, "gitea", 102, "c" * 40, "c" * 40)
        # adopted, no catalog slug and no script row
        orphan = App(host_id=host.id, ctid=103, name="custom",
                     slug="custom-1-103", catalog_slug=None, web_protocol="http",
                     web_path="/", adopted=True)
        db.add(orphan)
        db.commit()
        return stale, current, orphan.id


def test_update_all_enqueues_only_the_stale_apps(client, csrf_header,
                                                 bootstrap_admin):
    bootstrap_admin(client)
    stale, current, orphan = _seed(client)
    h = csrf_header(client)
    r = client.post("/api/v1/apps/update-all", json={"consent": True}, headers=h)
    assert r.status_code == 202, r.text
    body = r.json()
    assert [j["target_id"] for j in body["jobs"]] == [stale]
    assert all(j["kind"] == "app.update" for j in body["jobs"])
    with client.app.state.sessionmaker() as db:
        assert db.query(Job).count() == 1


def test_update_all_reports_why_each_app_was_skipped(client, csrf_header,
                                                     bootstrap_admin):
    """A silent "0 updated" is indistinguishable from a broken endpoint."""
    bootstrap_admin(client)
    stale, current, orphan = _seed(client)
    h = csrf_header(client)
    body = client.post("/api/v1/apps/update-all", json={"consent": True},
                       headers=h).json()
    skipped = {s["app_id"]: s["reason"] for s in body["skipped"]}
    assert set(skipped) == {current, orphan}
    assert "up to date" in skipped[current]
    assert "catalog" in skipped[orphan]


def test_update_all_requires_consent(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    _seed(client)
    h = csrf_header(client)
    r = client.post("/api/v1/apps/update-all", json={"consent": False}, headers=h)
    assert r.status_code == 400
    with client.app.state.sessionmaker() as db:
        assert db.query(Job).count() == 0


def test_update_all_writes_one_audit_row_per_job(client, csrf_header,
                                                 bootstrap_admin):
    bootstrap_admin(client)
    stale, _, _ = _seed(client)
    h = csrf_header(client)
    client.post("/api/v1/apps/update-all", json={"consent": True}, headers=h)
    with client.app.state.sessionmaker() as db:
        rows = db.query(AuditEvent).filter_by(action="app.update").all()
        assert len(rows) == 1
        assert rows[0].target_id == stale
        assert rows[0].job_id is not None


def test_update_all_with_nothing_stale_is_an_empty_202_not_an_error(
        client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    h = csrf_header(client)
    r = client.post("/api/v1/apps/update-all", json={"consent": True}, headers=h)
    assert r.status_code == 202
    assert r.json() == {"jobs": [], "skipped": []}


def test_update_all_is_not_matched_as_an_app_id(client, csrf_header,
                                                bootstrap_admin):
    """`/apps/{app_id}` would parse "update-all" as an id if ordering
    regressed, FastAPI would 422 on the int coercion."""
    bootstrap_admin(client)
    h = csrf_header(client)
    assert client.post("/api/v1/apps/update-all", json={"consent": True},
                       headers=h).status_code == 202


def test_update_all_skips_an_edited_app_and_enqueues_no_job(client, csrf_header,
                                                            bootstrap_admin):
    """Task 5's _resolve_update refuses to re-run upstream over local edits
    (JobFailed). If update-all enqueued a job for an edited app anyway, that
    job would be guaranteed to fail, this proves it's skipped instead, with
    the same remedy POST /{app_id}/update's 409 names (script/revert, not
    "refresh the catalog").

    Also proves the skip ORDER: an edited row's upstream_ref is NULL, same as
    an app with no pinned script at all, so the edited check must run before
    the "no pinned script" bucket or this app would land there with a
    misleading "refresh the catalog" reason instead.
    """
    bootstrap_admin(client)
    stale, current, orphan = _seed(client)
    h = csrf_header(client)
    client.put(f"/api/v1/apps/{stale}/script", json={"content": "edited by hand\n"},
              headers=h)
    r = client.post("/api/v1/apps/update-all", json={"consent": True}, headers=h)
    assert r.status_code == 202, r.text
    body = r.json()
    assert [j["target_id"] for j in body["jobs"]] == []
    skipped = {s["app_id"]: s["reason"] for s in body["skipped"]}
    assert set(skipped) == {stale, current, orphan}
    assert "script/revert" in skipped[stale]
    assert "refresh the catalog" not in skipped[stale]
    with client.app.state.sessionmaker() as db:
        assert db.query(Job).count() == 0


def test_store_update_all_entitlement_gates_it(tmp_path, csrf_header,
                                               bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _seed(c)
        h = csrf_header(c)
        c.app.state.entitlements._features = {"store.update": True,
                                              "store.update_all": False}
        r = c.post("/api/v1/apps/update-all", json={"consent": True}, headers=h)
        assert r.status_code == 403
        assert r.json()["feature"] == "store.update_all"
