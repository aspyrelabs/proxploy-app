"""The app lifecycle against a real Proxmox node: install, console, update,
uninstall.

Every bug this suite pins was invisible to the ~930 tests that pass without
hardware, because FakePVE and tests/fakes/ssh.py never run build.func:

- `MODE=default` was exported for five phases; build.func reads lowercase
  `${mode}` and nothing else, so the menu always appeared, whiptail read EOF
  from the DEVNULL stdin, and the script exited 0 having installed nothing;
- a non-PTY ssh session is TERM=dumb, where build.func's early `clear` exits 1
  and its error trap aborts the run;
- exit 0 was taken as proof of success, so a cancelled script filed an App row
  for a container that did not exist;
- `app.update` ran the catalog script over host SSH, and build.func's start()
  picks install-vs-update by WHERE it runs, so "update" built a SECOND
  container every time.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from tests import livepve
from tests.livepve import live_only

pytestmark = pytest.mark.pve_integration

SLUG = os.environ.get("PROXPLOY_TEST_PVE_APP_SLUG", "adguard")


def _ingest(app) -> str:
    from proxploy.models import CatalogEntry
    from proxploy.services.catalog import run_ingest

    with app.state.sessionmaker() as db:
        result = run_ingest(db, [SLUG])
        if result["failed"]:
            pytest.skip(f"catalog ingest failed (no GitHub access?): {result['failed']}")
        entry = db.query(CatalogEntry).filter_by(slug=SLUG).one()
        if not entry.installable:
            pytest.skip(f"{SLUG} is not installable: {entry.unsupported_reason}")
        return entry.upstream_sha


@live_only
def test_the_whole_app_lifecycle_on_real_hardware(tmp_path):
    """install -> console round trip -> update -> uninstall, on one container.

    Kept as a single test on purpose: each step needs the container the last
    one produced, and splitting it would mean installing an app four times.
    """
    from proxploy.jobs import HANDLERS
    from proxploy.models import App, AppScript

    app, host_id = livepve.live_app(tmp_path)
    ctid = livepve.assert_scratch(livepve.scratch_range()[1])
    _ingest(app)

    async def go():
        before = livepve.lxc_ids(app, host_id)
        assert ctid not in before, f"scratch id {ctid} is already in use on the node"
        try:
            out = await HANDLERS["app.install"](
                livepve.job_ctx(app, "app.install"),
                {"catalog_slug": SLUG, "host_id": host_id, "ctid": ctid,
                 "name": f"int-{SLUG}", "overrides": {}})
            app_id = out["app_id"]

            # The container really exists, read back over SSH rather than from
            # the API the installer just used.
            rc, listing = await livepve.ssh_run("pct list")
            assert rc == 0 and str(ctid) in listing, (
                f"install reported success but CT {ctid} is not on the node:\n{listing}")

            await _console_round_trip(app, host_id, ctid)

            # Roll the pin back so there is a real update to perform.
            with app.state.sessionmaker() as db:
                latest = (db.query(AppScript).filter_by(app_id=app_id)
                          .order_by(AppScript.version.desc()).first())
                latest.upstream_ref = "0" * 40
                db.get(App, app_id).update_available = "0000000"
                db.commit()

            mid = livepve.lxc_ids(app, host_id)
            await HANDLERS["app.update"](livepve.job_ctx(app, "app.update"),
                                         {"app_id": app_id})
            after = livepve.lxc_ids(app, host_id)
            assert after == mid, (
                f"update created container(s) {sorted(after - mid)} instead of "
                f"updating CT {ctid}: it ran on the host, not inside the guest")

            with app.state.sessionmaker() as db:
                versions = (db.query(AppScript).filter_by(app_id=app_id)
                            .order_by(AppScript.version).all())
            assert len(versions) >= 2, "update did not pin a new script version"

            await HANDLERS["app.uninstall"](livepve.job_ctx(app, "app.uninstall"),
                                            {"target_id": app_id})
            assert ctid not in livepve.lxc_ids(app, host_id)
            with app.state.sessionmaker() as db:
                assert db.get(App, app_id) is None, "uninstall left the app row behind"
        finally:
            if ctid in livepve.lxc_ids(app, host_id):
                await livepve.destroy_guest(app, host_id, "lxc", ctid)

    asyncio.run(go())


async def _console_round_trip(app, host_id, ctid: int) -> None:
    """A real root shell in the container, through the product's own bridge.

    Proves all four console fixes at once: the Authorization header on the
    upgrade, the percent-encoded vncticket, bytes frames decoded to text, and
    a handshake that actually reaches a PTY.
    """
    from proxploy.models import Host
    from proxploy.services.ptybridge import connect_upstream_pty

    client = livepve.client_for(app, host_id)
    with app.state.sessionmaker() as db:
        host = db.get(Host, host_id)
        address, verify_tls = host.address, host.verify_tls

    up = client.termproxy("lxc", livepve.node(), ctid)
    ws, buffered = await connect_upstream_pty(
        address=address, node=livepve.node(), guest_kind="lxc", vmid=ctid,
        upstream_user=up["user"], upstream_ticket=up["ticket"],
        upstream_port=str(up["port"]), verify_tls=verify_tls,
        tls_fingerprint=None, auth_header=client.pve_auth_header)
    try:
        marker = "proxploy-console-probe"
        payload = f"echo {marker}\n"
        await ws.send(f"0:{len(payload.encode())}:{payload}")
        seen = buffered
        for _ in range(25):
            frame = await asyncio.wait_for(ws.recv(), timeout=10)
            seen += (frame.decode("utf-8", "replace")
                     if isinstance(frame, (bytes, bytearray)) else frame)
            if seen.count(marker) >= 2:      # the typed line AND its output
                return
        raise AssertionError(f"no echo came back from the console: {seen[-200:]!r}")
    finally:
        await ws.close()


@live_only
def test_install_refuses_a_ctid_that_already_exists(tmp_path):
    """Installing onto a live container would let the catalog script
    reconfigure a guest Proxploy does not own, then file an App row claiming
    it. Uses a container this suite created, never a pre-existing one."""
    from proxploy.jobs import HANDLERS, JobFailed

    app, host_id = livepve.live_app(tmp_path)
    ctid = livepve.assert_scratch(livepve.scratch_range()[2])
    _ingest(app)

    async def go():
        tmpl_source = f"pct create {ctid} %s --hostname pxp-dupe-{ctid} " \
                      f"--rootfs {os.environ.get('PROXPLOY_TEST_PVE_STORAGE_ROOTFS', 'local-lvm')}:2 " \
                      f"--memory 512 --cores 1 --unprivileged 1"
        client = livepve.client_for(app, host_id)
        vols = client.storage_content(
            livepve.node(), os.environ.get("PROXPLOY_TEST_PVE_STORAGE_ISO", "local"),
            content="vztmpl")
        if not vols:
            pytest.skip("no CT template on the node")
        rc, out = await livepve.ssh_run(tmpl_source % vols[0]["volid"])
        assert rc == 0, out[-300:]
        try:
            with pytest.raises(JobFailed, match="already exists"):
                await HANDLERS["app.install"](
                    livepve.job_ctx(app, "app.install"),
                    {"catalog_slug": SLUG, "host_id": host_id, "ctid": ctid,
                     "name": "dupe", "overrides": {}})
        finally:
            await livepve.destroy_guest(app, host_id, "lxc", ctid)

    asyncio.run(go())
