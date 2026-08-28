"""The update routes. Authorization is the Phase 8 authorize() path; what is
new here is refusing to act on a shape that cannot self-apply, and refusing to
install a version the operator was not shown."""
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient

import proxploy
from tests.support import make_app


def _channel(tmp_path, version):
    priv = Ed25519PrivateKey.generate()
    ch = tmp_path / "channel"
    ch.mkdir(exist_ok=True)
    raw = json.dumps({
        "schema": 1, "version": version, "channel": "stable",
        "released_at": "2026-08-05T12:00:00Z",
        "notes_url": f"https://example.invalid/v{version}",
        "artifacts": {"tarball": {"name": f"proxploy-{version}.tar.gz",
                                  "sha256": "0" * 64, "size": 1}},
    }).encode()
    (ch / "manifest.json").write_bytes(raw)
    (ch / "manifest.json.sig").write_bytes(priv.sign(raw))
    key = tmp_path / "release.pem"
    key.write_bytes(priv.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
    return {"release_channel_url": ch.as_uri(), "release_pubkey_file": key}


def test_status_reports_an_available_update(tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path, install_shape="lxc", **_channel(tmp_path, "99.0.0"))
    with TestClient(app) as c:
        bootstrap_admin(c)                       # logs in; auth is the cookie
        r = c.get("/api/v1/meta/update")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["update_available"] is True
        assert body["latest"] == "99.0.0"
        assert body["current"] == proxploy.__version__
        assert body["install_shape"] == "lxc"
        assert body["can_self_apply"] is True
        assert body["compose_hint"] is None


def test_docker_shape_reports_the_compose_command_instead_of_applying(
        tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path, install_shape="docker", **_channel(tmp_path, "99.0.0"))
    with TestClient(app) as c:
        bootstrap_admin(c)
        body = c.get("/api/v1/meta/update").json()
        assert body["update_available"] is True
        assert body["can_self_apply"] is False
        assert body["compose_hint"] == "docker compose pull && docker compose up -d"

        r = c.post("/api/v1/meta/update", json={"version": "99.0.0"},
                   headers=csrf_header(c))
        assert r.status_code == 409
        assert r.json()["error"] == "docker_shape"


def test_apply_launches_the_updater_for_lxc(tmp_path, csrf_header, bootstrap_admin,
                                            monkeypatch):
    launched = []
    monkeypatch.setattr("proxploy.api.meta.updater.launch",
                        lambda s, v: launched.append(v))
    script = tmp_path / "proxploy-update"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    app = make_app(tmp_path, install_shape="lxc", update_script=script,
                   **_channel(tmp_path, "99.0.0"))
    with TestClient(app) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/meta/update", json={"version": "99.0.0"},
                   headers=csrf_header(c))
        assert r.status_code == 202, r.text
        assert launched == ["99.0.0"]


def test_a_version_the_channel_does_not_offer_is_refused(
        tmp_path, csrf_header, bootstrap_admin, monkeypatch):
    monkeypatch.setattr("proxploy.api.meta.updater.launch",
                        lambda s, v: (_ for _ in ()).throw(AssertionError("must not launch")))
    script = tmp_path / "proxploy-update"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    app = make_app(tmp_path, install_shape="lxc", update_script=script,
                   **_channel(tmp_path, "99.0.0"))
    with TestClient(app) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/meta/update", json={"version": "98.0.0"},
                   headers=csrf_header(c))
        assert r.status_code == 409
        assert r.json()["error"] == "no_such_version"


def test_a_missing_update_script_is_503_not_a_crash(tmp_path, csrf_header,
                                                    bootstrap_admin):
    app = make_app(tmp_path, install_shape="systemd",
                   update_script=tmp_path / "absent",
                   **_channel(tmp_path, "99.0.0"))
    with TestClient(app) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/meta/update", json={"version": "99.0.0"},
                   headers=csrf_header(c))
        assert r.status_code == 503


def test_a_viewer_cannot_apply_an_update(tmp_path, csrf_header, bootstrap_admin):
    """Covered generically by test_rbac_invariant.py; asserted explicitly here
    because 'a viewer can restart the product' would be the most embarrassing
    possible hole in the phase that adds the restart."""
    app = make_app(tmp_path, install_shape="lxc", **_channel(tmp_path, "99.0.0"))
    with TestClient(app) as c:
        bootstrap_admin(c)                       # owner, so it can mint a viewer
        h = csrf_header(c)
        c.post("/api/v1/users", json={"email": "v@x.io", "role": "viewer",
               "password": "Correct-Horse-Battery-9"}, headers=h)
        c.post("/api/v1/auth/logout", headers=h)
        c.post("/api/v1/auth/login", json={"email": "v@x.io",
               "password": "Correct-Horse-Battery-9"}, headers=h)
        r = c.post("/api/v1/meta/update", json={"version": "99.0.0"},
                   headers=csrf_header(c))
        assert r.status_code == 403
