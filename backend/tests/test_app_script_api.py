from fastapi.testclient import TestClient

from proxploy.models import App, AppScript
from tests.support import make_app, seed_host_row


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
    """Not just locally-edited scripts drift from upstream, a catalog refresh
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
    # tofile=pinned): the same fixed order the sibling
    # test_edited_script_shows_a_real_diff_against_current_upstream relies on
    # ("-msg_ok done"/"+msg_ok edited"). That order is a structural constant:
    # content unique to upstream always renders "-", never "+", regardless of
    # which scenario produced it. Here upstream moved to v2 while pinned
    # stayed put, so v2 (upstream-only) is the "-" side; the important
    # assertion is that a diff exists at all despite no local edit.
    assert diff is not None and "-msg_ok done v2" in diff


# --- I4: ordinary bad input must not surface as a raw 500 ---


def test_put_script_without_content_is_a_422_not_a_500(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        app_id = _seed_app_with_script(db).id

    r = client.put(f"/api/v1/apps/{app_id}/script", json={},
                   headers=csrf_header(client))
    assert r.status_code == 422


def test_put_script_for_an_unknown_app_is_a_404_not_a_500(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    r = client.put("/api/v1/apps/9999/script", json={"content": "x\n"},
                   headers=csrf_header(client))
    assert r.status_code == 404


# --- POST /{app_id}/script/revert (Task 6 mandatory addition) --------------
#
# Task 5's review found a dead end: put_app_script above always writes
# source="edited", and nothing else ever writes source="upstream" except the
# install/update job handlers: so once a script is edited, services/
# appstore.py::_resolve_update's edited-script guard blocks app.update
# FOREVER. This route is the way back.


def test_revert_pins_a_new_upstream_version_and_keeps_history(client, csrf_header,
                                                               bootstrap_admin):
    bootstrap_admin(client)
    from proxploy.models import CatalogEntry
    with client.app.state.sessionmaker() as db:
        app = _seed_app_with_script(db, content="msg_ok done\n")
        db.add(CatalogEntry(slug="redis", name="Redis", installable=True,
                            upstream_sha="c" * 40,
                            raw={"install_script": "msg_ok upstream v2\n"}))
        db.commit()
        app_id = app.id

    client.put(f"/api/v1/apps/{app_id}/script", json={"content": "msg_ok edited\n"},
              headers=csrf_header(client))
    edited = client.get(f"/api/v1/apps/{app_id}/script").json()
    assert edited["source"] == "edited" and edited["version"] == 2

    rr = client.post(f"/api/v1/apps/{app_id}/script/revert", headers=csrf_header(client))
    assert rr.status_code == 200, rr.text
    body = rr.json()
    assert body["version"] == 3
    assert body["content"] == "msg_ok upstream v2\n"
    assert body["source"] == "upstream"

    versions = client.get(f"/api/v1/apps/{app_id}/script/versions").json()
    assert [v["version"] for v in versions] == [3, 2, 1]
    assert [v["source"] for v in versions] == ["upstream", "edited", "upstream"]

    from proxploy.services.appstore import pinned_ref
    with client.app.state.sessionmaker() as db:
        assert pinned_ref(db, app_id) == "c" * 40


def test_revert_clears_the_edited_guard_that_blocks_app_update(client, csrf_header,
                                                                bootstrap_admin):
    """`_resolve_update` refuses to update an app whose newest script is
    source="edited". After a revert, the newest script is source="upstream"
    again and pinned to the catalog sha, so the guard no longer fires."""
    bootstrap_admin(client)
    from proxploy.models import CatalogEntry
    with client.app.state.sessionmaker() as db:
        app = _seed_app_with_script(db, content="msg_ok done\n")
        db.add(CatalogEntry(slug="redis", name="Redis", installable=True,
                            upstream_sha="c" * 40,
                            raw={"install_script": "msg_ok upstream v2\n"}))
        db.commit()
        app_id = app.id

    client.put(f"/api/v1/apps/{app_id}/script", json={"content": "msg_ok edited\n"},
              headers=csrf_header(client))
    client.post(f"/api/v1/apps/{app_id}/script/revert", headers=csrf_header(client))

    # The revert pins the app to the catalog's CURRENT commit exactly, so
    # _resolve_update now takes the "already up to date" branch rather than
    # the "was edited locally" one: proof the edited-script guard cleared.
    from proxploy.jobs import JobFailed
    from proxploy.services.appstore import _resolve_update
    try:
        _resolve_update(client.app, app_id)
    except JobFailed as e:
        assert "edited locally" not in str(e)
        assert "already on upstream commit" in str(e)
    else:
        raise AssertionError("expected JobFailed: already on upstream commit")


def test_revert_404s_an_unknown_app(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    r = client.post("/api/v1/apps/9999/script/revert", headers=csrf_header(client))
    assert r.status_code == 404


def test_revert_409s_an_adopted_app_with_no_catalog_slug(client, csrf_header,
                                                         bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        host = seed_host_row(db)
        app = App(host_id=host.id, ctid=151, name="Adopted", slug="adopted-1",
                  catalog_slug=None, web_protocol="http", web_path="/", adopted=True)
        db.add(app)
        db.commit()
        app_id = app.id
    r = client.post(f"/api/v1/apps/{app_id}/script/revert", headers=csrf_header(client))
    assert r.status_code == 409
    assert "adopted" in r.text.lower()


def test_revert_409s_when_the_catalog_entry_is_gone(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        app_id = _seed_app_with_script(db).id  # catalog_slug="redis", no CatalogEntry row
    r = client.post(f"/api/v1/apps/{app_id}/script/revert", headers=csrf_header(client))
    assert r.status_code == 409
    assert "catalog entry" in r.text.lower()


def test_revert_409s_when_the_catalog_entry_has_no_upstream_sha(client, csrf_header,
                                                                bootstrap_admin):
    bootstrap_admin(client)
    from proxploy.models import CatalogEntry
    with client.app.state.sessionmaker() as db:
        app_id = _seed_app_with_script(db).id
        db.add(CatalogEntry(slug="redis", name="Redis", installable=True,
                            upstream_sha=None, raw={"install_script": "x\n"}))
        db.commit()
    r = client.post(f"/api/v1/apps/{app_id}/script/revert", headers=csrf_header(client))
    assert r.status_code == 409
    assert "upstream commit" in r.text.lower()


def test_revert_409s_when_the_catalog_entry_has_no_pinned_script(client, csrf_header,
                                                                 bootstrap_admin):
    bootstrap_admin(client)
    from proxploy.models import CatalogEntry
    with client.app.state.sessionmaker() as db:
        app_id = _seed_app_with_script(db).id
        db.add(CatalogEntry(slug="redis", name="Redis", installable=True,
                            upstream_sha="c" * 40, raw={}))
        db.commit()
    r = client.post(f"/api/v1/apps/{app_id}/script/revert", headers=csrf_header(client))
    assert r.status_code == 409
    assert "no pinned script to revert to" in r.text.lower()


def test_revert_requires_admin(tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        from proxploy.models import CatalogEntry
        with c.app.state.sessionmaker() as db:
            app_row = _seed_app_with_script(db)
            db.add(CatalogEntry(slug="redis", name="Redis", installable=True,
                                upstream_sha="c" * 40,
                                raw={"install_script": "x\n"}))
            db.commit()
            app_id = app_row.id
        c.post("/api/v1/users", json={"email": "op@example.com",
                                      "password": "Correct-Horse-Battery-9",
                                      "display_name": "Op", "role": "operator"},
               headers=csrf_header(c))
        c.post("/api/v1/auth/login", json={"email": "op@example.com",
                                           "password": "Correct-Horse-Battery-9"},
               headers=csrf_header(c))
        r = c.post(f"/api/v1/apps/{app_id}/script/revert", headers=csrf_header(c))
        assert r.status_code == 403 and r.json()["detail"] == "Your role does not allow this."


def test_revert_entitlement_gates_the_route(tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        from proxploy.models import CatalogEntry
        with c.app.state.sessionmaker() as db:
            app_row = _seed_app_with_script(db)
            db.add(CatalogEntry(slug="redis", name="Redis", installable=True,
                                upstream_sha="c" * 40,
                                raw={"install_script": "x\n"}))
            db.commit()
            app_id = app_row.id
        c.app.state.entitlements._features = {"apps.script_edit": False}
        r = c.post(f"/api/v1/apps/{app_id}/script/revert", headers=csrf_header(c))
        assert r.status_code == 403
        assert r.json()["feature"] == "apps.script_edit"


def test_an_operator_may_read_the_script_but_not_write_it(client, csrf_header,
                                                          bootstrap_admin):
    """Doc 05 L115/117 put GET /script and GET /script/versions at operator,
    while PUT and revert are admin. Converting all four onto the single
    ("app","script")=admin entry would have silently tightened read access, 
    no test covered an operator actor here, so nothing would have caught it.
    Hence ("app","script_read")="operator" in the matrix, and hence this test.
    """
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        app_id = _seed_app_with_script(db).id

    client.post("/api/v1/users", json={"email": "op@example.com",
                                       "password": "Correct-Horse-Battery-9",
                                       "display_name": "Op", "role": "operator"},
                headers=csrf_header(client))
    client.post("/api/v1/auth/logout", headers=csrf_header(client))
    client.post("/api/v1/auth/login", json={"email": "op@example.com",
                                            "password": "Correct-Horse-Battery-9"},
                headers=csrf_header(client))

    assert client.get(f"/api/v1/apps/{app_id}/script").status_code == 200
    assert client.get(f"/api/v1/apps/{app_id}/script/versions").status_code == 200
    assert client.put(f"/api/v1/apps/{app_id}/script",
                      json={"content": "msg_ok sneaky\n"},
                      headers=csrf_header(client)).status_code == 403
    assert client.post(f"/api/v1/apps/{app_id}/script/revert",
                       json={"version": 1},
                       headers=csrf_header(client)).status_code == 403


# --- the payload script is read whatever key upstream's shape lands under ---
#
# Five apps (coolify, dockge, dokploy, komodo, runtipi) delegate their
# in-container step to tools/addon/<slug>.sh, so their pinned payload lives in
# raw["addon_script"] rather than raw["install_script"]. Every reader of that
# pair goes through services/catalog.py::pinned_payload_script; these pin the
# two routes that read it.

ADDON_PAYLOAD = "msg_info \"Installing via addon\"\n$STD docker compose up -d\n"


def test_pinned_payload_script_reads_both_shapes():
    from proxploy.models import CatalogEntry
    from proxploy.services.catalog import pinned_payload_script

    normal = CatalogEntry(slug="redis", raw={"install_script": "a"})
    addon = CatalogEntry(slug="dockge", raw={"ct_script": "x",
                                             "addon_script": ADDON_PAYLOAD})
    assert pinned_payload_script(normal) == "a"
    assert pinned_payload_script(addon) == ADDON_PAYLOAD
    # install_script wins when both are present: the more specific key.
    both = CatalogEntry(slug="x", raw={"install_script": "a",
                                       "addon_script": ADDON_PAYLOAD})
    assert pinned_payload_script(both) == "a"
    # Nothing pinned yet stays None, which is what the callers branch on.
    assert pinned_payload_script(CatalogEntry(slug="y", raw=None)) is None
    assert pinned_payload_script(CatalogEntry(slug="z", raw={})) is None
    assert pinned_payload_script(
        CatalogEntry(slug="w", raw={"install_script": ""})) is None


def test_revert_pins_the_addon_script_when_that_is_the_payload(client, csrf_header,
                                                               bootstrap_admin):
    """Without this the route 409s "no pinned script to revert to" for an app
    whose script we have sitting right there."""
    import hashlib

    from proxploy.models import CatalogEntry
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        app_id = _seed_app_with_script(db, content="edited by hand\n").id
        db.add(CatalogEntry(slug="redis", name="Redis", installable=True,
                            upstream_sha="c" * 40,
                            raw={"ct_script": "...", "addon_script": ADDON_PAYLOAD}))
        db.commit()

    r = client.post(f"/api/v1/apps/{app_id}/script/revert", headers=csrf_header(client))

    assert r.status_code == 200, r.text
    with client.app.state.sessionmaker() as db:
        latest = (db.query(AppScript).filter_by(app_id=app_id)
                  .order_by(AppScript.version.desc()).first())
        assert latest.content == ADDON_PAYLOAD
        assert latest.content_sha256 == hashlib.sha256(
            ADDON_PAYLOAD.encode()).hexdigest()
        assert latest.source == "upstream"


def test_the_config_tab_diffs_against_the_addon_script_too(client, csrf_header,
                                                           bootstrap_admin):
    """_diff_vs_upstream compares the pinned app_scripts row against the
    catalog's current payload. Reading only install_script meant no diff was
    ever shown for these apps, which reads as "no drift" rather than as "we
    did not look"."""
    from proxploy.models import CatalogEntry
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        app_id = _seed_app_with_script(db, content="pinned old\n").id
        db.add(CatalogEntry(slug="redis", name="Redis", installable=True,
                            upstream_sha="c" * 40,
                            raw={"ct_script": "...", "addon_script": ADDON_PAYLOAD}))
        db.commit()

    body = client.get(f"/api/v1/apps/{app_id}/script").json()

    assert body["diff_vs_upstream"] is not None
    assert "docker compose up -d" in body["diff_vs_upstream"]
