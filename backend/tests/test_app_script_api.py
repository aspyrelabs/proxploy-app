from proxploy.models import App, AppScript
from tests.support import seed_host_row


def _seed_app_with_script(db, content="msg_ok done\n"):
    host = seed_host_row(db)
    app = App(host_id=host.id, ctid=150, name="Redis", slug="redis-1",
              catalog_slug="redis", web_protocol="http", web_path="/", adopted=True)
    db.add(app)
    db.flush()
    import hashlib
    db.add(AppScript(app_id=app.id, version=1, content=content,
                     content_sha256=hashlib.sha256(content.encode()).hexdigest(),
                     source="upstream", upstream_ref="abc123"))
    db.commit()
    return app


def test_get_script_returns_latest_version(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        app = _seed_app_with_script(db)
        app_id = app.id

    r = client.get(f"/api/v1/apps/{app_id}/script")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == 1 and body["content"] == "msg_ok done\n"


def test_put_script_creates_a_new_version(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        app = _seed_app_with_script(db)
        app_id = app.id

    r = client.put(f"/api/v1/apps/{app_id}/script", json={"content": "msg_ok edited\n"},
                   headers=csrf_header(client))
    assert r.status_code == 200
    assert r.json()["version"] == 2

    r = client.get(f"/api/v1/apps/{app_id}/script/versions")
    assert [v["version"] for v in r.json()] == [2, 1]


def test_edited_script_shows_source_edited(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        app = _seed_app_with_script(db)
        app_id = app.id
    client.put(f"/api/v1/apps/{app_id}/script", json={"content": "msg_ok edited\n"},
              headers=csrf_header(client))
    r = client.get(f"/api/v1/apps/{app_id}/script")
    assert r.json()["source"] == "edited"


def test_script_matching_current_upstream_has_no_diff(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        app = _seed_app_with_script(db, content="msg_ok done\n")
        from proxploy.models import CatalogEntry
        db.add(CatalogEntry(slug="redis", name="Redis", installable=True,
                            raw={"install_script": "msg_ok done\n"}))
        db.commit()
        app_id = app.id

    r = client.get(f"/api/v1/apps/{app_id}/script")
    assert r.json()["diff_vs_upstream"] is None


def test_edited_script_shows_a_real_diff_against_current_upstream(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        app = _seed_app_with_script(db, content="msg_ok done\n")
        from proxploy.models import CatalogEntry
        db.add(CatalogEntry(slug="redis", name="Redis", installable=True,
                            raw={"install_script": "msg_ok done\n"}))
        db.commit()
        app_id = app.id

    client.put(f"/api/v1/apps/{app_id}/script", json={"content": "msg_ok edited\n"},
              headers=csrf_header(client))
    r = client.get(f"/api/v1/apps/{app_id}/script")
    diff = r.json()["diff_vs_upstream"]
    assert diff is not None
    assert "-msg_ok done" in diff and "+msg_ok edited" in diff


def test_upstream_moving_on_after_pin_also_surfaces_a_diff(client, csrf_header, bootstrap_admin):
    """Not just locally-edited scripts drift from upstream — a catalog refresh
    that picks up a new upstream version must surface that too, even though
    this app's own pinned content never changed (doc 10 DoD: "diffed against
    upstream before every run", not just "diffed against local edits")."""
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        app = _seed_app_with_script(db, content="msg_ok done\n")
        from proxploy.models import CatalogEntry
        db.add(CatalogEntry(slug="redis", name="Redis", installable=True,
                            raw={"install_script": "msg_ok done v2\n"}))
        db.commit()
        app_id = app.id

    r = client.get(f"/api/v1/apps/{app_id}/script")
    diff = r.json()["diff_vs_upstream"]
    # _diff_vs_upstream diffs FROM upstream TO pinned (fromfile=upstream,
    # tofile=pinned) — the same fixed order the sibling
    # test_edited_script_shows_a_real_diff_against_current_upstream relies on
    # ("-msg_ok done"/"+msg_ok edited"). That order is a structural constant:
    # content unique to upstream always renders "-", never "+", regardless of
    # which scenario produced it. Here upstream moved to v2 while pinned
    # stayed put, so v2 (upstream-only) is the "-" side; the important
    # assertion is that a diff exists at all despite no local edit.
    assert diff is not None and "-msg_ok done v2" in diff
