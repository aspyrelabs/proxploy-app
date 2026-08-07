"""Both spellings of a public key, across every place one is accepted."""
import base64

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from proxploy.pubkey import load_public_key, to_pem


@pytest.fixture
def keypair():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    pem = to_pem(pub)
    body = "".join(l for l in pem.splitlines() if not l.startswith("-----"))
    return priv, pem, body


def test_bare_body_and_pem_give_the_same_key(keypair):
    _, pem, body = keypair
    raw = lambda k: k.public_bytes(Encoding.Raw, PublicFormat.Raw)
    assert raw(load_public_key(body)) == raw(load_public_key(pem))
    assert raw(load_public_key(body.encode())) == raw(load_public_key(pem))


def test_a_body_wrapped_across_lines_still_parses(keypair):
    _, pem, body = keypair
    wrapped = body[:20] + "\n" + body[20:]
    assert to_pem(load_public_key(wrapped)) == pem


@pytest.mark.parametrize("junk", ["", "not-a-key", "-----BEGIN PUBLIC KEY-----\nx\n-----END PUBLIC KEY-----"])
def test_junk_is_rejected(junk):
    with pytest.raises((ValueError, TypeError)):
        load_public_key(junk)


def test_bundled_keys_normalise_to_pem(tmp_path):
    """The bundled set is stored bare; PyJWT needs PEM, so load_public_keys
    is what bridges that. Also covers the operator overlay."""
    from types import SimpleNamespace

    from proxploy.entitlements.keys import BUNDLED_PUBLIC_KEYS, load_public_keys

    assert not any(v.startswith("-----") for v in BUNDLED_PUBLIC_KEYS.values()), \
        "bundled keys are stored as bare bodies"
    keys = load_public_keys(SimpleNamespace(ent_extra_keys_file=None))
    assert keys and all(v.startswith("-----BEGIN PUBLIC KEY-----")
                        for v in keys.values())


def test_a_broken_overlay_key_is_dropped_not_fatal(tmp_path, keypair, caplog):
    """One bad entry in an operator-supplied file must not take the bundled
    set down with it, and must not vanish quietly either."""
    import json
    from types import SimpleNamespace

    from proxploy.entitlements.keys import load_public_keys

    _, _, body = keypair
    f = tmp_path / "extra.json"
    f.write_text(json.dumps({"good-kid": body, "bad-kid": "garbage"}))
    keys = load_public_keys(SimpleNamespace(ent_extra_keys_file=f))

    assert "good-kid" in keys
    assert "bad-kid" not in keys
    assert "dev-2026-07" in keys, "a bad overlay entry must not drop bundled keys"
    assert "bad-kid" in caplog.text
