"""Transparent binary VNC bridge: no protocol translation (unlike PtyBridge).
Proxmox validates the ticket at websocket-upgrade from URL query params, so
there's no client-sent auth line; the first upstream frame is the RFB greeting,
which noVNC's own RFB class consumes."""
import asyncio
import ssl
from urllib.parse import quote, urlparse

import websockets

from proxploy.services.proxmox import open_validated_tcp_socket, tls_fingerprint_sha256


class ConsoleProxyError(RuntimeError):
    """Raised on a TLS-pin mismatch so callers (vm_vnc_ws) can send the browser
    a clean signal instead of an unhandled exception and bare abnormal close."""


async def connect_upstream_vnc(*, address: str, node: str, vmid: int,
                                upstream_ticket: str, upstream_port: str,
                                verify_tls: bool, tls_fingerprint: str | None,
                                auth_header: str | None = None,
                                ws_connect=None):
    if ws_connect is None:
        url = urlparse(address)
        host = url.hostname
        port = url.port or 8006  # match ProxmoxClient._connect's own fallback
        # PVE authenticates the upgrade itself; the ticket must be quoted or
        # base64 "+"/"/" get dropped (see ProxmoxClient.pve_auth_header).
        uri = (f"wss://{host}:{port}/api2/json/nodes/{node}/qemu/{vmid}"
               f"/vncwebsocket?port={quote(str(upstream_port), safe='')}"
               f"&vncticket={quote(upstream_ticket, safe='')}")
        if not verify_tls and tls_fingerprint:
            # Blocking socket/TLS I/O: run in a thread or a slow/unreachable
            # PVE host stalls every other request on this worker's loop.
            seen = await asyncio.to_thread(tls_fingerprint_sha256, host, port)
            if seen != tls_fingerprint.upper():
                raise ConsoleProxyError(
                    f"TLS fingerprint mismatch: pinned {tls_fingerprint}, got {seen}")
        ctx = ssl.create_default_context() if verify_tls else ssl._create_unverified_context()
        sock = await asyncio.to_thread(open_validated_tcp_socket, host, port)
        ws_connect = lambda: websockets.connect(
            uri, subprotocols=["binary"], sock=sock, ssl=ctx, server_hostname=host,
            additional_headers={"Authorization": auth_header} if auth_header else None)
    # A 401/403 on the upgrade must reach the caller as ConsoleProxyError
    # (which _run_vnc_ws turns into a close frame), not an escaped
    # InvalidStatus on an already-accepted socket.
    try:
        return await ws_connect()
    except (OSError, websockets.WebSocketException) as e:
        raise ConsoleProxyError(f"console upgrade rejected by Proxmox: {e}") from e


async def _best_effort(coro) -> None:
    try:
        await coro
    except Exception:
        pass


async def bridge_binary(browser_ws, upstream_ws, *, idle_timeout_s: float) -> None:
    """Dumb byte relay: RFB is opaque to Proxploy, so unlike bridge_pty there is
    no framing to translate in either direction."""
    async def from_browser():
        while True:
            msg = await asyncio.wait_for(browser_ws.receive(), timeout=idle_timeout_s)
            if msg.get("type") == "websocket.disconnect":
                return
            data = msg.get("bytes")
            if data is not None:
                await upstream_ws.send(data)

    async def from_upstream():
        async for frame in upstream_ws:
            await browser_ws.send_bytes(frame)

    try:
        tasks = [asyncio.create_task(from_browser()), asyncio.create_task(from_upstream())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in pending:
            try:
                await task
            except asyncio.CancelledError:
                pass
        # asyncio.wait() doesn't re-raise a done task's exception -- it sits
        # unretrieved on the task. Without this re-raise, an idle timeout or
        # abnormal close stops the bridge but silently drops the error instead
        # of hitting the except clause below.
        for task in done:
            exc = task.exception()
            if exc is not None:
                raise exc
    except (TimeoutError, websockets.ConnectionClosed):
        pass
    finally:
        # Isolated steps: if the browser is already gone, close() raising here
        # must not prevent upstream_ws.close() (a live session leaks per
        # abandoned tab otherwise).
        await _best_effort(browser_ws.close())
        await _best_effort(upstream_ws.close())
