from proxploy.models import CatalogEntry
from tests.conftest import client  # noqa: F401 fixture
from tests.support import make_db


def _seed_entry(db, **overrides):
    row = CatalogEntry(slug="redis", name="Redis", category="Databases",
                       installable=True, unsupported_reason=None, **overrides)
    db.add(row)
    db.commit()
    return row


def test_list_catalog_requires_auth(client):
    r = client.get("/api/v1/catalog")
    assert r.status_code == 401


def test_list_and_get_catalog_entry(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_entry(db)
    r = client.get("/api/v1/catalog")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1 and body[0]["slug"] == "redis"

    r = client.get("/api/v1/catalog/redis")
    assert r.status_code == 200 and r.json()["name"] == "Redis"

    r = client.get("/api/v1/catalog/does-not-exist")
    assert r.status_code == 404


def test_category_and_query_filters(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_entry(db)
        db.add(CatalogEntry(slug="grafana", name="Grafana", category="Monitoring", installable=True))
        db.commit()
    assert len(client.get("/api/v1/catalog?category=Monitoring").json()) == 1
    assert len(client.get("/api/v1/catalog?q=redis").json()) == 1
    assert len(client.get("/api/v1/catalog?q=nomatch").json()) == 0


def test_refresh_enqueues_a_job(client, csrf_header, bootstrap_admin, monkeypatch):
    bootstrap_admin(client)
    r = client.post("/api/v1/catalog/refresh", headers=csrf_header(client))
    assert r.status_code == 202
    job = r.json()["job"]
    assert job["kind"] == "catalog.refresh"
