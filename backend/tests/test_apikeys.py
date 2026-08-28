"""API keys (Task 12, doc 04 `api_keys` / doc 08 §6): bearer resolution,
scope narrowing on top of authorize(), and the create/list/revoke routes.
"""
import hashlib

import pytest
from fastapi.testclient import TestClient

from proxploy.models import ApiKey, App, AuditEvent, User
from tests.support import entitle, make_app, seed_host_row


def _mk_user(client, csrf_header, email, role, password="Correct-Horse-Battery-9"):
    h = csrf_header(client)
    r = client.post("/api/v1/users", json={"email": email, "password": password,
                                           "role": role}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _login(client, csrf_header, email, password="Correct-Horse-Battery-9"):
    r = client.post("/api/v1/auth/login", json={"email": email,
                    "password": password}, headers=csrf_header(client))
    assert r.status_code == 200, r.text


def _seed_app(app_obj):
    with app_obj.state.sessionmaker() as db:
        h = seed_host_row(db)
        a = App(host_id=h.id, ctid=150, name="Immich", slug="immich")
        db.add(a)
        db.commit()
        return h.id, a.id


@pytest.fixture
def app_client(tmp_path, csrf_header, bootstrap_admin):
    # API keys are a Team feature. This file is about what a key can do once
    # it exists, not about who may mint one.
    app = entitle(make_app(tmp_path), "api.tokens")
    with TestClient(app) as c:
        bootstrap_admin(c)             # owner session, default team
        yield app, c


def _create_key(c, csrf_header, name="ci", scopes=None, expires_at=None):
    body = {"name": name}
    if scopes is not None:
        body["scopes"] = scopes
    if expires_at is not None:
        body["expires_at"] = expires_at
    r = c.post("/api/v1/api-keys", json=body, headers=csrf_header(c))
    return r


# --- create / list / hashing / audit ---------------------------------------


def test_create_shows_raw_key_once_and_hashes_at_rest(app_client, csrf_header):
    app, c = app_client
    r = _create_key(c, csrf_header)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["key"].startswith("ppk_")
    assert body["prefix"] == body["key"][:8]
    with app.state.sessionmaker() as db:
        row = db.query(ApiKey).filter_by(id=body["id"]).one()
        assert row.key_hash == hashlib.sha256(body["key"].encode()).hexdigest()
        assert row.key_hash != body["key"]


def test_list_shows_prefix_only_no_hash_or_raw_key(app_client, csrf_header):
    app, c = app_client
    created = _create_key(c, csrf_header).json()
    rows = c.get("/api/v1/api-keys").json()
    assert len(rows) == 1
    row = rows[0]
    assert row["prefix"] == created["prefix"]
    assert "key" not in row
    assert "key_hash" not in row


def test_raw_key_never_appears_in_any_audit_row(app_client, csrf_header):
    app, c = app_client
    created = _create_key(c, csrf_header).json()
    raw = created["key"]
    c.delete(f"/api/v1/api-keys/{created['id']}", headers=csrf_header(c))
    with app.state.sessionmaker() as db:
        for row in db.query(AuditEvent).all():
            assert raw not in str(row.params)


def test_unknown_scope_string_422s_at_creation(app_client, csrf_header):
    app, c = app_client
    assert _create_key(c, csrf_header, scopes=["gizmo:write"]).status_code == 422
    assert _create_key(c, csrf_header, scopes=["admin"]).status_code == 422
    # PXP-32: a real resource with an action that isn't in the matrix is
    # still unknown, "host:write" being valid does not make every
    # "host:<anything>" string valid.
    assert _create_key(c, csrf_header, scopes=["host:teleport"]).status_code == 422


def test_per_action_scope_string_is_accepted_at_creation(app_client, csrf_header):
    """PXP-32: each of the matrix's 57 (resource, action) pairs is now a
    grantable scope string on its own, not just '<resource>:write'."""
    app, c = app_client
    assert _create_key(c, csrf_header, scopes=["host:remove"]).status_code == 201
    assert _create_key(c, csrf_header, scopes=["vm:snapshot"]).status_code == 201
    assert _create_key(c, csrf_header, scopes=["app:install"]).status_code == 201


def test_revoke_is_404_for_someone_elses_key(app_client, csrf_header):
    app, c = app_client
    created = _create_key(c, csrf_header).json()
    _mk_user(c, csrf_header, "other@x.io", "owner")
    c.post("/api/v1/auth/logout", headers=csrf_header(c))
    _login(c, csrf_header, "other@x.io")
    r = c.delete(f"/api/v1/api-keys/{created['id']}", headers=csrf_header(c))
    assert r.status_code == 404


# --- bearer resolution -------------------------------------------------


def test_bearer_auth_without_cookies_works(app_client, csrf_header):
    app, c = app_client
    raw = _create_key(c, csrf_header).json()["key"]
    c.cookies.clear()   # prove the header alone authenticates, not a stray session cookie
    r = c.get("/api/v1/hosts", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 200


def test_bearer_post_needs_no_csrf_header(app_client, csrf_header):
    app, c = app_client
    raw = _create_key(c, csrf_header).json()["key"]
    c.cookies.clear()
    # no X-CSRF-Token at all: middleware.py exempts the API-key scheme
    r = c.post("/api/v1/api-keys", json={"name": "second"},
              headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 201


@pytest.mark.parametrize("header", [
    "Basic YWRtaW46YWRtaW4=",       # a stale same-origin credential the browser still sends
    "Bearer not-a-proxploy-key",    # right scheme, not our token shape
    "bearer ppk_wrong_case",        # deps.py's Bearer match is case-sensitive; so is ours
])
def test_csrf_exemption_needs_the_api_key_scheme_not_just_any_authorization(
        app_client, csrf_header, header):
    """PXP-34: the exemption used to be `"authorization" not in headers`, so
    ANY Authorization header bought a full CSRF bypass on every mutating
    route. A cross-site page cannot make a browser attach `Bearer ppk_...`,
    but it can ride along on a Basic credential the user once entered for the
    same origin. Each header below must now be refused by CSRF (403), never
    reach the route, and never come back as a 401 from authentication --
    a 401 would mean the middleware let it through.
    """
    app, c = app_client
    c.cookies.clear()
    r = c.post("/api/v1/api-keys", json={"name": "nope"},
               headers={"Authorization": header})
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "CSRF token missing or invalid"


def test_revoked_key_is_401(app_client, csrf_header):
    app, c = app_client
    created = _create_key(c, csrf_header).json()
    raw = created["key"]
    c.delete(f"/api/v1/api-keys/{created['id']}", headers=csrf_header(c))
    c.cookies.clear()
    r = c.get("/api/v1/hosts", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 401


def test_expired_key_is_401(app_client, csrf_header):
    app, c = app_client
    raw = _create_key(c, csrf_header, expires_at="2000-01-01T00:00:00").json()["key"]
    c.cookies.clear()
    r = c.get("/api/v1/hosts", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 401


def test_deactivated_user_key_is_401(app_client, csrf_header):
    app, c = app_client
    raw = _create_key(c, csrf_header).json()["key"]
    with app.state.sessionmaker() as db:
        u = db.query(User).filter_by(email="admin@example.com").one()
        u.is_active = False
        db.commit()
    c.cookies.clear()
    r = c.get("/api/v1/hosts", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 401


def test_garbage_bearer_token_is_401(app_client, csrf_header):
    app, c = app_client
    c.cookies.clear()
    r = c.get("/api/v1/hosts", headers={"Authorization": "Bearer ppk_not-a-real-key"})
    assert r.status_code == 401
    r = c.get("/api/v1/hosts", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401


def test_bearer_401s_when_api_tokens_entitlement_is_off(app_client, csrf_header):
    app, c = app_client
    raw = _create_key(c, csrf_header).json()["key"]
    c.app.state.entitlements._features["api.tokens"] = False
    c.cookies.clear()
    r = c.get("/api/v1/hosts", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 401


def test_last_used_at_stamped_once_per_minute(app_client, csrf_header):
    app, c = app_client
    created = _create_key(c, csrf_header)
    raw = created.json()["key"]
    key_id = created.json()["id"]
    c.cookies.clear()
    h = {"Authorization": f"Bearer {raw}"}
    assert c.get("/api/v1/hosts", headers=h).status_code == 200
    with app.state.sessionmaker() as db:
        first = db.query(ApiKey).filter_by(id=key_id).one().last_used_at
    assert first is not None
    assert c.get("/api/v1/hosts", headers=h).status_code == 200
    with app.state.sessionmaker() as db:
        second = db.query(ApiKey).filter_by(id=key_id).one().last_used_at
    assert second == first   # same key-minute, no second write


# --- scope narrows the user's own role, never widens it --------------------


def test_key_is_capped_by_owners_role_not_a_second_grant(tmp_path, csrf_header,
                                                          bootstrap_admin):
    """A viewer's unscoped key still cannot PATCH a host: empty scopes means
    'full user rights' (doc 04), and the user's own rights top out at viewer.
    Proves a key can only narrow, never widen, its owner's role."""
    app = entitle(make_app(tmp_path), "api.tokens")
    with TestClient(app) as c:
        bootstrap_admin(c)
        with app.state.sessionmaker() as db:
            host_id = seed_host_row(db).id
        _mk_user(c, csrf_header, "viewer@x.io", "viewer")
        c.post("/api/v1/auth/logout", headers=csrf_header(c))
        _login(c, csrf_header, "viewer@x.io")
        raw = _create_key(c, csrf_header).json()["key"]   # unscoped
        c.cookies.clear()
        h = {"Authorization": f"Bearer {raw}"}
        assert c.get("/api/v1/hosts", headers=h).status_code == 200
        r = c.patch(f"/api/v1/hosts/{host_id}",
                    json={"node_shell_enabled": True}, headers=h)
        assert r.status_code == 403   # casbin still denies: viewer can't manage hosts


def test_read_scope_key_cannot_write_and_is_audited_as_api_key(app_client, csrf_header):
    app, c = app_client
    _, app_id = _seed_app(app)
    raw = _create_key(c, csrf_header, scopes=["read"]).json()["key"]
    c.cookies.clear()
    h = {"Authorization": f"Bearer {raw}"}
    assert c.get("/api/v1/hosts", headers=h).status_code == 200
    r = c.post(f"/api/v1/apps/{app_id}/start", headers=h)
    assert r.status_code == 403
    with app.state.sessionmaker() as db:
        row = (db.query(AuditEvent)
               .filter_by(action="app.lifecycle", result="denied").one())
        assert row.actor_type == "api_key"


def test_host_write_scope_still_authorizes_every_host_action(app_client, csrf_header):
    """PXP-32 backward compat: 'resource:write' stays shorthand for every
    action on that resource. A key holding 'host:write' must keep
    authorizing host:manage (PATCH) AND host:remove (DELETE), the two host
    actions doc PXP-32 names by example, after per-action scopes landed."""
    app, c = app_client
    with app.state.sessionmaker() as db:
        host_id = seed_host_row(db).id
    raw = _create_key(c, csrf_header, scopes=["host:write"]).json()["key"]
    c.cookies.clear()
    h = {"Authorization": f"Bearer {raw}"}
    r = c.patch(f"/api/v1/hosts/{host_id}",
               json={"node_shell_enabled": True}, headers=h)
    assert r.status_code == 200, r.text
    r2 = c.request("DELETE", f"/api/v1/hosts/{host_id}",
                   json={"confirm": "host-01"}, headers=h)
    assert r2.status_code == 200, r2.text
    assert r2.json()["removed"] is True


def test_per_action_scope_authorizes_only_that_action(app_client, csrf_header):
    """PXP-32: a key scoped to exactly one action ('host:manage') authorizes
    that action but not a sibling action on the same resource
    ('host:remove'), unlike 'host:write' above."""
    app, c = app_client
    with app.state.sessionmaker() as db:
        host_id = seed_host_row(db).id
    raw = _create_key(c, csrf_header, scopes=["host:manage"]).json()["key"]
    c.cookies.clear()
    h = {"Authorization": f"Bearer {raw}"}
    r = c.patch(f"/api/v1/hosts/{host_id}",
               json={"node_shell_enabled": True}, headers=h)
    assert r.status_code == 200, r.text
    r2 = c.request("DELETE", f"/api/v1/hosts/{host_id}",
                   json={"confirm": "host-01"}, headers=h)
    assert r2.status_code == 403, r2.text


def test_write_scope_key_matches_matrix_resource_name(app_client, csrf_header):
    """Doc 04's example scope string is 'apps:write' (plural); the matrix
    resource is 'app' (singular), so the accepted/matched scope is 'app:write'."""
    app, c = app_client
    _, app_id = _seed_app(app)
    raw = _create_key(c, csrf_header, scopes=["app:write"]).json()["key"]
    c.cookies.clear()
    h = {"Authorization": f"Bearer {raw}"}
    r = c.post(f"/api/v1/apps/{app_id}/start", headers=h)
    assert r.status_code == 202, r.text
    r2 = c.post("/api/v1/schedules", json={"name": "s1", "job_kind": "app.update",
               "cron": "0 3 * * *"}, headers=h)
    assert r2.status_code == 403   # app:write does not cover the schedule resource
