"""Host removal, credential rotation, forced sync, task passthrough (PXP-17).

doc 05 listed all of these and the authz matrix has carried
("host","sync"/"credentials"/"remove") since Phase 1. No phase ever added the
routes; api/hosts.py's own header comment admitted it.
"""
import json

from proxploy.models import App, Host, HostCredential, Vm


def _seeded(tmp_path, fake=None, with_app=False):
    from fastapi.testclient import TestClient
    from tests.support import make_app, seed_host_row

    app = make_app(tmp_path, fake=fake)
    c = TestClient(app)

    def seed():
        with app.state.sessionmaker() as db:
            h = seed_host_row(db)
            blob, ver = app.state.secretstore.encrypt(json.dumps(
                {"token_id": "proxploy@pve!old", "token_secret": "old"}).encode())
            db.add(HostCredential(host_id=h.id, kind="api_token:monitoring",
                                  encrypted_blob=blob, key_version=ver,
                                  public_meta="proxploy@pve!old"))
            db.add(Vm(host_id=h.id, vmid=100, name="win11", status="running"))
            if with_app:
                db.add(App(host_id=h.id, ctid=150, name="Immich", slug="immich"))
            db.commit()
            return h.id
    return app, c, seed


# --- removal --------------------------------------------------------------

def test_removal_refuses_while_apps_reference_the_host_and_names_them(
        tmp_path, csrf_header, bootstrap_admin):
    """apps.host_id is ON DELETE RESTRICT. The operator needs to know WHICH
    apps stand in the way, not a bare constraint error."""
    app, c, seed = _seeded(tmp_path, with_app=True)
    with c:
        bootstrap_admin(c)
        host_id = seed()
        r = c.request("DELETE", f"/api/v1/hosts/{host_id}",
                      json={"confirm": "host-01"}, headers=csrf_header(c))
        assert r.status_code == 409
        assert r.json()["error"] == "host_has_apps"
        assert r.json()["apps"][0]["name"] == "Immich"
        with app.state.sessionmaker() as db:
            assert db.get(Host, host_id) is not None


def test_removal_needs_the_typed_name(tmp_path, csrf_header, bootstrap_admin):
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        host_id = seed()
        r = c.request("DELETE", f"/api/v1/hosts/{host_id}", json={},
                      headers=csrf_header(c))
        assert r.status_code == 409
        assert r.json()["error"] == "confirm_required"
        with app.state.sessionmaker() as db:
            assert db.get(Host, host_id) is not None


def test_removal_drops_the_host_its_cache_and_its_credentials(
        tmp_path, csrf_header, bootstrap_admin):
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        host_id = seed()
        r = c.request("DELETE", f"/api/v1/hosts/{host_id}",
                      json={"confirm": "host-01"}, headers=csrf_header(c))
        assert r.status_code == 200 and r.json()["removed"] is True
        with app.state.sessionmaker() as db:
            assert db.get(Host, host_id) is None
            assert db.query(Vm).filter_by(host_id=host_id).count() == 0
            assert db.query(HostCredential).filter_by(host_id=host_id).count() == 0
        audit = c.get("/api/v1/audit", params={"action": "host.remove"}).json()
        assert audit and audit[0]["params"]["name"] == "host-01"


def test_forget_apps_removes_the_records_and_leaves_the_containers(
        tmp_path, csrf_header, bootstrap_admin):
    """Destroying a container is app uninstall's job, never a side effect of
    removing a host."""
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    app, c, seed = _seeded(tmp_path, fake=fake, with_app=True)
    with c:
        bootstrap_admin(c)
        host_id = seed()
        r = c.request("DELETE", f"/api/v1/hosts/{host_id}",
                      json={"confirm": "host-01", "forget_apps": True},
                      headers=csrf_header(c))
        assert r.status_code == 200 and r.json()["forgot_apps"] == 1
        with app.state.sessionmaker() as db:
            assert db.query(App).count() == 0
        assert fake.guest_deletes == [], "no container may be destroyed here"


# --- credential rotation --------------------------------------------------

def test_a_rejected_new_token_leaves_the_old_one_in_place(
        tmp_path, csrf_header, bootstrap_admin):
    """A rotation that stores an unusable credential would take the host
    offline with no way back except editing the database."""
    from tests.fakes.pve import FakePVE

    fake = FakePVE(fail=True)
    app, c, seed = _seeded(tmp_path, fake=fake)
    with c:
        bootstrap_admin(c)
        host_id = seed()
        r = c.post(f"/api/v1/hosts/{host_id}/credentials",
                   json={"token_id": "proxploy@pve!new", "token_secret": "new"},
                   headers=csrf_header(c))
        assert r.status_code == 502 and r.json()["error"] == "token_rejected"
        with app.state.sessionmaker() as db:
            cred = db.query(HostCredential).filter_by(
                host_id=host_id, kind="api_token:monitoring").one()
            assert cred.public_meta == "proxploy@pve!old"


def test_rotating_the_api_token_replaces_it_after_verifying(
        tmp_path, csrf_header, bootstrap_admin):
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    app, c, seed = _seeded(tmp_path, fake=fake)
    with c:
        bootstrap_admin(c)
        host_id = seed()
        r = c.post(f"/api/v1/hosts/{host_id}/credentials",
                   json={"token_id": "proxploy@pve!new", "token_secret": "new"},
                   headers=csrf_header(c))
        assert r.status_code == 200
        # No `capability` in the request body: default "monitoring" preserves
        # every caller written before per-capability tokens existed.
        assert r.json()["rotated"] == ["api_token:monitoring"]
        with app.state.sessionmaker() as db:
            cred = db.query(HostCredential).filter_by(
                host_id=host_id, kind="api_token:monitoring").one()
            assert "new" in cred.public_meta
            tok = json.loads(app.state.secretstore.decrypt(cred.encrypted_blob))
            assert tok["token_secret"] == "new"


def test_rotating_a_named_capability_touches_only_that_kind_row(
        tmp_path, csrf_header, bootstrap_admin):
    """CredentialRotateIn.capability lets a caller add/replace a specific
    capability's token (lifecycle/console/backup) without disturbing the
    others -- the mechanism a later UI step needs to let an operator add
    lifecycle after enrolling monitoring-only, and proof the rotate route
    isn't hardwired to the single-token model."""
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    app, c, seed = _seeded(tmp_path, fake=fake)
    with c:
        bootstrap_admin(c)
        host_id = seed()
        r = c.post(f"/api/v1/hosts/{host_id}/credentials",
                   json={"token_id": "proxploy@pve!lifecycle",
                        "token_secret": "new-lc", "capability": "lifecycle"},
                   headers=csrf_header(c))
        assert r.status_code == 200
        assert r.json()["rotated"] == ["api_token:lifecycle"]
        with app.state.sessionmaker() as db:
            # The pre-existing monitoring row is untouched.
            mon = db.query(HostCredential).filter_by(
                host_id=host_id, kind="api_token:monitoring").one()
            assert mon.public_meta == "proxploy@pve!old"
            lc = db.query(HostCredential).filter_by(
                host_id=host_id, kind="api_token:lifecycle").one()
            assert lc.public_meta == "proxploy@pve!lifecycle"


def test_rotating_an_unknown_capability_is_422(tmp_path, csrf_header, bootstrap_admin):
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        host_id = seed()
        r = c.post(f"/api/v1/hosts/{host_id}/credentials",
                   json={"token_id": "proxploy@pve!x", "token_secret": "x",
                        "capability": "teleportation"},
                   headers=csrf_header(c))
        assert r.status_code == 422


def test_rotating_ssh_clears_verification_and_returns_the_new_public_key(
        tmp_path, csrf_header, bootstrap_admin):
    """The new key is not authorized on the node yet. Keeping the old
    ssh_verified_at would claim a root shell Proxploy no longer has."""
    from proxploy.models import utcnow
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        host_id = seed()
        with app.state.sessionmaker() as db:
            blob, ver = app.state.secretstore.encrypt(b"old-key")
            db.add(HostCredential(host_id=host_id, kind="ssh_key",
                                  encrypted_blob=blob, key_version=ver,
                                  public_meta="ssh-ed25519 OLD",
                                  ssh_verified_at=utcnow()))
            db.commit()
        r = c.post(f"/api/v1/hosts/{host_id}/credentials",
                   json={"rotate_ssh": True}, headers=csrf_header(c))
        assert r.status_code == 200
        assert r.json()["public_key"].startswith("ssh-ed25519 ")
        assert r.json()["consent_note"]
        with app.state.sessionmaker() as db:
            cred = db.query(HostCredential).filter_by(host_id=host_id,
                                                      kind="ssh_key").one()
            assert cred.ssh_verified_at is None
            assert cred.public_meta != "ssh-ed25519 OLD"


def test_half_a_token_pair_is_422(tmp_path, csrf_header, bootstrap_admin):
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        host_id = seed()
        r = c.post(f"/api/v1/hosts/{host_id}/credentials",
                   json={"token_id": "proxploy@pve!new"}, headers=csrf_header(c))
        assert r.status_code == 422
        r = c.post(f"/api/v1/hosts/{host_id}/credentials", json={},
                   headers=csrf_header(c))
        assert r.status_code == 422


# --- forced sync ----------------------------------------------------------

def test_forced_sync_runs_the_pollers_own_cycle(tmp_path, csrf_header,
                                                bootstrap_admin):
    """Not a parallel implementation: a forced sync and a scheduled one must
    not be able to disagree about what they ingest."""
    from tests.fakes.pve import FakePVE

    fake = FakePVE(resources=[{"type": "node", "node": "pve1", "status": "online",
                               "maxcpu": 4, "maxmem": 8589934592}])
    app, c, seed = _seeded(tmp_path, fake=fake)
    with c:
        bootstrap_admin(c)
        host_id = seed()
        calls = []
        original = app.state.poller._poll_once
        app.state.poller._poll_once = lambda hid: calls.append(hid) or original(hid)
        r = c.post(f"/api/v1/hosts/{host_id}/sync", headers=csrf_header(c))
        assert r.status_code == 200, r.text
        assert calls == [host_id]
        assert r.json()["id"] == host_id
        audit = c.get("/api/v1/audit", params={"action": "host.sync"}).json()
        assert audit


def test_forced_sync_of_a_missing_host_is_404(tmp_path, csrf_header,
                                              bootstrap_admin):
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()
        assert c.post("/api/v1/hosts/9999/sync",
                      headers=csrf_header(c)).status_code == 404


# --- task passthrough -----------------------------------------------------

def test_task_list_passes_the_limit_through_and_projects_the_rows(
        tmp_path, csrf_header, bootstrap_admin):
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    fake.node_task_rows = [
        {"upid": "UPID:pve1:AAA::vzdump:", "type": "vzdump", "id": "150",
         "node": "pve1", "user": "root@pam", "status": "OK",
         "exitstatus": "OK", "starttime": 1, "endtime": 2, "extra": "dropped"},
    ]
    app, c, seed = _seeded(tmp_path, fake=fake)
    with c:
        bootstrap_admin(c)
        host_id = seed()
        r = c.get(f"/api/v1/hosts/{host_id}/tasks", params={"limit": 10})
        assert r.status_code == 200, r.text
        row = r.json()[0]
        assert row["type"] == "vzdump" and row["user"] == "root@pam"
        assert "extra" not in row, "only the projected fields are returned"
        assert fake.task_list_calls == [{"limit": 10}]


def test_task_list_rejects_an_absurd_limit(tmp_path, csrf_header, bootstrap_admin):
    from tests.fakes.pve import FakePVE
    app, c, seed = _seeded(tmp_path, fake=FakePVE())
    with c:
        bootstrap_admin(c)
        host_id = seed()
        assert c.get(f"/api/v1/hosts/{host_id}/tasks",
                     params={"limit": 100000}).status_code == 422
        assert c.get(f"/api/v1/hosts/{host_id}/tasks",
                     params={"limit": 0}).status_code == 422


def test_task_log_returns_the_lines_for_a_task_proxploy_did_not_start(
        tmp_path, csrf_header, bootstrap_admin):
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    upid = "UPID:pve1:AAA::vzdump:"
    fake.task_lines[upid] = ["starting backup", "finished"]
    app, c, seed = _seeded(tmp_path, fake=fake)
    with c:
        bootstrap_admin(c)
        host_id = seed()
        r = c.get(f"/api/v1/hosts/{host_id}/tasks/{upid}/log")
        assert r.status_code == 200, r.text
        assert r.json()["lines"] == ["starting backup", "finished"]


def test_enrolment_records_the_node_name_immediately(tmp_path, csrf_header,
                                                     bootstrap_admin):
    """`node_name` used to stay NULL until the poller's first cycle, and every
    job handler reads `host.node_name or ""`, so anything started in that
    window sent an EMPTY node name to PVE. Enrol-then-install is the obvious
    first thing an operator does, not an exotic sequence.

    Confirmed against real hardware on 2026-08-10: POST /hosts returned
    `node_name: null` while the node was plainly `pve-lab-host-02`.
    """
    from fastapi.testclient import TestClient
    from tests.fakes.pve import FakePVE
    from tests.support import make_app

    fake = FakePVE()
    fake.cluster_status_rows = [{"type": "node", "name": "pve1", "local": 1,
                                 "online": 1}]
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as client:
        bootstrap_admin(client)
        r = client.post("/api/v1/hosts", json={
            "name": "host-01", "address": "https://10.0.0.9:8006",
            "token_id": "proxploy@pve!ops", "token_secret": "s3cret",
            "verify_tls": False}, headers=csrf_header(client))
        assert r.status_code == 201, r.text
        assert r.json()["node_name"] == "pve1"


def test_enrolment_picks_the_local_node_out_of_a_cluster(tmp_path, csrf_header,
                                                         bootstrap_admin):
    """On a cluster, `/nodes` cannot say which node this address IS. Only
    `local: 1` in /cluster/status can."""
    from fastapi.testclient import TestClient
    from tests.fakes.pve import FakePVE
    from tests.support import make_app

    fake = FakePVE()
    fake.cluster_status_rows = [
        {"type": "cluster", "name": "prod"},
        {"type": "node", "name": "pve1", "local": 0, "online": 1},
        {"type": "node", "name": "pve2", "local": 1, "online": 1},
        {"type": "node", "name": "pve3", "local": 0, "online": 1},
    ]
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as client:
        bootstrap_admin(client)
        r = client.post("/api/v1/hosts", json={
            "name": "host-02", "address": "https://10.0.0.10:8006",
            "token_id": "proxploy@pve!ops", "token_secret": "s3cret",
            "verify_tls": False}, headers=csrf_header(client))
        assert r.status_code == 201, r.text
        assert r.json()["node_name"] == "pve2"


def test_enrolment_survives_a_cluster_status_failure(tmp_path, csrf_header,
                                                     bootstrap_admin):
    """A surprising cluster shape must never block enrolment: leave it NULL and
    let the poller fill it in, exactly as before."""
    from fastapi.testclient import TestClient
    from tests.fakes.pve import FakePVE
    from tests.support import make_app

    class _Boom(FakePVE):
        @property
        def cluster_status_rows(self):
            raise ConnectionError("no /cluster/status here")

        @cluster_status_rows.setter
        def cluster_status_rows(self, v):
            pass

    app = make_app(tmp_path, fake=_Boom())
    with TestClient(app) as client:
        bootstrap_admin(client)
        r = client.post("/api/v1/hosts", json={
            "name": "host-03", "address": "https://10.0.0.11:8006",
            "token_id": "proxploy@pve!ops", "token_secret": "s3cret",
            "verify_tls": False}, headers=csrf_header(client))
        assert r.status_code == 201, r.text
        assert r.json()["node_name"] is None


def test_enrolment_records_the_cluster_name(tmp_path, csrf_header,
                                            bootstrap_admin):
    """`hosts.cluster_name` was written by nothing but migration preflight, so
    every node card said "standalone" no matter how big the cluster was.

    /cluster/status is already called at enrolment for the node name, and it
    carries the cluster name in its `{"type": "cluster"}` row, so this costs
    no extra round trip.
    """
    from fastapi.testclient import TestClient
    from proxploy.models import Host
    from tests.fakes.pve import FakePVE
    from tests.support import make_app

    fake = FakePVE()
    fake.cluster_status_rows = [
        {"type": "cluster", "name": "prod", "nodes": 3},
        {"type": "node", "name": "pve1", "local": 0, "online": 1},
        {"type": "node", "name": "pve2", "local": 1, "online": 1},
        {"type": "node", "name": "pve3", "local": 0, "online": 1},
    ]
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as client:
        bootstrap_admin(client)
        r = client.post("/api/v1/hosts", json={
            "name": "host-01", "address": "https://10.0.0.9:8006",
            "token_id": "proxploy@pve!ops", "token_secret": "s3cret",
            "verify_tls": False}, headers=csrf_header(client))
        assert r.status_code == 201, r.text
        with app.state.sessionmaker() as db:
            host = db.get(Host, r.json()["id"])
            assert host.cluster_name == "prod"
            assert host.node_name == "pve2"


def test_a_standalone_node_records_no_cluster_name(tmp_path, csrf_header,
                                                   bootstrap_admin):
    """No `{"type": "cluster"}` row means no cluster. NULL is the honest
    answer, and it is what makes the node card say "standalone"."""
    from fastapi.testclient import TestClient
    from proxploy.models import Host
    from tests.fakes.pve import FakePVE
    from tests.support import make_app

    fake = FakePVE()
    fake.cluster_status_rows = [{"type": "node", "name": "pve1", "local": 1,
                                 "online": 1}]
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as client:
        bootstrap_admin(client)
        r = client.post("/api/v1/hosts", json={
            "name": "host-01", "address": "https://10.0.0.9:8006",
            "token_id": "proxploy@pve!ops", "token_secret": "s3cret",
            "verify_tls": False}, headers=csrf_header(client))
        assert r.status_code == 201, r.text
        with app.state.sessionmaker() as db:
            assert db.get(Host, r.json()["id"]).cluster_name is None
