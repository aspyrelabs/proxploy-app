from proxploy.models import App
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
