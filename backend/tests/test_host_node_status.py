"""The host page's own reads: on demand, never from the poll loop.

The fixture is a real payload captured from a PVE 9.2.10 node, not an invented
shape, so the normalisation below is tested against what Proxmox actually
sends.
"""
import json
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures" / "pve"


def _app(tmp_path, status=None, disks=None, fail=False, pci=None, services=None,
         subscription=None, dns=None, time=None, networks=None, refuse=(),
         status_forbidden=()):
    from fastapi.testclient import TestClient
    from proxploy.models import HostCredential
    from tests.fakes.pve import FakePVE
    from tests.support import make_app, seed_host_row

    fake = FakePVE(fail=fail)
    fake.node_status_by_node = {"pve1": status or {}}
    fake.disks_by_node = {"pve1": disks or []}
    fake.pci_by_node = {"pve1": pci or []}
    fake.services_by_node = {"pve1": services or []}
    fake.subscription_by_node = {"pve1": subscription or {}}
    fake.dns_by_node = {"pve1": dns or {}}
    fake.time_by_node = {"pve1": time or {}}
    fake.networks_by_node = {"pve1": networks or []}
    fake.hardware_fail_sections = set(refuse)
    fake.status_forbidden_nodes = set(status_forbidden)
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
        db.add(HostCredential(host_id=h.id, kind="api_token:monitoring",
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


# --- the rest of the hardware tab ----------------------------------------
# Every payload below is the shape a real PVE 9.2.10 node sent back, including
# the hyphenated keys systemd's service list uses.

PCI = [{"id": "0000:00:02.0", "class": "0x030000", "device": "0xa780",
        "device_name": "Raptor Lake-S GT1 [UHD Graphics 770]",
        "vendor": "0x8086", "vendor_name": "Intel Corporation",
        "subsystem_device": "0x3230", "subsystem_vendor": "0x8086",
        "subsystem_vendor_name": "Intel Corporation", "iommugroup": 2},
       {"id": "0000:00:1f.3", "class": "0x040300", "device": "0x7a50",
        "device_name": "Raptor Lake High Definition Audio Controller",
        "vendor": "0x8086", "vendor_name": "Intel Corporation",
        "subsystem_device": "0x3230", "subsystem_vendor": "0x8086",
        "subsystem_vendor_name": "Intel Corporation", "iommugroup": 13}]

SERVICES = [{"name": "pveproxy", "service": "pveproxy", "desc": "PVE API Proxy Server",
             "state": "running", "active-state": "active", "unit-state": "enabled"},
            {"name": "corosync", "service": "corosync", "desc": "Corosync Cluster Engine",
             "state": "stopped", "active-state": "inactive", "unit-state": "enabled"}]

NETWORKS = [{"iface": "vmbr0", "type": "bridge", "method": "static",
             "method6": "manual", "families": ["inet"], "active": 1,
             "exists": 1, "priority": 5},
            {"iface": "enp1s0", "type": "eth", "method": "manual",
             "method6": "manual", "families": ["inet"], "active": 1,
             "exists": 1, "altnames": ["enx000000"], "priority": 2}]

SUBSCRIPTION = {"status": "notfound", "message": "There is no subscription key",
                "serverid": "8FE4C...", "url": "https://www.proxmox.com/"}

DNS = {"dns1": "192.168.50.249", "search": "lab.local"}
TIME = {"localtime": 1754900000, "time": 1754880200, "timezone": "Asia/Kolkata"}


def _hardware(tmp_path, bootstrap_admin, **kw):
    app, c, hid = _app(tmp_path, disks=[{"devpath": "/dev/nvme0n1"}], pci=PCI,
                       services=SERVICES, networks=NETWORKS,
                       subscription=SUBSCRIPTION, dns=DNS, time=TIME, **kw)
    bootstrap_admin(c)
    return c.get(f"/api/v1/hosts/{hid}/nodes/pve1/hardware")


def test_hardware_carries_every_section_the_node_will_answer(tmp_path, bootstrap_admin):
    r = _hardware(tmp_path, bootstrap_admin)
    assert r.status_code == 200, r.text
    b = r.json()
    assert [d["devpath"] for d in b["disks"]] == ["/dev/nvme0n1"]
    assert [n["iface"] for n in b["network"]] == ["vmbr0", "enp1s0"]
    assert [p["id"] for p in b["pci"]] == ["0000:00:02.0", "0000:00:1f.3"]
    assert [s["name"] for s in b["services"]] == ["pveproxy", "corosync"]
    assert b["subscription"]["status"] == "notfound"
    assert b["dns"]["servers"] == ["192.168.50.249"]
    assert b["time"]["timezone"] == "Asia/Kolkata"
    # nothing was refused, so nothing is named as unreadable
    assert b["unreadable"] == {}


def test_hardware_renames_the_hyphenated_systemd_keys(tmp_path, bootstrap_admin):
    # "active-state" is not addressable in JS without bracket syntax, and the
    # UI should not have to know that systemd names it with a hyphen.
    s = _hardware(tmp_path, bootstrap_admin).json()["services"][0]
    assert s["active_state"] == "active"
    assert s["unit_state"] == "enabled"
    assert s["state"] == "running"
    assert s["desc"] == "PVE API Proxy Server"


def test_pci_devices_carry_a_readable_class_name(tmp_path, bootstrap_admin):
    # PVE sends the class as a raw hex code. The high byte is the PCI base
    # class, which is what makes eleven devices groupable instead of a list.
    pci = _hardware(tmp_path, bootstrap_admin).json()["pci"]
    assert pci[0]["class_name"] == "Display controller"
    assert pci[1]["class_name"] == "Multimedia controller"
    assert pci[0]["class_id"] == "0x030000"
    assert pci[0]["iommu_group"] == 2


def test_an_unrecognised_pci_class_keeps_its_raw_code(tmp_path, bootstrap_admin):
    app, c, hid = _app(tmp_path, pci=[{"id": "0000:00:00.0", "class": "0xff0000"}])
    bootstrap_admin(c)
    assert c.get(f"/api/v1/hosts/{hid}/nodes/pve1/hardware"
                 ).json()["pci"][0]["class_name"] == "0xff0000"


def test_dns_collapses_the_numbered_keys_and_skips_the_absent_ones(tmp_path, bootstrap_admin):
    # dns2/dns3 are simply absent when unset, so a fixed three-slot shape would
    # put two "unknown"s on the page for a perfectly normal resolver config.
    app, c, hid = _app(tmp_path, dns={"dns1": "1.1.1.1", "dns3": "9.9.9.9",
                                      "search": "lan"})
    bootstrap_admin(c)
    b = c.get(f"/api/v1/hosts/{hid}/nodes/pve1/hardware").json()
    assert b["dns"]["servers"] == ["1.1.1.1", "9.9.9.9"]
    assert b["dns"]["search"] == "lan"


def test_one_refused_section_costs_that_section_and_nothing_else(tmp_path, bootstrap_admin):
    # A token narrow enough to be refused /hardware/pci still answers the rest,
    # and a tab that 502s on the whole read would throw away six good sections
    # for one bad one.
    b = _hardware(tmp_path, bootstrap_admin, refuse=["pci"]).json()
    assert b["pci"] is None
    assert "pci" in b["unreadable"] and b["unreadable"]["pci"]
    assert [d["devpath"] for d in b["disks"]] == ["/dev/nvme0n1"]
    assert [s["name"] for s in b["services"]] == ["pveproxy", "corosync"]
    assert b["subscription"]["status"] == "notfound"
    assert b["time"]["timezone"] == "Asia/Kolkata"


SECTIONS = ["disks", "network", "pci", "services", "subscription", "dns", "time"]


@pytest.mark.parametrize("section", SECTIONS)
def test_every_section_can_be_refused_on_its_own(section, tmp_path, bootstrap_admin):
    r = _hardware(tmp_path, bootstrap_admin, refuse=[section])
    assert r.status_code == 200, r.text
    b = r.json()
    assert b[section] is None
    assert section in b["unreadable"]
    # and the six siblings all came back
    assert [k for k in SECTIONS if b[k] is None] == [section]


def test_the_hardware_tab_502s_only_when_the_node_is_unreachable(tmp_path, bootstrap_admin):
    app, c, hid = _app(tmp_path, fail=True)
    bootstrap_admin(c)
    r = c.get(f"/api/v1/hosts/{hid}/nodes/pve1/hardware")
    # Nothing at all could be read: that is the node being down, not a narrow
    # token, and the page should say so rather than render seven empty cards.
    assert r.status_code == 502, r.text


# --- 403 vs 502: a permission problem must not read as a generic relay -----
# Before this fix, _classify() (services/proxmox.py) had no case for "403",
# so a too-narrow token's permission failure fell through as kind="unknown"
# and the body carried nothing beyond Proxmox's own raw text under a label
# indistinguishable from an unreachable node or a broken cert. This is why
# the Sys.PowerMgmt gap gave no useful message, and it is not special to
# node power: any 403 anywhere took the same fall.

def test_a_permission_denied_403_names_the_privilege_not_a_generic_unknown(
        tmp_path, bootstrap_admin):
    # FakePVE.status_forbidden_nodes makes GET /nodes/pve1/status 403 with
    # PVE's own realistic "Permission check failed (/path, Priv)" text.
    app, c, hid = _app(tmp_path, status_forbidden={"pve1"})
    bootstrap_admin(c)
    r = c.get(f"/api/v1/hosts/{hid}/nodes/pve1/status")
    assert r.status_code == 502, r.text
    body = r.json()
    # error/detail keys, not raw text: see api/hosts.py's HTTPException(502,
    # {"error": e.kind, "detail": str(e)}) shape (main.py's problem_handler
    # merges a dict `detail` straight onto the body). Before this fix `error`
    # was "unknown" here, indistinguishable from a broken cert or a dead node.
    assert body["error"] == "permission", body
    assert "Sys.Audit" in body["detail"]
    assert "403" in body["detail"]


def test_an_unknown_host_is_404(tmp_path, bootstrap_admin):
    app, c, hid = _app(tmp_path)
    bootstrap_admin(c)
    assert c.get("/api/v1/hosts/9999/nodes/pve1/status").status_code == 404


# --- is_self: whether this is the node Proxploy itself runs on -------------
# The host actions menu (Edit/Reboot/Power off) reads this off the SAME
# query the identity rail already fetches, so the confirm dialog can warn
# BEFORE the operator types anything, not only after a rejected call.

def test_is_self_is_false_with_no_self_host_id_recorded(tmp_path, bootstrap_admin):
    app, c, hid = _app(tmp_path)
    bootstrap_admin(c)
    body = c.get(f"/api/v1/hosts/{hid}/nodes/pve1/status").json()
    assert body["is_self"] is False


def test_is_self_is_true_for_the_recorded_entry_node(tmp_path, bootstrap_admin):
    from proxploy.services.settings import set_setting

    app, c, hid = _app(tmp_path)
    with app.state.sessionmaker() as db:
        set_setting(db, "self.host_id", hid)
    bootstrap_admin(c)
    body = c.get(f"/api/v1/hosts/{hid}/nodes/pve1/status").json()
    assert body["is_self"] is True
