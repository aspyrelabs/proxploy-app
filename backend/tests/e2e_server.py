"""Serve the REAL app to Playwright with fake PVE and SSH behind it.

This exists so the e2e suite can drive the actual onboarding wizard —
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
from pathlib import Path


def create_e2e_app():
    from proxploy.config import Settings
    from proxploy.main import create_app
    from tests.fakes.pve import FakePVE, make_fake_factory
    from tests.fakes.ssh import FakeSSHConnection, make_fake_connect_factory

    data_dir = Path(os.environ["PROXPLOY_DATA_DIR"])

    fake = FakePVE(version={"version": "8.4.1", "release": "8.4"})
    fake.add_ct(101, node="pve1", name="demo-ct", status="running")

    ssh = FakeSSHConnection(host_key_fingerprint="SHA256:e2e",
                            stdout_lines=["ok"], stderr_lines=[], exit_status=0)

    settings = Settings(
        db_url=os.environ["PROXPLOY_DB_URL"],
        data_dir=data_dir,
        master_key_file=Path(os.environ["PROXPLOY_MASTER_KEY_FILE"]),
        poll_enabled=False, scheduler_enabled=False, alerts_enabled=False,
    )
    return create_app(settings,
                      proxmox_factory=make_fake_factory(fake),
                      ssh_factory=make_fake_connect_factory(ssh))
