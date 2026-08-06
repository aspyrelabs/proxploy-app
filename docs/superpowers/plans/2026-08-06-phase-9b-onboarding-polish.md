# Phase 9b — Onboarding, empty states, error states, light theme

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a stranger's first hour work — onboarding that survives a reload, failures that say what actually failed, lists that never lie about being empty — and prove the four Phase 9 DoD clauses by executing them in a real browser.

**Architecture:** Three backend changes (a Proxmox error taxonomy, an SSH verification endpoint, one new `/meta/onboarding` field) unblock a wizard rebuilt on server-derived state. On the frontend, one shared four-state query component replaces 40 hand-rolled `?? []` fallbacks, a themed route `errorComponent` closes finding F1, and two hardcoded colours become tokens. A test-only launcher lets Playwright drive the real UI against `FakePVE` + `FakeSSHConnection`, so onboarding → app install → VM create → backup schedule runs end to end, in both themes, gated in CI.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (backend), React 19 + Vite + Tailwind v4 + TanStack Router/Query (frontend), Vitest + Testing Library (unit), Playwright + Chromium (e2e).

**Spec:** `docs/superpowers/specs/2026-08-06-phase-9b-onboarding-polish-design.md`

---

## Global Constraints

Every task's requirements implicitly include this section.

- **Python floor is 3.11**, not 3.12 — Debian 12 is the real LXC target. CI runs both (`backend` = 3.12, `backend-py311` = 3.11).
- **Backend tests:** `cd backend && .venv/bin/python -m pytest tests/ -q -m "not pve_integration and not e2e"`. Baseline entering this phase: **810 passed, 2 skipped, 4 deselected**. Never let this go down.
- **Frontend tests:** `cd frontend && npx vitest run --no-file-parallelism`. Baseline: **205 passed across 37 files**. The `--no-file-parallelism` flag is required — unrelated suites flake under vitest's default parallelism on this box and pass in isolation.
- **Frontend lint:** `npm run lint` (oxlint) must stay exit 0. It currently emits 30 warnings, 0 errors; do not add new warning classes.
- **Commit directly to `main`.** No branches. Every task ends in a commit.
- **Never use a literal colour in frontend code.** Every colour comes from `styles/tokens.css` via a Tailwind utility (`bg-elev`, `text-text-2`, …) or `var(--token)`. Task 11 adds a test that enforces this.
- **`EmptyState` is for "nothing here", never for "loading" and never for "failed".** After Task 5 those are three different renderings.
- **No test-only branches in shipped code.** Fakes are injected through `create_app(proxmox_factory=…, ssh_factory=…)`. An env var honoured by `main.py` that swaps a core client is a backdoor and is rejected — see spec §6.
- **Backend route shape** (established by `api/hosts.py:1-2`): auth → RBAC → entitlement → work → audit. Every new mutating route follows it and calls `write_audit`.
- **Auth deps are module-level singletons** (`_read = authorize("meta", "read")`), reused across routes in a file — FastAPI's dependency cache is keyed on the callable, so this collapses repeated checks into one per request.

---

## Task Order and Dependencies

```
Backend, independent, do first:
  Task 1  Proxmox error taxonomy          -> unblocks 13
  Task 2  SSH verify endpoint + migration -> unblocks 3, 14
  Task 3  ssh_pending on /meta/onboarding -> unblocks 12

Frontend primitives, independent of the backend:
  Task 4  EmptyState gains an action slot -> unblocks 10
  Task 5  The four-state query component  -> unblocks 6, 7, 8, 10
  Task 9  Themed errorComponent (F1)      -> independent
  Task 11 Theme literals + hex guard      -> independent

Sweeps, after Task 5:
  Task 6  25 page-level content lists
  Task 7  15 selects, dead code, loading-as-empty
  Task 8  3 false-negative single-value queries

Wizard, after 1/2/3:
  Task 12 Server-derived step
  Task 13 Skippable host + honest errors   (needs 1)
  Task 14 Verified SSH step                (needs 2)

Proof, after everything above:
  Task 15 E2E launcher with fakes
  Task 16 The stranger journey
  Task 17 Light-mode leg
  Task 18 E2E in CI
  Task 19 DoD verification, notes, buildlog
```

Tasks 1–2, 4, 5, 9, 11 can run in parallel. Tasks 6, 7, 8 can run in parallel once 5 lands. Tasks 16 and 17 both need 15.

---

## Task 1: A Proxmox error you can act on

**Files:**
- Modify: `backend/proxploy/services/proxmox.py` (the `ProxmoxError` class and `_wrap`)
- Modify: `backend/proxploy/api/hosts.py` (the two `except ProxmoxError` blocks, `hosts.py:76-83` and `hosts.py:100-106`)
- Test: `backend/tests/test_hosts.py`

**Interfaces:**
- Produces, for Task 13: `ProxmoxError.kind: str`, one of `"unreachable"`, `"auth"`, `"tls_fingerprint"`, `"refused"`, `"unknown"`. Both `POST /hosts/probe` and `POST /hosts` return `502` with body `{"error": "<kind>", "detail": "<scrubbed message>"}`.

Today every probe failure — a wrong token, an unreachable box, a changed TLS fingerprint, an SSRF refusal — arrives as the same `ProxmoxError` and becomes `HTTPException(502, str(e))`. A stranger with a typo'd token and a stranger whose firewall is closed get identical copy and take different actions. `_wrap` is documented as "the ONE place a proxmoxer/requests exception becomes our own", so it is the one place to classify.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_hosts.py`:

```python
def test_probe_reports_unreachable_as_a_kind(tmp_path, csrf_header, bootstrap_admin):
    """A closed port and a bad token must not read identically to the wizard."""
    from fastapi.testclient import TestClient
    from proxploy.config import Settings
    from proxploy.main import create_app

    def unreachable(**kwargs):
        raise ConnectionError("connection refused")

    s = Settings(db_url=f"sqlite:///{tmp_path}/p.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key")
    with TestClient(create_app(s, proxmox_factory=unreachable)) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/hosts/probe", headers=csrf_header(c), json={
            "address": "https://10.0.0.5:8006", "token_id": "u@pve!t",
            "token_secret": "s", "verify_tls": True})
    assert r.status_code == 502
    assert r.json()["detail"]["error"] == "unreachable"


def test_probe_reports_auth_failure_as_its_own_kind(tmp_path, csrf_header, bootstrap_admin):
    from fastapi.testclient import TestClient
    from proxploy.config import Settings
    from proxploy.main import create_app

    def denied(**kwargs):
        raise PermissionError("401 authentication failure")

    s = Settings(db_url=f"sqlite:///{tmp_path}/a.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key")
    with TestClient(create_app(s, proxmox_factory=denied)) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/hosts/probe", headers=csrf_header(c), json={
            "address": "https://10.0.0.5:8006", "token_id": "u@pve!t",
            "token_secret": "s", "verify_tls": True})
    assert r.status_code == 502
    assert r.json()["detail"]["error"] == "auth"


def test_error_kind_never_leaks_the_token_secret(tmp_path, csrf_header, bootstrap_admin):
    """The scrubbing _wrap already does must survive the new structure."""
    from fastapi.testclient import TestClient
    from proxploy.config import Settings
    from proxploy.main import create_app

    def leaky(**kwargs):
        raise RuntimeError("failed using secret super-secret-value")

    s = Settings(db_url=f"sqlite:///{tmp_path}/l.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key")
    with TestClient(create_app(s, proxmox_factory=leaky)) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/hosts/probe", headers=csrf_header(c), json={
            "address": "https://10.0.0.5:8006", "token_id": "u@pve!t",
            "token_secret": "super-secret-value", "verify_tls": True})
    assert "super-secret-value" not in r.text
```

**Before writing these, read `backend/tests/test_hosts.py:9-27`** for the `pve_client` fixture and confirm the exact names of the `csrf_header` and `bootstrap_admin` fixtures in `backend/tests/conftest.py`. Match them; do not invent fixture names.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/python -m pytest tests/test_hosts.py -q -k "kind or leak"`
Expected: FAIL — `detail` is currently a plain string, so `r.json()["detail"]["error"]` raises `TypeError: string indices must be integers`.

- [ ] **Step 3: Give `ProxmoxError` a kind**

In `backend/proxploy/services/proxmox.py`, replace the bare exception:

```python
class ProxmoxError(RuntimeError):
    """A Proxmox interaction that failed, classified so a caller can tell a
    stranger what to actually do about it. `kind` is a stable machine string;
    the message stays human and is always secret-scrubbed by _wrap.
    """

    def __init__(self, message: str, kind: str = "unknown"):
        super().__init__(message)
        self.kind = kind
```

In `_wrap` (around `proxmox.py:199-217`), classify before raising. **Read the existing body first** — it already scrubs the token secret and token id out of the message, and that scrubbing must run unchanged on the message you pass through:

```python
def _classify(exc: BaseException) -> str:
    """Map an underlying transport/auth failure onto a kind the UI can act on.
    Substring matching is deliberate and lives HERE rather than in the
    frontend: proxmoxer and requests do not expose typed failures for these,
    and one fuzzy match in one place beats the same match spread across
    call sites in another language.
    """
    if isinstance(exc, SSRFRefused):          # whatever resolve_target raises
        return "refused"
    text = str(exc).lower()
    if "fingerprint" in text:
        return "tls_fingerprint"
    if isinstance(exc, PermissionError) or "401" in text or "authentication" in text:
        return "auth"
    if isinstance(exc, (ConnectionError, TimeoutError)) or "refused" in text \
            or "timed out" in text or "unreachable" in text or "resolve" in text:
        return "unreachable"
    return "unknown"
```

`resolve_target`'s SSRF refusals currently raise plain `ProxmoxError` with messages like *"refusing to connect to … it resolves to …, which is a link-local address"*. **Check whether a distinct exception type exists**; if it does not, match on the literal prefix `"refusing to connect"` instead of inventing an `SSRFRefused` class, and delete that first branch. Do not add a new exception type just to satisfy the snippet above.

Then in `_wrap`, raise `ProxmoxError(scrubbed_message, kind=_classify(exc))`. Any existing `raise ProxmoxError(...)` sites elsewhere in the file keep working — `kind` defaults to `"unknown"`.

- [ ] **Step 4: Return the kind from both routes**

In `backend/proxploy/api/hosts.py`, both handlers change from `raise HTTPException(502, str(e))` to:

```python
    except ProxmoxError as e:
        raise HTTPException(502, {"error": e.kind, "detail": str(e)})
```

There are exactly two sites: `probe` (`hosts.py:76-83`) and `create_host` (`hosts.py:100-106`). In `create_host` the `write_audit(..., result="error", ...)` call stays exactly where it is, before the raise.

Then `grep -rn "except ProxmoxError" backend/proxploy/` and check every other catcher in the codebase. Any that formats `str(e)` into a user-facing 502 should get the same treatment; any that logs or swallows can stay. List what you found in the commit message.

- [ ] **Step 5: Run the tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_hosts.py -q`
Expected: PASS, including the pre-existing host tests. If an existing test asserted `detail` was a string, update it — it was pinning the shape this task deliberately changes.

- [ ] **Step 6: Full backend suite, then commit**

Run: `cd backend && .venv/bin/python -m pytest tests/ -q -m "not pve_integration and not e2e"`
Expected: ≥ 810 passed.

```bash
git add backend/proxploy/services/proxmox.py backend/proxploy/api/hosts.py backend/tests/test_hosts.py
git commit -m "feat(hosts): classify probe failures so the wizard can say what broke"
```

---

## Task 2: Verifying the SSH key actually works

**Files:**
- Create: `backend/proxploy/migrations/versions/<rev>_ssh_verified_at.py` (generated, not hand-numbered)
- Modify: `backend/proxploy/models.py` (`HostCredential`)
- Modify: `backend/proxploy/api/hosts.py` (new route)
- Test: `backend/tests/test_hosts_ssh_verify.py` (new file)

**Interfaces:**
- Consumes: `SSHExecutor.run_for_host(sessionmaker, secretstore, host_id, host, command, *, pinned_fingerprint, on_new_fingerprint, env=None, on_line=None, timeout_s=1800.0) -> int` from `backend/proxploy/executor/ssh.py:134`.
- Produces, for Tasks 3 and 14: `POST /hosts/{host_id}/ssh/verify` → `200 {"verified": true, "verified_at": "<iso8601>"}` or `502 {"error": "<kind>", "detail": "<message>"}` where kind is one of `"no_key"`, `"host_key_mismatch"`, `"unreachable"`, `"timeout"`, `"command_failed"`. Also `HostCredential.ssh_verified_at: datetime | None`.

The wizard's authorize step is an honor-system button today. A mis-pasted `authorized_keys` line fails much later, at the first app install, far from its cause. This task makes the step provable — and the stored result is what Task 3 reads.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_hosts_ssh_verify.py`:

```python
"""POST /hosts/{id}/ssh/verify — the wizard's authorize step, made honest."""
import pytest

from tests.fakes.pve import FakePVE
from tests.fakes.ssh import FakeSSHConnection, make_fake_connect_factory


def _host_with_ssh(client, csrf_header):
    """Create a host with SSH enrolment, returning its id."""
    r = client.post("/api/v1/hosts", headers=csrf_header(client), json={
        "name": "pve-01", "address": "https://10.0.0.5:8006",
        "token_id": "proxploy@pve!t", "token_secret": "s",
        "verify_tls": False, "ssh_enroll": True, "ssh_consent": True})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_verify_marks_the_credential_verified(tmp_path, csrf_header, bootstrap_admin):
    from fastapi.testclient import TestClient
    from proxploy.config import Settings
    from proxploy.main import create_app
    from tests.fakes.pve import make_fake_factory

    fake = FakeSSHConnection(host_key_fingerprint="SHA256:abc",
                             stdout_lines=["ok"], stderr_lines=[], exit_status=0)
    s = Settings(db_url=f"sqlite:///{tmp_path}/v.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key")
    app = create_app(s, proxmox_factory=make_fake_factory(FakePVE()),
                     ssh_factory=make_fake_connect_factory(fake))
    with TestClient(app) as c:
        bootstrap_admin(c)
        hid = _host_with_ssh(c, csrf_header)
        r = c.post(f"/api/v1/hosts/{hid}/ssh/verify", headers=csrf_header(c))
    assert r.status_code == 200, r.text
    assert r.json()["verified"] is True
    assert r.json()["verified_at"]


def test_verify_reports_a_nonzero_exit_as_command_failed(tmp_path, csrf_header, bootstrap_admin):
    """The key authenticated but the command did not run — a real, different
    failure from 'the key is not authorized', and the copy must differ."""
    from fastapi.testclient import TestClient
    from proxploy.config import Settings
    from proxploy.main import create_app
    from tests.fakes.pve import make_fake_factory

    fake = FakeSSHConnection(host_key_fingerprint="SHA256:abc",
                             stdout_lines=[], stderr_lines=["nope"], exit_status=1)
    s = Settings(db_url=f"sqlite:///{tmp_path}/f.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key")
    app = create_app(s, proxmox_factory=make_fake_factory(FakePVE()),
                     ssh_factory=make_fake_connect_factory(fake))
    with TestClient(app) as c:
        bootstrap_admin(c)
        hid = _host_with_ssh(c, csrf_header)
        r = c.post(f"/api/v1/hosts/{hid}/ssh/verify", headers=csrf_header(c))
    assert r.status_code == 502
    assert r.json()["error"] == "command_failed"


def test_verify_on_a_host_without_ssh_enrolment_is_no_key(tmp_path, csrf_header, bootstrap_admin):
    from fastapi.testclient import TestClient
    from proxploy.config import Settings
    from proxploy.main import create_app
    from tests.fakes.pve import make_fake_factory

    s = Settings(db_url=f"sqlite:///{tmp_path}/n.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key")
    app = create_app(s, proxmox_factory=make_fake_factory(FakePVE()))
    with TestClient(app) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/hosts", headers=csrf_header(c), json={
            "name": "pve-02", "address": "https://10.0.0.6:8006",
            "token_id": "proxploy@pve!t", "token_secret": "s",
            "verify_tls": False})
        hid = r.json()["id"]
        r = c.post(f"/api/v1/hosts/{hid}/ssh/verify", headers=csrf_header(c))
    assert r.status_code == 502
    assert r.json()["error"] == "no_key"
```

**Read `backend/tests/fakes/ssh.py` first** and match `FakeSSHConnection`'s real constructor signature — the arguments above come from `tests/test_app_update_job.py:52-66` but confirm them rather than trusting this plan.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/python -m pytest tests/test_hosts_ssh_verify.py -q`
Expected: FAIL — 404, the route does not exist.

- [ ] **Step 3: Add the column and generate the migration**

In `backend/proxploy/models.py`, add to `HostCredential`:

```python
    # Set by POST /hosts/{id}/ssh/verify. NULL means "never confirmed working"
    # — which is exactly what the onboarding wizard's authorize step reads to
    # know whether it still has something to ask the operator for.
    ssh_verified_at = Column(DateTime, nullable=True)
```

Match the file's existing column style (it may use `mapped_column`/`Mapped[...]`; read a neighbouring model and follow it).

Generate the migration rather than hand-writing a revision id:

```bash
cd backend && .venv/bin/alembic -c alembic.ini revision --autogenerate -m "ssh_verified_at on host_credentials"
```

Read the generated file. Autogenerate on SQLite frequently emits a batch-mode-less `ALTER`; confirm it matches the style of the existing migrations in `backend/proxploy/migrations/versions/` and that `downgrade()` is populated.

Then: `cd backend && .venv/bin/alembic -c alembic.ini upgrade head && .venv/bin/alembic -c alembic.ini heads`
Expected: one head, and it is the new revision.

- [ ] **Step 4: Implement the route**

In `backend/proxploy/api/hosts.py`. Note `SSHExecutor.run_for_host` is **async** and this router's handlers are sync — declare this one `async def`.

```python
@router.post("/{host_id}/ssh/verify")
async def verify_ssh(host_id: int, request: Request, db=Depends(get_db),
                     user: User = Depends(_manage)):
    """Prove the enrolled key actually opens a root shell on the node.

    The wizard used to take the operator's word for it, so a mis-pasted
    authorized_keys line surfaced at the first app install instead of here,
    far from its cause. `true` is the whole command: this asks one question
    — does the key authenticate and can we run anything — and nothing else.
    """
    host = db.query(Host).filter_by(id=host_id).one_or_none()
    if host is None:
        raise HTTPException(404, "host not found")
    cred = db.query(HostCredential).filter_by(host_id=host_id,
                                              kind="ssh_key").one_or_none()
    if cred is None:
        raise HTTPException(502, {"error": "no_key",
                                  "detail": "this host has no enrolled SSH key"})

    from proxploy.executor.ssh import SSHExecutor, SSHHostKeyMismatch

    seen: list[str] = []
    executor = SSHExecutor(connect_factory=request.app.state.ssh_connect_factory)
    try:
        code = await executor.run_for_host(
            request.app.state.sessionmaker, request.app.state.secretstore,
            host_id, _ssh_target(host.address), "true",
            pinned_fingerprint=host.ssh_host_fingerprint,
            on_new_fingerprint=seen.append, timeout_s=20.0)
    except SSHHostKeyMismatch as e:
        raise HTTPException(502, {"error": "host_key_mismatch", "detail": str(e)})
    except LookupError as e:
        raise HTTPException(502, {"error": "no_key", "detail": str(e)})
    except TimeoutError as e:
        raise HTTPException(502, {"error": "timeout", "detail": str(e)})
    except OSError as e:
        raise HTTPException(502, {"error": "unreachable", "detail": str(e)})

    if code != 0:
        raise HTTPException(502, {"error": "command_failed",
                                  "detail": f"the key authenticated but `true` exited {code}"})
    if seen and not host.ssh_host_fingerprint:
        host.ssh_host_fingerprint = seen[0]
    cred.ssh_verified_at = utcnow()
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id, action="host.ssh_verify",
                target_type="host", target_id=host_id,
                ip=request.client.host if request.client else None)
    return {"verified": True, "verified_at": cred.ssh_verified_at.isoformat()}
```

Three things this snippet assumes that you **must verify against the real code before writing it**, and correct in place if they differ — do not force the code to match the plan:

1. `host.ssh_host_fingerprint` — the field name where a node's pinned SSH host key lives. Grep `models.py` for the real one; app-install code already reads it, so `grep -rn "pinned_fingerprint=" backend/proxploy/` shows the canonical accessor.
2. `request.app.state.sessionmaker` and `request.app.state.secretstore` — confirm both names in `backend/proxploy/main.py`.
3. `_ssh_target(host.address)` — `run_for_host` wants a hostname, not a URL. Find how the existing app-install path derives it (`grep -rn "run_for_host" backend/proxploy/`) and reuse that helper rather than writing a second one.

- [ ] **Step 5: Run the tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_hosts_ssh_verify.py -q`
Expected: 3 passed.

- [ ] **Step 6: Full suite and commit**

Run: `cd backend && .venv/bin/python -m pytest tests/ -q -m "not pve_integration and not e2e"`

```bash
git add backend/proxploy/models.py backend/proxploy/api/hosts.py \
        backend/proxploy/migrations/versions/ backend/tests/test_hosts_ssh_verify.py
git commit -m "feat(hosts): verify an enrolled SSH key instead of taking your word for it"
```

---

## Task 3: `ssh_pending` on `/meta/onboarding`

**Files:**
- Modify: `backend/proxploy/api/meta.py:36-42`
- Test: `backend/tests/test_meta.py` (find the existing onboarding test first)

**Interfaces:**
- Consumes: `HostCredential.ssh_verified_at` from Task 2.
- Produces, for Task 12: `GET /meta/onboarding` → `{"admin_exists": bool, "host_added": bool, "ssh_pending": bool, "complete": bool, "oidc": bool}`. `ssh_pending` is true when some host has an `ssh_key` credential whose `ssh_verified_at` is NULL.

- [ ] **Step 1: Write the failing test**

```python
def test_onboarding_reports_ssh_pending_until_verified(tmp_path, csrf_header, bootstrap_admin):
    """The wizard derives its step from this; an unverified key means the
    authorize step still has something to ask for."""
    # Build a host with ssh_enroll=True exactly as tests/test_hosts.py does,
    # then:
    r = client.get("/api/v1/meta/onboarding")
    assert r.json()["ssh_pending"] is True
    # ...after POST /hosts/{id}/ssh/verify succeeds:
    assert client.get("/api/v1/meta/onboarding").json()["ssh_pending"] is False
```

Write this out fully against the real fixtures — the sketch above marks the two assertions that matter, not the whole test. Model the setup on `test_hosts_ssh_verify.py` from Task 2.

- [ ] **Step 2: Run to verify failure**

Expected: `KeyError: 'ssh_pending'`.

- [ ] **Step 3: Implement**

`onboarding()` takes no auth dependency by design — it is the pre-session gate, probed before any admin exists. Keep it that way; `ssh_pending` is a boolean about configuration state, not a secret.

```python
@router.get("/onboarding")
def onboarding(request: Request, db=Depends(get_db)):
    return {"admin_exists": db.query(User).count() > 0,
            "host_added": db.query(Host).count() > 0,
            # An enrolled-but-unverified key is the wizard's authorize step
            # still being owed an answer (Task 2). Verified or absent, there
            # is nothing left to ask.
            "ssh_pending": db.query(HostCredential).filter_by(kind="ssh_key")
                             .filter(HostCredential.ssh_verified_at.is_(None))
                             .count() > 0,
            "complete": bool(get_setting(db, "onboarding.complete", False)),
            # Task 11: login page's pre-session SSO-button gate.
            "oidc": oidc.configured(db) and request.app.state.entitlements.enabled("auth.oidc")}
```

Add `HostCredential` to the `from proxploy.models import ...` line at `meta.py:8`.

- [ ] **Step 4: Run tests and commit**

```bash
git add backend/proxploy/api/meta.py backend/tests/test_meta.py
git commit -m "feat(meta): report ssh_pending so the wizard can derive its own step"
```

---

## Task 4: `EmptyState` gains an action

**Files:**
- Modify: `frontend/src/components/EmptyState.tsx`
- Test: `frontend/src/tests/empty-state.test.tsx` (new)

**Interfaces:**
- Produces, for Tasks 5 and 10: `<EmptyState title={string} note={string} action?={ReactNode} />`. `action` renders below the note; omitting it renders exactly what the component renders today.

Cluster's first-run state needs an "Add your first host" button, and the current component has nowhere to put one.

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { EmptyState } from '../components/EmptyState'

describe('EmptyState', () => {
  it('renders title and note with no action', () => {
    render(<EmptyState title="No hosts yet" note="Add one to get started." />)
    expect(screen.getByText('No hosts yet')).toBeInTheDocument()
    expect(screen.getByText('Add one to get started.')).toBeInTheDocument()
  })

  it('renders an action when given one', () => {
    render(<EmptyState title="No hosts yet" note="Add one."
                       action={<button>Add a host</button>} />)
    expect(screen.getByRole('button', { name: 'Add a host' })).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/tests/empty-state.test.tsx`
Expected: FAIL — TypeScript rejects the `action` prop.

- [ ] **Step 3: Implement**

```tsx
export function EmptyState({ title, note, action }: {
  title: string; note: string; action?: React.ReactNode
}) {
  return (
    <div className="grid place-items-center rounded-card border border-dashed border-line py-20 text-center">
      <div>
        <h2 className="font-display text-[16px] text-text-2">{title}</h2>
        <p className="mt-1 max-w-md text-[12.5px] text-text-3">{note}</p>
        {action && <div className="mt-4">{action}</div>}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run and commit**

```bash
git add frontend/src/components/EmptyState.tsx frontend/src/tests/empty-state.test.tsx
git commit -m "feat(ui): EmptyState can carry an action"
```

---

## Task 5: The four-state query component

**Files:**
- Create: `frontend/src/components/QueryState.tsx`
- Test: `frontend/src/tests/query-state.test.tsx` (new)

**Interfaces:**
- Consumes: `EmptyState` with the `action` prop from Task 4.
- Produces, for Tasks 6, 7, 8, 10:

```tsx
<QueryState
  query={someUseQueryResult}
  empty={(data) => boolean}          // optional; default: Array.isArray(d) && d.length === 0
  emptyTitle="No VMs yet"
  emptyNote="Create one to get started."
  emptyAction={<Button/>}            // optional
  errorTitle="VMs not readable"      // optional; has a sane default
  errorNote="Proxploy could not reach the backend."  // optional
  loading={<Skeleton/>}              // optional; default: a Loading EmptyState-shaped block
>
  {(data) => <VmTable rows={data} />}
</QueryState>
```

This is the whole point of §3 in the spec: **an error must never render as an empty state.** Today 40 collection-rendering queries fall back to `?? []`, so "we could not reach the backend" and "you have nothing yet" are the same pixels. Making them one component makes the conflation impossible to express rather than a rule contributors must remember at 46 call sites.

- [ ] **Step 1: Write the failing tests**

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { QueryState } from '../components/QueryState'

// A UseQueryResult is a big interface; these tests only exercise the four
// fields QueryState reads, so a cast keeps the test readable rather than
// constructing a full fake result object.
const q = (over: object) => ({ isPending: false, isError: false, data: undefined, ...over }) as never

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('QueryState', () => {
  it('renders data when the query resolved with rows', () => {
    wrap(<QueryState query={q({ data: [{ id: 1 }] })} emptyTitle="none" emptyNote="">
      {(rows: { id: number }[]) => <p>{rows.length} rows</p>}
    </QueryState>)
    expect(screen.getByText('1 rows')).toBeInTheDocument()
  })

  it('renders the empty state for a resolved-but-empty list', () => {
    wrap(<QueryState query={q({ data: [] })} emptyTitle="No VMs yet" emptyNote="Create one.">
      {() => <p>never</p>}
    </QueryState>)
    expect(screen.getByText('No VMs yet')).toBeInTheDocument()
  })

  it('renders the ERROR state, not the empty state, when the query failed', () => {
    // The regression this component exists to prevent: a failed fetch must
    // never be indistinguishable from "you have nothing".
    wrap(<QueryState query={q({ isError: true })} emptyTitle="No VMs yet" emptyNote="Create one.">
      {() => <p>never</p>}
    </QueryState>)
    expect(screen.queryByText('No VMs yet')).not.toBeInTheDocument()
    expect(screen.getByText(/could not/i)).toBeInTheDocument()
  })

  it('renders loading separately from empty', () => {
    wrap(<QueryState query={q({ isPending: true })} emptyTitle="No VMs yet" emptyNote="Create one.">
      {() => <p>never</p>}
    </QueryState>)
    expect(screen.queryByText('No VMs yet')).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/tests/query-state.test.tsx`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement**

```tsx
import type { UseQueryResult } from '@tanstack/react-query'

import { EmptyState } from './EmptyState'

/**
 * Loading, error, empty and data are four different answers and must look
 * like four different things.
 *
 * Before this component the codebase spelled every list as `(data ?? []).map`,
 * which renders a failed fetch as "No VMs discovered" — the UI stating
 * confidently that you have nothing when the truth is that it has no idea.
 * `isPending` is likewise not `isError`: react-query flips isPending false on
 * failure too, so a `!data` guard shows "Loading…" forever after a hard error.
 */
export function QueryState<T>({
  query, children, emptyTitle, emptyNote, emptyAction, empty,
  errorTitle = 'Could not load this',
  errorNote = 'Proxploy could not reach the backend. It may be restarting.',
  loading,
}: {
  query: UseQueryResult<T>
  children: (data: T) => React.ReactNode
  emptyTitle: string
  emptyNote: string
  emptyAction?: React.ReactNode
  empty?: (data: T) => boolean
  errorTitle?: string
  errorNote?: string
  loading?: React.ReactNode
}) {
  if (query.isError) return <EmptyState title={errorTitle} note={errorNote} />
  if (query.isPending || query.data === undefined) {
    return loading ?? (
      <div role="status" aria-live="polite"
           className="grid place-items-center rounded-card border border-dashed border-line py-20 text-[12.5px] text-text-3">
        Loading…
      </div>
    )
  }
  const isEmpty = empty ? empty(query.data)
    : Array.isArray(query.data) && query.data.length === 0
  if (isEmpty) return <EmptyState title={emptyTitle} note={emptyNote} action={emptyAction} />
  return <>{children(query.data)}</>
}
```

- [ ] **Step 4: Run and commit**

Run: `cd frontend && npx vitest run src/tests/query-state.test.tsx`
Expected: 4 passed.

```bash
git add frontend/src/components/QueryState.tsx frontend/src/tests/query-state.test.tsx
git commit -m "feat(ui): one component for loading, error, empty and data"
```

---

## Task 6: Convert the 25 page-level content lists

**Files (all Modify):** `routes/vms.tsx:27`, `routes/cluster.tsx:33,81,86,237,242`, `routes/apps.tsx:34,38,49`, `routes/settings.tsx:145,180`, `api/account.ts:49` (SessionsCard), `api/apikeys.ts:16` (ApiKeysCard), `api/storage.ts:37` (StoragePage), `api/catalog.ts:17` (StorePage), `api/alerts.ts:27,35,42` (AlertsPage's three tables), `api/jobs.ts:36,54,62` (ActivityDrawer, JobLog, ActivityFeed), `api/teams.ts:21,25,33`, `api/schedules.ts:29` (SchedulesCard)
- Test: extend the existing per-route tests in `frontend/src/tests/`

**Interfaces:**
- Consumes: `QueryState` from Task 5.

The line numbers above are where the `useQuery` lives; the render site is usually elsewhere in the same file. These are the lists a user reads as "there is nothing here", which is why they go first.

- [ ] **Step 1: Write one failing test per page, asserting the error case**

For each route with an existing test file, add a case in this shape (this one for Alerts, which today has no `isError` handling at all):

```tsx
it('says the alerts could not be read rather than showing "nothing is firing"', async () => {
  // The bug: a failed fetch renders identically to a healthy, quiet cluster.
  vi.mocked(api).mockRejectedValue(new Error('boom'))
  withQuery(<AlertsPage />)
  expect(await screen.findByText(/could not/i)).toBeInTheDocument()
  expect(screen.queryByText(/Nothing is firing/)).not.toBeInTheDocument()
})
```

**Follow `frontend/src/tests/storage.test.tsx:26-57` for the established mocking pattern** — `vi.mock('../api/client', …)` with a path-keyed `vi.fn`, `vi.mock('@tanstack/react-router', …)` spreading the real module, and a `withQuery` helper using `retry: false`. Import the component *after* the mocks.

Not every one of the 25 sites has an existing test file. Where one exists, extend it. Where none exists, add the error assertion to whichever suite covers that page, and if there is genuinely none, note it in the commit rather than creating a new suite per site.

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run --no-file-parallelism`
Expected: the new cases FAIL — the empty-state copy is still what renders on error.

- [ ] **Step 3: Convert, one file at a time**

The mechanical shape, using Alerts as the worked example. Before (`routes/alerts.tsx:98-108`):

```tsx
{(firing.data ?? []).length === 0 ? (
  <p className="text-[12.5px] text-text-3">
    Nothing is firing. Rules are checked every poll cycle.
  </p>
) : (
  <table>…{(firing.data ?? []).map((a) => (…))}…</table>
)}
```

After:

```tsx
<QueryState query={firing}
            emptyTitle="Nothing is firing"
            emptyNote="Rules are checked every poll cycle."
            errorTitle="Alerts not readable"
            errorNote="Proxploy could not reach the backend to check what is firing.">
  {(rows) => <table>…{rows.map((a) => (…))}…</table>}
</QueryState>
```

Rules for the sweep:

- **Never delete an existing empty-state message.** Move its wording into `emptyTitle`/`emptyNote`. The copy was written deliberately; this task changes when it shows, not what it says.
- **Where a page has an `isError` branch already** (the 6 exemplary sites), leave them for a later pass or convert them too — but if you convert, the rendered copy must stay identical.
- **`api/*.ts` sites are hooks, not components.** The hook stays as-is; the `QueryState` goes at the *consuming component's* render site. Follow the hook's import to find it.
- Commit per file or per small group, not one giant commit.

- [ ] **Step 4: Run the full frontend suite**

Run: `cd frontend && npx vitest run --no-file-parallelism`
Expected: ≥ 205 passed plus the new cases; zero failures.

- [ ] **Step 5: Lint and commit**

Run: `cd frontend && npm run lint` — must stay exit 0.

```bash
git add frontend/src
git commit -m "fix(ui): a failed list no longer claims you have nothing"
```

---

## Task 7: Selects, dead code, and loading-as-empty

**Files (all Modify):** `routes/backups.tsx:41`, `api/alerts.ts:50`, `components/VmCreateWizard.tsx:64,65,66,67,73`, `components/ScheduleForm.tsx:29`, `components/CloneDialog.tsx:24`, `components/MigrateDialog.tsx:47`, `components/AlertRuleForm.tsx:38,44,48`, `components/StorageForm.tsx:44`, `components/InstallDialog.tsx:12`, `routes/vms.tsx:125`, `routes/apps.tsx:159`
- Delete: the `useJob` hook at `frontend/src/api/jobs.ts:45`

**Interfaces:**
- Consumes: `QueryState` from Task 5.

- [ ] **Step 1: Delete the dead hook**

`api/jobs.ts:45`'s `useJob` has no callers anywhere in `frontend/src`. Confirm with `grep -rn "useJob\b" frontend/src` (note the word boundary — `useJobs` and `useJobEvents` are both live and must survive), then delete it.

- [ ] **Step 2: Fix the two loading-as-empty sites**

`routes/vms.tsx:125` and `routes/apps.tsx:159` both render `<EmptyState title="Loading…" note="" />` when their detail query has no data yet. This masks a hard error as eternal loading — `isPending` goes false on failure, so a permanently failed fetch shows "Loading…" forever. Replace each with `QueryState`, using `empty={() => false}` since a single record is never a collection:

```tsx
<QueryState query={vmQuery} emptyTitle="" emptyNote="" empty={() => false}
            errorTitle="This VM could not be loaded"
            errorNote="Proxploy could not reach the backend, or the VM no longer exists.">
  {(vm) => ( … the existing detail body … )}
</QueryState>
```

Leave `routes/vms.tsx:229` and `routes/apps.tsx:367` (`title="Opening console…"`) alone — those guard a console ticket, not a `useQuery`, and "opening" is a genuinely transient state with its own semantics. Note them in the commit as deliberately untouched.

- [ ] **Step 3: Convert the 15 select-option lists**

Same mechanical shape as Task 6, but a `<select>` cannot contain an `EmptyState` div. Use the `loading`/error slots to render a disabled placeholder option instead:

```tsx
<select disabled={hosts.isPending || hosts.isError}>
  {hosts.isError
    ? <option>Could not load hosts</option>
    : (hosts.data ?? []).map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
</select>
```

`QueryState` is the wrong tool inside a `<select>`; do not force it. What matters is the same principle: a failed fetch must not look like "there are no hosts". Keep the shape above consistent across all 15 so the pattern is greppable.

- [ ] **Step 4: Run, lint, commit**

Run: `cd frontend && npx vitest run --no-file-parallelism && npm run lint`

```bash
git add frontend/src
git commit -m "fix(ui): selects say when they could not load, and dead useJob goes"
```

---

## Task 8: The three queries that lie reassuringly

**Files:**
- Modify: `frontend/src/api/hooks.ts:16` (`useEntitlements`), `frontend/src/api/account.ts:41` (`useTotpStatus`) and its `TotpCard` consumer, `frontend/src/routes/cluster.tsx:25` (`useSummary`) and its Ring consumers
- Test: `frontend/src/tests/entitlements-failure.test.tsx` (new), plus cases in the existing TOTP and cluster suites

These are not lists, so Task 6 does not cover them, but each renders a confident falsehood on failure rather than a blank. `components/HealthFooter.tsx:15` already does this right and is the reference.

- [ ] **Step 1: Write the failing test for the worst one**

```tsx
it('does not silently hide every gated feature when entitlements fail to load', async () => {
  // has() returning false on error is indistinguishable from "not entitled",
  // so a backend blip reads to the user as a downgrade. It must be possible
  // to tell "no" from "do not know".
  vi.mocked(api).mockRejectedValue(new Error('boom'))
  const { result } = renderHook(() => useEntitlements(), { wrapper })
  await waitFor(() => expect(result.current.unknown).toBe(true))
  expect(result.current.has('storage.manage')).toBe(false)
})
```

- [ ] **Step 2: Run to verify failure**

Expected: FAIL — there is no `unknown` on the hook's return.

- [ ] **Step 3: Implement**

`useEntitlements` gains an `unknown` flag so consumers can distinguish "not entitled" from "could not check":

```tsx
export function useEntitlements() {
  const q = useQuery({ queryKey: ['entitlements'], queryFn: () => api<Ents>('/entitlements') })
  return {
    // `has` stays fail-closed — a feature must never unlock because a fetch
    // failed. But `unknown` lets a consumer say "could not check" instead of
    // rendering the UI of a tenant who simply is not entitled.
    has: (k: string) => q.data?.features[k] ?? false,
    unknown: q.isError,
    ...
  }
}
```

`has()` deliberately keeps returning `false` on error — failing open would be a security bug. What changes is that callers *can* now tell the difference. Apply `unknown` where a whole panel or page-level capability is gated; do not thread it through every individual button.

For `useTotpStatus`, the `TotpCard` must not offer "Enable two-factor" when the status is unknown — render the error instead. For `useSummary`, the rings must show an unknown state rather than a calm 0%.

- [ ] **Step 4: Run, lint, commit**

```bash
git add frontend/src
git commit -m "fix(ui): tell 'not entitled' apart from 'could not check'"
```

---

## Task 9: Finding F1, closed

**Files:**
- Create: `frontend/src/components/RouteError.tsx`
- Modify: `frontend/src/router.tsx:32`, `frontend/src/routes/shell.tsx:38-42`
- Test: `frontend/src/tests/route-error.test.tsx` (new)

**Interfaces:**
- Produces: `<RouteError error={unknown} reset?={() => void} />`, passed as `defaultErrorComponent` to `createRouter` and as `errorComponent` on `shellRoute`.

Phase 8 recorded F1 as "no `errorComponent`, so a 5xx white-screens the app". It is worse than that: TanStack falls back to its own `ErrorComponent`, which styles itself with **inline `style={}`** and so ignores the theme entirely, and because it fires at the failing route's match, `AppShell` never mounts. A stranger gets an unstyled grey box on a blank page.

- [ ] **Step 1: Write the failing tests**

```tsx
describe('RouteError', () => {
  it('offers a retry for an unreachable backend', () => {
    const reset = vi.fn()
    render(<RouteError error={new TypeError('Failed to fetch')} reset={reset} />)
    fireEvent.click(screen.getByRole('button', { name: /try again/i }))
    expect(reset).toHaveBeenCalled()
  })

  it('distinguishes a broken app from an unreachable backend', () => {
    render(<RouteError error={new Error('Cannot read properties of undefined')} />)
    expect(screen.getByText(/something in Proxploy broke/i)).toBeInTheDocument()
  })

  it('uses theme tokens, never inline colours', () => {
    // The whole reason the built-in fallback is unacceptable.
    const { container } = render(<RouteError error={new Error('x')} />)
    expect(container.innerHTML).not.toMatch(/style="[^"]*(#[0-9a-f]{3,6}|rgb\()/i)
  })
})
```

- [ ] **Step 2: Run to verify failure**

Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement `RouteError`**

An unreachable backend and a bug in the app want different things from the user — one wants a retry, the other wants a way out and (in dev) a stack. Collapsing them into "Something went wrong" is exactly what the built-in fallback already does badly.

```tsx
export function RouteError({ error, reset }: { error: unknown; reset?: () => void }) {
  // A fetch that never reached the server throws TypeError('Failed to fetch')
  // in every browser we target; an ApiError means the server answered, so it
  // is reachable and something else is wrong.
  const unreachable = error instanceof TypeError && /fetch/i.test(error.message)
  return (
    <div className="grid min-h-screen place-items-center bg-ink p-6">
      <div className="w-[520px] rounded-card border border-line-soft bg-panel p-7 text-center">
        <h1 className="font-display text-[18px] text-text">
          {unreachable ? 'Proxploy is not answering' : 'Something in Proxploy broke'}
        </h1>
        <p className="mt-2 text-[13px] text-text-2">
          {unreachable
            ? 'The backend did not respond. It may be restarting after an update.'
            : 'This is a bug, not something you did. The page could not be rendered.'}
        </p>
        {reset && <Button className="mt-5" onClick={reset}>Try again</Button>}
        {import.meta.env.DEV && (
          <pre className="mt-4 overflow-x-auto rounded-ctl bg-elev p-3 text-left font-mono text-[11px] text-text-3">
            {String(error instanceof Error ? error.stack ?? error.message : error)}
          </pre>
        )}
      </div>
    </div>
  )
}
```

The detail block is `import.meta.env.DEV`-gated: a stack trace on a stranger's screen is noise to them and reconnaissance to anyone else.

- [ ] **Step 4: Register it in two places**

`frontend/src/router.tsx:32`:

```tsx
export const router = createRouter({ routeTree, defaultErrorComponent: RouteError })
```

And on `shellRoute` in `frontend/src/routes/shell.tsx`, add `errorComponent: RouteError` alongside `component`. The router-level default catches any route; the shell-level one is what actually fires for the app's own pages.

- [ ] **Step 5: Handle the unwrapped call that causes F1**

`shell.tsx:38-42`'s `beforeLoad` calls `/meta/onboarding` unguarded — a 500 or an unreachable backend there throws straight into the router. That is the live path into F1, and `errorComponent` alone would only make it *pretty*. Wrap it so a reachable-but-broken backend is distinguishable from "not onboarded":

```tsx
  beforeLoad: async () => {
    // An unreachable backend must not read as "you have not onboarded" — that
    // would bounce a fully set-up user back into the wizard.
    const ob = await api<Onboarding>('/meta/onboarding')
    if (!ob.complete) throw redirect({ to: '/onboarding' })
    try { await api('/auth/me') } catch { throw redirect({ to: '/login' }) }
  },
```

Leave the throw *uncaught* here on purpose — `errorComponent` is now what renders it, which is the correct outcome and the thing F1 was missing. What must change is the `/auth/me` catch below it: it currently redirects to `/login` on *any* failure, so a 500 is indistinguishable from "not signed in". Re-throw when the failure is not a 401:

```tsx
    try { await api('/auth/me') } catch (e) {
      if (e instanceof ApiError && e.status === 401) throw redirect({ to: '/login' })
      throw e   // a 500 is not "please sign in"
    }
```

`redirect()` throws, so the `instanceof ApiError` check must come first — confirm the redirect object is not itself an `ApiError` before shipping this.

- [ ] **Step 6: Run, lint, commit**

```bash
git add frontend/src/components/RouteError.tsx frontend/src/router.tsx \
        frontend/src/routes/shell.tsx frontend/src/tests/route-error.test.tsx
git commit -m "fix(ui): F1 — a route failure renders in the app, in the theme, and says which failure"
```

---

## Task 10: The empty states that are missing

**Files:**
- Modify: `frontend/src/routes/cluster.tsx:33` render site (the node grid), `frontend/src/routes/alerts.tsx:98-101,121-122`, `frontend/src/routes/settings.tsx:128,265`
- Test: `frontend/src/tests/cluster.test.tsx` (extend)

**Interfaces:**
- Consumes: `QueryState` (Task 5), `EmptyState` with `action` (Task 4).

Cluster's node grid renders `(nodes ?? []).map(...)` into a bare `<div>` — with zero hosts a fresh install shows *nothing at all*, no heading, no message, no action. Task 13 makes the wizard's host step skippable, which turns this into the literal first screen a stranger sees.

- [ ] **Step 1: Write the failing test**

```tsx
it('tells a fresh install what to do when there are no hosts', async () => {
  // With a skippable host step (Task 13) this is the first screen a stranger
  // sees. A blank div is not a first-run experience.
  withQuery(<ClusterPage />)   // api mock returns [] for /cluster/nodes
  expect(await screen.findByText(/no hosts/i)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /add.*host/i })).toBeInTheDocument()
})
```

- [ ] **Step 2: Run to verify failure**

Expected: FAIL — nothing renders for an empty node list.

- [ ] **Step 3: Implement**

Cluster's node grid, wrapped with an action pointing at wherever hosts are added (`/settings` — confirm the real route and any deep link before writing the `to`):

```tsx
<QueryState query={nodesQuery}
            emptyTitle="No hosts yet"
            emptyNote="Proxploy manages Proxmox nodes. Add your first host to see it here."
            emptyAction={<Link to="/settings"><Button>Add a host</Button></Link>}
            errorTitle="Nodes not readable"
            errorNote="Proxploy could not reach the backend to list your nodes.">
  {(nodes) => <div className="grid …">{nodes.map((n) => <NodeCard key={n.node} … />)}</div>}
</QueryState>
```

Then move Alerts' and Settings' ad-hoc inline `<p>` messages onto `EmptyState`, keeping their existing wording verbatim. If Task 6 already converted a given site, this step is a no-op there — check before editing.

- [ ] **Step 4: Run, lint, commit**

```bash
git add frontend/src
git commit -m "feat(ui): a fresh install says what to do next instead of nothing"
```

---

## Task 11: Two literals, and a test that keeps them gone

**Files:**
- Modify: `frontend/src/components/UsageBar.tsx:12`, `frontend/src/components/StatRings.tsx:19`
- Test: `frontend/src/tests/no-hardcoded-colors.test.ts` (new)

**Interfaces:** none — this task is self-contained.

The theme system is already disciplined: a scan for hardcoded Tailwind gray-scale classes across `frontend/src` returns **zero** matches. Exactly two literals bypass it, both `#1d2733`, and together they account for ~11 rendered instances — every usage bar and dashboard ring keeps a dark trough on a light card.

- [ ] **Step 1: Write the failing guard test**

```ts
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

// Terminal and console surfaces are dark in BOTH themes on purpose — a
// terminal that follows a light theme stops looking like a terminal. That
// intent was previously unrecorded anywhere; this list is where it lives now.
const INTENTIONALLY_DARK = [
  'components/ScriptPanel.tsx',
  'components/TerminalPanel.tsx',
  'components/terminal/Terminal.tsx',
  'components/console/VncConsole.tsx',
  'routes/onboarding.tsx',
]

// Gradient stops are multi-colour brand ramps with no token equivalent; they
// are theme-neutral by construction (they sit on their own fill, not on a
// surface that flips).
const ALLOWED_LINE = /GRADIENT\s*=|linearGradient|stopColor=\{/

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((e) => {
    const p = join(dir, e)
    return statSync(p).isDirectory() ? walk(p) : p.endsWith('.tsx') || p.endsWith('.ts') ? [p] : []
  })
}

describe('no hardcoded colours', () => {
  it('every colour comes from a token', () => {
    const src = join(__dirname, '..')
    const offenders: string[] = []
    for (const file of walk(src)) {
      const rel = file.slice(src.length + 1)
      if (rel.startsWith('tests/') || INTENTIONALLY_DARK.some((d) => rel.endsWith(d))) continue
      readFileSync(file, 'utf8').split('\n').forEach((line, i) => {
        if (ALLOWED_LINE.test(line)) return
        if (/(style=\{\{[^}]*|stroke=|fill=)["'\s:]*#[0-9a-fA-F]{3,8}\b/.test(line)) {
          offenders.push(`${rel}:${i + 1}  ${line.trim()}`)
        }
      })
    }
    expect(offenders, offenders.join('\n')).toEqual([])
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/tests/no-hardcoded-colors.test.ts`
Expected: FAIL, listing `components/UsageBar.tsx:12` and `components/StatRings.tsx:19`.

If it lists more than those two, **do not widen the allowlist to make it pass.** Report what else it found — the earlier survey said there were only two, and a third is a finding.

- [ ] **Step 3: Replace both literals**

`--elev` is the existing "raised surface" token, defined in both themes (`#1B2531` dark, `#E7ECF2` light), and is the correct semantic fit for a track or trough.

`UsageBar.tsx:12`:

```tsx
    <div className="h-1.5 overflow-hidden rounded-full bg-elev">
```

(dropping the `style` prop entirely — a Tailwind utility reads better here and the guard test never has to reason about it).

`StatRings.tsx:19` is an SVG `stroke`, which cannot take a Tailwind background utility. Use the CSS variable directly:

```tsx
        <circle cx="60" cy="60" r="52" fill="none" stroke="var(--elev)" strokeWidth="10" />
```

Note the guard regex above matches `stroke=` followed by a literal hex — `var(--elev)` passes it, which is the intended distinction.

- [ ] **Step 4: Run, lint, commit**

Run: `cd frontend && npx vitest run --no-file-parallelism && npm run lint`

```bash
git add frontend/src/components/UsageBar.tsx frontend/src/components/StatRings.tsx \
        frontend/src/tests/no-hardcoded-colors.test.ts
git commit -m "fix(ui): the last two hardcoded colours, and a test that keeps them out"
```

---

## Task 12: The wizard derives its own step

**Files:**
- Modify: `frontend/src/routes/onboarding.tsx`
- Test: `frontend/src/tests/onboarding.test.tsx` (currently only tests `HostForm` in isolation, 15 lines — this grows it into a real wizard suite)

**Interfaces:**
- Consumes: `GET /meta/onboarding` → `{admin_exists, host_added, ssh_pending, complete, oidc}` from Task 3.

Today `step` is `useState(0)`. Reload mid-wizard and `beforeLoad` still sees `complete: false`, so it remounts at step 0 — but the admin now exists and a session cookie is already set, so resubmitting hits `create_user`'s non-first-run path and 409s, surfaced as *"Could not create the admin account (password: 12+ characters)"*. The user is told they typed a bad password when what actually happened is that they already succeeded.

- [ ] **Step 1: Write the failing tests**

```tsx
describe('onboarding wizard', () => {
  it('resumes at the host step when the admin already exists', async () => {
    // The reload bug: local useState always restarted at step 0 and then
    // told the user their password was bad.
    mockOnboarding({ admin_exists: true, host_added: false, ssh_pending: false, complete: false })
    renderWizard()
    expect(await screen.findByLabelText('API token id')).toBeInTheDocument()
    expect(screen.queryByLabelText('Password (12+ chars)')).not.toBeInTheDocument()
  })

  it('resumes at the authorize step when a key is enrolled but unverified', async () => {
    mockOnboarding({ admin_exists: true, host_added: true, ssh_pending: true, complete: false })
    renderWizard()
    expect(await screen.findByRole('button', { name: /verify/i })).toBeInTheDocument()
  })

  it('starts at the admin step on a truly fresh install', async () => {
    mockOnboarding({ admin_exists: false, host_added: false, ssh_pending: false, complete: false })
    renderWizard()
    expect(await screen.findByLabelText('Password (12+ chars)')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/tests/onboarding.test.tsx`
Expected: FAIL — the wizard always renders step 0.

- [ ] **Step 3: Implement**

Replace `const [step, setStep] = useState(0)` with a derived step plus an override for forward movement inside a single session:

```tsx
type Onboarding = { admin_exists: boolean; host_added: boolean
                    ssh_pending: boolean; complete: boolean }

/** Server state decides where you are; the local override only ever moves
 *  you forward within one session, so a reload re-derives instead of
 *  restarting. This is the fix for "you already created the admin" being
 *  reported as "your password is bad". */
function stepFrom(ob: Onboarding): number {
  if (!ob.admin_exists) return 0
  if (!ob.host_added) return 1
  if (ob.ssh_pending) return 2
  return 3
}

function Wizard() {
  const ob = useQuery({ queryKey: ['onboarding'], queryFn: () => api<Onboarding>('/meta/onboarding') })
  const [advanced, setAdvanced] = useState<number | null>(null)
  const step = advanced ?? (ob.data ? stepFrom(ob.data) : 0)
  …
}
```

Every place that previously called `setStep(n)` calls `setAdvanced(n)` and invalidates the `['onboarding']` query so the next render re-derives from the server.

- [ ] **Step 4: Run and commit**

```bash
git add frontend/src/routes/onboarding.tsx frontend/src/tests/onboarding.test.tsx
git commit -m "fix(onboarding): a reload resumes where you were, not at step one"
```

---

## Task 13: A skippable host step that says what went wrong

**Files:**
- Modify: `frontend/src/routes/onboarding.tsx`, `frontend/src/components/HostForm.tsx:22-23`
- Test: `frontend/src/tests/onboarding.test.tsx`, `frontend/src/tests/host-form-errors.test.tsx` (new)

**Interfaces:**
- Consumes: `502 {"error": "unreachable"|"auth"|"tls_fingerprint"|"refused"|"unknown", "detail": str}` from Task 1; `ApiError` with `.status` and `.body` from `frontend/src/api/client.ts:1-9`.

`HostForm.errText` (`HostForm.tsx:22-23`) reads `.detail`/`.title`/`.message` and throws the status away, so every failure renders as one flat red line. The client already carries everything needed — this is a display fix on top of Task 1's taxonomy.

- [ ] **Step 1: Write the failing tests**

```tsx
it('tells a wrong token apart from an unreachable box', async () => {
  vi.mocked(api).mockRejectedValue(new ApiError(502, { error: 'auth', detail: '401' }))
  render(<HostForm onCreated={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: 'Test connection' }))
  expect(await screen.findByText(/token/i)).toBeInTheDocument()
})

it('names a fingerprint mismatch as the security event it is', async () => {
  vi.mocked(api).mockRejectedValue(new ApiError(502, { error: 'tls_fingerprint', detail: 'x' }))
  render(<HostForm onCreated={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: 'Test connection' }))
  expect(await screen.findByText(/fingerprint/i)).toBeInTheDocument()
})

it('lets a stranger skip the host step entirely', async () => {
  mockOnboarding({ admin_exists: true, host_added: false, ssh_pending: false, complete: false })
  renderWizard()
  fireEvent.click(await screen.findByRole('button', { name: /skip for now/i }))
  expect(await screen.findByRole('button', { name: /open the dashboard/i })).toBeInTheDocument()
})
```

- [ ] **Step 2: Run to verify failure**

Expected: FAIL — no skip button, and every error renders the same text.

- [ ] **Step 3: Map the kinds to copy people can act on**

In `HostForm.tsx`, replace `errText`:

```tsx
// Each kind names a different fix. "Request failed" named none of them.
const KIND_COPY: Record<string, string> = {
  auth: 'Proxmox rejected the API token. Check the token id and secret, and that the token has not expired.',
  unreachable: 'Could not reach that address. Check the host is up and that :8006 is reachable from Proxploy.',
  tls_fingerprint: "The node's TLS certificate does not match the fingerprint you pinned. "
    + 'If you did not just replace the certificate, stop and investigate before continuing.',
  refused: 'Proxploy refused to connect to that address because it resolves somewhere unsafe '
    + '(loopback, link-local, or metadata). Use the node\'s real address.',
}

const errText = (e: unknown) => {
  if (!(e instanceof ApiError)) return 'Request failed.'
  const body = e.body as { error?: string; detail?: string | { error?: string } } | null
  const kind = body?.error
  if (kind && KIND_COPY[kind]) return KIND_COPY[kind]
  if (e.status === 409) return 'A host with that name already exists.'
  if (e.status === 403) return 'Managing more than one host needs a paid tier.'
  return typeof body?.detail === 'string' ? body.detail : 'Request failed.'
}
```

**The body is flat, not nested.** Plain FastAPI would nest a dict `detail` one
level deep, but `main.py::problem_handler` flattens it into the top-level
RFC7807 body — so a kind arrives as `body.error`, and `body.detail` is the
human string. Established by Task 1 against a real response (commit `3763b7a`),
not assumed.

- [ ] **Step 4: Add the skip**

In the wizard's step 1, alongside `<HostForm>`:

```tsx
<Button variant="ghost" onClick={() => setAdvanced(3)}>Skip for now</Button>
<p className="text-[12px] text-text-3">
  You can add a host later from Settings. Everything except managing nodes works without one.
</p>
```

The shell's guard already permits a host-less app — it checks `onboarding.complete` and never `host_added` (`shell.tsx:38-42`) — so no backend change is needed. Task 10's Cluster empty state is what a skipping user lands on.

- [ ] **Step 5: Run, lint, commit**

```bash
git add frontend/src
git commit -m "feat(onboarding): skippable host step, and errors that name the fix"
```

---

## Task 14: The authorize step stops taking your word for it

**Files:**
- Modify: `frontend/src/routes/onboarding.tsx:74-83`
- Test: `frontend/src/tests/onboarding.test.tsx`

**Interfaces:**
- Consumes: `POST /hosts/{id}/ssh/verify` from Task 2.

- [ ] **Step 1: Write the failing test**

```tsx
it('will not advance until the key actually works', async () => {
  vi.mocked(api).mockRejectedValueOnce(new ApiError(502, { detail: { error: 'command_failed' } }))
  renderWizardAtAuthorizeStep()
  fireEvent.click(screen.getByRole('button', { name: /verify/i }))
  expect(await screen.findByText(/not authorized yet/i)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /open the dashboard/i })).not.toBeInTheDocument()
})
```

- [ ] **Step 2: Run to verify failure**

Expected: FAIL — the button unconditionally advances.

- [ ] **Step 3: Implement**

Replace the `I have authorized it` button:

```tsx
<Button onClick={async () => {
  setVerifyError('')
  try {
    await api(`/hosts/${host.id}/ssh/verify`, { method: 'POST' })
    setAdvanced(3)
  } catch (e) {
    // A mis-pasted key used to surface at the first app install instead of
    // here, far from its cause.
    setVerifyError(e instanceof ApiError && (e.body as any)?.error === 'host_key_mismatch'
      ? "The node's SSH host key changed since Proxploy first saw it. Stop and investigate."
      : 'Not authorized yet — Proxploy still cannot open a root shell on the node. '
        + 'Check the line was added to /root/.ssh/authorized_keys and saved.')
  }
}}>Verify access</Button>
```

Keep the "Copy key line" button as-is.

- [ ] **Step 4: Run, lint, commit**

```bash
git add frontend/src/routes/onboarding.tsx frontend/src/tests/onboarding.test.tsx
git commit -m "feat(onboarding): verify the SSH key rather than trusting a click"
```

---

## Task 15: A backend the e2e suite can actually onboard against

**Files:**
- Create: `backend/tests/e2e_server.py`
- Modify: `frontend/playwright.config.ts:40-42`

**Interfaces:**
- Produces, for Tasks 16–17: a uvicorn factory target `tests.e2e_server:create_e2e_app` that serves the real app with `FakePVE` and `FakeSSHConnection` installed, so `POST /hosts` succeeds without a live Proxmox node.

`POST /hosts` unconditionally probes the real Proxmox API (`hosts.py:101`) — which is why `smoke.spec.ts:18-27` bypasses the wizard's host step with direct API calls. Without this task the stranger journey cannot start.

`backend/tests/` is already excluded from the release tarball by 9a's `build_release.sh`, so a launcher living there satisfies the spec's "test code only" constraint through an existing mechanism rather than a new convention. **Verify that exclusion still holds** (`grep -n "tests" packaging/build_release.sh`) before relying on it, and say so in the commit.

- [ ] **Step 1: Write the launcher**

```python
"""Serve the REAL app to Playwright with fake PVE and SSH behind it.

This exists so the e2e suite can drive the actual onboarding wizard —
including POST /hosts, which probes a live Proxmox API and therefore could
never run here. It lives in tests/ deliberately: packaging/build_release.sh
excludes tests/ from the release tarball, so none of this ships. An env var
honoured by main.py would have been simpler and would also have been a
backdoor that swaps a core client in the production binary, in a product
whose trust story is root-on-node.

What it proves: the product's own logic, routing and UI, end to end.
What it does not prove: behaviour against real Proxmox hardware.
"""
import json
import os
from pathlib import Path


def create_e2e_app():
    from proxploy.config import Settings
    from proxploy.main import create_app
    from tests.fakes.pve import FakePVE, make_fake_factory
    from tests.fakes.ssh import FakeSSHConnection, make_fake_connect_factory

    data_dir = Path(os.environ["PROXPLOY_DATA_DIR"])

    fake = FakePVE(version={"version": "8.4.1", "release": "8.4"})
    fake.add_ct(101, node="pve1", name="demo-ct", status="running")

    ssh = FakeSSHConnection(host_key_fingerprint="SHA256:e2e",
                            stdout_lines=["ok"], stderr_lines=[], exit_status=0)

    settings = Settings(
        db_url=os.environ["PROXPLOY_DB_URL"],
        data_dir=data_dir,
        master_key_file=Path(os.environ["PROXPLOY_MASTER_KEY_FILE"]),
        poll_enabled=False, scheduler_enabled=False, alerts_enabled=False,
    )
    return create_app(settings,
                      proxmox_factory=make_fake_factory(fake),
                      ssh_factory=make_fake_connect_factory(ssh))
```

`FakePVE` covers the whole journey — `version` for the probe, `cluster.resources` for node/guest listing, `nodes(n).qemu.post` for VM create, `nodes(n).vzdump.post` and `storage(s).content` for backups, and task-status polling via `running_ticks`/`task_exit`. Confirm the constructor arguments against `backend/tests/fakes/pve.py:525-528` and `backend/tests/fakes/ssh.py` before writing.

Seed whatever additional `FakePVE` state Task 16's journey needs (a node row in `cluster.resources`, a storage with ISO content for VM create) — add it here rather than from the spec file, so the fixture has one home.

- [ ] **Step 2: Point Playwright at it**

In `frontend/playwright.config.ts`, the backend `webServer.command` currently ends with `proxploy.main:create_app --factory`. Change that target only:

```
+ `${path.join(backendDir, '.venv/bin/uvicorn')} tests.e2e_server:create_e2e_app `
+ `--factory --host 127.0.0.1 --port ${BACKEND_PORT}`,
```

`cwd` is already `backendDir`, so `tests.e2e_server` is importable. The `env` block already sets the three `PROXPLOY_*` variables the launcher reads. Leave the `rm -rf`/`mkdir` prefix and the comment above it exactly as they are — that comment records why the wipe lives in the command string and not at module scope, and it is still true.

- [ ] **Step 3: Prove the fake is actually behind it**

```bash
cd frontend && npx playwright test --list   # config parses
```

Then start the harness by hand and confirm the thing that was impossible before:

```bash
cd frontend && npx playwright test e2e/smoke.spec.ts
```

Expected: still passes. This step is only proving the swap did not break the existing harness.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/e2e_server.py frontend/playwright.config.ts
git commit -m "test(e2e): serve the real app with fake PVE and SSH behind it"
```

---

## Task 16: The stranger journey

**Files:**
- Create: `frontend/e2e/journey.spec.ts`
- Modify: `frontend/e2e/smoke.spec.ts` (only to drop its now-unnecessary host-step bypass comment if it becomes untrue)

**Interfaces:**
- Consumes: the fake-backed backend from Task 15; the rebuilt wizard from Tasks 12–14.

This is the phase's reason for existing. Doc 10's Phase 9 DoD says a stranger *"completes onboarding, installs an app, creates a VM, schedules a backup"* — four clauses that no test has ever executed through the UI.

- [ ] **Step 1: Write the journey**

```ts
/**
 * The four Phase 9 DoD clauses nothing had ever executed: a stranger
 * completes onboarding, installs an app, creates a VM, and schedules a
 * backup — through the real UI, in a real browser.
 *
 * What this proves: the product's own logic, routing and UI, end to end.
 * What it does NOT prove: behaviour against real Proxmox hardware. There is
 * no Proxmox node on this machine and there never will be; every PVE and SSH
 * interaction below is served by tests/e2e_server.py's fakes.
 */
import { expect, test } from '@playwright/test'

test('a stranger onboards, installs an app, creates a VM and schedules a backup', async ({ page }) => {
  await test.step('onboarding: admin account', async () => {
    await page.goto('/onboarding')
    await page.getByLabel('Email').fill('stranger@example.com')
    await page.getByLabel('Display name').fill('Stranger')
    await page.getByLabel('Password (12+ chars)').fill('a-long-enough-passphrase')
    await page.getByRole('button', { name: 'Create admin account' }).click()
  })

  await test.step('onboarding: first host', async () => {
    // Impossible before Task 15 — POST /hosts probes a live Proxmox API.
    await page.getByLabel('Name').fill('pve-01')
    await page.getByLabel('Address').fill('https://10.0.0.5:8006')
    await page.getByLabel('API token id').fill('proxploy@pve!e2e')
    await page.getByLabel('API token secret').fill('secret')
    await page.getByRole('button', { name: 'Add host' }).click()
    await expect(page.getByRole('button', { name: /open the dashboard/i })).toBeVisible()
  })

  await test.step('land on Cluster', async () => {
    await page.getByRole('button', { name: /open the dashboard/i }).click()
    await expect(page.getByRole('heading', { name: 'Cluster', level: 1 })).toBeVisible()
  })

  // The remaining three clauses. Fill these in against the real UI — read
  // routes/store.tsx, components/VmCreateWizard.tsx and components/
  // ScheduleForm.tsx for the actual labels and button names rather than
  // guessing them here.
  await test.step('install an app', async () => { /* … */ })
  await test.step('create a VM', async () => { /* … */ })
  await test.step('schedule a backup', async () => { /* … */ })
})
```

The three unfilled steps are marked because their selectors must come from reading the real components, not from this plan — writing guessed labels here would produce a test that fails for the wrong reason. **Each step must end in a visible assertion that the thing exists afterwards** (the app appears on Apps, the VM appears on Virtual Machines, the schedule appears in Settings), not merely that a button was clickable.

- [ ] **Step 2: Run it**

Run: `cd frontend && npx playwright test e2e/journey.spec.ts`
Expected: all steps pass. Expect this to take several iterations — this is the first time the wizard's host step has ever run in a browser, and Tasks 12–14 changed it substantially.

If a step fails because the *product* is wrong rather than the test, fix the product and say so in the commit. That is the harness doing its job, exactly as 9a's install harness did.

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e/journey.spec.ts
git commit -m "test(e2e): the stranger journey — onboard, install, create, schedule"
```

---

## Task 17: The light-theme leg

**Files:**
- Create: `frontend/e2e/light-theme.spec.ts`

**Interfaces:**
- Consumes: the fake-backed backend (Task 15); the token fixes (Task 11).

There are no human eyes here, so "light-theme QA pass" has to mean something a machine can check. It checks the real bug class — a colour that bypasses the tokens — and nothing more.

- [ ] **Step 1: Write the spec**

```ts
/**
 * Light theme, asserted rather than eyeballed.
 *
 * What this proves: no element resolves to the dark-only literal the two
 * bypass bugs used, and key surfaces clear a contrast threshold in light
 * mode. What it does not prove: that the light theme looks *good*. Nothing
 * available on this machine proves that.
 */
import { expect, test } from '@playwright/test'

const DARK_LITERAL = 'rgb(29, 39, 51)'   // #1d2733, the bypass colour

const PAGES = ['Cluster', 'Apps', 'App Store', 'Virtual Machines',
               'Storage', 'Network', 'Backups', 'Alerts', 'Settings'] as const

test.describe('light theme', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('pp_theme', 'light'))
  })

  for (const label of PAGES) {
    test(`${label} uses no dark-only literals`, async ({ page }) => {
      // …sign in, navigate to `label`…
      await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
      const offenders = await page.evaluate((literal) =>
        [...document.querySelectorAll('*')]
          .filter((el) => {
            const s = getComputedStyle(el)
            return s.backgroundColor === literal || s.stroke === literal
          })
          .map((el) => el.tagName + '.' + el.className), DARK_LITERAL)
      expect(offenders, offenders.join('\n')).toEqual([])
    })
  }
})
```

`ThemeToggle.tsx:6` persists to `localStorage['pp_theme']` and sets `document.documentElement.dataset.theme` — confirm both key and values before writing the init script.

The sign-in and navigation steps are shared with `smoke.spec.ts`; extract them into `frontend/e2e/helpers.ts` and use them from all three specs rather than a third copy. The second copy is where they drift.

- [ ] **Step 2: Run it**

Run: `cd frontend && npx playwright test e2e/light-theme.spec.ts`
Expected: 9 passed. If any page reports offenders, that is a real bypass Task 11's static guard missed (e.g. a colour computed at runtime) — fix the component, do not relax the assertion.

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e/light-theme.spec.ts frontend/e2e/helpers.ts
git commit -m "test(e2e): light theme asserted on computed styles, not eyeballed"
```

---

## Task 18: Gate the e2e suite in CI

**Files:**
- Modify: `.github/workflows/ci.yml`

There is no e2e job today and no `playwright install` step anywhere. Phase 8 closed the browser gap by *writing* a harness that nothing runs. Building the DoD journey on an ungated harness means these clauses pass once and then rot.

- [ ] **Step 1: Add the job**

```yaml
  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - uses: actions/setup-node@v4
        with: {node-version: 22}
      # The harness launches the backend itself (frontend/playwright.config.ts
      # webServer), so it needs a real venv at backend/.venv — the path that
      # config hardcodes — not just a pip install on the runner python.
      - run: python -m venv .venv && .venv/bin/pip install -e '.[dev]'
        working-directory: backend
      - run: npm ci
        working-directory: frontend
      - run: npx playwright install --with-deps chromium
        working-directory: frontend
      - run: npx playwright test
        working-directory: frontend
```

Match the file's existing conventions (it uses `defaults: {run: {working-directory: …}}` on some jobs and inline `{}` map style for `with`) — read it and follow whichever fits.

- [ ] **Step 2: Verify the YAML parses**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo YAML_OK`

- [ ] **Step 3: Run the whole e2e suite locally as CI would**

Run: `cd frontend && npx playwright test`
Expected: smoke + journey + 9 light-theme tests, all passing.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci(9b): gate the e2e suite so the DoD journey cannot rot"
```

---

## Task 19: DoD verification, notes, buildlog

**Files:**
- Create: `backend/dod_verify_phase9b.py` (throwaway; `backend/.gitignore` carries `dod_verify_phase*.py` — confirm, the repo-root `.gitignore` does **not**)
- Create: `docs/notes/phase-9b-onboarding-polish.md`
- Modify: `buildlog.md`

- [ ] **Step 1: Write `dod_verify_phase9b.py`**

Follow `backend/dod_verify_phase9a.py`'s structure exactly. Four checks, each printing `OK`/`FAIL`, exit non-zero on any failure:

1. **The stranger journey** — shell out to `npx playwright test e2e/journey.spec.ts`, print its step names. The output line must state the substitution plainly: `OK (real Chromium against fake PVE and SSH — no Proxmox node on this machine)`.
2. **Error is never empty** — start the app with `make_app`, force a query failure, and assert via the frontend unit suite that the error and empty renderings differ. Simplest honest form: shell out to `npx vitest run src/tests/query-state.test.tsx` and print the four state names it proves.
3. **Light theme** — shell out to `npx playwright test e2e/light-theme.spec.ts`, print the page count asserted.
4. **Onboarding resumes** — drive `GET /meta/onboarding` through four states via `make_app` and assert `stepFrom`'s contract holds at the API level (admin-only, host-added, ssh-pending, complete).

Run it twice; output identical apart from timings.

- [ ] **Step 2: Write `docs/notes/phase-9b-onboarding-polish.md`**

Same skeleton as `docs/notes/phase-9a-install-update.md`: what shipped per subsystem; findings that contradicted the docs; residual limitations (**at minimum**: no real Proxmox node — the journey runs against `FakePVE`; computed-style assertions are not visual review and "ugly but correct" passes them; the light theme has never been seen by a human on this branch); a gate-numbers table with real counts; commit range.

- [ ] **Step 3: `buildlog.md`** — the phase entry in the established format, including "Known gaps, stated plainly".

- [ ] **Step 4: Run everything and record real numbers**

DoD script ×2; full backend suite; frontend suite (`--no-file-parallelism`) + build + lint; the full Playwright suite; `alembic heads`. **Never write a projected number.** Note that unlike 9a this phase adds one migration (Task 2), so `alembic heads` will report a new revision — record it.

- [ ] **Step 5: Commit**

```bash
git add docs/notes/phase-9b-onboarding-polish.md buildlog.md
git commit -m "docs(phase-9b): DoD verification, notes, buildlog"
```

---

## Self-Review

Checked after writing, against the spec:

1. **Spec coverage.** §1 wizard → Tasks 12 (resume), 13 (skip + honest copy), 14 (verified SSH), backed by 1 (error kinds), 2 (verify endpoint), 3 (`ssh_pending`). §2 F1 → Task 9, including the unwrapped `shell.tsx:39` call and the `/auth/me`-catches-everything bug found while planning. §3 four-state wrapper → Tasks 5 (component), 6 (25 page lists), 7 (15 selects + dead code + loading-as-empty), 8 (the three false-negative singles the spec named). §4 empty states → Tasks 4 (action slot) and 10. §5 light theme → Task 11 (both literals + the guard, with the terminal-surface exemption recorded in the allowlist). §6 the journey → Tasks 15 (launcher), 16 (journey), 17 (light leg), 18 (CI gate, which the spec added after the survey found no e2e job). Verification → Task 19.

2. **Placeholder scan.** No "TBD" or "handle errors appropriately". Four places tell the implementer to check a fact before coding and say what to do with each answer, rather than guessing on their behalf: the SSRF exception type in Task 1, the three `app.state`/model field names in Task 2, the FastAPI nested-`detail` shape in Task 13, and the real component labels in Task 16's three unfilled steps. Task 16's steps are deliberately unfilled with a stated reason — guessed selectors would produce tests that fail for the wrong reason.

3. **Type consistency.** `ProxmoxError.kind` values are the same five strings in Tasks 1 and 13. The `POST /hosts/{id}/ssh/verify` error kinds are the same in Tasks 2 and 14. `GET /meta/onboarding`'s five fields are identical in Tasks 3 and 12. `QueryState`'s props are used identically in Tasks 5, 6, 7 and 10. `EmptyState`'s `action` prop is defined in Task 4 and consumed in 5 and 10.

4. **Honesty.** The two things this machine cannot prove — a real Proxmox node, and whether the light theme actually looks right — are stated in the spec, in Tasks 16 and 17's file docstrings, in the DoD script's own printed output, and in the notes' residual-limitations list. `has()` staying fail-closed in Task 8 is called out as deliberate, since failing open would be a security bug.
