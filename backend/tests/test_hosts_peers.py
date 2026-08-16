# backend/tests/test_hosts_peers.py
"""GET /hosts/{id}/peers: cluster peer discovery, phase 2 of
docs/notes/cluster-peer-auto-enrolment-plan.md.

Read only. Nothing in this file may create a host row or a credential row as
a side effect of discovery; enrolment is phase 4 and has no route yet.

One FakePVE per address (make_addressed_factory), because the whole point of
the route is that it talks to a machine other than the one the host row
points at. tls_fingerprint_sha256 opens a real socket, so it is stubbed per
address the same way the PVE factory is.
"""
import pytest
from fastapi.testclient import TestClient

from tests.fakes.pve import FakePVE, make_addressed_factory

ORIGIN = "10.0.0.5"
PEER = "10.0.0.6"

# Same shape as test_hosts_lifecycle.py::test_enrolment_picks_the_local_node_
# out_of_a_cluster, plus the `ip` field discovery builds the peer address from.
CLUSTER_ROWS = [
    {"type": "cluster", "name": "lab-cluster"},
    {"type": "node", "name": "pve1", "local": 1, "online": 1, "ip": ORIGIN},
    {"type": "node", "name": "pve2", "local": 0, "online": 1, "ip": PEER},
]
STANDALONE_ROWS = [{"type": "node", "name": "pve1", "local": 1, "online": 1,
                    "ip": ORIGIN}]


@pytest.fixture
def peers_app(tmp_path, monkeypatch, bootstrap_admin, csrf_header):
    """(client, fakes, host_id) with one host enrolled at ORIGIN."""
    from proxploy.api.auth import limiter
    from proxploy.config import Settings
    from proxploy.main import create_app

    fakes = {ORIGIN: FakePVE(), PEER: FakePVE()}
    fakes[ORIGIN].cluster_status_rows = CLUSTER_ROWS

    def _fingerprint(host, port=8006):
        if fakes[host].fail:
            raise OSError("connection refused")
        return f"FP:{host}"

    monkeypatch.setattr("proxploy.api.hosts.tls_fingerprint_sha256", _fingerprint)
    limiter.reset()
    s = Settings(db_url=f"sqlite:///{tmp_path}/t.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key", poll_enabled=False)
    app = create_app(s, proxmox_factory=make_addressed_factory(fakes))
    with TestClient(app) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/hosts", json={
            "name": "pve-01", "address": f"https://{ORIGIN}:8006",
            "token_id": "proxploy@pve!mon", "token_secret": "s3cret",
            "verify_tls": False}, headers=csrf_header(c))
        assert r.status_code == 201, r.text
        yield c, fakes, r.json()["id"]


def _add_capability(c, csrf_header, host_id, capability):
    r = c.post(f"/api/v1/hosts/{host_id}/credentials",
               json={"token_id": f"proxploy@pve!{capability}",
                     "token_secret": "s3cret", "capability": capability},
               headers=csrf_header(c))
    assert r.status_code == 200, r.text


def test_discovery_lists_the_peer_and_never_the_local_node(peers_app, csrf_header):
    c, _, host_id = peers_app
    _add_capability(c, csrf_header, host_id, "lifecycle")

    r = c.get(f"/api/v1/hosts/{host_id}/peers")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cluster"] == "lab-cluster"
    assert [p["node"] for p in body["peers"]] == ["pve2"]
    peer = body["peers"][0]
    assert peer["address"] == f"https://{PEER}:8006"
    assert peer["online"] is True and peer["reachable"] is True
    assert peer["tls_fingerprint"] == f"FP:{PEER}"
    assert peer["already_enrolled_as"] is None and peer["error"] is None
    # The origin's own api_token:* kinds, in capability order. Never ssh_key.
    assert body["capabilities_to_copy"] == ["monitoring", "lifecycle"]
    assert body["multi_host_entitled"] is True

    c.app.state.entitlements._features["hosts.multi"] = False
    r = c.get(f"/api/v1/hosts/{host_id}/peers")
    assert r.status_code == 200, r.text
    assert r.json()["multi_host_entitled"] is False


def test_discovery_on_a_standalone_node_returns_no_cluster_and_no_peers(peers_app):
    c, fakes, host_id = peers_app
    fakes[ORIGIN].cluster_status_rows = STANDALONE_ROWS

    body = c.get(f"/api/v1/hosts/{host_id}/peers").json()
    assert body["cluster"] is None and body["peers"] == []


def test_an_already_enrolled_peer_is_matched_on_cluster_and_node_name(peers_app):
    """Never on address: the same machine enrolled under a DNS name or a
    second address is still the same machine."""
    from proxploy.models import Host

    c, _, host_id = peers_app
    with c.app.state.sessionmaker() as db:
        db.add(Host(name="pve-02", address="https://pve2.internal:8006",
                    node_name="pve2", cluster_name="lab-cluster", status="connected"))
        db.commit()

    peer = c.get(f"/api/v1/hosts/{host_id}/peers").json()["peers"][0]
    assert peer["node"] == "pve2" and peer["already_enrolled_as"] == "pve-02"

    # A row from before cluster detection, or one the poller has not filled in
    # yet, still counts: adding the same machine twice is the worse failure.
    with c.app.state.sessionmaker() as db:
        db.query(Host).filter_by(name="pve-02").one().cluster_name = None
        db.commit()
    peer = c.get(f"/api/v1/hosts/{host_id}/peers").json()["peers"][0]
    assert peer["already_enrolled_as"] == "pve-02"


def test_an_unreachable_peer_is_reported_with_a_reason_not_dropped(peers_app):
    """One dead node must never hide the live ones, and must never fail the
    whole call."""
    c, fakes, host_id = peers_app
    fakes[PEER].fail = True
    fakes[ORIGIN].cluster_status_rows = CLUSTER_ROWS + [
        {"type": "node", "name": "pve3", "local": 0, "online": 1, "ip": "10.0.0.7"}]
    fakes["10.0.0.7"] = FakePVE()

    r = c.get(f"/api/v1/hosts/{host_id}/peers")
    assert r.status_code == 200, r.text
    dead, live = r.json()["peers"]
    assert dead["node"] == "pve2" and dead["reachable"] is False
    assert dead["tls_fingerprint"] is None
    assert dead["error"]["kind"]
    assert "pve2" in dead["error"]["detail"] and PEER in dead["error"]["detail"]
    assert live["node"] == "pve3" and live["reachable"] is True


def test_discovery_reports_the_origins_team_as_an_id_and_a_name(peers_app):
    from proxploy.models import Host, Team

    c, _, host_id = peers_app
    with c.app.state.sessionmaker() as db:
        team = db.query(Team).filter_by(slug="default").one()
        db.get(Host, host_id).team_id = team.id
        db.commit()
        expected = {"id": team.id, "name": team.name}

    assert c.get(f"/api/v1/hosts/{host_id}/peers").json()["team"] == expected

    with c.app.state.sessionmaker() as db:
        db.get(Host, host_id).team_id = None
        db.commit()
    assert c.get(f"/api/v1/hosts/{host_id}/peers").json()["team"] is None


def test_discovery_needs_an_admin(peers_app, csrf_header):
    c, _, host_id = peers_app
    with TestClient(c.app) as anon:
        assert anon.get(f"/api/v1/hosts/{host_id}/peers").status_code == 401

    c.post("/api/v1/users", json={"email": "viewer@example.com",
                                  "password": "correct-horse-battery",
                                  "display_name": "V", "role": "viewer"},
           headers=csrf_header(c))
    c.post("/api/v1/auth/login", json={"email": "viewer@example.com",
                                       "password": "correct-horse-battery"},
           headers=csrf_header(c))
    assert c.get(f"/api/v1/hosts/{host_id}/peers").status_code == 403


def test_the_hosts_list_carries_cluster_name(peers_app):
    """The frontend works out which enrolled hosts are siblings from this. It
    is already on the model and already returned by POST /hosts."""
    c, _, _ = peers_app
    assert [h["cluster_name"] for h in c.get("/api/v1/hosts").json()] == ["lab-cluster"]


def test_discovery_writes_nothing(peers_app, csrf_header):
    from proxploy.models import Host, HostCredential

    c, _, host_id = peers_app
    with c.app.state.sessionmaker() as db:
        before = (db.query(Host).count(), db.query(HostCredential).count())
    assert c.get(f"/api/v1/hosts/{host_id}/peers").status_code == 200
    with c.app.state.sessionmaker() as db:
        assert (db.query(Host).count(), db.query(HostCredential).count()) == before
