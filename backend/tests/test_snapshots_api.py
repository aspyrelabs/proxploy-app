"""VM snapshots (doc 05 §VMs, doc 01 §4 "with-RAM option surfaced").

Two properties here are load-bearing and each gets its own test:
  1. all four routes sit ABOVE api/vms.py's POST /{vm_id}/{action} wildcard, 
     otherwise POST /vms/3/snapshots is dispatched as the lifecycle action
     "snapshots" and 422s;
  2. PVE's snapshot list carries a synthetic `current` pseudo-snapshot for the
     running state. It is not a real snapshot and rolling back "to current" is
     meaningless, so the GET filters it out.
"""
import asyncio
import json

from fastapi.testclient import TestClient

from proxploy.models import App, AuditEvent, Host, HostCredential, Job, Vm

SNAPS = [
    {"name": "current", "description": "You are here!", "digest": "abc"},
    {"name": "base", "description": "fresh install", "snaptime": 1753840800,
     "vmstate": 0},
    {"name": "pre-update", "description": "before 2.4", "snaptime": 1753844400,
     "vmstate": 1, "parent": "base"},
]


def _fake():
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    fake.snapshots_by_guest = {("qemu", 201): list(SNAPS)}
    return fake


def _seed(app, vm_status="running"):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.7:8006", node_name="pve1",
                    status="connected", pve_version="8.4.1")
        db.add(host)
        db.commit()
        # Listing snapshots is a monitoring read (VM.Audit); create/rollback/
        # delete run as lifecycle jobs (VM.Snapshot*).
        for cap in ("monitoring", "lifecycle"):
            blob, ver = app.state.secretstore.encrypt(json.dumps(
                {"token_id": f"proxploy@pve!snap-{cap}",
                 "token_secret": "s3cret"}).encode())
            db.add(HostCredential(host_id=host.id, kind=f"api_token:{cap}",
                                  encrypted_blob=blob, key_version=ver,
                                  public_meta=f"proxploy@pve!snap-{cap}"))
        db.add(App(host_id=host.id, ctid=150, name="Immich", slug="immich"))
        v = Vm(host_id=host.id, vmid=201, name="win11", status=vm_status)
        db.add(v)
        db.commit()
        return {"host_id": host.id, "vm_id": v.id}


def _authed(tmp_path, bootstrap_admin, vm_status="running"):
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    c = TestClient(app)
    c.__enter__()
    bootstrap_admin(c)
    return app, c, fake, _seed(app, vm_status=vm_status)


# --- ProxmoxClient level ---------------------------------------------------

def test_snapshot_client_calls_hit_the_right_pve_paths(tmp_path):
    from proxploy.services.proxmox import ProxmoxClient
    from tests.fakes.pve import make_fake_factory

    fake = _fake()
    client = ProxmoxClient("https://10.0.0.7:8006", "proxploy@pve!snap", "s3cret",
                           factory=make_fake_factory(fake))
    upid = client.snapshot_create("qemu", "pve1", 201, "pre-update",
                                  description="before 2.4", vmstate=True)
    assert upid.startswith("UPID:")
    kind, node, vmid, kwargs = fake.snapshot_creates[0]
    assert (kind, node, vmid) == ("qemu", "pve1", 201)
    assert kwargs == {"snapname": "pre-update", "description": "before 2.4",
                      "vmstate": 1}
    client.snapshot_rollback("qemu", "pve1", 201, "base")
    assert fake.snapshot_rollbacks == [("qemu", "pve1", 201, "base")]
    client.snapshot_delete("qemu", "pve1", 201, "base")
    assert fake.snapshot_deletes == [("qemu", "pve1", 201, "base")]
    # a snapshot without a description must not send description=None
    client.snapshot_create("qemu", "pve1", 201, "plain")
    assert fake.snapshot_creates[1][3] == {"snapname": "plain"}


def test_with_ram_snapshot_is_refused_for_containers(tmp_path):
    """doc 01 §4's with-RAM option is a qemu feature; PVE's lxc snapshot
    endpoint has no vmstate parameter at all."""
    import pytest

    from proxploy.services.proxmox import ProxmoxClient, ProxmoxError
    from tests.fakes.pve import make_fake_factory

    fake = _fake()
    client = ProxmoxClient("https://10.0.0.7:8006", "proxploy@pve!snap", "s3cret",
                           factory=make_fake_factory(fake))
    with pytest.raises(ProxmoxError, match="vmstate"):
        client.snapshot_create("lxc", "pve1", 150, "nope", vmstate=True)
    assert fake.snapshot_creates == []  # refused before the POST


# --- routes ----------------------------------------------------------------

def test_list_snapshots_drops_the_synthetic_current_entry(tmp_path, bootstrap_admin):
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        rows = c.get(f"/api/v1/vms/{ids['vm_id']}/snapshots").json()
        assert [r["name"] for r in rows] == ["base", "pre-update"]
        assert rows[0]["vmstate"] is False and rows[1]["vmstate"] is True
        assert rows[1]["parent"] == "base" and rows[1]["snaptime"] == 1753844400
        assert rows[0]["description"] == "fresh install"


def _all_paths(app):
    """Flatten app.routes in registration order.

    This FastAPI build (0.140.x) defers `include_router` into a lazy
    `_IncludedRouter` node rather than eagerly copying child routes onto
    `app.routes`, so a plain `[r.path for r in app.routes if hasattr(r, "path")]`
    silently returns only the 4 top-level doc routes and none of api_router's
    children (it would pass vacuously here, `paths.index(...)` would raise
    ValueError on both sides rather than proving ordering). Reusing
    test_network_api.py's `_all_paths` pattern: `_IncludedRouter.
    effective_route_contexts()` is the same recursive walk Starlette's own
    dispatch uses to pick a route at request time, so reading it here reflects
    the real match order.
    """
    paths = []
    for r in app.routes:
        if hasattr(r, "effective_route_contexts"):
            paths.extend(c.path for c in r.effective_route_contexts())
        elif hasattr(r, "path"):
            paths.append(r.path)
    return paths


def test_snapshot_routes_are_registered_above_the_lifecycle_wildcard(tmp_path):
    from tests.support import make_app

    paths = _all_paths(make_app(tmp_path))
    wildcard = paths.index("/api/v1/vms/{vm_id}/{action}")
    for p in ("/api/v1/vms/{vm_id}/snapshots",
              "/api/v1/vms/{vm_id}/snapshots/{name}/rollback",
              "/api/v1/vms/{vm_id}/snapshots/{name}"):
        assert paths.index(p) < wildcard, p


def test_post_snapshots_is_not_swallowed_by_the_lifecycle_wildcard(
        tmp_path, csrf_header, bootstrap_admin):
    """The behavioural half of the ordering guarantee: if the wildcard matched
    first this would 422 with 'action must be one of start, stop, …', and if it
    somehow enqueued it would enqueue the kind `vm.snapshots`."""
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        r = c.post(f"/api/v1/vms/{ids['vm_id']}/snapshots",
                   json={"name": "pre-update"}, headers=csrf_header(c))
        assert r.status_code == 202, r.text
        assert r.json()["job"]["kind"] == "vm.snapshot_create"
        with app.state.sessionmaker() as db:
            kinds = {j.kind for j in db.query(Job).all()}
            assert kinds == {"vm.snapshot_create"}
            assert "vm.snapshots" not in kinds


def test_snapshot_name_is_validated(tmp_path, csrf_header, bootstrap_admin):
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin)
    vid = ids["vm_id"]
    with c:
        for bad in ("current", "1bad", "has space", "semi;colon", "../escape", ""):
            r = c.post(f"/api/v1/vms/{vid}/snapshots", json={"name": bad},
                       headers=csrf_header(c))
            assert r.status_code == 422, bad
        # the same rule guards the path parameter on rollback/delete. Starlette
        # keeps the literal ".." segment (it does not dot-normalize the path
        # before matching), so no api/v1 route matches at all and the request
        # falls through to main.py's SPA static mount at "/": which only
        # allows GET/HEAD, hence 405. Whichever of the three, the traversal
        # payload never reaches rollback_vm_snapshot.
        assert c.post(f"/api/v1/vms/{vid}/snapshots/..%2Fescape/rollback",
                      json={"confirm": "win11"},
                      headers=csrf_header(c)).status_code in (404, 422, 405)
        with app.state.sessionmaker() as db:
            assert db.query(Job).count() == 0


def test_rollback_requires_the_typed_vm_name(tmp_path, csrf_header, bootstrap_admin):
    """Rollback discards everything written since the snapshot. It reuses the
    same 409 vocabulary as the self-target stop guard so the frontend's
    existing ConfirmSelfDialog renders it unchanged."""
    app, c, fake, ids = _authed(tmp_path, bootstrap_admin)
    vid = ids["vm_id"]
    with c:
        r = c.post(f"/api/v1/vms/{vid}/snapshots/base/rollback", json={},
                   headers=csrf_header(c))
        assert r.status_code == 409
        assert r.json()["error"] == "confirm_required"
        assert r.json()["confirm_phrase"] == "win11"
        with app.state.sessionmaker() as db:
            assert db.query(AuditEvent).filter_by(
                action="vm.snapshot_rollback", result="denied").count() == 1
            assert db.query(Job).count() == 0
        assert c.post(f"/api/v1/vms/{vid}/snapshots/base/rollback",
                      json={"confirm": "nope"},
                      headers=csrf_header(c)).status_code == 409
        ok = c.post(f"/api/v1/vms/{vid}/snapshots/base/rollback",
                    json={"confirm": "win11"}, headers=csrf_header(c))
        assert ok.status_code == 202, ok.text
        assert ok.json()["job"]["kind"] == "vm.snapshot_rollback"


def test_rollback_requires_admin(tmp_path, csrf_header, bootstrap_admin):
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin)
    vid = ids["vm_id"]
    with c:
        c.post("/api/v1/users", json={"email": "op@example.com",
                                      "password": "Correct-Horse-Battery-9",
                                      "display_name": "Op", "role": "operator"},
               headers=csrf_header(c))
        c.post("/api/v1/auth/login", json={"email": "op@example.com",
                                           "password": "Correct-Horse-Battery-9"},
               headers=csrf_header(c))
        # an operator may take and delete snapshots …
        assert c.post(f"/api/v1/vms/{vid}/snapshots", json={"name": "opsnap"},
                      headers=csrf_header(c)).status_code == 202
        assert c.request("DELETE", f"/api/v1/vms/{vid}/snapshots/base",
                         headers=csrf_header(c)).status_code == 202
        # … but not roll one back
        r = c.post(f"/api/v1/vms/{vid}/snapshots/base/rollback",
                   json={"confirm": "win11"}, headers=csrf_header(c))
        assert r.status_code == 403 and r.json()["detail"] == "Your role does not allow this."


def test_delete_snapshot_enqueues_and_audits(tmp_path, csrf_header, bootstrap_admin):
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        r = c.request("DELETE", f"/api/v1/vms/{ids['vm_id']}/snapshots/base",
                      headers=csrf_header(c))
        assert r.status_code == 202, r.text
        assert r.json()["job"]["kind"] == "vm.snapshot_delete"
        assert r.json()["job"]["params"]["name"] == "base"
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="vm.snapshot_delete").one()
            assert row.target_type == "vm" and row.target_id == ids["vm_id"]
            assert row.job_id is not None


def test_snapshot_routes_require_auth(tmp_path, csrf_header):
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        ids = _seed(app)
        vid = ids["vm_id"]
        h = csrf_header(c)
        assert c.get(f"/api/v1/vms/{vid}/snapshots").status_code == 401
        assert c.post(f"/api/v1/vms/{vid}/snapshots", json={"name": "x1"},
                      headers=h).status_code == 401
        assert c.post(f"/api/v1/vms/{vid}/snapshots/base/rollback", json={},
                      headers=h).status_code == 401
        assert c.request("DELETE", f"/api/v1/vms/{vid}/snapshots/base",
                         headers=h).status_code == 401


# --- job handlers ----------------------------------------------------------

def _run_job(tmp_path, kind, params_from_ids):
    from proxploy.jobs import JobBackend
    from tests.support import make_job_app

    async def go():
        fake = _fake()
        # test_snapshot_jobs_run_end_to_end calls this three times (one per
        # kind) against the same tmp_path fixture; each call re-seeds a host
        # named "host-01", so sharing one sqlite file across calls trips the
        # hosts.name UNIQUE constraint on the 2nd and 3rd. Give each kind its
        # own subdirectory so the three job runs get independent databases.
        db_dir = tmp_path / kind
        db_dir.mkdir(parents=True, exist_ok=True)
        app = make_job_app(db_dir, fake=fake)
        import proxploy.services.guestjobs  # noqa: F401  (registers vm.snapshot_*)

        backend = JobBackend(app)
        ids = _seed(app)
        with app.state.sessionmaker() as db:
            jid = backend.enqueue(db, kind=kind, target_type="vm",
                                  target_id=ids["vm_id"],
                                  params=params_from_ids(ids)).id
        await backend.wait(jid, timeout=10)
        with app.state.sessionmaker() as db:
            job = db.get(Job, jid)
            return fake, job.status, job.result, job.error

    return asyncio.run(go())


def test_a_vm_on_another_cluster_node_runs_on_ITS_node(tmp_path):
    """The guest's node decides where the call goes, not its host's node.

    `/cluster/resources` answers for the whole cluster from any member, so on a
    cluster every polled host mirrors every VM, and the row under the host that
    does NOT own the guest used to send its snapshot to the wrong node. PVE
    answered `500 Configuration file 'nodes/node1/qemu-server/100.conf' does not
    exist`, observed on PVE 9.2.10 (doc 12 check 18). A cluster-wide token can
    act on another node's guest through any member, which is why the fix routes
    to the right node rather than hiding the guest.
    """
    from proxploy.jobs import JobBackend
    from tests.support import make_job_app

    async def go():
        fake = _fake()
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.guestjobs  # noqa: F401

        backend = JobBackend(app)
        ids = _seed(app)
        with app.state.sessionmaker() as db:
            # host-01 is pve1; this guest lives on pve2, the other member
            db.get(Vm, ids["vm_id"]).node_name = "pve2"
            db.commit()
            jid = backend.enqueue(db, kind="vm.snapshot_create", target_type="vm",
                                  target_id=ids["vm_id"],
                                  params={"vm_id": ids["vm_id"], "name": "x"}).id
        await backend.wait(jid, timeout=10)
        with app.state.sessionmaker() as db:
            job = db.get(Job, jid)
            assert job.status == "succeeded", job.error
        kind, node, vmid, _kwargs = fake.snapshot_creates[0]
        assert (kind, node, vmid) == ("qemu", "pve2", 201), (
            f"snapshot went to {node!r}, not the node the guest runs on")

    asyncio.run(go())


def test_a_vm_never_polled_since_node_name_existed_uses_its_host_node(tmp_path):
    """NULL node_name means "not polled yet", not "standalone".

    The fallback is the behaviour that predates the column, so an upgraded
    install is never worse off between the migration and the next poll cycle.
    """
    from proxploy.jobs import JobBackend
    from tests.support import make_job_app

    async def go():
        fake = _fake()
        db_dir = tmp_path / "fallback"
        db_dir.mkdir(parents=True, exist_ok=True)
        app = make_job_app(db_dir, fake=fake)
        import proxploy.services.guestjobs  # noqa: F401

        backend = JobBackend(app)
        ids = _seed(app)
        with app.state.sessionmaker() as db:
            assert db.get(Vm, ids["vm_id"]).node_name is None
            jid = backend.enqueue(db, kind="vm.snapshot_create", target_type="vm",
                                  target_id=ids["vm_id"],
                                  params={"vm_id": ids["vm_id"], "name": "x"}).id
        await backend.wait(jid, timeout=10)
        assert fake.snapshot_creates[0][1] == "pve1"

    asyncio.run(go())


def test_snapshot_jobs_run_end_to_end(tmp_path):
    from proxploy.jobs import HANDLERS

    import proxploy.services.guestjobs  # noqa: F401

    for k in ("vm.snapshot_create", "vm.snapshot_rollback", "vm.snapshot_delete"):
        assert k in HANDLERS

    fake, status, result, error = _run_job(
        tmp_path, "vm.snapshot_create",
        lambda ids: {"vm_id": ids["vm_id"], "name": "pre-update",
                     "description": "before 2.4", "vmstate": True})
    assert status == "succeeded", error
    assert fake.snapshot_creates[0][3] == {"snapname": "pre-update",
                                           "description": "before 2.4", "vmstate": 1}
    assert result["exitstatus"] == "OK" and result["name"] == "pre-update"

    fake, status, result, error = _run_job(
        tmp_path, "vm.snapshot_rollback",
        lambda ids: {"vm_id": ids["vm_id"], "name": "base"})
    assert status == "succeeded", error
    assert fake.snapshot_rollbacks == [("qemu", "pve1", 201, "base")]

    fake, status, result, error = _run_job(
        tmp_path, "vm.snapshot_delete",
        lambda ids: {"vm_id": ids["vm_id"], "name": "base"})
    assert status == "succeeded", error
    assert fake.snapshot_deletes == [("qemu", "pve1", 201, "base")]


def test_a_failing_pve_task_fails_the_snapshot_job(tmp_path):
    from proxploy.jobs import JobBackend
    from tests.support import make_job_app

    async def go():
        fake = _fake()
        fake.task_exit = "snapshot feature is not available"
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.guestjobs  # noqa: F401

        backend = JobBackend(app)
        ids = _seed(app)
        with app.state.sessionmaker() as db:
            jid = backend.enqueue(db, kind="vm.snapshot_create", target_type="vm",
                                  target_id=ids["vm_id"],
                                  params={"vm_id": ids["vm_id"], "name": "x1"}).id
        await backend.wait(jid, timeout=10)
        with app.state.sessionmaker() as db:
            job = db.get(Job, jid)
            assert job.status == "failed"
            assert "snapshot feature is not available" in (job.error or "")

    asyncio.run(go())
