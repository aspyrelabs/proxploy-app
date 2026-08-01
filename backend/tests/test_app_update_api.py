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


def test_get_update_on_an_edited_app_reports_no_update_and_says_so(client, csrf_header,
                                                                   bootstrap_admin):
    """Review finding: put_app_script leaves `upstream_ref` NULL on an edited
    row, which used to make GET's `from_ref != to_ref` diff guard trivially
    true and advertise a diff/update that POST would then refuse. An edited
    newest script must report no update at all, plus WHY via script_source."""
    bootstrap_admin(client)
    app_id = _seed(client)
    client.put(f"/api/v1/apps/{app_id}/script", json={"content": "edited by hand\n"},
              headers=csrf_header(client))
    body = client.get(f"/api/v1/apps/{app_id}/update").json()
    assert body["script_source"] == "edited"
    assert body["update_available"] is None
    assert body["from_ref"] is None
    assert body["diff_vs_upstream"] is None


def test_post_update_on_an_edited_app_names_revert_not_refresh_the_catalog(client,
                                                                          csrf_header,
                                                                          bootstrap_admin):
    """Distinct 409 from the "nothing pinned" case: refreshing the catalog
    does nothing for an edited app, so the message must not say that, and must
    point at the real remedy (POST .../script/revert) built in this task."""
    bootstrap_admin(client)
    app_id = _seed(client)
    h = csrf_header(client)
    client.put(f"/api/v1/apps/{app_id}/script", json={"content": "edited by hand\n"},
              headers=h)
    r = client.post(f"/api/v1/apps/{app_id}/update", json={"consent": True}, headers=h)
    assert r.status_code == 409
    text = r.text.lower()
    assert "script/revert" in text
    assert "refresh the catalog" not in text


def test_revert_clears_a_stale_update_available(client, csrf_header, bootstrap_admin):
    """Review finding: revert pins to the catalog's CURRENT sha, so by
    definition nothing is pending afterwards — GET must not go on reporting
    both "up to date" (from_ref == to_ref) and a stale update_available."""
    bootstrap_admin(client)
    app_id = _seed(client)  # pinned="a"*40, upstream="b"*40 -> update pending
    before = client.get(f"/api/v1/apps/{app_id}/update").json()
    assert before["update_available"] == "b" * 7

    r = client.post(f"/api/v1/apps/{app_id}/script/revert", headers=csrf_header(client))
    assert r.status_code == 200, r.text

    after = client.get(f"/api/v1/apps/{app_id}/update").json()
    assert after["update_available"] is None
    assert after["from_ref"] == after["to_ref"] == "b" * 40


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
