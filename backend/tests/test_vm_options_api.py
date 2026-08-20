"""The VM Options tab: GET /vms/{id}/options and its sparse PUT.

The three behaviours worth pinning are the ones that are quiet when they go
wrong. A sparse body must touch nothing it did not name. A null must REMOVE a
setting rather than write its default, because those are different states in
Proxmox and only one of them follows Proxmox's own default when it changes.
And a property string must be merged into, never rebuilt, or a save from a
form that models four sub-keys silently drops the fifth: for smbios1 the fifth
is the guest's uuid, which is the identity its operating system was licensed
against.
"""
import json

from fastapi.testclient import TestClient

from proxploy.models import AuditEvent, Host, HostCredential, Job, Vm

STORAGES = [
    {"storage": "local", "type": "dir", "content": "iso,vztmpl,backup", "active": 1},
    {"storage": "local-lvm", "type": "lvmthin", "content": "rootdir,images",
     "active": 1},
    {"storage": "nas", "type": "nfs", "content": "backup,iso,images,rootdir",
     "active": 1},
]

# Shaped after VM 108 on the lab cluster (pve-manager 9.2.11, 2026-08-20): a
# 13-key config in which acpi, kvm, tablet, onboot, protection, freeze,
# localtime, agent, hotplug, startup, startdate and vmstatestorage are all
# ABSENT. Absent means "at the Proxmox default", not false, and the read path
# has to keep that distinction visible.
VM_CONFIG = {
    "name": "debian-test",
    "ostype": "l26",
    "boot": "order=scsi0",
    "smbios1": "uuid=3820f446-3e72-4ba1-a93c-fe7dc3cc9407",
    "cores": 2,
    "memory": "2048",
    "scsi0": "local-lvm:vm-108-disk-0,size=32G",
    "net0": "virtio=BC:24:11:AA:B7:84,bridge=vmbr0",
    "digest": "89a05a0a3a3653f4949e7f6ab8163dba421c313f",
}


def _fake():
    from tests.fakes.pve import FakePVE

    f = FakePVE()
    f.guest_configs = {("qemu", 108): dict(VM_CONFIG)}
    f.storages_by_node = {"pve1": list(STORAGES)}
    return f


def _seed(app, capabilities=("monitoring", "lifecycle"), status="running"):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.9:8006", node_name="pve1",
                    status="connected", pve_version="9.2.11")
        db.add(host)
        db.commit()
        for cap in capabilities:
            blob, ver = app.state.secretstore.encrypt(json.dumps(
                {"token_id": f"proxploy@pve!{cap}", "token_secret": "s3cret"}).encode())
            db.add(HostCredential(host_id=host.id, kind=f"api_token:{cap}",
                                  encrypted_blob=blob, key_version=ver))
        v = Vm(host_id=host.id, vmid=108, name="debian-test", status=status,
               node_name="pve1")
        db.add(v)
        db.commit()
        return host.id, v.id


def _writes(fake):
    """The config dicts that actually reached PVE."""
    return [cfg for _kind, _vmid, cfg in fake.config_updates]


def test_read_reports_only_the_keys_pve_holds(tmp_path, bootstrap_admin):
    """Absent is not false. A key Proxmox does not hold is left out entirely,
    so the dialog can say "Proxmox default" instead of inventing a value that
    a save would then pin forever."""
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, vm_id = _seed(app)
        r = c.get(f"/api/v1/vms/{vm_id}/options")
        assert r.status_code == 200
        body = r.json()
        assert body["values"] == {
            "name": "debian-test", "ostype": "l26", "boot": "order=scsi0",
            "smbios1": "uuid=3820f446-3e72-4ba1-a93c-fe7dc3cc9407",
        }
        # cores/memory/scsi0/net0/digest are real config keys and none of them
        # belong to this dialog, so none of them are reported.
        assert "cores" not in body["values"] and "net0" not in body["values"]
        assert body["pending"] == {}
        assert body["running"] is True
        assert body["restricted"] == ["spice_enhancements", "amd-sev", "intel-tdx"]
        # vmstatestorage needs somewhere a suspended machine's memory can go,
        # so only stores that accept disk images qualify.
        assert body["storages"] == ["local-lvm", "nas"]


def test_read_reports_what_is_waiting_for_a_restart(tmp_path, bootstrap_admin):
    from tests.support import make_app

    fake = _fake()
    fake.pending_by_guest[("qemu", 108)] = [
        {"key": "ostype", "value": "l26", "pending": "win11"},
        {"key": "acpi", "value": "1", "delete": 1},
        {"key": "memory", "value": "2048", "pending": "4096"},
    ]
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, vm_id = _seed(app)
        body = c.get(f"/api/v1/vms/{vm_id}/options").json()
        # null is a waiting REMOVAL, which is how a setting goes back to the
        # Proxmox default; memory is not an option this dialog owns.
        assert body["pending"] == {"ostype": "win11", "acpi": None}


def test_a_sparse_body_touches_only_what_it_named(tmp_path, csrf_header,
                                                  bootstrap_admin):
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, vm_id = _seed(app)
        r = c.put(f"/api/v1/vms/{vm_id}/options",
                  json={"onboot": True, "protection": False},
                  headers=csrf_header(c))
        assert r.status_code == 200
        assert r.json()["changed"] == ["onboot", "protection"]
        # Booleans go to Proxmox as 1 and 0, and nothing else went at all.
        assert _writes(fake) == [{"onboot": 1, "protection": 0}]
        assert fake.guest_configs[("qemu", 108)]["name"] == "debian-test"
        assert fake.guest_configs[("qemu", 108)]["boot"] == "order=scsi0"
        with app.state.sessionmaker() as db:
            assert db.query(Job).count() == 0          # not a job
            row = db.query(AuditEvent).filter_by(action="vm.options").one()
            assert row.params == {"changed": ["onboot", "protection"]}


def test_null_removes_the_setting_instead_of_writing_its_default(tmp_path, csrf_header,
                                                                 bootstrap_admin):
    """The distinction the whole feature turns on. Returning `acpi` to the
    Proxmox default means DELETING the key; writing acpi=1 pins it, and stays
    pinned even if a later Proxmox defaults it to something else."""
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, vm_id = _seed(app)
        r = c.put(f"/api/v1/vms/{vm_id}/options",
                  json={"ostype": None, "tablet": None, "name": "renamed"},
                  headers=csrf_header(c))
        assert r.status_code == 200
        sent = _writes(fake)[0]
        assert sent["name"] == "renamed"
        assert sorted(sent["delete"].split(",")) == ["ostype", "tablet"]
        assert "ostype" not in sent and "tablet" not in sent
        assert "ostype" not in fake.guest_configs[("qemu", 108)]


def test_a_property_string_is_merged_and_keeps_the_uuid(tmp_path, csrf_header,
                                                        bootstrap_admin):
    """smbios1 is the case that would hurt: it carries the guest's uuid, the
    identifier its operating system reads as its machine id. Rebuilding the
    string from the form's four fields would drop it, Proxmox would mint a new
    one, and the guest would come back as a different machine."""
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, vm_id = _seed(app)
        r = c.put(f"/api/v1/vms/{vm_id}/options",
                  json={"smbios1": {"manufacturer": "QEMU", "product": "Standard"}},
                  headers=csrf_header(c))
        assert r.status_code == 200
        assert _writes(fake) == [{"smbios1": ("uuid=3820f446-3e72-4ba1-a93c-fe7dc3cc9407,"
                                              "manufacturer=QEMU,product=Standard")}]


def test_a_sub_key_set_to_null_leaves_its_siblings_alone(tmp_path, csrf_header,
                                                         bootstrap_admin):
    from tests.support import make_app

    fake = _fake()
    fake.guest_configs[("qemu", 108)]["boot"] = "order=scsi0;ide2"
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, vm_id = _seed(app)
        c.put(f"/api/v1/vms/{vm_id}/options",
              json={"smbios1": {"uuid": None, "family": "lab"}},
              headers=csrf_header(c))
        assert _writes(fake) == [{"smbios1": "family=lab"}]


def test_emptying_a_property_string_becomes_a_delete(tmp_path, csrf_header,
                                                     bootstrap_admin):
    """Proxmox has no representation for an empty property string, so clearing
    the last sub-key means the setting is gone, not set to ""."""
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, vm_id = _seed(app)
        c.put(f"/api/v1/vms/{vm_id}/options", json={"smbios1": {"uuid": None}},
              headers=csrf_header(c))
        assert _writes(fake) == [{"delete": "smbios1"}]


def test_a_bare_default_sub_key_is_named_before_it_is_merged(tmp_path, csrf_header,
                                                             bootstrap_admin):
    """`agent: 1` is Proxmox's short spelling of `enabled=1`, and the same
    trick applies to boot's `legacy` and startup's `order`. Merged naively the
    bare token reads as a sub-key of its own, and switching the agent off would
    produce `1,enabled=0`: two values for one sub-key, stale one first."""
    from tests.support import make_app

    fake = _fake()
    fake.guest_configs[("qemu", 108)]["agent"] = "1,fstrim_cloned_disks=1"
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, vm_id = _seed(app)
        c.put(f"/api/v1/vms/{vm_id}/options", json={"agent": {"enabled": False}},
              headers=csrf_header(c))
        assert _writes(fake) == [{"agent": "enabled=0,fstrim_cloned_disks=1"}]


def test_pending_reboot_comes_from_the_guests_own_pending_config(tmp_path, csrf_header,
                                                                 bootstrap_admin):
    """Never from the write's return value: that endpoint is Proxmox's
    synchronous one and always returns null. See guest_config_update."""
    from tests.support import make_app

    fake = _fake()
    fake.pending_by_guest[("qemu", 108)] = [
        {"key": "ostype", "value": "l26", "pending": "win11"},
    ]
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, vm_id = _seed(app)
        body = c.put(f"/api/v1/vms/{vm_id}/options", json={"ostype": "win11"},
                     headers=csrf_header(c)).json()
        assert body["pending_reboot"] is True
        assert body["pending"] == {"ostype": "win11"}
        assert body["detail"] is None


def test_a_hot_setting_does_not_claim_a_restart_is_needed(tmp_path, csrf_header,
                                                          bootstrap_admin):
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())          # nothing waiting
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, vm_id = _seed(app)
        body = c.put(f"/api/v1/vms/{vm_id}/options", json={"onboot": True},
                     headers=csrf_header(c)).json()
        assert body["pending_reboot"] is False and body["pending"] == {}


def test_a_root_only_setting_is_refused_here_and_never_reaches_pve(tmp_path, csrf_header,
                                                                   bootstrap_admin):
    """spice_enhancements, amd-sev and intel-tdx are in no privilege bucket in
    Proxmox's own permission check, so its fall-through refuses them for every
    API token. Forwarding one buys a Proxmox 500 and a message nobody can act
    on, so it is refused here with one that says what to do instead."""
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, vm_id = _seed(app)
        r = c.put(f"/api/v1/vms/{vm_id}/options",
                  json={"amd-sev": "type=std", "onboot": True},
                  headers=csrf_header(c))
        assert r.status_code == 403
        # main.py's problem_handler merges a dict detail into the top level.
        body = r.json()
        assert body["error"] == "root_only_option"
        assert "amd-sev" in body["detail"] and "root" in body["detail"]
        assert fake.config_updates == []       # including the legal key alongside it


def test_an_unsupported_key_is_refused_by_name(tmp_path, csrf_header, bootstrap_admin):
    """The config dict is unpacked straight into the Proxmox call, so the key
    space is a trust boundary, not a convenience."""
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, vm_id = _seed(app)
        r = c.put(f"/api/v1/vms/{vm_id}/options", json={"memory": 4096},
                  headers=csrf_header(c))
        assert r.status_code == 422 and "memory" in r.json()["detail"]
        assert fake.config_updates == []


def test_an_empty_body_is_422_not_an_empty_write(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, vm_id = _seed(app)
        r = c.put(f"/api/v1/vms/{vm_id}/options", json={}, headers=csrf_header(c))
        assert r.status_code == 422 and r.json()["detail"] == "nothing to change"
        assert fake.config_updates == []


def test_the_read_half_runs_on_the_monitoring_token(tmp_path, bootstrap_admin):
    """/config and /pending need only VM.Audit, and monitoring is the one
    capability every enrolled host is guaranteed to have. A host with only a
    lifecycle token therefore cannot serve this read, which is what proves the
    read is not quietly borrowing the write's client."""
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, vm_id = _seed(app, capabilities=("lifecycle",))
        r = c.get(f"/api/v1/vms/{vm_id}/options")
        assert r.status_code == 502
        assert "monitoring API token" in r.json()["detail"]


def test_the_write_half_runs_on_the_lifecycle_token(tmp_path, csrf_header,
                                                    bootstrap_admin):
    """And the mirror image: with only a monitoring token the write cannot
    even be attempted, and nothing is logged as a settings change because
    nothing was sent."""
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, vm_id = _seed(app, capabilities=("monitoring",))
        r = c.put(f"/api/v1/vms/{vm_id}/options", json={"onboot": True},
                  headers=csrf_header(c))
        assert r.status_code == 502
        assert "lifecycle API token" in r.json()["detail"]
        assert fake.config_updates == []
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="vm.options_read").one()
            assert row.result == "error" and row.target_id == vm_id
            assert db.query(AuditEvent).filter_by(action="vm.options").count() == 0


def test_a_failed_write_still_leaves_an_audit_trace(tmp_path, csrf_header,
                                                    bootstrap_admin, monkeypatch):
    from proxploy.services.proxmox import ProxmoxClient, ProxmoxError
    from tests.support import make_app

    def boom(*a, **kw):
        raise ProxmoxError("fake PVE refused the write")

    monkeypatch.setattr(ProxmoxClient, "guest_config_update", boom)
    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, vm_id = _seed(app)
        r = c.put(f"/api/v1/vms/{vm_id}/options", json={"onboot": True},
                  headers=csrf_header(c))
        assert r.status_code == 502
        assert r.json()["error"] == "pve_error"
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="vm.options").one()
            assert row.result == "error" and row.params == {"changed": ["onboot"]}


def test_a_stopped_machine_reads_as_not_running(tmp_path, bootstrap_admin):
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, vm_id = _seed(app, status="stopped")
        assert c.get(f"/api/v1/vms/{vm_id}/options").json()["running"] is False
