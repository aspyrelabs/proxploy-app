"""VM CD-ROM: GET /vms/{id}/cdrom and its PUT.

The write only ever sets an ide slot to a volid or to "none", both with
media=cdrom. The guard worth pinning is the one that stops it from ever
writing over a slot that is not already a CD-ROM drive: PVE has no separate
signal for "this ide slot is a data disk", so the only way to know is to
read the config first and check what is actually there.
"""
import json

from fastapi.testclient import TestClient

from proxploy.models import AuditEvent, Host, HostCredential, Vm

ISO_VOLID = "local:iso/debian-12.7.0-amd64-netinst.iso"


def _fake(ide2=None, extra_config=None):
    from tests.fakes.pve import FakePVE

    f = FakePVE()
    cfg = {
        "name": "debian-test", "ostype": "l26", "boot": "order=scsi0",
        "cores": 2, "memory": "2048", "scsi0": "local-lvm:vm-108-disk-0,size=32G",
    }
    if ide2 is not None:
        cfg["ide2"] = ide2
    if extra_config:
        cfg.update(extra_config)
    f.guest_configs = {("qemu", 108): cfg}
    f.content_by_storage = {
        "local": [{"volid": ISO_VOLID, "content": "iso", "format": "iso",
                  "size": 700000000}],
    }
    return f


def _seed(app):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.9:8006", node_name="pve1",
                    status="connected", pve_version="9.2.11")
        db.add(host)
        db.commit()
        for cap in ("monitoring", "lifecycle"):
            blob, ver = app.state.secretstore.encrypt(json.dumps(
                {"token_id": f"proxploy@pve!{cap}", "token_secret": "s3cret"}).encode())
            db.add(HostCredential(host_id=host.id, kind=f"api_token:{cap}",
                                  encrypted_blob=blob, key_version=ver))
        v = Vm(host_id=host.id, vmid=108, name="debian-test", status="stopped",
               node_name="pve1")
        db.add(v)
        db.commit()
        return v.id


def _writes(fake):
    return [cfg for _kind, _vmid, cfg in fake.config_updates]


def test_read_reports_nothing_mounted_when_there_is_no_cdrom_drive(tmp_path,
                                                                    bootstrap_admin):
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        bootstrap_admin(c)
        vm_id = _seed(app)
        r = c.get(f"/api/v1/vms/{vm_id}/cdrom")
        assert r.status_code == 200
        assert r.json() == {"key": None, "volid": None, "mounted": False}


def test_read_reports_what_is_mounted(tmp_path, bootstrap_admin):
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake(ide2=f"{ISO_VOLID},media=cdrom"))
    with TestClient(app) as c:
        bootstrap_admin(c)
        vm_id = _seed(app)
        body = c.get(f"/api/v1/vms/{vm_id}/cdrom").json()
        assert body == {"key": "ide2", "volid": ISO_VOLID, "mounted": True}


def test_mount_sets_ide2_to_the_volid_with_media_cdrom(tmp_path, csrf_header,
                                                        bootstrap_admin):
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        vm_id = _seed(app)
        r = c.put(f"/api/v1/vms/{vm_id}/cdrom", json={"volid": ISO_VOLID},
                  headers=csrf_header(c))
        assert r.status_code == 200
        assert r.json() == {"key": "ide2", "volid": ISO_VOLID, "mounted": True}
        assert _writes(fake) == [{"ide2": f"{ISO_VOLID},media=cdrom"}]
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="vm.cdrom").one()
            assert row.params == {"ide_key": "ide2", "volid": ISO_VOLID}


def test_eject_sets_none_media_cdrom_and_leaves_the_drive_attached(tmp_path,
                                                                    csrf_header,
                                                                    bootstrap_admin):
    from tests.support import make_app

    fake = _fake(ide2=f"{ISO_VOLID},media=cdrom")
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        vm_id = _seed(app)
        r = c.put(f"/api/v1/vms/{vm_id}/cdrom", json={"volid": None},
                  headers=csrf_header(c))
        assert r.status_code == 200
        assert r.json() == {"key": "ide2", "volid": None, "mounted": False}
        assert _writes(fake) == [{"ide2": "none,media=cdrom"}]


def test_a_volid_the_host_does_not_offer_is_refused(tmp_path, csrf_header,
                                                     bootstrap_admin):
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        vm_id = _seed(app)
        r = c.put(f"/api/v1/vms/{vm_id}/cdrom",
                  json={"volid": "local:iso/not-a-real-iso.iso"},
                  headers=csrf_header(c))
        assert r.status_code == 422
        assert fake.config_updates == []


def test_the_guard_refuses_to_overwrite_a_disk_when_no_ide_slot_is_free(
        tmp_path, csrf_header, bootstrap_admin):
    """Every ide slot on this guest already holds a disk, so there is nowhere
    to write a CD-ROM drive without destroying one. This is the one guard the
    whole feature turns on: it must refuse, not pick a slot and overwrite it."""
    from tests.support import make_app

    fake = _fake(ide2="local-lvm:vm-108-disk-1,size=10G", extra_config={
        "ide0": "local-lvm:vm-108-disk-2,size=5G",
        "ide1": "local-lvm:vm-108-disk-3,size=5G",
        "ide3": "local-lvm:vm-108-disk-4,size=5G",
    })
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        vm_id = _seed(app)
        r = c.put(f"/api/v1/vms/{vm_id}/cdrom", json={"volid": ISO_VOLID},
                  headers=csrf_header(c))
        assert r.status_code == 422
        assert r.json()["error"] == "no_free_ide_slot"
        assert fake.config_updates == []
        assert fake.guest_configs[("qemu", 108)]["ide2"] == \
            "local-lvm:vm-108-disk-1,size=10G"


def test_a_data_disk_on_ide2_moves_the_mount_to_the_next_free_ide_slot(
        tmp_path, csrf_header, bootstrap_admin):
    """ide2 is preferred, but a data disk already there is never clobbered:
    the write goes to the next ide slot PVE has not put a disk on."""
    from tests.support import make_app

    fake = _fake(ide2="local-lvm:vm-108-disk-1,size=10G")
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        vm_id = _seed(app)
        r = c.put(f"/api/v1/vms/{vm_id}/cdrom", json={"volid": ISO_VOLID},
                  headers=csrf_header(c))
        assert r.status_code == 200
        assert r.json()["key"] == "ide0"
        assert _writes(fake) == [{"ide0": f"{ISO_VOLID},media=cdrom"}]
        assert fake.guest_configs[("qemu", 108)]["ide2"] == \
            "local-lvm:vm-108-disk-1,size=10G"
