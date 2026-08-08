"""Global search (PXP-17).

`ui.global_search` was a registered flag with zero implementation, and doc 06's
command palette was dropped rather than reimplemented. This is its data.
"""
from proxploy.models import App, CatalogEntry, TeamMember, User, Vm


def _seeded(tmp_path):
    from fastapi.testclient import TestClient
    from tests.support import make_app, seed_host_row

    app = make_app(tmp_path)
    c = TestClient(app)

    def seed():
        with app.state.sessionmaker() as db:
            h = seed_host_row(db, name="pve-node-01")
            db.add(App(host_id=h.id, ctid=150, name="Immich", slug="immich",
                       status_cached="running"))
            db.add(App(host_id=h.id, ctid=151, name="Immich Archive",
                       slug="immich-archive", status_cached="stopped"))
            db.add(Vm(host_id=h.id, vmid=100, name="immich-builder",
                      status="stopped"))
            db.add(CatalogEntry(slug="immich", name="Immich", category="media",
                                script_path="ct/immich.sh", installable=True))
            db.commit()
    return app, c, seed


def test_search_spans_apps_vms_hosts_and_the_store(tmp_path, csrf_header,
                                                   bootstrap_admin):
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()
        body = c.get("/api/v1/search", params={"q": "immich"}).json()
        kinds = {r["kind"] for r in body["results"]}
        assert kinds == {"app", "vm", "store"}
        labels = [r["label"] for r in body["results"]]
        assert "Immich Archive" in labels and "immich-builder" in labels


def test_a_host_matches_on_its_name(tmp_path, csrf_header, bootstrap_admin):
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()
        body = c.get("/api/v1/search", params={"q": "pve-node"}).json()
        assert [r["kind"] for r in body["results"]] == ["host"]
        assert body["results"][0]["href"].startswith("/settings/hosts/")


def test_an_exact_match_sorts_above_a_substring_match(tmp_path, csrf_header,
                                                      bootstrap_admin):
    """Otherwise a result's rank depends on which table was queried first,
    which is an implementation detail leaking into the UI."""
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()
        labels = [r["label"] for r in
                  c.get("/api/v1/search", params={"q": "Immich"}).json()["results"]]
        assert labels[0] == "Immich"
        assert labels.index("Immich") < labels.index("Immich Archive")


def test_a_short_query_returns_nothing_rather_than_everything(tmp_path, csrf_header,
                                                              bootstrap_admin):
    """A palette that dumps the whole inventory on the first keystroke is
    noise; there is a nav for browsing."""
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()
        for q in ("", " ", "i"):
            assert c.get("/api/v1/search", params={"q": q}).json()["results"] == []


def test_results_carry_a_href_the_ui_can_navigate_to(tmp_path, csrf_header,
                                                     bootstrap_admin):
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()
        for r in c.get("/api/v1/search", params={"q": "immich"}).json()["results"]:
            assert r["href"].startswith("/") and r["label"] and r["kind"]


def test_search_never_reveals_a_resource_the_caller_cannot_read(
        tmp_path, csrf_header, bootstrap_admin):
    """Search must not be the one place a restricted user discovers inventory.

    A viewer keeps app/vm/host/catalog read, so this drops the membership
    entirely: with no role at all, authz is fail-closed and every section must
    filter itself out rather than the route simply 403ing.
    """
    from fastapi.testclient import TestClient

    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()
        r = c.post("/api/v1/users", json={"email": "nobody@example.com",
                                          "password": "correct-horse-battery",
                                          "role": "viewer"},
                   headers=csrf_header(c))
        uid = r.json()["id"]
        with app.state.sessionmaker() as db:
            for m in db.query(TeamMember).filter_by(user_id=uid):
                db.delete(m)
            db.commit()
            db.get(User, uid).is_active = True
            db.commit()
        from proxploy.services.authz import build_enforcer
        with app.state.sessionmaker() as db:
            app.state.authz = build_enforcer(db)

        other = TestClient(app)
        with other:
            login = other.post("/api/v1/auth/login",
                               json={"email": "nobody@example.com",
                                     "password": "correct-horse-battery"},
                               headers=csrf_header(other))
            assert login.status_code == 200, login.text
            got = other.get("/api/v1/search", params={"q": "immich"})
            # Either the route refuses outright or it returns nothing; what it
            # must never do is list inventory.
            assert got.status_code in (401, 403) or got.json()["results"] == []


def test_search_needs_a_session(tmp_path):
    from fastapi.testclient import TestClient
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        assert c.get("/api/v1/search", params={"q": "immich"}).status_code == 401
