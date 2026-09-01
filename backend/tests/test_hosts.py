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
    from tests.support import entitle

    fake = FakePVE(version=json.loads((FIX / "version_pve8.json").read_text()),
                   permissions=json.loads((FIX / "permissions_full.json").read_text()))
    limiter.reset()
    s = Settings(db_url=f"sqlite:///{tmp_path}/h.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key")
    # A few tests here need a second host (rename clashes, listing), which is
    # the Pro flag. The refusal itself is covered in
    # test_entitlement_denied_branches.py.
    app = entitle(create_app(s, proxmox_factory=make_fake_factory(fake)),
                  "hosts.multi")
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
    assert kinds == {"api_token:monitoring", "ssh_key"}
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
                                  "password": "Correct-Horse-Battery-9",
                                  "display_name": "V", "role": "viewer"},
           headers=csrf_header(c))
    c.post("/api/v1/auth/login", json={"email": "viewer@example.com",
                                       "password": "Correct-Horse-Battery-9"},
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
                                  "password": "Correct-Horse-Battery-9",
                                  "display_name": "V2", "role": "viewer"},
           headers=csrf_header(c))
    c.post("/api/v1/auth/login", json={"email": "viewer2@example.com",
                                       "password": "Correct-Horse-Battery-9"},
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
        # The caller's own team. GET /hosts/{id} is team-scoped, so reassigning
        # the host to a team this admin is not in would (correctly) make the
        # detail read a 403 and prove nothing about the field being exposed.
        team_id = db.query(Team).filter_by(slug="default").one().id
        db.add(Host(name="h1", address="https://pve:8006", status="connected"))
        db.commit()
        host_id = db.query(Host).one().id

    assert client.get("/api/v1/hosts").json()[0]["team_id"] is None
    assert client.get(f"/api/v1/hosts/{host_id}").json()["team_id"] is None

    r = client.patch(f"/api/v1/hosts/{host_id}",
                     json={"node_shell_enabled": False, "team_id": team_id},
                     headers=csrf_header(client))
    assert r.status_code == 200, r.text

    assert client.get("/api/v1/hosts").json()[0]["team_id"] == team_id
    assert client.get(f"/api/v1/hosts/{host_id}").json()["team_id"] == team_id


def test_host_list_carries_no_remembered_storage_pools(client, csrf_header,
                                                       bootstrap_admin):
    """This used to assert the opposite. PXP-86 (48fbbb2) removed remembering a
    host's last placement, and the columns behind these two keys are gone, so
    the assertion is that the shape does not grow them back: a client seeing
    the field again would reasonably conclude the memory is back."""
    bootstrap_admin(client)
    from proxploy.models import Host

    with client.app.state.sessionmaker() as db:
        db.add(Host(name="h1", address="https://pve:8006", status="connected"))
        db.commit()

    row = client.get("/api/v1/hosts").json()[0]
    assert "default_container_storage" not in row
    assert "default_template_storage" not in row


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


def test_a_host_can_be_moved_out_of_a_team_not_just_between_teams(
        client, csrf_header, bootstrap_admin):
    """team_id was read with `is not None`, so an explicit null looked exactly
    like an omitted field and the only way out of a team was deleting the team.
    The Settings picker offered "Unassigned" the whole time and it silently did
    nothing."""
    bootstrap_admin(client)
    from proxploy.models import Host, Team

    with client.app.state.sessionmaker() as db:
        team_id = db.query(Team).filter_by(slug="default").one().id
        db.add(Host(name="h-unassign", address="https://pve:8006", status="connected"))
        db.commit()
        host_id = db.query(Host).filter_by(name="h-unassign").one().id

    assert client.patch(f"/api/v1/hosts/{host_id}", json={"team_id": team_id},
                        headers=csrf_header(client)).status_code == 200
    assert client.get(f"/api/v1/hosts/{host_id}").json()["team_id"] == team_id

    r = client.patch(f"/api/v1/hosts/{host_id}", json={"team_id": None},
                     headers=csrf_header(client))
    assert r.status_code == 200, r.text
    assert client.get("/api/v1/hosts").json()[0]["team_id"] is None

    # An omitted team_id still means "leave it alone", not "unassign".
    assert client.patch(f"/api/v1/hosts/{host_id}", json={"team_id": team_id},
                        headers=csrf_header(client)).status_code == 200
    assert client.patch(f"/api/v1/hosts/{host_id}", json={"name": "h-renamed"},
                        headers=csrf_header(client)).status_code == 200
    assert client.get(f"/api/v1/hosts/{host_id}").json()["team_id"] == team_id


# --- the stored pin, and the way back out of one (plan phase 3) ------------
# A pin is only enforced while verify_tls is false, so that is what these
# enrol with. Both bindings of tls_fingerprint_sha256 are stubbed: api/hosts.py
# takes the pin, services/proxmox.py's ProxmoxClient._connect enforces it, and
# the real one opens a socket.

def _pinned_host(c, csrf_header, monkeypatch, presenting):
    """(host_id, probes). `presenting` is a one-item list read on every call, so
    a test can change the certificate afterwards the way a renewal does, and
    `probes` counts the probes api/hosts.py itself took."""
    probes = []

    def _fingerprint(host, port=8006):
        probes.append((host, port))
        return presenting[0]

    monkeypatch.setattr("proxploy.api.hosts.tls_fingerprint_sha256", _fingerprint)
    # ProxmoxClient._connect enforces the pin through its own binding, which is
    # a connection cost and not a probe api/hosts.py chose to take, so it is
    # deliberately not counted.
    monkeypatch.setattr("proxploy.services.proxmox.tls_fingerprint_sha256",
                        lambda host, port=8006: presenting[0])
    r = c.post("/api/v1/hosts", json=HOST | {"verify_tls": False},
               headers=csrf_header(c))
    assert r.status_code == 201, r.text
    probes.clear()  # enrolment's own pin, not what any test below is counting
    return r.json()["id"], probes


def test_a_pin_that_stops_matching_refuses_the_connection_and_test_says_what_is_presented(
        pve_client, csrf_header, monkeypatch):
    """The node is answering perfectly here: only the certificate changed. That
    has to read as a refusal, never as a quiet connection, and the test route
    has to hand back what the node is presenting now so the operator can
    compare it with the pin before accepting anything."""
    c, _ = pve_client
    presenting = ["AB:CD"]
    hid, _ = _pinned_host(c, csrf_header, monkeypatch, presenting)

    presenting[0] = "12:34"  # the node renewed its certificate
    r = c.post(f"/api/v1/hosts/{hid}/test", headers=csrf_header(c))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "unreachable"
    assert r.json()["tls_fingerprint"] == "AB:CD"
    assert r.json()["tls_fingerprint_seen"] == "12:34"


def test_patch_repins_to_the_supplied_fingerprint_and_null_clears_the_pin(
        pve_client, csrf_header, monkeypatch):
    """The way out of a pin that no longer matches, and the way out of pinning
    altogether. Without both, a routine certificate renewal leaves a host row
    nobody can fix from the UI."""
    from proxploy.models import Host

    c, _ = pve_client
    presenting = ["AB:CD"]
    hid, _ = _pinned_host(c, csrf_header, monkeypatch, presenting)

    presenting[0] = "12:34"
    r = c.patch(f"/api/v1/hosts/{hid}", json={"tls_fingerprint": "12:34"},
                headers=csrf_header(c))
    assert r.status_code == 200, r.text
    with c.app.state.sessionmaker() as db:
        assert db.get(Host, hid).tls_fingerprint == "12:34"
    assert c.post(f"/api/v1/hosts/{hid}/test",
                  headers=csrf_header(c)).json()["status"] == "connected"

    r = c.patch(f"/api/v1/hosts/{hid}", json={"tls_fingerprint": None},
                headers=csrf_header(c))
    assert r.status_code == 200, r.text
    with c.app.state.sessionmaker() as db:
        assert db.get(Host, hid).tls_fingerprint is None


def test_patching_something_else_leaves_the_pin_alone(pve_client, csrf_header,
                                                      monkeypatch):
    """An omitted field and an explicit null mean different things here, same
    as team_id: a rename must not silently unpin the host."""
    from proxploy.models import Host

    c, _ = pve_client
    hid, _ = _pinned_host(c, csrf_header, monkeypatch, ["AB:CD"])
    r = c.patch(f"/api/v1/hosts/{hid}", json={"name": "pve-renamed"},
                headers=csrf_header(c))
    assert r.status_code == 200, r.text
    with c.app.state.sessionmaker() as db:
        assert db.get(Host, hid).tls_fingerprint == "AB:CD"


def test_testing_an_unreachable_host_takes_no_fingerprint_probe(
        pve_client, csrf_header, monkeypatch):
    """A dead node is the case an operator tests most, and fetching a
    certificate from it can only sit out the full connect timeout. The probe
    belongs on the one failure the operator can act on, the pin refusing the
    connection, and nowhere else."""
    c, fake = pve_client
    hid, probes = _pinned_host(c, csrf_header, monkeypatch, ["AB:CD"])

    fake.version._fail = True
    r = c.post(f"/api/v1/hosts/{hid}/test", headers=csrf_header(c))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "unreachable"
    assert probes == []
    assert r.json()["tls_fingerprint_seen"] is None
    assert r.json()["tls_fingerprint"] == "AB:CD"  # the stored pin is still reported


def test_a_connected_host_reports_no_presented_fingerprint(pve_client, csrf_header,
                                                           monkeypatch):
    """version() got through with the pin enforced, so the certificate matched
    it by definition. There is nothing to compare and nothing to probe."""
    c, _ = pve_client
    hid, probes = _pinned_host(c, csrf_header, monkeypatch, ["AB:CD"])

    r = c.post(f"/api/v1/hosts/{hid}/test", headers=csrf_header(c))
    assert r.json()["status"] == "connected"
    assert probes == []
    assert r.json()["tls_fingerprint_seen"] is None


# --- re-pinning a rotated SSH host key --------------------------------------
#
# Rejoining a node to a PVE cluster rotates its SSH host key, and until this
# existed nothing could change Host.ssh_host_key_fingerprint: it is only written
# through on_new_fingerprint, which fires ONLY when the stored pin is already
# None. So a legitimate rotation bricked installs, updates and transfer-strategy
# migration for that host permanently, fixable only by editing the database. The
# TLS pin has had "Accept the new certificate" for a while; this is the same
# shape for the other pin.

def test_patch_host_repins_the_ssh_host_key(pve_client, csrf_header):
    c, _ = pve_client
    hid = c.post("/api/v1/hosts", json=HOST, headers=csrf_header(c)).json()["id"]
    r = c.patch(f"/api/v1/hosts/{hid}",
                json={"ssh_host_key_fingerprint": "SHA256:the-new-one"},
                headers=csrf_header(c))
    assert r.status_code == 200, r.text
    with c.app.state.sessionmaker() as db:
        from proxploy.models import Host
        assert db.get(Host, hid).ssh_host_key_fingerprint == "SHA256:the-new-one"


def test_patching_the_ssh_pin_to_null_clears_it_for_tofu(pve_client, csrf_header):
    """Null is a real value here, the same as for tls_fingerprint and team_id:
    it means "stop pinning", so the next connection learns the key again."""
    c, _ = pve_client
    hid = c.post("/api/v1/hosts", json=HOST, headers=csrf_header(c)).json()["id"]
    c.patch(f"/api/v1/hosts/{hid}", json={"ssh_host_key_fingerprint": "SHA256:x"},
            headers=csrf_header(c))
    r = c.patch(f"/api/v1/hosts/{hid}", json={"ssh_host_key_fingerprint": None},
                headers=csrf_header(c))
    assert r.status_code == 200, r.text
    with c.app.state.sessionmaker() as db:
        from proxploy.models import Host
        assert db.get(Host, hid).ssh_host_key_fingerprint is None


def test_an_omitted_ssh_pin_is_left_alone_by_an_unrelated_patch(pve_client,
                                                                csrf_header):
    """An omitted field must not clear the pin on every rename."""
    c, _ = pve_client
    hid = c.post("/api/v1/hosts", json=HOST, headers=csrf_header(c)).json()["id"]
    c.patch(f"/api/v1/hosts/{hid}", json={"ssh_host_key_fingerprint": "SHA256:keep"},
            headers=csrf_header(c))
    c.patch(f"/api/v1/hosts/{hid}", json={"name": "renamed-host"},
            headers=csrf_header(c))
    with c.app.state.sessionmaker() as db:
        from proxploy.models import Host
        assert db.get(Host, hid).ssh_host_key_fingerprint == "SHA256:keep"


def test_ssh_verify_hands_back_both_fingerprints_on_a_mismatch(tmp_path,
                                                               csrf_header,
                                                               bootstrap_admin):
    """The operator has to be offered the key the node is presenting, not be
    asked to read it out of an error message."""
    from proxploy.executor.ssh import SSHHostKeyMismatch
    from tests.fakes.pve import FakePVE
    from tests.support import make_app, seed_host_row
    from fastapi.testclient import TestClient
    from proxploy.models import HostCredential

    async def refusing_factory(host, key_pem, *, pinned_fingerprint,
                               on_new_fingerprint, port=22):
        raise SSHHostKeyMismatch("host key changed: pinned A, saw B",
                                 pinned="SHA256:A", seen="SHA256:B")

    app = make_app(tmp_path, fake=FakePVE())
    c = TestClient(app)
    with c:
        # Inside the block: create_app's lifespan assigns this, so setting it
        # before entering would be overwritten and the test would dial the real
        # address in the fixture.
        app.state.ssh_connect_factory = refusing_factory
        bootstrap_admin(c)
        with app.state.sessionmaker() as db:
            h = seed_host_row(db)
            # A real key: run_for_host imports it before the factory is
            # reached, so a placeholder blob fails earlier than the case
            # under test.
            import asyncssh
            pem = asyncssh.generate_private_key("ssh-ed25519").export_private_key()
            blob, ver = app.state.secretstore.encrypt(pem)
            db.add(HostCredential(host_id=h.id, kind="ssh_key",
                                  encrypted_blob=blob, key_version=ver))
            db.commit()
            hid = h.id
        r = c.post(f"/api/v1/hosts/{hid}/ssh/verify", headers=csrf_header(c))
        assert r.status_code == 502, r.text
        body = r.json()
        assert body["error"] == "host_key_mismatch"
        assert body["ssh_host_key_fingerprint"] == "SHA256:A"
        assert body["ssh_host_key_fingerprint_seen"] == "SHA256:B"


@pytest.mark.parametrize("path", [
    "/api/v1/hosts/abc",
    "/api/v1/apps/abc",
    "/api/v1/vms/abc",
])
def test_a_non_numeric_id_is_a_422_not_a_crash(pve_client, path):
    """PXP-30: the scope resolvers in api/deps.py run as sub-dependencies and
    read `request.path_params`, which holds the raw matched string, so the
    route signature's `int` annotation has not been applied yet. A bare
    `int(raw)` there turned a typo'd URL into a ValueError escaping the
    dependency. The route's own validation should answer instead.
    """
    c, _ = pve_client
    r = c.get(path)
    assert r.status_code == 422, r.text
def test_a_failed_ssh_enrolment_leaves_no_half_built_host(pve_client, csrf_header,
                                                          monkeypatch):
    """PXP-39: enrolment committed the Host row before minting its credentials,
    so anything that failed afterwards left a host that shows as enrolled in
    the UI and has nothing to authenticate with, and no route repairs it.
    One transaction means a failure leaves no host at all, which is a state
    the operator can act on: add it again.
    """
    import proxploy.api.hosts as hosts_api

    c, _ = pve_client
    monkeypatch.setattr(hosts_api, "generate_ed25519",
                        lambda _c: (_ for _ in ()).throw(RuntimeError("no entropy")))
    with pytest.raises(RuntimeError):
        c.post("/api/v1/hosts", json={**HOST, "ssh_enroll": True, "ssh_consent": True},
               headers=csrf_header(c))

    r = c.get("/api/v1/hosts")
    assert r.status_code == 200, r.text
    assert r.json() == [] or r.json() == {"items": []}


def test_node_shell_is_enabled_by_default_and_can_be_turned_off(pve_client, csrf_header):
    """Sys.Console rides the Console role now, so the privilege is always
    granted by onboarding and the toggle is the only thing left deciding
    whether a host may open a node shell. Defaulting it off made a granted
    privilege look broken, so a new host arrives with it on and an operator
    who does not want it turns it off."""
    c, _ = pve_client
    hid = c.post("/api/v1/hosts", json=HOST, headers=csrf_header(c)).json()["id"]

    assert c.get(f"/api/v1/hosts/{hid}").json()["node_shell_enabled"] is True

    r = c.patch(f"/api/v1/hosts/{hid}", json={"node_shell_enabled": False},
                headers=csrf_header(c))
    assert r.status_code == 200 and r.json()["node_shell_enabled"] is False
