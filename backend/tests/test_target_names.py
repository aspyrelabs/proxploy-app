"""Jobs and audit rows record the NAME of what they acted on, not just its id.

"vm 3" in the tray and in the audit log names nothing anybody remembers a
month later, and for the destructive actions there is no way to find out: the
row that held the name was deleted by the very job being described. So the
name is captured on the write path (JobBackend.enqueue and write_audit), which
always runs before the work does.
"""
import json

from fastapi.testclient import TestClient

from proxploy.models import App, AuditEvent, Host, HostCredential, Job, Vm
from proxploy.services.audit import resolve_target_name


def _seed(app, *, vm_name="win11", vm_status="stopped"):
    with app.state.sessionmaker() as db:
        host = Host(name="node1.lab", address="https://10.0.0.7:8006",
                    node_name="pve1", status="connected", pve_version="8.4.1")
        db.add(host)
        db.commit()
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!vm", "token_secret": "s3cret"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token:lifecycle",
                              encrypted_blob=blob, key_version=ver,
                              public_meta="proxploy@pve!vm"))
        v = Vm(host_id=host.id, vmid=201, name=vm_name, status=vm_status)
        a = App(host_id=host.id, ctid=101, name="debian-test", slug="debian-test")
        db.add_all([v, a])
        db.commit()
        return {"host_id": host.id, "vm_id": v.id, "app_id": a.id}


def _authed(tmp_path, bootstrap_admin, **kw):
    from tests.fakes.pve import FakePVE
    from tests.support import make_app, seed_snapshot

    app = make_app(tmp_path, fake=FakePVE())
    c = TestClient(app)
    c.__enter__()
    bootstrap_admin(c)
    ids = _seed(app, **kw)
    seed_snapshot(app, ids["host_id"], nodes=[{"node": "pve1"}])
    return app, c, ids


# --- the resolver ----------------------------------------------------------

def test_resolver_names_each_target_kind(tmp_path, bootstrap_admin):
    app, c, ids = _authed(tmp_path, bootstrap_admin)
    with c, app.state.sessionmaker() as db:
        assert resolve_target_name(db, "vm", ids["vm_id"]) == "win11"
        assert resolve_target_name(db, "app", ids["app_id"]) == "debian-test"
        assert resolve_target_name(db, "host", ids["host_id"]) == "node1.lab"
        # Nothing to name: no target, a kind with no human name, and a target
        # that is already gone all answer None rather than inventing one.
        assert resolve_target_name(db, None, None) is None
        assert resolve_target_name(db, "system", 1) is None
        assert resolve_target_name(db, "vm", 99999) is None


def test_unnamed_guest_falls_back_to_its_id(tmp_path, bootstrap_admin):
    app, c, ids = _authed(tmp_path, bootstrap_admin, vm_name="")
    with c, app.state.sessionmaker() as db:
        assert resolve_target_name(db, "vm", ids["vm_id"]) == "VM 201"


# --- capture before the thing is destroyed ---------------------------------

def test_destroy_job_keeps_the_name_after_the_guest_is_gone(
        tmp_path, csrf_header, bootstrap_admin):
    """The whole point. The delete job outlives the row it is about, so the
    name has to be read at enqueue time, not looked up when the tray renders."""
    app, c, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        r = c.request("DELETE", f"/api/v1/vms/{ids['vm_id']}",
                      json={"confirm": "win11"}, headers=csrf_header(c))
        assert r.status_code == 202, r.text
        assert r.json()["job"]["target_name"] == "win11"

        # What the job handler does at the end of a successful delete.
        with app.state.sessionmaker() as db:
            db.delete(db.get(Vm, ids["vm_id"]))
            db.commit()

        with app.state.sessionmaker() as db:
            job = db.query(Job).filter_by(kind="vm.delete").one()
            assert job.target_name == "win11"
            row = db.query(AuditEvent).filter_by(action="vm.delete",
                                                 result="ok").one()
            assert row.target_name == "win11"

        # And the API still hands it to the tray with the guest long gone.
        listed = c.get("/api/v1/jobs").json()
        assert [j["target_name"] for j in listed if j["kind"] == "vm.delete"] == ["win11"]


def test_denied_action_records_the_name_too(tmp_path, csrf_header, bootstrap_admin):
    app, c, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        r = c.request("DELETE", f"/api/v1/vms/{ids['vm_id']}", json={},
                      headers=csrf_header(c))
        assert r.status_code == 409
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="vm.delete",
                                                 result="denied").one()
            assert row.target_name == "win11"


# --- every enqueue path, not just the ones that remembered to ask ----------

def test_lifecycle_and_host_routes_name_their_target(tmp_path, csrf_header,
                                                     bootstrap_admin):
    """A representative site per enqueue path: the app and VM lifecycle
    wildcards (which go through api/apps.py::enqueue_lifecycle, NOT
    enqueue_and_audit) and a plain enqueue_and_audit route. None of them pass
    a name; JobBackend.enqueue reads it, which is what stops a future route
    from forgetting."""
    app, c, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        h = csrf_header(c)
        assert c.post(f"/api/v1/vms/{ids['vm_id']}/start",
                      json={}, headers=h).status_code == 202
        assert c.post(f"/api/v1/apps/{ids['app_id']}/start",
                      json={}, headers=h).status_code == 202
        with app.state.sessionmaker() as db:
            names = {j.kind: j.target_name for j in db.query(Job).all()}
            assert names["vm.start"] == "win11"
            assert names["app.start"] == "debian-test"
            for kind, name in names.items():
                assert name is not None, f"{kind} enqueued with no target name"


def test_audit_row_prefers_the_captured_name_over_a_live_lookup(
        tmp_path, csrf_header, bootstrap_admin):
    """api/audit.py used to label rows by looking the target up when the page
    was read, which is why a deleted host printed "host #2". The stored name
    now wins, and an older row with none still resolves the old way."""
    app, c, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        c.request("DELETE", f"/api/v1/vms/{ids['vm_id']}",
                  json={"confirm": "win11"}, headers=csrf_header(c))
        with app.state.sessionmaker() as db:
            db.delete(db.get(Vm, ids["vm_id"]))
            db.commit()
        rows = c.get("/api/v1/audit").json()
        deletes = [r for r in rows if r["action"] == "vm.delete"]
        assert deletes and all(r["target_label"] == "win11" for r in deletes)


# --- the thing that did not exist yet when the row was written -------------
#
# The install, the create and the clone all record a REQUEST: the App or Vm
# row they are about is written later, by the job. There is nothing for
# resolve_target_name to look up, so left alone these rows took the name of
# the HOST they pointed at and the trail read "App Install / node1.lab",
# which never says which app. Each route now records what was asked for.

def _installable(app, host_id, slug="redis"):
    """The two gates the install route clears before it enqueues anything: an
    enrolled ssh_key on the host, and a catalog entry classified installable."""
    from proxploy.models import CatalogEntry, HostCredential

    with app.state.sessionmaker() as db:
        db.add(CatalogEntry(slug=slug, name="Redis", installable=True))
        db.add(HostCredential(host_id=host_id, kind="ssh_key", encrypted_blob=b"x",
                              key_version=1, public_meta="ssh-ed25519 AAAA"))
        db.commit()


def test_install_names_the_app_its_ctid_and_the_host(tmp_path, csrf_header,
                                                     bootstrap_admin):
    """The reported bug: the audit log said "App Install" and nothing else."""
    app, c, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        _installable(app, ids["host_id"])
        r = c.post("/api/v1/catalog/redis/install",
                   json={"host_id": ids["host_id"], "name": "Redis", "ctid": 150,
                         "consent": True}, headers=csrf_header(c))
        assert r.status_code == 202, r.text
        assert r.json()["job"]["target_name"] == "Redis (CT 150) on node1.lab"
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="app.install").one()
            assert row.target_name == "Redis (CT 150) on node1.lab"
        # And it reaches the screen, which is where the bug was seen.
        listed = c.get("/api/v1/audit").json()
        assert [x["target_label"] for x in listed if x["action"] == "app.install"] \
            == ["Redis (CT 150) on node1.lab"]


def test_install_without_a_ctid_still_names_the_app_and_the_host(
        tmp_path, csrf_header, bootstrap_admin):
    """A blank ctid means the node picks the next free one, so there is no
    container id to record. The app and the host are still knowable, and a
    row that names those two beats one that names neither."""
    app, c, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        _installable(app, ids["host_id"])
        r = c.post("/api/v1/catalog/redis/install",
                   json={"host_id": ids["host_id"], "name": "Redis",
                         "consent": True}, headers=csrf_header(c))
        assert r.status_code == 202, r.text
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="app.install").one()
            assert row.target_name == "Redis on node1.lab"


def test_uninstall_names_the_app(tmp_path, csrf_header, bootstrap_admin):
    """The other half of the report. This one always worked, because the App
    row still exists when the row is written, and it stays working."""
    app, c, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        r = c.request("DELETE", f"/api/v1/apps/{ids['app_id']}",
                      json={"confirm": "debian-test"}, headers=csrf_header(c))
        assert r.status_code == 200, r.text
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="app.uninstall").one()
            assert row.target_name == "debian-test"


def test_vm_create_names_the_guest_not_the_host(tmp_path, csrf_header,
                                                bootstrap_admin):
    app, c, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        r = c.post("/api/v1/vms",
                   json={"host_id": ids["host_id"], "name": "web-01", "node": "pve1",
                         "vmid": 310, "cores": 2, "memory_mb": 2048,
                         "disk_gb": 32, "storage": "local-lvm"},
                   headers=csrf_header(c))
        assert r.status_code == 202, r.text
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="vm.create").one()
            assert row.target_name == "web-01 (VM 310) on node1.lab"


def test_clone_names_both_the_source_and_the_copy(tmp_path, csrf_header,
                                                  bootstrap_admin):
    """target_id points at the source, which is the row that exists. Without
    the copy in the name, two clones of one template read identically."""
    app, c, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        r = c.post(f"/api/v1/vms/{ids['vm_id']}/clone",
                   json={"name": "web-02", "newid": 311}, headers=csrf_header(c))
        assert r.status_code == 202, r.text
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="vm.clone").one()
            assert row.target_name == "win11 to web-02 (VM 311)"


# --- the thing that has no row of its own ---------------------------------
#
# A snapshot, a storage definition and a bridge are all named on a host or a
# guest rather than in a table of their own, so target_id points at the owner
# and the name has to carry the rest. Storage was the worst of the three: its
# target_id is a HOST id, so an unnamed row rendered as "storage #1", an id
# that belongs to a different table entirely.

def test_snapshot_rows_name_the_snapshot_and_the_guest(tmp_path, csrf_header,
                                                       bootstrap_admin):
    app, c, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        h = csrf_header(c)
        assert c.post(f"/api/v1/vms/{ids['vm_id']}/snapshots",
                      json={"name": "nightly"}, headers=h).status_code == 202
        assert c.request("DELETE",
                         f"/api/v1/vms/{ids['vm_id']}/snapshots/nightly",
                         headers=h).status_code == 202
        with app.state.sessionmaker() as db:
            names = {r.action: r.target_name for r in db.query(AuditEvent)
                     .filter(AuditEvent.action.like("vm.snapshot%"))}
            assert names == {"vm.snapshot_create": "nightly on win11",
                             "vm.snapshot_delete": "nightly on win11"}


def test_storage_rows_name_the_storage_not_a_host_id(tmp_path, csrf_header,
                                                     bootstrap_admin):
    app, c, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        r = c.post("/api/v1/storage",
                   json={"host_id": ids["host_id"], "storage": "nfs-media",
                         "type": "nfs", "config": {"server": "10.0.0.30",
                                                   "export": "/media"}},
                   headers=csrf_header(c))
        assert r.status_code == 201, r.text
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="storage.create").one()
            assert row.target_name == "nfs-media on node1.lab"
        listed = c.get("/api/v1/audit").json()
        assert [x["target_label"] for x in listed
                if x["action"] == "storage.create"] == ["nfs-media on node1.lab"]


def test_api_key_rows_name_the_key(tmp_path, csrf_header, bootstrap_admin):
    """No route passes this one: `api_key` joined TARGET_LABELS, so the
    resolver answers for it the way it does for a host or a VM."""
    app, c, _ids = _authed(tmp_path, bootstrap_admin)
    with c:
        r = c.post("/api/v1/api-keys", json={"name": "ci-runner", "scopes": []},
                   headers=csrf_header(c))
        assert r.status_code == 201, r.text
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="apikey.create").one()
            assert row.target_name == "ci-runner"


def test_bridge_rows_name_the_interface_and_the_node(tmp_path, csrf_header,
                                                     bootstrap_admin):
    app, c, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        r = c.post("/api/v1/network/bridges", headers=csrf_header(c),
                   json={"host_id": ids["host_id"], "node": "pve1",
                         "iface": "vmbr9", "type": "bridge",
                         "config": {"bridge_ports": "enp3s0"}})
        assert r.status_code == 201, r.text
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="network.host_config").one()
            assert row.target_name == "vmbr9 on pve1"


def test_adopt_names_the_apps_it_took_over(tmp_path, csrf_header,
                                           bootstrap_admin):
    """One row covers the batch, so there is no single target to point at.
    The names are what make it answerable without opening params, which the
    audit screen never shows."""
    app, c, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        r = c.post("/api/v1/apps/adopt", headers=csrf_header(c),
                   json={"items": [{"host_id": ids["host_id"], "ctid": 120,
                                    "name": "plex"},
                                   {"host_id": ids["host_id"], "ctid": 121,
                                    "name": "pihole"}]})
        assert r.status_code == 200, r.text
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="apps.adopt").one()
            assert row.target_name == "plex, pihole"


def test_adopting_a_big_batch_caps_the_list(tmp_path, csrf_header,
                                            bootstrap_admin):
    """Forty names in one cell pushes every other column off the screen. The
    full set is still in params."""
    app, c, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        r = c.post("/api/v1/apps/adopt", headers=csrf_header(c),
                   json={"items": [{"host_id": ids["host_id"], "ctid": 200 + n,
                                    "name": f"ct{n}"} for n in range(7)]})
        assert r.status_code == 200, r.text
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="apps.adopt").one()
            assert row.target_name == "ct0, ct1, ct2, ct3, ct4 and 2 more"
