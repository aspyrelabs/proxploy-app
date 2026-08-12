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
    # The reload case (onboarding wizard step 3): authorized_keys_line is
    # only ever returned once, from POST /hosts. host_detail must still
    # surface the same public key line via the ssh_key credential's
    # public_meta, or a user who reloads mid-authorize can never finish.
    assert any(cred["kind"] == "ssh_key" and cred["public_meta"] == body["authorized_keys_line"]
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
    reach the probe at all. Anonymous must be 401 (not 403, a session-less
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
    body = r.json()
    assert body["error"] == "refused"
    assert "refusing to connect" in body["detail"]
    assert not fake.kwargs, "the client was constructed despite the refusal"


def test_creating_a_host_at_a_denied_address_stores_nothing(pve_client, csrf_header):
    c, _ = pve_client
    r = c.post("/api/v1/hosts", json=HOST | {"address": "https://127.0.0.1:8006"},
               headers=csrf_header(c))
    assert r.status_code == 502
    body = r.json()
    assert body["error"] == "refused" and "loopback" in body["detail"]
    assert c.get("/api/v1/hosts").json() == []


def test_patch_host_toggles_node_shell_enabled(pve_client, csrf_header):
    c, _ = pve_client
    hid = c.post("/api/v1/hosts", json=HOST, headers=csrf_header(c)).json()["id"]
    r = c.patch(f"/api/v1/hosts/{hid}", json={"node_shell_enabled": True},
               headers=csrf_header(c))
    assert r.status_code == 200
    assert r.json() == {"id": hid, "node_shell_enabled": True}
    assert c.get(f"/api/v1/hosts/{hid}").json()["id"] == hid

    r = c.patch(f"/api/v1/hosts/{hid}", json={"node_shell_enabled": False},
               headers=csrf_header(c))
    assert r.status_code == 200 and r.json()["node_shell_enabled"] is False


def test_patch_host_assigns_team(pve_client, csrf_header):
    from proxploy.models import Team

    c, _ = pve_client
    hid = c.post("/api/v1/hosts", json=HOST, headers=csrf_header(c)).json()["id"]
    with c.app.state.sessionmaker() as db:
        db.add(Team(name="Ops", slug="ops"))
        db.commit()
        team_id = db.query(Team).filter_by(slug="ops").one().id

    r = c.patch(f"/api/v1/hosts/{hid}",
               json={"node_shell_enabled": False, "team_id": team_id},
               headers=csrf_header(c))
    assert r.status_code == 200
    with c.app.state.sessionmaker() as db:
        from proxploy.models import Host
        assert db.get(Host, hid).team_id == team_id


def test_patch_host_rejects_unknown_team(pve_client, csrf_header):
    c, _ = pve_client
    hid = c.post("/api/v1/hosts", json=HOST, headers=csrf_header(c)).json()["id"]
    r = c.patch(f"/api/v1/hosts/{hid}",
               json={"node_shell_enabled": False, "team_id": 999999},
               headers=csrf_header(c))
    assert r.status_code == 404


def test_patch_host_writes_an_audit_event(pve_client, csrf_header):
    from proxploy.models import AuditEvent

    c, _ = pve_client
    hid = c.post("/api/v1/hosts", json=HOST, headers=csrf_header(c)).json()["id"]
    r = c.patch(f"/api/v1/hosts/{hid}", json={"node_shell_enabled": True},
               headers=csrf_header(c))
    assert r.status_code == 200

    with c.app.state.sessionmaker() as db:
        row = db.query(AuditEvent).filter_by(action="host.node_shell_toggle").one()
        assert row.target_type == "host" and row.target_id == hid
        assert row.params == {"node_shell_enabled": True}


def test_patch_host_updates_name_and_address(pve_client, csrf_header):
    """HostPatchIn used to hard-refuse these (doc comment: "name/address/
    credentials all go through their own dedicated flows"), but there was no
    dedicated flow for name/address at all -- the Edit dialog needs one."""
    c, _ = pve_client
    hid = c.post("/api/v1/hosts", json=HOST, headers=csrf_header(c)).json()["id"]
    r = c.patch(f"/api/v1/hosts/{hid}",
               json={"name": "pve-renamed", "address": "https://10.0.0.9:8006"},
               headers=csrf_header(c))
    assert r.status_code == 200, r.text
    detail = c.get(f"/api/v1/hosts/{hid}").json()
    assert detail["name"] == "pve-renamed"
    assert detail["address"] == "https://10.0.0.9:8006"


def test_patch_host_name_and_address_are_both_optional_and_independent(
        pve_client, csrf_header):
    """The node-shell toggle already patches without name/address; the
    reverse must hold too -- renaming alone must not require re-sending the
    node-shell flag or touching the address."""
    c, _ = pve_client
    hid = c.post("/api/v1/hosts", json=HOST, headers=csrf_header(c)).json()["id"]
    r = c.patch(f"/api/v1/hosts/{hid}", json={"name": "renamed-only"},
               headers=csrf_header(c))
    assert r.status_code == 200, r.text
    detail = c.get(f"/api/v1/hosts/{hid}").json()
    assert detail["name"] == "renamed-only"
    assert detail["address"] == HOST["address"]


def test_patch_host_rejects_a_duplicate_name_on_rename(pve_client, csrf_header):
    c, _ = pve_client
    hid = c.post("/api/v1/hosts", json=HOST, headers=csrf_header(c)).json()["id"]
    c.post("/api/v1/hosts", json=HOST | {"name": "pve-02"}, headers=csrf_header(c))
    r = c.patch(f"/api/v1/hosts/{hid}", json={"name": "pve-02"},
               headers=csrf_header(c))
    assert r.status_code == 409


def test_patch_host_name_change_is_audited_as_host_update(pve_client, csrf_header):
    from proxploy.models import AuditEvent

    c, _ = pve_client
    hid = c.post("/api/v1/hosts", json=HOST, headers=csrf_header(c)).json()["id"]
    c.patch(f"/api/v1/hosts/{hid}", json={"name": "pve-renamed"},
           headers=csrf_header(c))
    with c.app.state.sessionmaker() as db:
        row = db.query(AuditEvent).filter_by(action="host.update").one()
        assert row.target_type == "host" and row.target_id == hid
        assert row.params == {"name": "pve-renamed"}


def test_patch_host_still_toggles_node_shell_without_name_or_address(
        pve_client, csrf_header):
    """Backward compatibility: node_shell_enabled becoming optional must not
    change its own behaviour for the Settings page's existing call sites."""
    from proxploy.models import AuditEvent

    c, _ = pve_client
    hid = c.post("/api/v1/hosts", json=HOST, headers=csrf_header(c)).json()["id"]
    r = c.patch(f"/api/v1/hosts/{hid}", json={"node_shell_enabled": True},
               headers=csrf_header(c))
    assert r.status_code == 200
    assert r.json() == {"id": hid, "node_shell_enabled": True}
    with c.app.state.sessionmaker() as db:
        row = db.query(AuditEvent).filter_by(action="host.node_shell_toggle").one()
        assert row.params == {"node_shell_enabled": True}


def test_patch_host_requires_admin_role(pve_client, csrf_header):
    c, _ = pve_client
    hid = c.post("/api/v1/hosts", json=HOST, headers=csrf_header(c)).json()["id"]
    c.post("/api/v1/users", json={"email": "viewer2@example.com",
                                  "password": "correct-horse-battery",
                                  "display_name": "V2", "role": "viewer"},
           headers=csrf_header(c))
    c.post("/api/v1/auth/login", json={"email": "viewer2@example.com",
                                       "password": "correct-horse-battery"},
           headers=csrf_header(c))
    r = c.patch(f"/api/v1/hosts/{hid}", json={"node_shell_enabled": True},
               headers=csrf_header(c))
    assert r.status_code == 403


def test_an_unparseable_token_id_is_a_422_not_a_502(pve_client, csrf_header):
    """Rejected at the door as bad input, not surfaced as an upstream failure; 
    and nothing derived from the raw string is stored on the way."""
    c, _ = pve_client
    r = c.post("/api/v1/hosts", json=HOST | {"token_id": "root@pam!tok=deadbeef"},
               headers=csrf_header(c))
    assert r.status_code == 422, r.text
    assert "deadbeef" not in r.text
    assert c.get("/api/v1/hosts").json() == []


def test_host_reads_expose_team_id_so_the_ui_can_show_current_assignment(
        client, csrf_header, bootstrap_admin):
    """PATCH /hosts/{id} accepted team_id from the start but neither GET
    returned it, so the Settings team picker could only ever be a write-only
    control; it could reassign a host but never show what it was already
    assigned to. Found while wiring the Teams admin UI (Task 20)."""
    bootstrap_admin(client)
    from proxploy.models import Host, Team

    with client.app.state.sessionmaker() as db:
        team = Team(name="Ops", slug="ops")
        db.add(team)
        db.add(Host(name="h1", address="https://pve:8006", status="connected"))
        db.commit()
        team_id, host_id = team.id, db.query(Host).one().id

    assert client.get("/api/v1/hosts").json()[0]["team_id"] is None
    assert client.get(f"/api/v1/hosts/{host_id}").json()["team_id"] is None

    r = client.patch(f"/api/v1/hosts/{host_id}",
                     json={"node_shell_enabled": False, "team_id": team_id},
                     headers=csrf_header(client))
    assert r.status_code == 200, r.text

    assert client.get("/api/v1/hosts").json()[0]["team_id"] == team_id
    assert client.get(f"/api/v1/hosts/{host_id}").json()["team_id"] == team_id


def test_probe_reports_unreachable_as_a_kind(tmp_path, csrf_header, bootstrap_admin):
    """A closed port and a bad token must not read identically to the wizard."""
    from fastapi.testclient import TestClient
    from proxploy.config import Settings
    from proxploy.main import create_app

    def unreachable(**kwargs):
        raise ConnectionError("connection refused")

    s = Settings(db_url=f"sqlite:///{tmp_path}/p.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key")
    with TestClient(create_app(s, proxmox_factory=unreachable)) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/hosts/probe", headers=csrf_header(c), json={
            "address": "https://10.0.0.5:8006", "token_id": "u@pve!t",
            "token_secret": "s", "verify_tls": True})
    assert r.status_code == 502
    assert r.json()["error"] == "unreachable"


def test_probe_reports_auth_failure_as_its_own_kind(tmp_path, csrf_header, bootstrap_admin):
    from fastapi.testclient import TestClient
    from proxploy.config import Settings
    from proxploy.main import create_app

    def denied(**kwargs):
        raise PermissionError("401 authentication failure")

    s = Settings(db_url=f"sqlite:///{tmp_path}/a.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key")
    with TestClient(create_app(s, proxmox_factory=denied)) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/hosts/probe", headers=csrf_header(c), json={
            "address": "https://10.0.0.5:8006", "token_id": "u@pve!t",
            "token_secret": "s", "verify_tls": True})
    assert r.status_code == 502
    assert r.json()["error"] == "auth"


def test_error_kind_never_leaks_the_token_secret(tmp_path, csrf_header, bootstrap_admin):
    """The scrubbing _wrap already does must survive the new structure."""
    from fastapi.testclient import TestClient
    from proxploy.config import Settings
    from proxploy.main import create_app

    def leaky(**kwargs):
        raise RuntimeError("failed using secret super-secret-value")

    s = Settings(db_url=f"sqlite:///{tmp_path}/l.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key")
    with TestClient(create_app(s, proxmox_factory=leaky)) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/hosts/probe", headers=csrf_header(c), json={
            "address": "https://10.0.0.5:8006", "token_id": "u@pve!t",
            "token_secret": "super-secret-value", "verify_tls": True})
    assert "super-secret-value" not in r.text
