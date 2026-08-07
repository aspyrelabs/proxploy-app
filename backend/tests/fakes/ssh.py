"""Fake asyncssh-shaped connection (mirrors tests/fakes/pve.py's FakePVE) so
executor tests never open a real socket."""
import asyncio


class _FakeStream:
    def __init__(self, lines: list[str]):
        self._lines = lines

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for line in self._lines:
            yield line + "\n"


class _FakeProcess:
    def __init__(self, conn: "FakeSSHConnection"):
        self._conn = conn
        self.stdout = _FakeStream(conn.stdout_lines)
        self.stderr = _FakeStream(conn.stderr_lines)
        self.exit_status = conn.exit_status
        self._terminated = False

    async def wait_closed(self):
        if self._conn.hang:
            await asyncio.sleep(999)

    def terminate(self):
        self._terminated = True


class FakeSFTPFile:
    """Mirrors asyncssh's SFTPClientFile just enough for
    executor/transfer.py::sftp_copy's read/write chunk loop, backed by a
    plain `{path: bytes}` dict so a test can share one "network" between two
    independently-constructed fake connections (Phase 8 Task 16)."""

    def __init__(self, store: dict[str, bytes], path: str, *, write: bool):
        self._store, self._path = store, path
        self._pos = 0
        if write:
            self._store[path] = b""

    async def read(self, size: int = -1, offset: int | None = None) -> bytes:
        data = self._store.get(self._path, b"")
        pos = self._pos if offset is None else offset
        chunk = data[pos:] if size is None or size < 0 else data[pos:pos + size]
        self._pos = pos + len(chunk)
        return chunk

    async def write(self, data: bytes, offset: int | None = None) -> int:
        pos = self._pos if offset is None else offset
        cur = self._store.get(self._path, b"")
        if len(cur) < pos:
            cur = cur + b"\x00" * (pos - len(cur))
        self._store[self._path] = cur[:pos] + bytes(data) + cur[pos + len(data):]
        self._pos = pos + len(data)
        return len(data)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSFTP:
    """`.open()` returns an object usable both awaited and as `async with
    sftp.open(path, mode)`, matching asyncssh's real `@async_context_manager`
    -decorated `SFTPClient.open`, sftp_copy only ever uses the `async with`
    form, so that's the only shape implemented here."""

    def __init__(self, store: dict[str, bytes]):
        self._store = store

    def open(self, path: str, mode: str = "rb"):
        if "r" in mode and path not in self._store:
            raise FileNotFoundError(path)
        return FakeSFTPFile(self._store, path, write="w" in mode)


class FakeSSHConnection:
    def __init__(self, *, host_key_fingerprint: str, stdout_lines: list[str],
                stderr_lines: list[str], exit_status: int, hang: bool = False,
                on_create_process=None, sftp_store: dict[str, bytes] | None = None):
        self.host_key_fingerprint = host_key_fingerprint
        self.stdout_lines = stdout_lines
        self.stderr_lines = stderr_lines
        self.exit_status = exit_status
        self.hang = hang
        # Shared (or private, if a test passes none) in-memory "filesystem"
        # for start_sftp_client() below: two FakeSSHConnections constructed
        # with the SAME dict instance behave like two SSH sessions into two
        # hosts that happen to be reachable from the same fake "network"
        # (Phase 8 Task 16's sftp_copy tests pass distinct storage `path`
        # roots per host so keys never collide).
        self.sftp_store: dict[str, bytes] = {} if sftp_store is None else sftp_store
        self.stdin_closed: bool | None = None
        # The exact command string handed to create_process. Captured because
        # env vars are inlined into it (SSH env channel requests are dropped
        # by default sshd AcceptEnv): asserting on it is the only way to
        # prove an override actually reaches the remote process.
        self.last_command: str | None = None
        # Fires right after the command is recorded, before the process
        # object is returned (Phase 7 Task 5): lets a test mutate FakePVE
        # mid-run, e.g. simulate the catalog script taking build.func's
        # install branch and creating a stray CT while "over SSH" the update
        # is still in flight.
        self._on_create_process = on_create_process

    async def create_process(self, command, *, env=None, stdin=None):
        self.last_command = command
        self.stdin_closed = stdin is not None
        if self._on_create_process is not None:
            self._on_create_process(command)
        return _FakeProcess(self)

    async def start_sftp_client(self, **kwargs) -> FakeSFTP:
        return FakeSFTP(self.sftp_store)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def make_fake_connect_factory(fake: FakeSSHConnection):
    async def factory(host, private_key_pem, *, pinned_fingerprint, on_new_fingerprint):
        if pinned_fingerprint is not None and pinned_fingerprint != fake.host_key_fingerprint:
            from proxploy.executor.ssh import SSHHostKeyMismatch
            raise SSHHostKeyMismatch(
                f"host key changed: pinned {pinned_fingerprint}, saw {fake.host_key_fingerprint}")
        if pinned_fingerprint is None:
            on_new_fingerprint(fake.host_key_fingerprint)
        return fake
    return factory


def make_addressed_connect_factory(fakes: dict[str, FakeSSHConnection]):
    """Two-host tests (Phase 8 Task 16): route to the right fake connection by
    the `host` argument the connect_factory is called with, mirrors
    tests/fakes/pve.py's `make_addressed_factory`."""
    async def factory(host, private_key_pem, *, pinned_fingerprint, on_new_fingerprint):
        fake = fakes[host]
        if pinned_fingerprint is not None and pinned_fingerprint != fake.host_key_fingerprint:
            from proxploy.executor.ssh import SSHHostKeyMismatch
            raise SSHHostKeyMismatch(
                f"host key changed: pinned {pinned_fingerprint}, saw {fake.host_key_fingerprint}")
        if pinned_fingerprint is None:
            on_new_fingerprint(fake.host_key_fingerprint)
        return fake
    return factory
