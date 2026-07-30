import asyncio

import pytest
import websockets

from proxploy.services.consoleproxy import bridge_binary, connect_upstream_vnc


class FakeRfbUpstream:
    """No auth-line handshake for VNC — the ticket is validated by Proxmox at
    the URL-query-param stage; the first frame IS the RFB greeting."""

    def __init__(self):
        self.received: list[bytes] = []
        self._server = None

    async def _handler(self, ws):
        await ws.send(b"RFB 003.008\n")
        try:
            async for frame in ws:
                self.received.append(frame)
                await ws.send(b"ack:" + frame)
        except websockets.ConnectionClosed:
            pass

    async def start(self) -> str:
        self._server = await websockets.serve(self._handler, "127.0.0.1", 0)
        return f"ws://127.0.0.1:{self._server.sockets[0].getsockname()[1]}"

    async def stop(self):
        self._server.close()
        await self._server.wait_closed()


def test_connect_upstream_vnc_gets_rfb_greeting_with_no_auth_frame():
    async def run():
        fake = FakeRfbUpstream()
        url = await fake.start()
        try:
            upstream = await connect_upstream_vnc(
                address="unused", node="pve1", vmid=200, upstream_ticket="PVEVNC:def",
                upstream_port="5902", verify_tls=True, tls_fingerprint=None,
                ws_connect=lambda: websockets.connect(url, subprotocols=["binary"]),
            )
            greeting = await upstream.recv()
            assert greeting == b"RFB 003.008\n"
        finally:
            await fake.stop()
    asyncio.run(run())


def test_bridge_binary_relays_bytes_untranslated():
    async def run():
        fake = FakeRfbUpstream()
        url = await fake.start()
        try:
            upstream = await connect_upstream_vnc(
                address="unused", node="pve1", vmid=200, upstream_ticket="PVEVNC:def",
                upstream_port="5902", verify_tls=True, tls_fingerprint=None,
                ws_connect=lambda: websockets.connect(url, subprotocols=["binary"]),
            )
            await upstream.recv()  # consume the greeting like a real RFB client would

            sent, closed = [], []
            recv_calls = []
            # Same test-double gating fix as ptybridge's translate test: gate
            # the disconnect on the ack actually landing in `sent`, not on
            # call count alone -- otherwise this races from_browser's
            # disconnect against from_upstream's in-flight ack and
            # FIRST_COMPLETED can fire (cancelling from_upstream) before the
            # ack is ever recorded, which is exactly what happened when this
            # was written verbatim from the brief (frames_in = [frame, None]).
            acked = asyncio.Event()

            class FakeBrowserWs:
                async def receive(self):
                    n = len(recv_calls)
                    recv_calls.append(None)
                    if n == 0:
                        return {"type": "websocket.receive", "bytes": b"\x03\x08\x01\x00"}
                    await acked.wait()
                    return {"type": "websocket.disconnect"}

                async def send_bytes(self, data):
                    sent.append(data)
                    acked.set()

                async def close(self, code=1000):
                    closed.append(code)

            await bridge_binary(FakeBrowserWs(), upstream, idle_timeout_s=5.0)

            assert fake.received == [b"\x03\x08\x01\x00"]
            assert sent == [b"ack:\x03\x08\x01\x00"]
            assert closed
        finally:
            await fake.stop()
    asyncio.run(run())


def test_bridge_binary_propagates_unexpected_task_exceptions():
    """Regression test for the asyncio.wait() exception-swallowing bug (same
    shape as ptybridge's bridge_pty, see test_ptybridge.py): a task's
    exception raised inside asyncio.wait()'s task set is never propagated to
    the awaiting coroutine unless explicitly retrieved via task.exception().
    Unlike bridge_pty, bridge_binary has no exit_code to observe a difference
    through, and both a websockets.ConnectionClosed and a totally-swallowed
    exception look identical from the outside (bridge_binary just returns) --
    so this drives the browser-side task into a *non*-network exception
    instead. Without inspecting `done` and re-raising it, the buggy version
    would swallow this too and return normally, hiding a real bug in the
    transport rather than surfacing it."""
    async def run():
        fake = FakeRfbUpstream()
        url = await fake.start()
        try:
            upstream = await connect_upstream_vnc(
                address="unused", node="pve1", vmid=200, upstream_ticket="PVEVNC:def",
                upstream_port="5902", verify_tls=True, tls_fingerprint=None,
                ws_connect=lambda: websockets.connect(url, subprotocols=["binary"]),
            )
            await upstream.recv()  # consume the greeting

            class BrokenBrowserWs:
                async def receive(self):
                    raise ValueError("simulated bug in the browser-side transport")

                async def send_bytes(self, data):
                    pass

                async def close(self, code=1000):
                    pass

            with pytest.raises(ValueError, match="simulated bug"):
                await bridge_binary(BrokenBrowserWs(), upstream, idle_timeout_s=5.0)
        finally:
            await fake.stop()
    asyncio.run(run())
