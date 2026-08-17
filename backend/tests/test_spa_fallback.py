"""The SPA deep-link fallback (doc 12's "Known bug: SPA deep links 404").

`_SPAStatic` lives inside create_app(), and the mount only happens when
frontend/dist exists, so these drive the class through a minimal Starlette app
over a temp dist instead of building the whole app. What matters is the four
behaviours, one of which is why the first attempt at this fix was reverted.
"""
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from proxploy.main import _SPAStatic


@pytest.fixture
def client(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>Proxploy</title>")
    (dist / "app.js").write_text("console.log('real asset')")

    # The class is defined inside create_app(), so reach it the way the app
    # does: build a throwaway app with the same mount shape.
    app = FastAPI()

    @app.get("/api/v1/thing")
    def thing():
        raise HTTPException(404, {"error": "structured_detail"})

    app.mount("/", _SPAStatic(directory=dist, html=True), name="spa")
    return TestClient(app)


def test_real_asset_is_served_unchanged(client):
    r = client.get("/app.js")
    assert r.status_code == 200
    assert "real asset" in r.text


def test_client_side_route_gets_index_html(client):
    """The bug: refreshing on a client-side route 404'd in production."""
    r = client.get("/settings", headers={"accept": "text/html"})
    assert r.status_code == 200
    assert "<title>Proxploy</title>" in r.text


def test_nested_client_side_route_gets_index_html(client):
    r = client.get("/store/plex", headers={"accept": "text/html"})
    assert r.status_code == 200
    assert "<title>Proxploy</title>" in r.text


def test_missing_asset_stays_404(client):
    """A fetch for a missing module must not be answered with HTML: that fails
    further from the cause than a 404 does."""
    r = client.get("/missing.js", headers={"accept": "*/*"})
    assert r.status_code == 404
    assert "<title>" not in r.text


def test_unmatched_api_path_is_not_answered_with_html(client):
    """Even from a browser. /api/ is a caller error, never a page."""
    r = client.get("/api/v1/nope", headers={"accept": "text/html"})
    assert r.status_code == 404
    assert "<title>Proxploy</title>" not in r.text


def test_a_routes_own_structured_404_is_untouched(client):
    """This is the regression the first attempt caused, and the reason the fix
    is a StaticFiles subclass rather than a 404 exception handler: a handler
    replaced the body of every other 404 too, flattening details like
    oidc_not_configured (tests/test_oidc.py)."""
    r = client.get("/api/v1/thing", headers={"accept": "text/html"})
    assert r.status_code == 404
    assert r.json()["detail"] == {"error": "structured_detail"}
