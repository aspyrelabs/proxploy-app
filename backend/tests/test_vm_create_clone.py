"""VM create / clone / delete (doc 05 §VMs, doc 01 §4).

Same registration-order hazard as Task 10: POST /vms/{id}/clone and
DELETE /vms/{id} live above api/vms.py's POST /{vm_id}/{action} wildcard, and
both an ordering assertion and a behavioural one lock that in.

DELETE is the most destructive route in this phase, it removes a guest and its
disks, so it carries three separate gates: owner role, the selfguard, and a
typed confirmation, plus a refusal to touch a running guest.
"""
import asyncio
import json

from fastapi.testclient import TestClient

from proxploy.models import AuditEvent, Host, HostCredential, Job, Vm


def _fake():
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    fake.nextid = 999
    return fake


def _seed(app, vm_status="stopped"):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.7:8006", node_name="pve1",
                    status="connected", pve_version="8.4.1")
        db.add(host)
        db.commit()
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!vm", "token_secret": "s3cret"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token", encrypted_blob=blob,
                              key_version=ver, public_meta="proxploy@pve!vm"))
        v = Vm(host_id=host.id, vmid=201, name="win11", status=vm_status)
        db.add(v)
        db.commit()
        return {"host_id": host.id, "vm_id": v.id}


def _authed(tmp_path, bootstrap_admin, vm_status="stopped"):
    from tests.support import make_app, seed_snapshot

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    c = TestClient(app)
    c.__enter__()
    bootstrap_admin(c)
    ids = _seed(app, vm_status=vm_status)
    seed_snapshot(app, ids["host_id"], nodes=[{"node": "pve1"}, {"node": "pve2"}])
    return app, c, fake, ids


def _spec(ids, **over):
    body = {"host_id": ids["host_id"], "name": "web-01", "node": "pve1",
            "cores": 2, "memory_mb": 2048, "disk_gb": 32, "storage": "local-lvm"}
    body.update(over)
    return body


# --- ProxmoxClient level ---------------------------------------------------

def test_create_clone_and_delete_client_calls(tmp_path):
    from proxploy.services.proxmox import ProxmoxClient
    from tests.fakes.pve import make_fake_factory

    fake = _fake()
    client = ProxmoxClient("https://10.0.0.7:8006", "proxploy@pve!vm", "s3cret",
                           factory=make_fake_factory(fake))
    upid = client.vm_create("pve1", {"vmid": 999, "name": "web-01", "cores": 2})
    assert upid.startswith("UPID:")
    # the guest-create leaf Task 9 added for restores: reused, not duplicated
    assert fake.creates == [("qemu", "pve1", {"vmid": 999, "name": "web-01",
                                              "cores": 2})]
    client.vm_clone("pve1", 201, {"newid": 999, "name": "web-02", "full": 1})
    assert fake.clones == [("pve1", 201, {"newid": 999, "name": "web-02",
                                          "full": 1})]
    client.guest_delete("qemu", "pve1", 201)
    assert fake.guest_deletes == [("qemu", "pve1", 201)]


def test_create_error_is_wrapped_and_scrubbed(tmp_path):
    import pytest

    from proxploy.services.proxmox import ProxmoxClient, ProxmoxError
    from tests.fakes.pve import make_fake_factory

    fake = _fake()
    fake.create_error = "500 VM 100 already exists (secret s3cret leaked)"
    client = ProxmoxClient("https://10.0.0.7:8006", "proxploy@pve!vm", "s3cret",
                           factory=make_fake_factory(fake))
    with pytest.raises(ProxmoxError) as exc:
        client.vm_create("pve1", {"vmid": 100})
    assert "already exists" in str(exc.value)
    assert "s3cret" not in str(exc.value)  # _wrap is the one scrubbing point


# --- route ordering --------------------------------------------------------

def _all_paths(app):
    """Flatten app.routes in registration order.

    This FastAPI build (0.140.x) defers `include_router` into a lazy
    `_IncludedRouter` node rather than eagerly copying child routes onto
    `app.routes`, so a plain `[r.path for r in app.routes if hasattr(r, "path")]`
    silently returns only the 4 top-level doc routes and none of api_router's
    children; it would pass vacuously here. Reusing test_network_api.py's /
    test_snapshots_api.py's `_all_paths` pattern: `_IncludedRouter.
    effective_route_contexts()` is the same recursive walk Starlette's own
    dispatch uses to pick a route at request time.
    """
    paths = []
    for r in app.routes:
        if hasattr(r, "effective_route_contexts"):
            paths.extend(c.path for c in r.effective_route_contexts())
        elif hasattr(r, "path"):
            paths.append(r.path)
    return paths


def test_create_routes_are_registered_above_the_lifecycle_wildcard(tmp_path):
    from tests.support import make_app

    paths = _all_paths(make_app(tmp_path))
    wildcard = paths.index("/api/v1/vms/{vm_id}/{action}")
    assert paths.index("/api/v1/vms/{vm_id}/clone") < wildcard
    assert "/api/v1/vms" in paths


def test_post_clone_is_not_swallowed_by_the_lifecycle_wildcard(
        tmp_path, csrf_header, bootstrap_admin):
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        r = c.post(f"/api/v1/vms/{ids['vm_id']}/clone", json={"name": "web-02"},
                   headers=csrf_header(c))
        assert r.status_code == 202, r.text
        assert r.json()["job"]["kind"] == "vm.clone"
        with app.state.sessionmaker() as db:
            assert {j.kind for j in db.query(Job).all()} == {"vm.clone"}


# --- create route ----------------------------------------------------------

def test_create_validates_the_spec(tmp_path, csrf_header, bootstrap_admin):
    app, c, fake, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        h = csrf_header(c)
        for over in ({"cores": 0}, {"memory_mb": 0}, {"disk_gb": 0},
                     {"cores": -4}, {"name": "bad name"}, {"node": "pve9"}):
            r = c.post("/api/v1/vms", json=_spec(ids, **over), headers=h)
            assert r.status_code == 422, over
        r = c.post("/api/v1/vms", json=_spec(ids, host_id=9999), headers=h)
        assert r.status_code == 404
        with app.state.sessionmaker() as db:
            assert db.query(Job).count() == 0


def test_create_mints_a_vmid_from_cluster_nextid(tmp_path, csrf_header,
                                                 bootstrap_admin):
    app, c, fake, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        r = c.post("/api/v1/vms", json=_spec(ids), headers=csrf_header(c))
        assert r.status_code == 202, r.text
        assert r.json()["vmid"] == 999
        job = r.json()["job"]
        assert job["kind"] == "vm.create" and job["params"]["vmid"] == 999
        assert job["target_type"] == "host" and job["target_id"] == ids["host_id"]
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="vm.create").one()
            assert row.job_id is not None
            # no Vm row is written by Proxploy: the poller discovers it
            assert db.query(Vm).count() == 1


def test_create_accepts_an_explicit_vmid(tmp_path, csrf_header, bootstrap_admin):
    app, c, fake, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        r = c.post("/api/v1/vms", json=_spec(ids, vmid=310),
                   headers=csrf_header(c))
        assert r.status_code == 202, r.text
        assert r.json()["vmid"] == 310
        assert fake.nextid_calls == 0  # never asked PVE for one


def test_create_requires_admin(tmp_path, csrf_header, bootstrap_admin):
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        c.post("/api/v1/users", json={"email": "op@example.com",
                                      "password": "correct-horse-battery",
                                      "display_name": "Op", "role": "operator"},
               headers=csrf_header(c))
        c.post("/api/v1/auth/login", json={"email": "op@example.com",
                                           "password": "correct-horse-battery"},
               headers=csrf_header(c))
        r = c.post("/api/v1/vms", json=_spec(ids), headers=csrf_header(c))
        assert r.status_code == 403 and r.json()["detail"] == "forbidden"


# --- job handlers ----------------------------------------------------------

def _run_job(tmp_path, kind, params_from_ids, tweak=None):
    from proxploy.jobs import JobBackend
    from tests.support import make_job_app

    async def go():
        fake = _fake()
        if tweak:
            tweak(fake)
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.guestjobs  # noqa: F401  (registers vm.create etc.)

        backend = JobBackend(app)
        ids = _seed(app)
        q = app.state.bus.subscribe()
        with app.state.sessionmaker() as db:
            jid = backend.enqueue(db, kind=kind, params=params_from_ids(ids)).id
        await backend.wait(jid, timeout=10)
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        with app.state.sessionmaker() as db:
            job = db.get(Job, jid)
            return fake, job.status, job.result, job.error, events

    return asyncio.run(go())


def test_create_job_builds_the_qemu_params_and_publishes(tmp_path):
    fake, status, result, error, events = _run_job(
        tmp_path, "vm.create",
        lambda ids: {"host_id": ids["host_id"], "node": "pve1", "vmid": 999,
                     "name": "web-01", "cores": 2, "memory_mb": 2048,
                     "disk_gb": 32, "storage": "local-lvm",
                     "iso": "local:iso/debian-12.iso", "bridge": "vmbr0",
                     "ostype": "l26", "start": True})
    assert status == "succeeded", error
    kind, node, kwargs = fake.creates[0]
    assert (kind, node) == ("qemu", "pve1")
    assert kwargs["vmid"] == 999 and kwargs["name"] == "web-01"
    assert kwargs["cores"] == 2 and kwargs["memory"] == 2048
    assert kwargs["scsi0"] == "local-lvm:32"
    assert kwargs["ide2"] == "local:iso/debian-12.iso,media=cdrom"
    assert kwargs["net0"] == "virtio,bridge=vmbr0"
    assert kwargs["boot"] == "order=scsi0;ide2" and kwargs["start"] == 1
    assert result["vmid"] == 999 and result["exitstatus"] == "OK"
    assert ("resource", {"type": "vm", "id": None, "change": "created"}) in events


def test_create_threads_the_wizards_vlan_tag_into_net0(tmp_path):
    """Task 17's Network step offers a VLAN. Pydantic drops unknown keys
    silently rather than 422-ing, so a missing `vlan_tag` on VmCreateIn would
    build an untagged NIC and report success, a wrong result wearing a green
    tick. Both halves are pinned here."""
    fake, status, _r, error, _e = _run_job(
        tmp_path, "vm.create",
        lambda ids: {"host_id": ids["host_id"], "node": "pve1", "vmid": 999,
                     "name": "web-01", "cores": 1, "memory_mb": 512,
                     "disk_gb": 8, "storage": "local-lvm", "iso": None,
                     "bridge": "vmbr1", "vlan_tag": 42, "ostype": "l26"})
    assert status == "succeeded", error
    assert fake.creates[0][2]["net0"] == "virtio,bridge=vmbr1,tag=42"


def test_create_omits_the_tag_entirely_when_untagged(tmp_path):
    for tag in (None, 0):
        sub = tmp_path / f"t{tag}"
        sub.mkdir()  # each run gets its own sqlite db, avoids a hosts.name
        # UNIQUE collision from reusing one db across sequential job runs
        fake, status, _r, error, _e = _run_job(
            sub, "vm.create",
            lambda ids: {"host_id": ids["host_id"], "node": "pve1", "vmid": 999,
                         "name": "web-01", "cores": 1, "memory_mb": 512,
                         "disk_gb": 8, "storage": "local-lvm", "iso": None,
                         "bridge": "vmbr0", "vlan_tag": tag, "ostype": "l26"})
        assert status == "succeeded", error
        # never `tag=` with an empty value: PVE rejects that outright
        assert fake.creates[0][2]["net0"] == "virtio,bridge=vmbr0"


def test_create_route_accepts_and_forwards_vlan_tag(tmp_path, csrf_header,
                                                     bootstrap_admin):
    app, c, fake, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        r = c.post("/api/v1/vms", headers=csrf_header(c), json={
            "host_id": ids["host_id"], "node": "pve1", "name": "web-01",
            "cores": 2, "memory_mb": 2048, "disk_gb": 32,
            "storage": "local-lvm", "bridge": "vmbr1", "vlan_tag": 42})
        assert r.status_code == 202, r.text
        with app.state.sessionmaker() as db:
            job = db.query(Job).filter_by(kind="vm.create").one()
            assert job.params["vlan_tag"] == 42


def test_create_without_an_iso_boots_from_disk_only(tmp_path):
    fake, status, _r, error, _e = _run_job(
        tmp_path, "vm.create",
        lambda ids: {"host_id": ids["host_id"], "node": "pve1", "vmid": 999,
                     "name": "web-01", "cores": 1, "memory_mb": 512,
                     "disk_gb": 8, "storage": "local-lvm"})
    assert status == "succeeded", error
    _k, _n, kwargs = fake.creates[0]
    assert "ide2" not in kwargs and kwargs["boot"] == "order=scsi0"
    assert "start" not in kwargs


def test_a_taken_vmid_fails_the_job_once_without_retrying(tmp_path):
    """PVE is the authority on vmid uniqueness. A retry loop here would race a
    second orchestrator forever and hide a real collision, so the error is
    surfaced and the job ends."""
    fake, status, _r, error, _e = _run_job(
        tmp_path, "vm.create",
        lambda ids: {"host_id": ids["host_id"], "node": "pve1", "vmid": 100,
                     "name": "web-01", "cores": 1, "memory_mb": 512,
                     "disk_gb": 8, "storage": "local-lvm"},
        tweak=lambda f: setattr(f, "create_error", "500 VM 100 already exists"))
    assert status == "failed"
    assert "already exists" in (error or "")
    assert len(fake.creates) == 1  # exactly one attempt


def test_clone_job_passes_full_through_and_surfaces_pve_rejection(tmp_path):
    # Each run gets its own sqlite db subdirectory: reusing one tmp_path
    # across sequential job runs collides on the hosts.name UNIQUE constraint.
    (tmp_path / "full").mkdir()
    (tmp_path / "linked").mkdir()
    fake, status, result, error, _e = _run_job(
        tmp_path / "full", "vm.clone",
        lambda ids: {"vm_id": ids["vm_id"], "newid": 999, "name": "web-02",
                     "full": True, "target": "pve2", "storage": "local-lvm"})
    assert status == "succeeded", error
    node, vmid, kwargs = fake.clones[0]
    assert (node, vmid) == ("pve1", 201)
    assert kwargs == {"newid": 999, "name": "web-02", "full": 1,
                      "target": "pve2", "storage": "local-lvm"}
    assert result["newid"] == 999

    # A linked clone of a non-template is refused by PVE, not by Proxploy; 
    # Proxploy does not track template-ness (see the route's ponytail comment).
    fake, status, _r, error, _e = _run_job(
        tmp_path / "linked", "vm.clone",
        lambda ids: {"vm_id": ids["vm_id"], "newid": 999, "full": False},
        tweak=lambda f: setattr(f, "clone_error",
                                "400 Parameter verification failed. full: "
                                "linked clone feasible only for template"))
    assert status == "failed"
    assert "linked clone feasible only for template" in (error or "")
    assert fake.clones[0][2]["full"] == 0  # full=False went through untouched


def test_delete_job_destroys_the_guest(tmp_path):
    fake, status, result, error, events = _run_job(
        tmp_path, "vm.delete", lambda ids: {"vm_id": ids["vm_id"]})
    assert status == "succeeded", error
    assert fake.guest_deletes == [("qemu", "pve1", 201)]
    assert result["vmid"] == 201
    assert ("resource", {"type": "vm", "id": None, "change": "deleted"}) in events


# --- delete route ----------------------------------------------------------

def test_delete_requires_the_typed_name(tmp_path, csrf_header, bootstrap_admin):
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin)
    vid = ids["vm_id"]
    with c:
        r = c.request("DELETE", f"/api/v1/vms/{vid}", json={},
                      headers=csrf_header(c))
        assert r.status_code == 409
        assert r.json()["error"] == "confirm_required"
        assert r.json()["confirm_phrase"] == "win11"
        with app.state.sessionmaker() as db:
            assert db.query(AuditEvent).filter_by(
                action="vm.delete", result="denied").count() == 1
            assert db.query(Job).count() == 0
        ok = c.request("DELETE", f"/api/v1/vms/{vid}", json={"confirm": "win11"},
                       headers=csrf_header(c))
        assert ok.status_code == 202, ok.text
        assert ok.json()["job"]["kind"] == "vm.delete"


def test_delete_refuses_a_running_vm(tmp_path, csrf_header, bootstrap_admin):
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin, vm_status="running")
    with c:
        r = c.request("DELETE", f"/api/v1/vms/{ids['vm_id']}",
                      json={"confirm": "win11"}, headers=csrf_header(c))
        assert r.status_code == 409
        assert r.json()["error"] == "guest_running"
        with app.state.sessionmaker() as db:
            assert db.query(Job).count() == 0
            assert db.query(AuditEvent).filter_by(
                action="vm.delete", result="denied",
                target_type="vm", target_id=ids["vm_id"]).count() == 1


def test_delete_refuses_a_self_targeted_vm(tmp_path, csrf_header, bootstrap_admin,
                                           monkeypatch):
    """is_self() answers False for every VM today (selfguard.py checks
    target_type == "app" first), so this branch is otherwise unreachable
    through real settings, monkeypatched here so the _deny()/audit wiring on
    this specific gate is still under test, same as the other two refusals."""
    import proxploy.api.vms as vms_module

    app, c, _f, ids = _authed(tmp_path, bootstrap_admin)
    monkeypatch.setattr(vms_module, "is_self", lambda db, kind, target_id: True)
    with c:
        r = c.request("DELETE", f"/api/v1/vms/{ids['vm_id']}",
                      json={"confirm": "win11"}, headers=csrf_header(c))
        assert r.status_code == 409
        assert r.json()["error"] == "self_target"
        assert r.json()["confirm_phrase"] == "win11"
        with app.state.sessionmaker() as db:
            assert db.query(Job).count() == 0
            assert db.query(AuditEvent).filter_by(
                action="vm.delete", result="denied",
                target_type="vm", target_id=ids["vm_id"]).count() == 1


def test_delete_requires_owner_role(tmp_path, csrf_header, bootstrap_admin):
    """doc 05 puts DELETE /vms/{id} at owner, one rung above every other VM
    route, an admin who may create and clone still may not destroy."""
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        c.post("/api/v1/users", json={"email": "adm@example.com",
                                      "password": "correct-horse-battery",
                                      "display_name": "Adm", "role": "admin"},
               headers=csrf_header(c))
        c.post("/api/v1/auth/login", json={"email": "adm@example.com",
                                           "password": "correct-horse-battery"},
               headers=csrf_header(c))
        assert c.post(f"/api/v1/vms/{ids['vm_id']}/clone", json={},
                      headers=csrf_header(c)).status_code == 202
        r = c.request("DELETE", f"/api/v1/vms/{ids['vm_id']}",
                      json={"confirm": "win11"}, headers=csrf_header(c))
        assert r.status_code == 403 and r.json()["detail"] == "forbidden"


def test_vm_mutations_require_auth(tmp_path, csrf_header):
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        ids = _seed(app)
        h = csrf_header(c)
        assert c.post("/api/v1/vms", json=_spec(ids), headers=h).status_code == 401
        assert c.post(f"/api/v1/vms/{ids['vm_id']}/clone", json={},
                      headers=h).status_code == 401
        assert c.request("DELETE", f"/api/v1/vms/{ids['vm_id']}", json={},
                         headers=h).status_code == 401
