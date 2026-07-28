"""app-side entitlement contract test (doc 09): the app must deserialize a token
built from the shared fixture exactly. Fails loudly on drift, not at runtime."""
import json
from pathlib import Path

import jwt

FIXTURE = json.loads((Path(__file__).parent / "entitlement_token.fixture.json").read_text())


def test_app_verifies_fixture_token_and_claims_roundtrip():
    from proxploy.entitlements.client import Entitlements

    token = jwt.encode(FIXTURE["claims"], FIXTURE["private_key_pem"],
                       algorithm="EdDSA", headers={"kid": FIXTURE["kid"]})
    ent = Entitlements(public_keys={FIXTURE["kid"]: FIXTURE["public_key_pem"]})
    claims = ent.verify(token)
    assert claims == FIXTURE["claims"]
    assert jwt.get_unverified_header(token) == {"alg": "EdDSA", "typ": "JWT",
                                                "kid": FIXTURE["kid"]}


def test_fixture_features_keys_are_known_flags():
    from proxploy.entitlements.registry import FLAG_KEYS

    assert set(FIXTURE["claims"]["features"]) <= set(FLAG_KEYS)
