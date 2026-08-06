"""asyncssh-backed root shell executor (doc 08 §4). This module is the only
one (besides executor/keys.py) allowed to import asyncssh — enforced by
scripts/check_executor_isolation.py.

Stdin is always closed (asyncssh.DEVNULL), never left open: the Phase 4
entry-gate spike (docs/notes/phase-4-spike.md) proved that an unguarded
upstream `read` prompt hard-aborts under closed stdin but hangs forever
under an open, idle stdin — closed stdin is the only choice that fails fast
instead of parking a JobBackend semaphore slot indefinitely.
"""
from __future__ import annotations

import asyncio
import re
import shlex
from collections.abc import Callable
from urllib.parse import urlparse

import asyncssh

CONNECT_TIMEOUT_S = 15.0


def normalize_ssh_host(address: str) -> str:
    """`Host.address` (api/hosts.py) is stored as a full `scheme://host:port`
    URL — the same shape services/proxmox.py::ProxmoxClient._connect parses
    for HTTPS — but asyncssh's `host` argument wants a bare hostname/IP.
    Strips scheme and port; falls back to the raw string when there is no
    scheme (`urlparse(...).hostname` is None for a bare host/IP), which also
    covers a bare unbracketed IPv6 literal. A bare bracketed IPv6 literal
    (`"[::1]"`, no scheme) is the one shape urlparse can't help with either
    way, so that's unwrapped by hand.
    """
    hostname = urlparse(address).hostname
    if hostname:
        return hostname
    if address.startswith("[") and address.endswith("]"):
        return address[1:-1]
    return address

# POSIX shell variable name. `env` keys are inlined literally (unquoted) into
# the command string below, so a key isn't just data like a value is — an
# unvalidated key IS shell syntax. shlex.quote on the value can't help here;
# this is the only thing standing between an admin-supplied override key
# (proxploy/api/catalog.py InstallIn.overrides, untyped keys) and a second
# root command riding in via e.g. `"os; touch /tmp/pwned; a": "1"`.
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SSHHostKeyMismatch(Exception):
    """The node's SSH host key does not match what was pinned at first
    connect (doc 08 §4: hard-fail, never auto-accept)."""


async def default_connect_factory(host: str, private_key_pem: bytes, *,
                                  pinned_fingerprint: str | None,
                                  on_new_fingerprint: Callable[[str], None],
                                  port: int = 22):
    # port defaults to the real SSH port; it's a keyword-only extra (not
    # part of SSHExecutor.run's contract) so tests can point this factory at
    # an in-process asyncssh server on an ephemeral port.
    key = asyncssh.import_private_key(private_key_pem)
    captured: dict[str, str] = {}

    class _PinningClient(asyncssh.SSHClient):
        def validate_host_public_key(self, host_, addr, port_, key_) -> bool:
            # Always accept at the transport layer and only capture the
            # fingerprint here. Returning False on a mismatch would make
            # asyncssh itself abort the handshake with its own
            # HostKeyNotVerifiable *before* the caller gets a chance to see
            # a proper SSHHostKeyMismatch — the mismatch decision belongs to
            # the post-connect check below, which can also close the
            # connection cleanly instead of asyncssh tearing it down mid-kex.
            captured["fingerprint"] = key_.get_fingerprint()
            return True

    conn, _ = await asyncssh.create_connection(
        _PinningClient, host, port, username="root", client_keys=[key],
        # known_hosts=None disables asyncssh's own trust store AND skips
        # calling validate_host_public_key entirely (asyncssh sets
        # _trusted_host_keys=None and never invokes the callback) — that
        # silently no-ops our TOFU pinning. known_hosts=b'' (an empty inline
        # trust store, not "no check") keeps _trusted_host_keys as an empty
        # set, which is what makes asyncssh actually call
        # validate_host_public_key below.
        known_hosts=b"", connect_timeout=CONNECT_TIMEOUT_S,
    )
    if pinned_fingerprint is not None and captured.get("fingerprint") != pinned_fingerprint:
        conn.close()
        await conn.wait_closed()
        raise SSHHostKeyMismatch(
            f"host key changed: pinned {pinned_fingerprint}, saw {captured.get('fingerprint')}")
    if pinned_fingerprint is None and "fingerprint" in captured:
        on_new_fingerprint(captured["fingerprint"])
    return conn


class SSHExecutor:
    """One executor per install/update job. `connect_factory` is an
    injectable seam (mirrors `proxmox_factory`) so tests never open a real
    socket."""

    def __init__(self, connect_factory=default_connect_factory):
        self._connect_factory = connect_factory

    async def run(self, host: str, private_key_pem: bytes, command: str, *,
                  pinned_fingerprint: str | None,
                  on_new_fingerprint: Callable[[str], None],
                  env: dict[str, str] | None = None,
                  on_line: Callable[[str, str], None] | None = None,
                  timeout_s: float = 1800.0) -> int:
        """Run `command` as root on `host`, streaming output line-by-line.

        `env` is inlined as a shell-quoted `KEY=value ...` prefix on the
        command string, NOT passed through asyncssh's `env=` kwarg. This is
        not a style choice: asyncssh's `env=` sends each variable as an SSH
        protocol `env` channel request, and stock OpenSSH `sshd` silently
        drops every variable not listed in its `AcceptEnv` directive — which
        defaults to empty (only `LANG`/`LC_*` survive on most builds). On a
        default-configured Proxmox node that means `MODE`, `PHS_SILENT` and
        every `var_*` override would vanish before the remote script saw
        them, with no error anywhere. Inlining into the command is the only
        mechanism that works without editing the node's sshd config.
        """
        for k in (env or {}):
            if not _ENV_KEY_RE.match(k):
                raise ValueError(f"invalid env var name: {k!r}")
        conn = await self._connect_factory(
            normalize_ssh_host(host), private_key_pem, pinned_fingerprint=pinned_fingerprint,
            on_new_fingerprint=on_new_fingerprint)
        async with conn:
            env_prefix = " ".join(f"{k}={shlex.quote(str(v))}"
                                  for k, v in (env or {}).items())
            full_command = f"{env_prefix} {command}" if env_prefix else command
            proc = await conn.create_process(full_command, stdin=asyncssh.DEVNULL)

            async def _pump(stream, name):
                async for line in stream:
                    if on_line:
                        on_line(name, line.rstrip("\n"))

            try:
                await asyncio.wait_for(
                    asyncio.gather(_pump(proc.stdout, "stdout"),
                                  _pump(proc.stderr, "stderr"), proc.wait_closed()),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                proc.terminate()
                raise
            return proc.exit_status

    async def run_for_host(self, sessionmaker, secretstore, host_id: int, host: str,
                           command: str, *, pinned_fingerprint: str | None,
                           on_new_fingerprint: Callable[[str], None],
                           env: dict[str, str] | None = None,
                           on_line: Callable[[str, str], None] | None = None,
                           timeout_s: float = 1800.0) -> int:
        """Same contract as `run`, but resolves the private key from
        SecretStore itself so the raw key bytes never have to leave
        executor/ (docs 08 §4) — callers outside this package pass a
        sessionmaker + host_id instead of a key, and
        scripts/check_executor_isolation.py enforces that only this module
        ever references `get_ssh_private_key`. Raises LookupError if the
        host has no ssh_key credential (see executor/keys.py)."""
        from proxploy.executor.keys import get_ssh_private_key

        with sessionmaker() as db:
            private_key_pem = get_ssh_private_key(db, secretstore, host_id)
        return await self.run(host, private_key_pem, command,
                              pinned_fingerprint=pinned_fingerprint,
                              on_new_fingerprint=on_new_fingerprint, env=env,
                              on_line=on_line, timeout_s=timeout_s)
