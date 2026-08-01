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


class FakeSSHConnection:
    def __init__(self, *, host_key_fingerprint: str, stdout_lines: list[str],
                stderr_lines: list[str], exit_status: int, hang: bool = False,
                on_create_process=None):
        self.host_key_fingerprint = host_key_fingerprint
        self.stdout_lines = stdout_lines
        self.stderr_lines = stderr_lines
        self.exit_status = exit_status
        self.hang = hang
        self.stdin_closed: bool | None = None
        # The exact command string handed to create_process. Captured because
        # env vars are inlined into it (SSH env channel requests are dropped
        # by default sshd AcceptEnv) — asserting on it is the only way to
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
