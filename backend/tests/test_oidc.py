"""Service-level half of Task 10 (doc 10): discovery, PKCE, joserfc ID-token
validation, JIT provisioning, all driven against the in-process mock IdP
(tests/fakes/oidc.py), never a real network call. The route half (login/
callback/config endpoints, the full HTTP round-trip) is Task 11.

Also covers the gap-review addendum: services/authz.py is fail-closed on
team_members, so a JIT-provisioned user with no membership is a silent
lockout unless `oidc_default_role` is configured, see oidc.py's module
docstring and PENDING_APPROVAL_MESSAGE."""
import asyncio
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from proxploy.api.deps import default_team
from proxploy.models import AuditEvent, TeamMember, User
from proxploy.services import oidc
from proxploy.services.authn import hash_password
from tests.fakes.oidc import ISSUER, make_idp
from tests.support import make_job_app

REDIRECT_URI = "https://app.test/callback"


def _configure(app, db, *, default_role=None, default_team_slug=None, **idp_kwargs):
    """Wires the fake IdP as the transport seam, stores real oidc config, and
    (when asked) overrides the auto-provisioning settings introduced by the
    gap-review addendum. `default_team()` seeds the "default" team the same
    way every other bootstrap path in this codebase does, the JIT path
    itself must NOT auto-create a missing team (that's a config error), so
    tests that expect a role grant to succeed seed it explicitly here."""
    idp = make_idp(**idp_kwargs)
    app.state.oidc_transport = httpx.ASGITransport(app=idp)
    oidc.set_config(db, app.state.secretstore, ISSUER, "proxploy", "s3cret")
    default_team(db)
    overrides = {}
    if default_role is not None:
        overrides["oidc_default_role"] = default_role
    if default_team_slug is not None:
        overrides["oidc_default_team_slug"] = default_team_slug
    if overrides:
        app.state.settings = app.state.settings.model_copy(update=overrides)
    return idp


async def _login(app, db, *, nonce_override=None, redirect_uri=REDIRECT_URI):
    """Drives begin() -> the fake IdP's /authorize (standing in for the
    browser) -> complete(), returning whatever complete() returns or raises."""
    url = await oidc.begin(app, db, redirect_uri)
    q = parse_qs(urlparse(url).query)
    async with httpx.AsyncClient(transport=app.state.oidc_transport) as hc:
        r = await hc.get(f"{ISSUER}/authorize", params={
            "state": q["state"][0],
            "nonce": nonce_override or q["nonce"][0],
            "code_challenge": q["code_challenge"][0],
            "code_challenge_method": "S256",
            "redirect_uri": redirect_uri,
        })
    redirect = r.json()["redirect"]
    rq = parse_qs(urlparse(redirect).query)
    return await oidc.complete(app, db, state=rq["state"][0], code=rq["code"][0],
                               redirect_uri=redirect_uri)


def test_begin_url_carries_state_nonce_and_s256_pkce_challenge(tmp_path):
    async def scenario():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            _configure(app, db)
            url = await oidc.begin(app, db, REDIRECT_URI)
        q = parse_qs(urlparse(url).query)
        assert q["state"][0] and q["nonce"][0]
        assert q["code_challenge"][0]
        assert q["code_challenge_method"] == ["S256"]

    asyncio.run(scenario())


def test_complete_jit_provisions_the_configured_role_in_the_default_team(tmp_path):
    async def scenario():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            _configure(app, db, default_role="viewer", sub="alice-1",
                      email="alice@example.com")
            user = await _login(app, db)
            assert user.email == "alice@example.com"
            assert user.oidc_issuer == ISSUER and user.oidc_sub == "alice-1"
            assert user.password_hash is None
            assert user.is_active is True
            member = db.query(TeamMember).filter_by(user_id=user.id).one()
            assert member.role == "viewer"

    asyncio.run(scenario())


def test_second_login_reuses_the_same_user_row(tmp_path):
    async def scenario():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            _configure(app, db, default_role="viewer", sub="alice-1",
                      email="alice@example.com")
            first = await _login(app, db)
            second = await _login(app, db)
            assert first.id == second.id
            assert db.query(User).filter_by(oidc_sub="alice-1").count() == 1

    asyncio.run(scenario())


def test_tampered_state_is_rejected(tmp_path):
    async def scenario():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            _configure(app, db)
            with pytest.raises(oidc.OIDCError):
                await oidc.complete(app, db, state="not-a-real-state", code="x",
                                    redirect_uri=REDIRECT_URI)

    asyncio.run(scenario())


def test_wrong_nonce_id_token_is_rejected(tmp_path):
    async def scenario():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            _configure(app, db)
            with pytest.raises(oidc.OIDCError):
                await _login(app, db, nonce_override="attacker-supplied-nonce")

    asyncio.run(scenario())


def test_id_token_signed_by_a_different_key_is_rejected(tmp_path):
    from joserfc.jwk import RSAKey

    async def scenario():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            idp = _configure(app, db, default_role="viewer", sub="alice-1",
                             email="alice@example.com")
            await _login(app, db)  # warms the app's cached JWKS with idp's original key

            # Simulate the IdP rotating its signing key without the app's
            # cache having refreshed (kid is unchanged, so the "refetch once
            # on a kid miss" path never fires: this is a straight forgery,
            # not a rotation, and must be rejected, not silently retried).
            idp.state.key = RSAKey.generate_key(2048, {"alg": "RS256", "kid": "test-1"})
            with pytest.raises(oidc.OIDCError):
                await _login(app, db)

    asyncio.run(scenario())


def test_local_email_already_taken_refuses_silent_linking(tmp_path):
    async def scenario():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            db.add(User(email="alice@example.com", password_hash=hash_password("x" * 12)))
            db.commit()
            _configure(app, db, default_role="viewer", sub="alice-1",
                      email="alice@example.com")
            with pytest.raises(oidc.OIDCError):
                await _login(app, db)

    asyncio.run(scenario())


def test_missing_email_claim_is_an_honest_refusal(tmp_path):
    async def scenario():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            _configure(app, db, default_role="viewer", sub="alice-1", email=None)
            with pytest.raises(oidc.OIDCError):
                await _login(app, db)

    asyncio.run(scenario())


# --- Gap-review addendum: fail-closed default provisioning policy ----------

def test_configured_default_role_grants_exactly_that_roles_permissions(tmp_path):
    """services/authz.py is the real enforcer here (not a stand-in): the
    membership JIT provisioning writes must be visible to enforce() with
    both an allowed and a denied action, proving it is a real grant and not
    just a row that happens to exist."""
    from proxploy.services.authz import build_enforcer, enforce

    async def scenario():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            _configure(app, db, default_role="operator", sub="op-1", email="op@example.com")
            user = await _login(app, db)
            enforcer = build_enforcer(db)
            assert enforce(enforcer, db, user, "backup", "run") is True  # operator+
            assert enforce(enforcer, db, user, "settings", "manage") is False  # admin+

    asyncio.run(scenario())


def test_unconfigured_default_role_provisions_a_pending_inactive_account(tmp_path):
    async def scenario():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            _configure(app, db, sub="pending-1", email="pending@example.com")
            with pytest.raises(oidc.OIDCError, match="administrator"):
                await _login(app, db)

            user = db.query(User).filter_by(oidc_sub="pending-1").one()
            assert user.is_active is False
            assert db.query(TeamMember).filter_by(user_id=user.id).count() == 0
            audit = (db.query(AuditEvent)
                     .filter_by(action="oidc.jit_provision.pending").one())
            assert audit.actor_id == user.id and audit.target_id == user.id

    asyncio.run(scenario())


def test_unknown_configured_role_fails_loudly_and_provisions_nothing(tmp_path):
    async def scenario():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            _configure(app, db, default_role="superuser", sub="bad-1",
                      email="bad@example.com")
            with pytest.raises(RuntimeError, match="superuser"):
                await _login(app, db)
            assert db.query(User).filter_by(oidc_sub="bad-1").count() == 0

    asyncio.run(scenario())


# --- Route half (Task 11): the same protocol driven through real HTTP, over
# the app's actual /auth/oidc/* endpoints, against the same mock IdP. ---

import json as jsonlib

from fastapi.testclient import TestClient


def _configure_via_api(client, csrf_header, *, default_role=None, **idp_kwargs):
    """`_configure()`'s HTTP-route equivalent: PUT /auth/oidc/config as the
    authed owner (rather than calling oidc.set_config() directly), wiring the
    fake IdP as the transport seam the same way. oidc_default_role stays a
    Settings/env value (doc 10: no route exposes it), so it is still set
    directly on app.state.settings."""
    idp = make_idp(**idp_kwargs)
    client.app.state.oidc_transport = httpx.ASGITransport(app=idp)
    r = client.put("/api/v1/auth/oidc/config",
                   json={"issuer": ISSUER, "client_id": "proxploy", "client_secret": "s3cret"},
                   headers=csrf_header(client))
    assert r.status_code == 200, r.text
    with client.app.state.sessionmaker() as db:
        default_team(db)
    if default_role is not None:
        client.app.state.settings = client.app.state.settings.model_copy(
            update={"oidc_default_role": default_role})
    return idp


def _authorize_at_fake_idp(idp, q):
    with TestClient(idp) as idpc:
        ar = idpc.get("/authorize", params={
            "state": q["state"][0], "nonce": q["nonce"][0],
            "code_challenge": q["code_challenge"][0],
            "code_challenge_method": "S256",
            "redirect_uri": q["redirect_uri"][0]})
    assert ar.status_code == 200, ar.text
    return parse_qs(urlparse(ar.json()["redirect"]).query)


def test_oidc_config_get_never_returns_the_secret(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    _configure_via_api(client, csrf_header, default_role="viewer")
    r = client.get("/api/v1/auth/oidc/config", headers=csrf_header(client))
    assert r.status_code == 200
    body = r.json()
    assert body == {"issuer": ISSUER, "client_id": "proxploy", "configured": True}
    assert "s3cret" not in jsonlib.dumps(body) and "client_secret" not in body


def test_oidc_login_is_404_not_403_when_unconfigured(client):
    r = client.get("/api/v1/auth/oidc/login", follow_redirects=False)
    assert r.status_code == 404
    assert r.json()["error"] == "oidc_not_configured"


def test_oidc_login_and_callback_round_trip_creates_a_jit_session(client, csrf_header,
                                                                   bootstrap_admin):
    """The Task 11 round-trip, and the closest honest substitute for doc 10's
    DoD ("OIDC round-trips against a real Authelia") available on this
    machine: there is no browser and no live IdP here, so tests/fakes/oidc.py
    stands in for Authelia. What this genuinely proves, a real discovery
    document is fetched, S256 PKCE is enforced end-to-end (challenge stored
    at /authorize, verifier checked at /token), and a real RS256 ID token is
    verified against a real JWKS endpoint, is exactly what the app would do
    against Authelia; only the third-party implementation is absent.

    PUT config (owner) -> anonymous GET /login (307, real PKCE params in the
    Location) -> the fake IdP's /authorize (standing in for the browser) ->
    GET /callback -> session cookie + 307 to "/" -> GET /auth/me resolves the
    JIT-provisioned viewer."""
    bootstrap_admin(client)
    idp = _configure_via_api(client, csrf_header, default_role="viewer",
                             sub="alice-1", email="alice@example.com", name="Alice")
    client.cookies.delete("pp_session")  # the owner session must not matter below

    r = client.get("/api/v1/auth/oidc/login", follow_redirects=False)
    assert r.status_code == 307
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["code_challenge_method"] == ["S256"] and q["state"][0] and q["nonce"][0]

    rq = _authorize_at_fake_idp(idp, q)

    r = client.get("/api/v1/auth/oidc/callback",
                   params={"state": rq["state"][0], "code": rq["code"][0]},
                   follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/"
    assert "pp_session" in r.cookies

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "alice@example.com" and body["role"] == "viewer"

    with client.app.state.sessionmaker() as db:
        rows = db.query(AuditEvent).all()
        assert rows  # the walk below would be vacuously true over an empty table
        for row in rows:
            assert "s3cret" not in jsonlib.dumps(row.params or {})
        oidc_logins = [e for e in rows if e.action == "auth.login" and e.result == "ok"
                       and e.params and e.params.get("via") == "oidc"]
        assert len(oidc_logins) == 1


def test_oidc_bad_state_redirects_to_login_with_a_generic_error_and_no_session(
        client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    _configure_via_api(client, csrf_header, default_role="viewer")
    client.cookies.delete("pp_session")

    r = client.get("/api/v1/auth/oidc/callback",
                   params={"state": "not-a-real-state", "code": "x"},
                   follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/login?error=oidc"
    assert "pp_session" not in r.cookies

    with client.app.state.sessionmaker() as db:
        errs = (db.query(AuditEvent)
                .filter_by(action="auth.login", result="error").all())
        assert any(e.params and e.params.get("via") == "oidc" for e in errs)


def test_oidc_pending_approval_gets_its_own_redirect_and_grants_no_session(
        client, csrf_header, bootstrap_admin):
    """Global Constraint 1 of the Task 11 brief: an unconfigured
    oidc_default_role provisions a real, inactive, teamless user row (proven
    directly below) and services/oidc.py raises OIDCError(PENDING_APPROVAL_
    MESSAGE). The callback must not turn that into a session, a 500, or the
    same undifferentiated "?error=oidc" every other failure gets; it is not
    a login failure, it is a successful sign-up awaiting an administrator."""
    bootstrap_admin(client)
    idp = _configure_via_api(client, csrf_header, sub="pending-1",
                             email="pending@example.com")  # no default_role
    client.cookies.delete("pp_session")

    r = client.get("/api/v1/auth/oidc/login", follow_redirects=False)
    q = parse_qs(urlparse(r.headers["location"]).query)
    rq = _authorize_at_fake_idp(idp, q)

    r = client.get("/api/v1/auth/oidc/callback",
                   params={"state": rq["state"][0], "code": rq["code"][0]},
                   follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/login?error=oidc_pending"
    assert "pp_session" not in r.cookies

    with client.app.state.sessionmaker() as db:
        user = db.query(User).filter_by(email="pending@example.com").one()
        assert user.is_active is False
        assert db.query(TeamMember).filter_by(user_id=user.id).count() == 0


def test_oidc_config_delete_clears_it_back_to_unconfigured(client, csrf_header,
                                                            bootstrap_admin):
    bootstrap_admin(client)
    _configure_via_api(client, csrf_header, default_role="viewer")
    r = client.delete("/api/v1/auth/oidc/config", headers=csrf_header(client))
    assert r.status_code == 200
    r = client.get("/api/v1/auth/oidc/config", headers=csrf_header(client))
    assert r.json() == {"issuer": None, "client_id": None, "configured": False}
    r = client.get("/api/v1/auth/oidc/login", follow_redirects=False)
    assert r.status_code == 404


def test_oidc_config_routes_require_admin(client, csrf_header):
    """No session at all -> 401 (covered by test_route_auth_invariant.py);
    this checks the role floor specifically: a plain viewer must not manage
    OIDC config (doc 10 Task 11: authorize("settings", "manage"))."""
    client.post("/api/v1/users", json={"email": "owner@example.com",
                                       "password": "Correct-Horse-Battery-9"},
               headers=csrf_header(client))
    client.post("/api/v1/auth/login",
               json={"email": "owner@example.com", "password": "Correct-Horse-Battery-9"},
               headers=csrf_header(client))
    r = client.post("/api/v1/users", json={"email": "viewer@example.com",
                                           "password": "Correct-Horse-Battery-9",
                                           "role": "viewer"},
                    headers=csrf_header(client))
    assert r.status_code == 201
    client.post("/api/v1/auth/login",
               json={"email": "viewer@example.com", "password": "Correct-Horse-Battery-9"},
               headers=csrf_header(client))
    r = client.get("/api/v1/auth/oidc/config", headers=csrf_header(client))
    assert r.status_code == 403
