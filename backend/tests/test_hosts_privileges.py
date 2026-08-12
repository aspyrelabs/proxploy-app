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

        app = c.app
        with app.state.sessionmaker() as db:
            h = db.query(Host).one()
            assert h.node_power_missing is True

        detail = c.get(f"/api/v1/hosts/{r.json()['id']}").json()
        assert detail["node_power_missing"] is True


def test_an_existing_token_missing_node_power_still_enrols_cleanly_and_keeps_everything_else(
        tmp_path, csrf_header, bootstrap_admin):
    """node_power_missing is informational, never a refusal: a token with a
    perfectly good monitoring grant (everything that worked before this
    feature existed) must enrol exactly as it always did, only now also
    telling the operator node power specifically is unavailable."""
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
        assert r.json()["node_power_missing"] is True


def test_the_test_endpoint_rechecks_node_power(tmp_path, csrf_header, bootstrap_admin):
    """POST /hosts/{id}/test re-probes the live token, the same as it already
    does for reachability: granting Sys.PowerMgmt after enrolment and then
    testing again must flip node_power_missing to False without re-enrolling."""
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
        assert r.json()["node_power_missing"] is True

        # Grant it, as if the operator had just run the extra pveum commands.
        # No clean setter exists on this test double: `_fail` above is the
        # same idiom, reaching past the leaf's own attribute name.
        fake.access.permissions._value = {"/": {"Sys.PowerMgmt": 1}}

        r2 = c.post(f"/api/v1/hosts/{host_id}/test", headers=csrf_header(c))
        assert r2.status_code == 200, r2.text
        assert r2.json()["node_power_missing"] is False

        detail = c.get(f"/api/v1/hosts/{host_id}").json()
        assert detail["node_power_missing"] is False
