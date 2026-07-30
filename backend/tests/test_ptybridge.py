import asyncio

import pytest
import websockets

from proxploy.services.ptybridge import PtyBridgeError, bridge_pty, connect_upstream_pty
from tests.fakes.pve_ws import FakeXtermUpstream


async def _connect_direct(url):
    """Bypass the SSRF/TLS-pinning wrapper for handshake-only tests — a plain
    ws:// loopback fake server, so this exercises connect_upstream_pty's
    protocol logic without also re-testing Task 1's already-covered TLS path."""
    return await websockets.connect(url, subprotocols=["binary"])


def test_handshake_succeeds_and_flushes_buffered_output():
    async def run():
        fake = FakeXtermUpstream(expected_auth_line="proxploy@pve!console:PVEVNC:abc\n",
                                 output_lines=["Welcome\n"])
        url = await fake.start()
        try:
            ws = await _connect_direct(url)
            await ws.send("proxploy@pve!console:PVEVNC:abc\n")
            first = await ws.recv()
            assert first == "OKWelcome\n"
        finally:
            await fake.stop()
    asyncio.run(run())


def test_connect_upstream_pty_raises_on_rejected_auth():
    async def run():
        fake = FakeXtermUpstream(expected_auth_line="ignored", reject=True)
        url = await fake.start()
        try:
            with pytest.raises(PtyBridgeError, match="does not look like a valid user"):
                await connect_upstream_pty(
                    address="unused", node="pve1", guest_kind="lxc", vmid=150,
                    upstream_user="proxploy@pve!console", upstream_ticket="PVEVNC:abc",
                    upstream_port="5900", verify_tls=True, tls_fingerprint=None,
                    ws_connect=lambda *a, **k: websockets.connect(url, subprotocols=["binary"]),
                )
        finally:
            await fake.stop()
    asyncio.run(run())


def test_bridge_pty_translates_resize_and_keystrokes():
    async def run():
        fake = FakeXtermUpstream(expected_auth_line="proxploy@pve!console:PVEVNC:abc\n")
        url = await fake.start()
        try:
            upstream = await connect_upstream_pty(
                address="unused", node="pve1", guest_kind="lxc", vmid=150,
                upstream_user="proxploy@pve!console", upstream_ticket="PVEVNC:abc",
                upstream_port="5900", verify_tls=True, tls_fingerprint=None,
                ws_connect=lambda *a, **k: websockets.connect(url, subprotocols=["binary"]),
            )

            sent, closed = [], []
            recv_calls = []
            echoed = asyncio.Event()

            class FakeBrowserWs:
                async def receive(self):
                    # Keyed on the number of receive() calls, not on `sent`:
                    # a resize control frame produces no upstream reply, so
                    # gating on len(sent) would return the resize message
                    # forever and spin bridge_pty in a busy loop. The final
                    # call waits for the upstream's echo of the keystroke to
                    # actually land in `sent` before signalling disconnect --
                    # without this wait, disconnect could race ahead of the
                    # echo's round trip and the test would pass even against
                    # a bridge_pty that drops in-flight upstream output.
                    n = len(recv_calls)
                    recv_calls.append(None)
                    if n == 0:
                        return {"type": "websocket.receive", "text": '{"type":"resize","cols":100,"rows":40}'}
                    if n == 1:
                        return {"type": "websocket.receive", "text": "ls\n"}
                    await echoed.wait()
                    return {"type": "websocket.disconnect"}

                async def send_text(self, data):
                    sent.append(data)
                    if "echo:" in data:
                        echoed.set()

                async def close(self, code=1000):
                    closed.append(code)

            await bridge_pty(FakeBrowserWs(), upstream, idle_timeout_s=5.0)

            assert fake.received_resizes == [(100, 40)]
            assert fake.received_frames == ["ls\n"]
            assert any("echo:ls" in s for s in sent)
            assert closed
        finally:
            await fake.stop()
    asyncio.run(run())
