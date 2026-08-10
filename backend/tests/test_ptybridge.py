import asyncio
import json
import time

import pytest
import websockets

from proxploy.services.ptybridge import PtyBridgeError, bridge_pty, connect_upstream_pty
import proxploy.services.ptybridge as ptybridge_mod
from tests.fakes.pve_ws import FakeXtermUpstream


def test_handshake_succeeds_and_flushes_buffered_output():
    """Regression test for the bug where connect_upstream_pty discarded
    everything after the literal "OK" prefix: Proxmox's first server->client
    frame on a successful handshake is "OK" immediately followed by any
    already-buffered PTY output (e.g. the shell prompt) -- that buffered text
    is real output the caller must forward to the browser, not something to
    throw away. This calls connect_upstream_pty itself (not a raw
    `websockets.connect`) so it actually exercises -- and can fail against --
    the production handshake code."""
    async def run():
        fake = FakeXtermUpstream(expected_auth_line="proxploy@pve!console:PVEVNC:abc\n",
                                 output_lines=["Welcome\n"])
        url = await fake.start()
        try:
            upstream, buffered = await connect_upstream_pty(
                address="unused", node="pve1", guest_kind="lxc", vmid=150,
                upstream_user="proxploy@pve!console", upstream_ticket="PVEVNC:abc",
                upstream_port="5900", verify_tls=True, tls_fingerprint=None,
                ws_connect=lambda *a, **k: websockets.connect(url, subprotocols=["binary"]),
            )
            assert buffered == "Welcome\n"
            await upstream.close()
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
            upstream, _buffered = await connect_upstream_pty(
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


def test_bridge_pty_reports_exit_code_1_on_abnormal_upstream_close():
    """Regression test for the asyncio.wait() exception-swallowing bug: a
    task's exception raised inside asyncio.wait()'s task set is never
    propagated to the awaiting coroutine unless explicitly retrieved via
    task.exception(). The fake upstream here raises inside its handler after
    one frame, which makes `websockets` close the connection abnormally
    (code 1011, no clean handshake) -- `from_upstream`'s `async for` then
    raises ConnectionClosedError instead of just ending the iteration. Proves
    bridge_pty distinguishes this from a clean close (exit_code=1, not 0)."""
    async def run():
        fake = FakeXtermUpstream(expected_auth_line="proxploy@pve!console:PVEVNC:abc\n",
                                  abort_after_frames=1)
        url = await fake.start()
        try:
            upstream, _buffered = await connect_upstream_pty(
                address="unused", node="pve1", guest_kind="lxc", vmid=150,
                upstream_user="proxploy@pve!console", upstream_ticket="PVEVNC:abc",
                upstream_port="5900", verify_tls=True, tls_fingerprint=None,
                ws_connect=lambda *a, **k: websockets.connect(url, subprotocols=["binary"]),
            )

            sent = []

            class FakeBrowserWs:
                def __init__(self):
                    self._sent_keystroke = False

                async def receive(self):
                    if not self._sent_keystroke:
                        self._sent_keystroke = True
                        return {"type": "websocket.receive", "text": "ls\n"}
                    # Block far longer than the abnormal close should take,
                    # so this task is still in-flight (and gets cancelled)
                    # when from_upstream's ConnectionClosedError wins
                    # FIRST_COMPLETED -- not because the idle timeout fired.
                    await asyncio.Event().wait()

                async def send_text(self, data):
                    sent.append(data)

                async def close(self, code=1000):
                    pass

            start = time.monotonic()
            # Generous idle_timeout_s: if the abnormal-close detection ever
            # regresses back to the dead-code exception-swallowing bug, the
            # bridge would instead fall through to this timeout, and the
            # elapsed-time assertion below would catch that.
            await bridge_pty(FakeBrowserWs(), upstream, idle_timeout_s=30.0)
            elapsed = time.monotonic() - start

            assert fake.received_frames == ["ls\n"]
            assert elapsed < 5.0, "took the idle-timeout path, not the abnormal-close path"
            assert sent, "browser never received an exit frame"
            assert json.loads(sent[-1]) == {"type": "exit", "code": 1}
        finally:
            await fake.stop()
    asyncio.run(run())


def test_bridge_pty_sends_periodic_keepalive(monkeypatch):
    """Proxmox's own pve-xtermjs client sends a bare "2" every 30s so idle
    PVE-side timeouts don't fire under a silent terminal (plan's wire-protocol
    note) -- bridge_pty must do the same. KEEPALIVE_INTERVAL_S is monkeypatched
    down so this doesn't need a real 30s wait."""
    monkeypatch.setattr(ptybridge_mod, "KEEPALIVE_INTERVAL_S", 0.05)

    async def run():
        fake = FakeXtermUpstream(expected_auth_line="proxploy@pve!console:PVEVNC:abc\n")
        url = await fake.start()
        try:
            upstream, _buffered = await connect_upstream_pty(
                address="unused", node="pve1", guest_kind="lxc", vmid=150,
                upstream_user="proxploy@pve!console", upstream_ticket="PVEVNC:abc",
                upstream_port="5900", verify_tls=True, tls_fingerprint=None,
                ws_connect=lambda *a, **k: websockets.connect(url, subprotocols=["binary"]),
            )

            class FakeBrowserWs:
                async def receive(self):
                    await asyncio.sleep(0.3)
                    return {"type": "websocket.disconnect"}

                async def send_text(self, data):
                    pass

                async def close(self, code=1000):
                    pass

            await bridge_pty(FakeBrowserWs(), upstream, idle_timeout_s=5.0)
            assert fake.keepalive_count >= 3
        finally:
            await fake.stop()
    asyncio.run(run())


def test_bridge_pty_closes_upstream_even_if_browser_side_raises():
    """Regression test for the close-ordering leak: the finally block used to
    await browser_ws.send_text(...) then browser_ws.close() then
    upstream_ws.close() sequentially with no isolation -- if the browser is
    already gone (common: user just closed the tab) the first await raises
    and upstream_ws.close() never runs, leaking a live Proxmox termproxy
    session. Proves upstream_ws.close() still runs even when every browser-
    side step raises."""
    async def run():
        fake = FakeXtermUpstream(expected_auth_line="proxploy@pve!console:PVEVNC:abc\n")
        url = await fake.start()
        try:
            upstream, _buffered = await connect_upstream_pty(
                address="unused", node="pve1", guest_kind="lxc", vmid=150,
                upstream_user="proxploy@pve!console", upstream_ticket="PVEVNC:abc",
                upstream_port="5900", verify_tls=True, tls_fingerprint=None,
                ws_connect=lambda *a, **k: websockets.connect(url, subprotocols=["binary"]),
            )
            closed = {"upstream": False}
            orig_close = upstream.close

            async def tracking_close(*a, **k):
                closed["upstream"] = True
                await orig_close(*a, **k)
            upstream.close = tracking_close

            class BrowserGoneWs:
                async def receive(self):
                    return {"type": "websocket.disconnect"}

                async def send_text(self, data):
                    raise RuntimeError("browser already disconnected")

                async def close(self, code=1000):
                    raise RuntimeError("browser already disconnected")

            await bridge_pty(BrowserGoneWs(), upstream, idle_timeout_s=5.0)
            assert closed["upstream"] is True
        finally:
            await fake.stop()
    asyncio.run(run())


def test_bridge_pty_ignores_malformed_resize_instead_of_crashing():
    """Trust-boundary validation: a malformed {"type":"resize"} (missing
    cols/rows) must not KeyError-crash the bridge, and a payload with
    non-numeric cols/rows must never be forwarded verbatim into Proxmox's
    line-oriented "1:{cols}:{rows}:" control channel."""
    async def run():
        fake = FakeXtermUpstream(expected_auth_line="proxploy@pve!console:PVEVNC:abc\n")
        url = await fake.start()
        try:
            upstream, _buffered = await connect_upstream_pty(
                address="unused", node="pve1", guest_kind="lxc", vmid=150,
                upstream_user="proxploy@pve!console", upstream_ticket="PVEVNC:abc",
                upstream_port="5900", verify_tls=True, tls_fingerprint=None,
                ws_connect=lambda *a, **k: websockets.connect(url, subprotocols=["binary"]),
            )
            recv_calls = []

            class FakeBrowserWs:
                async def receive(self):
                    n = len(recv_calls)
                    recv_calls.append(None)
                    if n == 0:
                        return {"type": "websocket.receive", "text": '{"type":"resize"}'}
                    if n == 1:
                        return {"type": "websocket.receive",
                                "text": '{"type":"resize","cols":"80:24:\\ninjected","rows":40}'}
                    return {"type": "websocket.disconnect"}

                async def send_text(self, data):
                    pass

                async def close(self, code=1000):
                    pass

            # Must not raise (no KeyError/ValueError escaping bridge_pty).
            await bridge_pty(FakeBrowserWs(), upstream, idle_timeout_s=5.0)
            assert fake.received_resizes == []
            assert fake.received_frames == []
        finally:
            await fake.stop()
    asyncio.run(run())


def test_upstream_url_and_headers_are_what_a_real_pve_requires(monkeypatch):
    """The three defects a live PVE 9.2.6 found on 2026-08-10, none of which
    any other test in this file can see.

    Every other test here injects `ws_connect`, which skips URL construction
    and header assembly entirely -- so the real path went five phases without
    once being exercised. Against genuine Proxmox all three are fatal:

    - no Authorization header: PVE authenticates the websocket UPGRADE, not
      just the termproxy POST, and answers `401 No ticket`;
    - unquoted vncticket: a PVEVNC ticket is base64, so a "+" arrives as a
      space and PVE rejects it, again with a bare 401;
    - bytes frames: the `binary` subprotocol means a real node's frames are
      bytes, and the browser half of the bridge sends text.
    """
    captured = {}

    class _FakeWS:
        async def send(self, _):
            return None

        async def recv(self):
            return b"OKprompt$ "        # bytes, exactly as a real node sends

        async def close(self):
            return None

    def fake_connect(uri, **kw):
        captured["uri"] = uri
        captured["headers"] = kw.get("additional_headers")

        class _Ctx:
            def __await__(self):
                async def _go():
                    return _FakeWS()
                return _go().__await__()
        return _Ctx()

    monkeypatch.setattr(ptybridge_mod.websockets, "connect", fake_connect)
    monkeypatch.setattr(ptybridge_mod, "open_validated_tcp_socket", lambda h, p: None)

    async def run():
        return await connect_upstream_pty(
            address="https://10.0.0.5:8006", node="pve1", guest_kind="lxc", vmid=150,
            upstream_user="root@pam!testing", upstream_ticket="PVEVNC:a+b/c=",
            upstream_port="5900", verify_tls=True, tls_fingerprint=None,
            auth_header="PVEAPIToken=root@pam!testing=secret")

    _upstream, buffered = asyncio.run(run())

    assert captured["headers"] == {"Authorization": "PVEAPIToken=root@pam!testing=secret"}
    assert "vncticket=PVEVNC%3Aa%2Bb%2Fc%3D" in captured["uri"], captured["uri"]
    assert "+" not in captured["uri"].split("vncticket=")[1]
    # bytes in, str out, with Proxmox's "OK" prefix stripped
    assert buffered == "prompt$ "
