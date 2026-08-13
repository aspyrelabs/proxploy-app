# App Install Modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the live storage bug that silently installs nothing on multi-pool
hosts, then give the App Store a Default and an Advanced install mode with a
container-customization form and an optional CTID.

**Architecture:** Part A is a standalone bugfix: switch `mode=default` to
`mode=generated` so `build.func` stops calling its interactive storage picker,
and resolve both storage pools in the backend before the SSH command is built.
Part B fills the `overrides` dict that `InstallDialog` has always sent empty,
adding a Default/Advanced choice to the existing dialog. No new execution
mechanism is introduced in either part.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, pytest (backend); React 19,
TanStack Router/Query, Tailwind v4, shadcn, vitest (frontend); asyncssh to a
Proxmox node over root SSH via `pct`.

## Global Constraints

- **No em dashes** anywhere: code, comments, docs, commit messages.
- Proxploy **never** answers a prompt on the operator's behalf. Either the
  operator chose the value in a form, or the operator answers it live.
- Metadata (PocketBase) is **presentation-only**. It never decides
  installability, entry type, or resource defaults.
  `catalog_metadata.WRITABLE_FIELDS` and `apply_writable_fields` stay as they
  are.
- Discovery keeps its flat **2-`api.github.com`-call ceiling**. All payload
  fetches are `raw.githubusercontent.com`, pinned to `upstream_sha`.
- Installs run over root SSH via `pct`, the existing channel. No new transport.
- The Store stays **LXC-only**. The classifier's interactive-input finding is
  not softened.
- Every emitted environment variable name must exist in `build.func`'s real
  variable set (Task 3 pins the list).
- Backend suite: `cd backend && .venv/bin/python -m pytest tests/ -q -m "not pve_integration and not e2e"`
- Frontend suite: `cd frontend && npx vitest run --no-file-parallelism` then
  `npx tsc -b && npx oxlint`. **Vitest must run from `frontend/`**, never the
  repo root, or every test fails with `document is not defined`.
- Do not kill anything on ports 8000 or 5173. They are the user's dev servers.

## File Structure

**Part A, the bugfix**

| File | Responsibility |
|---|---|
| `backend/proxploy/services/appstore.py` | `_storage_pools` host query, `resolve_storage_pools` resolution, `run_install` wiring |
| `backend/proxploy/models/__init__.py` | `Host.default_container_storage`, `Host.default_template_storage` |
| `backend/proxploy/migrations/versions/*_host_storage_defaults.py` | the two columns |
| `backend/tests/test_appstore_storage.py` | new, the resolution rules |
| `backend/tests/test_appstore_install.py` | update the pinned command assertion |

**Part B, the modes and form**

| File | Responsibility |
|---|---|
| `backend/proxploy/api/catalog.py` | `InstallIn.ctid` optional, install defaults on the detail payload |
| `backend/proxploy/models/__init__.py` | `Host.install_consent_at` |
| `backend/proxploy/migrations/versions/*_host_install_consent.py` | the column plus the backfill |
| `frontend/src/api/catalog.ts` | `InstallVars` gains the optional fields |
| `frontend/src/components/InstallDialog.tsx` | the Default/Advanced choice and the core fields |
| `frontend/src/components/install/StorageFields.tsx` | new, the two content-filtered pickers |
| `frontend/src/components/install/AdvancedOptions.tsx` | new, the collapsed group and its validation |
| `frontend/src/tests/install.test.tsx` | the dialog behaviour |

---

# PART A: the storage bugfix

Ships on its own. Do not hold it behind Part B.

### Task 1: Query a host's storage pools by content type

**Files:**
- Modify: `backend/proxploy/services/appstore.py` (add beside `_lxc_ids`, line 278)
- Test: `backend/tests/test_appstore_storage.py` (create)

**Interfaces:**
- Consumes: `client_for_host(app, db, host)` and the `_lxc_ids` blocking-helper
  pattern, both already in `appstore.py`.
- Produces: `_storage_pools(app, host_id, content) -> list[str]`, the enabled and
  active pool names on the host's node carrying that content type.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_appstore_storage.py
import pytest
from proxploy.services.appstore import _storage_pools


def test_storage_pools_filters_by_content_type(app_with_fake_pve, host_id):
    """rootdir and vztmpl are different questions. A pool that can hold a
    template cannot necessarily hold a rootfs, and offering one for the other
    fails at pct create with a raw Proxmox error."""
    app_with_fake_pve.state.fake_pve.storages = [
        {"storage": "local", "content": "vztmpl,iso", "enabled": 1, "active": 1},
        {"storage": "local-lvm", "content": "rootdir,images", "enabled": 1, "active": 1},
        {"storage": "tank", "content": "rootdir,vztmpl", "enabled": 1, "active": 1},
    ]

    assert _storage_pools(app_with_fake_pve, host_id, "rootdir") == ["local-lvm", "tank"]
    assert _storage_pools(app_with_fake_pve, host_id, "vztmpl") == ["local", "tank"]


def test_storage_pools_excludes_disabled_and_inactive(app_with_fake_pve, host_id):
    app_with_fake_pve.state.fake_pve.storages = [
        {"storage": "good", "content": "rootdir", "enabled": 1, "active": 1},
        {"storage": "off", "content": "rootdir", "enabled": 0, "active": 1},
        {"storage": "down", "content": "rootdir", "enabled": 1, "active": 0},
    ]

    assert _storage_pools(app_with_fake_pve, host_id, "rootdir") == ["good"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_appstore_storage.py -v`
Expected: FAIL, `ImportError: cannot import name '_storage_pools'`

- [ ] **Step 3: Write the implementation**

```python
# backend/proxploy/services/appstore.py, beside _lxc_ids

def _storage_pools(app, host_id: int, content: str) -> list[str]:
    """Blocking: the pool names on this host's node that carry `content`.

    The API-side equivalent of build.func's
    `pvesm status -content "$content"`. Deliberately NOT the poller's cached
    snapshot, for the same reason `_lxc_ids` gives: this decides where a
    container's disk lands, and a 30 s stale cache is the wrong input for that.

    Sorted so a caller comparing two candidate lists gets a stable answer, and
    so an error message naming them reads the same every time.
    """
    with app.state.sessionmaker() as db:
        host = db.get(Host, host_id)
        if host is None:
            raise JobFailed(f"host {host_id} not found")
        if not host.node_name:
            raise JobFailed(f"host {host.name} has no node name recorded")
        client = client_for_host(app, db, host)
        rows = client.storages(host.node_name)
    out = []
    for row in rows:
        if not row.get("enabled", 1) or not row.get("active", 1):
            continue
        if content in str(row.get("content") or "").split(","):
            out.append(str(row["storage"]))
    return sorted(out)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_appstore_storage.py -v`
Expected: PASS, 2 tests

- [ ] **Step 5: Commit**

```bash
git add backend/proxploy/services/appstore.py backend/tests/test_appstore_storage.py
git commit -m "feat(install): query a host's storage pools by content type"
```

---

### Task 2: Remember a host's chosen pools

**Files:**
- Modify: `backend/proxploy/models/__init__.py` (class `Host`, near `node_shell_enabled` line 142)
- Create: `backend/proxploy/migrations/versions/<rev>_host_storage_defaults.py`
- Test: `backend/tests/test_appstore_storage.py`

**Interfaces:**
- Produces: `Host.default_container_storage: str | None`,
  `Host.default_template_storage: str | None`. Null means "not chosen yet",
  which is distinct from any pool name.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_appstore_storage.py, append

def test_host_storage_defaults_start_null(db_session, a_host):
    """Null means the operator has not chosen. It must stay distinguishable
    from a real pool name, so the resolution order can tell "not asked yet"
    from "asked, and they picked local-lvm"."""
    assert a_host.default_container_storage is None
    assert a_host.default_template_storage is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_appstore_storage.py -k storage_defaults -v`
Expected: FAIL, `AttributeError: 'Host' object has no attribute 'default_container_storage'`

- [ ] **Step 3: Add the columns and the migration**

```python
# backend/proxploy/models/__init__.py, in class Host after node_shell_enabled

    # The pools this host's operator chose, remembered so the question is asked
    # once rather than on every install. NULL means "not chosen yet", which is
    # deliberately distinct from any pool name: services/appstore.py's
    # resolution order treats NULL as "fall through", and a stored name as an
    # answer to re-validate. Per content type, because a node can have one
    # rootdir candidate and several vztmpl ones.
    default_container_storage: Mapped[str | None] = mapped_column(Text)
    default_template_storage: Mapped[str | None] = mapped_column(Text)
```

```python
# backend/proxploy/migrations/versions/<rev>_host_storage_defaults.py
"""host storage defaults

Revision ID: <generate>
Revises: <current head>
Create Date: 2026-08-13

The pools an operator chose for a host, so the storage question is asked once
rather than on every install. Nullable with no default on purpose: NULL means
"not chosen yet" and must stay distinguishable from a pool name.
"""
from alembic import op
import sqlalchemy as sa

revision = "<generate>"
down_revision = "<current head>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("hosts") as batch:
        batch.add_column(sa.Column("default_container_storage", sa.Text(), nullable=True))
        batch.add_column(sa.Column("default_template_storage", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("hosts") as batch:
        batch.drop_column("default_template_storage")
        batch.drop_column("default_container_storage")
```

Find the current head first:

```bash
cd backend && .venv/bin/python -c "
import os, re
d='proxploy/migrations/versions'
revs, downs = {}, set()
for f in os.listdir(d):
    if not f.endswith('.py'): continue
    t = open(os.path.join(d, f)).read()
    r = re.search(r'^revision(?::.*?)?\s*=\s*[\"\']([^\"\']+)', t, re.M)
    dn = re.search(r'^down_revision(?::.*?)?\s*=\s*[\"\']([^\"\']+)', t, re.M)
    if r: revs[r.group(1)] = f
    if dn: downs.add(dn.group(1))
print([k for k in revs if k not in downs])
"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_appstore_storage.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/proxploy/models/__init__.py backend/proxploy/migrations/versions backend/tests/test_appstore_storage.py
git commit -m "feat(install): remember a host's chosen storage pools"
```

---

### Task 3: Resolve the pools, and never pick one

**Files:**
- Modify: `backend/proxploy/services/appstore.py`
- Test: `backend/tests/test_appstore_storage.py`

**Interfaces:**
- Consumes: `_storage_pools` (Task 1), `Host.default_*_storage` (Task 2).
- Produces: `resolve_storage_pools(app, host_id, supplied) -> tuple[str, str]`,
  returning `(container_pool, template_pool)` or raising `JobFailed`.
  `supplied` is the `overrides` dict; it reads the keys
  `container_storage` and `template_storage`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_appstore_storage.py, append
from proxploy.services.appstore import resolve_storage_pools
from proxploy.jobs import JobFailed


def test_sole_candidate_is_not_a_pick(app_with_fake_pve, host_id):
    """One candidate is not a choice, so using it answers nothing on the
    operator's behalf."""
    app_with_fake_pve.state.fake_pve.storages = [
        {"storage": "local", "content": "vztmpl", "enabled": 1, "active": 1},
        {"storage": "local-lvm", "content": "rootdir", "enabled": 1, "active": 1},
    ]
    assert resolve_storage_pools(app_with_fake_pve, host_id, {}) == ("local-lvm", "local")


def test_refuses_rather_than_picking_when_ambiguous(app_with_fake_pve, host_id):
    """THE RULE OF THIS SPEC. Which pool a container lives on is a question,
    and picking one is answering it for the operator. Never auto-pick, not by
    free space, not by name, not by order."""
    app_with_fake_pve.state.fake_pve.storages = [
        {"storage": "local", "content": "vztmpl", "enabled": 1, "active": 1},
        {"storage": "lvm-a", "content": "rootdir", "enabled": 1, "active": 1},
        {"storage": "lvm-b", "content": "rootdir", "enabled": 1, "active": 1},
    ]
    with pytest.raises(JobFailed) as e:
        resolve_storage_pools(app_with_fake_pve, host_id, {})
    assert "lvm-a" in str(e.value) and "lvm-b" in str(e.value)


def test_supplied_beats_remembered(app_with_fake_pve, host_id, a_host, db_session):
    a_host.default_container_storage = "lvm-a"
    db_session.commit()
    app_with_fake_pve.state.fake_pve.storages = [
        {"storage": "local", "content": "vztmpl", "enabled": 1, "active": 1},
        {"storage": "lvm-a", "content": "rootdir", "enabled": 1, "active": 1},
        {"storage": "lvm-b", "content": "rootdir", "enabled": 1, "active": 1},
    ]
    got = resolve_storage_pools(app_with_fake_pve, host_id, {"container_storage": "lvm-b"})
    assert got[0] == "lvm-b"


def test_stale_remembered_pool_reasks_rather_than_substituting(
        app_with_fake_pve, host_id, a_host, db_session):
    """A remembered pool that no longer carries rootdir must not be silently
    replaced with another one. Sending it anyway hits build.func's
    resolve_storage_preselect 238 path, where it spins in an empty while true."""
    a_host.default_container_storage = "retired-pool"
    db_session.commit()
    app_with_fake_pve.state.fake_pve.storages = [
        {"storage": "local", "content": "vztmpl", "enabled": 1, "active": 1},
        {"storage": "lvm-a", "content": "rootdir", "enabled": 1, "active": 1},
        {"storage": "lvm-b", "content": "rootdir", "enabled": 1, "active": 1},
    ]
    with pytest.raises(JobFailed) as e:
        resolve_storage_pools(app_with_fake_pve, host_id, {})
    assert "retired-pool" in str(e.value)


def test_supplied_pool_invalid_for_the_node_is_refused(app_with_fake_pve, host_id):
    app_with_fake_pve.state.fake_pve.storages = [
        {"storage": "local", "content": "vztmpl", "enabled": 1, "active": 1},
        {"storage": "lvm-a", "content": "rootdir", "enabled": 1, "active": 1},
    ]
    with pytest.raises(JobFailed) as e:
        resolve_storage_pools(app_with_fake_pve, host_id, {"container_storage": "nope"})
    assert "nope" in str(e.value)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_appstore_storage.py -v`
Expected: FAIL, `ImportError: cannot import name 'resolve_storage_pools'`

- [ ] **Step 3: Write the implementation**

```python
# backend/proxploy/services/appstore.py

_STORAGE_CLASSES = (
    # (overrides key, Host column, build.func content type)
    ("container_storage", "default_container_storage", "rootdir"),
    ("template_storage", "default_template_storage", "vztmpl"),
)


def resolve_storage_pools(app, host_id: int, supplied: dict) -> tuple[str, str]:
    """The container and template pools for this install, or JobFailed.

    THIS FUNCTION NEVER PICKS. Which pool a container lives on is a question,
    and choosing one is answering it on the operator's behalf, which is the
    thing this whole design exists to refuse. The order is:

      1. what the operator supplied for this install
      2. what the operator previously chose for this host, if still valid
      3. the sole candidate, if the node has exactly one. Not a pick: there is
         nothing to choose between.
      4. refuse, naming the candidates

    Every value is validated against the node's real content list before it is
    returned. An invalid pool reaches build.func's resolve_storage_preselect
    238 branch, where `while true` spins with an empty body: a real hang that
    our 1800 s SSH timeout would surface as `TimeoutError: ` with no message.
    """
    resolved = []
    for key, column, content in _STORAGE_CLASSES:
        candidates = _storage_pools(app, host_id, content)
        if not candidates:
            raise JobFailed(f"host has no storage carrying {content!r}")

        chosen = (supplied.get(key) or "").strip() or None
        if chosen:
            if chosen not in candidates:
                raise JobFailed(
                    f"storage {chosen!r} does not carry {content!r} on this host; "
                    f"available: {', '.join(candidates)}")
            resolved.append(chosen)
            continue

        with app.state.sessionmaker() as db:
            host = db.get(Host, host_id)
            remembered = getattr(host, column, None) if host else None
        if remembered:
            if remembered in candidates:
                resolved.append(remembered)
                continue
            raise JobFailed(
                f"this host's saved {content!r} storage {remembered!r} is no longer "
                f"available; choose one of: {', '.join(candidates)}")

        if len(candidates) == 1:
            resolved.append(candidates[0])
            continue

        raise JobFailed(
            f"this host has {len(candidates)} pools for {content!r} and none has "
            f"been chosen: {', '.join(candidates)}. Choose one in the install form.")
    return resolved[0], resolved[1]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_appstore_storage.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add backend/proxploy/services/appstore.py backend/tests/test_appstore_storage.py
git commit -m "feat(install): resolve storage pools without ever picking one"
```

---

### Task 4: Switch to mode=generated and send the pools

**Files:**
- Modify: `backend/proxploy/services/appstore.py` (`run_install`, around line 134)
- Modify: `backend/tests/test_appstore_install.py:157`
- Test: `backend/tests/test_appstore_storage.py`

**Interfaces:**
- Consumes: `resolve_storage_pools` (Task 3).
- Produces: the install command now carries `mode=generated`,
  `var_container_storage` and `var_template_storage` on **every** install.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_appstore_storage.py, append

@pytest.mark.asyncio
async def test_default_install_with_no_user_input_sends_both_storage_vars(
        app_with_fake_pve, host_id, fake_ssh):
    """NAMED REGRESSION TEST. The future change this exists to stop is a
    tidy-up that omits storage when the operator did not touch it. That looks
    like sending less noise, reintroduces build.func's interactive picker, and
    fails ONLY on hosts with two or more candidates, so it passes on any
    single-storage development box.
    """
    app_with_fake_pve.state.fake_pve.storages = [
        {"storage": "local", "content": "vztmpl", "enabled": 1, "active": 1},
        {"storage": "local-lvm", "content": "rootdir", "enabled": 1, "active": 1},
    ]
    await run_a_default_install(app_with_fake_pve, host_id)

    cmd = fake_ssh.last_command
    assert "var_container_storage=local-lvm" in cmd
    assert "var_template_storage=local" in cmd


@pytest.mark.asyncio
async def test_mode_is_generated_never_default(app_with_fake_pve, host_id, fake_ssh):
    """mode=default is the ONLY branch that runs
    defaults_target=$(ensure_global_default_vars_file), which is what reaches
    the interactive storage picker at build.func:3533. The generated branch is
    byte-identical apart from METHOD, which only reaches telemetry. Reverting
    this silently reintroduces the silent exit 0.
    """
    await run_a_default_install(app_with_fake_pve, host_id)
    cmd = fake_ssh.last_command
    assert "mode=generated" in cmd
    assert "mode=default" not in cmd
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_appstore_storage.py -k "storage_vars or generated" -v`
Expected: FAIL, the command contains `mode=default` and no storage variables

- [ ] **Step 3: Write the implementation**

```python
# backend/proxploy/services/appstore.py, in run_install, replacing the env block

    # `mode` is lowercase and `generated`, not `default`. Both branches of
    # build.func's case statement are byte-identical apart from METHOD (which
    # reaches nothing but the telemetry payload) EXCEPT that `default` also
    # runs `defaults_target="$(ensure_global_default_vars_file)"`, and that is
    # what reaches ensure_storage_selection_for_vars_file at build.func:3533.
    # On a host with two or more pools for a content type that calls
    # select_storage, whiptail cannot run without a TTY, `|| exit_script`
    # fires, and exit_script does `exit 0`: a container is never created and
    # the script reports success. This is the same failure shape as the
    # uppercase-MODE bug documented below, in a second place.
    #
    # TERM must be a real terminal type. A non-PTY ssh session lands on
    # TERM=dumb, where build.func's `clear` fails.
    env = {"TERM": "xterm", "mode": "generated", "PHS_SILENT": "1"}
    for key, val in overrides.items():
        env[f"var_{key}"] = str(val)

    # Sent on EVERY install, Default included. build.func only auto-picks when
    # exactly one candidate exists for the content type; with two or more it
    # asks, and we can never let it ask. See resolve_storage_pools: it refuses
    # rather than picking when the operator has not chosen.
    container_pool, template_pool = await asyncio.to_thread(
        resolve_storage_pools, app, host_id, overrides)
    env["var_container_storage"] = container_pool
    env["var_template_storage"] = template_pool

    # Set last so it always wins over an `overrides` entry: the App row below
    # records this ctid as fact, so the container has to actually land there.
    env["var_ctid"] = str(ctid)
```

Then update the pinned assertion:

```python
# backend/tests/test_appstore_install.py, replacing line 157
        assert cmd.startswith("TERM=xterm mode=generated PHS_SILENT=1 "
                              "var_cpu=2 var_ram=2048 "
                              "var_container_storage=local-lvm "
                              "var_template_storage=local "
                              "var_ctid=150 bash -c ")
```

- [ ] **Step 4: Run the whole backend suite**

Run: `cd backend && .venv/bin/python -m pytest tests/ -q -m "not pve_integration and not e2e"`
Expected: PASS. If other install tests fail on the storage variables, their
fixtures need a storage list, not a weakened assertion.

- [ ] **Step 5: Commit**

```bash
git add backend/proxploy/services/appstore.py backend/tests/
git commit -m "fix(install): stop build.func reaching its interactive storage picker"
```

**PART A SHIPS HERE.** Push it before starting Part B. Then perform the
multi-storage hardware checks in `docs/12-hardware-verification.md`, which are
the only way to know this actually worked.

---

# PART B: Default and Advanced install modes

### Task 5: Make the CTID optional

**Files:**
- Modify: `backend/proxploy/api/catalog.py:341` (`InstallIn.ctid`)
- Modify: `backend/proxploy/services/appstore.py` (`run_install`)
- Test: `backend/tests/test_catalog_install_api.py`

**Interfaces:**
- Produces: `InstallIn.ctid: int | None = None`. When null, `var_ctid` is
  **absent** from the environment.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_catalog_install_api.py, append

@pytest.mark.asyncio
async def test_blank_ctid_omits_the_variable_entirely(app_with_fake_pve, host_id, fake_ssh):
    """ABSENCE, not an empty string. build.func:1083 reads
    `${var_ctid:-$NEXTID}`, whose colon form tolerates empty, but :1086
    separately branches on `[[ -n "${var_ctid:-}" ]]`. Absence is the contract
    that satisfies both readers and survives a future change to the non-colon
    `${var_ctid-...}` form.
    """
    await run_install_without_ctid(app_with_fake_pve, host_id)
    assert "var_ctid" not in fake_ssh.last_command
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_catalog_install_api.py -k blank_ctid -v`
Expected: FAIL, `ctid` is a required field

- [ ] **Step 3: Write the implementation**

```python
# backend/proxploy/api/catalog.py
class InstallIn(BaseModel):
    host_id: int
    name: str
    # Optional: blank means build.func assigns the next free id via
    # `${var_ctid:-$NEXTID}`. Requiring one was a bug; there is nothing an
    # operator can usefully say here that the node cannot say better.
    ctid: int | None = None
    overrides: dict = {}
    consent: bool = False
```

```python
# backend/proxploy/services/appstore.py, in run_install
    ctid = params.get("ctid")
    ctid = int(ctid) if ctid is not None else None
```

```python
    # ...and replacing the unconditional var_ctid line:
    if ctid is not None:
        # Set last so it wins over an `overrides` entry: the App row records
        # this ctid as fact, so the container has to land there. When it is
        # None the key is ABSENT, never empty, because build.func reads it
        # twice and only one of the two readers tolerates an empty value.
        env["var_ctid"] = str(ctid)
```

The existing pre-check and post-check both guard on `ctid`; make each
conditional on it being supplied, and when it is not, read the created id back
from the diff of `_lxc_ids` before and after:

```python
    before = await asyncio.to_thread(_lxc_ids, app, host_id)
    if ctid is not None and ctid in before:
        raise JobFailed(f"CT {ctid} already exists on {host.name}; "
                        f"refusing to install over it")
    # ... after the run ...
    after = await asyncio.to_thread(_lxc_ids, app, host_id)
    if ctid is None:
        created = sorted(after - before)
        if len(created) != 1:
            raise JobFailed(
                f"install script exited 0 but {len(created)} containers appeared "
                f"on {host.name}: cannot record which one is this app")
        ctid = created[0]
    elif ctid not in after:
        raise JobFailed(
            f"install script exited 0 but CT {ctid} does not exist on "
            f"{host.name}: nothing was installed")
```

- [ ] **Step 4: Run the backend suite**

Run: `cd backend && .venv/bin/python -m pytest tests/ -q -m "not pve_integration and not e2e"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/proxploy/api/catalog.py backend/proxploy/services/appstore.py backend/tests/
git commit -m "feat(install): make the CTID optional"
```

---

### Task 6: Move consent to the host

**Files:**
- Modify: `backend/proxploy/models/__init__.py` (class `Host`)
- Create: `backend/proxploy/migrations/versions/<rev>_host_install_consent.py`
- Modify: `backend/proxploy/api/catalog.py:369`
- Test: `backend/tests/test_catalog_install_api.py`

**Interfaces:**
- Produces: `Host.install_consent_at: datetime | None`. Null means not
  acknowledged.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_catalog_install_api.py, append

def test_install_refused_without_host_consent(client, a_host_without_consent):
    r = client.post("/api/v1/catalog/redis/install",
                    json={"host_id": a_host_without_consent.id, "name": "redis"})
    assert r.status_code == 400
    assert "consent" in r.json()["detail"].lower()


def test_migration_backfills_only_hosts_with_installs_enabled(migrated_db):
    """Hosts that enrolled an SSH key already performed the same grant, and
    ticked the per-install box on every install they ran. Re-asking surfaces no
    new information. Hosts WITHOUT a key never granted anything to backfill."""
    with_key, without_key = hosts_by_key_presence(migrated_db)
    assert all(h.install_consent_at is not None for h in with_key)
    assert all(h.install_consent_at is None for h in without_key)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_catalog_install_api.py -k consent -v`
Expected: FAIL, `AttributeError: install_consent_at`

- [ ] **Step 3: Write the implementation**

```python
# backend/proxploy/models/__init__.py, in class Host

    # When this host's operator acknowledged that installs run third-party
    # scripts as root here. Per host rather than per install: the acknowledgement
    # is about the host, and re-asking on every install is friction that
    # surfaces no new information. NULL means not acknowledged.
    install_consent_at: Mapped[datetime | None] = mapped_column(DateTime)
```

```python
# backend/proxploy/migrations/versions/<rev>_host_install_consent.py
"""host install consent

Revision ID: <generate>
Revises: <head from Task 2>
Create Date: 2026-08-13

Consent moves from a per-install checkbox to a per-host acknowledgement.

THE BACKFILL IS A DELIBERATE DECISION, not a default value. Hosts that already
have an enrolled SSH key are marked acknowledged: enrolling that key IS the
grant of root execution, and those operators additionally ticked the
per-install box on every install they ran, so requiring a re-tick would be
friction that surfaces no new information. Hosts WITHOUT a key are left NULL:
they never granted anything there is anything to backfill from.
"""
from alembic import op
import sqlalchemy as sa

revision = "<generate>"
down_revision = "<head from Task 2>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("hosts") as batch:
        batch.add_column(sa.Column("install_consent_at", sa.DateTime(), nullable=True))
    op.execute(sa.text(
        "UPDATE hosts SET install_consent_at = CURRENT_TIMESTAMP "
        "WHERE id IN (SELECT host_id FROM host_credentials WHERE kind = 'ssh_key')"
    ))


def downgrade() -> None:
    with op.batch_alter_table("hosts") as batch:
        batch.drop_column("install_consent_at")
```

```python
# backend/proxploy/api/catalog.py, replacing the body.consent check at :369
    host = db.get(Host, body.host_id)
    if host is None:
        raise HTTPException(404, "host not found")
    if host.install_consent_at is None and not body.consent:
        raise HTTPException(400, "root-consent required: this installs and runs a "
                                 "third-party script as root on the node")
    if host.install_consent_at is None and body.consent:
        host.install_consent_at = utcnow()
        db.commit()
```

- [ ] **Step 4: Run the backend suite**

Run: `cd backend && .venv/bin/python -m pytest tests/ -q -m "not pve_integration and not e2e"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/proxploy/models/__init__.py backend/proxploy/migrations/versions backend/proxploy/api/catalog.py backend/tests/
git commit -m "feat(install): move root consent from per-install to per-host"
```

---

### Task 7: Serve the install defaults

**Files:**
- Modify: `backend/proxploy/api/catalog.py` (`_serialize`)
- Test: `backend/tests/test_catalog_api.py`

**Interfaces:**
- Produces: `_serialize` already returns `default_cpu`, `default_ram_mb`,
  `default_disk_gb`, `default_os`, `default_os_version`. Verify each is present
  and add any that is not. No new source: **not** `install_methods[].resources`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_catalog_api.py, append

def test_install_defaults_come_from_the_script_not_metadata(client, dockge_row):
    """dockge is the row where the two sources disagree: the ct script says
    2/2048/18 and the cached metadata says 0/0/0. The script is what actually
    runs, and metadata is presentation-only, so the script wins."""
    body = client.get("/api/v1/catalog/dockge").json()
    assert body["default_cpu"] == 2
    assert body["default_ram_mb"] == 2048
    assert body["default_disk_gb"] == 18
```

- [ ] **Step 2: Run the test to verify it fails or passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_catalog_api.py -k install_defaults -v`
Expected: PASS if `_serialize` already carries them, in which case this task is
just the regression guard. FAIL means add the missing keys.

- [ ] **Step 3: Add any missing keys to `_serialize`**

No code needed if the test passes. If a key is missing, add it to the dict
returned by `_serialize` alongside the existing `default_*` entries.

- [ ] **Step 4: Run the backend suite**

Run: `cd backend && .venv/bin/python -m pytest tests/ -q -m "not pve_integration and not e2e"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/proxploy/api/catalog.py backend/tests/test_catalog_api.py
git commit -m "test(install): pin script-parsed defaults as the form's source"
```

---

### Task 8: The Default/Advanced choice

**Files:**
- Modify: `frontend/src/components/InstallDialog.tsx`
- Test: `frontend/src/tests/install.test.tsx`

**Interfaces:**
- Produces: a `mode` state of `'default' | 'advanced'`, Default preselected.
  Advanced reveals the fields added in Tasks 9 to 11.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/tests/install.test.tsx
it('opens on Default, and Advanced reveals the container fields', async () => {
  render(<InstallDialog slug="redis" onClose={() => {}} />)

  // Default asks nothing that has an honest default.
  expect(screen.queryByLabelText(/vCPU/i)).not.toBeInTheDocument()

  await userEvent.click(screen.getByRole('radio', { name: /advanced/i }))
  expect(screen.getByLabelText(/vCPU/i)).toBeInTheDocument()
})

it('does not require a CTID to submit', async () => {
  render(<InstallDialog slug="redis" onClose={() => {}} />)
  await selectHost('host-01')
  await userEvent.type(screen.getByPlaceholderText('App name'), 'redis')
  expect(screen.getByRole('button', { name: 'Install' })).toBeEnabled()
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/tests/install.test.tsx --no-file-parallelism`
Expected: FAIL, no Advanced control, and Install disabled without a CTID

- [ ] **Step 3: Write the implementation**

In `InstallDialog.tsx`, add the mode state and drop `ctid` from `canSubmit`:

```tsx
const [mode, setMode] = useState<'default' | 'advanced'>('default')
// CTID is no longer required. Blank means the node assigns the next free id.
const canSubmit = hostId != null && name.trim() !== '' && (consented || consent)
```

Render the choice above the fields, and gate the advanced block on
`mode === 'advanced'`.

- [ ] **Step 4: Run the frontend suite**

Run: `cd frontend && npx vitest run --no-file-parallelism` then `npx tsc -b && npx oxlint`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/InstallDialog.tsx frontend/src/tests/install.test.tsx
git commit -m "feat(install): add the Default and Advanced choice"
```

---

### Task 9: The content-filtered storage pickers

**Files:**
- Create: `frontend/src/components/install/StorageFields.tsx`
- Modify: `frontend/src/components/InstallDialog.tsx`
- Test: `frontend/src/tests/install.test.tsx`

**Interfaces:**
- Consumes: `api<StorageRow[]>('/storage')` where
  `StorageRow = { host_id: number; node: string; storage: string; content: string[] }`,
  the same query `VmCreateWizard.tsx:68` already makes.
- Produces: `<StorageFields hostId={number|null} value={...} onChange={...} />`
  emitting `container_storage` and `template_storage` into `overrides`.

- [ ] **Step 1: Write the failing tests**

```tsx
it('offers only rootdir pools for the container and vztmpl for the template', async () => {
  mockStorage([
    { host_id: 1, node: 'pve', storage: 'local', content: ['vztmpl', 'iso'] },
    { host_id: 1, node: 'pve', storage: 'local-lvm', content: ['rootdir'] },
  ])
  render(<InstallDialog slug="redis" onClose={() => {}} />)
  await openAdvanced()

  // A vztmpl-only pool as the rootfs fails at pct create with a raw Proxmox
  // error, AFTER the form said it was fine.
  expect(containerOptions()).toEqual(['local-lvm'])
  expect(templateOptions()).toEqual(['local'])
})

it('re-queries candidates when the target host changes', async () => {
  render(<InstallDialog slug="redis" onClose={() => {}} />)
  await openAdvanced()
  await selectHost('host-02')
  expect(containerOptions()).toEqual(['host02-lvm'])
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/tests/install.test.tsx --no-file-parallelism`
Expected: FAIL, no storage controls

- [ ] **Step 3: Write the implementation**

```tsx
// frontend/src/components/install/StorageFields.tsx
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'

type StorageRow = { host_id: number; node: string; storage: string; content: string[] }

/**
 * The two storage pickers, filtered by content type.
 *
 * `rootdir` and `vztmpl` are different questions: a pool that holds templates
 * cannot necessarily hold a rootfs. Offering every pool for both fields lets
 * an operator choose a vztmpl-only pool as the rootfs, which fails at
 * `pct create` with a raw Proxmox error after this form told them it was fine.
 *
 * Pools are per host, so the candidate list is keyed on hostId and a value
 * that is not valid on the newly selected host is cleared rather than
 * submitted.
 */
export function StorageFields({ hostId, container, template, onChange }: {
  hostId: number | null
  container: string
  template: string
  onChange: (next: { container: string; template: string }) => void
}) {
  const storages = useQuery({
    queryKey: ['storage', hostId],
    enabled: hostId != null,
    queryFn: () => api<StorageRow[]>('/storage'),
  })
  const rows = (storages.data ?? []).filter((r) => r.host_id === hostId)
  const forContent = (c: string) =>
    rows.filter((r) => r.content.includes(c)).map((r) => r.storage)

  const rootdir = forContent('rootdir')
  const vztmpl = forContent('vztmpl')

  return (
    <>
      <label htmlFor="container-storage">Container storage</label>
      <select id="container-storage" value={container}
        onChange={(e) => onChange({ container: e.target.value, template })}>
        <option value="">Select a pool…</option>
        {rootdir.map((s) => <option key={s} value={s}>{s}</option>)}
      </select>

      <label htmlFor="template-storage">Template storage</label>
      <select id="template-storage" value={template}
        onChange={(e) => onChange({ container, template: e.target.value })}>
        <option value="">Select a pool…</option>
        {vztmpl.map((s) => <option key={s} value={s}>{s}</option>)}
      </select>
    </>
  )
}
```

- [ ] **Step 4: Run the frontend suite**

Run: `cd frontend && npx vitest run --no-file-parallelism` then `npx tsc -b && npx oxlint`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/install frontend/src/components/InstallDialog.tsx frontend/src/tests/install.test.tsx
git commit -m "feat(install): storage pickers filtered by content type"
```

---

### Task 10: The core container fields

**Files:**
- Modify: `frontend/src/components/InstallDialog.tsx`
- Modify: `frontend/src/api/catalog.ts` (`InstallVars`)
- Test: `frontend/src/tests/install.test.tsx`

**Interfaces:**
- Consumes: the `default_*` fields from Task 7.
- Produces: `overrides` populated with `cpu`, `ram`, `disk`, `os`, `version`,
  `hostname`, `unprivileged`. The backend prefixes each with `var_`.

**The variable names are the whole risk.** A wrong name does not error: the
installer ignores it, uses its own default, and reports success, so the operator
gets defaults while believing they got their choices.

- [ ] **Step 1: Write the failing test**

```tsx
it('emits only variable names build.func actually reads', async () => {
  // Pinned from build.func at the catalog's upstream_sha. A typo or an
  // upstream rename must fail here rather than silently sending an override
  // into the void.
  const KNOWN = new Set([
    'brg', 'container_storage', 'cpu', 'ctid', 'disk', 'fuse', 'gateway',
    'gpu', 'hostname', 'mtu', 'nesting', 'net', 'os', 'pw', 'ram',
    'searchdomain', 'ssh', 'ssh_authorized_key', 'tags', 'template_storage',
    'timezone', 'unprivileged', 'version', 'vlan',
  ])
  render(<InstallDialog slug="redis" onClose={() => {}} />)
  await openAdvanced()
  await fillEveryField()
  const sent = capturedSubmit().overrides
  for (const key of Object.keys(sent)) expect(KNOWN.has(key)).toBe(true)
})

it('prefills from the script-parsed defaults', async () => {
  render(<InstallDialog slug="dockge" onClose={() => {}} />)
  await openAdvanced()
  expect(screen.getByLabelText(/RAM/i)).toHaveValue(2048)  // not metadata's 0
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/tests/install.test.tsx --no-file-parallelism`
Expected: FAIL, no fields to fill

- [ ] **Step 3: Write the implementation**

Add the core inputs to the advanced block, each prefilled from the catalog
entry's `default_*` value, writing into an `overrides` object keyed exactly as
the test's `KNOWN` set spells them.

- [ ] **Step 4: Run the frontend suite**

Run: `cd frontend && npx vitest run --no-file-parallelism` then `npx tsc -b && npx oxlint`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/InstallDialog.tsx frontend/src/api/catalog.ts frontend/src/tests/install.test.tsx
git commit -m "feat(install): the core container customization fields"
```

---

### Task 11: The collapsed advanced group, with validation

**Files:**
- Create: `frontend/src/components/install/AdvancedOptions.tsx`
- Test: `frontend/src/tests/install.test.tsx`

**Interfaces:**
- Produces: `gpu`, `nesting`, `tags`, `timezone`, `ssh`, `ssh_authorized_key`,
  `net`, `gateway`, `vlan`, `mtu` into `overrides`.

- [ ] **Step 1: Write the failing tests**

```tsx
it('rejects a malformed gateway, CIDR, VLAN and MTU', async () => {
  render(<InstallDialog slug="redis" onClose={() => {}} />)
  await openAdvanced()
  await openMoreOptions()

  await userEvent.type(screen.getByLabelText(/Gateway/i), '999.1.1.1')
  expect(screen.getByRole('button', { name: 'Install' })).toBeDisabled()
  expect(screen.getByText(/not a valid IP/i)).toBeInTheDocument()
})

it('accepts a blank network and says it means DHCP', async () => {
  // build.func:1106 is NET=${var_net:-"dhcp"}. This is upstream's behaviour,
  // not our convention, so blank must not read as broken.
  render(<InstallDialog slug="redis" onClose={() => {}} />)
  await openAdvanced()
  await openMoreOptions()
  expect(screen.getByText(/blank means DHCP/i)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Install' })).toBeEnabled()
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/tests/install.test.tsx --no-file-parallelism`
Expected: FAIL, no advanced group

- [ ] **Step 3: Write the implementation**

```tsx
// frontend/src/components/install/AdvancedOptions.tsx

/**
 * The collapsed group. gpu and nesting are the highest-demand options in the
 * whole form: GPU passthrough is what Plex and Jellyfin need for hardware
 * transcoding, and nesting is what Docker-based apps need to run containers
 * inside the LXC. Both are booleans that add capability, so neither needs
 * validation.
 *
 * Static networking does. It is where an operator can lock themselves out of
 * a container they just created, so net, gateway, vlan and mtu get format
 * validation. Format only: we do not attempt to prove a gateway is reachable.
 * The goal is that this group cannot QUIETLY produce an unreachable container
 * through a typo.
 */
const IPV4 = /^(\d{1,3}\.){3}\d{1,3}$/
const CIDR = /^(\d{1,3}\.){3}\d{1,3}\/\d{1,2}$/

export function validateNetworking(v: {
  net: string; gateway: string; vlan: string; mtu: string
}): Record<string, string> {
  const errors: Record<string, string> = {}
  if (v.net && !CIDR.test(v.net)) errors.net = 'Use CIDR, for example 192.168.1.50/24'
  if (v.gateway && !IPV4.test(v.gateway)) errors.gateway = 'Not a valid IP address'
  if (v.vlan && !(Number(v.vlan) >= 1 && Number(v.vlan) <= 4094)) {
    errors.vlan = 'VLAN must be between 1 and 4094'
  }
  if (v.mtu && !(Number(v.mtu) >= 576 && Number(v.mtu) <= 9000)) {
    errors.mtu = 'MTU must be between 576 and 9000'
  }
  return errors
}
```

- [ ] **Step 4: Run the frontend suite**

Run: `cd frontend && npx vitest run --no-file-parallelism` then `npx tsc -b && npx oxlint`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/install/AdvancedOptions.tsx frontend/src/tests/install.test.tsx
git commit -m "feat(install): the collapsed advanced options and their validation"
```

---

### Task 12: CTID collision validation in the form

**Files:**
- Modify: `frontend/src/components/InstallDialog.tsx`
- Test: `frontend/src/tests/install.test.tsx`

**Interfaces:**
- Consumes: the existing guest listing the app already fetches for the Apps and
  Cluster pages. Do not add an endpoint if one already returns per-host guest
  ids; check `frontend/src/api/` first.

- [ ] **Step 1: Write the failing tests**

```tsx
it('blocks a CTID already in use on the selected host', async () => {
  render(<InstallDialog slug="redis" onClose={() => {}} />)
  await openAdvanced()
  await selectHost('host-01')
  await userEvent.type(screen.getByLabelText(/Container ID/i), '100')

  expect(screen.getByText(/CTID 100 is already in use on host-01/i)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Install' })).toBeDisabled()
})

it('re-checks the CTID when the host changes, because ids are per host', async () => {
  render(<InstallDialog slug="redis" onClose={() => {}} />)
  await openAdvanced()
  await selectHost('host-01')
  await userEvent.type(screen.getByLabelText(/Container ID/i), '100')
  await selectHost('host-02')   // 100 is free there
  expect(screen.getByRole('button', { name: 'Install' })).toBeEnabled()
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/tests/install.test.tsx --no-file-parallelism`
Expected: FAIL, no collision check

- [ ] **Step 3: Write the implementation**

Add the check against the selected host's guest ids, keyed on `hostId` so it
re-runs on host change. Add a comment recording that **the backend is the real
gate**: `run_install`'s `_lxc_ids` pre-check stays authoritative because a guest
can be created between this validation and submit, and client-side validation is
bypassable.

- [ ] **Step 4: Run the frontend suite**

Run: `cd frontend && npx vitest run --no-file-parallelism` then `npx tsc -b && npx oxlint`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/InstallDialog.tsx frontend/src/tests/install.test.tsx
git commit -m "feat(install): validate a typed CTID against the selected host"
```

---

### Task 13: Default asks the storage question, once, and remembers

**Files:**
- Modify: `frontend/src/components/InstallDialog.tsx`
- Modify: `backend/proxploy/api/catalog.py` (persist the choice)
- Test: `frontend/src/tests/install.test.tsx`, `backend/tests/test_catalog_install_api.py`

**Interfaces:**
- Consumes: `Host.default_container_storage` / `default_template_storage`
  (Task 2), the content-filtered candidate lists (Task 9).
- Produces: `InstallIn.remember_storage: bool = True`. When the operator picks
  a pool and this is set, the API writes it to the host.

This is the task that closes the loop. Tasks 2 and 3 read the remembered pools;
nothing writes them yet, so without this the refusal in Task 3 is permanent.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/tests/install.test.tsx
it('Default asks the storage question only when there is a real choice', async () => {
  // One candidate is not a choice. Default stays one click.
  mockStorage([
    { host_id: 1, node: 'pve', storage: 'local', content: ['vztmpl'] },
    { host_id: 1, node: 'pve', storage: 'local-lvm', content: ['rootdir'] },
  ])
  render(<InstallDialog slug="redis" onClose={() => {}} />)
  await selectHost('host-01')
  expect(screen.queryByLabelText(/Container storage/i)).not.toBeInTheDocument()
})

it('Default asks when the host has two pools, because there is no honest default', async () => {
  mockStorage([
    { host_id: 1, node: 'pve', storage: 'local', content: ['vztmpl'] },
    { host_id: 1, node: 'pve', storage: 'lvm-a', content: ['rootdir'] },
    { host_id: 1, node: 'pve', storage: 'lvm-b', content: ['rootdir'] },
  ])
  render(<InstallDialog slug="redis" onClose={() => {}} />)
  await selectHost('host-01')
  expect(screen.getByLabelText(/Container storage/i)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Install' })).toBeDisabled()
})

it('shows the pools it will use, so remembering never becomes deciding silently', async () => {
  mockHostWithRememberedStorage({ container: 'lvm-a', template: 'local' })
  render(<InstallDialog slug="redis" onClose={() => {}} />)
  await selectHost('host-01')
  // Displayed as text, not asked as a question.
  expect(screen.getByText(/lvm-a/)).toBeInTheDocument()
  expect(screen.queryByLabelText(/Container storage/i)).not.toBeInTheDocument()
})
```

```python
# backend/tests/test_catalog_install_api.py
def test_the_chosen_pool_is_remembered_on_the_host(client, a_host, db_session):
    client.post("/api/v1/catalog/redis/install", json={
        "host_id": a_host.id, "name": "redis", "consent": True,
        "overrides": {"container_storage": "lvm-b", "template_storage": "local"},
    })
    db_session.refresh(a_host)
    assert a_host.default_container_storage == "lvm-b"
    assert a_host.default_template_storage == "local"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/tests/install.test.tsx --no-file-parallelism`
and `cd backend && .venv/bin/python -m pytest tests/test_catalog_install_api.py -k remembered -v`
Expected: FAIL on both

- [ ] **Step 3: Write the implementation**

Frontend, in `InstallDialog.tsx`:

```tsx
// Default asks no questions THAT HAVE AN HONEST DEFAULT. Two rootdir pools
// have no default: build.func has none and we do not invent one, so this is
// the one question Default has to ask. One candidate is not a choice, and a
// remembered answer is shown rather than re-asked.
const needsStoragePrompt =
  hostId != null
  && !host?.default_container_storage
  && rootdirPools.length > 1

// Remembering must not become deciding silently: when we already know the
// pools, DISPLAY them rather than asking again.
const showsStorageSummary = hostId != null && !needsStoragePrompt
```

Backend, in `install_catalog_entry` after the consent block:

```python
    # Remember the operator's choice so the question is asked once per host
    # rather than on every install. Only ever written from a value the operator
    # actually supplied: this never records a pool that Proxploy resolved for
    # them, because it never resolves one for them.
    if body.remember_storage:
        for key, column in (("container_storage", "default_container_storage"),
                            ("template_storage", "default_template_storage")):
            chosen = (body.overrides.get(key) or "").strip()
            if chosen and getattr(host, column) != chosen:
                setattr(host, column, chosen)
        db.commit()
```

- [ ] **Step 4: Run both suites**

Run: `cd backend && .venv/bin/python -m pytest tests/ -q -m "not pve_integration and not e2e"`
then `cd frontend && npx vitest run --no-file-parallelism` and `npx tsc -b && npx oxlint`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/InstallDialog.tsx backend/proxploy/api/catalog.py backend/tests/ frontend/src/tests/
git commit -m "feat(install): ask the storage question once per host, and show the answer"
```

---

## Known weaknesses in this plan

Stated rather than hidden, so the implementer knows where to think rather than
copy:

- **Tasks 10 and 12 step 3 describe the change without a full code block.** The
  test in each names the exact contract (the `KNOWN` variable-name set, the
  collision message), so the shape is pinned, but the implementer writes the
  markup. Every other code step carries real code.
- **Fixture names are indicative.** `app_with_fake_pve`, `host_id`, `fake_ssh`,
  `mockStorage`, `openAdvanced` and friends follow the existing suites'
  conventions but may not match exactly. Read
  `backend/tests/test_appstore_install.py` and
  `frontend/src/tests/install.test.tsx` before writing Task 1, and use whatever
  those files already use.
- **Task 5's "one container appeared" rule** assumes a install creates exactly
  one CT. That is true for every `ct/` script today, and the failure is loud
  rather than silent, but it is an assumption rather than a guarantee.

## After the plan

Part A's correctness cannot be established by this suite. The fakes model `pct`
over SSH but not `pvesm status`, which is exactly why the bug survived. Perform
the three multi-storage checks in `docs/12-hardware-verification.md` on a host
with at least two `rootdir` pools and two `vztmpl` pools, and record the date
and PVE version against each entry.
