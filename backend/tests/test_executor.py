import asyncio
import pytest

from proxploy.executor import SSHExecutor
from proxploy.executor.ssh import SSHHostKeyMismatch
from tests.fakes.ssh import FakeSSHConnection, make_fake_connect_factory


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
