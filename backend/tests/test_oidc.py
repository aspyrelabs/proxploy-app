"""Service-level half of Task 10 (doc 10): discovery, PKCE, joserfc ID-token
validation, JIT provisioning — all driven against the in-process mock IdP
(tests/fakes/oidc.py), never a real network call. The route half (login/
callback/config endpoints, the full HTTP round-trip) is Task 11.

Also covers the gap-review addendum: services/authz.py is fail-closed on
team_members, so a JIT-provisioned user with no membership is a silent
lockout unless `oidc_default_role` is configured — see oidc.py's module
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
    way every other bootstrap path in this codebase does — the JIT path
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
            # on a kid miss" path never fires — this is a straight forgery,
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
