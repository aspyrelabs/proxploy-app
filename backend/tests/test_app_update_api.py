"""GET/POST /apps/{id}/update (doc 05 §Apps)."""
from fastapi.testclient import TestClient

from proxploy.models import App, AppScript, AuditEvent, CatalogEntry, Job
from tests.support import make_app, seed_host_row


def _seed(c, *, pinned="a" * 40, upstream="b" * 40, slug="redis", ctid=101):
    with c.app.state.sessionmaker() as db:
        host = seed_host_row(db)
        db.add(CatalogEntry(slug=slug, name="Redis", script_path=f"ct/{slug}.sh",
                            upstream_sha=upstream, installable=True,
                            raw={"install_script": "#!/bin/bash\nNEW\n"}))
        a = App(host_id=host.id, ctid=ctid, name="Redis",
                slug=f"{slug}-{host.id}-{ctid}", catalog_slug=slug,
                web_protocol="http", web_path="/", adopted=True,
                update_available=upstream[:7] if pinned != upstream else None)
        db.add(a)
        db.flush()
        db.add(AppScript(app_id=a.id, version=1, content="#!/bin/bash\nOLD\n",
                         content_sha256="0" * 64, source="upstream",
                         upstream_ref=pinned))
        db.commit()
        return a.id


def test_get_update_reports_the_two_commits_and_the_diff(client, csrf_header,
                                                         bootstrap_admin):
    bootstrap_admin(client)
    app_id = _seed(client)
    r = client.get(f"/api/v1/apps/{app_id}/update")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["update_available"] == "b" * 7
    assert body["from_ref"] == "a" * 40
    assert body["to_ref"] == "b" * 40
    assert "OLD" in body["diff_vs_upstream"] and "NEW" in body["diff_vs_upstream"]


def test_get_update_on_a_current_app_reports_no_update(client, csrf_header,
                                                       bootstrap_admin):
    bootstrap_admin(client)
    app_id = _seed(client, pinned="a" * 40, upstream="a" * 40)
    body = client.get(f"/api/v1/apps/{app_id}/update").json()
    assert body["update_available"] is None
    assert body["to_ref"] == "a" * 40
    assert body["diff_vs_upstream"] is None


def test_get_update_404s_an_unknown_app(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    assert client.get("/api/v1/apps/9999/update").status_code == 404


def test_post_update_requires_explicit_consent(client, csrf_header, bootstrap_admin):
    """Same root-consent gate as install (api/catalog.py) — this runs a
    community script as root on the node."""
    bootstrap_admin(client)
    app_id = _seed(client)
    h = csrf_header(client)
    r = client.post(f"/api/v1/apps/{app_id}/update", json={"consent": False},
                    headers=h)
    assert r.status_code == 400
    assert "consent" in r.text.lower()
    with client.app.state.sessionmaker() as db:
        assert db.query(Job).count() == 0


def test_post_update_enqueues_and_audits(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    app_id = _seed(client)
    h = csrf_header(client)
    r = client.post(f"/api/v1/apps/{app_id}/update", json={"consent": True},
                    headers=h)
    assert r.status_code == 202, r.text
    job = r.json()["job"]
    assert job["kind"] == "app.update"
    assert job["target_type"] == "app" and job["target_id"] == app_id
    with client.app.state.sessionmaker() as db:
        assert db.query(AuditEvent).filter_by(
            action="app.update", target_id=app_id).count() == 1


def test_post_update_refuses_when_there_is_nothing_to_update(client, csrf_header,
                                                             bootstrap_admin):
    """Rejected at the route, not four minutes later inside the job."""
    bootstrap_admin(client)
    app_id = _seed(client, pinned="a" * 40, upstream="a" * 40)
    h = csrf_header(client)
    r = client.post(f"/api/v1/apps/{app_id}/update", json={"consent": True},
                    headers=h)
    assert r.status_code == 409
    assert "up to date" in r.text.lower()


def test_post_update_404s_an_unknown_app(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    h = csrf_header(client)
    assert client.post("/api/v1/apps/9999/update", json={"consent": True},
                       headers=h).status_code == 404


def test_update_routes_are_not_swallowed_by_the_lifecycle_wildcard(client,
                                                                   csrf_header,
                                                                   bootstrap_admin):
    """`POST /{app_id}/{action}` is registered later and would match
    `/{id}/update` as action="update" if ordering ever regressed."""
    bootstrap_admin(client)
    app_id = _seed(client)
    h = csrf_header(client)
    r = client.post(f"/api/v1/apps/{app_id}/update", json={"consent": True},
                    headers=h)
    assert r.json()["job"]["kind"] == "app.update"     # not "app.update" via lifecycle
    assert r.status_code == 202


def test_store_update_entitlement_gates_the_post(tmp_path, csrf_header,
                                                 bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        app_id = _seed(c)
        h = csrf_header(c)
        c.app.state.entitlements._features = {"store.updates": True,
                                              "store.update": False}
        r = c.post(f"/api/v1/apps/{app_id}/update", json={"consent": True},
                   headers=h)
        assert r.status_code == 403
        assert r.json()["feature"] == "store.update"
