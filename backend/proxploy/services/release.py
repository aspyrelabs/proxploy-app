"""Release manifest parsing and verification.

Deliberately pure: no network, no filesystem beyond hashing a file the caller
already has. Everything here is on the path an attacker would need to walk to
make us install their bytes, so it is small enough to read in one sitting.

The signature is checked over the RAW bytes before any parsing, so malformed
or hostile JSON never reaches the parser.
"""
import hashlib
import json
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from proxploy.pubkey import load_public_key

MANIFEST_SCHEMA_VERSION = 1
_CHUNK = 1024 * 1024


class ReleaseError(Exception):
    """Any reason we refuse a release. Callers surface the message verbatim."""


def verify_manifest(raw: bytes, sig: bytes, pubkey_pem: bytes) -> dict:
    try:
        # PEM or the bare base64 body: same bytes, and the signature either
        # verifies against them or it does not. Accepting both spellings
        # widens nothing an attacker can reach, it only stops a correct key
        # being rejected over its label lines.
        key = load_public_key(pubkey_pem)
    except Exception as e:
        raise ReleaseError(f"release public key is unreadable: {e}") from e
    if not isinstance(key, Ed25519PublicKey):
        raise ReleaseError("release public key is not Ed25519")
    try:
        key.verify(sig, raw)
    except InvalidSignature as e:
        raise ReleaseError("manifest signature is not valid for this key") from e

    try:
        manifest = json.loads(raw)
    except ValueError as e:
        raise ReleaseError(f"manifest is not valid JSON: {e}") from e
    if not isinstance(manifest, dict):
        raise ReleaseError("manifest is not an object")
    if manifest.get("schema") != MANIFEST_SCHEMA_VERSION:
        raise ReleaseError(
            f"manifest schema {manifest.get('schema')!r} is not supported "
            f"(this build understands {MANIFEST_SCHEMA_VERSION}), update "
            f"Proxploy manually, then retry")
    for field in ("version", "artifacts"):
        if field not in manifest:
            raise ReleaseError(f"manifest is missing {field!r}")
    tarball = manifest["artifacts"].get("tarball")
    if not isinstance(tarball, dict) or not {"name", "sha256", "size"} <= tarball.keys():
        raise ReleaseError("manifest has no complete tarball artifact entry")
    return manifest


def verify_artifact(path: Path, entry: dict) -> None:
    actual_size = path.stat().st_size
    if actual_size != entry["size"]:
        raise ReleaseError(
            f"{path.name}: expected {entry['size']} bytes, got {actual_size}")
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != entry["sha256"]:
        raise ReleaseError(f"{path.name}: sha256 mismatch, refusing to install")


def _parts(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in v.split("."))
    except ValueError as e:
        raise ReleaseError(f"unparseable version {v!r}") from e


def is_upgrade(current: str, candidate: str) -> bool:
    """Strictly newer. Downgrades are refused here rather than at the call
    site, so no caller can forget: rolling BACK is the updater's rollback
    path, which restores a known-good directory, not a fresh install of an
    older release over a newer database."""
    return _parts(candidate) > _parts(current)
