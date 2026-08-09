"""app-side entitlement contract test (doc 09): the app must verify the
token -> leaf -> cert -> root chain built from the shared fixture exactly.
Fails loudly on drift, not at runtime.

The certificate is minted here rather than checked into the fixture because a
fixed exp would rot the suite. Its shape is not invented here either: this
builds what proxploy-api's sign_cert emits, and proxploy-api's own contract
test pins that against this same fixture. If the two drift, one of the two
tests fails.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt

FIXTURE = json.loads((Path(__file__).parent / "entitlement_token.fixture.json").read_text())


def _cert() -> str:
    now = datetime.now(tz=timezone.utc)
    claims = {"kid": FIXTURE["leaf_kid"], "pub": FIXTURE["leaf_public_body"],
              "iat": int(now.timestamp()), "nbf": int(now.timestamp()),
              "exp": int((now + timedelta(days=180)).timestamp())}
    return jwt.encode(claims, FIXTURE["root_private_key_pem"], algorithm="EdDSA",
                      headers={"kid": FIXTURE["root_kid"]})


def test_app_verifies_fixture_token_and_claims_roundtrip():
    from proxploy.entitlements.client import Entitlements

    token = jwt.encode(FIXTURE["claims"], FIXTURE["leaf_private_key_pem"],
                       algorithm="EdDSA", headers={"kid": FIXTURE["leaf_kid"]})
    ent = Entitlements(roots={FIXTURE["root_kid"]: FIXTURE["root_public_key_pem"]})
    claims = ent.verify(token, _cert())
    assert claims == FIXTURE["claims"]
    assert jwt.get_unverified_header(token) == {"alg": "EdDSA", "typ": "JWT",
                                                "kid": FIXTURE["leaf_kid"]}


def test_fixture_features_keys_are_known_flags():
    from proxploy.entitlements.registry import FLAG_KEYS

    assert set(FIXTURE["claims"]["features"]) <= set(FLAG_KEYS)
