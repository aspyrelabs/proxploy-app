"""Per-capability credential state on the host reads (capability-token capture).

Presence only: the UI needs to know whether a capability is configured and
nothing more, so a leak here is a leak of a Proxmox token.
"""
import json

from fastapi.testclient import TestClient

from proxploy.models import HostCredential
from proxploy.services.pveum import CAPABILITIES
from tests.support import make_app, seed_host_row


def _seed(app, kinds):
    """A host carrying exactly `kinds` credential rows."""
    with app.state.sessionmaker() as db:
        h = seed_host_row(db)
        for kind in kinds:
            blob, ver = app.state.secretstore.encrypt(json.dumps(
                {"token_id": f"proxploy@pve!{kind}", "token_secret": "s"}).encode())
            db.add(HostCredential(host_id=h.id, kind=kind, encrypted_blob=blob,
                                  key_version=ver,
                                  public_meta=f"proxploy@pve!{kind}"))
        db.commit()
        return h.id


def test_a_host_with_no_credentials_reports_every_capability_false(
        tmp_path, bootstrap_admin):
    """False, not an omitted field: the UI must never have to tell
    "absent" from "unknown"."""
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app, [])
        caps = c.get(f"/api/v1/hosts/{host_id}").json()["capabilities"]
        assert caps == {k: False for k in CAPABILITIES}


def test_monitoring_only_reports_just_monitoring(tmp_path, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app, ["api_token:monitoring", "ssh_key"])
        caps = c.get(f"/api/v1/hosts/{host_id}").json()["capabilities"]
        assert caps["monitoring"] is True
        assert caps["lifecycle"] is False and caps["backup"] is False


def test_all_capabilities_present(tmp_path, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app, [f"api_token:{k}" for k in CAPABILITIES])
        caps = c.get(f"/api/v1/hosts/{host_id}").json()["capabilities"]
        assert caps == {k: True for k in CAPABILITIES}


def test_the_list_route_reports_it_too(tmp_path, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _seed(app, ["api_token:monitoring", "api_token:lifecycle"])
        row = c.get("/api/v1/hosts").json()[0]
        assert row["capabilities"]["lifecycle"] is True
        assert row["capabilities"]["console"] is False


def test_capability_state_carries_no_token_material(tmp_path, bootstrap_admin):
    """Booleans and nothing else: no token id, no secret, no blob."""
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app, ["api_token:monitoring"])
        caps = c.get(f"/api/v1/hosts/{host_id}").json()["capabilities"]
        assert all(isinstance(v, bool) for v in caps.values())
        assert "proxploy@pve" not in json.dumps(caps)


def test_a_rejected_token_leaves_the_other_capabilities_and_the_host_alone(
        tmp_path, csrf_header, bootstrap_admin):
    """The partial-failure case the onboarding flow is built around: one
    capability's token is refused, everything already stored stays stored,
    and the host is still there."""
    from tests.fakes.pve import FakePVE

    app = make_app(tmp_path, fake=FakePVE(fail=True))
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app, ["api_token:monitoring", "api_token:lifecycle"])
        r = c.post(f"/api/v1/hosts/{host_id}/credentials",
                   json={"token_id": "proxploy@pve!console",
                         "token_secret": "bad", "capability": "console"},
                   headers=csrf_header(c))
        assert r.status_code == 502 and r.json()["error"] == "token_rejected"
        caps = c.get(f"/api/v1/hosts/{host_id}").json()["capabilities"]
        assert caps["monitoring"] is True and caps["lifecycle"] is True
        assert caps["console"] is False


def test_a_capability_added_to_CAPABILITIES_appears_with_no_second_list(
        tmp_path, bootstrap_admin, monkeypatch):
    """The one-definition rule, enforced rather than asserted in a comment."""
    from proxploy.services.pveum import Capability

    monkeypatch.setitem(CAPABILITIES, "teleportation", Capability(
        key="teleportation", label="Teleportation", role="ProxployTeleport",
        token="teleportation", privileges=("VM.Audit",), why="test only"))
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app, ["api_token:monitoring"])
        caps = c.get(f"/api/v1/hosts/{host_id}").json()["capabilities"]
        assert caps["teleportation"] is False


# GET /hosts/capabilities: the static catalogue (key/label/why/required) the
# HostForm reads to tell an operator what unticking a box gives up. Not to be
# confused with _capability_state above, which is per-host presence booleans.

def test_capabilities_route_lists_them_in_declaration_order(tmp_path, bootstrap_admin):
    """Monitoring first, matching CAPABILITIES's own order (the order the
    script emits), and only monitoring is required."""
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        r = c.get("/api/v1/hosts/capabilities")
        assert r.status_code == 200
        caps = r.json()
        assert isinstance(caps, list)
        assert [entry["key"] for entry in caps] == list(CAPABILITIES.keys())
        assert caps[0]["key"] == "monitoring" and caps[0]["required"] is True
        assert all(entry["required"] is False for entry in caps[1:])


def test_capabilities_route_carries_the_exact_label_and_why_from_pveum(
        tmp_path, bootstrap_admin):
    """Compared against the imported dataclass, never a pasted string: pveum.py
    stays the only place label/why text is written."""
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        caps = c.get("/api/v1/hosts/capabilities").json()
        for entry in caps:
            source = CAPABILITIES[entry["key"]]
            assert entry["label"] == source.label
            assert entry["why"] == source.why


def test_capabilities_route_omits_privileges_role_and_token(tmp_path, bootstrap_admin):
    """The UI needs why a capability matters, not the PVE privilege names or
    role/token identifiers that generate the script."""
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        caps = c.get("/api/v1/hosts/capabilities").json()
        for entry in caps:
            assert set(entry.keys()) == {"key", "label", "why", "required"}


def test_capabilities_route_is_not_shadowed_by_the_host_id_wildcard(
        tmp_path, bootstrap_admin):
    """A literal /capabilities segment must resolve to this route, not fall
    into GET /{host_id} with host_id="capabilities" (which would 404 as
    "no such host")."""
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        r = c.get("/api/v1/hosts/capabilities")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


def test_capabilities_route_requires_auth_like_the_other_host_reads(
        tmp_path, bootstrap_admin):
    """Same treatment as GET /hosts (list_hosts): anonymous is 401."""
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        assert c.get("/api/v1/hosts/capabilities").status_code == 200
    with TestClient(app) as anon:
        assert anon.get("/api/v1/hosts/capabilities").status_code == 401
