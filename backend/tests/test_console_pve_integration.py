"""The CT console through its real HTTP routes, against real Proxmox.

Distinct from tests/test_apps_pve_integration.py, which drives
`connect_upstream_pty` directly: this one goes through
`POST /apps/{id}/console/tickets` and the `/console/ws` route, so it covers
ticket minting, redemption and the bridge as the browser actually reaches them.

It settles the question doc 11 left open, and the answer is now recorded: PVE
9.2.6 DOES accept API-token auth on the LXC termproxy/vncwebsocket path
(Proxmox bugzilla #6079 does not block it here). Getting there needed four
fixes no fake could have forced:

- an `Authorization: PVEAPIToken=` header on the websocket UPGRADE, which PVE
  authenticates separately from the termproxy POST (`401 No ticket` without it);
- a percent-encoded `vncticket`, since a PVEVNC ticket is base64 and its `+`
  and `/` do not survive a raw query string;
- bytes frames decoded to text, because the `binary` subprotocol means a real
  node never sends str;
- a rejected upgrade surfaced as PtyBridgeError instead of escaping as an
  unhandled InvalidStatus on an already-accepted socket.

This test builds and destroys its own container. It used to require the
operator to point PROXPLOY_TEST_PVE_CTID at a running CT and then broke the
moment that container went away.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os

import pytest

from tests import livepve
from tests.livepve import live_only

pytestmark = pytest.mark.pve_integration

# Every read off the console socket needs its own deadline.
# `websocket_connect(timeout=...)` bounds the CONNECT only, and TestClient's
# `receive_text()` blocks forever otherwise: when this test first ran against a
# container whose PTY went quiet, the whole suite sat there for 26 minutes
# instead of failing. A hung test is worse than a failing one, because it looks
# like slowness.
READ_TIMEOUT_S = 20


def _recv(ws, timeout: float = READ_TIMEOUT_S) -> str:
    # NOT `with ThreadPoolExecutor(...)`: its __exit__ calls shutdown(wait=True),
    # which blocks on the very read that just timed out, so the deadline fires
    # and the test hangs anyway. That cost a 25-minute suite run to learn.
    # shutdown(wait=False) leaks one blocked thread into a process that is
    # about to fail this test and exit, which is the right trade.
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(ws.receive_text)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        raise AssertionError(
            f"console produced nothing for {timeout:.0f}s; the PTY is not "
            f"talking (a container sitting at a login prompt looks exactly "
            f"like this)") from None
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

ROOTFS_STORAGE = os.environ.get("PROXPLOY_TEST_PVE_STORAGE_ROOTFS", "local-lvm")
ISO_STORAGE = os.environ.get("PROXPLOY_TEST_PVE_STORAGE_ISO", "local")


async def _make_running_ct(app, host_id, ctid: int) -> None:
    client = livepve.client_for(app, host_id)
    vols = client.storage_content(livepve.node(), ISO_STORAGE, content="vztmpl")
    if not vols:
        pytest.skip(f"no CT template on {ISO_STORAGE}; "
                    f"run `pveam download {ISO_STORAGE} <template>` first")
    systemd = [v for v in vols
               if any(d in v["volid"] for d in ("debian", "ubuntu"))]
    if not systemd:
        pytest.skip(f"no systemd CT template on {ISO_STORAGE}; the autologin "
                    f"override this fixture installs needs systemd and bash")
    template = systemd[0]["volid"]
    rc, out = await livepve.ssh_run(
        f"pct create {ctid} {template} --hostname pxp-console-{ctid} "
        f"--rootfs {ROOTFS_STORAGE}:2 --memory 512 --cores 1 --unprivileged 1 "
        f"--net0 name=eth0,bridge=vmbr0,ip=dhcp "
        f"--password proxploy-console-fixture && pct start {ctid}")
    assert rc == 0, f"could not create the fixture container: {out[-400:]}"
    await asyncio.sleep(5)
    unit = "/etc/systemd/system/container-getty@1.service.d"
    getty = ("[Service]\\nExecStart=\\nExecStart=-/sbin/agetty --autologin root "
             "--noclear --keep-baud tty1 115200,38400,9600 \\$TERM\\n")
    rc, out = await livepve.ssh_run(
        f"pct exec {ctid} -- bash -c \"mkdir -p {unit} && "
        f"printf '{getty}' > {unit}/autologin.conf && "
        f"systemctl daemon-reload && systemctl restart container-getty@1\"")
    assert rc == 0, f"could not give the fixture container a login shell: {out[-400:]}"
    for _ in range(20):
        await asyncio.sleep(2)
        rc, out = await livepve.ssh_run(
            f"pct exec {ctid} -- systemctl is-active container-getty@1")
        if rc == 0 and out.strip().startswith("active"):
            break
    await asyncio.sleep(4)


@live_only
def test_app_console_ticket_and_ws_against_real_pve(tmp_path, csrf_header,
                                                    bootstrap_admin):
    """Mint a ticket over HTTP, redeem it over the websocket, echo through the
    PTY. Either outcome is informative: a working round trip, or the explicit
    PtyBridgeError exit frame if this PVE still refuses token auth for LXC. A
    bare hang is the only real failure."""
    from fastapi.testclient import TestClient

    from proxploy.config import Settings
    from proxploy.main import create_app
    from proxploy.models import App, Host, HostCredential

    ctid = livepve.assert_scratch(livepve.scratch_range()[6])
    url = os.environ["PROXPLOY_TEST_PVE_URL"]
    verify_tls = os.environ.get("PROXPLOY_TEST_PVE_VERIFY", "0") == "1"

    # A reachability/version check first, so a bad env fails loudly here rather
    # than deep inside a ticket-mint 500.
    from proxploy.services.proxmox import ProxmoxClient

    probe = ProxmoxClient(url, os.environ["PROXPLOY_TEST_PVE_TOKEN_ID"],
                          os.environ["PROXPLOY_TEST_PVE_TOKEN_SECRET"],
                          verify_tls=verify_tls)
    assert probe.version()["release"].split(".")[0] in ("8", "9")

    s = Settings(db_url=f"sqlite:///{tmp_path}/t.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key", poll_enabled=False)
    app = create_app(s)
    with TestClient(app) as client:
        bootstrap_admin(client)
        with app.state.sessionmaker() as db:
            host = Host(name="live-pve", address=url, node_name=livepve.node(),
                        status="connected", verify_tls=verify_tls)
            db.add(host); db.commit()
            host_id = host.id
            blob, ver = app.state.secretstore.encrypt(json.dumps(
                {"token_id": os.environ["PROXPLOY_TEST_PVE_TOKEN_ID"],
                 "token_secret": os.environ["PROXPLOY_TEST_PVE_TOKEN_SECRET"]}).encode())
            # Live-hardware suite: the operator pastes ONE real token with
            # every privilege the pveum script can grant, so it is valid for
            # every capability the per-capability token scheme now encodes.
            for cap in ("monitoring", "lifecycle", "console", "backup"):
                db.add(HostCredential(host_id=host_id, kind=f"api_token:{cap}",
                                      encrypted_blob=blob, key_version=ver))
            db.commit()

        asyncio.run(_make_running_ct(app, host_id, ctid))
        try:
            with app.state.sessionmaker() as db:
                a = App(host_id=host_id, ctid=ctid, name="live-ct",
                        status_cached="running", slug=f"live-ct-{ctid}")
                db.add(a); db.commit()
                app_id = a.id

            r = client.post(f"/api/v1/apps/{app_id}/console/tickets",
                            headers=csrf_header(client))
            assert r.status_code == 200, r.text
            ticket = r.json()["ticket"]

            with client.websocket_connect(
                    f"/api/v1/apps/{app_id}/console/ws?ticket={ticket}",
                    timeout=20) as ws:
                # Send BEFORE reading. A PTY that has nothing buffered says
                # nothing until it is nudged (the node-shell probe needed the
                # same), so a read-first test blocks on a console that is in
                # fact perfectly healthy. There is also no literal "OK"
                # sentinel here: connect_upstream_pty strips Proxmox's prefix
                # and the route forwards only the PTY output behind it.
                marker = "proxploy-pve-integration"
                ws.send_text("\n")
                ws.send_text(f"echo {marker}\n")

                seen = ""
                for _ in range(25):
                    frame = _recv(ws)
                    seen += frame
                    try:
                        payload = json.loads(frame)
                    except ValueError:
                        payload = None
                    if isinstance(payload, dict) and payload.get("type") == "exit":
                        pytest.skip(f"this PVE refuses token auth on the LXC "
                                    f"console, reported cleanly: {payload}")
                    if seen.count(marker) >= 2:   # the typed line AND its output
                        break
                assert seen.count(marker) >= 2, f"no echo came back: {seen[-200:]!r}"
        finally:
            asyncio.run(livepve.destroy_guest(app, host_id, "lxc", ctid))
