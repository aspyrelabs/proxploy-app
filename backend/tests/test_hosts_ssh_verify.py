"""POST /hosts/{id}/ssh/verify — the wizard's authorize step, made honest."""
import pytest

from tests.fakes.ssh import FakeSSHConnection, make_fake_connect_factory


def _host_with_ssh(client, csrf_header):
    """Create a host with SSH enrolment, returning its id."""
    r = client.post("/api/v1/hosts", headers=csrf_header(client), json={
        "name": "pve-01", "address": "https://10.0.0.5:8006",
        "token_id": "proxploy@pve!t", "token_secret": "s",
        "verify_tls": False, "ssh_enroll": True, "ssh_consent": True})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_verify_marks_the_credential_verified(tmp_path, csrf_header, bootstrap_admin):
    from fastapi.testclient import TestClient
    from proxploy.config import Settings
    from proxploy.main import create_app
    from tests.fakes.pve import make_fake_factory, FakePVE

    fake = FakeSSHConnection(host_key_fingerprint="SHA256:abc",
                             stdout_lines=["ok"], stderr_lines=[], exit_status=0)
    s = Settings(db_url=f"sqlite:///{tmp_path}/v.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key")
    app = create_app(s, proxmox_factory=make_fake_factory(FakePVE()),
                     ssh_factory=make_fake_connect_factory(fake))
    with TestClient(app) as c:
        bootstrap_admin(c)
        hid = _host_with_ssh(c, csrf_header)
        r = c.post(f"/api/v1/hosts/{hid}/ssh/verify", headers=csrf_header(c))
    assert r.status_code == 200, r.text
    assert r.json()["verified"] is True
    assert r.json()["verified_at"]


def test_verify_reports_a_nonzero_exit_as_command_failed(tmp_path, csrf_header, bootstrap_admin):
    """The key authenticated but the command did not run — a real, different
    failure from 'the key is not authorized', and the copy must differ."""
    from fastapi.testclient import TestClient
    from proxploy.config import Settings
    from proxploy.main import create_app
    from tests.fakes.pve import make_fake_factory, FakePVE

    fake = FakeSSHConnection(host_key_fingerprint="SHA256:abc",
                             stdout_lines=[], stderr_lines=["nope"], exit_status=1)
    s = Settings(db_url=f"sqlite:///{tmp_path}/f.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key")
    app = create_app(s, proxmox_factory=make_fake_factory(FakePVE()),
                     ssh_factory=make_fake_connect_factory(fake))
    with TestClient(app) as c:
        bootstrap_admin(c)
        hid = _host_with_ssh(c, csrf_header)
        r = c.post(f"/api/v1/hosts/{hid}/ssh/verify", headers=csrf_header(c))
    assert r.status_code == 502
    assert r.json()["error"] == "command_failed"


def test_verify_on_a_host_without_ssh_enrolment_is_no_key(tmp_path, csrf_header, bootstrap_admin):
    from fastapi.testclient import TestClient
    from proxploy.config import Settings
    from proxploy.main import create_app
    from tests.fakes.pve import make_fake_factory, FakePVE

    s = Settings(db_url=f"sqlite:///{tmp_path}/n.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key")
    app = create_app(s, proxmox_factory=make_fake_factory(FakePVE()))
    with TestClient(app) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/hosts", headers=csrf_header(c), json={
            "name": "pve-02", "address": "https://10.0.0.6:8006",
            "token_id": "proxploy@pve!t", "token_secret": "s",
            "verify_tls": False})
        hid = r.json()["id"]
        r = c.post(f"/api/v1/hosts/{hid}/ssh/verify", headers=csrf_header(c))
    assert r.status_code == 502
    assert r.json()["error"] == "no_key"
