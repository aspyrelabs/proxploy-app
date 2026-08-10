"""The VM side against a real Proxmox node: create, start, VNC, snapshot,
clone, delete, plus the lifecycle edge cases.

Everything here had only ever run against FakePVE. The VNC console in
particular shares `connect_upstream_vnc` with the CT console path, and carried
the same two fatal defects (no Authorization header on the upgrade, unquoted
vncticket) until a real node rejected them.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from tests import livepve
from tests.livepve import live_only

pytestmark = pytest.mark.pve_integration

ROOTFS_STORAGE = os.environ.get("PROXPLOY_TEST_PVE_STORAGE_ROOTFS", "local-lvm")


def _vm_row(app, host_id, vmid: int, name: str) -> int:
    from proxploy.models import Vm

    with app.state.sessionmaker() as db:
        v = Vm(host_id=host_id, vmid=vmid, name=name, status="stopped")
        db.add(v); db.commit()
        return v.id


@live_only
def test_vm_create_start_console_snapshot_clone_delete(tmp_path):
    """One VM carried through every qemu-side handler.

    A 1 GiB disk with no ISO: it boots to the BIOS and sits there, which is all
    the VNC probe needs and keeps the suite quick.
    """
    from proxploy.jobs import HANDLERS

    app, host_id = livepve.live_app(tmp_path)
    scratch = livepve.scratch_range()
    vmid = livepve.assert_scratch(scratch[3])
    clone_id = livepve.assert_scratch(scratch[4])

    async def go():
        assert vmid not in livepve.lxc_ids(app, host_id)
        try:
            out = await HANDLERS["vm.create"](
                livepve.job_ctx(app, "vm.create"),
                {"host_id": host_id, "vmid": vmid, "name": f"pxp-int-{vmid}",
                 "cores": 1, "memory_mb": 512, "disk_gb": 1,
                 "storage": ROOTFS_STORAGE, "bridge": "vmbr0"})
            assert out["vmid"] == vmid

            row = _vm_row(app, host_id, vmid, f"pxp-int-{vmid}")
            await HANDLERS["vm.start"](livepve.job_ctx(app, "vm.start"),
                                       {"target_id": row})
            await asyncio.sleep(3)
            await _vnc_banner(app, host_id, vmid)

            await HANDLERS["vm.snapshot_create"](
                livepve.job_ctx(app, "vm.snapshot_create"),
                {"vm_id": row, "name": "pxp-int-snap", "description": "integration",
                 "vmstate": False})
            await HANDLERS["vm.snapshot_delete"](
                livepve.job_ctx(app, "vm.snapshot_delete"),
                {"vm_id": row, "name": "pxp-int-snap"})

            await HANDLERS["vm.stop"](livepve.job_ctx(app, "vm.stop"),
                                      {"target_id": row})
            await asyncio.sleep(2)

            # A FULL clone: PVE refuses a linked clone from a non-template
            # source on lvmthin, which is its policy, not our bug.
            out = await HANDLERS["vm.clone"](
                livepve.job_ctx(app, "vm.clone"),
                {"vm_id": row, "newid": clone_id, "full": True,
                 "name": f"pxp-int-clone-{clone_id}"})
            assert out["newid"] == clone_id

            rc, listing = await livepve.ssh_run("qm list")
            assert rc == 0 and str(clone_id) in listing, listing

            clone_row = _vm_row(app, host_id, clone_id, f"pxp-int-clone-{clone_id}")
            await HANDLERS["vm.delete"](livepve.job_ctx(app, "vm.delete"),
                                        {"vm_id": clone_row})
            await HANDLERS["vm.delete"](livepve.job_ctx(app, "vm.delete"),
                                        {"vm_id": row})
            rc, listing = await livepve.ssh_run("qm list")
            assert str(vmid) not in listing and str(clone_id) not in listing
        finally:
            for leftover in (clone_id, vmid):
                await livepve.destroy_guest(app, host_id, "qemu", leftover)

    asyncio.run(go())


async def _vnc_banner(app, host_id, vmid: int) -> None:
    """A real VNC server opens with an RFB version banner. Getting it proves
    the websocket UPGRADE was authenticated and the ticket survived encoding,
    which is exactly what failed against real Proxmox."""
    from proxploy.models import Host
    from proxploy.services.consoleproxy import connect_upstream_vnc

    client = livepve.client_for(app, host_id)
    with app.state.sessionmaker() as db:
        host = db.get(Host, host_id)
        address, verify_tls = host.address, host.verify_tls

    up = client.vncproxy(livepve.node(), vmid)
    ws = await connect_upstream_vnc(
        address=address, node=livepve.node(), vmid=vmid,
        upstream_ticket=up["ticket"], upstream_port=str(up["port"]),
        verify_tls=verify_tls, tls_fingerprint=None,
        auth_header=client.pve_auth_header)
    try:
        await ws.send(f"{up['user']}:{up['ticket']}\n")
        first = await asyncio.wait_for(ws.recv(), timeout=10)
        raw = first if isinstance(first, (bytes, bytearray)) else first.encode()
        assert b"RFB" in raw, f"no RFB banner, got {raw[:40]!r}"
    finally:
        await ws.close()


@live_only
def test_stopping_an_already_stopped_container_is_a_no_op(tmp_path):
    """PVE answers a redundant stop with a 500 "CT <id> not running", which
    used to surface as a failed job for something that was already true."""
    from proxploy.jobs import HANDLERS
    from proxploy.models import App

    app, host_id = livepve.live_app(tmp_path)
    ctid = livepve.assert_scratch(livepve.scratch_range()[5])

    async def go():
        client = livepve.client_for(app, host_id)
        vols = client.storage_content(
            livepve.node(), os.environ.get("PROXPLOY_TEST_PVE_STORAGE_ISO", "local"),
            content="vztmpl")
        if not vols:
            pytest.skip("no CT template on the node")
        rc, out = await livepve.ssh_run(
            f"pct create {ctid} {vols[0]['volid']} --hostname pxp-stop-{ctid} "
            f"--rootfs {ROOTFS_STORAGE}:2 --memory 512 --cores 1 --unprivileged 1")
        assert rc == 0, out[-300:]
        try:
            with app.state.sessionmaker() as db:
                row = App(host_id=host_id, ctid=ctid, name=f"stop-{ctid}",
                          slug=f"stop-{host_id}-{ctid}", adopted=True,
                          status_cached="stopped")
                db.add(row); db.commit()
                app_row = row.id

            out = await HANDLERS["app.stop"](livepve.job_ctx(app, "app.stop"),
                                             {"target_id": app_row})
            assert out["noop"] == "already stopped", out
        finally:
            await livepve.destroy_guest(app, host_id, "lxc", ctid)

    asyncio.run(go())
