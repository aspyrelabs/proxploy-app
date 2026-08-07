"""Ed25519 public keys, in either spelling of the same bytes.

A PEM is base64-encoded DER with two label lines wrapped around it. The
labels say what the bytes are; they do not contribute any. So accept the
body on its own as well: one line pastes into a config field or a JSON
value without the armor getting mangled on the way.

Both key inputs on this side go through here: the entitlement signing keys
(entitlements/keys.py, including the ent_extra_keys_file overlay) and the
release-signing key (services/release.py). Neither is secret, so the only
thing at stake is whether the bytes parse.
"""
import base64

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat, load_der_public_key, load_pem_public_key,
)


def load_public_key(value: str | bytes) -> Ed25519PublicKey:
    """Parse a public key from a PEM or from its bare base64 body.

    Raises ValueError (binascii.Error subclasses it) if it is neither.
    """
    text = value.decode() if isinstance(value, bytes) else value
    if "-----BEGIN" in text:
        return load_pem_public_key(text.encode())
    # validate=False discards whitespace, so a body wrapped across lines
    # parses the same as one long line.
    return load_der_public_key(base64.b64decode(text, validate=False))


def to_pem(key: Ed25519PublicKey) -> str:
    """Canonical PEM. PyJWT wants one of these, so normalising here keeps
    entitlements/client.py unaware that the bare form exists at all."""
    return key.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
