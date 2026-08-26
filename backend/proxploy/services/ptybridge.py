"""Bridges a browser-facing FastAPI WebSocket to Proxmox's termproxy/xtermjs
websocket (wire protocol reverse-engineered from Proxmox's own pve-xtermjs
client). PtyBridgeError surfaces the known API-token-vs-termproxy PVE
limitation rather than hiding it."""
import asyncio
import json
import ssl
from urllib.parse import quote, urlparse

import websockets

from proxploy.services.proxmox import open_validated_tcp_socket, tls_fingerprint_sha256


class PtyBridgeError(RuntimeError):
    pass


# Proxmox's own pve-xtermjs client sends a bare "2" every 30s to keep PVE's
# own idle timeout from firing on a silent terminal. A module-level constant
# (not a bridge_pty kwarg) so tests can monkeypatch it down without changing
# bridge_pty's public signature.
KEEPALIVE_INTERVAL_S = 30.0


def _guest_path(node: str, guest_kind: str | None, vmid: int | None) -> str:
    if guest_kind is None:
        return f"/nodes/{node}"
    return f"/nodes/{node}/{guest_kind}/{vmid}"


async def _best_effort(coro) -> None:
    """Run a best-effort cleanup step: swallow its exception so a sibling
    cleanup step (in particular the upstream Proxmox socket close) still runs
    even if this one fails -- e.g. the browser already dropped the TCP
    connection, so browser_ws.send_text/close raise, but upstream_ws.close()
    must still fire or the PVE-side termproxy session leaks."""
    try:
        await coro
    except Exception:
        pass


def _as_text(frame) -> str:
    """PVE's termproxy negotiates the `binary` subprotocol, so a real node
    sends every frame as bytes while the browser half of this bridge is text.

    ponytail: errors="replace" decodes each frame independently, so a
    multi-byte character split across two frames shows one replacement
    char. Buffer the trailing partial sequence here if that ever shows up in
    a real terminal session.
    """
    return frame.decode("utf-8", "replace") if isinstance(frame, (bytes, bytearray)) else frame


async def connect_upstream_pty(*, address: str, node: str, guest_kind: str | None,
                                vmid: int | None, upstream_user: str,
                                upstream_ticket: str, upstream_port: str,
                                verify_tls: bool, tls_fingerprint: str | None,
                                auth_header: str | None = None,
                                ws_connect=None) -> tuple:
    """ws_connect is an injection seam for tests (skips the real TLS/SSRF path).

    Returns (upstream_ws, buffered: str). `buffered` is PTY output Proxmox
    already had waiting (e.g. the shell prompt) at the tail of the first
    "OK"-prefixed frame -- the caller must forward it to the browser before
    starting bridge_pty's loop, or the user sees a blank terminal until they
    press Enter (real output, never a literal "OK" sentinel)."""
    if ws_connect is None:
        url = urlparse(address)
        host = url.hostname
        port = url.port or 8006  # match ProxmoxClient._connect's own fallback
        # quote(safe="") is load-bearing: a PVEVNC ticket is base64 and
        # routinely contains "+" and "/", which arrive at PVE as a space and a
        # path separator unquoted, and it answers 401 with no hint that the
        # ticket was the thing it could not read.
        uri = (f"wss://{host}:{port}/api2/json{_guest_path(node, guest_kind, vmid)}"
               f"/vncwebsocket?port={quote(str(upstream_port), safe='')}"
               f"&vncticket={quote(upstream_ticket, safe='')}")
        if not verify_tls and tls_fingerprint:
            # Blocking socket/TLS I/O -- must not run directly on the event
            # loop (a slow/unreachable PVE host would otherwise stall every
            # other request this uvicorn worker is serving).
            seen = await asyncio.to_thread(tls_fingerprint_sha256, host, port)
            if seen != tls_fingerprint.upper():
                raise PtyBridgeError(
                    f"TLS fingerprint mismatch: pinned {tls_fingerprint}, got {seen}")
        ctx = ssl.create_default_context() if verify_tls else ssl._create_unverified_context()
        sock = await asyncio.to_thread(open_validated_tcp_socket, host, port)
        ws_connect = lambda: websockets.connect(
            uri, subprotocols=["binary"], sock=sock, ssl=ctx, server_hostname=host,
            additional_headers={"Authorization": auth_header} if auth_header else None)
    # One call site for both branches so the rejected-upgrade path is handled
    # identically. websockets raises InvalidStatus (a WebSocketException) when
    # PVE answers the upgrade with 401/403; uncaught, that escapes _run_pty_ws
    # as a 500 with the socket already accepted, so the browser sees a dead
    # terminal instead of the documented exit frame.
    try:
        upstream = await ws_connect()
    except (OSError, websockets.WebSocketException) as e:
        raise PtyBridgeError(f"console upgrade rejected by Proxmox: {e}") from e

    await upstream.send(f"{upstream_user}:{upstream_ticket}\n")
    try:
        first = _as_text(await asyncio.wait_for(upstream.recv(), timeout=10.0))
    except (TimeoutError, websockets.ConnectionClosed) as e:
        raise PtyBridgeError(f"termproxy handshake failed: {e}") from e
    if not first.startswith("OK"):
        await upstream.close()
        raise PtyBridgeError(f"termproxy rejected the handshake: {first}")
    return upstream, first[2:]


async def _keepalive(upstream_ws) -> None:
    while True:
        await asyncio.sleep(KEEPALIVE_INTERVAL_S)
        await upstream_ws.send("2")


async def bridge_pty(browser_ws, upstream_ws, *, idle_timeout_s: float) -> None:
    """Browser side: raw text keystrokes/output, one JSON control frame
    `{"type":"resize",...}` from the client, one `{"type":"exit","code":...}`
    from us before close. Proxmox side uses 0:/1:/2 length framing."""
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
                # Trust-boundary validation: a malformed frame (missing keys,
                # non-numeric values) must not crash the bridge, and must never
                # let arbitrary strings splice into Proxmox's line-oriented
                # "1:{cols}:{rows}:" control channel -- coerce to int and drop
                # the frame silently on failure rather than forwarding it or
                # raising.
                try:
                    cols = int(control.get("cols"))
                    rows = int(control.get("rows"))
                except (TypeError, ValueError):
                    continue
                await upstream_ws.send(f"1:{cols}:{rows}:")
            else:
                payload = text.encode("utf-8")
                await upstream_ws.send(f"0:{len(payload)}:{text}")

    async def from_upstream():
        async for frame in upstream_ws:
            await browser_ws.send_text(_as_text(frame))

    keepalive_task = asyncio.create_task(_keepalive(upstream_ws))
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
        keepalive_task.cancel()
        try:
            await keepalive_task
        except asyncio.CancelledError:
            pass
        # Each step below is independently best-effort: if the browser socket
        # is already gone (the common case -- user just closed the tab),
        # send_text/close raise, and without isolating each step the
        # upstream_ws.close() after it would never run, leaking a live
        # Proxmox termproxy session (and its PVE-side PTY) per abandoned
        # console.
        await _best_effort(browser_ws.send_text(json.dumps({"type": "exit", "code": exit_code})))
        await _best_effort(browser_ws.close())
        await _best_effort(upstream_ws.close())
