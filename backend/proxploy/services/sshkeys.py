"""Dedicated executor keypair generation (doc 08 §4): library-generated ed25519,
one keypair per host enrolment, private half exists ONLY as a SecretStore blob."""
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def generate_ed25519(comment: str) -> tuple[bytes, str]:
    priv = Ed25519PrivateKey.generate()
    private_pem = priv.private_bytes(serialization.Encoding.PEM,
                                     serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption())
    public_line = priv.public_key().public_bytes(
        serialization.Encoding.OpenSSH,
        serialization.PublicFormat.OpenSSH).decode()
    return private_pem, f"{public_line} {comment}"
