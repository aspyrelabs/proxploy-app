"""OIDC authorization-code+PKCE flow (doc 08 §6, doc 10 Task 10).

`authlib.jose` is deprecated at 1.7 ("use joserfc instead"), every byte of ID
token verification here goes through joserfc, never authlib.jose. Authlib
(OAuth2Client/AsyncOAuth2Client) is used only for the mechanical parts of the
protocol: building the authorization URL and doing the code/verifier exchange
over httpx. A signature/claims/nonce failure is always an `OIDCError`, never a
500 and never a silently-accepted token, see `_verify_id_token`.

JIT provisioning (`_jit_provision`) does not treat an IdP's user population as
automatically the application's authorized population: auto-admitting every
identity the directory happens to contain is the accidental-access failure
mode this deliberately avoids. `settings.oidc_default_role` unset (the
default) provisions the account with no team membership and `is_active=False`
a deny-with-an-explanation, not a silent lockout, since `is_active` is the
same gate `services/authn.py` and the password login path already check.
Setting it opts into auto-granting that one role in `oidc_default_team_slug`
instead; both are validated at first use and fail loudly (never silently
fall back) on a bad value, matching this codebase's fail-closed posture for
casbin/RBAC (`services/authz.py`, `api/deps.py::authorize`).
"""
from __future__ import annotations

import secrets
from datetime import timedelta

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client, OAuth2Client
from joserfc import jwt
from joserfc.errors import InvalidKeyIdError, JoseError
from joserfc.jwk import KeySet
from joserfc.jwt import JWTClaimsRegistry

from proxploy.api.deps import ROLE_ORDER
from proxploy.models import AppSetting, Team, TeamMember, User, utcnow
from proxploy.services.audit import write_audit
from proxploy.services.settings import get_setting, set_setting

STATE_TTL_S = 600  # doc 10 Task 10: single-use, 10-minute expiring state store

# Gap review finding: api/auth.py's user-creation route was, before this,
# the ONLY code path in the tree that ever minted a team_members row. A JIT-
# provisioned OIDC user with none is invisible to services/authz.py: every
# enforce() call denies (fail-closed by construction): which is a silent
# lockout with no explanation, not a security property. This message is what
# that lockout now says instead, and it is the exact text both the pending-
# after-creation path and the deactivated-account path raise below.
PENDING_APPROVAL_MESSAGE = (
    "account awaits administrator approval: no oidc_default_role is "
    "configured, so this OIDC sign-in created an account with no team "
    "membership and is_active=False; an administrator must activate it "
    "and assign a team role before it can sign in"
)


class OIDCError(Exception):
    """Raised on any discovery/exchange/validation/provisioning failure. The
    route layer (Task 11) turns every one of these into the same generic
    redirect, the message here is for logs/tests, never sent to the browser."""


# --- Config (settings-backed; client_secret Fernet-encrypted) --------------

def config(db, secretstore) -> dict | None:
    issuer = get_setting(db, "oidc.issuer")
    client_id = get_setting(db, "oidc.client_id")
    enc = get_setting(db, "oidc.client_secret.enc")
    if not (issuer and client_id and enc):
        return None
    client_secret = secretstore.decrypt(enc.encode()).decode()
    return {"issuer": issuer, "client_id": client_id, "client_secret": client_secret}


def set_config(db, secretstore, issuer: str, client_id: str, client_secret: str) -> None:
    enc, _key_version = secretstore.encrypt(client_secret.encode())
    set_setting(db, "oidc.issuer", issuer)
    set_setting(db, "oidc.client_id", client_id)
    set_setting(db, "oidc.client_secret.enc", enc.decode())


def clear_config(db) -> None:
    (db.query(AppSetting)
     .filter(AppSetting.key.in_(("oidc.issuer", "oidc.client_id", "oidc.client_secret.enc")))
     .delete(synchronize_session=False))
    db.commit()


def configured(db) -> bool:
    """Cheap existence check (no decrypt) for routes that only need to know
    whether OIDC is set up, not the secret itself; Task 11's login gate and
    /meta/onboarding's `oidc` flag both go through this instead of `config()`."""
    return bool(get_setting(db, "oidc.issuer") and get_setting(db, "oidc.client_id")
                and get_setting(db, "oidc.client_secret.enc"))


# --- Discovery / JWKS, cached on app.state keyed by issuer ------------------

def _cache(app, attr: str) -> dict:
    cache = getattr(app.state, attr, None)
    if cache is None:
        cache = {}
        setattr(app.state, attr, cache)
    return cache


async def _fetch_json(app, url: str) -> dict:
    transport = getattr(app.state, "oidc_transport", None)  # test seam; None = real network
    try:
        async with httpx.AsyncClient(transport=transport, timeout=10) as hc:
            r = await hc.get(url)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        raise OIDCError(f"GET {url} failed: {e}") from e


async def _metadata(app, issuer: str) -> dict:
    cache = _cache(app, "oidc_metadata_cache")
    if issuer not in cache:
        cache[issuer] = await _fetch_json(app, f"{issuer}/.well-known/openid-configuration")
    return cache[issuer]


async def _jwks(app, issuer: str, metadata: dict, *, refresh: bool = False) -> dict:
    cache = _cache(app, "oidc_jwks_cache")
    if refresh or issuer not in cache:
        cache[issuer] = await _fetch_json(app, metadata["jwks_uri"])
    return cache[issuer]


# --- State store: {state: (code_verifier, nonce, expires_at)} --------------

def _states(app) -> dict:
    states = getattr(app.state, "oidc_states", None)
    if states is None:
        states = {}
        app.state.oidc_states = states
    now = utcnow()
    # ponytail: single in-memory dict, fine for the single-process deployment
    # this phase targets; a multi-worker deploy needs a shared store (Redis/db
    # row) instead: same shape of note as the Task 9 pending-TOTP store.
    for k in [k for k, (_, _, exp) in states.items() if exp < now]:
        del states[k]
    return states


# --- begin() / complete() ---------------------------------------------------

async def begin(app, db, redirect_uri: str) -> str:
    cfg = config(db, app.state.secretstore)
    if not cfg:
        raise OIDCError("oidc not configured")
    metadata = await _metadata(app, cfg["issuer"])
    verifier = secrets.token_urlsafe(64)
    nonce = secrets.token_urlsafe(24)
    client = OAuth2Client(cfg["client_id"], cfg["client_secret"],
                          redirect_uri=redirect_uri, code_challenge_method="S256")
    # TRAP (Global Constraints): code_challenge/code_challenge_method only
    # appear in the URL when code_verifier= is passed here.
    url, state = client.create_authorization_url(
        metadata["authorization_endpoint"], nonce=nonce, code_verifier=verifier,
        scope="openid email profile")
    _states(app)[state] = (verifier, nonce, utcnow() + timedelta(seconds=STATE_TTL_S))
    return url


async def complete(app, db, state: str, code: str, redirect_uri: str) -> User:
    entry = _states(app).pop(state, None)  # single-use: popped whether or not it validates
    if entry is None:
        raise OIDCError("invalid or expired state")
    verifier, nonce, _expires_at = entry

    cfg = config(db, app.state.secretstore)
    if not cfg:
        raise OIDCError("oidc not configured")
    metadata = await _metadata(app, cfg["issuer"])

    transport = getattr(app.state, "oidc_transport", None)
    async with AsyncOAuth2Client(cfg["client_id"], cfg["client_secret"],
                                 redirect_uri=redirect_uri, transport=transport,
                                 timeout=10) as ac:
        try:
            token = await ac.fetch_token(metadata["token_endpoint"], code=code,
                                         code_verifier=verifier, state=state)
        except httpx.HTTPError as e:
            raise OIDCError(f"token exchange failed: {e}") from e
    id_token = token.get("id_token")
    if not id_token:
        raise OIDCError("token endpoint returned no id_token")

    claims = await _verify_id_token(app, cfg, metadata, id_token, nonce)
    return _jit_provision(app, db, cfg["issuer"], claims)


async def _verify_id_token(app, cfg: dict, metadata: dict, id_token: str, nonce: str) -> dict:
    """Signature (joserfc, against the IdP's real JWKS) + iss/aud/exp/sub
    (JWTClaimsRegistry) + nonce (manual, joserfc has no built-in claim for
    it). Any failure anywhere in this chain is OIDCError: never a leaked 500,
    never a claim trusted before it is verified."""
    jwks = await _jwks(app, cfg["issuer"], metadata)
    try:
        claims = jwt.decode(id_token, KeySet.import_key_set(jwks)).claims
    except InvalidKeyIdError:
        # The one legitimate retry: the IdP rotated to a kid we haven't seen
        # yet. A signature that fails against a *known* kid (below) is a
        # forgery, not a rotation, and must never trigger this retry: that
        # would let a stale-cache-adjacent attack just get a free do-over.
        jwks = await _jwks(app, cfg["issuer"], metadata, refresh=True)
        try:
            claims = jwt.decode(id_token, KeySet.import_key_set(jwks)).claims
        except JoseError as e:
            raise OIDCError(f"id_token signature invalid: {e}") from e
    except JoseError as e:
        raise OIDCError(f"id_token signature invalid: {e}") from e

    registry = JWTClaimsRegistry(
        iss={"essential": True, "value": cfg["issuer"]},
        aud={"essential": True, "value": cfg["client_id"]},
        exp={"essential": True}, sub={"essential": True})
    try:
        registry.validate(claims)
    except JoseError as e:
        raise OIDCError(f"id_token claims invalid: {e}") from e
    if claims.get("nonce") != nonce:
        raise OIDCError("id_token nonce mismatch")
    return claims


def _jit_provision(app, db, issuer: str, claims: dict) -> User:
    sub = claims["sub"]
    user = db.query(User).filter_by(oidc_issuer=issuer, oidc_sub=sub).one_or_none()
    if user is None:
        user = _create_user(app, db, issuer, sub, claims)
    if not user.is_active:
        raise OIDCError(PENDING_APPROVAL_MESSAGE)
    return user


def _create_user(app, db, issuer: str, sub: str, claims: dict) -> User:
    email = claims.get("email")
    if not email:
        raise OIDCError("IdP returned no email claim")
    existing = db.query(User).filter_by(email=email).one_or_none()
    if existing is not None:
        # No silent account linking: a local (password) account owning this
        # email is a takeover vector if OIDC just annexes it.
        raise OIDCError("account exists with password login")

    settings = app.state.settings
    role = settings.oidc_default_role
    if role is None:
        # Deny-with-an-explanation default (see module docstring): mint the
        # user row only, no membership. Fail-closed casbin means this account
        # already has zero permissions the moment it exists: is_active=False
        # additionally blocks even issuing it a session.
        user = User(email=email, display_name=claims.get("name"), oidc_issuer=issuer,
                   oidc_sub=sub, password_hash=None, is_active=False)
        db.add(user)
        db.commit()
        write_audit(db, actor_type="user", actor_id=user.id, action="oidc.jit_provision.pending",
                    target_type="user", target_id=user.id, params={"email": email})
        return user

    if role not in ROLE_ORDER:
        # Loud, not a fallback: an operator who typos oidc_default_role must
        # not get a working-but-wrong grant, and must not get a silently
        # unprovisioned account either: nothing is written at all.
        raise RuntimeError(
            f"oidc_default_role={role!r} is not a known role; must be one of "
            f"{sorted(ROLE_ORDER)}")
    team = db.query(Team).filter_by(slug=settings.oidc_default_team_slug).one_or_none()
    if team is None:
        raise RuntimeError(
            f"oidc_default_team_slug={settings.oidc_default_team_slug!r} does not "
            "name an existing team")

    user = User(email=email, display_name=claims.get("name"), oidc_issuer=issuer,
               oidc_sub=sub, password_hash=None)
    db.add(user)
    db.flush()  # assigns user.id inside the still-open transaction, the
                # membership below commits in the SAME transaction, so a crash
                # between the two can never strand a permissionless user row.
    db.add(TeamMember(team_id=team.id, user_id=user.id, role=role))
    db.commit()
    enforcer = getattr(app.state, "authz", None)  # unset only in bare service-level tests
    if enforcer is not None:
        from proxploy.services.authz import sync_user
        sync_user(enforcer, db, user.id)
    return user
