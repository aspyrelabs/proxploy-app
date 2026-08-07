"""Transparent binary VNC bridge (doc 05 §3): no protocol translation, unlike
PtyBridge, the ticket is validated by Proxmox at websocket-upgrade time via
the URL query params, so there's no client-sent auth line; the first upstream
frame is the RFB greeting itself, which noVNC's own RFB class consumes."""
import asyncio
import ssl
from urllib.parse import urlparse

import websockets

from proxploy.services.proxmox import open_validated_tcp_socket, tls_fingerprint_sha256


class ConsoleProxyError(RuntimeError):
    """Mirrors PtyBridgeError's role for the VNC path -- raised on a TLS-pin
    mismatch so callers (api/consoles.py's vm_vnc_ws) can catch this
    specifically and send the browser a clean signal instead of an unhandled
    exception and a bare abnormal close."""


async def connect_upstream_vnc(*, address: str, node: str, vmid: int,
                                upstream_ticket: str, upstream_port: str,
                                verify_tls: bool, tls_fingerprint: str | None,
                                ws_connect=None):
    if ws_connect is None:
        url = urlparse(address)
        host = url.hostname
        port = url.port or 8006  # match ProxmoxClient._connect's own fallback
        uri = (f"wss://{host}:{port}/api2/json/nodes/{node}/qemu/{vmid}"
               f"/vncwebsocket?port={upstream_port}&vncticket={upstream_ticket}")
        if not verify_tls and tls_fingerprint:
            # Blocking socket/TLS I/O -- must not run directly on the event
            # loop (a slow/unreachable PVE host would otherwise stall every
            # other request this uvicorn worker is serving).
            seen = await asyncio.to_thread(tls_fingerprint_sha256, host, port)
            if seen != tls_fingerprint.upper():
                raise ConsoleProxyError(
                    f"TLS fingerprint mismatch: pinned {tls_fingerprint}, got {seen}")
        ctx = ssl.create_default_context() if verify_tls else ssl._create_unverified_context()
        sock = await asyncio.to_thread(open_validated_tcp_socket, host, port)
        ws_connect = lambda: websockets.connect(
            uri, subprotocols=["binary"], sock=sock, ssl=ctx, server_hostname=host)
    return await ws_connect()


async def _best_effort(coro) -> None:
    """Same best-effort cleanup helper as ptybridge.py's -- kept local rather
    than shared since each bridge's finally block is only two/three lines and
    the two modules already duplicate this shape deliberately (see the
    comments in bridge_binary/bridge_pty)."""
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
        # asyncio.wait() never propagates a done task's exception to the
        # await point above -- it just sits unretrieved on the task -- so
        # without this, an idle timeout or abnormal upstream close would
        # still stop the bridge (FIRST_COMPLETED already saw it as done) but
        # the exception would be silently dropped instead of hitting the
        # except clause below. Same footgun as bridge_pty (Task 3).
        for task in done:
            exc = task.exception()
            if exc is not None:
                raise exc
    except (TimeoutError, websockets.ConnectionClosed):
        pass
    finally:
        # Isolated best-effort steps -- see ptybridge.bridge_pty's identical
        # comment: if the browser is already gone, close() raising here must
        # not prevent upstream_ws.close() from running (a live VNC/termproxy
        # session leaking per abandoned tab otherwise).
        await _best_effort(browser_ws.close())
        await _best_effort(upstream_ws.close())
