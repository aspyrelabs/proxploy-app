from datetime import timedelta


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
    return priv_pem, pub_pem


def _token(priv_pem, *, kid="t1", features=None, exp_delta_h=72, grace_delta_d=30):
    import jwt

    from proxploy.models import utcnow

    now = utcnow()
    claims = {"sub": "lic_x", "tier": "pro",
              "features": features if features is not None else {"hosts.multi": True},
              "iat": int(now.timestamp()),
              "exp": int((now + timedelta(hours=exp_delta_h)).timestamp()),
              "grace_until": int((now + timedelta(days=grace_delta_d)).timestamp())}
    return jwt.encode(claims, priv_pem, algorithm="EdDSA", headers={"kid": kid})


def test_registry_is_exactly_81_all_on():
    from proxploy.entitlements.registry import DEFAULT_FEATURES, FLAG_KEYS

    assert len(FLAG_KEYS) == 81 and len(set(FLAG_KEYS)) == 81
    for probe in ("hosts.multi", "store.install", "jobs.engine", "ent.client",
                  "platform.error_report", "terminal.node"):
        assert probe in FLAG_KEYS
    assert DEFAULT_FEATURES == {k: True for k in FLAG_KEYS}


def test_builtin_path_unknown_key_fails_closed():
    from proxploy.entitlements.client import Entitlements

    ent = Entitlements(public_keys={})
    assert ent.enabled("hosts.multi") is True
    assert ent.enabled("not.a.flag") is False
    assert ent.status().source == "builtin"


def test_token_path_and_grace():
    from proxploy.entitlements.client import Entitlements, TokenInvalid

    priv, pub = _keypair()
    ent = Entitlements(public_keys={"t1": pub})
    ent.apply_claims(ent.verify(_token(priv, features={"hosts.multi": False,
                                                       "apps.list": True})))
    assert ent.enabled("apps.list") is True
    assert ent.enabled("hosts.multi") is False       # token is authoritative
    assert ent.enabled("store.install") is False     # unknown-to-token: fail closed

    # past exp, inside grace: still honored, flagged in status (doc 07 §8)
    ent.apply_claims(ent.verify(_token(priv, exp_delta_h=-1)))
    assert ent.status().in_grace is True

    # past grace: dead
    import pytest
    with pytest.raises(TokenInvalid):
        ent.apply_claims(ent.verify(_token(priv, exp_delta_h=-2000, grace_delta_d=-1)))

    # unknown kid rejected
    with pytest.raises(TokenInvalid):
        ent.verify(_token(priv, kid="unknown"))


def test_entitlements_endpoint(client, csrf_header, bootstrap_admin):
    assert client.get("/api/v1/entitlements").status_code == 401
    bootstrap_admin(client)
    r = client.get("/api/v1/entitlements")
    assert r.status_code == 200
    body = r.json()
    assert body["tier"] == "builtin" and body["grace"] is None
    assert len(body["features"]) == 81
    assert all(body["features"].values())
