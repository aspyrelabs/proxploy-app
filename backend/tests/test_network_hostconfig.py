"""Host network staging + apply/revert (doc 01 §6 "Host network edit", Pro).

PVE stages every network edit into /etc/network/interfaces.new and does
nothing to the live config until PUT /nodes/{node}/network is called. A bad
bridge applied to a node takes that node off the network until someone walks
to it with a keyboard, the single most dangerous call in this phase, so
apply requires the node name typed back, mirroring selfguard's confirm shape.
"""
import asyncio
import json

from fastapi.testclient import TestClient

from proxploy.models import AuditEvent, Host, HostCredential, Job, JobEvent


def _seed(app):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.9:8006", node_name="pve1",
                    status="connected", pve_version="8.4.1")
        db.add(host)
        db.commit()
        # Bridge create/update/delete/apply/revert all run under "lifecycle"
        # (Sys.Modify -- api/network.py's host-config routes).
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!net", "token_secret": "s3cret"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token:lifecycle",
                              encrypted_blob=blob, key_version=ver))
        db.commit()
        return host.id


def _fake():
    from tests.fakes.pve import FakePVE

    f = FakePVE()
    f.networks_by_node = {"pve1": [{"iface": "vmbr0", "type": "bridge", "active": 1}]}
    return f


def test_create_bridge_stages_and_audits_without_a_job(tmp_path, csrf_header,
                                                       bootstrap_admin):
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app)
        r = c.post("/api/v1/network/bridges", headers=csrf_header(c),
                   json={"host_id": host_id, "node": "pve1", "iface": "vmbr9",
                         "type": "bridge",
                         "config": {"bridge_ports": "enp3s0", "autostart": 1,
                                    "cidr": "10.9.0.1/24"}})
        assert r.status_code == 201, r.text
        assert r.json()["staged"] is True
        assert fake.network_calls == [
            ("create", "pve1", None,
             {"iface": "vmbr9", "type": "bridge", "bridge_ports": "enp3s0",
              "autostart": 1, "cidr": "10.9.0.1/24"})]
        with app.state.sessionmaker() as db:
            assert db.query(Job).count() == 0
            row = db.query(AuditEvent).filter_by(action="network.host_config").one()
            assert row.target_type == "host" and row.target_id == host_id
            assert row.params["iface"] == "vmbr9" and row.params["op"] == "create"


def test_config_iface_collision_does_not_override_the_route_iface(tmp_path, csrf_header,
                                                                   bootstrap_admin):
    """BLOCKING 1 regression: `_SAFE_KEY` admits `iface`/`type` inside
    `config`, so a caller-supplied `config.iface` used to silently override
    the route's own, verified live: `{"iface": "vmbr9"..., "config":
    {"iface": "vmbr0", ...}}` staged a redefinition of vmbr0 (the management
    bridge) while claiming vmbr9 in both the response and the audit row.
    Asserted against what FakePVE actually recorded, not the response body,
    since the response body is exactly what lied before this fix."""
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app)
        r = c.post("/api/v1/network/bridges", headers=csrf_header(c),
                   json={"host_id": host_id, "node": "pve1", "iface": "vmbr9",
                         "type": "bridge",
                         "config": {"iface": "vmbr0", "type": "vlan"}})
        assert r.status_code == 201, r.text
        assert fake.network_calls == [
            ("create", "pve1", None, {"iface": "vmbr9", "type": "bridge"})]
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="network.host_config").one()
            assert row.params["iface"] == "vmbr9"  # the route's iface, not config's


def test_mutation_failure_is_a_502_with_an_error_audit_row(tmp_path, csrf_header,
                                                            bootstrap_admin):
    """BLOCKING 3: network.py's synchronous mutations used to have no
    ProxmoxError handling at all, a failed stage produced a bare 500 and no
    audit trace, unlike storage.py's identical routes."""
    from tests.support import make_app

    fake = _fake()
    fake.fail = True
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app)
        r = c.post("/api/v1/network/bridges", headers=csrf_header(c),
                   json={"host_id": host_id, "node": "pve1", "iface": "vmbr9",
                         "type": "bridge", "config": {}})
        assert r.status_code == 502
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="network.host_config").one()
            assert row.result == "error"


def test_update_and_delete_stage_through_to_the_iface_path(tmp_path, csrf_header,
                                                           bootstrap_admin):
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app)
        assert c.put(f"/api/v1/network/bridges/{host_id}/pve1/vmbr0",
                     headers=csrf_header(c),
                     json={"config": {"bridge_ports": "enp1s0 enp2s0"}}
                     ).status_code == 200
        assert c.delete(f"/api/v1/network/bridges/{host_id}/pve1/vmbr9",
                        headers=csrf_header(c)).status_code == 200
        assert fake.network_calls == [
            ("update", "pve1", "vmbr0", {"bridge_ports": "enp1s0 enp2s0"}),
            ("delete", "pve1", "vmbr9", {})]


def test_config_keys_are_validated_before_reaching_proxmox(tmp_path, csrf_header,
                                                           bootstrap_admin):
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app)
        r = c.post("/api/v1/network/bridges", headers=csrf_header(c),
                   json={"host_id": host_id, "node": "pve1", "iface": "vmbr9",
                         "config": {"__class__": "boom"}})
        assert r.status_code == 422
        assert fake.network_calls == []


def test_apply_without_confirm_is_409_with_the_node_as_the_phrase(tmp_path, csrf_header,
                                                                  bootstrap_admin):
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app)
        r = c.post(f"/api/v1/network/{host_id}/pve1/apply", headers=csrf_header(c),
                   json={})
        assert r.status_code == 409
        # main.py::problem_handler flattens a dict HTTPException.detail via
        # body.update(exc.detail), so these are top-level keys, not nested
        # under r.json()["detail"]: mirrors selfguard's self_target shape.
        body = r.json()
        assert body["error"] == "confirm_required"
        assert body["confirm_phrase"] == "pve1"
        assert "network" in body["detail"].lower()
        with app.state.sessionmaker() as db:
            assert db.query(Job).count() == 0
            assert (db.query(AuditEvent).filter_by(action="network.apply").one()
                    .result == "denied")
        assert fake.network_calls == []


def test_apply_with_the_wrong_phrase_is_also_409(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app)
        r = c.post(f"/api/v1/network/{host_id}/pve1/apply", headers=csrf_header(c),
                   json={"confirm": "pve2"})
        assert r.status_code == 409
        assert fake.network_calls == []


def test_apply_with_confirm_enqueues_the_job_and_audits_with_job_id(tmp_path, csrf_header,
                                                                    bootstrap_admin):
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app)
        r = c.post(f"/api/v1/network/{host_id}/pve1/apply", headers=csrf_header(c),
                   json={"confirm": "pve1"})
        assert r.status_code == 202, r.text
        job = r.json()["job"]
        assert job["kind"] == "network.apply"
        assert job["target_type"] == "host" and job["target_id"] == host_id
        with app.state.sessionmaker() as db:
            row = (db.query(AuditEvent).filter_by(action="network.apply")
                   .filter(AuditEvent.result == "ok").one())
            assert row.job_id == job["id"]


def test_revert_needs_no_confirm_and_is_not_a_job(tmp_path, csrf_header, bootstrap_admin):
    """Reverting only discards /etc/network/interfaces.new, it cannot strand a node."""
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app)
        r = c.post(f"/api/v1/network/{host_id}/pve1/revert", headers=csrf_header(c))
        assert r.status_code == 200 and r.json()["reverted"] is True
        assert fake.network_calls == [("revert", "pve1", None, {})]
        with app.state.sessionmaker() as db:
            assert db.query(Job).count() == 0
            assert db.query(AuditEvent).filter_by(action="network.revert").one()


def test_operator_role_is_refused_host_config_is_admin(tmp_path, csrf_header,
                                                       bootstrap_admin):
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app)
        c.post("/api/v1/users", json={"email": "viewer@example.com",
                                      "password": "correct-horse-battery",
                                      "display_name": "Viewer"},
               headers=csrf_header(c))
        c.post("/api/v1/auth/login", json={"email": "viewer@example.com",
                                           "password": "correct-horse-battery"},
               headers=csrf_header(c))
        r = c.post(f"/api/v1/network/{host_id}/pve1/apply", headers=csrf_header(c),
                   json={"confirm": "pve1"})
        assert r.status_code == 403 and r.json()["detail"] == "forbidden"


def test_missing_session_is_401_not_403(tmp_path, csrf_header):
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        host_id = _seed(app)
        assert c.post(f"/api/v1/network/{host_id}/pve1/apply", json={"confirm": "pve1"},
                      headers=csrf_header(c)).status_code == 401


def test_network_apply_handler_polls_the_upid_to_completion(tmp_path):
    from proxploy.jobs import JobBackend
    from tests.support import make_job_app

    async def run():
        fake = _fake()
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.guestjobs  # noqa: F401  (registers network.apply)
        backend = JobBackend(app)
        host_id = _seed(app)
        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(db, kind="network.apply", target_type="host",
                                     target_id=host_id,
                                     params={"host_id": host_id, "node": "pve1"}).id
        await backend.wait(job_id, timeout=10)
        with app.state.sessionmaker() as db:
            job = db.get(Job, job_id)
            assert job.status == "succeeded", job.error
            assert job.result["exitstatus"] == "OK" and job.result["node"] == "pve1"
            messages = [e.message for e in db.query(JobEvent)
                        .filter_by(job_id=job_id).order_by(JobEvent.seq)]
            assert any("pve1" in m for m in messages)
        assert [k for k, *_ in fake.network_calls] == ["apply"]

    asyncio.run(run())


def test_network_apply_fails_the_job_when_proxmox_reports_a_bad_exit(tmp_path):
    from proxploy.jobs import JobBackend
    from tests.support import make_job_app

    async def run():
        fake = _fake()
        fake.task_exit = "command 'ifreload -a' failed: exit code 1"
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.guestjobs  # noqa: F401
        backend = JobBackend(app)
        host_id = _seed(app)
        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(db, kind="network.apply", target_type="host",
                                     target_id=host_id,
                                     params={"host_id": host_id, "node": "pve1"}).id
        await backend.wait(job_id, timeout=10)
        with app.state.sessionmaker() as db:
            assert db.get(Job, job_id).status == "failed"

    asyncio.run(run())
