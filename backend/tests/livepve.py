"""Shared harness for the `pve_integration` suites: a real app wired to a real
Proxmox node.

Every test that imports this skips cleanly when `PROXPLOY_TEST_PVE_*` is
absent, which is the whole reason CI stays green without hardware. Fill in
`proxploy-app/pve-testing.env` (gitignored) and run:

    set -a; . ./pve-testing.env; set +a
    cd backend && python -m pytest tests/ -q -m pve_integration

SAFETY, non-negotiable and learned the hard way on 2026-08-10: a host that
looks idle can hold real data. The PBS datastore used for these tests held 121
archives belonging to six other guests. So:

- guests are created and destroyed ONLY inside the scratch CTID/VMID range;
- prune is always given a `vmid` filter, and the tests assert every other
  guest's archive count is unchanged;
- the network-apply suite refuses to run unless
  PROXPLOY_TEST_PVE_ALLOW_NETWORK_APPLY=1, because a wrong bridge write cuts
  the node off with no in-band undo.
"""
from __future__ import annotations

import asyncio
import collections
import json
import os
import types

import pytest

REQUIRED = ("PROXPLOY_TEST_PVE_URL", "PROXPLOY_TEST_PVE_TOKEN_ID",
            "PROXPLOY_TEST_PVE_TOKEN_SECRET", "PROXPLOY_TEST_PVE_NODE")

live_only = pytest.mark.skipif(
    not all(os.environ.get(k) for k in REQUIRED),
    reason="needs a disposable live PVE (PROXPLOY_TEST_PVE_*)")


def env(name: str, default=None):
    return os.environ.get(name, default)


def node() -> str:
    return os.environ["PROXPLOY_TEST_PVE_NODE"]


def scratch_range() -> range:
    lo = int(env("PROXPLOY_TEST_PVE_SCRATCH_CTID_MIN", "9000"))
    hi = int(env("PROXPLOY_TEST_PVE_SCRATCH_CTID_MAX", "9010"))
    return range(lo, hi + 1)


def guest_vmid(kind: str) -> int | None:
    raw = env(f"PROXPLOY_TEST_PVE_{kind.upper()}_VMID")
    return int(raw) if raw else None


def node_or_none() -> str | None:
    return env("PROXPLOY_TEST_PVE_NODE")


def guests_required(*vmids) -> pytest.MarkDecorator:
    return pytest.mark.skipif(
        not all(vmids),
        reason="needs PROXPLOY_TEST_PVE_LXC_VMID and PROXPLOY_TEST_PVE_QEMU_VMID: "
               "existing guests on the test node this suite may attach firewall "
               "rules to")


def foreign_guest() -> tuple[int, str] | None:
    vmid, node_name = (env("PROXPLOY_TEST_PVE_FOREIGN_VMID"),
                       env("PROXPLOY_TEST_PVE_FOREIGN_NODE"))
    return (int(vmid), node_name) if vmid and node_name else None


cluster_only = pytest.mark.skipif(
    foreign_guest() is None,
    reason="needs a second node in the same cluster: set "
           "PROXPLOY_TEST_PVE_FOREIGN_VMID and PROXPLOY_TEST_PVE_FOREIGN_NODE")


def assert_scratch(vmid: int) -> int:
    """Guard every destructive call site. A test that reaches outside the
    operator's declared scratch range is a bug in the test, not a finding."""
    if vmid not in scratch_range():
        raise AssertionError(
            f"{vmid} is outside the scratch range {scratch_range()}; refusing "
            f"to create or destroy it")
    return vmid


# --- the executor keypair -----------------------------------------------------

_KEY: tuple[bytes, str] | None = None


def executor_key() -> bytes:
    """The private half of a keypair this harness owns, with its public half
    installed on the node.

    Generated with the product's own `sshkeys.generate_ed25519` and installed
    once per session using PROXPLOY_TEST_PVE_SSH_PASSWORD, so a fresh checkout
    needs nothing on disk beyond the env file. Idempotent: `grep -qxF` first.
    """
    global _KEY
    if _KEY is not None:
        return _KEY[0]

    from proxploy.services.sshkeys import generate_ed25519

    priv, pub = generate_ed25519("proxploy-pve-integration")
    password = env("PROXPLOY_TEST_PVE_SSH_PASSWORD")
    key_file = env("PROXPLOY_TEST_PVE_SSH_KEY_FILE")
    if key_file:
        # An operator-provided key wins; nothing to install.
        _KEY = (open(key_file, "rb").read(), "")
        return _KEY[0]
    if not password:
        pytest.skip("needs PROXPLOY_TEST_PVE_SSH_PASSWORD or "
                    "PROXPLOY_TEST_PVE_SSH_KEY_FILE to reach the node over SSH")

    import asyncssh

    line = pub.strip()

    async def install():
        async with asyncssh.connect(
                env("PROXPLOY_TEST_PVE_SSH_HOST") or _host_of(os.environ["PROXPLOY_TEST_PVE_URL"]),
                port=int(env("PROXPLOY_TEST_PVE_SSH_PORT", "22")),
                username=env("PROXPLOY_TEST_PVE_SSH_USER", "root"),
                password=password, known_hosts=None) as c:
            await c.run(
                "mkdir -p /root/.ssh && chmod 700 /root/.ssh && "
                f"(grep -qxF {_q(line)} /root/.ssh/authorized_keys 2>/dev/null || "
                f"echo {_q(line)} >> /root/.ssh/authorized_keys) && "
                "chmod 600 /root/.ssh/authorized_keys", check=True)

    asyncio.run(install())
    _KEY = (priv, pub)
    return priv


def _q(s: str) -> str:
    import shlex
    return shlex.quote(s)


def _host_of(url: str) -> str:
    from urllib.parse import urlparse
    return urlparse(url).hostname or url


async def ssh_run(command: str) -> tuple[int, str]:
    """Read the node's own truth over SSH, deliberately NOT through the API
    client the code under test uses."""
    import asyncssh

    password = env("PROXPLOY_TEST_PVE_SSH_PASSWORD")
    host = env("PROXPLOY_TEST_PVE_SSH_HOST") or _host_of(os.environ["PROXPLOY_TEST_PVE_URL"])
    kwargs = {"username": env("PROXPLOY_TEST_PVE_SSH_USER", "root"), "known_hosts": None}
    if password:
        kwargs["password"] = password
    else:
        kwargs["client_keys"] = [asyncssh.import_private_key(executor_key())]
    async with asyncssh.connect(host, port=int(env("PROXPLOY_TEST_PVE_SSH_PORT", "22")),
                                **kwargs) as c:
        r = await c.run(command, check=False)
        return r.exit_status, (r.stdout or "") + (r.stderr or "")


# --- the app ------------------------------------------------------------------

def live_app(tmp_path, *, poll=False):
    """(app, host_id) for a real app pointed at the real node.

    The TestClient context is entered and left open on purpose: the lifespan is
    what populates `app.state`, and these suites drive handlers directly.
    """
    from fastapi.testclient import TestClient

    from proxploy.config import Settings
    from proxploy.models import Host, HostCredential

    s = Settings(db_url=f"sqlite:///{tmp_path}/live.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key", poll_enabled=poll)
    from proxploy.main import create_app

    app = create_app(s)
    TestClient(app).__enter__()

    with app.state.sessionmaker() as db:
        host = Host(name="live-pve", address=os.environ["PROXPLOY_TEST_PVE_URL"],
                    node_name=node(), status="connected",
                    verify_tls=env("PROXPLOY_TEST_PVE_VERIFY", "0") == "1")
        db.add(host); db.commit()
        host_id = host.id
        tok = json.dumps({"token_id": os.environ["PROXPLOY_TEST_PVE_TOKEN_ID"],
                          "token_secret": os.environ["PROXPLOY_TEST_PVE_TOKEN_SECRET"]}).encode()
        blob, ver = app.state.secretstore.encrypt(tok)
        # Live-hardware harness: one real token, valid for every capability
        # (see test_console_pve_integration.py's identical note).
        for cap in ("monitoring", "lifecycle", "console", "backup"):
            db.add(HostCredential(host_id=host_id, kind=f"api_token:{cap}",
                                  encrypted_blob=blob, key_version=ver))
        kb, kv = app.state.secretstore.encrypt(executor_key())
        db.add(HostCredential(host_id=host_id, kind="ssh_key",
                              encrypted_blob=kb, key_version=kv))
        db.commit()
    return app, host_id


def job_ctx(app, kind: str):
    """A real JobContext: ctx.log writes job_events rows with a real FK, and
    run_update reads ctx.job_id, so a SimpleNamespace will not do."""
    from proxploy.jobs import JobBackend, JobContext
    from proxploy.models import Job

    if getattr(app.state, "jobs", None) is None:
        app.state.jobs = JobBackend(app)
    with app.state.sessionmaker() as db:
        j = Job(kind=kind, status="running"); db.add(j); db.commit()
        return JobContext(app.state.jobs, j.id)


def client_for(app, host_id):
    from proxploy.models import Host
    from proxploy.services.hostclient import client_for_host

    with app.state.sessionmaker() as db:
        return client_for_host(app, db, db.get(Host, host_id))


def lxc_ids(app, host_id) -> set[int]:
    from proxploy.services.appstore import _lxc_ids
    return _lxc_ids(app, host_id)


def archive_census(app, host_id, storage: str) -> collections.Counter:
    """Archives per guest on `storage`. The tests compare this before and after
    a prune so an escaped vmid filter fails loudly instead of destroying data."""
    client = client_for(app, host_id)
    return collections.Counter(
        v.get("vmid") for v in client.storage_content(node(), storage, content="backup"))


async def destroy_guest(app, host_id, kind: str, vmid: int, *,
                        product_chose_the_id: bool = False) -> None:
    """Best-effort cleanup, scratch range only.

    `product_chose_the_id` is the one exemption, and it is narrow: a
    restore-as-new takes its id from `/cluster/nextid`, so the product can and
    does land a guest outside whatever range the operator declared (seen on
    2026-08-10: nextid handed out 100 while the scratch range was 500-900). The
    test still has to clean up what it caused, so it may pass the id the
    product reported back to it, and nothing else.
    """
    from proxploy.services.pvetask import await_task

    if not product_chose_the_id:
        assert_scratch(vmid)
    client = client_for(app, host_id)
    try:
        upid = await asyncio.to_thread(client.guest_action, kind, node(), vmid, "stop")
        await await_task(job_ctx(app, "cleanup"), client, node(), upid, timeout_s=120)
    except Exception:            # already stopped, or never existed
        pass
    try:
        upid = await asyncio.to_thread(client.guest_delete, kind, node(), vmid)
        await await_task(job_ctx(app, "cleanup"), client, node(), upid, timeout_s=300)
    except Exception:
        pass
