"""Global search (PXP-17).

`ui.global_search` was a registered flag with zero implementation, and doc 06's
command palette was dropped rather than reimplemented. This is its data.

It is also, since the Store's own search box was removed, the ONLY way to
search the catalog, which is why the store group matches on description and
slug as well as name, carries its own larger limit, and is gated on
`store.catalog` rather than on `ui.global_search`.
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


def _store_rows(body) -> list[dict]:
    return [r for r in body["results"] if r["kind"] == "store"]


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
        # A route that exists: /settings/hosts/{id} never did, so this
        # assertion passed while the link dead-ended in the browser.
        assert body["results"][0]["href"] == "/settings?section=hosts"


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
        results = c.get("/api/v1/search", params={"q": "immich"}).json()["results"]
        for r in results:
            assert r["href"].startswith("/") and r["label"] and r["kind"]
        # Neither an app nor a VM has a page of its own any more: both are a
        # row that expands on its list, so the href has to carry which row.
        for kind, prefix in (("app", "/apps?open="), ("vm", "/vms?open=")):
            for r in results:
                if r["kind"] == kind:
                    assert r["href"] == f"{prefix}{r['id']}"


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
                                          "password": "Correct-Horse-Battery-9",
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
                                     "password": "Correct-Horse-Battery-9"},
                               headers=csrf_header(other))
            assert login.status_code == 200, login.text
            got = other.get("/api/v1/search", params={"q": "immich"})
            # Either the route refuses outright or it returns nothing; what it
            # must never do is list inventory.
            assert got.status_code in (401, 403) or got.json()["results"] == []


# --- the store group stands in for the Store's deleted search box -----------

def test_a_term_that_matches_only_a_description_finds_the_store_entry(
        tmp_path, csrf_header, bootstrap_admin):
    """617 catalog rows carry a real upstream description
    (services/catalog_metadata.py). A palette matching names only would have
    made every one of them unsearchable the day they landed, and there is no
    longer a store search box to fall back to."""
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()
        with app.state.sessionmaker() as db:
            db.add(CatalogEntry(slug="paperless-ngx", name="Paperless-ngx",
                                description="Scan, index and archive documents.",
                                entry_type="ct", script_path="ct/paperless-ngx.sh"))
            db.commit()

        rows = _store_rows(c.get("/api/v1/search", params={"q": "archive docum"}).json())

        assert [r["id"] for r in rows] == ["paperless-ngx"]
        assert rows[0]["href"] == "/store/paperless-ngx"


def test_a_term_that_matches_only_a_slug_finds_the_store_entry(
        tmp_path, csrf_header, bootstrap_admin):
    """The mirror case, and the reason slug stays in the haystack: the 9
    "unlisted" rows have no description at all, so their slug is the only
    thing left to match, and it is usually what a person would type."""
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()
        with app.state.sessionmaker() as db:
            db.add(CatalogEntry(slug="rwmarkable", name="Some Display Name",
                                entry_type="ct", upstream_state="unlisted",
                                script_path="ct/rwmarkable.sh"))
            db.commit()

        rows = _store_rows(c.get("/api/v1/search", params={"q": "rwmark"}).json())

        assert [r["id"] for r in rows] == ["rwmarkable"]


def test_the_store_group_has_its_own_larger_limit(tmp_path, csrf_header,
                                                  bootstrap_admin):
    """PER_KIND=8 is a navigation limit: you know the app exists and you are
    jumping to it. The store is a 557-entry catalog people browse, and at 8 a
    short query truncates to near-nothing and the palette looks like the
    catalog does not hold what it plainly does. Still bounded: never the
    whole catalog."""
    from proxploy.api.search import PER_KIND, STORE_PER_KIND

    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()
        with app.state.sessionmaker() as db:
            for i in range(60):
                db.add(CatalogEntry(slug=f"widget-{i:03d}", name=f"Widget {i:03d}",
                                    entry_type="ct",
                                    script_path=f"ct/widget-{i:03d}.sh"))
            db.commit()

        rows = _store_rows(c.get("/api/v1/search", params={"q": "widget"}).json())

        assert STORE_PER_KIND > PER_KIND
        assert len(rows) == STORE_PER_KIND == 25


# --- the two entitlements gate two different things -------------------------

def test_store_results_survive_without_ui_global_search(tmp_path, csrf_header,
                                                        bootstrap_admin):
    """The capability this restructuring exists to protect. The Store's own
    search box was never behind `ui.global_search`, so a plan carrying
    `store.catalog` without it must still be able to search the store; and it
    must still get NOTHING from the app, VM and host groups, which are exactly
    as gated as they were when the whole route was."""
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()
        c.app.state.entitlements._features = {"store.catalog": True,
                                              "ui.global_search": False}

        got = c.get("/api/v1/search", params={"q": "immich"})

        assert got.status_code == 200, got.text
        kinds = {r["kind"] for r in got.json()["results"]}
        assert kinds == {"store"}
        assert [r["id"] for r in got.json()["results"]] == ["immich"]


def test_the_other_groups_still_need_ui_global_search(tmp_path, csrf_header,
                                                      bootstrap_admin):
    """The other half: dropping the route-level dependency must not hand an
    app, VM or host row to a caller who could not have reached this endpoint
    at all a moment ago."""
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()
        c.app.state.entitlements._features = {"store.catalog": True,
                                              "ui.global_search": False}

        body = c.get("/api/v1/search", params={"q": "pve-node"}).json()
        assert body["results"] == []          # the host is invisible

        # ...and turning it back on restores exactly the previous behaviour.
        c.app.state.entitlements._features = {"store.catalog": True,
                                              "ui.global_search": True}
        body = c.get("/api/v1/search", params={"q": "pve-node"}).json()
        assert [r["kind"] for r in body["results"]] == ["host"]


def test_a_plan_with_neither_entitlement_is_refused_outright(tmp_path, csrf_header,
                                                             bootstrap_admin):
    """With nothing to serve, the answer stays the 403 the route-level
    dependency already gave this caller. An empty 200 would claim the feature
    exists and is merely finding nothing."""
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()
        c.app.state.entitlements._features = {"store.catalog": False,
                                              "ui.global_search": False}

        got = c.get("/api/v1/search", params={"q": "immich"})

        assert got.status_code == 403
        # Same problem+json shape require_entitlement produced from the route
        # dependency (main.py's problem_handler flattens a dict detail), so a
        # client that already handled this response keeps working.
        body = got.json()
        assert body["error"] == "entitlement_required"
        assert body["feature"] == "ui.global_search"


def test_store_results_still_need_catalog_read_permission(tmp_path, monkeypatch,
                                                          csrf_header,
                                                          bootstrap_admin):
    """The entitlement is a plan flag; RBAC is the other axis and neither
    substitutes for the other. Both halves of the condition are load bearing,
    so an entitled plan with no catalog read still sees no store rows."""
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()
        c.app.state.entitlements._features = {"store.catalog": True,
                                              "ui.global_search": False}

        def deny_catalog(request, db, user, resource, action):
            return resource != "catalog"
        monkeypatch.setattr("proxploy.api.search._visible", deny_catalog)

        body = c.get("/api/v1/search", params={"q": "immich"}).json()

        assert body["results"] == []


def test_search_needs_a_session(tmp_path):
    from fastapi.testclient import TestClient
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        assert c.get("/api/v1/search", params={"q": "immich"}).status_code == 401


# --- the store group returns only rows the Store can actually open ----------
#
# USER-REPORTED BUG. Searching "alpine" returned 25 store results of which 20
# were unopenable: 28 hidden alpine-<parent> variants and 84 non-ct rows were
# all in scope, each emitting `href: /store/<slug>` for a card the Store does
# not render, so selecting one opened Not Found. The rule for "can the Store
# show this" had been written twice and only the copy in list_catalog was kept
# up to date; there is now one shared definition and these pin it.

def _seed_every_kind_of_row(db):
    """One row of every visibility class, all matching the same search term so
    a single query sees the whole matrix."""
    rows = [
        # visible: a normal listed ct row
        CatalogEntry(slug="adguard", name="AdGuard Home", entry_type="ct",
                     upstream_state="listed"),
        # visible: never synced, so upstream_state is NULL. This is the fresh
        # install case a bare `!= 'variant'` would silently drop.
        CatalogEntry(slug="adguard-fresh", name="AdGuard Fresh", entry_type="ct",
                     upstream_state=None),
        # visible: retired upstream but still installable, still a card
        CatalogEntry(slug="adguard-old", name="AdGuard Old", entry_type="ct",
                     upstream_state="delisted"),
        CatalogEntry(slug="adguard-gone", name="AdGuard Gone", entry_type="ct",
                     upstream_state="unlisted"),
        # HIDDEN: the phantom the user actually clicked
        CatalogEntry(slug="alpine-adguard", name="Alpine Adguard", entry_type="ct",
                     upstream_state="variant"),
        # HIDDEN: every non-ct type, whatever its state
        CatalogEntry(slug="adguard-vm", name="AdGuard VM", entry_type="vm",
                     upstream_state="listed"),
        CatalogEntry(slug="adguard-pve", name="AdGuard PVE", entry_type="pve",
                     upstream_state="listed"),
        CatalogEntry(slug="adguard-addon", name="AdGuard Addon", entry_type="addon",
                     upstream_state=None),
        CatalogEntry(slug="adguard-turnkey", name="AdGuard Turnkey",
                     entry_type="turnkey", upstream_state="listed"),
    ]
    for row in rows:
        db.add(row)
    db.commit()


VISIBLE = {"adguard", "adguard-fresh", "adguard-old", "adguard-gone"}


def test_a_hidden_alpine_variant_never_appears_in_search(tmp_path, csrf_header,
                                                         bootstrap_admin):
    """The exact row from the report. It stays a ct row and stays installable;
    it is simply not something the Store can open."""
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        with app.state.sessionmaker() as db:
            _seed_every_kind_of_row(db)

        rows = _store_rows(c.get("/api/v1/search", params={"q": "adguard"}).json())

        assert "alpine-adguard" not in {r["id"] for r in rows}


def test_no_vm_pve_addon_or_turnkey_row_is_offered_as_a_store_result(
        tmp_path, csrf_header, bootstrap_admin):
    """84 of them, and every one emitted a /store/<slug> href for a type the
    Store never shows."""
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        with app.state.sessionmaker() as db:
            _seed_every_kind_of_row(db)

        ids = {r["id"] for r in
               _store_rows(c.get("/api/v1/search", params={"q": "adguard"}).json())}

        for hidden in ("adguard-vm", "adguard-pve", "adguard-addon",
                       "adguard-turnkey"):
            assert hidden not in ids, hidden


def test_normal_and_never_synced_ct_rows_are_still_returned(tmp_path, csrf_header,
                                                            bootstrap_admin):
    """The other half: the fix must not empty search. A NULL upstream_state is
    a fresh install, not a hidden row, and delisted/unlisted rows are badged
    cards that the Store still shows."""
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        with app.state.sessionmaker() as db:
            _seed_every_kind_of_row(db)

        ids = {r["id"] for r in
               _store_rows(c.get("/api/v1/search", params={"q": "adguard"}).json())}

        assert ids == VISIBLE


def test_search_and_the_store_grid_return_the_same_row_set(tmp_path, csrf_header,
                                                           bootstrap_admin):
    """THE DRIFT TEST, and the reason the predicate is shared rather than
    written twice. Every result carries `href: /store/<slug>`, so anything
    search offers and the grid does not is a Not Found waiting to happen. This
    fails the moment the two call sites disagree, whatever the disagreement
    is."""
    from proxploy.api.catalog import list_catalog

    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        with app.state.sessionmaker() as db:
            _seed_every_kind_of_row(db)

            grid = {r["slug"] for r in list_catalog(entry_type="ct", db=db,
                                                    user=None)
                    if "adguard" in r["slug"]}
        found = {r["id"] for r in
                 _store_rows(c.get("/api/v1/search", params={"q": "adguard"}).json())}

        assert found == grid == VISIBLE


def test_both_call_sites_use_the_one_shared_predicate(tmp_path):
    """Belt and braces beside the behavioural test above: neither module may
    hold its own copy of the rule."""
    import proxploy.api.catalog as catalog_mod
    import proxploy.api.search as search_mod
    from proxploy.services.catalog_metadata import store_visible

    assert catalog_mod.store_visible is store_visible
    assert search_mod.store_visible is store_visible
