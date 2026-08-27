"""Phase 6 against a real, disposable PVE (doc 11 §7 matrix).

This file was an unconditional `pytest.skip` for five phases. It is now the
real thing, and it found the bugs the fakes could not: ISO upload, vzdump to a
real PBS datastore, restore both ways, and prune.

What only a real host can prove, and what tests/fakes/pve.py deliberately does
not:

- that `/nodes/{node}/storage/{storage}/upload` accepts proxmoxer's multipart
  shape for a real multi-hundred-MB file rather than the few-byte payload the
  fake accepts, and that the UPID it returns actually completes;
- that a vzdump of a real CT to a real PBS datastore, and a restore of that
  archive, both succeed;
- that a restore naming no storage lands somewhere that can actually hold a
  rootfs (PVE's own default, `local`, cannot: that bug shipped);
- that prune honours its vmid filter and leaves every other guest alone.

`/nodes/{node}/network` PUT is deliberately NOT exercised here. See
test_network_apply_is_gated_behind_an_explicit_opt_in below.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from tests import livepve
from tests.livepve import live_only

pytestmark = pytest.mark.pve_integration

BACKUP_STORAGE = os.environ.get("PROXPLOY_TEST_PVE_STORAGE_BACKUP", "local")
ISO_STORAGE = os.environ.get("PROXPLOY_TEST_PVE_STORAGE_ISO", "local")
ROOTFS_STORAGE = os.environ.get("PROXPLOY_TEST_PVE_STORAGE_ROOTFS", "local-lvm")


def _template(app, host_id) -> str:
    """A CT template already on the node; skip rather than download one."""
    client = livepve.client_for(app, host_id)
    vols = client.storage_content(livepve.node(), ISO_STORAGE, content="vztmpl")
    if not vols:
        pytest.skip(f"no CT template on {ISO_STORAGE}; "
                    f"run `pveam download {ISO_STORAGE} <template>` first")
    return vols[0]["volid"]


async def _make_ct(app, host_id, ctid: int) -> None:
    """A minimal container to back up, built with pct over SSH rather than the
    catalog installer: this suite is about storage, not about apps."""
    livepve.assert_scratch(ctid)
    tmpl = _template(app, host_id)
    rc, out = await livepve.ssh_run(
        f"pct create {ctid} {tmpl} --hostname pxp-int-{ctid} "
        f"--rootfs {ROOTFS_STORAGE}:2 --memory 512 --cores 1 --unprivileged 1 "
        f"--net0 name=eth0,bridge=vmbr0,ip=dhcp && pct start {ctid}")
    assert rc == 0, f"could not create the fixture container: {out[-400:]}"


@live_only
def test_iso_upload_and_delete_round_trip(tmp_path):
    """A real multipart upload, then a real delete of what it wrote."""
    from proxploy.jobs import HANDLERS

    app, host_id = livepve.live_app(tmp_path)
    name = "proxploy-integration-test.iso"
    volid = f"{ISO_STORAGE}:iso/{name}"
    # 8 MiB: big enough to cross the 1 MiB spool loop several times, small
    # enough not to make the suite tedious.
    payload = tmp_path / "fixture.iso"
    payload.write_bytes(b"\0" * (8 * 1024 * 1024))

    async def go():
        out = await HANDLERS["storage.upload"](
            livepve.job_ctx(app, "storage.upload"),
            {"host_id": host_id, "storage": ISO_STORAGE, "content": "iso",
             "filename": name, "spool_path": str(payload),
             "size_bytes": payload.stat().st_size})
        assert out["exitstatus"] == "OK"

        client = livepve.client_for(app, host_id)
        listed = {v["volid"] for v in
                  client.storage_content(livepve.node(), ISO_STORAGE, content="iso")}
        assert volid in listed, f"upload reported OK but {volid} is not there"

        await HANDLERS["storage.delete_volume"](
            livepve.job_ctx(app, "storage.delete_volume"),
            {"host_id": host_id, "storage": ISO_STORAGE, "volid": volid})
        listed = {v["volid"] for v in
                  client.storage_content(livepve.node(), ISO_STORAGE, content="iso")}
        assert volid not in listed

    asyncio.run(go())


@live_only
def test_backup_sync_restore_and_prune_against_a_real_datastore(tmp_path):
    """The whole backup story in one pass, because each step needs the last.

    The prune assertion is the important one: it must remove only the archives
    of the guest it was given and leave every other guest's alone.
    """
    from proxploy.jobs import HANDLERS
    from proxploy.models import Backup

    app, host_id = livepve.live_app(tmp_path)
    ctid = livepve.assert_scratch(livepve.scratch_range()[0])
    restored_vmid = None

    async def go():
        nonlocal restored_vmid
        # A leftover from an earlier aborted run would otherwise surface as a
        # confusing `pct create` error deep in _make_ct.
        assert ctid not in livepve.lxc_ids(app, host_id), (
            f"scratch id {ctid} is already in use; a previous run left it "
            f"behind. Remove it (`pct destroy {ctid} --purge 1`) and re-run")
        await _make_ct(app, host_id, ctid)
        try:
            others_before = {k: v for k, v in
                             livepve.archive_census(app, host_id, BACKUP_STORAGE).items()
                             if k != ctid}

            # Three backups, so keep-last=1 has something to remove.
            for _ in range(3):
                out = await HANDLERS["backup.run"](
                    livepve.job_ctx(app, "backup.run"),
                    {"host_id": host_id, "vmids": [ctid], "storage": BACKUP_STORAGE})
                assert out["exitstatus"] in ("OK",) or out["exitstatus"].startswith("WARNINGS")

            synced = await HANDLERS["backup.sync"](
                livepve.job_ctx(app, "backup.sync"), {"host_id": host_id})
            assert synced["synced"] >= 3
            with app.state.sessionmaker() as db:
                mine = [b for b in db.query(Backup).all() if b.guest_vmid == ctid]
            assert len(mine) >= 3, "sync did not mirror our archives"
            newest = max(mine, key=lambda b: (b.taken_at or 0))

            # Restore as new, naming NO storage. PVE's own fallback is `local`,
            # a directory store that cannot hold a rootfs, so this used to fail
            # for every container on a stock layout.
            out = await HANDLERS["backup.restore"](
                livepve.job_ctx(app, "backup.restore"), {"backup_id": newest.id})
            restored_vmid = out["vmid"]
            assert out["mode"] == "new"
            assert restored_vmid in livepve.lxc_ids(app, host_id)

            # Restore in place over the (stopped) fixture.
            await HANDLERS["app.stop"](livepve.job_ctx(app, "app.stop"),
                                       {"target_id": _app_row(app, host_id, ctid)})
            out = await HANDLERS["backup.restore"](
                livepve.job_ctx(app, "backup.restore"),
                {"backup_id": newest.id, "mode": "in_place"})
            assert out["mode"] == "in_place" and out["vmid"] == ctid

            # Prune, scoped to OUR guest only.
            await HANDLERS["backup.prune"](
                livepve.job_ctx(app, "backup.prune"),
                {"host_id": host_id, "storage": BACKUP_STORAGE,
                 "spec": "keep-last=1", "vmid": ctid, "guest_type": "lxc"})

            after = livepve.archive_census(app, host_id, BACKUP_STORAGE)
            assert after[ctid] == 1, f"keep-last=1 left {after[ctid]} archives"
            others_after = {k: v for k, v in after.items() if k != ctid}
            assert others_after == others_before, (
                "prune escaped its vmid filter and touched other guests: "
                f"{others_before} -> {others_after}")
        finally:
            if restored_vmid:
                # cluster_nextid, not us: a restore-as-new can land outside the
                # operator's scratch range entirely.
                await livepve.destroy_guest(app, host_id, "lxc", restored_vmid,
                                            product_chose_the_id=True)
            await livepve.destroy_guest(app, host_id, "lxc", ctid)

    asyncio.run(go())


def _app_row(app, host_id, ctid: int) -> int:
    from proxploy.models import App

    with app.state.sessionmaker() as db:
        row = db.query(App).filter_by(host_id=host_id, ctid=ctid).one_or_none()
        if row is None:
            row = App(host_id=host_id, ctid=ctid, name=f"int-{ctid}",
                      slug=f"int-{host_id}-{ctid}", adopted=True,
                      status_cached="running")
            db.add(row); db.commit()
        return row.id


@live_only
def test_network_apply_is_gated_behind_an_explicit_opt_in():
    """`/nodes/{node}/network` PUT is the highest-risk call in the product: a
    wrong bridge write cuts the node off with no in-band undo. It runs only
    when the operator has confirmed out-of-band access (IPMI or a physical
    console) by setting PROXPLOY_TEST_PVE_ALLOW_NETWORK_APPLY=1.

    This test exists so the gate is visible in the run rather than the suite
    quietly appearing complete without it."""
    if os.environ.get("PROXPLOY_TEST_PVE_ALLOW_NETWORK_APPLY") != "1":
        pytest.skip("network apply NOT run: set "
                    "PROXPLOY_TEST_PVE_ALLOW_NETWORK_APPLY=1 only with "
                    "out-of-band access to the node")
    pytest.skip("opt-in acknowledged; the apply scenario itself is still "
                "supervised-only and deliberately not automated")
