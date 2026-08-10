import asyncio
import pytest

import asyncssh

from proxploy.executor import SSHExecutor, get_ssh_private_key
from proxploy.executor.ssh import SSHHostKeyMismatch, default_connect_factory, normalize_ssh_host
from tests.fakes.ssh import (FakeSSHConnection, make_addressed_connect_factory,
                             make_fake_connect_factory)
from tests.support import make_db, seed_host_row


def test_run_streams_lines_and_returns_exit_status():
    fake = FakeSSHConnection(
        host_key_fingerprint="SHA256:abc123",
        stdout_lines=["Installing Dependencies", "Installed Dependencies"],
        stderr_lines=[], exit_status=0,
    )
    executor = SSHExecutor(connect_factory=make_fake_connect_factory(fake))
    lines: list[tuple[str, str]] = []
    seen_fp: list[str] = []

    status = asyncio.run(executor.run(
        "10.0.0.9", b"fake-key-pem", "bash /tmp/install.sh",
        pinned_fingerprint=None, on_new_fingerprint=seen_fp.append,
        on_line=lambda stream, line: lines.append((stream, line)),
    ))

    assert status == 0
    assert lines == [("stdout", "Installing Dependencies"), ("stdout", "Installed Dependencies")]
    assert seen_fp == ["SHA256:abc123"]  # first-connect TOFU pin captured
    assert fake.stdin_closed is True  # spike finding: stdin must be closed, never left open


def test_run_inlines_env_vars_into_the_command_string():
    """Regression test for Critical #1B: `env` used to go out via asyncssh's
    `env=` kwarg, i.e. SSH `env` channel requests, which stock OpenSSH sshd
    silently drops unless every name is listed in AcceptEnv (default: none).
    The only reliable mechanism is a shell-quoted prefix on the command."""
    fake = FakeSSHConnection(host_key_fingerprint="SHA256:abc123", stdout_lines=[],
                             stderr_lines=[], exit_status=0)
    executor = SSHExecutor(connect_factory=make_fake_connect_factory(fake))

    asyncio.run(executor.run(
        "10.0.0.9", b"fake-key-pem", "bash /tmp/install.sh",
        pinned_fingerprint=None, on_new_fingerprint=lambda fp: None,
        env={"MODE": "default", "var_ctid": "150", "TITLE": "two words"},
    ))

    assert fake.last_command == (
        "MODE=default var_ctid=150 TITLE='two words' bash /tmp/install.sh")


def test_run_rejects_a_shell_metacharacter_in_an_env_key():
    """Regression test: env values are shlex-quoted but keys never were, 
    an admin-supplied overrides key like `"os; touch /tmp/x"` used to be
    inlined literally into the command, running as a second root command.
    Uses a connect_factory that blows up if called at all, to prove
    validation happens before a connection is even opened, let alone before
    the command reaches create_process."""
    async def exploding_factory(*args, **kwargs):
        raise AssertionError("must not connect when an env key is invalid")

    executor = SSHExecutor(connect_factory=exploding_factory)

    with pytest.raises(ValueError, match="os; touch /tmp/x"):
        asyncio.run(executor.run(
            "10.0.0.9", b"fake-key-pem", "bash /tmp/install.sh",
            pinned_fingerprint=None, on_new_fingerprint=lambda fp: None,
            env={"os; touch /tmp/x": "1"},
        ))


def test_run_with_no_env_leaves_the_command_untouched():
    fake = FakeSSHConnection(host_key_fingerprint="SHA256:abc123", stdout_lines=[],
                             stderr_lines=[], exit_status=0)
    executor = SSHExecutor(connect_factory=make_fake_connect_factory(fake))

    asyncio.run(executor.run("10.0.0.9", b"k", "true", pinned_fingerprint=None,
                             on_new_fingerprint=lambda fp: None))

    assert fake.last_command == "true"


def test_run_rejects_a_changed_host_key():
    fake = FakeSSHConnection(host_key_fingerprint="SHA256:changed", stdout_lines=[],
                             stderr_lines=[], exit_status=0)
    executor = SSHExecutor(connect_factory=make_fake_connect_factory(fake))

    with pytest.raises(SSHHostKeyMismatch):
        asyncio.run(executor.run(
            "10.0.0.9", b"fake-key-pem", "true",
            pinned_fingerprint="SHA256:original", on_new_fingerprint=lambda fp: None,
        ))


def test_run_times_out_on_a_hanging_command():
    fake = FakeSSHConnection(host_key_fingerprint="SHA256:abc123", stdout_lines=[],
                             stderr_lines=[], exit_status=0, hang=True)
    executor = SSHExecutor(connect_factory=make_fake_connect_factory(fake))

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(executor.run(
            "10.0.0.9", b"fake-key-pem", "sleep 999",
            pinned_fingerprint=None, on_new_fingerprint=lambda fp: None, timeout_s=0.05,
        ))


class _AcceptAnyKeyServer(asyncssh.SSHServer):
    """Throwaway in-process server: accepts the one test client key so we
    can exercise the REAL default_connect_factory (not tests/fakes/ssh.py's
    hand-rolled reimplementation of the pin logic) end to end."""

    def __init__(self, client_pub):
        self._client_pub = client_pub

    def begin_auth(self, username):
        return True

    def public_key_auth_supported(self):
        return True

    def validate_public_key(self, username, key):
        return key == self._client_pub


def test_default_connect_factory_pins_then_accepts_then_rejects_changed_key():
    """Regression test for the bug a reviewer caught: known_hosts=None makes
    asyncssh skip validate_host_public_key entirely, silently disabling TOFU
    pinning. Runs against a real local asyncssh server/client pair, the
    fakes/ssh.py-based tests above never touch this code path."""

    async def scenario():
        host_key = asyncssh.generate_private_key("ssh-ed25519")
        client_key = asyncssh.generate_private_key("ssh-ed25519")
        client_pub = client_key.convert_to_public()
        client_pem = client_key.export_private_key()

        server = await asyncssh.create_server(
            lambda: _AcceptAnyKeyServer(client_pub), "127.0.0.1", 0,
            server_host_keys=[host_key],
        )
        try:
            port = server.sockets[0].getsockname()[1]

            # First connect: no pin yet -> TOFU captures the fingerprint.
            seen_fp: list[str] = []
            conn = await default_connect_factory(
                "127.0.0.1", client_pem, pinned_fingerprint=None,
                on_new_fingerprint=seen_fp.append, port=port,
            )
            conn.close()
            await conn.wait_closed()
            assert len(seen_fp) == 1 and seen_fp[0]

            # Second connect: same key pinned -> must succeed (this is the
            # case the known_hosts=None bug broke: it raised unconditionally).
            conn2 = await default_connect_factory(
                "127.0.0.1", client_pem, pinned_fingerprint=seen_fp[0],
                on_new_fingerprint=lambda fp: None, port=port,
            )
            conn2.close()
            await conn2.wait_closed()

            # Third connect: a different pinned fingerprint -> must reject.
            with pytest.raises(SSHHostKeyMismatch):
                await default_connect_factory(
                    "127.0.0.1", client_pem, pinned_fingerprint="SHA256:bogus",
                    on_new_fingerprint=lambda fp: None, port=port,
                )
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(scenario())


def test_get_ssh_private_key_decrypts_the_stored_credential(tmp_path):
    from proxploy.models import HostCredential
    from proxploy.secretstore import SecretStore

    db = make_db(tmp_path)
    host = seed_host_row(db)
    kf = tmp_path / "master.key"
    SecretStore.ensure_key_file(kf, db_file_exists=False)
    secretstore = SecretStore(kf)
    blob, ver = secretstore.encrypt(b"-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n")
    db.add(HostCredential(host_id=host.id, kind="ssh_key",
                          encrypted_blob=blob, key_version=ver))
    db.commit()

    assert get_ssh_private_key(db, secretstore, host.id) == \
        b"-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n"


def test_get_ssh_private_key_raises_when_no_credential(tmp_path):
    from proxploy.secretstore import SecretStore

    db = make_db(tmp_path)
    host = seed_host_row(db)
    kf = tmp_path / "master.key"
    SecretStore.ensure_key_file(kf, db_file_exists=False)
    secretstore = SecretStore(kf)

    with pytest.raises(LookupError):
        get_ssh_private_key(db, secretstore, host.id)


# --- normalize_ssh_host --------------------------------------------------

@pytest.mark.parametrize("address, expected", [
    ("https://10.0.0.5:8006", "10.0.0.5"),           # full URL with port
    ("https://10.0.0.5", "10.0.0.5"),                # full URL without port
    ("pve1.example.com", "pve1.example.com"),        # bare hostname
    ("10.0.0.5", "10.0.0.5"),                        # bare IP
    ("::1", "::1"),                                  # bare IPv6 literal, unbracketed
    ("https://[::1]:8006", "::1"),                   # full URL, bracketed IPv6
    ("[::1]", "::1"),                                # bare IPv6 literal, bracketed
])
def test_normalize_ssh_host(address, expected):
    assert normalize_ssh_host(address) == expected


# --- Host.address (a full URL) reaching SSH as a bare hostname -----------

def test_run_for_host_strips_scheme_and_port_from_the_stored_address(tmp_path):
    """Regression test: `Host.address` is stored as a full `https://host:port`
    URL (api/hosts.py), but every SSH call site used to hand that straight to
    asyncssh, which wants a bare hostname; `://` and the embedded port are
    not valid hostname characters, so this failed name resolution against any
    real node. `seed_host_row`'s default address is `https://10.0.0.9:8006`;
    the fake connect factory below is keyed by the bare hostname `10.0.0.9`
    only, so this raises KeyError before the fix (the full URL is looked up)
    and resolves after it (SSHExecutor.run normalizes before calling the
    connect factory)."""
    from proxploy.db import make_engine, make_sessionmaker, run_migrations
    from proxploy.config import Settings
    from proxploy.secretstore import SecretStore
    from proxploy.models import HostCredential

    s = Settings(db_url=f"sqlite:///{tmp_path}/t.db", data_dir=tmp_path,
                master_key_file=tmp_path / "master.key")
    run_migrations(s)
    sessionmaker = make_sessionmaker(make_engine(s))
    SecretStore.ensure_key_file(s.master_key_file, db_file_exists=False)
    secretstore = SecretStore(s.master_key_file)

    with sessionmaker() as db:
        host = seed_host_row(db)  # address == "https://10.0.0.9:8006"
        blob, ver = secretstore.encrypt(b"fake-key-pem")
        db.add(HostCredential(host_id=host.id, kind="ssh_key",
                              encrypted_blob=blob, key_version=ver))
        db.commit()
        host_id, host_address = host.id, host.address

    fake = FakeSSHConnection(host_key_fingerprint="SHA256:abc123", stdout_lines=[],
                             stderr_lines=[], exit_status=0)
    factory = make_addressed_connect_factory({"10.0.0.9": fake})
    executor = SSHExecutor(connect_factory=factory)

    status = asyncio.run(executor.run_for_host(
        sessionmaker, secretstore, host_id, host_address, "true",
        pinned_fingerprint=None, on_new_fingerprint=lambda fp: None))

    assert status == 0


def test_an_unreachable_host_fails_with_a_sentence_not_an_empty_string():
    """asyncssh's connect timeout raises a bare TimeoutError whose str() is "",
    and jobs/backend.py stores str(exc) as `jobs.error`. An unreachable node
    therefore produced a failed job with a completely blank reason: the
    operator saw "failed" and nothing else. Confirmed 2026-08-10 by pointing a
    real job at an unroutable address."""
    from proxploy.executor.ssh import SSHUnreachable

    async def boom(*_a, **_k):
        raise TimeoutError()          # str() == ""

    with pytest.raises(SSHUnreachable) as ei:
        asyncio.run(SSHExecutor(connect_factory=boom).run(
            "https://192.0.2.99:8006", b"pem", "hostname",
            pinned_fingerprint=None, on_new_fingerprint=lambda fp: None))

    msg = str(ei.value)
    assert msg.strip(), "still blank"
    assert "192.0.2.99" in msg          # names the host it could not reach
    assert "TimeoutError" in msg        # and what went wrong


def test_a_host_key_mismatch_is_not_reworded_as_unreachable():
    """SSHHostKeyMismatch already says exactly what happened, and it is a
    security signal: it must not be swallowed into a generic connect error."""
    from proxploy.executor.ssh import SSHHostKeyMismatch

    async def boom(*_a, **_k):
        raise SSHHostKeyMismatch("host key changed: pinned X, saw Y")

    with pytest.raises(SSHHostKeyMismatch):
        asyncio.run(SSHExecutor(connect_factory=boom).run(
            "10.0.0.9", b"pem", "hostname",
            pinned_fingerprint="SHA256:X", on_new_fingerprint=lambda fp: None))
