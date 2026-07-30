"""In-process fake Proxmox vncwebsocket server speaking the documented xtermjs
protocol (see plan doc's "Confirmed, not assumed" note) — enough to prove
PtyBridge's translation logic without a real PVE host."""
import asyncio

import websockets


class FakeXtermUpstream:
    """Records the auth line it received; scripted output lines are sent after
    the OK handshake; echoes decoded keystroke payloads back for round-trip
    tests; a `reject` flag makes the handshake fail the way an unpatched PVE
    would for API-token auth (doc's spike-correction note)."""

    def __init__(self, expected_auth_line: str, output_lines: list[str] | None = None,
                 reject: bool = False):
        self.expected_auth_line = expected_auth_line
        self.output_lines = output_lines or []
        self.reject = reject
        self.received_auth_line: str | None = None
        self.received_frames: list[str] = []
        self.received_resizes: list[tuple[int, int]] = []
        self._server = None

    async def _handler(self, ws):
        auth_line = await ws.recv()
        self.received_auth_line = auth_line
        if self.reject or auth_line != self.expected_auth_line:
            await ws.send("authentication failure; does not look like a valid user name")
            await ws.close()
            return
        await ws.send("OK" + "".join(self.output_lines))
        try:
            async for frame in ws:
                if frame == "2":
                    continue  # keepalive, no reply
                if frame.startswith("1:"):
                    _, cols, rows, _ = frame.split(":", 3)
                    self.received_resizes.append((int(cols), int(rows)))
                    continue
                if frame.startswith("0:"):
                    _, _length, data = frame.split(":", 2)
                    self.received_frames.append(data)
                    await ws.send(f"echo:{data}")
        except websockets.ConnectionClosed:
            pass

    async def start(self) -> str:
        self._server = await websockets.serve(self._handler, "127.0.0.1", 0)
        port = self._server.sockets[0].getsockname()[1]
        return f"ws://127.0.0.1:{port}"

    async def stop(self):
        self._server.close()
        await self._server.wait_closed()
