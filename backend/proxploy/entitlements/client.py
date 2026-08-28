"""Entitlements client (docs 00 §7, 07). OpenFeature-shaped; dormant = all-on.
Resolution: valid signed token within grace → its features claim; otherwise the
built-in default map. Unknown keys are False, fail closed (doc 07 §2).

Trust chain: token -> leaf key -> certificate -> bundled ROOT key. The app
never trusts a leaf directly; it trusts a small set of roots (entitlements/keys.py)
and each root's only job is signing certificates that vouch for a leaf. See
verify_cert() for why that makes the chain depth-1 by construction rather
than by a flag.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt

from proxploy.entitlements.registry import FREE_FEATURES
from proxploy.models import EntitlementCache, utcnow
from proxploy.pubkey import load_public_key, to_pem

LEEWAY = timedelta(seconds=300)  # clock-skew leeway for a token's grace_until/iat (doc 07 §8)
# 24h, not LEEWAY's 300s: leeway scales to the window it guards — a cert's
# signer is rotated far less often than a token.
CERT_LEEWAY = timedelta(hours=24)  # clock-skew leeway for a cert's nbf/exp


def _ts(v: int) -> datetime:
    return datetime.fromtimestamp(v, tz=timezone.utc).replace(tzinfo=None)


class TokenInvalid(Exception):
    """Any entitlement-token or signing-certificate verification failure.

    One type, not six: every caller (load()'s fall back to the builtin map,
    apply_new_token's 502) takes the identical action no matter which of the
    six cases in verify()/verify_cert() raised it. The distinguishing
    information travels in the message and in `clock_skew` (set only when
    the failure looks like a wrong local clock rather than a bad license, so
    a caller can render a different hint).
    # ponytail: split into a real exception hierarchy if the UI ever needs
    # to branch on cause instead of just displaying the message.
    """
    def __init__(self, message: str, *, clock_skew: bool = False):
        super().__init__(message)
        self.clock_skew = clock_skew


def verify_cert(cert: str | None, roots: dict[str, str]) -> tuple[str, str]:
    """Verify a signing certificate against the bundled ROOT map.

    Returns (leaf_kid, leaf_pem): the leaf key id and PEM the cert vouches
    for, so verify() can check a token was signed by exactly that key.

    Depth is 1 by construction, not by a flag: `roots` holds only root public
    keys (entitlements/keys.py), never leaf keys, and this function resolves
    the cert's signer ONLY by looking its header kid up in `roots`. A leaf
    key is therefore never a valid entry to find here, so a leaf can never
    sign a cert that verifies as anything other than "unknown root key id".
    There is no CA:TRUE-equivalent bit to get wrong because there is no code
    path that would ever consult a leaf as a potential signer.
    """
    if not cert:
        raise TokenInvalid("response carried no signing certificate")
    try:
        root_kid = jwt.get_unverified_header(cert).get("kid")
    except jwt.PyJWTError as e:
        raise TokenInvalid(f"malformed signing certificate: {type(e).__name__}") from e
    root_pem = roots.get(root_kid)
    if not root_pem:
        raise TokenInvalid(f"unknown root key id {root_kid!r}")
    try:
        claims = jwt.decode(cert, root_pem, algorithms=["EdDSA"], leeway=CERT_LEEWAY)
    except jwt.ImmatureSignatureError as e:
        nbf = _ts(jwt.decode(cert, options={"verify_signature": False})["nbf"])
        raise TokenInvalid(f"signing certificate not valid until {nbf.isoformat()}",
                           clock_skew=True) from e
    except jwt.ExpiredSignatureError as e:
        exp = _ts(jwt.decode(cert, options={"verify_signature": False})["exp"])
        raise TokenInvalid(f"signing certificate expired at {exp.isoformat()}") from e
    except jwt.PyJWTError as e:
        raise TokenInvalid(f"malformed signing certificate: {type(e).__name__}") from e
    leaf_kid = claims.get("kid")
    if leaf_kid is None:
        raise TokenInvalid("malformed signing certificate: KeyError")
    pub = claims.get("pub")
    if pub is None:
        raise TokenInvalid("certificate missing claim 'pub'")
    try:
        leaf_pem = to_pem(load_public_key(pub))
    except (ValueError, TypeError) as e:
        raise TokenInvalid(f"malformed signing certificate: {type(e).__name__}") from e
    return leaf_kid, leaf_pem


@dataclass
class EntitlementStatus:
    tier: str
    source: str  # builtin | token
    expires_at: datetime | None = None
    grace_until: datetime | None = None
    in_grace: bool = False
    clock_skew: bool = False
    reason: str | None = None  # why a fallback to builtin happened, if any


class Entitlements:
    def __init__(self, roots: dict[str, str],
                 baseline: dict[str, bool] | None = None):
        self._roots = roots
        # The floor this install falls back to with no token, a bad one, or one
        # past grace. Defaults to the free/Homelab map; registry.DEV_FEATURES is
        # the explicit opt-in for local work with every gate open. Never derive
        # this from an env setting: a dev box that silently runs all-on is how
        # denied branches go untested until a customer finds them.
        self._baseline = dict(baseline if baseline is not None else FREE_FEATURES)
        self._features: dict[str, bool] = dict(self._baseline)
        self._status = EntitlementStatus(tier="builtin", source="builtin")
        self.refresh_error: str | None = None

    def verify(self, token: str, cert: str | None) -> dict:
        """Signature + shape only. exp is OURS to interpret (grace window), so
        PyJWT's exp check is disabled and grace is enforced in apply_claims.

        Six failure cases, all raising TokenInvalid, checked in this order:
          1. cert missing (verify_cert)
          2. unknown root kid, looked up before any decode (verify_cert)
          3. malformed cert: bad JWS, bad signature, missing kid/pub, pub not
             a key (verify_cert)
          4. cert not yet valid, past CERT_LEEWAY (verify_cert, sets clock_skew)
          5. cert expired, past CERT_LEEWAY (verify_cert)
          6. token kid != the cert's certified leaf kid, checked BEFORE the
             token's own signature is verified, so a mismatched kid reports
             as itself rather than as a signature failure against the wrong
             key
        """
        leaf_kid, leaf_pem = verify_cert(cert, self._roots)
        try:
            token_kid = jwt.get_unverified_header(token).get("kid")
        except jwt.PyJWTError as e:
            raise TokenInvalid(str(e)) from e
        if token_kid != leaf_kid:
            raise TokenInvalid(f"token key id {token_kid!r} is not the "
                               f"certified key id {leaf_kid!r}")
        try:
            claims = jwt.decode(token, leaf_pem, algorithms=["EdDSA"],
                                options={"verify_exp": False})
        except jwt.PyJWTError as e:
            raise TokenInvalid(str(e)) from e
        for req in ("sub", "tier", "features", "iat", "exp", "grace_until"):
            if req not in claims:
                raise TokenInvalid(f"missing claim {req}")
        return claims

    def apply_claims(self, claims: dict) -> None:
        now = utcnow()
        grace_until = _ts(claims["grace_until"])
        if now > grace_until + LEEWAY:
            raise TokenInvalid("token past grace_until")
        exp = _ts(claims["exp"])
        self._features = {k: bool(v) for k, v in claims["features"].items()}
        self._status = EntitlementStatus(
            tier=claims["tier"], source="token", expires_at=exp,
            grace_until=grace_until, in_grace=now > exp,
            clock_skew=_ts(claims["iat"]) > now + LEEWAY)

    def reset_builtin(self, reason: str | None = None, clock_skew: bool = False) -> None:
        self._features = dict(self._baseline)
        self._status = EntitlementStatus(tier="builtin", source="builtin",
                                         reason=reason, clock_skew=clock_skew)

    def revalidation_lapsed(self, db, max_offline: timedelta | None) -> bool:
        if max_offline is None:
            return False
        row = db.get(EntitlementCache, 1)
        if not row or not row.token:
            return False
        since = row.fetched_at or row.created_at
        if since is None or utcnow() - since <= max_offline:
            return False
        self.reset_builtin(
            reason=f"licence not revalidated with the licence server since "
                   f"{since.isoformat()}, past the "
                   f"{max_offline.days}-day revalidation limit")
        return True

    def load(self, db, secretstore, max_offline: timedelta | None = None) -> None:
        row = db.get(EntitlementCache, 1)
        if not row or not row.token:
            self.reset_builtin()
            return
        if self.revalidation_lapsed(db, max_offline):
            return
        try:
            token = secretstore.decrypt(row.token.encode()).decode()
            self.apply_claims(self.verify(token, row.cert))
            row.last_verified_at = utcnow()
            db.commit()
        except TokenInvalid as e:
            # doc 07 §8: past grace / bad cache / unverifiable cert -> free
            # tier floor, never a bricked install. This is the deliberate
            # cost of chain verification: a still-in-grace cached token
            # cannot outlive the cert that proves who signed it (see
            # test_expired_cert_ends_a_cached_token_inside_grace).
            self.reset_builtin(reason=str(e), clock_skew=e.clock_skew)
        except Exception:
            self.reset_builtin()

    def enabled(self, key: str) -> bool:
        return self._features.get(key, False)

    def snapshot(self) -> dict[str, bool]:
        return dict(self._features)

    def status(self) -> EntitlementStatus:
        return self._status
