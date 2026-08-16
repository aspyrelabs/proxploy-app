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
import re
from datetime import datetime, timezone
from pathlib import Path

NODE = "pve1"
# journey.spec.ts adds its one host at exactly this address. Both the fake
# below and that spec have to agree on it now that the factory is keyed by
# address rather than answering with one fake for everything.
NODE_ADDRESS = "10.0.0.5"
ISO_STORAGE = "local"
IMAGES_STORAGE = "local-lvm"
DEMO_CATALOG_SLUG = "e2e-demo"

# The cluster peers.spec.ts drives, one node per address. Deliberately NOT at
# NODE's address: pve1 stays a standalone node, so journey.spec.ts keeps
# describing the simpler world and never meets a peer panel it knows nothing
# about. Same cluster name, node names and addresses as the unit tests in
# tests/test_hosts_peers.py, so there is one fake world here and not two.
CLUSTER = "lab-cluster"
CLUSTER_NODES = {"pve2": "10.0.0.6", "pve3": "10.0.0.7", "pve4": "10.0.0.8"}


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


def _mirror_ssh_installs(fake):
    """A community-scripts install creates the container with `pct` over root
    SSH, never through the PVE API; the node then reflects it in its very next
    /cluster/resources listing. That is precisely the causal link
    services/appstore.py::run_install relies on: it runs the script over SSH,
    then re-reads _lxc_ids() and refuses to file an App row if the CT is not
    there ("exit status 0 is NOT proof the container was built").

    FakeSSHConnection runs the script as a no-op, so without this the fake node
    never learns about the CT and that check correctly reports that nothing was
    installed. The check is right; the fake was lying by omission.

    Deliberately NOT routed through FakePVE's guest-create path the way
    _mirror_guest_creates does for VMs: no install ever calls it. Modelling it
    that way would be smaller and would make the test pass by simulating
    something the product does not do, which is how a fake that quietly does
    less than the real thing makes its own tests worthless.
    """
    def register_ct(command: str) -> None:
        # env reaches the remote as a shell-quoted `KEY=value` prefix on the
        # command string, not an SSH env request (executor/ssh.py::run's own
        # note). run_install sets var_ctid last so it always wins, and it is
        # the only caller that sets it, so this never fires for the ssh/verify
        # probe or any other remote command.
        m = re.search(r"\bvar_ctid=(\d+)", command)
        if m is None:
            return
        ctid = int(m.group(1))
        if any(r.get("type") == "lxc" and r.get("vmid") == ctid
               for r in fake.resources):
            return
        fake.add_ct(ctid, node=NODE, name=f"ct-{ctid}", status="running")

    return register_ct


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
    # Mirrors the two "storage" resource rows above into storages_by_node,
    # which is the ONLY list resolve_storage_pools reads (ProxmoxClient.storages
    # -> _NodeStorageFactory.get() -> storages_by_node, never the resources
    # list). Without this an app-store install correctly refuses: it can no
    # longer proceed against a host whose storage is unknown, and an unseeded
    # fake node is exactly such a host. This is the feature working as
    # designed, not a defect in the fake, so do not simplify this away; that
    # will silently break the app-store install step of journey.spec.ts.
    fake.storages_by_node[NODE] = [
        {"storage": ISO_STORAGE, "content": "iso,vztmpl,backup",
         "enabled": 1, "active": 1},
        {"storage": IMAGES_STORAGE, "content": "images,rootdir",
         "enabled": 1, "active": 1},
    ]
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


def _seed_cluster():
    """One FakePVE per node of CLUSTER, keyed by address.

    Each node answers /cluster/status with every node of the cluster and marks
    itself `local`, which is what a real node does and what cluster_identity
    reads to work out which node it is talking to. Without one fake per
    address, GET/POST /hosts/{id}/peers would reach the same machine whichever
    peer they were aimed at, and the panel could not be rendered at all.
    """
    from tests.fakes.pve import FakePVE

    fakes = {}
    for node, ip in CLUSTER_NODES.items():
        fake = FakePVE(resources=[
            {"type": "node", "node": node, "status": "online", "cpu": 0.04,
             "maxcpu": 4, "mem": 2147483648, "maxmem": 8589934592,
             "uptime": 100000}])
        fake.cluster_status_rows = [{"type": "cluster", "name": CLUSTER}] + [
            {"type": "node", "name": n, "ip": i, "online": 1,
             "local": 1 if n == node else 0} for n, i in CLUSTER_NODES.items()]
        fakes[ip] = fake
    return fakes


def create_e2e_app():
    from proxploy.config import Settings
    from proxploy.main import create_app
    from tests.fakes.pve import make_addressed_factory
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

    # There is no TLS listener behind the fake PVE, so the fingerprint
    # enrolment pins (api/hosts.py) and the one ProxmoxClient._connect checks
    # it against would each sit out a 10 second connect timeout on an address
    # nothing answers on. One stub for both, so the pin the wizard stores is
    # the certificate the fake node "presents" and every later call matches it.
    # It answers per address, never one constant: cluster nodes serve distinct
    # certificates, and a peer that appeared to present the origin's would
    # make the panel's fingerprint line a lie.
    import importlib

    def _e2e_fingerprint(host, port=8006):
        return f"E2:E0:{host}"

    # Every module that took its own reference to the helper at import time.
    for name in ("proxploy.api.hosts", "proxploy.services.proxmox",
                 "proxploy.services.consoleproxy", "proxploy.services.ptybridge"):
        importlib.import_module(name).tls_fingerprint_sha256 = _e2e_fingerprint

    _seed_catalog(settings)
    fake = _seed_pve()
    ssh = FakeSSHConnection(host_key_fingerprint="SHA256:e2e",
                            stdout_lines=["ok"], stderr_lines=[], exit_status=0,
                            on_create_process=_mirror_ssh_installs(fake))

    # An address with no fake behind it raises KeyError here, which
    # ProxmoxClient._connect already wraps into the same ProxmoxError a dead
    # node produces, so a typo'd address in a spec reads as "cannot connect"
    # rather than as a 500.
    return create_app(settings,
                      proxmox_factory=make_addressed_factory(
                          {NODE_ADDRESS: fake, **_seed_cluster()}),
                      ssh_factory=make_fake_connect_factory(ssh))
