"""App Store staleness indicator (PXP-17).

doc 01's Catalog refresh row promises a "staleness indicator in UI" and a
Phase 4 DoD clause named the banner. Neither was built.
"""
from datetime import timedelta

from proxploy.models import CatalogEntry, utcnow


def _app(tmp_path, **overrides):
    from fastapi.testclient import TestClient
    from tests.support import make_app

    app = make_app(tmp_path, **overrides)
    return app, TestClient(app)


def _seed(app, synced_at):
    with app.state.sessionmaker() as db:
        db.add(CatalogEntry(slug="immich", name="Immich", category="media",
                            script_path="ct/immich.sh", synced_at=synced_at,
                            installable=True))
        db.commit()


def test_a_never_refreshed_catalog_is_stale(tmp_path, csrf_header, bootstrap_admin):
    """An empty catalog is not a fresh one. Reporting it as fresh would hide
    the most broken state there is."""
    app, c = _app(tmp_path)
    with c:
        bootstrap_admin(c)
        r = c.get("/api/v1/catalog/status")
        assert r.status_code == 200, r.text
        assert r.json()["stale"] is True
        assert r.json()["synced_at"] is None and r.json()["entries"] == 0


def test_a_fresh_catalog_is_not_stale(tmp_path, csrf_header, bootstrap_admin):
    app, c = _app(tmp_path)
    with c:
        bootstrap_admin(c)
        _seed(app, utcnow())
        body = c.get("/api/v1/catalog/status").json()
        assert body["stale"] is False
        assert body["entries"] == 1 and body["age_s"] < 60


def test_a_catalog_older_than_the_threshold_is_stale(tmp_path, csrf_header,
                                                    bootstrap_admin):
    """48h by default: the refresh schedule is daily, so this means two
    consecutive refreshes did not land, which is a fault and not bad luck."""
    app, c = _app(tmp_path)
    with c:
        bootstrap_admin(c)
        _seed(app, utcnow() - timedelta(hours=49))
        body = c.get("/api/v1/catalog/status").json()
        assert body["stale"] is True
        assert body["stale_after_s"] == 172800.0


def test_the_threshold_is_configurable(tmp_path, csrf_header, bootstrap_admin):
    app, c = _app(tmp_path, catalog_stale_after_s=60.0)
    with c:
        bootstrap_admin(c)
        _seed(app, utcnow() - timedelta(minutes=5))
        assert c.get("/api/v1/catalog/status").json()["stale"] is True


def test_status_is_not_shadowed_by_the_slug_route(tmp_path, csrf_header,
                                                 bootstrap_admin):
    """Starlette matches in registration order. Declared after /{slug}, this
    would silently become a lookup for an entry named "status" and 404 forever.
    """
    app, c = _app(tmp_path)
    with c:
        bootstrap_admin(c)
        _seed(app, utcnow())
        r = c.get("/api/v1/catalog/status")
        assert r.status_code == 200
        assert "stale" in r.json(), "shadowed: this is a catalog entry, not status"
        # And the slug route still works for a real entry.
        assert c.get("/api/v1/catalog/immich").json()["slug"] == "immich"


def test_status_needs_a_session(tmp_path):
    from fastapi.testclient import TestClient
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        assert c.get("/api/v1/catalog/status").status_code == 401
