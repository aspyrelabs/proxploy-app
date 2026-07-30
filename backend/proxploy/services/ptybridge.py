"""Bridges a browser-facing FastAPI WebSocket to Proxmox's termproxy/xtermjs
websocket. See the plan's "Confirmed, not assumed" note for the wire protocol
(reverse-engineered from Proxmox's own pve-xtermjs client) and the "Spike
correction" note for the known API-token-vs-termproxy PVE limitation this
module's PtyBridgeError surfaces rather than hides."""
import asyncio
import json
import ssl
from urllib.parse import urlparse

import websockets

from proxploy.services.proxmox import open_validated_tcp_socket, tls_fingerprint_sha256


class PtyBridgeError(RuntimeError):
    pass


def _guest_path(node: str, guest_kind: str | None, vmid: int | None) -> str:
    if guest_kind is None:
        return f"/nodes/{node}"
    return f"/nodes/{node}/{guest_kind}/{vmid}"


async def connect_upstream_pty(*, address: str, node: str, guest_kind: str | None,
                                vmid: int | None, upstream_user: str,
                                upstream_ticket: str, upstream_port: str,
                                verify_tls: bool, tls_fingerprint: str | None,
                                ws_connect=None):
    """ws_connect is an injection seam for tests (skips the real TLS/SSRF path
    against a plain ws:// loopback fake); production callers omit it and get
    the real wss:// connection below."""
    if ws_connect is None:
        url = urlparse(address)
        host = url.hostname
        uri = (f"wss://{host}:8006/api2/json{_guest_path(node, guest_kind, vmid)}"
               f"/vncwebsocket?port={upstream_port}&vncticket={upstream_ticket}")
        if not verify_tls and tls_fingerprint:
            seen = tls_fingerprint_sha256(host, 8006)
            if seen != tls_fingerprint.upper():
                raise PtyBridgeError(
                    f"TLS fingerprint mismatch: pinned {tls_fingerprint}, got {seen}")
        ctx = ssl.create_default_context() if verify_tls else ssl._create_unverified_context()
        sock = open_validated_tcp_socket(host, 8006)
        ws_connect = lambda: websockets.connect(
            uri, subprotocols=["binary"], sock=sock, ssl=ctx, server_hostname=host)
        upstream = await ws_connect()
    else:
        upstream = await ws_connect()

    await upstream.send(f"{upstream_user}:{upstream_ticket}\n")
    try:
        first = await asyncio.wait_for(upstream.recv(), timeout=10.0)
    except (TimeoutError, websockets.ConnectionClosed) as e:
        raise PtyBridgeError(f"termproxy handshake failed: {e}") from e
    if not first.startswith("OK"):
        await upstream.close()
        raise PtyBridgeError(f"termproxy rejected the handshake: {first}")
    return upstream


async def bridge_pty(browser_ws, upstream_ws, *, idle_timeout_s: float) -> None:
    """Doc 05 framing on the browser side: raw text keystrokes/output, one
    JSON control frame `{"type":"resize",...}` from the client, one
    `{"type":"exit","code":...}` from us before close. Proxmox side: see the
    plan's wire-protocol note (0:/1:/2 framing)."""
    exit_code = 0

    async def from_browser():
        while True:
            msg = await asyncio.wait_for(browser_ws.receive(), timeout=idle_timeout_s)
            if msg.get("type") == "websocket.disconnect":
                return
            text = msg.get("text")
            if text is None:
                continue
            try:
                control = json.loads(text)
            except ValueError:
                control = None
            if isinstance(control, dict) and control.get("type") == "resize":
                await upstream_ws.send(f"1:{control['cols']}:{control['rows']}:")
            else:
                payload = text.encode("utf-8")
                await upstream_ws.send(f"0:{len(payload)}:{text}")

    async def from_upstream():
        async for frame in upstream_ws:
            await browser_ws.send_text(frame)

    try:
        done, pending = await asyncio.wait(
            [asyncio.create_task(from_browser()), asyncio.create_task(from_upstream())],
            return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in pending:
            try:
                await task
            except asyncio.CancelledError:
                pass
        # asyncio.wait() never propagates a done task's exception to the
        # await point above -- it just sits unretrieved on the task -- so
        # without this, an idle timeout or abnormal upstream close would
        # still stop the bridge (FIRST_COMPLETED already saw it as done)
        # but would silently misreport exit_code as 0.
        for task in done:
            exc = task.exception()
            if exc is not None:
                raise exc
    except (TimeoutError, websockets.ConnectionClosed):
        exit_code = 1
    finally:
        await browser_ws.send_text(json.dumps({"type": "exit", "code": exit_code}))
        await browser_ws.close()
        await upstream_ws.close()
