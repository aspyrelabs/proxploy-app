"""The host page's own reads: on demand, never from the poll loop.

The fixture is a real payload captured from a PVE 9.2.10 node, not an invented
shape, so the normalisation below is tested against what Proxmox actually
sends.
"""
import json
from pathlib import Path

FIX = Path(__file__).parent / "fixtures" / "pve"


def _app(tmp_path, status=None, disks=None, fail=False):
    from fastapi.testclient import TestClient
    from proxploy.models import HostCredential
    from tests.fakes.pve import FakePVE
    from tests.support import make_app, seed_host_row

    fake = FakePVE(fail=fail)
    fake.node_status_by_node = {"pve1": status or {}}
    fake.disks_by_node = {"pve1": disks or []}
    app = make_app(tmp_path, fake=fake)
    c = TestClient(app)
    c.__enter__()
    with app.state.sessionmaker() as db:
        h = seed_host_row(db)
        h.node_name = "pve1"
        # seed_host_row does not make one, and client_for_host needs it. Without
        # this the routes 502 on a missing credential, which made the "node
        # refuses" test below pass for entirely the wrong reason.
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!mon", "token_secret": "s"}).encode())
        db.add(HostCredential(host_id=h.id, kind="api_token",
                              encrypted_blob=blob, key_version=ver,
                              public_meta="proxploy@pve!mon"))
        db.commit()
        return app, c, h.id


def test_status_normalises_the_node_payload(tmp_path, bootstrap_admin):
    raw = json.loads((FIX / "node_status.json").read_text())
    app, c, hid = _app(tmp_path, status=raw)
    bootstrap_admin(c)
    body = c.get(f"/api/v1/hosts/{hid}/nodes/pve1/status").json()

    assert body["cpu"]["model"] == "13th Gen Intel(R) Core(TM) i5-13500T"
    # Physical vs logical is the distinction an operator actually wants, and
    # PVE calls the logical count `cpus`, which reads like "number of CPUs".
    assert body["cpu"]["cores"] == 14
    assert body["cpu"]["threads"] == 20
    assert body["cpu"]["sockets"] == 1
    assert body["kernel"] == "7.0.14-11-pve"
    assert body["arch"] == "x86_64"
    assert body["boot_mode"] == "efi"
    assert body["secure_boot"] is False
    assert body["io_delay"] == raw["wait"]
    # PVE sends loadavg as strings; a UI should not have to parse them.
    assert body["load"] == [0.0, 0.0, 0.0]
    assert body["memory"]["total"] == 33306869760
    assert body["uptime_s"] == 25029


def test_load_is_returned_as_numbers_even_when_pve_sends_junk(tmp_path, bootstrap_admin):
    app, c, hid = _app(tmp_path, status={"loadavg": ["1.5", None, "oops"]})
    bootstrap_admin(c)
    assert c.get(f"/api/v1/hosts/{hid}/nodes/pve1/status").json()["load"] == [1.5, 0.0, 0.0]


def test_a_node_that_will_not_answer_is_502_not_500(tmp_path, bootstrap_admin):
    app, c, hid = _app(tmp_path, fail=True)
    bootstrap_admin(c)
    r = c.get(f"/api/v1/hosts/{hid}/nodes/pve1/status")
    # The page must be able to tell "the node did not answer" from "the app
    # broke", so a narrow token costs the strip and nothing else.
    assert r.status_code == 502, r.text


def test_hardware_lists_disks_with_health_and_wearout(tmp_path, bootstrap_admin):
    disks = [{"devpath": "/dev/nvme0n1", "model": "WD Green SN350 2TB",
              "serial": "22303K800007", "size": 2000398934016, "type": "nvme",
              "health": "PASSED", "wearout": 99, "osdid": -1, "used": "BIOS boot"}]
    app, c, hid = _app(tmp_path, disks=disks)
    bootstrap_admin(c)
    r = c.get(f"/api/v1/hosts/{hid}/nodes/pve1/hardware")
    assert r.status_code == 200, r.text
    d = r.json()["disks"][0]
    assert d["model"] == "WD Green SN350 2TB"
    assert d["health"] == "PASSED"
    assert d["wearout"] == 99
    # -1 is PVE's "not a Ceph OSD". Passing it through would read as an id.
    assert d["osd_id"] is None


def test_a_disk_that_is_an_osd_keeps_its_id(tmp_path, bootstrap_admin):
    app, c, hid = _app(tmp_path, disks=[{"devpath": "/dev/sdb", "osdid": 3}])
    bootstrap_admin(c)
    body = c.get(f"/api/v1/hosts/{hid}/nodes/pve1/hardware").json()
    assert body["disks"][0]["osd_id"] == 3


def test_an_unknown_host_is_404(tmp_path, bootstrap_admin):
    app, c, hid = _app(tmp_path)
    bootstrap_admin(c)
    assert c.get("/api/v1/hosts/9999/nodes/pve1/status").status_code == 404
