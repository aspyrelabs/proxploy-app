"""vzdump-archive transfer between two hosts that share neither a PVE
cluster nor a backup storage (doc 08 §4, Phase 8 Task 16). The two nodes
have no credentials for each other by design — that is the whole point of
this product — so the archive is streamed host -> Proxploy -> host, one SFTP
connection to each side, entirely inside this process.

This is the only module (besides executor/ssh.py, executor/keys.py) allowed
to import asyncssh — scripts/check_executor_isolation.py enforces the
boundary. services/migrate.py, which drives this from outside executor/,
must never see a private key: it calls `sftp_copy_for_hosts` with host ids
and a sessionmaker/secretstore instead.
"""
from __future__ import annotations

from collections.abc import Callable

from proxploy.executor.ssh import default_connect_factory

CHUNK_SIZE = 4 * 1024 * 1024  # 4 MiB


async def sftp_copy(connect_factory, *, src: dict, dst: dict,
                    src_path: str, dst_path: str,
                    on_progress: Callable[[int], None]) -> int:
    """Stream one file host -> host through this process, 4 MiB at a time.

    `src`/`dst` carry {"host", "private_key_pem", "pinned_fingerprint",
    "on_new_fingerprint"} — the same arguments executor/ssh.py's
    `default_connect_factory` takes. `on_progress(bytes_done)` fires after
    every chunk written. Returns the total number of bytes copied.
    """
    async with await connect_factory(
        src["host"], src["private_key_pem"],
        pinned_fingerprint=src["pinned_fingerprint"],
        on_new_fingerprint=src["on_new_fingerprint"],
    ) as src_conn:
        async with await connect_factory(
            dst["host"], dst["private_key_pem"],
            pinned_fingerprint=dst["pinned_fingerprint"],
            on_new_fingerprint=dst["on_new_fingerprint"],
        ) as dst_conn:
            src_sftp = await src_conn.start_sftp_client()
            dst_sftp = await dst_conn.start_sftp_client()
            total = 0
            async with src_sftp.open(src_path, "rb") as fsrc, \
                       dst_sftp.open(dst_path, "wb") as fdst:
                while True:
                    chunk = await fsrc.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    await fdst.write(chunk)
                    total += len(chunk)
                    on_progress(total)
            return total


async def sftp_copy_for_hosts(sessionmaker, secretstore, *,
                              src_host_id: int, src_host: str,
                              src_pinned_fingerprint: str | None,
                              src_on_new_fingerprint: Callable[[str], None],
                              dst_host_id: int, dst_host: str,
                              dst_pinned_fingerprint: str | None,
                              dst_on_new_fingerprint: Callable[[str], None],
                              src_path: str, dst_path: str,
                              on_progress: Callable[[int], None],
                              connect_factory=default_connect_factory) -> int:
    """Same contract as `sftp_copy`, but resolves both private keys from
    SecretStore itself, mirroring `executor/ssh.py::SSHExecutor.run_for_host`
    — so raw key bytes never have to leave this module. Callers outside
    executor/ pass a sessionmaker + host ids instead of key material.
    Raises LookupError if either host has no ssh_key credential.
    """
    from proxploy.executor.keys import get_ssh_private_key

    with sessionmaker() as db:
        src_key = get_ssh_private_key(db, secretstore, src_host_id)
        dst_key = get_ssh_private_key(db, secretstore, dst_host_id)
    return await sftp_copy(
        connect_factory,
        src={"host": src_host, "private_key_pem": src_key,
             "pinned_fingerprint": src_pinned_fingerprint,
             "on_new_fingerprint": src_on_new_fingerprint},
        dst={"host": dst_host, "private_key_pem": dst_key,
             "pinned_fingerprint": dst_pinned_fingerprint,
             "on_new_fingerprint": dst_on_new_fingerprint},
        src_path=src_path, dst_path=dst_path, on_progress=on_progress)
