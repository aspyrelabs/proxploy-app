from dataclasses import dataclass
from datetime import timedelta

import pytest


@dataclass
class Chain:
    """A freshly-minted root + leaf keypair, and a cert (signed by the root,
    naming the leaf) that a test can hand to Entitlements/verify_cert. Not
    the real chain shape shipped to installs (that's keys.py's bundled root
    plus proxploy-api's signing), just enough of it to exercise
    entitlements/client.py in isolation."""
    root_kid: str
    root_pub: str
    root_priv: str
    leaf_kid: str
    leaf_priv: str
    cert: str


def _keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(serialization.Encoding.PEM,
                                  serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()).decode()
    pub_pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    body = "".join(l for l in pub_pem.splitlines() if not l.startswith("-----"))
    return priv_pem, pub_pem, body


def _mint_cert(root_priv: str, root_kid: str, claims: dict) -> str:
    import jwt

    return jwt.encode(claims, root_priv, algorithm="EdDSA", headers={"kid": root_kid})


def _chain(*, root_kid="root1", leaf_kid="leaf1", nbf_delta_h=-1, exp_delta_h=24 * 30) -> Chain:
    """Root pub (to trust), leaf priv (to sign a token with) and a cert tying
    the two together, signed by the root and naming the leaf's kid/pub."""
    from proxploy.models import utcnow

    root_priv, root_pub, _ = _keypair()
    leaf_priv, _, leaf_body = _keypair()

    now = utcnow()
    claims = {"kid": leaf_kid, "pub": leaf_body,
              "iat": int(now.timestamp()),
              "nbf": int((now + timedelta(hours=nbf_delta_h)).timestamp()),
              "exp": int((now + timedelta(hours=exp_delta_h)).timestamp())}
    cert = _mint_cert(root_priv, root_kid, claims)
    return Chain(root_kid, root_pub, root_priv, leaf_kid, leaf_priv, cert)


def _token(priv_pem, *, kid="leaf1", features=None, exp_delta_h=72, grace_delta_d=30):
    import jwt

    from proxploy.models import utcnow

    now = utcnow()
    claims = {"sub": "lic_x", "tier": "pro",
              "features": features if features is not None else {"hosts.multi": True},
              "iat": int(now.timestamp()),
              "exp": int((now + timedelta(hours=exp_delta_h)).timestamp()),
              "grace_until": int((now + timedelta(days=grace_delta_d)).timestamp())}
    return jwt.encode(claims, priv_pem, algorithm="EdDSA", headers={"kid": kid})


def test_registry_is_exactly_82_all_on():
    from proxploy.entitlements.registry import DEFAULT_FEATURES, FLAG_KEYS

    assert len(FLAG_KEYS) == 87 and len(set(FLAG_KEYS)) == 87
    for probe in ("hosts.multi", "store.install", "jobs.engine", "ent.client",
                  "platform.error_report", "terminal.node"):
        assert probe in FLAG_KEYS
    assert DEFAULT_FEATURES == {k: True for k in FLAG_KEYS}


def test_builtin_path_unknown_key_fails_closed():
    from proxploy.entitlements.client import Entitlements

    ent = Entitlements(roots={})
    assert ent.enabled("hosts.multi") is True
    assert ent.enabled("not.a.flag") is False
    assert ent.status().source == "builtin"


def test_full_chain_verifies():
    from proxploy.entitlements.client import Entitlements, TokenInvalid

    c = _chain()
    ent = Entitlements(roots={c.root_kid: c.root_pub})
    ent.apply_claims(ent.verify(
        _token(c.leaf_priv, kid=c.leaf_kid,
              features={"hosts.multi": False, "apps.list": True}),
        c.cert))
    assert ent.enabled("apps.list") is True
    assert ent.enabled("hosts.multi") is False       # token is authoritative
    assert ent.enabled("store.install") is False     # unknown-to-token: fail closed
    assert ent.status().source == "token"

    # past exp, inside grace: still honored, flagged in status (doc 07 §8)
    ent.apply_claims(ent.verify(_token(c.leaf_priv, kid=c.leaf_kid, exp_delta_h=-1), c.cert))
    assert ent.status().in_grace is True

    # past grace: dead
    with pytest.raises(TokenInvalid):
        ent.apply_claims(ent.verify(
            _token(c.leaf_priv, kid=c.leaf_kid, exp_delta_h=-2000, grace_delta_d=-1), c.cert))


def test_cert_expired_is_rejected():
    from proxploy.entitlements.client import TokenInvalid, verify_cert

    c = _chain(exp_delta_h=-48)  # 2 days ago, well past CERT_LEEWAY
    with pytest.raises(TokenInvalid, match="signing certificate expired"):
        verify_cert(c.cert, {c.root_kid: c.root_pub})


def test_cert_just_expired_inside_leeway_is_accepted():
    from proxploy.entitlements.client import verify_cert

    c = _chain(exp_delta_h=-1)  # 1 hour ago, inside CERT_LEEWAY (24h)
    leaf_kid, leaf_pem = verify_cert(c.cert, {c.root_kid: c.root_pub})
    assert leaf_kid == c.leaf_kid


def test_cert_not_yet_valid_is_rejected_and_flags_clock_skew():
    from proxploy.entitlements.client import TokenInvalid, verify_cert

    c = _chain(nbf_delta_h=48, exp_delta_h=24 * 30)  # nbf 2 days ahead
    with pytest.raises(TokenInvalid) as ei:
        verify_cert(c.cert, {c.root_kid: c.root_pub})
    assert "not valid until" in str(ei.value)
    assert ei.value.clock_skew is True


def test_unknown_root_kid_is_rejected():
    from proxploy.entitlements.client import TokenInvalid, verify_cert

    c = _chain(root_kid="root1")
    with pytest.raises(TokenInvalid, match="unknown root key id 'root1'"):
        verify_cert(c.cert, {"some-other-root": c.root_pub})


def test_token_kid_must_match_cert_kid():
    from proxploy.entitlements.client import Entitlements, TokenInvalid

    c = _chain()
    ent = Entitlements(roots={c.root_kid: c.root_pub})

    # (a) signed by the certified leaf, but the header claims a different
    # kid: must fail on identity, before the token signature is ever checked.
    mislabeled = _token(c.leaf_priv, kid="not-" + c.leaf_kid)
    with pytest.raises(TokenInvalid, match="is not the certified key id"):
        ent.verify(mislabeled, c.cert)

    # (b) signed by a DIFFERENT leaf, while claiming the certified kid: the
    # identity check passes (kid matches), so this must fail on the token's
    # signature instead.
    imposter = _chain()
    forged = _token(imposter.leaf_priv, kid=c.leaf_kid)
    with pytest.raises(TokenInvalid) as ei:
        ent.verify(forged, c.cert)
    assert "is not the certified key id" not in str(ei.value)


@pytest.mark.parametrize("case,expect_match", [
    ("garbage", "malformed signing certificate"),
    # missing `pub` gets its own explicit message, not the generic one:
    ("missing_pub", "certificate missing claim 'pub'"),
    ("bad_pub", "malformed signing certificate"),
    ("wrong_root", "malformed signing certificate"),
])
def test_malformed_cert_is_rejected(case, expect_match):
    from proxploy.models import utcnow
    from proxploy.entitlements.client import TokenInvalid, verify_cert

    c = _chain()
    roots = {c.root_kid: c.root_pub}
    now = int(utcnow().timestamp())

    if case == "garbage":
        bad_cert = "this-is-not-a-jwt"
    elif case == "missing_pub":
        claims = {"kid": c.leaf_kid, "iat": now, "nbf": now - 3600, "exp": now + 3600}
        bad_cert = _mint_cert(c.root_priv, c.root_kid, claims)
    elif case == "bad_pub":
        claims = {"kid": c.leaf_kid, "pub": "not-a-real-key",
                  "iat": now, "nbf": now - 3600, "exp": now + 3600}
        bad_cert = _mint_cert(c.root_priv, c.root_kid, claims)
    else:  # wrong_root: header names the real root's kid, signed by a different key
        impostor = _chain(root_kid=c.root_kid)
        bad_cert = impostor.cert

    with pytest.raises(TokenInvalid, match=expect_match):
        verify_cert(bad_cert, roots)


@pytest.mark.parametrize("cert", [None, ""])
def test_missing_cert_is_rejected(cert):
    from proxploy.entitlements.client import TokenInvalid, verify_cert

    with pytest.raises(TokenInvalid, match="no signing certificate"):
        verify_cert(cert, {})


def test_a_leaf_cannot_sign_a_cert():
    """Chain depth is 1 by construction: roots holds only root keys, never
    leaf keys, so a cert signed by a leaf can never resolve a signer. Pins
    the exact thing a future "just make roots and leaves the same map"
    refactor would quietly break."""
    from proxploy.models import utcnow
    from proxploy.entitlements.client import TokenInvalid, verify_cert

    c = _chain()
    now = int(utcnow().timestamp())
    claims = {"kid": "leaf2", "pub": c.root_pub,  # pub content is irrelevant here
              "iat": now, "nbf": now - 3600, "exp": now + 3600}
    forged = _mint_cert(c.leaf_priv, c.leaf_kid, claims)  # signed by the LEAF
    with pytest.raises(TokenInvalid, match="unknown root key id"):
        verify_cert(forged, {c.root_kid: c.root_pub})


def test_expired_cert_ends_a_cached_token_inside_grace(tmp_path):
    """A cert has to keep re-proving the leaf that signed a cached token: an
    in-grace token cannot outlive the cert that vouches for its signer. This
    is a deliberate cost (see client.py::load), pinned here so a later
    "just skip cert re-verification on the cached path" change fails loudly."""
    from proxploy.entitlements.client import Entitlements
    from proxploy.models import EntitlementCache
    from proxploy.secretstore import SecretStore
    from tests.support import make_db

    db = make_db(tmp_path)
    kf = tmp_path / "master.key"
    SecretStore.ensure_key_file(kf, db_file_exists=False)
    ss = SecretStore(kf)

    c = _chain(exp_delta_h=-1000)  # cert itself long past CERT_LEEWAY
    token = _token(c.leaf_priv, kid=c.leaf_kid, exp_delta_h=-1, grace_delta_d=30)  # token: in grace
    enc, _ = ss.encrypt(token.encode())
    db.add(EntitlementCache(id=1, token=enc.decode(), cert=c.cert, tier="pro"))
    db.commit()

    ent = Entitlements(roots={c.root_kid: c.root_pub})
    ent.load(db, ss)
    assert ent.status().source == "builtin"


def test_cached_chain_survives_a_restart_with_no_network(tmp_path):
    from proxploy.entitlements.client import Entitlements
    from proxploy.models import EntitlementCache
    from proxploy.secretstore import SecretStore
    from tests.support import make_db

    db = make_db(tmp_path)
    kf = tmp_path / "master.key"
    SecretStore.ensure_key_file(kf, db_file_exists=False)
    ss = SecretStore(kf)

    c = _chain()
    token = _token(c.leaf_priv, kid=c.leaf_kid, features={"hosts.multi": True})
    enc, _ = ss.encrypt(token.encode())
    db.add(EntitlementCache(id=1, token=enc.decode(), cert=c.cert, tier="pro"))
    db.commit()

    ent = Entitlements(roots={c.root_kid: c.root_pub})
    ent.load(db, ss)  # no HTTP client involved anywhere in this path
    assert ent.status().source == "token"
    assert ent.enabled("hosts.multi") is True


def test_entitlements_endpoint(client, csrf_header, bootstrap_admin):
    assert client.get("/api/v1/entitlements").status_code == 401
    bootstrap_admin(client)
    r = client.get("/api/v1/entitlements")
    assert r.status_code == 200
    body = r.json()
    assert body["tier"] == "builtin" and body["grace"] is None
    assert body["clock_skew"] is False
    assert len(body["features"]) == 87
    assert all(body["features"].values())
