# backend/tests/test_hosts_peers.py
"""GET /hosts/{id}/peers (discovery, phase 2) and POST /hosts/{id}/peers
(enrolment, phase 4) of the cluster peer auto-enrolment work.

Discovery is read only: nothing above the enrolment section may create a host
row or a credential row as a side effect of it.

One FakePVE per address (make_addressed_factory), because the whole point of
both routes is that they talk to a machine other than the one the host row
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


def _fake(**kwargs):
    """A FakePVE plus the two fields the test factory below reads."""
    fake = FakePVE(**kwargs)
    fake.rejects, fake.connects = set(), []
    return fake


@pytest.fixture
def peers_app(tmp_path, monkeypatch, bootstrap_admin, csrf_header):
    """(client, fakes, host_id) with one host enrolled at ORIGIN."""
    from proxploy.api.auth import limiter
    from proxploy.config import Settings
    from proxploy.main import create_app

    fakes = {ORIGIN: _fake(), PEER: _fake()}
    fakes[ORIGIN].cluster_status_rows = CLUSTER_ROWS

    def _fingerprint(host, port=8006):
        if fakes[host].fail:
            raise OSError("connection refused")
        return f"FP:{host}"

    monkeypatch.setattr("proxploy.api.hosts.tls_fingerprint_sha256", _fingerprint)
    # The origin is pinned at enrolment now (plan phase 3), so this is also the
    # certificate ProxmoxClient._connect checks that pin against. Same fake
    # node, one answer.
    monkeypatch.setattr("proxploy.services.proxmox.tls_fingerprint_sha256",
                        _fingerprint)
    base_factory = make_addressed_factory(fakes)

    def factory(**kwargs):
        """make_addressed_factory plus two things FakePVE cannot express: which
        token names a node refuses (a node whose /etc/pve has drifted answers
        for some tokens and not others), and the order the tokens were tried
        in, which is how "verified before it is written" is provable."""
        fake = fakes[kwargs["host"]]
        fake.connects.append(kwargs["token_name"])
        if kwargs["token_name"] in fake.rejects:
            raise PermissionError("401 authentication failure: invalid token")
        return base_factory(**kwargs)

    limiter.reset()
    s = Settings(db_url=f"sqlite:///{tmp_path}/t.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key", poll_enabled=False)
    app = create_app(s, proxmox_factory=factory)
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
    fakes["10.0.0.7"] = _fake()

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


# --- POST /hosts/{id}/peers: enrolment (phase 4) ---------------------------
# This half writes: host rows, credential rows copied from the origin, and
# audit rows. Every test here says what was written and what was not.

PEER3 = "10.0.0.7"
PVE3_ROW = {"type": "node", "name": "pve3", "local": 0, "online": 1, "ip": PEER3}


def _enrol(c, csrf_header, host_id, nodes, **extra):
    return c.post(f"/api/v1/hosts/{host_id}/peers",
                  json={"nodes": nodes, **extra}, headers=csrf_header(c))


def _add_third_node(fakes):
    fakes[ORIGIN].cluster_status_rows = CLUSTER_ROWS + [PVE3_ROW]
    fakes[PEER3] = _fake()


def test_enrolling_copies_every_api_token_and_verifies_each_on_the_peer(
        peers_app, csrf_header):
    """Same secret store and same key version, so the blob is copied as it is
    rather than decrypted and re-encrypted into a second place."""
    from proxploy.models import Host, HostCredential

    c, fakes, host_id = peers_app
    _add_capability(c, csrf_header, host_id, "lifecycle")
    _add_capability(c, csrf_header, host_id, "backup")
    fakes[PEER].connects.clear()

    r = _enrol(c, csrf_header, host_id, ["pve2"])
    assert r.status_code == 200, r.text
    row, = r.json()["results"]
    assert row["status"] == "enrolled"
    assert row["address"] == f"https://{PEER}:8006"
    assert row["capabilities_stored"] == ["monitoring", "lifecycle", "backup"]
    assert row["capabilities_failed"] == [] and row["detail"] is None
    # Every token was tried against the peer itself, monitoring first.
    assert fakes[PEER].connects == ["mon", "lifecycle", "backup"]

    with c.app.state.sessionmaker() as db:
        peer = db.query(Host).filter_by(name="pve2").one()
        assert row["host_id"] == peer.id
        assert (peer.address, peer.node_name, peer.cluster_name) == (
            f"https://{PEER}:8006", "pve2", "lab-cluster")
        assert peer.verify_tls is False and peer.pve_version == "8.4.1"
        copied = {cr.kind: cr for cr in
                  db.query(HostCredential).filter_by(host_id=peer.id)}
        assert sorted(copied) == ["api_token:backup", "api_token:lifecycle",
                                  "api_token:monitoring"]
        for kind, cr in copied.items():
            origin_cred = db.query(HostCredential).filter_by(
                host_id=host_id, kind=kind).one()
            assert (cr.encrypted_blob, cr.key_version, cr.public_meta) == (
                origin_cred.encrypted_blob, origin_cred.key_version,
                origin_cred.public_meta)


def test_a_peer_that_refuses_monitoring_leaves_no_host_row_and_no_credential(
        peers_app, csrf_header):
    """A host with no monitoring credential cannot poll, so there is nothing
    worth writing."""
    from proxploy.models import Host, HostCredential

    c, fakes, host_id = peers_app
    _add_capability(c, csrf_header, host_id, "lifecycle")
    fakes[PEER].rejects = {"mon"}
    with c.app.state.sessionmaker() as db:
        before = (db.query(Host).count(), db.query(HostCredential).count())

    row, = _enrol(c, csrf_header, host_id, ["pve2"]).json()["results"]
    assert row["status"] == "failed" and row["host_id"] is None
    assert row["capabilities_stored"] == []
    assert "refused the monitoring token" in row["detail"]
    assert "Nothing was stored" in row["detail"]
    with c.app.state.sessionmaker() as db:
        assert (db.query(Host).count(), db.query(HostCredential).count()) == before


def test_a_peer_that_refuses_lifecycle_is_still_enrolled_with_it_named(
        peers_app, csrf_header):
    """The other outcome, deliberately different: the peer is added and works,
    that one capability is left unconfigured."""
    from proxploy.models import Host, HostCredential

    c, fakes, host_id = peers_app
    _add_capability(c, csrf_header, host_id, "lifecycle")
    fakes[PEER].rejects = {"lifecycle"}

    row, = _enrol(c, csrf_header, host_id, ["pve2"]).json()["results"]
    assert row["status"] == "enrolled"
    assert row["capabilities_stored"] == ["monitoring"]
    assert row["capabilities_failed"] == ["lifecycle"]
    assert "was added" in row["detail"]
    assert "Lifecycle is not configured" in row["detail"]
    with c.app.state.sessionmaker() as db:
        peer = db.query(Host).filter_by(name="pve2").one()
        assert [cr.kind for cr in
                db.query(HostCredential).filter_by(host_id=peer.id)] == [
            "api_token:monitoring"]


def test_one_failing_peer_does_not_stop_another_in_the_same_request(
        peers_app, csrf_header):
    from proxploy.models import Host

    c, fakes, host_id = peers_app
    _add_third_node(fakes)
    fakes[PEER].fail = True

    dead, live = _enrol(c, csrf_header, host_id, ["pve2", "pve3"]).json()["results"]
    assert dead["node"] == "pve2" and dead["status"] == "failed"
    assert "did not answer on port 8006" in dead["detail"]
    assert live["node"] == "pve3" and live["status"] == "enrolled"
    with c.app.state.sessionmaker() as db:
        assert sorted(h.name for h in db.query(Host)) == ["pve-01", "pve3"]


def test_the_peer_stores_its_own_fingerprint_and_never_the_origins(
        peers_app, csrf_header):
    """Cluster nodes serve distinct certificates, so an inherited pin would
    refuse every connection to the peer."""
    from proxploy.models import Host

    c, _, host_id = peers_app
    _enrol(c, csrf_header, host_id, ["pve2"])
    with c.app.state.sessionmaker() as db:
        assert db.get(Host, host_id).tls_fingerprint == f"FP:{ORIGIN}"
        assert db.query(Host).filter_by(name="pve2").one().tls_fingerprint == \
            f"FP:{PEER}"


def test_a_peer_presenting_a_different_certificate_is_not_added(
        peers_app, csrf_header):
    """The operator read a fingerprint in the panel and ticked the box on the
    strength of it. If the node is presenting something else by the time they
    confirm, they never approved this certificate."""
    from proxploy.models import Host, HostCredential

    c, fakes, host_id = peers_app
    _add_third_node(fakes)
    with c.app.state.sessionmaker() as db:
        before = (db.query(Host).count(), db.query(HostCredential).count())

    changed, live = _enrol(c, csrf_header, host_id, ["pve2", "pve3"],
                           tls_fingerprints={"pve2": "FP:SHOWN-EARLIER"}
                           ).json()["results"]
    assert changed["node"] == "pve2" and changed["status"] == "failed"
    assert changed["host_id"] is None
    assert "different TLS certificate" in changed["detail"]
    assert "stop and investigate" in changed["detail"]
    # Both in full, so the operator can compare them against the node itself.
    assert "FP:SHOWN-EARLIER" in changed["detail"]
    assert f"FP:{PEER}" in changed["detail"]
    # One refused peer never stops another.
    assert live["node"] == "pve3" and live["status"] == "enrolled"
    with c.app.state.sessionmaker() as db:
        assert db.query(Host).filter_by(name="pve2").one_or_none() is None
        assert (db.query(Host).count(), db.query(HostCredential).count()) == (
            before[0] + 1, before[1] + 1)


def test_a_peer_with_no_echoed_fingerprint_enrols_as_it_always_did(
        peers_app, csrf_header):
    """Backwards tolerant on purpose: the field is optional per node, so a
    caller that sends none behaves exactly as before it existed."""
    c, fakes, host_id = peers_app
    _add_third_node(fakes)

    unechoed, echoed = _enrol(c, csrf_header, host_id, ["pve2", "pve3"],
                              tls_fingerprints={"pve3": f"FP:{PEER3}"}
                              ).json()["results"]
    assert unechoed["status"] == "enrolled" and echoed["status"] == "enrolled"


def test_the_echoed_fingerprint_is_never_what_gets_stored(peers_app, csrf_header):
    """It is only ever used to refuse. The pin always comes from Proxploy's
    own probe of that peer, which is what stops the probe being optimised
    away later in favour of whatever the caller sent."""
    from proxploy.models import Host

    c, _, host_id = peers_app
    # Matches case-insensitively, the way _connect and the Edit dialog compare.
    row, = _enrol(c, csrf_header, host_id, ["pve2"],
                  tls_fingerprints={"pve2": f"fp:{PEER}"}).json()["results"]
    assert row["status"] == "enrolled"
    with c.app.state.sessionmaker() as db:
        assert db.query(Host).filter_by(name="pve2").one().tls_fingerprint == \
            f"FP:{PEER}"


def test_an_unpinned_origin_is_pinned_first_and_a_pinned_one_is_left_alone(
        peers_app, csrf_header, monkeypatch):
    """Hosts enrolled before pinning existed have no pin. Without this, one
    cluster would hold pinned peers and an unpinned origin."""
    from proxploy.models import Host

    c, _, host_id = peers_app
    probed = []

    def _recording(host, port=8006):
        probed.append(host)
        return f"FP:{host}"

    monkeypatch.setattr("proxploy.api.hosts.tls_fingerprint_sha256", _recording)
    with c.app.state.sessionmaker() as db:
        db.get(Host, host_id).tls_fingerprint = None
        db.commit()

    _enrol(c, csrf_header, host_id, ["pve2"])
    assert ORIGIN in probed
    with c.app.state.sessionmaker() as db:
        assert db.get(Host, host_id).tls_fingerprint == f"FP:{ORIGIN}"

    # Already pinned: not re-probed, and whatever it holds is kept.
    probed.clear()
    _enrol(c, csrf_header, host_id, ["pve2"])
    assert ORIGIN not in probed
    with c.app.state.sessionmaker() as db:
        assert db.get(Host, host_id).tls_fingerprint == f"FP:{ORIGIN}"


def test_a_name_clash_fails_only_that_peer(peers_app, csrf_header):
    """The skip rules have already excluded the same machine, so a remaining
    clash is a different machine wearing the name."""
    from proxploy.models import Host

    c, fakes, host_id = peers_app
    _add_third_node(fakes)
    with c.app.state.sessionmaker() as db:
        db.add(Host(name="pve2", address="https://10.9.9.9:8006",
                    status="connected"))
        db.commit()

    clash, live = _enrol(c, csrf_header, host_id, ["pve2", "pve3"]).json()["results"]
    assert clash["status"] == "failed" and clash["host_id"] is None
    assert "different host called pve2" in clash["detail"]
    assert "https://10.9.9.9:8006" in clash["detail"]
    assert "still added" in clash["detail"]
    assert live["node"] == "pve3" and live["status"] == "enrolled"


def test_a_peer_already_in_proxploy_is_skipped_and_nothing_is_written(
        peers_app, csrf_header):
    """The skip rules are re-applied here, not trusted from discovery:
    minutes can pass between the two calls."""
    from proxploy.models import Host, HostCredential

    c, _, host_id = peers_app
    with c.app.state.sessionmaker() as db:
        db.add(Host(name="pve-02", address="https://pve2.internal:8006",
                    node_name="pve2", cluster_name="lab-cluster", status="connected"))
        db.commit()
        before = (db.query(Host).count(), db.query(HostCredential).count())

    row, = _enrol(c, csrf_header, host_id, ["pve2"]).json()["results"]
    assert row["status"] == "skipped" and row["host_id"] is None
    assert "already in Proxploy as pve-02" in row["detail"]
    with c.app.state.sessionmaker() as db:
        assert (db.query(Host).count(), db.query(HostCredential).count()) == before


def test_no_ssh_key_is_copied_and_consent_and_node_shell_are_not_inherited(
        peers_app, csrf_header):
    """The SSH key is a root shell on the node, a different trust decision
    from an API token, and that separation is why this feature exists."""
    from proxploy.models import Host, HostCredential, utcnow

    c, _, host_id = peers_app
    r = c.post(f"/api/v1/hosts/{host_id}/credentials", json={"rotate_ssh": True},
               headers=csrf_header(c))
    assert r.status_code == 200, r.text
    with c.app.state.sessionmaker() as db:
        origin = db.get(Host, host_id)
        origin.node_shell_enabled, origin.install_consent_at = True, utcnow()
        db.commit()

    _enrol(c, csrf_header, host_id, ["pve2"])
    with c.app.state.sessionmaker() as db:
        peer = db.query(Host).filter_by(name="pve2").one()
        assert peer.node_shell_enabled is False
        assert peer.install_consent_at is None
        assert [cr.kind for cr in
                db.query(HostCredential).filter_by(host_id=peer.id)] == [
            "api_token:monitoring"]


def test_the_audits_name_the_origin_and_every_copied_capability(
        peers_app, csrf_header):
    from proxploy.models import AuditEvent, Host

    c, _, host_id = peers_app
    _add_capability(c, csrf_header, host_id, "lifecycle")
    _enrol(c, csrf_header, host_id, ["pve2"])

    with c.app.state.sessionmaker() as db:
        peer_id = db.query(Host).filter_by(name="pve2").one().id
        events = db.query(AuditEvent).filter_by(target_id=peer_id).all()
        created = [e for e in events if e.action == "host.create"]
        assert len(created) == 1
        assert created[0].params["node"] == "pve2"
        assert created[0].params["via_host_id"] == host_id
        assert created[0].params["via_node"] == "pve1"
        copied = [e for e in events if e.action == "host.credentials"]
        assert [e.params["capability"] for e in copied] == ["monitoring",
                                                            "lifecycle"]
        assert {e.params["copied_from_host_id"] for e in copied} == {host_id}


def test_a_node_the_cluster_does_not_name_is_a_per_peer_failure(
        peers_app, csrf_header):
    """The caller sends node names only. An address in the body is not a
    field, so it can never aim an enrolment at a machine of its choosing."""
    from proxploy.models import Host

    c, _, host_id = peers_app
    row, = _enrol(c, csrf_header, host_id, ["pve9"],
                  address="https://10.9.9.9:8006").json()["results"]
    assert row["status"] == "failed" and row["host_id"] is None
    assert row["address"] is None and "pve9" in row["detail"]
    with c.app.state.sessionmaker() as db:
        assert db.query(Host).count() == 1

    row, = _enrol(c, csrf_header, host_id, ["pve2"],
                  address="https://10.9.9.9:8006").json()["results"]
    assert row["address"] == f"https://{PEER}:8006"
    with c.app.state.sessionmaker() as db:
        assert db.query(Host).filter_by(name="pve2").one().address == \
            f"https://{PEER}:8006"


def test_the_peer_carries_the_origins_team_and_a_teamless_origin_stays_teamless(
        peers_app, csrf_header):
    """A cluster is never half inside a team and half outside it."""
    from proxploy.models import Host, Team

    c, fakes, host_id = peers_app
    _add_third_node(fakes)
    with c.app.state.sessionmaker() as db:
        team_id = db.query(Team).filter_by(slug="default").one().id
        db.get(Host, host_id).team_id = team_id
        db.commit()

    _enrol(c, csrf_header, host_id, ["pve2"])
    with c.app.state.sessionmaker() as db:
        assert db.query(Host).filter_by(name="pve2").one().team_id == team_id
        db.get(Host, host_id).team_id = None
        db.commit()

    _enrol(c, csrf_header, host_id, ["pve3"])
    with c.app.state.sessionmaker() as db:
        assert db.query(Host).filter_by(name="pve3").one().team_id is None


def test_enrolment_is_refused_without_the_multi_host_entitlement(
        peers_app, csrf_header):
    """A peer is never the first host, so the same 403 create_host returns."""
    from proxploy.models import Host

    c, _, host_id = peers_app
    c.app.state.entitlements._features["hosts.multi"] = False

    r = _enrol(c, csrf_header, host_id, ["pve2"])
    assert r.status_code == 403
    body = r.json()
    assert (body["error"], body["feature"]) == ("entitlement_required",
                                                "hosts.multi")
    with c.app.state.sessionmaker() as db:
        assert db.query(Host).count() == 1


def test_enrolment_needs_an_owner(peers_app, csrf_header):
    """Copying stored secrets into new rows is the same severity class as
    rotating them, so admin is not enough."""
    c, _, host_id = peers_app
    with TestClient(c.app) as anon:
        assert _enrol(anon, csrf_header, host_id, ["pve2"]).status_code == 401

    c.post("/api/v1/users", json={"email": "admin2@example.com",
                                  "password": "correct-horse-battery",
                                  "display_name": "A", "role": "admin"},
           headers=csrf_header(c))
    c.post("/api/v1/auth/login", json={"email": "admin2@example.com",
                                       "password": "correct-horse-battery"},
           headers=csrf_header(c))
    assert _enrol(c, csrf_header, host_id, ["pve2"]).status_code == 403


def test_an_empty_node_list_is_refused(peers_app, csrf_header):
    c, _, host_id = peers_app
    assert _enrol(c, csrf_header, host_id, []).status_code == 422


# --- a split-network cluster: corosync address is not the API address --------
#
# /cluster/status reports only `ip`, which is corosync's ring0 address. PVE
# stores `ring0_addr` and `pve_addr` as SEPARATE fields in
# /cluster/config/join, which is what confirms they can differ (doc 12 check
# 13). On a cluster with a dedicated corosync link, building peers from
# /cluster/status offers every peer at an address the API never answers on, so
# discovery reports them all unreachable and enrolment cannot add any of them.

COROSYNC_ONLY = "10.9.9.2"   # deliberately has no FakePVE: nothing answers here

SPLIT_ROWS = [
    {"type": "cluster", "name": "lab-cluster"},
    {"type": "node", "name": "pve1", "local": 1, "online": 1, "ip": ORIGIN},
    # The corosync address, which is all /cluster/status ever reports.
    {"type": "node", "name": "pve2", "local": 0, "online": 1, "ip": COROSYNC_ONLY},
]
SPLIT_JOIN = {"nodelist": [
    {"name": "pve1", "ring0_addr": ORIGIN, "pve_addr": ORIGIN},
    {"name": "pve2", "ring0_addr": COROSYNC_ONLY, "pve_addr": PEER},
]}


def test_discovery_uses_the_api_address_not_the_corosync_one(peers_app):
    c, fakes, host_id = peers_app
    fakes[ORIGIN].cluster_status_rows = SPLIT_ROWS
    fakes[ORIGIN].cluster_join_info = SPLIT_JOIN

    peer = c.get(f"/api/v1/hosts/{host_id}/peers").json()["peers"][0]
    assert peer["node"] == "pve2"
    # The whole point: PEER, not COROSYNC_ONLY.
    assert peer["address"] == f"https://{PEER}:8006"
    # And because it is the address the API actually answers on, the peer is
    # reachable rather than being reported dead at a corosync-only address.
    assert peer["reachable"] is True
    assert peer["error"] is None


def test_discovery_falls_back_when_join_info_is_unreadable(peers_app):
    """Best effort by design: an unreadable /cluster/config/join must not fail
    discovery, it must leave it exactly as it was before this existed."""
    c, fakes, host_id = peers_app
    fakes[ORIGIN].cluster_status_rows = CLUSTER_ROWS
    fakes[ORIGIN].cluster_join_info = {}      # no nodelist at all

    peer = c.get(f"/api/v1/hosts/{host_id}/peers").json()["peers"][0]
    assert peer["address"] == f"https://{PEER}:8006"
    assert peer["reachable"] is True


def test_a_node_missing_from_join_info_still_uses_its_cluster_status_address(peers_app):
    """Per node, not all or nothing: a nodelist that omits one node must not
    strand that node."""
    c, fakes, host_id = peers_app
    fakes[ORIGIN].cluster_status_rows = CLUSTER_ROWS
    fakes[ORIGIN].cluster_join_info = {"nodelist": [
        {"name": "pve1", "ring0_addr": ORIGIN, "pve_addr": ORIGIN}]}

    peer = c.get(f"/api/v1/hosts/{host_id}/peers").json()["peers"][0]
    assert peer["address"] == f"https://{PEER}:8006"


def test_enrolment_adds_the_peer_at_the_api_address_it_was_shown_at(peers_app,
                                                                    csrf_header):
    """Discovery and enrolment must not disagree about an address: enrolment
    re-derives everything rather than trusting the caller, so it has to read
    the same source."""
    from proxploy.models import Host

    c, fakes, host_id = peers_app
    fakes[ORIGIN].cluster_status_rows = SPLIT_ROWS
    fakes[ORIGIN].cluster_join_info = SPLIT_JOIN

    r = c.post(f"/api/v1/hosts/{host_id}/peers", json={"nodes": ["pve2"]},
               headers=csrf_header(c))
    assert r.status_code == 200, r.text
    row = r.json()["results"][0]
    assert row["status"] == "enrolled", row
    assert row["address"] == f"https://{PEER}:8006"
    with c.app.state.sessionmaker() as db:
        added = db.query(Host).filter_by(name="pve2").one()
        assert added.address == f"https://{PEER}:8006"
