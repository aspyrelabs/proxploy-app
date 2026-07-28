"""Entitlements client (docs 00 §7, 07). OpenFeature-shaped; dormant = all-on.
Resolution: valid signed token within grace → its features claim; otherwise the
built-in default map. Unknown keys are False — fail closed (doc 07 §2)."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt

from proxploy.entitlements.registry import DEFAULT_FEATURES
from proxploy.models import EntitlementCache, utcnow

LEEWAY = timedelta(seconds=300)  # bounded clock-skew leeway (doc 07 §8)


class TokenInvalid(Exception):
    pass


def _ts(v: int) -> datetime:
    return datetime.fromtimestamp(v, tz=timezone.utc).replace(tzinfo=None)


@dataclass
class EntitlementStatus:
    tier: str
    source: str  # builtin | token
    expires_at: datetime | None = None
    grace_until: datetime | None = None
    in_grace: bool = False
    clock_skew: bool = False


class Entitlements:
    def __init__(self, public_keys: dict[str, str]):
        self._keys = public_keys
        self._features: dict[str, bool] = dict(DEFAULT_FEATURES)
        self._status = EntitlementStatus(tier="builtin", source="builtin")

    def verify(self, token: str) -> dict:
        """Signature + shape only. exp is OURS to interpret (grace window), so
        PyJWT's exp check is disabled and grace is enforced in apply_claims."""
        try:
            kid = jwt.get_unverified_header(token).get("kid")
            pem = self._keys.get(kid)
            if not pem:
                raise TokenInvalid(f"unknown signing key id {kid!r}")
            claims = jwt.decode(token, pem, algorithms=["EdDSA"],
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

    def reset_builtin(self) -> None:
        self._features = dict(DEFAULT_FEATURES)
        self._status = EntitlementStatus(tier="builtin", source="builtin")

    def load(self, db, secretstore) -> None:
        row = db.get(EntitlementCache, 1)
        if not row or not row.token:
            self.reset_builtin()
            return
        try:
            token = secretstore.decrypt(row.token.encode()).decode()
            self.apply_claims(self.verify(token))
            row.last_verified_at = utcnow()
            db.commit()
        except (TokenInvalid, Exception):
            # doc 07 §8: past grace / bad cache → free-tier floor, never a bricked install
            self.reset_builtin()

    def enabled(self, key: str) -> bool:
        return self._features.get(key, False)

    def snapshot(self) -> dict[str, bool]:
        return dict(self._features)

    def status(self) -> EntitlementStatus:
        return self._status
