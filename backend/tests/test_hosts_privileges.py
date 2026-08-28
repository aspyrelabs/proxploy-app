"""Enrolment checks the token can actually do the monitoring reads.

Doc 08 §"Onboarding flow" step 4: verification calls GET /version, then
GET /access/permissions, and diffs the granted privileges against the
expected set. Only the /version half was ever built, and /version succeeds
for a privilege-separated token holding no ACLs at all. So a token that
could not read /nodes/<n>/rrddata (Sys.Audit) sailed through onboarding and
surfaced minutes later as the host being "unreachable".
"""
import json
from pathlib import Path

FIX = Path(__file__).parent / "fixtures" / "pve"

PROBE = {"address": "https://10.0.0.7:8006", "token_id": "proxploy@pve!mon",
         "token_secret": "s3cret", "verify_tls": False}


def _client(tmp_path, permissions):
    from fastapi.testclient import TestClient
    from tests.fakes.pve import FakePVE
    from tests.support import make_app

    fake = FakePVE(permissions=permissions,
                   resources=[{"type": "node", "node": "pve1", "status": "online"}])
    return TestClient(make_app(tmp_path, fake=fake))


def test_probe_reports_the_privileges_the_token_is_missing(tmp_path, csrf_header,
                                                           bootstrap_admin):
    # A privsep token with no ACLs: exactly what `pveum user token add` makes
    # by default, and what shipped a broken host on real hardware.
    c = _client(tmp_path, permissions={})
    with c:
        bootstrap_admin(c)
        r = c.post("/api/v1/hosts/probe", json=PROBE, headers=csrf_header(c))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True          # it connected; that part was never wrong
        assert "Sys.Audit" in body["missing_privileges"]
        assert "VM.Audit" in body["missing_privileges"]


def test_probe_is_clean_for_a_fully_granted_token(tmp_path, csrf_header,
                                                  bootstrap_admin):
    perms = {"/": {"Sys.Audit": 1, "VM.Audit": 1, "Datastore.Audit": 1,
                   "Pool.Audit": 1, "SDN.Audit": 1}}
    c = _client(tmp_path, permissions=perms)
    with c:
        bootstrap_admin(c)
        r = c.post("/api/v1/hosts/probe", json=PROBE, headers=csrf_header(c))
        assert r.json()["missing_privileges"] == []


def test_a_privilege_granted_on_a_narrower_path_counts(tmp_path, csrf_header,
                                                       bootstrap_admin):
    # Doc 08: scoping Proxploy to a pool is supported. A privilege granted
    # only on /pool/x is still granted, so it must not be reported missing.
    perms = {"/pool/prod": {"Sys.Audit": 1, "VM.Audit": 1, "Datastore.Audit": 1,
                            "Pool.Audit": 1, "SDN.Audit": 1}}
    c = _client(tmp_path, permissions=perms)
    with c:
        bootstrap_admin(c)
        r = c.post("/api/v1/hosts/probe", json=PROBE, headers=csrf_header(c))
        assert r.json()["missing_privileges"] == []


def test_enrolment_records_missing_privileges_on_the_host(tmp_path, csrf_header,
                                                          bootstrap_admin):
    from proxploy.models import Host

    c = _client(tmp_path, permissions={})
    with c:
        bootstrap_admin(c)
        r = c.post("/api/v1/hosts", json={**PROBE, "name": "pve-01"},
                   headers=csrf_header(c))
        # Deliberately NOT a refusal: a token can be under-privileged for
        # optional features and still worth enrolling, and locking someone out
        # of their own host at the last step is worse than telling them.
        assert r.status_code == 201, r.text

        app = c.app
        with app.state.sessionmaker() as db:
            h = db.query(Host).one()
            assert h.last_error and "Sys.Audit" in h.last_error

        detail = c.get(f"/api/v1/hosts/{r.json()['id']}").json()
        assert "Sys.Audit" in detail["last_error"]


def test_a_permission_read_that_fails_does_not_block_enrolment(tmp_path, csrf_header,
                                                               bootstrap_admin):
    # Some PVE setups refuse /access/permissions to a token. Unknown must not
    # masquerade as "missing", and must never cost the operator the enrolment.
    from tests.fakes.pve import FakePVE
    from tests.support import make_app
    from fastapi.testclient import TestClient

    fake = FakePVE(resources=[{"type": "node", "node": "pve1", "status": "online"}])
    fake.access.permissions._fail = True   # _Leaf's own attribute name
    c = TestClient(make_app(tmp_path, fake=fake))
    with c:
        bootstrap_admin(c)
        r = c.post("/api/v1/hosts/probe", json=PROBE, headers=csrf_header(c))
        assert r.status_code == 200, r.text
        assert r.json()["missing_privileges"] is None   # unknown, not empty


# --- Sys.PowerMgmt: node power reported before the user ever tries ---------
#
# Node power (reboot/power off the whole host) is offered on every host page
# unconditionally, unlike Lifecycle/Console/Backup which are opt-in
# checkboxes; a user only discovers their token cannot use it by trying, which
# used to mean a bare Proxmox 403. Checked and reported the same way
# monitoring privileges are, so it is known before it is tried.

def test_probe_reports_node_power_missing_when_the_token_lacks_it(tmp_path, csrf_header,
                                                                  bootstrap_admin):
    c = _client(tmp_path, permissions={})
    with c:
        bootstrap_admin(c)
        r = c.post("/api/v1/hosts/probe", json=PROBE, headers=csrf_header(c))
        assert r.status_code == 200, r.text
        assert r.json()["node_power_missing"] is True


def test_probe_reports_node_power_present_when_granted(tmp_path, csrf_header,
                                                        bootstrap_admin):
    perms = {"/": {"Sys.PowerMgmt": 1}}
    c = _client(tmp_path, permissions=perms)
    with c:
        bootstrap_admin(c)
        r = c.post("/api/v1/hosts/probe", json=PROBE, headers=csrf_header(c))
        assert r.json()["node_power_missing"] is False


def test_a_node_power_privilege_granted_on_a_narrower_path_counts(tmp_path, csrf_header,
                                                                  bootstrap_admin):
    perms = {"/pool/prod": {"Sys.PowerMgmt": 1}}
    c = _client(tmp_path, permissions=perms)
    with c:
        bootstrap_admin(c)
        r = c.post("/api/v1/hosts/probe", json=PROBE, headers=csrf_header(c))
        assert r.json()["node_power_missing"] is False


def test_a_permission_read_that_fails_reports_node_power_as_unknown(tmp_path, csrf_header,
                                                                    bootstrap_admin):
    from tests.fakes.pve import FakePVE
    from tests.support import make_app
    from fastapi.testclient import TestClient

    fake = FakePVE(resources=[{"type": "node", "node": "pve1", "status": "online"}])
    fake.access.permissions._fail = True
    c = TestClient(make_app(tmp_path, fake=fake))
    with c:
        bootstrap_admin(c)
        r = c.post("/api/v1/hosts/probe", json=PROBE, headers=csrf_header(c))
        assert r.json()["node_power_missing"] is None   # unknown, not "missing"


def test_enrolment_records_node_power_missing_on_the_host(tmp_path, csrf_header,
                                                          bootstrap_admin):
    from proxploy.models import Host

    c = _client(tmp_path, permissions={})
    with c:
        bootstrap_admin(c)
        r = c.post("/api/v1/hosts", json={**PROBE, "name": "pve-01"},
                   headers=csrf_header(c))
        assert r.status_code == 201, r.text

        # Unknown at enrolment, not True: Sys.PowerMgmt rides on Lifecycle's
        # role and no lifecycle token has been stored yet, so the monitoring
        # token cannot answer for it either way.
        app = c.app
        with app.state.sessionmaker() as db:
            h = db.query(Host).one()
            assert h.node_power_missing is None

        detail = c.get(f"/api/v1/hosts/{r.json()['id']}").json()
        assert detail["node_power_missing"] is None


def test_an_existing_token_missing_node_power_still_enrols_cleanly_and_keeps_everything_else(
        tmp_path, csrf_header, bootstrap_admin):
    """node_power_missing is informational, never a refusal: a token with a
    perfectly good monitoring grant must enrol exactly as it always did, and
    say nothing either way about a privilege that lives on a token this host
    has not been given yet."""
    perms = {"/": {"Sys.Audit": 1, "VM.Audit": 1, "Datastore.Audit": 1,
                   "Pool.Audit": 1, "SDN.Audit": 1}}
    c = _client(tmp_path, permissions=perms)
    with c:
        bootstrap_admin(c)
        r = c.post("/api/v1/hosts", json={**PROBE, "name": "pve-01"},
                   headers=csrf_header(c))
        assert r.status_code == 201, r.text
        assert r.json()["missing_privileges"] == []
        assert r.json()["status"] == "connected"
        assert r.json()["node_power_missing"] is None


def test_the_test_endpoint_rechecks_node_power(tmp_path, csrf_header, bootstrap_admin):
    """POST /hosts/{id}/test re-probes, the same as it already does for
    reachability. With no lifecycle token stored there is nothing that could
    power the node, and the answer is a plain "missing" rather than the
    monitoring token's opinion."""
    from tests.fakes.pve import FakePVE
    from tests.support import make_app
    from fastapi.testclient import TestClient

    fake = FakePVE(permissions={},
                   resources=[{"type": "node", "node": "pve1", "status": "online"}])
    c = TestClient(make_app(tmp_path, fake=fake))
    with c:
        bootstrap_admin(c)
        r = c.post("/api/v1/hosts", json={**PROBE, "name": "pve-01"},
                   headers=csrf_header(c))
        host_id = r.json()["id"]
        assert r.json()["node_power_missing"] is None

        fake.access.permissions._value = {"/": {"Sys.PowerMgmt": 1}}

        r2 = c.post(f"/api/v1/hosts/{host_id}/test", headers=csrf_header(c))
        assert r2.status_code == 200, r2.text
        assert r2.json()["node_power_missing"] is True

        detail = c.get(f"/api/v1/hosts/{host_id}").json()
        assert detail["node_power_missing"] is True


# --- capability gaps: every token against its OWN role ----------------------

def _host_with_tokens(app, caps, permissions_by_cap=None):
    """One host carrying a token per capability in `caps`."""
    import json as _json

    from proxploy.models import Host, HostCredential
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.7:8006",
                    node_name="pve1", status="connected", pve_version="9.2.10")
        db.add(host)
        db.commit()
        for cap in caps:
            blob, ver = app.state.secretstore.encrypt(_json.dumps(
                {"token_id": f"proxploy@pve!{cap}",
                 "token_secret": "s3cret"}).encode())
            db.add(HostCredential(host_id=host.id, kind=f"api_token:{cap}",
                                  encrypted_blob=blob, key_version=ver,
                                  public_meta=f"proxploy@pve!{cap}"))
        db.commit()
        return host.id


def test_test_route_reports_a_lifecycle_token_missing_a_newly_added_privilege(
        tmp_path, csrf_header, bootstrap_admin):
    """The drift case, which is not hypothetical.

    `SDN.Use` and `VM.Config.HWType` were added to the Lifecycle role on
    2026-08-18 after a real NIC write and a real VM create refused without them
    (doc 12 checks 7, 17, 18). Every token generated before that is short of
    them, and until this probe existed the only symptom was a 403 partway
    through a job.
    """
    from proxploy.services.pveum import CAPABILITIES

    lifecycle = set(CAPABILITIES["lifecycle"].privileges)
    monitoring = set(CAPABILITIES["monitoring"].privileges)
    # An "old" lifecycle token: everything except the two added that day.
    stale = lifecycle - {"SDN.Use", "VM.Config.HWType"}
    perms = {"/": {p: 1 for p in stale | monitoring}}

    c = _client(tmp_path, permissions=perms)
    with c:
        bootstrap_admin(c)
        host_id = _host_with_tokens(c.app, ("monitoring", "lifecycle"))
        r = c.post(f"/api/v1/hosts/{host_id}/test", headers=csrf_header(c))
        assert r.status_code == 200, r.text
        gaps = r.json()["capability_gaps"]

    assert sorted(gaps["lifecycle"]) == ["SDN.Use", "VM.Config.HWType"]
    # monitoring is fully granted here, so it must not appear at all
    assert "monitoring" not in gaps
    # console and backup have no token configured: not configuring one is a
    # choice, not a gap.
    assert "console" not in gaps and "backup" not in gaps


def test_a_token_refused_access_permissions_reports_unknown_not_clean(
        tmp_path, csrf_header, bootstrap_admin):
    """None means "could not tell". Reporting unknown as a clean bill of health
    is exactly how the monitoring probe failed silently before it existed."""
    from tests.fakes.pve import FakePVE
    from tests.support import make_app
    from fastapi.testclient import TestClient

    fake = FakePVE(resources=[{"type": "node", "node": "pve1", "status": "online"}])
    fake.permissions_fail = True           # /access/permissions refused
    c = TestClient(make_app(tmp_path, fake=fake))
    with c:
        bootstrap_admin(c)
        host_id = _host_with_tokens(c.app, ("monitoring", "lifecycle"))
        r = c.post(f"/api/v1/hosts/{host_id}/test", headers=csrf_header(c))
        gaps = r.json()["capability_gaps"]

    assert gaps["lifecycle"] is None and gaps["monitoring"] is None


def test_the_probe_result_is_stored_so_the_warning_is_not_only_on_demand(
        tmp_path, csrf_header, bootstrap_admin):
    """Pressing Test connection must not be the only way to learn this.

    The stored value is what the host page reads, and the poll loop refreshes it
    every half hour, so a host enrolled long ago surfaces its stale token without
    anyone going looking (doc 12 checks 17, 18).
    """
    from proxploy.models import Host
    from proxploy.services.pveum import CAPABILITIES

    lifecycle = set(CAPABILITIES["lifecycle"].privileges)
    monitoring = set(CAPABILITIES["monitoring"].privileges)
    stale = lifecycle - {"SDN.Use"}
    perms = {"/": {p: 1 for p in stale | monitoring}}

    c = _client(tmp_path, permissions=perms)
    with c:
        bootstrap_admin(c)
        host_id = _host_with_tokens(c.app, ("monitoring", "lifecycle"))
        with c.app.state.sessionmaker() as db:
            assert db.get(Host, host_id).capability_gaps is None  # never probed

        c.post(f"/api/v1/hosts/{host_id}/test", headers=csrf_header(c))

        with c.app.state.sessionmaker() as db:
            assert db.get(Host, host_id).capability_gaps == {"lifecycle": ["SDN.Use"]}
        # and it reaches the payload the host page reads
        listed = c.get("/api/v1/hosts").json()
        assert listed[0]["capability_gaps"] == {"lifecycle": ["SDN.Use"]}
