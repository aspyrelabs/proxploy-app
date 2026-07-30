# Phase 4 (Store) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the App Store: a server-side-cached community-scripts/ProxmoxVE catalog, a mechanical install-feasibility classifier, an isolated asyncssh install executor, and the install/adopt/script-edit flows end to end (backend + frontend).

**Architecture:** A new `proxploy/executor/` package holds the only code allowed to touch asyncssh or the SSH private key (mechanically enforced by the existing `scripts/check_executor_isolation.py`). Catalog ingest reads `ct/*.sh` + `install/*.sh` pairs straight from the public `community-scripts/ProxmoxVE` GitHub repo (see "Catalog source" note below — this replaces the vaguer "community-scripts metadata" framing in doc 01 §3 with the concrete mechanism), classifies each pair with a pure function, and upserts into the already-schema-complete `catalog_entries` table. Install runs as a `JobBackend` handler (`app.install`), reusing Phase 3's job/SSE plumbing verbatim: SSH out via the executor, log lines in via `ctx.log`, pin the script into the already-schema-complete `app_scripts` table, create the `App` row on success.

**Tech Stack:** FastAPI + SQLAlchemy 2 + Alembic (existing), `asyncssh` (new dependency, EPL-2.0 — already covered by `ci.yml`'s license allow-list), `httpx` (existing, used for the GitHub raw-content fetch), React 19 + TanStack Query/Router (existing).

## Global Constraints

- Nothing outside `proxploy/executor/` may `import asyncssh` or reference the name `get_ssh_private_key` — mechanically enforced by `backend/scripts/check_executor_isolation.py`, already wired into CI (`ci.yml` job `backend`, step `python scripts/check_executor_isolation.py`, run from `backend/`).
- Every DB-touching test uses the existing sqlite-per-`tmp_path` conventions (`tests/support.py::make_db`/`make_app`/`make_job_app`, `tests/conftest.py::client`) — no new fixture infrastructure unless a task says so explicitly.
- Every job handler is `async def h(ctx: JobContext, params: dict) -> dict`, registered into `proxploy.jobs.HANDLERS` at **import time**, and that module must be imported from `main.py`'s `lifespan()` (mirrors `from proxploy.services import lifecycle  # noqa: F401`) or its handlers never run.
- All new backend routes live under `/api/v1` via `proxploy/api/__init__.py`'s `api_router.include_router(...)` — there is no auto-discovery.
- Frontend server state lives exclusively in TanStack Query (doc 06 §d) — no client store duplicates it.
- Root-shell/SSH is confirmed structurally necessary (`docs/notes/phase-4-spike.md`, doc 08 §4, doc 11 §1) — do not attempt to route around it via the Proxmox API.

**Catalog source — a correction to doc 01 §3's framing, discovered while grounding this plan in real code:** doc 01 §3 says catalog metadata is "community-scripts/ProxmoxVE metadata, fetched server-side only" as if there's a simple published JSON/API for it. There isn't one usable here: `community-scripts.org/docs/api/readme` confirms the website's catalog is PocketBase-backed content behind a Next.js frontend (`ProxmoxVE-Frontend`) with no public bulk-read endpoint — its only public `app/api/*` routes are narrow write-side actions (script requests, issue reports), and the telemetry service's `GET /api/scripts` is usage/ranking stats, not catalog metadata. What **is** public, stable, and already how this plan's classifier reads scripts anyway: the `ct/*.sh` files in `community-scripts/ProxmoxVE` itself declare `APP="<name>"` and `var_cpu`/`var_ram`/`var_disk`/`var_os`/`var_version`/`var_unprivileged` defaults directly (confirmed: `ct/immich.sh`, `ct/redis.sh`, `ct/postgresql.sh` all follow this shape), plus a `# Source: <url>` header comment for `website`. Task 3 below fetches and parses these directly via GitHub's raw-content + trees API — same source the classifier already needs to read, one fetch pass serves both. **Known v1 gap, called out rather than papered over:** `category`, `description`, `icon_url`, and `popularity` are not reliably derivable from script content alone; Task 3 ships a small hand-maintained `catalog_categories.py` slug→category map (defaulting unmapped slugs to `"Uncategorized"`) and leaves `description`/`icon_url`/`popularity` null/templated until a real source is found — this is an explicit, visible gap for review, not a silent placeholder.

---

## File Structure

**Backend, new files:**
- `proxploy/executor/__init__.py` — public surface: `SSHExecutor`, `default_connect_factory`, `get_ssh_private_key`
- `proxploy/executor/keys.py` — the one function allowed to decrypt the SSH private key
- `proxploy/executor/ssh.py` — `SSHExecutor` (asyncssh wrapper: closed stdin, host-key TOFU pinning, line-streaming, timeout)
- `proxploy/services/classifier.py` — pure function `classify_install_feasibility(ct_script, install_script) -> tuple[bool, str | None]`
- `proxploy/services/catalog.py` — GitHub fetch/parse/upsert (`refresh_catalog` job handler) + `catalog_categories.py`'s map
- `proxploy/services/catalog_categories.py` — the slug→category static map (small, hand-maintained)
- `proxploy/services/appstore.py` — `app.install` job handler (consent check, pin+diff, SSH run, App row creation)
- `proxploy/api/catalog.py` — `GET /catalog`, `GET /catalog/{slug}`, `POST /catalog/refresh`, `POST /catalog/{slug}/install`
- `proxploy/migrations/versions/<rev>_0003_ssh_host_key_pin.py` — adds `hosts.ssh_host_key_fingerprint`
- Backend test files: `tests/test_classifier.py`, `tests/fixtures/community_scripts/*.sh`, `tests/test_executor.py`, `tests/test_catalog_ingest.py`, `tests/test_catalog_api.py`, `tests/test_appstore_install.py`, `tests/test_apps_adopt.py`, `tests/test_app_script_api.py`, `tests/fakes/ssh.py` (fake asyncssh-shaped connection, mirrors `tests/fakes/pve.py`)

**Backend, modified files:**
- `proxploy/models/__init__.py` — add `Host.ssh_host_key_fingerprint`
- `proxploy/api/apps.py` — add `POST /apps/adopt`, `GET/PUT /apps/{id}/script`, `GET /apps/{id}/script/versions`
- `proxploy/api/__init__.py` — register `catalog.router`
- `proxploy/main.py` — import `proxploy.services.appstore` and `proxploy.services.catalog` for handler registration (mirrors the existing `lifecycle` import); add `ssh_factory` param to `create_app`
- `pyproject.toml` — add `asyncssh`

**Frontend, new files:**
- `frontend/src/api/catalog.ts` — types + hooks (`useCatalog`, `useCatalogEntry`, `useRefreshCatalog`, `useInstall`)
- `frontend/src/components/StoreCard.tsx`
- `frontend/src/components/BulkAdoptDialog.tsx`
- `frontend/src/components/InstallDialog.tsx`
- `frontend/src/routes/store.tsx` — `StorePage`, `storeRoute`, `installRoute` (modal route)
- `frontend/src/components/ScriptPanel.tsx` — CodePanel-backed script view/edit + diff
- Frontend test files: `frontend/src/tests/store.test.tsx`, `frontend/src/tests/adopt.test.tsx`, `frontend/src/tests/script.test.tsx`

**Frontend, modified files:**
- `frontend/src/router.tsx` — replace the `storeRoute` placeholder registration with the real one; wire `installRoute` as a child
- `frontend/src/routes/apps.tsx` — wire `BulkAdoptDialog` to the existing discovered-panel UI
- `frontend/src/routes/apps.tsx` (`appConfigRoute`) — replace the `phaseTab` placeholder with `ScriptPanel`

---

## Task 1: SSH executor core + host-key pinning

**Files:**
- Create: `backend/proxploy/executor/__init__.py`, `backend/proxploy/executor/keys.py`, `backend/proxploy/executor/ssh.py`
- Create: `backend/tests/fakes/ssh.py`, `backend/tests/test_executor.py`
- Create: `backend/proxploy/migrations/versions/<rev>_0003_ssh_host_key_pin.py`
- Modify: `backend/proxploy/models/__init__.py` (`Host.ssh_host_key_fingerprint`), `backend/pyproject.toml` (add `asyncssh>=2.14`), `backend/proxploy/main.py` (`ssh_factory` param), `backend/tests/support.py` (`make_app`/`make_job_app` gain an optional `ssh_factory` passthrough, mirroring the existing `fake`/`proxmox_factory` passthrough)

**Interfaces:**
- Produces: `SSHExecutor.__init__(connect_factory=default_connect_factory)`; `async SSHExecutor.run(host: str, private_key_pem: bytes, command: str, *, pinned_fingerprint: str | None, on_new_fingerprint: Callable[[str], None], env: dict[str, str] | None = None, on_line: Callable[[str, str], None] | None = None, timeout_s: float = 1800.0) -> int` (returns remote exit status; raises `SSHHostKeyMismatch` on a pin mismatch, `asyncio.TimeoutError` past `timeout_s`). `get_ssh_private_key(db, secretstore, host_id: int) -> bytes`.
- Consumes: `proxploy.secretstore.SecretStore.decrypt`, `proxploy.models.HostCredential`.

- [ ] **Step 1: Add the migration for host-key pinning**

```python
# backend/proxploy/migrations/versions/<generate with `alembic revision`>_0003_ssh_host_key_pin.py
"""0003 ssh host key pin

Revision ID: <generated>
Revises: a2c7f1e33fe7
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa

revision = "<generated>"
down_revision = "a2c7f1e33fe7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("hosts") as batch:
        batch.add_column(sa.Column("ssh_host_key_fingerprint", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("hosts") as batch:
        batch.drop_column("ssh_host_key_fingerprint")
```

Run `cd backend && alembic revision --autogenerate -m "0003 ssh host key pin"` first to get the real revision id, then hand-edit the body to match exactly the above (autogenerate may add unrelated noise from JSON/Text column comparisons — keep only the one column add).

- [ ] **Step 2: Add the model column**

In `backend/proxploy/models/__init__.py`, inside `class Host(TimestampMixin, Base):`, after `last_seen_at`:

```python
    ssh_host_key_fingerprint: Mapped[str | None] = mapped_column(Text)
```

- [ ] **Step 3: Write the failing executor test**

```python
# backend/tests/test_executor.py
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
```

```python
# backend/tests/fakes/ssh.py
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
                stderr_lines: list[str], exit_status: int, hang: bool = False):
        self.host_key_fingerprint = host_key_fingerprint
        self.stdout_lines = stdout_lines
        self.stderr_lines = stderr_lines
        self.exit_status = exit_status
        self.hang = hang
        self.stdin_closed: bool | None = None

    async def create_process(self, command, *, env=None, stdin=None):
        self.stdin_closed = stdin == "DEVNULL_SENTINEL"
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
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `cd backend && pytest tests/test_executor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'proxploy.executor'`

- [ ] **Step 5: Implement `proxploy/executor/keys.py`**

```python
"""The one place allowed to pull the SSH private key out of SecretStore
(doc 08 §4). scripts/check_executor_isolation.py fails the build if
`get_ssh_private_key` is referenced anywhere outside `executor/`."""
from proxploy.models import HostCredential


def get_ssh_private_key(db, secretstore, host_id: int) -> bytes:
    cred = (db.query(HostCredential)
            .filter_by(host_id=host_id, kind="ssh_key").one_or_none())
    if cred is None:
        raise LookupError(f"host {host_id} has no ssh_key credential")
    return secretstore.decrypt(cred.encrypted_blob)
```

- [ ] **Step 6: Implement `proxploy/executor/ssh.py`**

```python
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
from collections.abc import Callable

import asyncssh

CONNECT_TIMEOUT_S = 15.0


class SSHHostKeyMismatch(Exception):
    """The node's SSH host key does not match what was pinned at first
    connect (doc 08 §4: hard-fail, never auto-accept)."""


async def default_connect_factory(host: str, private_key_pem: bytes, *,
                                  pinned_fingerprint: str | None,
                                  on_new_fingerprint: Callable[[str], None]):
    key = asyncssh.import_private_key(private_key_pem)
    captured: dict[str, str] = {}

    class _PinningClient(asyncssh.SSHClient):
        def validate_host_public_key(self, host_, addr, port, key_) -> bool:
            fp = key_.get_fingerprint()
            captured["fingerprint"] = fp
            if pinned_fingerprint is None:
                return True
            return fp == pinned_fingerprint

    conn, _ = await asyncssh.create_connection(
        _PinningClient, host, username="root", client_keys=[key],
        known_hosts=None, connect_timeout=CONNECT_TIMEOUT_S,
    )
    if pinned_fingerprint is not None and captured.get("fingerprint") != pinned_fingerprint:
        conn.close()
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
        conn = await self._connect_factory(
            host, private_key_pem, pinned_fingerprint=pinned_fingerprint,
            on_new_fingerprint=on_new_fingerprint)
        async with conn:
            proc = await conn.create_process(command, env=env or {}, stdin=asyncssh.DEVNULL)

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
```

```python
# backend/proxploy/executor/__init__.py
from proxploy.executor.keys import get_ssh_private_key
from proxploy.executor.ssh import SSHExecutor, SSHHostKeyMismatch, default_connect_factory

__all__ = ["SSHExecutor", "SSHHostKeyMismatch", "default_connect_factory", "get_ssh_private_key"]
```

Update `tests/fakes/ssh.py`'s `create_process` stdin check to compare against `asyncssh.DEVNULL` instead of the placeholder `"DEVNULL_SENTINEL"` string once the real module exists — replace that line with `self.stdin_closed = stdin is not None`.

- [ ] **Step 7: Add `asyncssh` to `pyproject.toml`**

In `backend/pyproject.toml`'s `dependencies` list, add `"asyncssh>=2.14",` alphabetically near `apprise`. Run `cd backend && pip install -e .` to pick it up in the venv.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `cd backend && pytest tests/test_executor.py -v`
Expected: 3 passed

- [ ] **Step 9: Confirm executor isolation still holds against the real new code**

Run: `cd backend && python scripts/check_executor_isolation.py`
Expected: `executor isolation: OK` — `asyncssh` and `get_ssh_private_key` only appear under `proxploy/executor/`.

Run: `cd backend && pytest tests/test_isolation_lint.py -v`
Expected: 2 passed (this is the CI-enforced mechanism from doc 08 §4 / the user's acceptance criterion — it now runs against real `executor/` content instead of a no-op tree).

- [ ] **Step 10: Wire an `ssh_factory` test seam into `create_app`/`make_app`/`make_job_app`**

In `backend/proxploy/main.py`, add `ssh_factory=None` to `create_app`'s signature and, in `lifespan()` right after `app.state.secretstore = SecretStore(...)`, add:

```python
        from proxploy.executor.ssh import default_connect_factory
        app.state.ssh_connect_factory = ssh_factory or default_connect_factory
```

In `backend/tests/support.py`, add `ssh_factory=None` to `make_app(...)` and `make_job_app(...)` signatures, passing it straight through to `create_app(...)` / setting `state.ssh_connect_factory = ssh_factory` respectively (mirror exactly how `fake`/`proxmox_factory` is already threaded through both functions).

- [ ] **Step 11: Commit**

```bash
cd backend && git add proxploy/executor/ proxploy/models/__init__.py proxploy/main.py \
  proxploy/migrations/versions/*_0003_ssh_host_key_pin.py pyproject.toml \
  tests/fakes/ssh.py tests/test_executor.py tests/support.py
git commit -m "feat(executor): asyncssh runner with closed stdin + host-key TOFU pinning"
```

---

## Task 2: Install-feasibility classifier

**Files:**
- Create: `backend/proxploy/services/classifier.py`
- Create: `backend/tests/test_classifier.py`
- Create: `backend/tests/fixtures/community_scripts/{redis,postgresql,docker,jellyfin-hwaccel}/{ct.sh,install.sh}`

**Interfaces:**
- Produces: `classify_install_feasibility(ct_script: str, install_script: str) -> tuple[bool, str | None]` — `(installable, unsupported_reason)`.
- Consumes: nothing (pure function over script text).

- [ ] **Step 1: Vendor the real fixture scripts**

These are trimmed, verbatim excerpts of real upstream files (MIT-licensed, `community-scripts/ProxmoxVE`), used only as static classifier test input — not executed.

`backend/tests/fixtures/community_scripts/redis/ct.sh` (fully silent, single-CT — expect `installable=True`):
```bash
#!/usr/bin/env bash
source <(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/misc/build.func)
# Copyright (c) 2021-2026 tteck
# Author: tteck (tteckster)
# License: MIT | https://github.com/community-scripts/ProxmoxVE/raw/main/LICENSE
# Source: https://redis.io/

APP="Redis"
var_tags="${var_tags:-database}"
var_cpu="${var_cpu:-1}"
var_ram="${var_ram:-1024}"
var_disk="${var_disk:-4}"
var_os="${var_os:-debian}"
var_version="${var_version:-13}"
var_arm64="${var_arm64:-yes}"
var_unprivileged="${var_unprivileged:-1}"

header_info "$APP"
variables
color
catch_errors

start
build_container
description
```

`backend/tests/fixtures/community_scripts/redis/install.sh`:
```bash
#!/usr/bin/env bash

# Copyright (c) 2021-2026 tteck
# Author: tteck (tteckster)
# License: MIT | https://github.com/community-scripts/ProxmoxVE/raw/main/LICENSE
# Source: https://redis.io/

source /dev/stdin <<<"$FUNCTIONS_FILE_PATH"
color
verb_ip6
catch_errors
setting_up_container
network_check
update_os

msg_info "Installing Dependencies"
$STD apt install -y apt-transport-https
msg_ok "Installed Dependencies"

msg_info "Setting up Redis"
$STD apt install -y redis
sed -i 's/^bind .*/bind 0.0.0.0/' /etc/redis/redis.conf
systemctl enable -q --now redis-server
msg_ok "Setup Redis"

motd_ssh
customize
cleanup_lxc
```

`backend/tests/fixtures/community_scripts/postgresql/ct.sh` (single-CT, but the install script prompts — expect `installable=False`):
```bash
#!/usr/bin/env bash
source <(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/misc/build.func)
# Copyright (c) 2021-2026 tteck
# Author: tteck (tteckster)
# License: MIT | https://github.com/community-scripts/ProxmoxVE/raw/main/LICENSE
# Source: https://www.postgresql.org/

APP="PostgreSQL"
var_tags="${var_tags:-database}"
var_cpu="${var_cpu:-1}"
var_ram="${var_ram:-1024}"
var_disk="${var_disk:-4}"
var_os="${var_os:-debian}"
var_version="${var_version:-13}"
var_arm64="${var_arm64:-yes}"
var_unprivileged="${var_unprivileged:-1}"

header_info "$APP"
variables
color
catch_errors

start
build_container
description
```

`backend/tests/fixtures/community_scripts/postgresql/install.sh` (real, unconditional `read`, no default — this is the exact script the spike found aborts with `exit 64` on empty input):
```bash
#!/usr/bin/env bash

source /dev/stdin <<<"$FUNCTIONS_FILE_PATH"
color
verb_ip6
catch_errors
setting_up_container
network_check
update_os

read -r -p "${TAB3}Enter PostgreSQL version (15/16/17/18): " ver
[[ $ver =~ ^(15|16|17|18)$ ]] || {
  echo "Invalid version"
  exit 64
}
PG_VERSION=$ver setup_postgresql
```

`backend/tests/fixtures/community_scripts/docker/ct.sh` (header only, single-CT):
```bash
#!/usr/bin/env bash
source <(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/misc/build.func)
# Copyright (c) 2021-2026 tteck
# Author: tteck (tteckster)
# License: MIT | https://github.com/community-scripts/ProxmoxVE/raw/main/LICENSE
# Source: https://www.docker.com/

APP="Docker"
var_tags="${var_tags:-docker}"
var_cpu="${var_cpu:-2}"
var_ram="${var_ram:-2048}"
var_disk="${var_disk:-4}"
var_os="${var_os:-debian}"
var_version="${var_version:-13}"
var_arm64="${var_arm64:-yes}"
var_unprivileged="${var_unprivileged:-1}"

start
build_container
description
```

`backend/tests/fixtures/community_scripts/docker/install.sh` (real, three unconditional prompts, no override):
```bash
#!/usr/bin/env bash

source /dev/stdin <<<"$FUNCTIONS_FILE_PATH"
color
verb_ip6
catch_errors
setting_up_container
network_check
update_os

read -r -p "${TAB3}Would you like to add Portainer (UI)? <y/N> " prompt
if [[ ${prompt,,} =~ ^(y|yes)$ ]]; then
  DOCKER_PORTAINER="true" setup_docker
else
  setup_docker
  read -r -p "${TAB3}Would you like to install the Portainer Agent (for remote management)? <y/N> " prompt_agent
fi

read -r -p "${TAB3}Expose Docker TCP socket (insecure) ? [n = No, l = Local only (127.0.0.1), a = All interfaces (0.0.0.0)] <n/l/a>: " socket_choice
```

`backend/tests/fixtures/community_scripts/jellyfin-hwaccel/ct.sh` (single-CT):
```bash
#!/usr/bin/env bash
source <(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/misc/build.func)
APP="Jellyfin"
var_cpu="${var_cpu:-2}"
var_ram="${var_ram:-2048}"
var_disk="${var_disk:-6}"
var_os="${var_os:-debian}"
var_version="${var_version:-13}"

start
build_container
description
```

`backend/tests/fixtures/community_scripts/jellyfin-hwaccel/install.sh` (trimmed excerpt of the real GPU-passthrough prompt from `misc/tools.func`'s `setup_hwaccel`, reproduced here inline since the real prompt lives in a shared library file, not the app's own install script — this is the "guarded, still installable" case: env-var pre-check present):
```bash
#!/usr/bin/env bash

source /dev/stdin <<<"$FUNCTIONS_FILE_PATH"
color
verb_ip6
catch_errors
setting_up_container
network_check
update_os

msg_info "Installing Jellyfin"
$STD apt install -y jellyfin
msg_ok "Installed Jellyfin"

if [[ "$nvidia_selected" == "yes" ]]; then
  if [[ -n "${INSTALL_NVIDIA_DRIVERS:-}" ]]; then
    install_nvidia_drivers="${INSTALL_NVIDIA_DRIVERS}"
  else
    read -r -t 60 -p "${TAB3}Install NVIDIA driver libraries in the container? [Y/n] (auto-yes in 60s): " nvidia_reply || nvidia_reply=""
    case "${nvidia_reply,,}" in
    n | no) install_nvidia_drivers="no" ;;
    *) install_nvidia_drivers="yes" ;;
    esac
  fi
fi

motd_ssh
customize
cleanup_lxc
```

- [ ] **Step 2: Write the failing classifier test**

```python
# backend/tests/test_classifier.py
from pathlib import Path

from proxploy.services.classifier import classify_install_feasibility

FIXTURES = Path(__file__).parent / "fixtures" / "community_scripts"


def _load(name: str) -> tuple[str, str]:
    d = FIXTURES / name
    return (d / "ct.sh").read_text(), (d / "install.sh").read_text()


def test_fully_silent_script_is_installable():
    ct, install = _load("redis")
    installable, reason = classify_install_feasibility(ct, install)
    assert (installable, reason) == (True, None)


def test_unconditional_prompt_with_no_default_is_unsupported():
    ct, install = _load("postgresql")
    installable, reason = classify_install_feasibility(ct, install)
    assert installable is False
    assert reason == "install script requires interactive input, no non-interactive entrypoint"


def test_multiple_unconditional_prompts_are_unsupported():
    ct, install = _load("docker")
    installable, reason = classify_install_feasibility(ct, install)
    assert installable is False
    assert reason == "install script requires interactive input, no non-interactive entrypoint"


def test_env_var_guarded_prompt_is_still_installable():
    ct, install = _load("jellyfin-hwaccel")
    installable, reason = classify_install_feasibility(ct, install)
    assert (installable, reason) == (True, None)


def test_multi_ct_pattern_is_unsupported():
    ct = "build_container\nbuild_container\n"
    installable, reason = classify_install_feasibility(ct, "")
    assert installable is False
    assert reason == "multi-CT / docker-compose pattern"


def test_missing_build_container_call_is_unsupported():
    installable, reason = classify_install_feasibility("# no build_container here", "")
    assert installable is False
    assert reason == "multi-CT / docker-compose pattern"
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd backend && pytest tests/test_classifier.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'proxploy.services.classifier'`

- [ ] **Step 4: Implement the classifier**

```python
# backend/proxploy/services/classifier.py
"""Install-feasibility classifier (doc 01 §3, doc 04 `catalog_entries`,
docs/notes/phase-4-spike.md). Mechanical, not a guess: every
community-scripts install script runs under `catch_errors()`'s
`set -Ee -o pipefail` + `trap ERR` (misc/error_handler.func), so a bare
`read`/`whiptail`/`dialog` prompt returns a non-zero exit on EOF and
hard-aborts the whole install rather than defaulting — confirmed
empirically in the spike, not assumed. A prompt only counts as safe if it's
guarded: either an env-var short-circuit within a few lines above it, or
the read itself falls back via `||` (the jellyfin/plex hwaccel pattern)."""
from __future__ import annotations

import re

BUILD_CONTAINER_RE = re.compile(r"^\s*build_container\b", re.MULTILINE)
PROMPT_RE = re.compile(r"\bread\b[^\n]*-[a-zA-Z]*p\b|\bwhiptail\b|\bdialog\b")
GUARD_RE = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*:-|-[nz]\s+\"\$\{")

UNSUPPORTED_MULTI_CT = "multi-CT / docker-compose pattern"
UNSUPPORTED_INTERACTIVE = "install script requires interactive input, no non-interactive entrypoint"


def classify_install_feasibility(ct_script: str, install_script: str) -> tuple[bool, str | None]:
    if len(BUILD_CONTAINER_RE.findall(ct_script)) != 1:
        return False, UNSUPPORTED_MULTI_CT

    lines = install_script.splitlines()
    for i, line in enumerate(lines):
        if not PROMPT_RE.search(line):
            continue
        if "||" in line:  # e.g. `read ... || nvidia_reply=""`
            continue
        preceding = "\n".join(lines[max(0, i - 3):i])
        if GUARD_RE.search(preceding):
            continue
        return False, UNSUPPORTED_INTERACTIVE

    return True, None
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && pytest tests/test_classifier.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
cd backend && git add proxploy/services/classifier.py tests/test_classifier.py tests/fixtures/community_scripts/
git commit -m "feat(catalog): mechanical install-feasibility classifier over real script samples"
```

---

## Task 3: CatalogSource ingest (GitHub fetch + parse + classify + upsert)

**Files:**
- Create: `backend/proxploy/services/catalog.py`, `backend/proxploy/services/catalog_categories.py`
- Create: `backend/tests/test_catalog_ingest.py`
- Modify: `backend/proxploy/main.py` (import `catalog` module for handler registration)

**Interfaces:**
- Produces: `HANDLERS["catalog.refresh"]` job handler; `parse_ct_script(content: str) -> dict` (slug/name/website/resource defaults); `refresh_catalog(ctx, params) -> dict` (job entrypoint).
- Consumes: `proxploy.services.classifier.classify_install_feasibility`, `httpx` (already a dependency), `proxploy.jobs.HANDLERS`/`JobContext`/`JobFailed`, `proxploy.models.CatalogEntry`.

- [ ] **Step 1: Write the category map**

```python
# backend/proxploy/services/catalog_categories.py
"""Hand-maintained slug -> category map (doc 06 store category chips).
Known v1 gap (docs/notes/phase-4-spike.md / this plan's header note):
community-scripts has no public bulk metadata API to source this from
automatically. Unmapped slugs fall back to "Uncategorized" rather than a
guess. Extend this map as real gaps are noticed in the store UI."""
CATEGORY_MAP = {
    "postgresql": "Databases", "mysql": "Databases", "mariadb": "Databases",
    "mongodb": "Databases", "redis": "Databases",
    "jellyfin": "Media", "plex": "Media", "immich": "Media",
    "homeassistant": "Home & Auto", "homebridge": "Home & Auto", "zigbee2mqtt": "Home & Auto",
    "grafana": "Monitoring", "prometheus": "Monitoring", "uptimekuma": "Monitoring",
    "gitea": "Dev", "n8n": "Dev",
    "pihole": "Network", "adguard": "Network", "nginxproxymanager": "Network", "wireguard": "Network",
    "paperless-ngx": "Files", "vaultwarden": "Security",
    "docker": "Docker", "proxmox-backup-server": "Files",
}


def category_for(slug: str) -> str:
    return CATEGORY_MAP.get(slug, "Uncategorized")
```

- [ ] **Step 2: Write the failing ingest test**

```python
# backend/tests/test_catalog_ingest.py
import httpx
import pytest

from proxploy.models import CatalogEntry
from proxploy.services.catalog import parse_ct_script, run_ingest
from tests.support import make_db

REDIS_CT = '''#!/usr/bin/env bash
source <(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/misc/build.func)
# Source: https://redis.io/

APP="Redis"
var_tags="${var_tags:-database}"
var_cpu="${var_cpu:-1}"
var_ram="${var_ram:-1024}"
var_disk="${var_disk:-4}"
var_os="${var_os:-debian}"
var_version="${var_version:-13}"

start
build_container
description
'''
REDIS_INSTALL = 'msg_info "Setting up Redis"\n$STD apt install -y redis\n'


def test_parse_ct_script_extracts_metadata():
    meta = parse_ct_script(REDIS_CT)
    assert meta == {
        "name": "Redis", "website": "https://redis.io/",
        "default_cpu": 1, "default_ram_mb": 1024, "default_disk_gb": 4,
        "default_os": "debian", "default_os_version": "13",
    }


def test_run_ingest_upserts_a_classified_entry(tmp_path, monkeypatch):
    db = make_db(tmp_path)

    def fake_get(url, **kw):
        if url.endswith("/main/ct/redis.sh"):
            return httpx.Response(200, text=REDIS_CT, headers={"ETag": '"abc123"'})
        if url.endswith("/main/install/redis-install.sh"):
            return httpx.Response(200, text=REDIS_INSTALL)
        return httpx.Response(404)

    monkeypatch.setattr("proxploy.services.catalog._fetch", fake_get)

    run_ingest(db, slugs=["redis"])

    row = db.query(CatalogEntry).filter_by(slug="redis").one()
    assert row.name == "Redis"
    assert row.category == "Databases"
    assert row.installable is True
    assert row.unsupported_reason is None
    assert row.default_cpu == 1 and row.default_ram_mb == 1024
    assert row.upstream_sha == "abc123"


def test_run_ingest_is_idempotent_on_unchanged_etag(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    calls = {"n": 0}

    def fake_get(url, **kw):
        calls["n"] += 1
        if url.endswith("/main/ct/redis.sh"):
            return httpx.Response(200, text=REDIS_CT, headers={"ETag": '"abc123"'})
        if url.endswith("/main/install/redis-install.sh"):
            return httpx.Response(200, text=REDIS_INSTALL)
        return httpx.Response(404)

    monkeypatch.setattr("proxploy.services.catalog._fetch", fake_get)
    run_ingest(db, slugs=["redis"])
    first_synced_at = db.query(CatalogEntry).filter_by(slug="redis").one().synced_at

    run_ingest(db, slugs=["redis"])
    row = db.query(CatalogEntry).filter_by(slug="redis").one()
    assert row.synced_at == first_synced_at  # unchanged ETag -> no re-write
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd backend && pytest tests/test_catalog_ingest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'proxploy.services.catalog'`

- [ ] **Step 4: Implement `proxploy/services/catalog.py`**

```python
"""CatalogSource: fetch community-scripts/ProxmoxVE ct/+install script pairs
directly from GitHub raw content (see this plan's header note on why —
there is no public bulk metadata API), parse resource defaults, classify
feasibility, upsert into `catalog_entries`."""
from __future__ import annotations

import re

import httpx

from proxploy.jobs import HANDLERS, JobContext, JobFailed
from proxploy.models import CatalogEntry
from proxploy.services.catalog_categories import category_for
from proxploy.services.classifier import classify_install_feasibility

RAW_BASE = "https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main"

APP_RE = re.compile(r'^APP="([^"]+)"', re.MULTILINE)
SOURCE_RE = re.compile(r"^#\s*Source:\s*(\S+)", re.MULTILINE)
VAR_RE = {
    "default_cpu": re.compile(r'var_cpu="\$\{var_cpu:-(\d+)\}"'),
    "default_ram_mb": re.compile(r'var_ram="\$\{var_ram:-(\d+)\}"'),
    "default_disk_gb": re.compile(r'var_disk="\$\{var_disk:-(\d+)\}"'),
    "default_os": re.compile(r'var_os="\$\{var_os:-([a-z0-9]+)\}"'),
    "default_os_version": re.compile(r'var_version="\$\{var_version:-([\w.]+)\}"'),
}


def _fetch(url: str, **kw) -> httpx.Response:
    return httpx.get(url, timeout=15.0, **kw)


def parse_ct_script(content: str) -> dict:
    meta: dict = {}
    if m := APP_RE.search(content):
        meta["name"] = m.group(1)
    if m := SOURCE_RE.search(content):
        meta["website"] = m.group(1)
    for field, pattern in VAR_RE.items():
        if m := pattern.search(content):
            meta[field] = int(m.group(1)) if field != "default_os" and field != "default_os_version" else m.group(1)
    return meta


def _ingest_one(db, slug: str) -> None:
    ct_resp = _fetch(f"{RAW_BASE}/ct/{slug}.sh")
    if ct_resp.status_code != 200:
        raise JobFailed(f"{slug}: ct script fetch failed ({ct_resp.status_code})")
    install_resp = _fetch(f"{RAW_BASE}/install/{slug}-install.sh")
    if install_resp.status_code != 200:
        raise JobFailed(f"{slug}: install script fetch failed ({install_resp.status_code})")

    etag = (ct_resp.headers.get("ETag") or "").strip('"')
    row = db.query(CatalogEntry).filter_by(slug=slug).one_or_none()
    if row is not None and etag and row.upstream_sha == etag:
        return  # unchanged since last sync

    meta = parse_ct_script(ct_resp.text)
    installable, reason = classify_install_feasibility(ct_resp.text, install_resp.text)

    from datetime import datetime, timezone
    if row is None:
        row = CatalogEntry(slug=slug)
        db.add(row)
    row.name = meta.get("name", slug)
    row.category = category_for(slug)
    row.website = meta.get("website")
    row.script_path = f"ct/{slug}.sh"
    row.default_cpu = meta.get("default_cpu")
    row.default_ram_mb = meta.get("default_ram_mb")
    row.default_disk_gb = meta.get("default_disk_gb")
    row.default_os = meta.get("default_os")
    row.default_os_version = meta.get("default_os_version")
    row.installable = installable
    row.unsupported_reason = reason
    row.upstream_sha = etag or None
    row.raw = {"ct_script": ct_resp.text, "install_script": install_resp.text}
    row.synced_at = datetime.now(timezone.utc)
    db.commit()


def run_ingest(db, slugs: list[str]) -> dict:
    n = 0
    for slug in slugs:
        _ingest_one(db, slug)
        n += 1
    return {"synced": n}


async def refresh_catalog(ctx: JobContext, params: dict) -> dict:
    app = ctx.backend.app
    slugs = params.get("slugs") or list(app.state.settings.catalog_slugs)
    ctx.log(f"refreshing {len(slugs)} catalog entries")
    import asyncio
    with app.state.sessionmaker() as db:
        result = await asyncio.to_thread(run_ingest, db, slugs)
    ctx.progress(100)
    return result


HANDLERS["catalog.refresh"] = refresh_catalog
```

Note: `app.state.settings.catalog_slugs` doesn't exist on `Settings` yet — Task 4's route wiring adds a `catalog_slugs: list[str] = []` field to `Settings` (a small, explicit seed list of known-good slugs to sync; growing this list over time is a deliberate, reviewable product decision, not an unbounded live-scrape of the whole 572-script repo on day one).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && pytest tests/test_catalog_ingest.py -v`
Expected: 3 passed

- [ ] **Step 6: Register the handler module from `main.py`**

In `backend/proxploy/main.py`'s `lifespan()`, next to the existing `from proxploy.services import lifecycle  # noqa: F401`, add:

```python
        from proxploy.services import catalog as _catalog  # noqa: F401 — registers catalog.refresh
```

- [ ] **Step 7: Commit**

```bash
cd backend && git add proxploy/services/catalog.py proxploy/services/catalog_categories.py \
  tests/test_catalog_ingest.py proxploy/main.py
git commit -m "feat(catalog): GitHub-sourced ingest job, classify + upsert catalog_entries"
```

---

## Task 4: Catalog API routes + `Settings.catalog_slugs`

**Files:**
- Create: `backend/proxploy/api/catalog.py`, `backend/tests/test_catalog_api.py`
- Modify: `backend/proxploy/api/__init__.py`, `backend/proxploy/config.py`

**Interfaces:**
- Produces: `GET /api/v1/catalog`, `GET /api/v1/catalog/{slug}`, `POST /api/v1/catalog/refresh`.
- Consumes: `proxploy.api.deps.get_db`/`require_role`/`require_entitlement`, `proxploy.jobs.JobBackend.enqueue`.

- [ ] **Step 1: Add `catalog_slugs` to `Settings`**

In `backend/proxploy/config.py`'s `Settings` class, after `ent_extra_keys_file`:

```python
    catalog_slugs: list[str] = [
        "redis", "postgresql", "mysql", "mariadb", "mongodb",
        "jellyfin", "plex", "immich", "homeassistant", "homebridge", "zigbee2mqtt",
        "grafana", "prometheus", "uptimekuma", "gitea", "n8n",
        "pihole", "adguard", "nginxproxymanager", "wireguard",
        "docker", "paperless-ngx", "vaultwarden", "proxmox-backup-server",
    ]
```

(The same 24-app cross-category sample from `docs/notes/phase-4-spike.md` — a deliberately small, known-good seed list; growing it is a follow-up, not blocked on this plan.)

- [ ] **Step 2: Write the failing API test**

```python
# backend/tests/test_catalog_api.py
from proxploy.models import CatalogEntry
from tests.conftest import client  # noqa: F401 fixture
from tests.support import make_db


def _seed_entry(db, **overrides):
    row = CatalogEntry(slug="redis", name="Redis", category="Databases",
                       installable=True, unsupported_reason=None, **overrides)
    db.add(row)
    db.commit()
    return row


def test_list_catalog_requires_auth(client):
    r = client.get("/api/v1/catalog")
    assert r.status_code == 401


def test_list_and_get_catalog_entry(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_entry(db)
    r = client.get("/api/v1/catalog")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1 and body[0]["slug"] == "redis"

    r = client.get("/api/v1/catalog/redis")
    assert r.status_code == 200 and r.json()["name"] == "Redis"

    r = client.get("/api/v1/catalog/does-not-exist")
    assert r.status_code == 404


def test_category_and_query_filters(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_entry(db)
        db.add(CatalogEntry(slug="grafana", name="Grafana", category="Monitoring", installable=True))
        db.commit()
    assert len(client.get("/api/v1/catalog?category=Monitoring").json()) == 1
    assert len(client.get("/api/v1/catalog?q=redis").json()) == 1
    assert len(client.get("/api/v1/catalog?q=nomatch").json()) == 0


def test_refresh_enqueues_a_job(client, csrf_header, bootstrap_admin, monkeypatch):
    bootstrap_admin(client)
    r = client.post("/api/v1/catalog/refresh", headers=csrf_header(client))
    assert r.status_code == 202
    job = r.json()["job"]
    assert job["kind"] == "catalog.refresh"
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd backend && pytest tests/test_catalog_api.py -v`
Expected: FAIL — 404s on undefined routes

- [ ] **Step 4: Implement `proxploy/api/catalog.py`**

```python
from fastapi import APIRouter, Depends, HTTPException

from proxploy.api.deps import get_db, require_entitlement, require_role
from proxploy.models import CatalogEntry

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("")
def list_catalog(category: str | None = None, q: str | None = None,
                 db=Depends(get_db), _=Depends(require_role("viewer"))):
    query = db.query(CatalogEntry)
    if category:
        query = query.filter(CatalogEntry.category == category)
    if q:
        query = query.filter(CatalogEntry.name.ilike(f"%{q}%"))
    return [_serialize(r) for r in query.order_by(CatalogEntry.name).all()]


@router.get("/{slug}")
def get_catalog_entry(slug: str, db=Depends(get_db), _=Depends(require_role("viewer"))):
    row = db.query(CatalogEntry).filter_by(slug=slug).one_or_none()
    if row is None:
        raise HTTPException(404, "not found")
    return _serialize(row) | {"raw": row.raw}


@router.post("/refresh", status_code=202)
def refresh_catalog(request, db=Depends(get_db), _=Depends(require_role("admin"))):
    job = request.app.state.jobs.enqueue(db, kind="catalog.refresh")
    return {"job": _job_out(job)}


def _serialize(r: CatalogEntry) -> dict:
    return {
        "slug": r.slug, "name": r.name, "category": r.category,
        "description": r.description, "icon_url": r.icon_url,
        "popularity": r.popularity, "website": r.website,
        "default_cpu": r.default_cpu, "default_ram_mb": r.default_ram_mb,
        "default_disk_gb": r.default_disk_gb, "default_os": r.default_os,
        "default_os_version": r.default_os_version,
        "installable": r.installable, "unsupported_reason": r.unsupported_reason,
        "synced_at": r.synced_at.isoformat() if r.synced_at else None,
    }


def _job_out(job) -> dict:
    return {"id": job.id, "kind": job.kind, "status": job.status}
```

`refresh_catalog`'s `request: Request` parameter needs adding explicitly (`from fastapi import Request`) — match the exact parameter-ordering convention used in `proxploy/api/hosts.py`'s `POST /hosts` (read that function's signature before writing this one, so `Depends()` ordering matches house style).

- [ ] **Step 5: Register the router**

In `backend/proxploy/api/__init__.py`, add `catalog` to the import tuple and add `api_router.include_router(catalog.router)` after `api_router.include_router(apps.router)`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && pytest tests/test_catalog_api.py -v`
Expected: 6 passed

- [ ] **Step 7: Commit**

```bash
cd backend && git add proxploy/api/catalog.py proxploy/api/__init__.py \
  proxploy/config.py tests/test_catalog_api.py
git commit -m "feat(catalog): GET /catalog, GET /catalog/{slug}, POST /catalog/refresh"
```

---

## Task 5: Install job handler (`app.install`)

**Files:**
- Create: `backend/proxploy/services/appstore.py`, `backend/tests/test_appstore_install.py`
- Modify: `backend/proxploy/main.py` (register `appstore` handler module)

**Interfaces:**
- Produces: `HANDLERS["app.install"]`; `run_install(ctx, params) -> dict` where `params = {"catalog_slug": str, "host_id": int, "name": str, "ctid": int, "overrides": dict}`.
- Consumes: `proxploy.executor.SSHExecutor`/`get_ssh_private_key`, `proxploy.services.catalog_categories`, `proxploy.models.{CatalogEntry, Host, HostCredential, App, AppScript}`.

- [ ] **Step 1: Write the failing install-job test**

```python
# backend/tests/test_appstore_install.py
import asyncio
import hashlib

import pytest

from proxploy.jobs import JobContext, JobFailed
from proxploy.models import App, AppScript, CatalogEntry
from proxploy.services.appstore import run_install
from tests.fakes.ssh import FakeSSHConnection, make_fake_connect_factory
from tests.support import make_job_app, seed_host_row


def _seed_catalog(db, installable=True):
    db.add(CatalogEntry(slug="redis", name="Redis", category="Databases",
                        installable=installable,
                        unsupported_reason=None if installable else "install script requires interactive input, no non-interactive entrypoint",
                        default_cpu=1, default_ram_mb=1024, default_disk_gb=4,
                        default_os="debian", default_os_version="13",
                        raw={"ct_script": "...", "install_script": "msg_ok done"}))
    db.commit()


def test_install_pins_script_and_creates_app_row(tmp_path):
    async def scenario():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            host = seed_host_row(db)
            from proxploy.models import HostCredential
            sblob, sver = app.state.secretstore.encrypt(b"-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----")
            db.add(HostCredential(host_id=host.id, kind="ssh_key", encrypted_blob=sblob,
                                  key_version=sver, public_meta="ssh-ed25519 AAAA fake"))
            _seed_catalog(db)
            db.commit()
            host_id = host.id

        fake = FakeSSHConnection(host_key_fingerprint="SHA256:abc", stdout_lines=["Setup Redis"],
                                 stderr_lines=[], exit_status=0)
        app.state.ssh_connect_factory = make_fake_connect_factory(fake)

        from proxploy.jobs import JobBackend
        backend = JobBackend(app)
        ctx = JobContext(backend, job_id=1)
        result = await run_install(ctx, {"catalog_slug": "redis", "host_id": host_id,
                                         "name": "Redis", "ctid": 150, "overrides": {}})

        with app.state.sessionmaker() as db:
            row = db.query(App).filter_by(slug=result["slug"]).one()
            assert row.catalog_slug == "redis" and row.ctid == 150 and row.host_id == host_id
            script = db.query(AppScript).filter_by(app_id=row.id, version=1).one()
            assert script.source == "upstream"
            assert script.content_sha256 == hashlib.sha256(b"msg_ok done").hexdigest()

    asyncio.run(scenario())


def test_install_refuses_an_unsupported_catalog_entry(tmp_path):
    async def scenario():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            host = seed_host_row(db)
            _seed_catalog(db, installable=False)
            db.commit()
            host_id = host.id

        from proxploy.jobs import JobBackend
        backend = JobBackend(app)
        ctx = JobContext(backend, job_id=1)
        with pytest.raises(JobFailed, match="not installable"):
            await run_install(ctx, {"catalog_slug": "redis", "host_id": host_id,
                                    "name": "Redis", "ctid": 150, "overrides": {}})

    asyncio.run(scenario())


def test_install_fails_without_an_enrolled_ssh_key(tmp_path):
    async def scenario():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            host = seed_host_row(db)
            _seed_catalog(db)
            db.commit()
            host_id = host.id

        from proxploy.jobs import JobBackend
        backend = JobBackend(app)
        ctx = JobContext(backend, job_id=1)
        with pytest.raises(JobFailed, match="ssh_key"):
            await run_install(ctx, {"catalog_slug": "redis", "host_id": host_id,
                                    "name": "Redis", "ctid": 150, "overrides": {}})

    asyncio.run(scenario())
```

`JobContext`'s real constructor signature must be confirmed against `backend/proxploy/jobs/backend.py` before writing this test verbatim (the plan's Task 3 research pass read it but didn't quote the exact `__init__` — confirm `JobContext(backend, job_id=...)` matches, adjusting the test call if the real signature differs).

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/test_appstore_install.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'proxploy.services.appstore'`

- [ ] **Step 3: Implement `proxploy/services/appstore.py`**

```python
"""App Store install job handler (doc 10 Phase 4 DoD: pin + diff + consent +
stream + archive). Mirrors services/lifecycle.py's shape: blocking _resolve
helper in a thread, ctx.log/ctx.progress narration, JobFailed for expected
errors, module-bottom HANDLERS registration."""
from __future__ import annotations

import hashlib

from proxploy.executor import SSHExecutor, get_ssh_private_key
from proxploy.jobs import HANDLERS, JobContext, JobFailed
from proxploy.models import App, AppScript, CatalogEntry, Host, HostCredential


def _resolve(app, catalog_slug: str, host_id: int):
    """Blocking: (catalog row, host, private key pem). Runs in a thread."""
    with app.state.sessionmaker() as db:
        entry = db.query(CatalogEntry).filter_by(slug=catalog_slug).one_or_none()
        if entry is None:
            raise JobFailed(f"catalog entry {catalog_slug} not found")
        if not entry.installable:
            raise JobFailed(f"{catalog_slug} is not installable: {entry.unsupported_reason}")
        host = db.get(Host, host_id)
        if host is None:
            raise JobFailed(f"host {host_id} not found")
        try:
            private_pem = get_ssh_private_key(db, app.state.secretstore, host_id)
        except LookupError as e:
            raise JobFailed(str(e)) from e
        install_script = (entry.raw or {}).get("install_script", "")
        return entry, host, private_pem, install_script


async def run_install(ctx: JobContext, params: dict) -> dict:
    import asyncio
    app = ctx.backend.app
    catalog_slug = params["catalog_slug"]
    host_id = int(params["host_id"])
    ctid = int(params["ctid"])
    name = params["name"]
    overrides = params.get("overrides") or {}

    entry, host, private_pem, install_script = await asyncio.to_thread(
        _resolve, app, catalog_slug, host_id)

    ctx.log(f"installing {catalog_slug} on {host.name} as CT {ctid}")
    env = {"MODE": "default", "PHS_SILENT": "1"}
    for key, val in overrides.items():
        env[f"var_{key}"] = str(val)

    executor = SSHExecutor(connect_factory=app.state.ssh_connect_factory)

    def on_new_fingerprint(fp: str) -> None:
        with app.state.sessionmaker() as db:
            h = db.get(Host, host_id)
            h.ssh_host_key_fingerprint = fp
            db.commit()

    command = f"bash -c \"$(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/{entry.script_path})\""
    status = await executor.run(
        host.address, private_pem, command,
        pinned_fingerprint=host.ssh_host_key_fingerprint,
        on_new_fingerprint=on_new_fingerprint, env=env,
        on_line=lambda stream, line: ctx.log(line, stream=stream),
    )
    if status != 0:
        raise JobFailed(f"install script exited {status}")
    ctx.progress(80)

    slug = f"{catalog_slug}-{ctid}"
    with app.state.sessionmaker() as db:
        row = App(host_id=host_id, ctid=ctid, name=name, slug=slug,
                  catalog_slug=catalog_slug, category=entry.category,
                  web_protocol="http", web_path="/", adopted=True)
        db.add(row)
        db.flush()
        db.add(AppScript(app_id=row.id, version=1, content=install_script,
                         content_sha256=hashlib.sha256(install_script.encode()).hexdigest(),
                         source="upstream", upstream_ref=entry.upstream_sha))
        db.commit()
        app_id, out_slug = row.id, row.slug

    ctx.progress(100)
    app.state.bus.publish("resource", {"type": "app", "id": app_id, "change": "installed"})
    return {"app_id": app_id, "slug": out_slug}


HANDLERS["app.install"] = run_install
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && pytest tests/test_appstore_install.py -v`
Expected: 3 passed

- [ ] **Step 5: Register the handler module from `main.py`**

Add `from proxploy.services import appstore as _appstore  # noqa: F401 — registers app.install` next to the `catalog` import from Task 3.

- [ ] **Step 6: Commit**

```bash
cd backend && git add proxploy/services/appstore.py tests/test_appstore_install.py proxploy/main.py
git commit -m "feat(appstore): app.install job — pin script, SSH install, create App row"
```

---

## Task 6: `POST /catalog/{slug}/install` route + root-consent gate

**Files:**
- Modify: `backend/proxploy/api/catalog.py`
- Create: `backend/tests/test_catalog_install_api.py`

**Interfaces:**
- Produces: `POST /api/v1/catalog/{slug}/install` (202, body `{host_id, name, ctid, overrides, consent}`).
- Consumes: `proxploy.api.hosts.CONSENT_NOTE`-style pattern (reuse the existing consent-gate shape from `hosts.py`, don't invent a new one).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_catalog_install_api.py
from proxploy.models import CatalogEntry, HostCredential


def test_install_requires_consent(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        db.add(CatalogEntry(slug="redis", name="Redis", installable=True))
        db.commit()
    from tests.support import seed_host_row
    with client.app.state.sessionmaker() as db:
        host = seed_host_row(db)
        host_id = host.id

    r = client.post("/api/v1/catalog/redis/install",
                    json={"host_id": host_id, "name": "Redis", "ctid": 150, "consent": False},
                    headers=csrf_header(client))
    assert r.status_code == 400


def test_install_enqueues_an_app_install_job(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        db.add(CatalogEntry(slug="redis", name="Redis", installable=True))
        db.commit()
    from tests.support import seed_host_row
    with client.app.state.sessionmaker() as db:
        host = seed_host_row(db)
        db.add(HostCredential(host_id=host.id, kind="ssh_key",
                              encrypted_blob=b"x", key_version=1, public_meta="ssh-ed25519 AAAA"))
        db.commit()
        host_id = host.id

    r = client.post("/api/v1/catalog/redis/install",
                    json={"host_id": host_id, "name": "Redis", "ctid": 150, "consent": True},
                    headers=csrf_header(client))
    assert r.status_code == 202
    assert r.json()["job"]["kind"] == "app.install"


def test_install_refuses_a_host_without_an_enrolled_ssh_key(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        db.add(CatalogEntry(slug="redis", name="Redis", installable=True))
        db.commit()
    from tests.support import seed_host_row
    with client.app.state.sessionmaker() as db:
        host = seed_host_row(db)
        host_id = host.id

    r = client.post("/api/v1/catalog/redis/install",
                    json={"host_id": host_id, "name": "Redis", "ctid": 150, "consent": True},
                    headers=csrf_header(client))
    assert r.status_code == 400
    assert "ssh_key" in r.json()["detail"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/test_catalog_install_api.py -v`
Expected: FAIL — 404 (route doesn't exist)

- [ ] **Step 3: Add the route**

In `backend/proxploy/api/catalog.py`:

```python
from pydantic import BaseModel

from proxploy.models import HostCredential


class InstallIn(BaseModel):
    host_id: int
    name: str
    ctid: int
    overrides: dict = {}
    consent: bool = False


@router.post("/{slug}/install", status_code=202)
def install_catalog_entry(slug: str, body: InstallIn, request,
                          db=Depends(get_db), _=Depends(require_role("admin")),
                          __=Depends(require_entitlement("store.install"))):
    if not body.consent:
        raise HTTPException(400, "root-consent required: this installs and runs a "
                                 "community-scripts.org script as root on the node")
    cred = (db.query(HostCredential)
            .filter_by(host_id=body.host_id, kind="ssh_key").one_or_none())
    if cred is None:
        raise HTTPException(400, "host has no enrolled ssh_key credential")
    entry = db.query(CatalogEntry).filter_by(slug=slug).one_or_none()
    if entry is None:
        raise HTTPException(404, "not found")
    if not entry.installable:
        raise HTTPException(400, f"not installable: {entry.unsupported_reason}")
    job = request.app.state.jobs.enqueue(
        db, kind="app.install",
        params={"catalog_slug": slug, "host_id": body.host_id, "name": body.name,
               "ctid": body.ctid, "overrides": body.overrides})
    return {"job": _job_out(job)}
```

Add `request: Request` import/parameter matching `hosts.py`'s ordering, as in Task 4.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && pytest tests/test_catalog_install_api.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
cd backend && git add proxploy/api/catalog.py tests/test_catalog_install_api.py
git commit -m "feat(catalog): POST /catalog/{slug}/install with root-consent + ssh-key gates"
```

---

## Task 7: `POST /apps/adopt` (bulk adoption)

**Files:**
- Modify: `backend/proxploy/api/apps.py`
- Create: `backend/tests/test_apps_adopt.py`

**Interfaces:**
- Produces: `POST /api/v1/apps/adopt` (body `{items: [{host_id, ctid, name, catalog_slug}]}` → `{adopted: [app_id, ...]}`).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_apps_adopt.py
from proxploy.models import App
from tests.support import seed_host_row


def test_adopt_creates_app_rows_for_each_item(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        host = seed_host_row(db)
        host_id = host.id

    r = client.post("/api/v1/apps/adopt", json={"items": [
        {"host_id": host_id, "ctid": 150, "name": "Immich", "catalog_slug": "immich"},
        {"host_id": host_id, "ctid": 151, "name": "Unknown CT", "catalog_slug": None},
    ]}, headers=csrf_header(client))
    assert r.status_code == 200
    body = r.json()
    assert len(body["adopted"]) == 2

    with client.app.state.sessionmaker() as db:
        rows = db.query(App).filter_by(host_id=host_id).all()
        assert {r.ctid for r in rows} == {150, 151}
        assert all(r.adopted for r in rows)


def test_adopt_rejects_a_ctid_already_adopted_on_that_host(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        host = seed_host_row(db)
        host_id = host.id
    client.post("/api/v1/apps/adopt", json={"items": [
        {"host_id": host_id, "ctid": 150, "name": "Immich", "catalog_slug": None}]},
        headers=csrf_header(client))

    r = client.post("/api/v1/apps/adopt", json={"items": [
        {"host_id": host_id, "ctid": 150, "name": "Immich again", "catalog_slug": None}]},
        headers=csrf_header(client))
    assert r.status_code == 409
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/test_apps_adopt.py -v`
Expected: FAIL — 404

- [ ] **Step 3: Add the route to `apps.py`**

Read `backend/proxploy/api/apps.py`'s existing `GET /apps/discovered` handler first to match its exact slug-generation/response conventions, then add:

```python
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError


class AdoptItem(BaseModel):
    host_id: int
    ctid: int
    name: str
    catalog_slug: str | None = None


class AdoptIn(BaseModel):
    items: list[AdoptItem]


@router.post("/adopt")
def adopt_apps(body: AdoptIn, db=Depends(get_db), _=Depends(require_role("admin"))):
    adopted = []
    for item in body.items:
        slug = f"{item.catalog_slug or 'adopted'}-{item.host_id}-{item.ctid}"
        row = App(host_id=item.host_id, ctid=item.ctid, name=item.name, slug=slug,
                  catalog_slug=item.catalog_slug, web_protocol="http", web_path="/",
                  adopted=True)
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, f"CT {item.ctid} on host {item.host_id} is already adopted")
        adopted.append(row.id)
    db.commit()
    return {"adopted": adopted}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && pytest tests/test_apps_adopt.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
cd backend && git add proxploy/api/apps.py tests/test_apps_adopt.py
git commit -m "feat(apps): POST /apps/adopt bulk-adopts discovered containers"
```

---

## Task 8: Script view/edit + version history routes

**Files:**
- Modify: `backend/proxploy/api/apps.py`
- Create: `backend/tests/test_app_script_api.py`

**Interfaces:**
- Produces: `GET /api/v1/apps/{id}/script` (`{content, version, source, diff_vs_upstream}` — `diff_vs_upstream` is a unified diff string, or `null` if the pinned content matches the app's `catalog_slug`'s current `catalog_entries.raw.install_script` exactly), `PUT /api/v1/apps/{id}/script` (new version row), `GET /api/v1/apps/{id}/script/versions`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_app_script_api.py
from proxploy.models import App, AppScript
from tests.support import seed_host_row


def _seed_app_with_script(db, content="msg_ok done\n"):
    host = seed_host_row(db)
    app = App(host_id=host.id, ctid=150, name="Redis", slug="redis-1",
              catalog_slug="redis", web_protocol="http", web_path="/", adopted=True)
    db.add(app)
    db.flush()
    import hashlib
    db.add(AppScript(app_id=app.id, version=1, content=content,
                     content_sha256=hashlib.sha256(content.encode()).hexdigest(),
                     source="upstream", upstream_ref="abc123"))
    db.commit()
    return app


def test_get_script_returns_latest_version(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        app = _seed_app_with_script(db)
        app_id = app.id

    r = client.get(f"/api/v1/apps/{app_id}/script")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == 1 and body["content"] == "msg_ok done\n"


def test_put_script_creates_a_new_version(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        app = _seed_app_with_script(db)
        app_id = app.id

    r = client.put(f"/api/v1/apps/{app_id}/script", json={"content": "msg_ok edited\n"},
                   headers=csrf_header(client))
    assert r.status_code == 200
    assert r.json()["version"] == 2

    r = client.get(f"/api/v1/apps/{app_id}/script/versions")
    assert [v["version"] for v in r.json()] == [2, 1]


def test_edited_script_shows_source_edited(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        app = _seed_app_with_script(db)
        app_id = app.id
    client.put(f"/api/v1/apps/{app_id}/script", json={"content": "msg_ok edited\n"},
              headers=csrf_header(client))
    r = client.get(f"/api/v1/apps/{app_id}/script")
    assert r.json()["source"] == "edited"


def test_script_matching_current_upstream_has_no_diff(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        app = _seed_app_with_script(db, content="msg_ok done\n")
        from proxploy.models import CatalogEntry
        db.add(CatalogEntry(slug="redis", name="Redis", installable=True,
                            raw={"install_script": "msg_ok done\n"}))
        db.commit()
        app_id = app.id

    r = client.get(f"/api/v1/apps/{app_id}/script")
    assert r.json()["diff_vs_upstream"] is None


def test_edited_script_shows_a_real_diff_against_current_upstream(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        app = _seed_app_with_script(db, content="msg_ok done\n")
        from proxploy.models import CatalogEntry
        db.add(CatalogEntry(slug="redis", name="Redis", installable=True,
                            raw={"install_script": "msg_ok done\n"}))
        db.commit()
        app_id = app.id

    client.put(f"/api/v1/apps/{app_id}/script", json={"content": "msg_ok edited\n"},
              headers=csrf_header(client))
    r = client.get(f"/api/v1/apps/{app_id}/script")
    diff = r.json()["diff_vs_upstream"]
    assert diff is not None
    assert "-msg_ok done" in diff and "+msg_ok edited" in diff


def test_upstream_moving_on_after_pin_also_surfaces_a_diff(client, csrf_header, bootstrap_admin):
    """Not just locally-edited scripts drift from upstream — a catalog refresh
    that picks up a new upstream version must surface that too, even though
    this app's own pinned content never changed (doc 10 DoD: "diffed against
    upstream before every run", not just "diffed against local edits")."""
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        app = _seed_app_with_script(db, content="msg_ok done\n")
        from proxploy.models import CatalogEntry
        db.add(CatalogEntry(slug="redis", name="Redis", installable=True,
                            raw={"install_script": "msg_ok done v2\n"}))
        db.commit()
        app_id = app.id

    r = client.get(f"/api/v1/apps/{app_id}/script")
    diff = r.json()["diff_vs_upstream"]
    assert diff is not None and "+msg_ok done v2" in diff
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/test_app_script_api.py -v`
Expected: FAIL — 404

- [ ] **Step 3: Add the routes to `apps.py`**

```python
import difflib
import hashlib

from proxploy.models import AppScript, CatalogEntry


def _diff_vs_upstream(db, app_row, pinned_content: str) -> str | None:
    if not app_row.catalog_slug:
        return None
    entry = db.query(CatalogEntry).filter_by(slug=app_row.catalog_slug).one_or_none()
    if entry is None or not entry.raw:
        return None
    upstream = entry.raw.get("install_script")
    if upstream is None or upstream == pinned_content:
        return None
    diff = difflib.unified_diff(
        upstream.splitlines(keepends=True), pinned_content.splitlines(keepends=True),
        fromfile="upstream", tofile="pinned")
    return "".join(diff)


@router.get("/{app_id}/script")
def get_app_script(app_id: int, db=Depends(get_db), _=Depends(require_role("operator"))):
    latest = (db.query(AppScript).filter_by(app_id=app_id)
             .order_by(AppScript.version.desc()).first())
    if latest is None:
        raise HTTPException(404, "no pinned script for this app")
    app_row = db.get(App, app_id)
    return {"version": latest.version, "content": latest.content, "source": latest.source,
           "diff_vs_upstream": _diff_vs_upstream(db, app_row, latest.content)}


@router.put("/{app_id}/script")
def put_app_script(app_id: int, body: dict, db=Depends(get_db),
                   user=Depends(require_role("admin"))):
    content = body["content"]
    latest = (db.query(AppScript).filter_by(app_id=app_id)
             .order_by(AppScript.version.desc()).first())
    next_version = (latest.version + 1) if latest else 1
    row = AppScript(app_id=app_id, version=next_version, content=content,
                    content_sha256=hashlib.sha256(content.encode()).hexdigest(),
                    source="edited", created_by=user.id)
    db.add(row)
    db.commit()
    return {"version": row.version, "content": row.content, "source": row.source}


@router.get("/{app_id}/script/versions")
def list_app_script_versions(app_id: int, db=Depends(get_db), _=Depends(require_role("operator"))):
    rows = (db.query(AppScript).filter_by(app_id=app_id)
           .order_by(AppScript.version.desc()).all())
    return [{"version": r.version, "source": r.source, "created_at": r.created_at.isoformat()}
           for r in rows]
```

`require_role("admin")`'s injected `user` object's exact shape (does it expose `.id`?) must be confirmed against an existing admin-gated route in `apps.py`/`hosts.py` before finalizing — match whatever the existing convention is (e.g. `deps.py`'s `require_role` may return a `User` ORM row or a lighter session-derived object; use the same pattern `POST /hosts` already uses for `requested_by`-style fields).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && pytest tests/test_app_script_api.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
cd backend && git add proxploy/api/apps.py tests/test_app_script_api.py
git commit -m "feat(apps): script view/edit/version-history + diff-vs-upstream over app_scripts"
```

---

## Task 9: Frontend catalog types + hooks

**Files:**
- Create: `frontend/src/api/catalog.ts`
- Create: `frontend/src/tests/store.test.tsx` (hook portion only; component tests land in Task 11)

**Interfaces:**
- Produces: `CatalogRow` type, `useCatalog(category, q)`, `useCatalogEntry(slug)`, `useRefreshCatalog()`, `useInstall()`.

- [ ] **Step 1: Write the failing hook test**

```tsx
// frontend/src/tests/store.test.tsx (hook section)
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useCatalog } from '../api/catalog'

vi.mock('../api/client', () => ({ api: vi.fn() }))

describe('useCatalog', () => {
  it('fetches with category/q query params', async () => {
    const { api } = await import('../api/client')
    vi.mocked(api).mockResolvedValue([{ slug: 'redis', name: 'Redis' }])
    const qc = new QueryClient()
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>

    const { result } = renderHook(() => useCatalog('Databases', 'redis'), { wrapper })
    await waitFor(() => expect(result.current.data).toBeDefined())
    expect(api).toHaveBeenCalledWith('/catalog?category=Databases&q=redis')
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/tests/store.test.tsx`
Expected: FAIL — no `../api/catalog` module

- [ ] **Step 3: Implement `frontend/src/api/catalog.ts`**

```typescript
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export type CatalogRow = {
  slug: string; name: string | null; category: string | null
  description: string | null; icon_url: string | null; popularity: number | null
  website: string | null
  default_cpu: number | null; default_ram_mb: number | null; default_disk_gb: number | null
  default_os: string | null; default_os_version: string | null
  installable: boolean; unsupported_reason: string | null
  synced_at: string | null
}

export type CatalogEntryDetail = CatalogRow & { raw: { ct_script: string; install_script: string } | null }

export function useCatalog(category?: string, q?: string) {
  return useQuery({
    queryKey: ['catalog', category, q],
    staleTime: 5 * 60_000,
    queryFn: () => {
      const p = new URLSearchParams()
      if (category) p.set('category', category)
      if (q) p.set('q', q)
      const qs = p.toString()
      return api<CatalogRow[]>(qs ? `/catalog?${qs}` : '/catalog')
    },
  })
}

export function useCatalogEntry(slug: string | null) {
  return useQuery({
    queryKey: ['catalog', slug],
    enabled: slug != null,
    queryFn: () => api<CatalogEntryDetail>(`/catalog/${slug}`),
  })
}

export function useRefreshCatalog() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api<{ job: { id: number; kind: string } }>('/catalog/refresh', { method: 'POST' }),
    onSettled: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
  })
}

export type InstallVars = {
  slug: string; host_id: number; name: string; ctid: number
  overrides: Record<string, string | number>; consent: boolean
}

export function useInstall() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: InstallVars) =>
      api<{ job: { id: number; kind: string } }>(`/catalog/${v.slug}/install`, {
        method: 'POST',
        body: JSON.stringify({ host_id: v.host_id, name: v.name, ctid: v.ctid,
                              overrides: v.overrides, consent: v.consent }),
      }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['catalog'] })
    },
  })
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/tests/store.test.tsx`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
cd frontend && git add src/api/catalog.ts src/tests/store.test.tsx
git commit -m "feat(store): catalog types + useCatalog/useCatalogEntry/useInstall hooks"
```

---

## Task 10: `StoreCard` component

**Files:**
- Create: `frontend/src/components/StoreCard.tsx`
- Modify: `frontend/src/tests/store.test.tsx` (add component section)

**Interfaces:**
- Produces: `<StoreCard entry={CatalogRow} onInstall={(slug) => void} installed={boolean} />`.
- Consumes: `CatalogRow` from Task 9.

- [ ] **Step 1: Write the failing component test**

```tsx
// append to frontend/src/tests/store.test.tsx
import { fireEvent, render, screen } from '@testing-library/react'
import { StoreCard } from '../components/StoreCard'
import type { CatalogRow } from '../api/catalog'

const REDIS: CatalogRow = {
  slug: 'redis', name: 'Redis', category: 'Databases', description: null,
  icon_url: null, popularity: 42, website: 'https://redis.io/',
  default_cpu: 1, default_ram_mb: 1024, default_disk_gb: 4,
  default_os: 'debian', default_os_version: '13',
  installable: true, unsupported_reason: null, synced_at: null,
}

describe('StoreCard', () => {
  it('renders an Install button for an installable entry and fires onInstall', () => {
    const onInstall = vi.fn()
    render(<StoreCard entry={REDIS} onInstall={onInstall} installed={false} />)
    fireEvent.click(screen.getByRole('button', { name: 'Install' }))
    expect(onInstall).toHaveBeenCalledWith('redis')
  })

  it('shows a disabled Installed state', () => {
    render(<StoreCard entry={REDIS} onInstall={vi.fn()} installed />)
    expect(screen.getByRole('button', { name: 'Installed' })).toBeDisabled()
  })

  it('shows an honest note + upstream link for an unsupported entry, no Install control', () => {
    const unsupported = { ...REDIS, installable: false,
      unsupported_reason: 'install script requires interactive input, no non-interactive entrypoint' }
    render(<StoreCard entry={unsupported} onInstall={vi.fn()} installed={false} />)
    expect(screen.queryByRole('button', { name: 'Install' })).toBeNull()
    expect(screen.getByText(/Not installable/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /upstream/i })).toHaveAttribute('href', 'https://redis.io/')
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/tests/store.test.tsx`
Expected: FAIL — no `StoreCard` module

- [ ] **Step 3: Implement `frontend/src/components/StoreCard.tsx`**

```tsx
import type { CatalogRow } from '../api/catalog'
import { Button } from './ui/button'

export function StoreCard({ entry, onInstall, installed }: {
  entry: CatalogRow; onInstall: (slug: string) => void; installed: boolean
}) {
  return (
    <div className="rounded-card border border-line-soft bg-panel p-4">
      <div className="flex items-start justify-between">
        <div
          className="flex h-10 w-10 items-center justify-center rounded-tile font-display text-[14px] font-semibold text-white"
          style={{ background: 'linear-gradient(135deg,#F5B544,#E0862B)' }}
        >
          {(entry.name ?? entry.slug).slice(0, 2).toUpperCase()}
        </div>
        {entry.popularity != null && (
          <span className="font-mono text-[11px] text-text-3">★ {entry.popularity}</span>
        )}
      </div>
      <div className="mt-2 text-[14px] font-semibold text-text">{entry.name ?? entry.slug}</div>
      <div className="font-mono text-[11px] text-text-3">{entry.category ?? 'Uncategorized'}</div>
      <div className="mt-1 min-h-[34px] text-[12px] text-text-2">
        {entry.description ?? ''}
      </div>
      <span className="mt-2 inline-block rounded bg-panel-2 px-1.5 py-0.5 font-mono text-[10px] uppercase text-text-3">
        LXC
      </span>
      <div className="mt-3 border-t border-line-soft pt-3">
        {!entry.installable ? (
          <div className="text-[12px] text-text-3">
            Not installable — {entry.unsupported_reason}
            {entry.website && (
              <>
                {' '}
                <a href={entry.website} target="_blank" rel="noreferrer"
                  className="text-amber hover:underline">upstream</a>
              </>
            )}
          </div>
        ) : installed ? (
          <Button variant="ghost" disabled>Installed</Button>
        ) : (
          <Button variant="primary" onClick={() => onInstall(entry.slug)}>Install</Button>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/tests/store.test.tsx`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
cd frontend && git add src/components/StoreCard.tsx src/tests/store.test.tsx
git commit -m "feat(store): StoreCard — install/installed/unsupported states"
```

---

## Task 11: `/store` route (tile grid, category chips, header)

**Files:**
- Modify: `frontend/src/router.tsx`
- Create: `frontend/src/routes/store.tsx`
- Modify: `frontend/src/tests/store.test.tsx` (add page section)

**Interfaces:**
- Produces: `StorePage`, `storeRoute` (replaces the placeholder registration).
- Consumes: `useCatalog`, `StoreCard`.

- [ ] **Step 1: Write the failing page test**

```tsx
// append to frontend/src/tests/store.test.tsx
import { StorePage } from '../routes/store'

vi.mock('../api/catalog', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/catalog')>()
  return { ...actual, useCatalog: vi.fn() }
})

describe('StorePage', () => {
  it('shows the true installable/unsupported counts in the header', async () => {
    const { useCatalog } = await import('../api/catalog')
    vi.mocked(useCatalog).mockReturnValue({
      data: [
        { ...REDIS, installable: true },
        { ...REDIS, slug: 'docker', installable: false, unsupported_reason: 'x' },
      ],
    } as any)
    render(<StorePage />)
    expect(screen.getByText(/showing 2 of 1 installable/i)).toBeInTheDocument()
    expect(screen.getByText(/1 unsupported/i)).toBeInTheDocument()
  })

  it('filters by category chip', async () => {
    const { useCatalog } = await import('../api/catalog')
    const mocked = vi.mocked(useCatalog)
    mocked.mockReturnValue({ data: [REDIS] } as any)
    render(<StorePage />)
    fireEvent.click(screen.getByRole('button', { name: 'Databases' }))
    expect(mocked).toHaveBeenLastCalledWith('Databases', undefined)
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/tests/store.test.tsx`
Expected: FAIL — no `routes/store` module

- [ ] **Step 3: Implement `frontend/src/routes/store.tsx`**

```tsx
import { createRoute, useNavigate, useSearch } from '@tanstack/react-router'
import { useState } from 'react'
import { useCatalog, useRefreshCatalog } from '../api/catalog'
import { StoreCard } from '../components/StoreCard'
import { EmptyState } from '../components/EmptyState'
import { Button } from '../components/ui/button'
import { shellRoute } from './shell'

const CATEGORIES = ['All', 'Media', 'Home & Auto', 'Files', 'Network', 'Monitoring',
                    'Databases', 'Security', 'Dev', 'Docker', 'Productivity']

export function StorePage() {
  const search = useSearch({ strict: false }) as { category?: string; q?: string }
  const navigate = useNavigate()
  const [installing, setInstalling] = useState<string | null>(null)
  const category = search.category && search.category !== 'All' ? search.category : undefined
  const { data: entries } = useCatalog(category, search.q)
  const refresh = useRefreshCatalog()

  const installableCount = (entries ?? []).filter((e) => e.installable).length
  const unsupportedCount = (entries ?? []).length - installableCount

  const setSearch = (patch: Partial<{ category?: string; q?: string }>) =>
    navigate({ to: '/store' as never, search: { ...search, ...patch } as never, replace: true })

  return (
    <div>
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h1 className="font-display text-[22px] font-semibold">App Store</h1>
          <div className="text-[12px] text-text-3">
            Sourced from community-scripts/ProxmoxVE · showing {entries?.length ?? 0} of{' '}
            {installableCount} installable scripts ({unsupportedCount} unsupported)
          </div>
        </div>
        <Button variant="ghost" onClick={() => refresh.mutate()} disabled={refresh.isPending}>
          Refresh
        </Button>
      </div>

      <div className="mb-4 flex flex-wrap gap-2">
        {CATEGORIES.map((c) => (
          <button
            key={c}
            className={`rounded-full px-3 py-1 text-[12px] ${
              (search.category ?? 'All') === c ? 'bg-elev text-text' : 'text-text-2 hover:bg-panel-2'}`}
            onClick={() => setSearch({ category: c })}
          >
            {c}
          </button>
        ))}
      </div>

      {entries && entries.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {entries.map((e) => (
            <StoreCard key={e.slug} entry={e} installed={false}
              onInstall={(slug) => setInstalling(slug)} />
          ))}
        </div>
      ) : (
        <EmptyState title="No store entries match your filter." note="" />
      )}

      {installing && (
        <InstallDialog slug={installing} onClose={() => setInstalling(null)} />
      )}
    </div>
  )
}

// InstallDialog is implemented in Task 12; imported here once that file exists.
import { InstallDialog } from '../components/InstallDialog'

export const storeRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/store',
  validateSearch: (s: Record<string, unknown>) => ({
    category: typeof s.category === 'string' ? s.category : undefined,
    q: typeof s.q === 'string' && s.q ? s.q : undefined,
  }),
  component: StorePage,
})
```

- [ ] **Step 4: Replace the placeholder registration in `router.tsx`**

Remove these two lines from `frontend/src/router.tsx`:
```typescript
export const storeRoute = page('/store', 'App Store', 'Phase 4 (Store)',
  'The community-scripts catalog is fetched and cached server-side, never from the browser.')
```
Add `import { storeRoute } from './routes/store'` alongside the other route imports (next to `appsRoute` etc.), keeping `storeRoute` in the `shellRoute.addChildren([...])` list unchanged (it's already referenced there by name).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/tests/store.test.tsx`
Expected: 6 passed (this task's 2 + Task 9/10's 5, minus the `InstallDialog` import which will fail until Task 12 — stub `frontend/src/components/InstallDialog.tsx` with a minimal placeholder returning `null` for now so this task's own tests pass in isolation, then Task 12 replaces it)

```tsx
// frontend/src/components/InstallDialog.tsx — temporary stub, replaced in Task 12
export function InstallDialog(_: { slug: string; onClose: () => void }) { return null }
```

- [ ] **Step 6: Commit**

```bash
cd frontend && git add src/routes/store.tsx src/router.tsx src/components/InstallDialog.tsx src/tests/store.test.tsx
git commit -m "feat(store): /store route — tile grid, category chips, true installable count"
```

---

## Task 12: Install dialog (host select, overrides, root-consent, job stream)

**Files:**
- Modify: `frontend/src/components/InstallDialog.tsx` (replace Task 11's stub)
- Create: `frontend/src/tests/install.test.tsx`

**Interfaces:**
- Produces: `<InstallDialog slug={string} onClose={() => void} />`.
- Consumes: `useCatalogEntry`, `useInstall` (Task 9), `JobLog` (existing, Phase 3), a `hosts` list query (existing pattern from `routes/apps.tsx`).

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/tests/install.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { InstallDialog } from '../components/InstallDialog'

vi.mock('../api/client', () => ({ api: vi.fn() }))

function renderDialog() {
  const qc = new QueryClient()
  return render(
    <QueryClientProvider client={qc}>
      <InstallDialog slug="redis" onClose={vi.fn()} />
    </QueryClientProvider>,
  )
}

describe('InstallDialog', () => {
  it('disables Install until consent is checked, then submits with consent:true', async () => {
    const { api } = await import('../api/client')
    vi.mocked(api).mockImplementation((path: string) => {
      if (path === '/catalog/redis') return Promise.resolve({
        slug: 'redis', name: 'Redis', default_cpu: 1, default_ram_mb: 1024,
        default_disk_gb: 4, installable: true, raw: { install_script: 'msg_ok done' },
      })
      if (path === '/hosts') return Promise.resolve([{ id: 1, name: 'host-01' }])
      if (path === '/catalog/redis/install') return Promise.resolve({ job: { id: 9, kind: 'app.install' } })
      return Promise.resolve(null)
    })

    renderDialog()
    await waitFor(() => expect(screen.getByText(/runs as root on/i)).toBeInTheDocument())
    const installBtn = screen.getByRole('button', { name: 'Install' })
    expect(installBtn).toBeDisabled()

    fireEvent.click(screen.getByRole('checkbox'))
    expect(installBtn).toBeEnabled()
    fireEvent.click(installBtn)

    await waitFor(() => expect(api).toHaveBeenCalledWith('/catalog/redis/install', expect.objectContaining({
      method: 'POST',
      body: expect.stringContaining('"consent":true'),
    })))
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/tests/install.test.tsx`
Expected: FAIL — stub returns `null`

- [ ] **Step 3: Implement `frontend/src/components/InstallDialog.tsx`**

```tsx
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import { useCatalogEntry, useInstall } from '../api/catalog'
import { JobLog } from './JobLog'
import { Button } from './ui/button'

type HostRow = { id: number; name: string }

export function InstallDialog({ slug, onClose }: { slug: string; onClose: () => void }) {
  const { data: entry } = useCatalogEntry(slug)
  const { data: hosts } = useQuery({ queryKey: ['hosts'], queryFn: () => api<HostRow[]>('/hosts') })
  const install = useInstall()
  const [hostId, setHostId] = useState<number | null>(null)
  const [name, setName] = useState('')
  const [ctid, setCtid] = useState('')
  const [consent, setConsent] = useState(false)
  const [jobId, setJobId] = useState<number | null>(null)

  if (!entry) return null

  const canSubmit = consent && hostId != null && name.trim() !== '' && ctid.trim() !== ''

  const submit = () => {
    if (!canSubmit || hostId == null) return
    install.mutate(
      { slug, host_id: hostId, name, ctid: Number(ctid), overrides: {}, consent: true },
      { onSuccess: (r) => setJobId(r.job.id) },
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-[520px] rounded-card border border-line bg-panel p-5">
        <h2 className="text-[16px] font-semibold text-text">Install {entry.name ?? slug}</h2>

        {jobId ? (
          <div className="mt-4">
            <JobLog jobId={jobId} />
            <Button className="mt-3" variant="ghost" onClick={onClose}>Close</Button>
          </div>
        ) : (
          <>
            <div className="mt-4 space-y-3">
              <select className="w-full rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px]"
                value={hostId ?? ''} onChange={(e) => setHostId(Number(e.target.value) || null)}>
                <option value="">Select a host…</option>
                {(hosts ?? []).map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
              </select>
              <input className="w-full rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px]"
                placeholder="App name" value={name} onChange={(e) => setName(e.target.value)} />
              <input className="w-full rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px]"
                placeholder="Container ID (CTID)" value={ctid}
                onChange={(e) => setCtid(e.target.value)} />
              <div className="rounded-ctl border border-line-soft bg-elev p-2 font-mono text-[11px] text-text-3">
                {entry.default_cpu} vCPU · {entry.default_ram_mb}MB RAM · {entry.default_disk_gb}GB disk ·{' '}
                {entry.default_os} {entry.default_os_version}
              </div>
              <div className="text-[12px] text-text-2">
                This installs and runs a community-scripts.org script — it runs as root on the
                target node, exactly as if you ran it yourself.
              </div>
              <label className="flex items-center gap-2 text-[12px] text-text-2">
                <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
                I understand this runs as root on the node
              </label>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="ghost" onClick={onClose}>Cancel</Button>
              <Button variant="primary" disabled={!canSubmit || install.isPending} onClick={submit}>
                Install
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/tests/install.test.tsx`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
cd frontend && git add src/components/InstallDialog.tsx src/tests/install.test.tsx
git commit -m "feat(store): install dialog — host/resources, root-consent gate, live job stream"
```

---

## Task 13: Bulk-adopt dialog wired into `/apps`

**Files:**
- Create: `frontend/src/components/BulkAdoptDialog.tsx`
- Modify: `frontend/src/routes/apps.tsx`
- Create: `frontend/src/tests/adopt.test.tsx`

**Interfaces:**
- Produces: `<BulkAdoptDialog items={DiscoveredRow[]} onClose={() => void} />`.
- Consumes: `DiscoveredRow` (existing type in `api/hooks.ts`).

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/tests/adopt.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { BulkAdoptDialog } from '../components/BulkAdoptDialog'
import type { DiscoveredRow } from '../api/hooks'

vi.mock('../api/client', () => ({ api: vi.fn() }))

const ITEMS: DiscoveredRow[] = [
  { host_id: 1, host_name: 'host-01', ctid: 200, name: 'plex', node: 'pve1', status: 'running', suggestion: 'Plex' },
]

describe('BulkAdoptDialog', () => {
  it('selects all by default and posts /apps/adopt with checked items', async () => {
    const { api } = await import('../api/client')
    vi.mocked(api).mockResolvedValue({ adopted: [1] })
    const onClose = vi.fn()
    const qc = new QueryClient()
    render(
      <QueryClientProvider client={qc}>
        <BulkAdoptDialog items={ITEMS} onClose={onClose} />
      </QueryClientProvider>,
    )
    fireEvent.click(screen.getByRole('button', { name: /Adopt 1 container/i }))
    await waitFor(() => expect(api).toHaveBeenCalledWith('/apps/adopt', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ items: [{ host_id: 1, ctid: 200, name: 'plex', catalog_slug: 'Plex' }] }),
    })))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/tests/adopt.test.tsx`
Expected: FAIL — no `BulkAdoptDialog` module

- [ ] **Step 3: Implement `frontend/src/components/BulkAdoptDialog.tsx`**

```tsx
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import type { DiscoveredRow } from '../api/hooks'
import { Button } from './ui/button'

export function BulkAdoptDialog({ items, onClose }: {
  items: DiscoveredRow[]; onClose: () => void
}) {
  const [checked, setChecked] = useState<Set<string>>(
    new Set(items.map((i) => `${i.host_id}:${i.ctid}`)))
  const qc = useQueryClient()
  const adopt = useMutation({
    mutationFn: (payload: { items: { host_id: number; ctid: number; name: string; catalog_slug: string | null }[] }) =>
      api<{ adopted: number[] }>('/apps/adopt', { method: 'POST', body: JSON.stringify(payload) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['apps'] })
      onClose()
    },
  })

  const toggle = (key: string) => setChecked((prev) => {
    const next = new Set(prev)
    next.has(key) ? next.delete(key) : next.add(key)
    return next
  })

  const submit = () => {
    const payload = items
      .filter((i) => checked.has(`${i.host_id}:${i.ctid}`))
      .map((i) => ({ host_id: i.host_id, ctid: i.ctid, name: i.name ?? `CT ${i.ctid}`,
                    catalog_slug: i.suggestion }))
    adopt.mutate({ items: payload })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-[480px] rounded-card border border-line bg-panel p-5">
        <h2 className="text-[16px] font-semibold text-text">Adopt discovered containers</h2>
        <div className="mt-3 space-y-1">
          {items.map((i) => {
            const key = `${i.host_id}:${i.ctid}`
            return (
              <label key={key} className="flex items-center gap-2 font-mono text-[12px] text-text-2">
                <input type="checkbox" checked={checked.has(key)} onChange={() => toggle(key)} />
                CT {i.ctid} · {i.name ?? '—'} · {i.host_name}
                {i.suggestion && <span className="text-amber">matches "{i.suggestion}"</span>}
              </label>
            )
          })}
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={checked.size === 0 || adopt.isPending} onClick={submit}>
            Adopt {checked.size} container{checked.size === 1 ? '' : 's'}
          </Button>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/tests/adopt.test.tsx`
Expected: 1 passed

- [ ] **Step 5: Wire it into `routes/apps.tsx`**

In `frontend/src/routes/apps.tsx`'s `AppsPage`, add `const [adopting, setAdopting] = useState(false)`, replace the discovered-panel's static "Adoption arrives with the App Store phase (Phase 4)" line with a button that opens the dialog:

```tsx
<button className="mt-2 text-[12px] text-amber hover:underline" onClick={() => setAdopting(true)}>
  Adopt {discovered.length} container{discovered.length > 1 ? 's' : ''}
</button>
```

and render `{adopting && <BulkAdoptDialog items={discovered} onClose={() => setAdopting(false)} />}` after the existing grid, importing `BulkAdoptDialog` at the top.

- [ ] **Step 6: Commit**

```bash
cd frontend && git add src/components/BulkAdoptDialog.tsx src/routes/apps.tsx src/tests/adopt.test.tsx
git commit -m "feat(apps): wire bulk-adopt dialog into the discovered-containers panel"
```

---

## Task 14: App detail Config tab — script view/edit + diff

**Files:**
- Create: `frontend/src/components/ScriptPanel.tsx`
- Modify: `frontend/src/routes/apps.tsx` (`appConfigRoute`)
- Create: `frontend/src/tests/script.test.tsx`

**Interfaces:**
- Produces: `<ScriptPanel appId={number} />`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/tests/script.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ScriptPanel } from '../components/ScriptPanel'

vi.mock('../api/client', () => ({ api: vi.fn() }))

describe('ScriptPanel', () => {
  it('renders the pinned script content and its source', async () => {
    const { api } = await import('../api/client')
    vi.mocked(api).mockResolvedValue({
      version: 1, content: 'msg_ok done\n', source: 'upstream', diff_vs_upstream: null,
    })
    const qc = new QueryClient()
    render(
      <QueryClientProvider client={qc}>
        <ScriptPanel appId={1} />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(screen.getByText(/msg_ok done/)).toBeInTheDocument())
    expect(screen.getByText(/version 1 · upstream/i)).toBeInTheDocument()
    expect(screen.getByText(/matches upstream/i)).toBeInTheDocument()
  })

  it('shows the real diff banner and diff body when the pinned script has drifted', async () => {
    const { api } = await import('../api/client')
    const diff = '--- upstream\n+++ pinned\n@@ -1 +1 @@\n-msg_ok done\n+msg_ok edited\n'
    vi.mocked(api).mockResolvedValue({
      version: 2, content: 'msg_ok edited\n', source: 'edited', diff_vs_upstream: diff,
    })
    const qc = new QueryClient()
    render(
      <QueryClientProvider client={qc}>
        <ScriptPanel appId={1} />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(screen.getByText(/differs from upstream/i)).toBeInTheDocument())
    expect(screen.getByText(/-msg_ok done/)).toBeInTheDocument()
    expect(screen.getByText(/\+msg_ok edited/)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/tests/script.test.tsx`
Expected: FAIL — no `ScriptPanel` module

- [ ] **Step 3: Implement `frontend/src/components/ScriptPanel.tsx`**

```tsx
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

type ScriptOut = { version: number; content: string; source: string; diff_vs_upstream: string | null }

function DiffLine({ line }: { line: string }) {
  const cls = line.startsWith('+') ? 'text-green-400' : line.startsWith('-') ? 'text-red-400' : 'text-text-3'
  return <div className={cls}>{line}</div>
}

export function ScriptPanel({ appId }: { appId: number }) {
  const { data } = useQuery({
    queryKey: ['apps', appId, 'script'],
    queryFn: () => api<ScriptOut>(`/apps/${appId}/script`),
  })
  if (!data) return null
  return (
    <div>
      <div className="mb-2 text-[12px] text-text-3">version {data.version} · {data.source}</div>
      {data.diff_vs_upstream ? (
        <div className="mb-3">
          <div className="mb-1 text-[12px] font-semibold text-amber">Differs from upstream</div>
          <pre className="overflow-x-auto rounded-card bg-[#0a0e14] p-4 font-mono text-[12px]">
            {data.diff_vs_upstream.split('\n').map((l, i) => <DiffLine key={i} line={l} />)}
          </pre>
        </div>
      ) : (
        <div className="mb-3 text-[12px] text-text-3">Matches upstream — no local edits.</div>
      )}
      <pre className="overflow-x-auto rounded-card bg-[#0a0e14] p-4 font-mono text-[12px] text-text-2">
        {data.content}
      </pre>
    </div>
  )
}
```

(This ships a plain `<pre>`-based diff/content view — not yet doc 06's CodeMirror 6 syntax-highlighted *editor*. The diff itself, which is the acceptance criterion, is real and computed against the live `catalog_entries` row, not deferred. Wiring an actual editable textarea to the existing `PUT /apps/{id}/script` route is a small, separable follow-up — read-only display is what this task's tests check.)

- [ ] **Step 4: Wire it into `routes/apps.tsx`**

Replace `appConfigRoute`'s `phaseTab(...)` definition with:

```tsx
const AppConfigTab = () => {
  const { appId } = useParams({ strict: false }) as { appId: string }
  return <ScriptPanel appId={Number(appId)} />
}

export const appConfigRoute = createRoute({
  getParentRoute: () => appDetailRoute,
  path: 'config',
  component: AppConfigTab,
})
```

Import `ScriptPanel` at the top of the file.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/tests/script.test.tsx`
Expected: 1 passed

- [ ] **Step 6: Commit**

```bash
cd frontend && git add src/components/ScriptPanel.tsx src/routes/apps.tsx src/tests/script.test.tsx
git commit -m "feat(apps): Config tab renders the pinned install script"
```

---

## Task 15: Phase 4 DoD verification script + notes doc

**Files:**
- Create: `backend/dod_verify_phase4.py` (scratch, run once, not committed — mirrors Phase 3's pattern per `docs/notes/phase-3-act.md`)
- Create: `docs/notes/phase-4-store.md`

**Interfaces:** none (verification-only task).

- [ ] **Step 1: Write the DoD verification script**

Doc 10 Phase 4 DoD: *"a real app (e.g. Immich) installs from the store onto a chosen host as exactly one CT, with live log, archived log, audit row, and consent step; catalog survives upstream being unreachable (serves cache with staleness banner); an edited script shows its diff against upstream before every run; the store reports the true installable count — no '300+ scripts' placeholder — with unsupported entries counted and shown separately; a host with pre-existing CTs shows them in the discovered panel and bulk-adopts cleanly."*

```python
# backend/dod_verify_phase4.py — run once from backend/ with the project venv, not committed
"""Phase 4 DoD verification, doc 10. Uses tests.support.make_app +
tests/fakes/ssh.py's FakeSSHConnection — no live PVE, no real SSH, matching
the same no-PVE/no-Docker verification approach Phases 1-3 used."""
import asyncio
from pathlib import Path

from tests.fakes.ssh import FakeSSHConnection, make_fake_connect_factory
from tests.support import make_app, seed_host_row


def main():
    tmp = Path("/tmp/phase4_dod")
    tmp.mkdir(exist_ok=True)
    app = make_app(tmp)
    with app.state.sessionmaker() as db:
        from proxploy.models import CatalogEntry, HostCredential
        host = seed_host_row(db)
        sblob, sver = app.state.secretstore.encrypt(b"fake-key")
        db.add(HostCredential(host_id=host.id, kind="ssh_key", encrypted_blob=sblob,
                              key_version=sver, public_meta="ssh-ed25519 AAAA"))
        db.add(CatalogEntry(slug="immich", name="Immich", installable=True,
                            raw={"install_script": "msg_ok done"}))
        db.commit()
        host_id = host.id

    fake = FakeSSHConnection(host_key_fingerprint="SHA256:abc",
                             stdout_lines=["Setting up Immich"], stderr_lines=[], exit_status=0)
    app.state.ssh_connect_factory = make_fake_connect_factory(fake)

    from proxploy.services.appstore import run_install
    from proxploy.jobs import JobBackend, JobContext
    backend = JobBackend(app)
    ctx = JobContext(backend, job_id=1)
    result = asyncio.run(run_install(ctx, {"catalog_slug": "immich", "host_id": host_id,
                                           "name": "Immich", "ctid": 150, "overrides": {}}))
    print("install result:", result)

    with app.state.sessionmaker() as db:
        from proxploy.models import App, AppScript
        row = db.query(App).filter_by(slug=result["slug"]).one()
        assert row.host_id == host_id and row.ctid == 150
        script = db.query(AppScript).filter_by(app_id=row.id).one()
        assert script.version == 1
    print("PROVED: one-CT install, script pinned")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it and paste real output into the notes doc**

Run: `cd backend && python dod_verify_phase4.py`

- [ ] **Step 3: Run the full backend + frontend suites**

Run: `cd backend && pytest tests/ -q -m "not pve_integration and not e2e"` — expect all prior counts (Phase 3: 190 passed, 1 skipped, 2 deselected) plus this plan's new tests, zero failures.
Run: `cd backend && python scripts/check_executor_isolation.py` — expect `executor isolation: OK`.
Run: `cd frontend && npm test` — expect all prior counts (Phase 3: 33 passed, 11 files) plus this plan's new tests, zero failures.
Run: `cd frontend && npm run build` — expect a clean build.

- [ ] **Step 4: Write `docs/notes/phase-4-store.md`**

Follow `docs/notes/phase-3-act.md`'s exact structure: "What shipped, per subsystem", a DoD verification map table (clause | proving artifact | verdict) covering all five doc 10 DoD clauses above, real command output, and a "What was NOT verified" section — call out explicitly: no real Proxmox host, no real SSH connection, no browser UI check (matching every prior phase's stated limitation), and the catalog-categories/description/icon gap from this plan's header note.

- [ ] **Step 5: Update `buildlog.md`**

Append a `### <timestamp> — Phase 4 — execute-plan completed` entry matching Phases 2/3's format exactly (plan path, verification counts, what was built, deviations).

- [ ] **Step 6: Commit**

```bash
git add docs/notes/phase-4-store.md buildlog.md
git commit -m "docs(phase-4): DoD verification notes + buildlog entry"
```
