# backend/tests/test_backups_api.py
"""Backup mutations: run, restore (in place / as new), delete, prune.

Two safety properties are load-bearing here and each has its own test:
  1. an in-place restore over the CT Proxploy runs in is refused outright;
  2. prune-preview is a dry run and can never delete (different HTTP verb).
"""
import asyncio
import json

from fastapi.testclient import TestClient

from proxploy.models import App, Backup, Host, HostCredential, Job, Vm

VOLID_CT = "local:backup/vzdump-lxc-150-2026_07_30-02_00_00.tar.zst"
VOLID_VM = "local:backup/vzdump-qemu-201-2026_07_30-03_00_00.vma.zst"


def _fake():
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    # A stock Proxmox shape: `local` is a directory store that takes backups
    # but no rootfs, `local-lvm` is where guest disks actually live. Restores
    # that name no storage must land on the latter; PVE's own default is the
    # former, which is why every real restore failed before that was fixed.
    fake.storages_by_node = {"pve1": [{"storage": "local", "type": "dir",
                                       "content": "backup,iso", "active": 1},
                                      {"storage": "local-lvm", "type": "lvmthin",
                                       "content": "rootdir,images", "active": 1}]}
    fake.content_by_storage = {"local": [
        {"volid": VOLID_CT, "ctime": 1753840800, "size": 1,
         "verification": {"state": "ok"}}]}
    fake.nextid = 999
    return fake


def _seed(app, ct_status="stopped"):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.7:8006", node_name="pve1",
                    status="connected", pve_version="8.4.1")
        db.add(host)
        db.commit()
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!bk", "token_secret": "s3cret"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token:backup", encrypted_blob=blob,
                              key_version=ver, public_meta="proxploy@pve!bk"))
        a = App(host_id=host.id, ctid=150, name="Immich", slug="immich",
                status_cached=ct_status)
        v = Vm(host_id=host.id, vmid=201, name="win11", status="stopped")
        db.add_all([a, v])
        db.commit()
        b_ct = Backup(host_id=host.id, storage="local", volid=VOLID_CT,
                      guest_type="ct", guest_vmid=150, guest_name="Immich")
        b_vm = Backup(host_id=host.id, storage="local", volid=VOLID_VM,
                      guest_type="vm", guest_vmid=201, guest_name="win11")
        db.add_all([b_ct, b_vm])
        db.commit()
        return {"host_id": host.id, "app_id": a.id, "vm_id": v.id,
                "ct_backup": b_ct.id, "vm_backup": b_vm.id}


def _authed(tmp_path, bootstrap_admin, ct_status="stopped"):
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    c = TestClient(app)
    c.__enter__()
    bootstrap_admin(c)
    return app, c, fake, _seed(app, ct_status=ct_status)


# --- ProxmoxClient level ---------------------------------------------------

def test_prune_preview_and_prune_use_different_verbs(tmp_path):
    """The whole point of the preview: it must be structurally incapable of
    deleting anything."""
    from proxploy.services.proxmox import ProxmoxClient
    from tests.fakes.pve import make_fake_factory

    fake = _fake()
    client = ProxmoxClient("https://10.0.0.7:8006", "proxploy@pve!bk", "s3cret",
                           factory=make_fake_factory(fake))
    spec = {"prune-backups": "keep-last=3,keep-daily=7"}
    client.prune_preview("pve1", "local", spec)
    assert fake.prune_gets == [("pve1", "local", spec)]
    assert fake.prune_deletes == []
    client.prune_backups("pve1", "local", spec)
    assert fake.prune_deletes == [("pve1", "local", spec)]
    assert len(fake.prune_gets) == 1  # the preview did not re-run


def test_restore_guest_posts_to_the_guest_create_endpoint(tmp_path):
    from proxploy.services.proxmox import ProxmoxClient
    from tests.fakes.pve import make_fake_factory

    fake = _fake()
    client = ProxmoxClient("https://10.0.0.7:8006", "proxploy@pve!bk", "s3cret",
                           factory=make_fake_factory(fake))
    client.restore_guest("lxc", "pve1", 150, {"ostemplate": VOLID_CT, "restore": 1})
    kind, node, kwargs = fake.creates[0]
    assert (kind, node) == ("lxc", "pve1")
    assert kwargs == {"vmid": 150, "ostemplate": VOLID_CT, "restore": 1}


# --- job handlers ----------------------------------------------------------

def _run_job(tmp_path, kind, params, seed_status="stopped", storages=None):
    from proxploy.jobs import JobBackend
    from tests.support import make_job_app

    async def go():
        fake = _fake()
        if storages is not None:
            fake.storages_by_node = storages
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.backupjobs  # noqa: F401  (registers backup.*)

        backend = JobBackend(app)
        ids = _seed(app, ct_status=seed_status)
        with app.state.sessionmaker() as db:
            jid = backend.enqueue(db, kind=kind, params={k: (ids[v] if isinstance(v, str)
                                                             and v in ids else v)
                                                         for k, v in params.items()}).id
        await backend.wait(jid, timeout=10)
        with app.state.sessionmaker() as db:
            return fake, db.get(Job, jid).status, db.get(Job, jid).result, \
                db.get(Job, jid).error

    return asyncio.run(go())


def test_backup_run_calls_vzdump_with_the_selected_vmids(tmp_path):
    fake, status, result, error = _run_job(
        tmp_path, "backup.run",
        {"host_id": "host_id", "vmids": [150, 201], "storage": "local"})
    assert status == "succeeded", error
    node, kwargs = fake.vzdumps[0]
    assert node == "pve1"
    assert kwargs["vmid"] == "150,201" and kwargs["storage"] == "local"
    assert kwargs["mode"] == "snapshot" and "all" not in kwargs
    assert result["exitstatus"] == "OK"


def test_backup_run_with_no_vmids_backs_up_all_guests(tmp_path):
    fake, status, _, error = _run_job(tmp_path, "backup.run",
                                      {"host_id": "host_id", "vmids": []})
    assert status == "succeeded", error
    _node, kwargs = fake.vzdumps[0]
    assert kwargs["all"] == 1 and "vmid" not in kwargs


def test_restore_as_new_takes_a_fresh_vmid_and_never_forces(tmp_path):
    fake, status, result, error = _run_job(tmp_path, "backup.restore",
                                           {"backup_id": "ct_backup", "mode": "new"})
    assert status == "succeeded", error
    kind, _node, kwargs = fake.creates[0]
    assert kind == "lxc"
    assert kwargs["vmid"] == 999  # cluster_nextid(), not the guest's own 150
    assert kwargs["ostemplate"] == VOLID_CT and kwargs["restore"] == 1
    assert "force" not in kwargs
    assert result["vmid"] == 999 and result["mode"] == "new"


def test_restore_with_no_storage_picks_one_that_holds_the_guest(tmp_path):
    """Found on PVE 9.2.6, 2026-08-10: the UI sends no storage on restore
    (api/backups.ts), the route defaults it to None, and PVE then falls back to
    `local`, a directory store, which answers "storage 'local' does not support
    container directories". Restore-as-new was broken for every container on a
    default storage layout."""
    fake, status, _result, error = _run_job(tmp_path, "backup.restore",
                                            {"backup_id": "ct_backup", "mode": "new"})
    assert status == "succeeded", error
    _kind, _node, kwargs = fake.creates[0]
    assert kwargs["storage"] == "local-lvm", "picked a store that cannot hold a rootfs"


def test_restore_fails_clearly_when_nothing_can_hold_the_guest(tmp_path):
    fake, status, _result, error = _run_job(
        tmp_path, "backup.restore", {"backup_id": "ct_backup", "mode": "new"},
        storages={"pve1": [{"storage": "local", "type": "dir",
                            "content": "backup", "active": 1}]})
    assert status == "failed"
    assert "accepts rootdir" in (error or "")
    assert fake.creates == [], "asked PVE to restore anyway"


def test_restore_in_place_reuses_the_vmid_and_forces(tmp_path):
    fake, status, result, error = _run_job(tmp_path, "backup.restore",
                                           {"backup_id": "ct_backup", "mode": "in_place"})
    assert status == "succeeded", error
    _kind, _node, kwargs = fake.creates[0]
    assert kwargs["vmid"] == 150 and kwargs["force"] == 1
    assert result["mode"] == "in_place"


def test_restore_of_a_vm_backup_uses_archive_not_ostemplate(tmp_path):
    fake, status, _, error = _run_job(tmp_path, "backup.restore",
                                      {"backup_id": "vm_backup", "mode": "new"})
    assert status == "succeeded", error
    kind, _node, kwargs = fake.creates[0]
    assert kind == "qemu" and kwargs["archive"] == VOLID_VM
    assert "ostemplate" not in kwargs and "restore" not in kwargs


def test_delete_removes_the_volume_and_resyncs_the_cache(tmp_path):
    from proxploy.jobs import JobBackend
    from tests.support import make_job_app

    async def go():
        fake = _fake()
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.backupjobs  # noqa: F401

        backend = JobBackend(app)
        ids = _seed(app)
        fake.content_by_storage["local"] = []  # upstream now has nothing
        with app.state.sessionmaker() as db:
            jid = backend.enqueue(db, kind="backup.delete",
                                  params={"backup_id": ids["ct_backup"]}).id
        await backend.wait(jid, timeout=10)
        with app.state.sessionmaker() as db:
            assert db.get(Job, jid).status == "succeeded", db.get(Job, jid).error
            # the resync ran: the cache no longer lists what was deleted
            assert db.query(Backup).count() == 0
        assert fake.deleted_volumes == [("pve1", "local", VOLID_CT)]

    asyncio.run(go())


def test_prune_job_uses_the_hyphenated_param(tmp_path):
    fake, status, result, error = _run_job(
        tmp_path, "backup.prune",
        {"host_id": "host_id", "storage": "local",
         "spec": "keep-last=3,keep-daily=7", "guest_type": "ct"})
    assert status == "succeeded", error
    _node, _storage, kwargs = fake.prune_deletes[0]
    assert kwargs["prune-backups"] == "keep-last=3,keep-daily=7"
    assert kwargs["type"] == "ct"
    assert result["spec"] == "keep-last=3,keep-daily=7"


# --- routes ----------------------------------------------------------------

def test_run_route_enqueues_a_job_and_audits(tmp_path, csrf_header, bootstrap_admin):
    from proxploy.models import AuditEvent

    app, c, _fake_, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        r = c.post("/api/v1/backups/run",
                   json={"guests": [{"type": "app", "id": ids["app_id"]}]},
                   headers=csrf_header(c))
        assert r.status_code == 202, r.text
        assert r.json()["job"]["kind"] == "backup.run"
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="backup.run").one()
            assert row.job_id is not None and row.target_id == ids["host_id"]


def test_run_route_rejects_guests_spread_across_hosts(tmp_path, csrf_header,
                                                      bootstrap_admin):
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        with app.state.sessionmaker() as db:
            h2 = Host(name="host-02", address="https://10.0.0.8:8006",
                      node_name="pve2", status="connected")
            db.add(h2)
            db.commit()
            v2 = Vm(host_id=h2.id, vmid=300, name="other", status="stopped")
            db.add(v2)
            db.commit()
            other_vm = v2.id
        r = c.post("/api/v1/backups/run",
                   json={"guests": [{"type": "app", "id": ids["app_id"]},
                                    {"type": "vm", "id": other_vm}]},
                   headers=csrf_header(c))
        assert r.status_code == 422


def test_in_place_restore_requires_the_typed_name(tmp_path, csrf_header,
                                                  bootstrap_admin):
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        r = c.post(f"/api/v1/backups/{ids['ct_backup']}/restore",
                   json={"mode": "in_place"}, headers=csrf_header(c))
        assert r.status_code == 409
        # main.py::problem_handler does `body.update(exc.detail)` for a dict
        # detail, so a dict HTTPException body serialises FLAT, not nested
        # under "detail": same shape test_lifecycle_api.py already asserts.
        assert r.json()["error"] == "confirm_required"
        assert r.json()["confirm_phrase"] == "Immich"
        r = c.post(f"/api/v1/backups/{ids['ct_backup']}/restore",
                   json={"mode": "in_place", "confirm": "Immich"},
                   headers=csrf_header(c))
        assert r.status_code == 202, r.text


def test_in_place_restore_refuses_a_running_guest(tmp_path, csrf_header,
                                                  bootstrap_admin):
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin, ct_status="running")
    with c:
        r = c.post(f"/api/v1/backups/{ids['ct_backup']}/restore",
                   json={"mode": "in_place", "confirm": "Immich"},
                   headers=csrf_header(c))
        assert r.status_code == 409
        assert r.json()["error"] == "guest_running"


def test_in_place_restore_over_proxploy_itself_is_refused_even_with_confirm(
        tmp_path, csrf_header, bootstrap_admin):
    from proxploy.models import AuditEvent
    from proxploy.services.settings import set_setting

    app, c, _f, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        with app.state.sessionmaker() as db:
            set_setting(db, "self.ctid", "150")
            set_setting(db, "self.host_id", str(ids["host_id"]))
        r = c.post(f"/api/v1/backups/{ids['ct_backup']}/restore",
                   json={"mode": "in_place", "confirm": "Immich"},
                   headers=csrf_header(c))
        assert r.status_code == 409
        # FLAT envelope (main.py::problem_handler does `body.update(exc.detail)`
        # for a dict detail): the brief's own draft asserted
        # `r.json()["detail"]["error"]` here, which is wrong: `detail` in the
        # flattened body is the human-readable STRING from the exception dict's
        # own "detail" key, not a nested object, and indexing a string with
        # ["error"] raises `TypeError: string indices must be integers`. The
        # top-level keys are what the client actually receives.
        body = r.json()
        assert body["error"] == "self_target" and body["confirm_phrase"] == "Immich"
        with app.state.sessionmaker() as db:
            assert db.query(Job).filter_by(kind="backup.restore").count() == 0
            # The refused restore's only durable trace: the route calls
            # write_audit(..., result="denied") before it raises. Assert the
            # DB row itself, not the HTTP body: a future refactor could drop
            # the write_audit call, misspell the action, or flip the result
            # string, and the response-only assertions above would stay green.
            row = db.query(AuditEvent).filter_by(action="backup.restore",
                                                 target_type="backup").one()
            assert row.target_id == ids["ct_backup"] and row.result == "denied"
        # restore-as-new over the same backup is fine: it takes a fresh vmid
        r = c.post(f"/api/v1/backups/{ids['ct_backup']}/restore",
                   json={"mode": "new"}, headers=csrf_header(c))
        assert r.status_code == 202, r.text


def test_restore_as_new_needs_no_confirmation(tmp_path, csrf_header, bootstrap_admin):
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin, ct_status="running")
    with c:
        r = c.post(f"/api/v1/backups/{ids['ct_backup']}/restore", json={},
                   headers=csrf_header(c))
        assert r.status_code == 202, r.text  # default mode is "new"


def test_prune_preview_route_reads_and_prune_route_deletes(tmp_path, csrf_header,
                                                           bootstrap_admin):
    app, c, fake, ids = _authed(tmp_path, bootstrap_admin)
    fake.prune_preview_rows = [{"volid": VOLID_CT, "type": "ct", "vmid": 150,
                                "ctime": 1753840800, "mark": "remove"}]
    with c:
        r = c.get(f"/api/v1/backups/prune-preview?host_id={ids['host_id']}"
                  f"&storage=local&keep_last=3&keep_daily=7")
        assert r.status_code == 200
        assert r.json()[0]["mark"] == "remove"
        assert fake.prune_gets[0][2]["prune-backups"] == "keep-last=3,keep-daily=7"
        assert fake.prune_deletes == []  # the preview deleted nothing
        r = c.post("/api/v1/backups/prune",
                   json={"host_id": ids["host_id"], "storage": "local",
                         "keep_last": 3}, headers=csrf_header(c))
        assert r.status_code == 202, r.text


def test_prune_preview_upstream_failure_is_a_502_not_a_500(tmp_path, csrf_header,
                                                            bootstrap_admin):
    """BLOCKING 3: prune_preview_route had no ProxmoxError handling at all, 
    an unreachable host bare-500'd instead of the 502 every other read in
    this phase returns."""
    app, c, fake, ids = _authed(tmp_path, bootstrap_admin)
    fake.fail = True
    with c:
        r = c.get(f"/api/v1/backups/prune-preview?host_id={ids['host_id']}"
                  f"&storage=local&keep_last=3")
        assert r.status_code == 502


def test_prune_without_any_keep_value_is_rejected(tmp_path, csrf_header,
                                                  bootstrap_admin):
    app, c, fake, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        r = c.get(f"/api/v1/backups/prune-preview?host_id={ids['host_id']}"
                  f"&storage=local")
        assert r.status_code == 422  # an empty spec would mark everything `remove`
        r = c.post("/api/v1/backups/prune",
                   json={"host_id": ids["host_id"], "storage": "local"},
                   headers=csrf_header(c))
        assert r.status_code == 422
        assert fake.prune_deletes == []


def test_delete_route_enqueues(tmp_path, csrf_header, bootstrap_admin):
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        r = c.request("DELETE", f"/api/v1/backups/{ids['ct_backup']}",
                      headers=csrf_header(c))
        assert r.status_code == 202, r.text
        assert r.json()["job"]["kind"] == "backup.delete"


def test_every_mutation_is_authenticated(tmp_path, csrf_header):
    """`csrf_header(c)` is required even here, CSRFMiddleware runs ahead of
    routing for every mutating verb and 403s a header-less POST/DELETE before
    auth ever gets a look, same fix test_network_api.py's
    test_missing_session_is_401_not_403 already needed. Omitting it (the
    brief's own snippet does) makes every mutating assertion below see 403,
    not 401."""
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        h = csrf_header(c)
        assert c.post("/api/v1/backups/run", json={}, headers=h).status_code == 401
        assert c.post("/api/v1/backups/1/restore", json={}, headers=h).status_code == 401
        assert c.request("DELETE", "/api/v1/backups/1", headers=h).status_code == 401
        assert c.get("/api/v1/backups/prune-preview").status_code == 401
        assert c.post("/api/v1/backups/prune", json={}, headers=h).status_code == 401


def _all_paths(app):
    """Flatten app.routes in registration order.

    This FastAPI build (0.140.x) defers `include_router` into a lazy
    `_IncludedRouter` node rather than eagerly copying child routes onto
    `app.routes`, so a plain `[r.path for r in app.routes if hasattr(r, "path")]`
    (the brief's own snippet) silently returns only the 4 top-level doc routes
    and none of api_router's children, every `paths.index(...)` below would
    raise `ValueError`. `_IncludedRouter.effective_route_contexts()` is the same
    recursive walk Starlette's own dispatch uses to pick a route at request
    time, so reading it here reflects the real match order. Copied verbatim
    from tests/test_network_api.py::_all_paths, which hit this first.
    """
    paths = []
    for r in app.routes:
        if hasattr(r, "effective_route_contexts"):
            paths.extend(c.path for c in r.effective_route_contexts())
        elif hasattr(r, "path"):
            paths.append(r.path)
    return paths


def test_literal_routes_are_registered_above_the_id_routes(tmp_path):
    from tests.support import make_app

    paths = _all_paths(make_app(tmp_path))
    assert paths.index("/api/v1/backups/run") < paths.index(
        "/api/v1/backups/{backup_id}/restore")
    assert paths.index("/api/v1/backups/prune-preview") < paths.index(
        "/api/v1/backups/{backup_id}")


def test_selfguard_destructive_set_is_unchanged():
    """Backup restore/delete are NOT lifecycle verbs, see this task's note."""
    from proxploy.services.selfguard import DESTRUCTIVE

    assert DESTRUCTIVE == frozenset({"stop", "shutdown", "restart", "pause"})
