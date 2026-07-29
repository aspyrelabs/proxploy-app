import json
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures" / "pve"


@pytest.fixture
def pve_client(tmp_path, csrf_header, bootstrap_admin):
    """App wired to a FakePVE via the proxmox_factory seam."""
    from fastapi.testclient import TestClient

    from proxploy.api.auth import limiter
    from proxploy.config import Settings
    from proxploy.main import create_app
    from tests.fakes.pve import FakePVE, make_fake_factory

    fake = FakePVE(version=json.loads((FIX / "version_pve8.json").read_text()),
                   permissions=json.loads((FIX / "permissions_full.json").read_text()))
    limiter.reset()
    s = Settings(db_url=f"sqlite:///{tmp_path}/h.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key")
    app = create_app(s, proxmox_factory=make_fake_factory(fake))
    with TestClient(app) as c:
        bootstrap_admin(c)
        yield c, fake


HOST = {"name": "pve-01", "address": "https://10.0.0.5:8006",
        "token_id": "proxploy@pve!mon", "token_secret": "s3cret"}


def test_probe(pve_client, csrf_header):
    c, _ = pve_client
    r = c.post("/api/v1/hosts/probe", json=HOST | {"name": None},
               headers=csrf_header(c))
    assert r.status_code == 200 and r.json()["release"] == "8.4"


def test_create_host_with_ssh_enrolment(pve_client, csrf_header):
    c, _ = pve_client
    r = c.post("/api/v1/hosts", json=HOST | {"ssh_enroll": True, "ssh_consent": True},
               headers=csrf_header(c))
    assert r.status_code == 201
    body = r.json()
    assert body["pve_version"] == "8.4.1" and body["status"] == "connected"
    assert body["ssh_public_key"].startswith("ssh-ed25519 ")
    assert body["authorized_keys_line"].startswith("ssh-ed25519 ")
    assert "root on" in body["consent_note"]

    # credentials at rest: encrypted, public_meta only ever exposed
    detail = c.get(f"/api/v1/hosts/{body['id']}").json()
    kinds = {cred["kind"] for cred in detail["credentials"]}
    assert kinds == {"api_token", "ssh_key"}
    assert all("encrypted_blob" not in cred for cred in detail["credentials"])
    assert any(cred["public_meta"] == "proxploy@pve!mon"
               for cred in detail["credentials"])

    # audit rows exist (route-template proof)
    audit = c.get("/api/v1/audit", params={"action": "host.create"}).json()
    assert audit and audit[0]["params"]["token_secret"] == "[redacted]"


def test_ssh_enroll_requires_explicit_consent(pve_client, csrf_header):
    c, _ = pve_client
    r = c.post("/api/v1/hosts", json=HOST | {"ssh_enroll": True},
               headers=csrf_header(c))
    assert r.status_code == 400
    assert "consent" in r.json()["detail"].lower()


def test_unreachable_host_rejected_and_audited(pve_client, csrf_header):
    c, fake = pve_client
    fake.version._fail = True
    r = c.post("/api/v1/hosts", json=HOST, headers=csrf_header(c))
    assert r.status_code == 502
    fake.version._fail = False
    audit = c.get("/api/v1/audit", params={"action": "host.create"}).json()
    assert any(e["result"] == "error" for e in audit)


def test_second_host_gated_by_hosts_multi(pve_client, csrf_header):
    c, _ = pve_client
    assert c.post("/api/v1/hosts", json=HOST,
                  headers=csrf_header(c)).status_code == 201
    # simulate an armed tier without multi-host (dormant default is ON)
    c.app.state.entitlements._features["hosts.multi"] = False
    r = c.post("/api/v1/hosts", json=HOST | {"name": "pve-02"},
               headers=csrf_header(c))
    assert r.status_code == 403 and r.json()["feature"] == "hosts.multi"
    c.app.state.entitlements._features["hosts.multi"] = True
    assert c.post("/api/v1/hosts", json=HOST | {"name": "pve-02"},
                  headers=csrf_header(c)).status_code == 201


def test_host_test_endpoint_updates_status(pve_client, csrf_header):
    c, fake = pve_client
    hid = c.post("/api/v1/hosts", json=HOST, headers=csrf_header(c)).json()["id"]
    fake.version._fail = True
    r = c.post(f"/api/v1/hosts/{hid}/test", headers=csrf_header(c))
    assert r.status_code == 200 and r.json()["status"] == "unreachable"
    fake.version._fail = False
    assert c.post(f"/api/v1/hosts/{hid}/test",
                  headers=csrf_header(c)).json()["status"] == "connected"


def test_probe_is_auth_and_rbac_gated_before_it_touches_the_network(pve_client,
                                                                    csrf_header):
    """The SSRF guard is the second line; the first is that only an admin can
    reach the probe at all. Anonymous must be 401 (not 403 — a session-less
    caller has no role state to leak), an authenticated viewer must be 403.
    """
    from fastapi.testclient import TestClient

    c, _ = pve_client
    with TestClient(c.app) as anon:
        r = anon.post("/api/v1/hosts/probe", json=HOST | {"name": None},
                      headers=csrf_header(anon))
        assert r.status_code == 401, r.text

    c.post("/api/v1/users", json={"email": "viewer@example.com",
                                  "password": "correct-horse-battery",
                                  "display_name": "V", "role": "viewer"},
           headers=csrf_header(c))
    c.post("/api/v1/auth/login", json={"email": "viewer@example.com",
                                       "password": "correct-horse-battery"},
           headers=csrf_header(c))
    r = c.post("/api/v1/hosts/probe", json=HOST | {"name": None},
               headers=csrf_header(c))
    assert r.status_code == 403, r.text


def test_probe_refuses_the_cloud_metadata_address(pve_client, csrf_header):
    """End of the SSRF path as an operator sees it: an admin-supplied address
    that would reach instance metadata is refused before any connection."""
    c, fake = pve_client
    r = c.post("/api/v1/hosts/probe",
               json=HOST | {"name": None, "address": "https://169.254.169.254:8006"},
               headers=csrf_header(c))
    assert r.status_code == 502
    assert "refusing to connect" in r.json()["detail"]
    assert not fake.kwargs, "the client was constructed despite the refusal"


def test_creating_a_host_at_a_denied_address_stores_nothing(pve_client, csrf_header):
    c, _ = pve_client
    r = c.post("/api/v1/hosts", json=HOST | {"address": "https://127.0.0.1:8006"},
               headers=csrf_header(c))
    assert r.status_code == 502 and "loopback" in r.json()["detail"]
    assert c.get("/api/v1/hosts").json() == []
