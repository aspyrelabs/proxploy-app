import httpx

from proxploy.models import CatalogEntry
from tests.conftest import client  # noqa: F401 fixture


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


SHA = "d7bc6b59676456f7a8b3a20f24c3ca589d7fe2f6"
REDIS_CT = 'APP="Redis"\nbuild_container\n'
REDIS_INSTALL = 'msg_info "Setting up Redis"\n$STD apt install -y redis\n'


def _seed_unclassified_ct(db, slug="redis", sha=SHA):
    row = CatalogEntry(slug=slug, entry_type="ct", upstream_sha=sha,
                       script_path=f"ct/{slug}.sh", installable=None)
    db.add(row)
    db.commit()
    return row


def test_opening_a_card_lazily_classifies_it(client, csrf_header, bootstrap_admin, monkeypatch):
    """Decision 2: a card's script pair is fetched the moment it's opened,
    never during discovery. GET /catalog/{slug} is that moment."""
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_unclassified_ct(db)

    def fake_get(url, **kw):
        if url.endswith(f"/{SHA}/ct/redis.sh"):
            return httpx.Response(200, text=REDIS_CT)
        if url.endswith(f"/{SHA}/install/redis-install.sh"):
            return httpx.Response(200, text=REDIS_INSTALL)
        return httpx.Response(404)
    monkeypatch.setattr("proxploy.services.catalog._fetch", fake_get)

    r = client.get("/api/v1/catalog/redis")
    assert r.status_code == 200
    assert r.json()["installable"] is True
    assert r.json()["unsupported_reason"] is None


def test_a_403_or_timeout_fetching_the_script_leaves_the_card_readable(
        client, csrf_header, bootstrap_admin, monkeypatch):
    """Decision 1: degrade silently. A fetch failure while opening a card
    must not 500 it; the card renders with whatever it already had."""
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_unclassified_ct(db)

    def raises(url, **kw):
        raise TimeoutError("upstream timed out")
    monkeypatch.setattr("proxploy.services.catalog._fetch", raises)

    r = client.get("/api/v1/catalog/redis")
    assert r.status_code == 200
    assert r.json()["installable"] is None  # honestly "not yet known", not broken

    # ...and the store list is still fully usable
    r = client.get("/api/v1/catalog")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_a_403_fetching_the_script_reports_400_not_500_via_ct_status(
        client, csrf_header, bootstrap_admin, monkeypatch):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_unclassified_ct(db)

    def not_found(url, **kw):
        return httpx.Response(403)
    monkeypatch.setattr("proxploy.services.catalog._fetch", not_found)

    r = client.get("/api/v1/catalog/redis")
    assert r.status_code == 200
    body = r.json()
    assert body["installable"] is False
    assert "fetch" in body["unsupported_reason"]


def test_entry_type_is_returned_and_filterable(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_entry(db)
        db.add(CatalogEntry(slug="haos", entry_type="vm", name="HAOS", installable=False,
                            unsupported_reason="VM script"))
        db.commit()

    r = client.get("/api/v1/catalog")
    types = {row["slug"]: row["type"] for row in r.json()}
    assert types == {"redis": "ct", "haos": "vm"}

    r = client.get("/api/v1/catalog?entry_type=ct")
    assert [row["slug"] for row in r.json()] == ["redis"]
