# backend/tests/test_migrate_transfer.py
"""The vzdump + SFTP transfer path (Phase 8 Task 16): `executor/transfer.py`
plus the `STRATEGY_TRANSFER` branch of `services/migrate.py::migrate_app`,
for two hosts that share neither a PVE cluster nor a backup storage.

FAKES vs HARDWARE — read this before trusting a green run: there is no live
Proxmox host and no real SSH target in this repo, ever. Every assertion here
is proven against `tests/fakes/pve.py::FakePVE` (a hand-maintained mimic of
the proxmoxer attribute surface) and `tests/fakes/ssh.py::FakeSSHConnection`/
`FakeSFTP` (an in-memory `{path: bytes}` store standing in for two real
filesystems, driven through the REAL `executor/transfer.py::sftp_copy`/
`sftp_copy_for_hosts` and the REAL `services/migrate.py` handler code). What
that proves: the handler's call sequence (vzdump -> locate archive -> SFTP
copy -> restore from the target-local copy -> start -> health check ->
repoint), the SFTP chunk/progress mechanics, the honesty properties (measured
downtime, source never destroyed, transfer scratch files cleaned up on both
hosts on both success and failure), and the JobFailed/rollback messaging —
all GIVEN the PVE API shapes FakePVE encodes and the SFTP semantics FakeSFTP
encodes. What it does NOT prove: that a real PVE dir storage's `dump/`
layout, a real OpenSSH sshd, or a real asyncssh SFTP session over an actual
network behaves this way end-to-end on real disks — that needs live
hardware.
"""
import asyncio
import json

import pytest

from proxploy.executor import transfer as transfer_mod
from proxploy.executor.transfer import sftp_copy
from proxploy.jobs import HANDLERS, JobBackend, JobContext, JobFailed
from proxploy.models import App, Host, HostCredential, Job, JobEvent
from proxploy.services import migrate as migrate_mod  # registers migrate.app
from tests.fakes.pve import FakePVE, make_addressed_factory
from tests.fakes.ssh import FakeSSHConnection, make_addressed_connect_factory
from tests.support import make_job_app

SRC_ADDR = "https://10.0.0.101:8006"
TGT_ADDR = "https://10.0.0.102:8006"
SRC_HOSTNAME = "10.0.0.101"
TGT_HOSTNAME = "10.0.0.102"

FAKE_KEY = b"-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----"


# --- executor/transfer.py::sftp_copy — unit -----------------------------------

def test_sftp_copy_streams_bytes_and_reports_progress(monkeypatch):
    """4 MiB chunking forced down to 4 bytes so one 12-byte payload exercises
    three chunks — bytes land intact at the destination path, on_progress
    fires once per chunk with a running total, and the return value is the
    total byte count."""
    monkeypatch.setattr(transfer_mod, "CHUNK_SIZE", 4)

    async def go():
        store: dict[str, bytes] = {"/src/archive.bin": b"hello world!"}
        fake_src = FakeSSHConnection(host_key_fingerprint="SHA256:src", stdout_lines=[],
                                     stderr_lines=[], exit_status=0, sftp_store=store)
        fake_dst = FakeSSHConnection(host_key_fingerprint="SHA256:dst", stdout_lines=[],
                                     stderr_lines=[], exit_status=0, sftp_store=store)
        factory = make_addressed_connect_factory({"src-host": fake_src, "dst-host": fake_dst})
        progress: list[int] = []

        total = await sftp_copy(
            factory,
            src={"host": "src-host", "private_key_pem": b"k", "pinned_fingerprint": None,
                "on_new_fingerprint": lambda fp: None},
            dst={"host": "dst-host", "private_key_pem": b"k", "pinned_fingerprint": None,
                "on_new_fingerprint": lambda fp: None},
            src_path="/src/archive.bin", dst_path="/dst/archive.bin",
            on_progress=progress.append)

        assert total == 12
        assert store["/dst/archive.bin"] == b"hello world!"
        assert progress == [4, 8, 12]

    asyncio.run(go())


def test_sftp_copy_missing_source_file_raises():
    async def go():
        store: dict[str, bytes] = {}
        fake_src = FakeSSHConnection(host_key_fingerprint="SHA256:src", stdout_lines=[],
                                     stderr_lines=[], exit_status=0, sftp_store=store)
        fake_dst = FakeSSHConnection(host_key_fingerprint="SHA256:dst", stdout_lines=[],
                                     stderr_lines=[], exit_status=0, sftp_store=store)
        factory = make_addressed_connect_factory({"src-host": fake_src, "dst-host": fake_dst})

        with pytest.raises(FileNotFoundError):
            await sftp_copy(
                factory,
                src={"host": "src-host", "private_key_pem": b"k", "pinned_fingerprint": None,
                    "on_new_fingerprint": lambda fp: None},
                dst={"host": "dst-host", "private_key_pem": b"k", "pinned_fingerprint": None,
                    "on_new_fingerprint": lambda fp: None},
                src_path="/nope", dst_path="/dst/archive.bin", on_progress=lambda n: None)

    asyncio.run(go())


# --- migrate.app handler: transfer strategy end-to-end ------------------------

def _two_host_app(tmp_path, pve_fakes: dict, ssh_fakes: dict):
    app = make_job_app(tmp_path)
    app.state.proxmox_factory = make_addressed_factory(pve_fakes)
    app.state.ssh_connect_factory = make_addressed_connect_factory(ssh_fakes)
    app.state.jobs = JobBackend(app)
    return app


def _seed(app, *, src_node="pve-src", tgt_node="pve-tgt", ctid=150):
    with app.state.sessionmaker() as db:
        src = Host(name="host-src", address=SRC_ADDR, node_name=src_node,
                  status="connected", pve_version="8.4.1")
        tgt = Host(name="host-tgt", address=TGT_ADDR, node_name=tgt_node,
                  status="connected", pve_version="8.4.1")
        db.add(src); db.add(tgt); db.commit()
        for h, tag in ((src, "src"), (tgt, "tgt")):
            ablob, aver = app.state.secretstore.encrypt(json.dumps(
                {"token_id": f"proxploy@pve!{tag}", "token_secret": "s3cret"}).encode())
            db.add(HostCredential(host_id=h.id, kind="api_token", encrypted_blob=ablob,
                                  key_version=aver, public_meta=f"proxploy@pve!{tag}"))
            sblob, sver = app.state.secretstore.encrypt(FAKE_KEY)
            db.add(HostCredential(host_id=h.id, kind="ssh_key", encrypted_blob=sblob,
                                  key_version=sver, public_meta="ssh-ed25519 AAAA fake"))
        a = App(host_id=src.id, ctid=ctid, name="immich", slug="immich",
               web_protocol="http", web_path="/")
        db.add(a)
        db.commit()
        return src.id, tgt.id, a.id


def _job(app, app_id, target_host_id):
    with app.state.sessionmaker() as db:
        j = Job(kind="migrate.app", status="running", target_type="app",
               target_id=app_id, params={"app_id": app_id,
                                         "target_host_id": target_host_id})
        db.add(j)
        db.commit()
        return j.id


def _events(app, job_id) -> list[str]:
    with app.state.sessionmaker() as db:
        rows = (db.query(JobEvent).filter_by(job_id=job_id)
               .order_by(JobEvent.seq).all())
        return [e.message for e in rows]


def _app_row(app, app_id):
    with app.state.sessionmaker() as db:
        a = db.get(App, app_id)
        return a.host_id, a.ctid


FILENAME = "vzdump-lxc-150-2026_08_05-00_00_00.tar.zst"
SRC_VOLID = f"local-src:backup/{FILENAME}"
DST_VOLID = f"local-tgt:backup/{FILENAME}"
PAYLOAD = b"pretend-vzdump-archive-bytes" * 1000


def _no_shared_storage_pair():
    """Two standalone hosts, each with its own dir-type backup storage at a
    DIFFERENT filesystem path — the no-cluster, no-shared-storage setup that
    forces `preflight()` to pick STRATEGY_TRANSFER."""
    a, b = FakePVE(), FakePVE()
    a.cluster_storage_rows = [{"storage": "local-src", "type": "dir",
                              "content": "backup,iso", "path": "/mnt/src"}]
    b.cluster_storage_rows = [{"storage": "local-tgt", "type": "dir",
                              "content": "backup,iso", "path": "/mnt/tgt"}]
    return a, b


def test_transfer_strategy_copies_archive_restores_on_target_and_cleans_up(tmp_path):
    async def go():
        fake_src, fake_tgt = _no_shared_storage_pair()
        fake_src.add_ct(150, node="pve-src", name="immich", status="running")
        fake_src.content_by_storage["local-src"] = [{
            "volid": SRC_VOLID, "content": "backup", "ctime": 1785000000,
            "size": len(PAYLOAD)}]
        fake_tgt.nextid = "500"
        fake_tgt.add_ct(500, node="pve-tgt", name="immich", status="running")

        store: dict[str, bytes] = {"/mnt/src/dump/" + FILENAME: PAYLOAD}
        ssh_src = FakeSSHConnection(host_key_fingerprint="SHA256:src", stdout_lines=[],
                                    stderr_lines=[], exit_status=0, sftp_store=store)
        ssh_tgt = FakeSSHConnection(host_key_fingerprint="SHA256:tgt", stdout_lines=[],
                                    stderr_lines=[], exit_status=0, sftp_store=store)

        app = _two_host_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt},
                            {SRC_ADDR: ssh_src, TGT_ADDR: ssh_tgt})
        src_id, tgt_id, app_id = _seed(app)
        job_id = _job(app, app_id, tgt_id)
        ctx = JobContext(app.state.jobs, job_id)

        out = await HANDLERS["migrate.app"](ctx, {"app_id": app_id,
                                                   "target_host_id": tgt_id})

        assert out["strategy"] == "transfer"
        assert out["source_ctid"] == 150
        assert out["target_ctid"] == 500
        assert out["volid"] == DST_VOLID          # restored from the TARGET-local copy
        assert out["downtime_s"] > 0              # MEASURED

        # the archive actually landed on the target, byte for byte
        assert store["/mnt/tgt/dump/" + FILENAME] == PAYLOAD

        # vzdump ran on the source into its own local storage (not shared)
        assert len(fake_src.vzdumps) == 1
        node, params = fake_src.vzdumps[0]
        assert node == "pve-src"
        assert params["storage"] == "local-src"
        assert params["mode"] == "stop"

        # restore ran on the target FROM the target-local volid
        assert len(fake_tgt.creates) == 1
        _, tgt_node, restore_params = fake_tgt.creates[0]
        assert tgt_node == "pve-tgt"
        assert restore_params["vmid"] == 500
        assert restore_params["restore"] == 1
        assert restore_params["ostemplate"] == DST_VOLID

        # source stopped, never destroyed; target started
        assert ("lxc", 150, "stop") in fake_src.actions
        assert fake_src.guest_deletes == fake_tgt.guest_deletes == []
        assert ("lxc", 500, "start") in fake_tgt.actions

        # both scratch archives cleaned up on success — no orphaned dump files
        assert ("pve-src", "local-src", SRC_VOLID) in fake_src.deleted_volumes
        assert ("pve-tgt", "local-tgt", DST_VOLID) in fake_tgt.deleted_volumes

        # identity repointed only after everything above succeeded
        host_id, ctid = _app_row(app, app_id)
        assert host_id == tgt_id
        assert ctid == 500

    asyncio.run(go())


def test_transfer_strategy_missing_dir_storage_on_target_fails_naming_the_side(tmp_path):
    async def go():
        fake_src, fake_tgt = FakePVE(), FakePVE()
        fake_src.cluster_storage_rows = [{"storage": "local-src", "type": "dir",
                                          "content": "backup,iso", "path": "/mnt/src"}]
        # target has no dir-type backup storage at all
        fake_src.add_ct(150, node="pve-src", name="immich", status="running")

        app = _two_host_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt}, {})
        src_id, tgt_id, app_id = _seed(app)
        job_id = _job(app, app_id, tgt_id)
        ctx = JobContext(app.state.jobs, job_id)

        with pytest.raises(JobFailed) as e:
            await HANDLERS["migrate.app"](ctx, {"app_id": app_id,
                                                "target_host_id": tgt_id})
        assert "host-tgt" in str(e.value)
        assert ("lxc", 150, "stop") not in fake_src.actions   # nothing touched

        host_id, ctid = _app_row(app, app_id)
        assert (host_id, ctid) == (src_id, 150)

    asyncio.run(go())


def test_transfer_strategy_ssh_host_key_mismatch_fails_and_cleans_up_source_archive(tmp_path):
    """The target's SSH host key has changed since it was pinned — the
    hard-fail-never-auto-accept rule (doc 08 §4) surfaces as JobFailed, the
    already-created source vzdump archive is deleted rather than orphaned,
    and nothing is touched on the target."""
    async def go():
        fake_src, fake_tgt = _no_shared_storage_pair()
        fake_src.add_ct(150, node="pve-src", name="immich", status="running")
        fake_src.content_by_storage["local-src"] = [{
            "volid": SRC_VOLID, "content": "backup", "ctime": 1785000000,
            "size": len(PAYLOAD)}]
        fake_tgt.nextid = "500"

        store: dict[str, bytes] = {"/mnt/src/dump/" + FILENAME: PAYLOAD}
        ssh_src = FakeSSHConnection(host_key_fingerprint="SHA256:src", stdout_lines=[],
                                    stderr_lines=[], exit_status=0, sftp_store=store)
        # the fake's *current* fingerprint no longer matches what's pinned below
        ssh_tgt = FakeSSHConnection(host_key_fingerprint="SHA256:tgt-rotated",
                                    stdout_lines=[], stderr_lines=[], exit_status=0,
                                    sftp_store=store)

        app = _two_host_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt},
                            {SRC_ADDR: ssh_src, TGT_ADDR: ssh_tgt})
        src_id, tgt_id, app_id = _seed(app)
        with app.state.sessionmaker() as db:
            db.get(Host, tgt_id).ssh_host_key_fingerprint = "SHA256:tgt-original"
            db.commit()
        job_id = _job(app, app_id, tgt_id)
        ctx = JobContext(app.state.jobs, job_id)

        with pytest.raises(JobFailed) as e:
            await HANDLERS["migrate.app"](ctx, {"app_id": app_id,
                                                "target_host_id": tgt_id})
        assert "host key changed" in str(e.value)
        assert "intact" in str(e.value)

        # source archive was created (vzdump ran) then cleaned back up
        assert len(fake_src.vzdumps) == 1
        assert ("pve-src", "local-src", SRC_VOLID) in fake_src.deleted_volumes

        # nothing ever reached the target
        assert fake_tgt.creates == []
        assert not any(a == "start" for _, _, a in fake_tgt.actions)

        host_id, ctid = _app_row(app, app_id)
        assert (host_id, ctid) == (src_id, 150)

        transcript = " ".join(_events(app, job_id)).lower()
        assert "intact" in transcript

    asyncio.run(go())
