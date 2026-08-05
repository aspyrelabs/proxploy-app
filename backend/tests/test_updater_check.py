"""The update check talks to a channel we do not control. Every failure mode
of that channel must degrade to 'no update available, here is why' — never to
an exception that takes the Settings page down with it."""
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import proxploy
from proxploy.config import Settings
from proxploy.services.updater import CAN_SELF_APPLY, check, detect_shape


def _channel(tmp_path, version, schema=1, sign_with=None):
    """Writes a file:// channel and returns (settings, pubkey_path)."""
    priv = sign_with or Ed25519PrivateKey.generate()
    pem = priv.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    ch = tmp_path / "channel"
    ch.mkdir(exist_ok=True)
    raw = json.dumps({
        "schema": schema, "version": version, "channel": "stable",
        "released_at": "2026-08-05T12:00:00Z",
        "notes_url": f"https://example.invalid/v{version}",
        "artifacts": {"tarball": {"name": f"proxploy-{version}.tar.gz",
                                  "sha256": "0" * 64, "size": 1}},
    }).encode()
    (ch / "manifest.json").write_bytes(raw)
    (ch / "manifest.json.sig").write_bytes(priv.sign(raw))
    key_path = tmp_path / "release.pem"
    key_path.write_bytes(pem)
    return Settings(db_url=f"sqlite:///{tmp_path}/t.db", data_dir=tmp_path,
                    master_key_file=tmp_path / "m.key",
                    release_channel_url=ch.as_uri(),
                    release_pubkey_file=key_path)


def test_a_newer_signed_release_is_offered(tmp_path):
    s = _channel(tmp_path, "99.0.0")
    got = check(s)
    assert got["update_available"] is True
    assert got["latest"] == "99.0.0"
    assert got["current"] == proxploy.__version__
    assert got["notes_url"] == "https://example.invalid/v99.0.0"
    assert got["error"] is None


def test_the_running_version_is_not_an_update(tmp_path):
    s = _channel(tmp_path, proxploy.__version__)
    got = check(s)
    assert got["update_available"] is False
    assert got["error"] is None


def test_an_older_release_is_not_an_update(tmp_path):
    s = _channel(tmp_path, "0.0.1")
    assert check(s)["update_available"] is False


def test_a_manifest_signed_by_the_wrong_key_reports_an_error(tmp_path):
    s = _channel(tmp_path, "99.0.0")
    (tmp_path / "release.pem").write_bytes(
        Ed25519PrivateKey.generate().public_key().public_bytes(
            Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
    got = check(s)
    assert got["update_available"] is False
    assert got["error"] and "signature" in got["error"].lower()


def test_an_unreachable_channel_reports_an_error_and_does_not_raise(tmp_path):
    s = Settings(db_url=f"sqlite:///{tmp_path}/t.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "m.key",
                 release_channel_url=(tmp_path / "nope").as_uri())
    got = check(s)
    assert got["update_available"] is False
    assert got["error"]


def test_shape_detection(tmp_path, monkeypatch):
    s = Settings(db_url=f"sqlite:///{tmp_path}/t.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "m.key", install_shape="lxc")
    assert detect_shape(s) == "lxc"

    # Configured shape wins; env is the fallback for a container that was
    # started from the image without the installer's env file.
    s2 = Settings(db_url=f"sqlite:///{tmp_path}/t.db", data_dir=tmp_path,
                  master_key_file=tmp_path / "m.key")
    monkeypatch.setenv("PROXPLOY_IN_DOCKER", "1")
    assert detect_shape(s2) == "docker"


def test_only_lxc_and_systemd_may_self_apply():
    assert CAN_SELF_APPLY == {"lxc", "systemd"}
