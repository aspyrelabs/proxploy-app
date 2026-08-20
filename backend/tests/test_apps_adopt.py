from proxploy.models import App, CatalogEntry
from tests.support import seed_host_row


def test_adopt_creates_app_rows_for_each_item(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        host = seed_host_row(db)
        host_id = host.id

    r = client.post("/api/v1/apps/adopt", json={"items": [
        {"host_id": host_id, "ctid": 150, "name": "Immich", "catalog_slug": "immich"},
        {"host_id": host_id, "ctid": 151, "name": "Unknown CT", "catalog_slug": None},
    ]}, headers=csrf_header(client))
    assert r.status_code == 200
    body = r.json()
    assert len(body["adopted"]) == 2

    with client.app.state.sessionmaker() as db:
        rows = db.query(App).filter_by(host_id=host_id).all()
        assert {r.ctid for r in rows} == {150, 151}
        assert all(r.adopted for r in rows)


def test_adopt_rejects_a_ctid_already_adopted_on_that_host(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        host = seed_host_row(db)
        host_id = host.id
    client.post("/api/v1/apps/adopt", json={"items": [
        {"host_id": host_id, "ctid": 150, "name": "Immich", "catalog_slug": None}]},
        headers=csrf_header(client))

    r = client.post("/api/v1/apps/adopt", json={"items": [
        {"host_id": host_id, "ctid": 150, "name": "Immich again", "catalog_slug": None}]},
        headers=csrf_header(client))
    assert r.status_code == 409


def test_adopt_copies_category_and_port_from_the_catalog_entry(
        client, csrf_header, bootstrap_admin):
    """Adopt used to set neither, so every adopted app read back with no
    category (the grid grouped them all as unknown) and no web port (nothing on
    the row knew where its web UI answers)."""
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        host = seed_host_row(db)
        host_id = host.id
        db.add(CatalogEntry(slug="adguard", name="AdGuard Home",
                            category="Adblock & DNS", port=3000,
                            installable=True))
        db.commit()

    r = client.post("/api/v1/apps/adopt", json={"items": [
        {"host_id": host_id, "ctid": 102, "name": "adguard",
         "catalog_slug": "adguard"}]}, headers=csrf_header(client))
    assert r.status_code == 200

    with client.app.state.sessionmaker() as db:
        row = db.query(App).filter_by(host_id=host_id, ctid=102).one()
        assert row.category == "Adblock & DNS"
        assert row.web_port == 3000


def test_adopt_without_a_resolvable_catalog_slug_still_works(
        client, csrf_header, bootstrap_admin):
    """A None slug and a slug no catalog entry answers to are both ordinary:
    they adopt with no category and no port rather than failing."""
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        host = seed_host_row(db)
        host_id = host.id

    r = client.post("/api/v1/apps/adopt", json={"items": [
        {"host_id": host_id, "ctid": 150, "name": "Mystery CT",
         "catalog_slug": None},
        {"host_id": host_id, "ctid": 151, "name": "Gone Upstream",
         "catalog_slug": "no-such-entry"},
    ]}, headers=csrf_header(client))
    assert r.status_code == 200
    assert len(r.json()["adopted"]) == 2

    with client.app.state.sessionmaker() as db:
        rows = db.query(App).filter_by(host_id=host_id).all()
        assert {r.ctid for r in rows} == {150, 151}
        assert all(r.category is None and r.web_port is None for r in rows)
