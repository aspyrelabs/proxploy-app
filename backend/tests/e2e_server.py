"""Serve the REAL app to Playwright with fake PVE and SSH behind it.

This exists so the e2e suite can drive the actual onboarding wizard, 
including POST /hosts, which probes a live Proxmox API and therefore could
never run here. It lives in tests/ deliberately: packaging/build_release.sh
excludes tests/ from the release tarball, so none of this ships. An env var
honoured by main.py would have been simpler and would also have been a
backdoor that swaps a core client in the production binary, in a product
whose trust story is root-on-node.

What it proves: the product's own logic, routing and UI, end to end.
What it does not prove: behaviour against real Proxmox hardware.
"""
import os
from datetime import datetime, timezone
from pathlib import Path

NODE = "pve1"
ISO_STORAGE = "local"
IMAGES_STORAGE = "local-lvm"
DEMO_CATALOG_SLUG = "e2e-demo"


def _seed_catalog(settings) -> None:
    """CatalogEntry rows normally arrive via CatalogSource hitting the real
    community-scripts/ProxmoxVE repo on GitHub (services/catalog.py), no
    network here, and there never will be. Seeded directly against the DB
    file, once, before create_app()'s own lifespan runs (which re-runs
    migrations idempotently and opens its own engine on the same file), the
    Store page needs something installable from the very first load, and
    there is no API that creates a catalog entry without that network call.
    """
    from proxploy.db import make_engine, make_sessionmaker, run_migrations
    from proxploy.models import CatalogEntry
    from proxploy.secretstore import SecretStore

    # SecretStore.ensure_key_file refuses to mint a key once a DB file already
    # exists (doc 11 §9: never silently regenerate a key over stored
    # ciphertext), and run_migrations() below is what creates the sqlite file.
    # Idempotent: create_app()'s own lifespan calls this again with
    # db_file_exists=True and just finds the key already there.
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    SecretStore.ensure_key_file(settings.master_key_file, db_file_exists=False)
    run_migrations(settings)
    engine = make_engine(settings)
    try:
        with make_sessionmaker(engine)() as db:
            if db.query(CatalogEntry).filter_by(slug=DEMO_CATALOG_SLUG).one_or_none():
                return
            db.add(CatalogEntry(
                slug=DEMO_CATALOG_SLUG, name="E2E Demo", category="Productivity",
                description="Fixture catalog entry for the e2e journey, a real "
                            "install comes from community-scripts/ProxmoxVE.",
                default_cpu=1, default_ram_mb=512, default_disk_gb=4,
                default_os="debian", default_os_version="12",
                installable=True, unsupported_reason=None,
                upstream_sha="e2e0000000000000000000000000000000000000",
                script_path=f"ct/{DEMO_CATALOG_SLUG}.sh",
                raw={"ct_script": "#!/usr/bin/env bash\napp=e2e-demo\n",
                     "install_script": "#!/usr/bin/env bash\necho installed\n"},
                synced_at=datetime.now(timezone.utc).replace(tzinfo=None),
            ))
            db.commit()
    finally:
        engine.dispose()


def _mirror_guest_creates(fake) -> None:
    """A real Proxmox node reflects a newly created guest in its very next
    /cluster/resources listing; FakePVE's guest-create call
    (tests/fakes/pve.py::_GuestFactory.post) only records the call. GET /vms
    exists solely as the poller's mirror of that listing (services/
    guestjobs.py::create_vm: "no Vm row is written here ... the next poll
    cycle either confirms or deletes"), so without this, a VM created
    through the wizard would never appear on the Virtual Machines page here.

    Patched on this one FakePVE instance, not in the shared fixture: every
    other test's FakePVE keeps today's exact behaviour, and e2e-only fixture
    shape belongs in this file (Task 15's rationale for why it lives here at
    all).
    """
    orig_record_action = fake._record_action

    def record_and_discover(kind, vmid, action):
        upid = orig_record_action(kind, vmid, action)
        if action == "create" and kind == "qemu" and vmid:
            _, node, kwargs = fake.creates[-1]
            fake.resources.append({
                "type": "qemu", "vmid": vmid, "node": node,
                "name": kwargs.get("name") or f"qemu-{vmid}", "status": "running",
                "cpu": 0.01, "maxcpu": int(kwargs.get("cores") or 1),
                "mem": 0, "maxmem": int(kwargs.get("memory") or 512) * 1024 * 1024,
                "maxdisk": 0, "uptime": 5,
            })
        return upid

    fake._record_action = record_and_discover


def _seed_pve():
    from tests.fakes.pve import FakePVE

    fake = FakePVE(version={"version": "8.4.1", "release": "8.4"}, resources=[
        {"type": "node", "node": NODE, "status": "online",
         "cpu": 0.05, "maxcpu": 4, "mem": 2147483648, "maxmem": 8589934592,
         "uptime": 100000},
        # Two datastores so the VM-create wizard's ISO and target-storage
        # selects each have something real to offer (Task 16's own VM step).
        {"type": "storage", "storage": ISO_STORAGE, "node": NODE,
         "plugintype": "dir", "content": "iso,vztmpl,backup", "shared": 0,
         "disk": 5_000_000_000, "maxdisk": 50_000_000_000, "status": "available"},
        {"type": "storage", "storage": IMAGES_STORAGE, "node": NODE,
         "plugintype": "lvmthin", "content": "images,rootdir", "shared": 0,
         "disk": 5_000_000_000, "maxdisk": 100_000_000_000, "status": "available"},
    ])
    fake.add_ct(101, node=NODE, name="demo-ct", status="running")
    fake.content_by_storage[ISO_STORAGE] = [
        {"volid": f"{ISO_STORAGE}:iso/ubuntu-24.04-live-server-amd64.iso",
         "content": "iso", "format": "iso", "size": 1_500_000_000},
    ]
    fake.networks_by_node[NODE] = [
        {"iface": "vmbr0", "type": "bridge", "method": "static",
         "active": 1, "autostart": 1, "bridge_ports": "eno1"},
    ]
    _mirror_guest_creates(fake)
    return fake


def create_e2e_app():
    from proxploy.config import Settings
    from proxploy.main import create_app
    from tests.fakes.pve import make_fake_factory
    from tests.fakes.ssh import FakeSSHConnection, make_fake_connect_factory

    data_dir = Path(os.environ["PROXPLOY_DATA_DIR"])

    settings = Settings(
        db_url=os.environ["PROXPLOY_DB_URL"],
        data_dir=data_dir,
        master_key_file=Path(os.environ["PROXPLOY_MASTER_KEY_FILE"]),
        # The poller has to actually run here, unlike the rest of this file's
        # PROXPLOY_* env (which leaves it off): Host.node_name, the VM-create
        # wizard's node/storage pickers and the Virtual Machines page are all
        # either populated by, or read straight out of, a poll cycle against
        # FakePVE (api/vms.py::_pick_node's own comment says as much): never
        # by host creation itself. A short interval keeps Task 16's journey
        # from waiting out a production 30 s cycle; there is no real Proxmox
        # host here to spare from being hammered.
        poll_enabled=True, poll_interval_s=1.0,
        scheduler_enabled=False, alerts_enabled=False,
    )

    _seed_catalog(settings)
    fake = _seed_pve()
    ssh = FakeSSHConnection(host_key_fingerprint="SHA256:e2e",
                            stdout_lines=["ok"], stderr_lines=[], exit_status=0)

    return create_app(settings,
                      proxmox_factory=make_fake_factory(fake),
                      ssh_factory=make_fake_connect_factory(ssh))
