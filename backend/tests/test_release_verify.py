"""Release verification is the product's supply chain. Every test here is a
way an attacker or a corrupt mirror could hand us bytes we should refuse."""
import hashlib
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from proxploy.services.release import (ReleaseError, is_upgrade, verify_artifact,
                                       verify_manifest)


def _keypair():
    priv = Ed25519PrivateKey.generate()
    pem = priv.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    return priv, pem


def _manifest(version="1.0.1", sha="0" * 64, size=10, schema=1):
    return json.dumps({
        "schema": schema, "version": version, "channel": "stable",
        "released_at": "2026-08-05T12:00:00Z",
        "notes_url": "https://example.invalid/notes",
        "artifacts": {"tarball": {"name": f"proxploy-{version}.tar.gz",
                                  "sha256": sha, "size": size}},
    }).encode()


def test_a_correctly_signed_manifest_parses():
    priv, pem = _keypair()
    raw = _manifest()
    got = verify_manifest(raw, priv.sign(raw), pem)
    assert got["version"] == "1.0.1"
    assert got["artifacts"]["tarball"]["name"] == "proxploy-1.0.1.tar.gz"


def test_a_tampered_body_is_refused():
    priv, pem = _keypair()
    raw = _manifest()
    sig = priv.sign(raw)
    tampered = raw.replace(b"1.0.1", b"9.9.9")
    with pytest.raises(ReleaseError):
        verify_manifest(tampered, sig, pem)


def test_a_signature_from_the_wrong_key_is_refused():
    priv, _ = _keypair()
    _, other_pem = _keypair()
    raw = _manifest()
    with pytest.raises(ReleaseError):
        verify_manifest(raw, priv.sign(raw), other_pem)


def test_an_unknown_schema_version_is_refused():
    """Forward compatibility must fail closed: a manifest we do not
    understand is not a manifest we may act on."""
    priv, pem = _keypair()
    raw = _manifest(schema=99)
    with pytest.raises(ReleaseError):
        verify_manifest(raw, priv.sign(raw), pem)


def test_unparseable_body_is_refused_even_when_correctly_signed():
    priv, pem = _keypair()
    raw = b"this is not json"
    with pytest.raises(ReleaseError):
        verify_manifest(raw, priv.sign(raw), pem)


def test_artifact_checksum_and_size_must_both_match(tmp_path):
    blob = tmp_path / "proxploy-1.0.1.tar.gz"
    blob.write_bytes(b"payload")
    good = {"name": blob.name, "sha256": hashlib.sha256(b"payload").hexdigest(),
            "size": len(b"payload")}
    verify_artifact(blob, good)                      # no raise

    with pytest.raises(ReleaseError):
        verify_artifact(blob, {**good, "sha256": "0" * 64})
    with pytest.raises(ReleaseError):
        verify_artifact(blob, {**good, "size": 999})


def test_upgrade_comparison_rejects_equal_and_older():
    assert is_upgrade("1.0.0", "1.0.1")
    assert is_upgrade("1.0.9", "1.1.0")
    assert is_upgrade("1.9.0", "2.0.0")
    assert not is_upgrade("1.0.1", "1.0.1")
    assert not is_upgrade("1.0.1", "1.0.0")
    assert not is_upgrade("2.0.0", "1.9.9")
