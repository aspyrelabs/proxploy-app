# Capability Token Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the operator somewhere to put all four capability tokens the pveum script prints, instead of only the monitoring one.

**Architecture:** One backend addition — `GET /hosts` and `GET /hosts/{id}` report per-capability credential presence (booleans only), keyed off `services/pveum.py::CAPABILITIES`. Everything else is UI over the existing, already-correct `POST /hosts/{host_id}/credentials`, which validates the capability, verifies the token against the node, and upserts `api_token:{capability}`. Onboarding creates the host with monitoring exactly as today, then makes one credentials call per additional capability; a rejection of one token is shown as that capability's failure with an inline retry, not as a failed onboarding.

**Tech Stack:** FastAPI + SQLAlchemy (`backend/proxploy`), pytest with `tests/support.py::make_app`/`seed_host_row`; React 19 + TanStack Query + Tailwind (`frontend/src`), vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-08-13-capability-token-capture-design.md`

## Global Constraints

- The capability list has exactly one definition: `backend/proxploy/services/pveum.py::CAPABILITIES`. Never write a second list of capability keys in backend code or in the capability *state* UI.
- Serialized capability state is **presence only**: booleans. Never the token, the token id, `public_meta`, `key_version`, or any part of `encrypted_blob`.
- A host with no credential rows reports every capability `false` — never an omitted or empty `capabilities` field.
- Do not reimplement token verification. `POST /hosts/{host_id}/credentials` (`backend/proxploy/api/hosts.py:906`) already does the `ProxmoxClient(...).version()` check and raises 502 `token_rejected` leaving the previous credential in place.
- Nothing in this plan provisions tokens, deletes a credential, adds a capability, or touches the SSH key path.
- `monitoring` is `required=True`; the host cannot exist without it. It is never rendered as missing or removable — rotate-only.
- Error bodies: `main.py::problem_handler` flattens a dict `HTTPException` detail to the top level, so a rejected token arrives at the client as `{type, title, status, error: "token_rejected", detail: "<string>"}`. `detail` is a string, `error` is the kind.
- Frontend colors come from tokens (`text-red`, `text-green`, `text-text-3`…), never literal hex — `src/tests/no-hardcoded-colors.test.ts` enforces it.

---

### Task 1: Per-capability credential state on the host reads

**Files:**
- Modify: `backend/proxploy/api/hosts.py` (add `_capability_state` near the other module helpers; `list_hosts` at :330; `host_detail` at :341)
- Test: `backend/tests/test_hosts_capabilities.py` (create)

**Interfaces:**
- Consumes: `CAPABILITIES` (already imported at `api/hosts.py:104`), `HostCredential`.
- Produces: `_capability_state(kinds: Iterable[str]) -> dict[str, bool]`, and a `"capabilities"` key in both `GET /hosts` rows and `GET /hosts/{id}`, shaped `{"monitoring": true, "lifecycle": false, "console": false, "backup": false}` in `CAPABILITIES` order.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_hosts_capabilities.py`:

```python
"""Per-capability credential state on the host reads (capability-token capture).

Presence only: the UI needs to know whether a capability is configured and
nothing more, so a leak here is a leak of a Proxmox token.
"""
import json

from fastapi.testclient import TestClient

from proxploy.models import HostCredential
from proxploy.services.pveum import CAPABILITIES
from tests.support import make_app, seed_host_row


def _seed(app, kinds):
    """A host carrying exactly `kinds` credential rows."""
    with app.state.sessionmaker() as db:
        h = seed_host_row(db)
        for kind in kinds:
            blob, ver = app.state.secretstore.encrypt(json.dumps(
                {"token_id": f"proxploy@pve!{kind}", "token_secret": "s"}).encode())
            db.add(HostCredential(host_id=h.id, kind=kind, encrypted_blob=blob,
                                  key_version=ver,
                                  public_meta=f"proxploy@pve!{kind}"))
        db.commit()
        return h.id


def test_a_host_with_no_credentials_reports_every_capability_false(
        tmp_path, bootstrap_admin):
    """False, not an omitted field: the UI must never have to tell
    "absent" from "unknown"."""
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app, [])
        caps = c.get(f"/api/v1/hosts/{host_id}").json()["capabilities"]
        assert caps == {k: False for k in CAPABILITIES}


def test_monitoring_only_reports_just_monitoring(tmp_path, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app, ["api_token:monitoring", "ssh_key"])
        caps = c.get(f"/api/v1/hosts/{host_id}").json()["capabilities"]
        assert caps["monitoring"] is True
        assert caps["lifecycle"] is False and caps["backup"] is False


def test_all_capabilities_present(tmp_path, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app, [f"api_token:{k}" for k in CAPABILITIES])
        caps = c.get(f"/api/v1/hosts/{host_id}").json()["capabilities"]
        assert caps == {k: True for k in CAPABILITIES}


def test_the_list_route_reports_it_too(tmp_path, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _seed(app, ["api_token:monitoring", "api_token:lifecycle"])
        row = c.get("/api/v1/hosts").json()[0]
        assert row["capabilities"]["lifecycle"] is True
        assert row["capabilities"]["console"] is False


def test_capability_state_carries_no_token_material(tmp_path, bootstrap_admin):
    """Booleans and nothing else: no token id, no secret, no blob."""
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app, ["api_token:monitoring"])
        caps = c.get(f"/api/v1/hosts/{host_id}").json()["capabilities"]
        assert all(isinstance(v, bool) for v in caps.values())
        assert "proxploy@pve" not in json.dumps(caps)


def test_a_rejected_token_leaves_the_other_capabilities_and_the_host_alone(
        tmp_path, csrf_header, bootstrap_admin):
    """The partial-failure case the onboarding flow is built around: one
    capability's token is refused, everything already stored stays stored,
    and the host is still there."""
    from tests.fakes.pve import FakePVE

    app = make_app(tmp_path, fake=FakePVE(fail=True))
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app, ["api_token:monitoring", "api_token:lifecycle"])
        r = c.post(f"/api/v1/hosts/{host_id}/credentials",
                   json={"token_id": "proxploy@pve!console",
                         "token_secret": "bad", "capability": "console"},
                   headers=csrf_header(c))
        assert r.status_code == 502 and r.json()["error"] == "token_rejected"
        caps = c.get(f"/api/v1/hosts/{host_id}").json()["capabilities"]
        assert caps["monitoring"] is True and caps["lifecycle"] is True
        assert caps["console"] is False


def test_a_capability_added_to_CAPABILITIES_appears_with_no_second_list(
        tmp_path, bootstrap_admin, monkeypatch):
    """The one-definition rule, enforced rather than asserted in a comment."""
    from proxploy.services.pveum import Capability

    monkeypatch.setitem(CAPABILITIES, "teleportation", Capability(
        key="teleportation", label="Teleportation", role="ProxployTeleport",
        token="teleportation", privileges=("VM.Audit",), why="test only"))
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app, ["api_token:monitoring"])
        caps = c.get(f"/api/v1/hosts/{host_id}").json()["capabilities"]
        assert caps["teleportation"] is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_hosts_capabilities.py -v`
Expected: FAIL — `KeyError: 'capabilities'` on every test.

- [ ] **Step 3: Add the helper**

In `backend/proxploy/api/hosts.py`, next to `_privilege_note` (around line 156):

```python
def _capability_state(kinds) -> dict[str, bool]:
    """Which capability tokens this host holds. Presence only.

    Never the token, the token id, or any part of the blob: the UI needs to
    know whether a capability is configured and nothing more. Keyed off
    CAPABILITIES so a capability added to services/pveum.py appears here
    with no second list to maintain, and a host with no credential rows
    reports every capability False rather than omitting the field.
    """
    stored = set(kinds)
    return {c: f"api_token:{c}" in stored for c in CAPABILITIES}
```

- [ ] **Step 4: Report it from both read routes**

Replace `list_hosts` (`api/hosts.py:330`):

```python
@router.get("")
def list_hosts(db=Depends(get_db), user: User = Depends(_read)):
    # One query for every host's credential kinds, not one per host: this
    # route is the hosts table's own fetch and N+1 here is N+1 on every
    # settings page load.
    kinds: dict[int, set[str]] = {}
    for host_id, kind in db.query(HostCredential.host_id, HostCredential.kind):
        kinds.setdefault(host_id, set()).add(kind)
    return [{"id": h.id, "name": h.name, "address": h.address,
             "node_name": h.node_name, "status": h.status,
             "last_error": h.last_error,
             "pve_version": h.pve_version, "node_shell_enabled": h.node_shell_enabled,
             "node_power_missing": h.node_power_missing,
             "team_id": h.team_id,
             "capabilities": _capability_state(kinds.get(h.id, ())),
             "last_seen_at": h.last_seen_at.isoformat() if h.last_seen_at else None}
            for h in db.query(Host).order_by(Host.id)]
```

In `host_detail` (`api/hosts.py:341`), materialize the credential query — it is now read twice — and add the field:

```python
    creds = db.query(HostCredential).filter_by(host_id=h.id).all()
    return {"id": h.id, "name": h.name, "address": h.address,
            "node_name": h.node_name, "status": h.status,
            "last_error": h.last_error,
            "pve_version": h.pve_version, "verify_tls": h.verify_tls,
            "node_shell_enabled": h.node_shell_enabled,
            "node_power_missing": h.node_power_missing, "team_id": h.team_id,
            "capabilities": _capability_state(c.kind for c in creds),
            "credentials": [{"kind": c.kind, "public_meta": c.public_meta,
                             "last_used_at": c.last_used_at.isoformat()
                             if c.last_used_at else None} for c in creds]}
```

- [ ] **Step 5: Run the new tests, then the host suite**

Run: `cd backend && python -m pytest tests/test_hosts_capabilities.py -v`
Expected: PASS (7 tests).

Run: `cd backend && python -m pytest tests/test_hosts.py tests/test_hosts_lifecycle.py tests/test_hosts_privileges.py tests/contract -q`
Expected: PASS — the reads only gained a key, and nothing under `tests/contract` pins the host response shape (checked: the only fixture there is `entitlement_token.fixture.json`).

- [ ] **Step 6: Commit**

```bash
git add backend/proxploy/api/hosts.py backend/tests/test_hosts_capabilities.py
git commit -m "feat(hosts): report per-capability credential presence on the host reads"
```

---

### Task 2: Onboarding captures a token per selected capability

**Files:**
- Modify: `frontend/src/components/HostForm.tsx`
- Test: `frontend/src/tests/host-form-capabilities.test.tsx` (create)

**Interfaces:**
- Consumes: `POST /hosts` (unchanged), `POST /hosts/{id}/credentials` with `{token_id, token_secret, capability}` from Task 1's untouched route; the existing `errText` helper in this file.
- Produces: no exported API change. `HostForm({ onCreated })` still calls `onCreated(host)` — but only once every filled capability token has been stored.

**Ruling (the spec says both things; this is the reconciliation, do not re-decide it):** the create form shows a token field only for capabilities the operator ticked, per the spec's "The form shows a field per capability the operator selected". The "all four, always visible" rule is about *state* — stored vs missing — and there is no state to show before the host exists; an unticked capability got no role and no token from the script, so a field for it would be a field nobody can fill. All four become visible the moment the host exists, in Task 3's list.

**Ruling (write it into the code as a comment, do not re-decide it):** `CAPABILITY_CHOICES` in this file stays the hand-written list it already is. The spec's one-list rule binds capability *state* (Task 1's map, Task 3's list). The create form has no host to read state from yet, and there is no route that lists capabilities without also generating a script, so adding one would be a second backend addition the spec explicitly does not ask for.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/tests/host-form-capabilities.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { ApiError } = vi.hoisted(() => ({
  ApiError: class extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) { super(`API ${status}`); this.status = status; this.body = body }
  },
}))

const calls: { path: string; body: any }[] = []
// Which capability the fake node rejects, by capability key.
let reject: string | null = null

vi.mock('../api/client', () => ({
  ApiError,
  api: vi.fn((path: string, opts?: RequestInit) => {
    const body = opts?.body ? JSON.parse(String(opts.body)) : null
    calls.push({ path, body })
    if (path === '/hosts') return Promise.resolve({ id: 7, name: body.name })
    if (path.endsWith('/credentials')) {
      if (body.capability === reject) {
        return Promise.reject(new ApiError(502, {
          error: 'token_rejected',
          detail: 'the new token did not work against https://10.0.0.5:8006, '
                + 'the old one is still in place: auth failed',
        }))
      }
      return Promise.resolve({ id: 7, rotated: [`api_token:${body.capability}`] })
    }
    return Promise.resolve({})
  }),
}))

import { HostForm } from '../components/HostForm'

const fill = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } })

const fillHost = () => {
  fill('Name', 'pve-01')
  fill('Address', 'https://10.0.0.5:8006')
  fill('API token id', 'proxploy@pve!monitoring')
  fill('API token secret', 'mon-secret')
}

const credentialCalls = () => calls.filter(c => c.path.endsWith('/credentials'))

describe('HostForm capability tokens', () => {
  beforeEach(() => { calls.length = 0; reject = null })
  afterEach(() => vi.restoreAllMocks())

  it('offers a token field for each capability still ticked, and none for the unticked', () => {
    render(<HostForm onCreated={() => {}} />)
    expect(screen.getByLabelText('Lifecycle token id')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText(/^Lifecycle$/))
    expect(screen.queryByLabelText('Lifecycle token id')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Backup token id')).toBeInTheDocument()
  })

  it('creates the host, then stores one capability token per filled pair', async () => {
    const onCreated = vi.fn()
    render(<HostForm onCreated={onCreated} />)
    fillHost()
    fill('Lifecycle token id', 'proxploy@pve!lifecycle')
    fill('Lifecycle token secret', 'lc-secret')
    fireEvent.click(screen.getByRole('button', { name: 'Add host' }))

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith({ id: 7, name: 'pve-01' }))
    expect(calls[0].path).toBe('/hosts')
    expect(credentialCalls()).toEqual([{
      path: '/hosts/7/credentials',
      body: { token_id: 'proxploy@pve!lifecycle', token_secret: 'lc-secret',
              capability: 'lifecycle' },
    }])
  })

  it('skips a capability whose token pair was left blank', async () => {
    const onCreated = vi.fn()
    render(<HostForm onCreated={onCreated} />)
    fillHost()
    fill('Console token id', 'proxploy@pve!console')  // secret left empty
    fireEvent.click(screen.getByRole('button', { name: 'Add host' }))
    await waitFor(() => expect(onCreated).toHaveBeenCalled())
    expect(credentialCalls()).toEqual([])
  })

  it('names the rejected capability, keeps the host, and does not advance', async () => {
    reject = 'console'
    const onCreated = vi.fn()
    render(<HostForm onCreated={onCreated} />)
    fillHost()
    fill('Lifecycle token id', 'proxploy@pve!lifecycle')
    fill('Lifecycle token secret', 'lc-secret')
    fill('Console token id', 'proxploy@pve!console')
    fill('Console token secret', 'bad')
    fireEvent.click(screen.getByRole('button', { name: 'Add host' }))

    // The host exists and works: this is not a failed onboarding.
    expect(await screen.findByText(/pve-01 was added/i)).toBeInTheDocument()
    expect(screen.getByText(/Console: .*did not work/i)).toBeInTheDocument()
    expect(screen.queryByText(/Lifecycle:/)).not.toBeInTheDocument()
    expect(onCreated).not.toHaveBeenCalled()
  })

  it('retries only the rejected capability, without re-creating the host', async () => {
    reject = 'console'
    const onCreated = vi.fn()
    render(<HostForm onCreated={onCreated} />)
    fillHost()
    fill('Lifecycle token id', 'proxploy@pve!lifecycle')
    fill('Lifecycle token secret', 'lc-secret')
    fill('Console token id', 'proxploy@pve!console')
    fill('Console token secret', 'bad')
    fireEvent.click(screen.getByRole('button', { name: 'Add host' }))
    await screen.findByText(/Console: .*did not work/i)

    reject = null
    calls.length = 0
    fill('Console token secret', 'good')
    fireEvent.click(screen.getByRole('button', { name: /retry/i }))

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith({ id: 7, name: 'pve-01' }))
    expect(calls.some(c => c.path === '/hosts')).toBe(false)
    expect(credentialCalls().map(c => c.body.capability)).toEqual(['console'])
  })

  it('lets the operator continue with the capability still missing', async () => {
    reject = 'backup'
    const onCreated = vi.fn()
    render(<HostForm onCreated={onCreated} />)
    fillHost()
    fill('Backup token id', 'proxploy@pve!backup')
    fill('Backup token secret', 'bad')
    fireEvent.click(screen.getByRole('button', { name: 'Add host' }))
    await screen.findByText(/Backup: .*did not work/i)

    fireEvent.click(screen.getByRole('button', { name: /continue without it/i }))
    expect(onCreated).toHaveBeenCalledWith({ id: 7, name: 'pve-01' })
  })

  it('behaves exactly as before when no capability token is filled in', async () => {
    const onCreated = vi.fn()
    render(<HostForm onCreated={onCreated} />)
    fillHost()
    fireEvent.click(screen.getByRole('button', { name: 'Add host' }))
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith({ id: 7, name: 'pve-01' }))
    expect(calls.map(c => c.path)).toEqual(['/hosts'])
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/tests/host-form-capabilities.test.tsx`
Expected: FAIL — `Unable to find a label with the text of: Lifecycle token id`.

- [ ] **Step 3: Add the state and the submit sequence**

In `frontend/src/components/HostForm.tsx`, below the existing `const [nodePower, setNodePower] = useState(false)`:

```tsx
  // One token per capability the operator ticked above, because the pveum
  // script prints one per capability and until now three of them had nowhere
  // to go. Keyed by capability so the retry path can tell which one the node
  // rejected.
  const [capTokens, setCapTokens] = useState<Record<string, { id: string; secret: string }>>({})
  // The host, once POST /hosts has succeeded. Non-null means a retry must NOT
  // create it again (409 host name already exists).
  const [created, setCreated] = useState<HostCreated | null>(null)
  const [storedCaps, setStoredCaps] = useState<string[]>([])
  const [capErrors, setCapErrors] = useState<Record<string, string>>({})
  const setCapToken = (key: string, field: 'id' | 'secret', v: string) =>
    setCapTokens(s => ({ ...s, [key]: { id: '', secret: '', ...s[key], [field]: v } }))
  const labelOf = (key: string) =>
    CAPABILITY_CHOICES.find(c => c.key === key)?.label ?? key
```

Replace `submit`:

```tsx
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError('')
    try {
      // `created` non-null is the retry path: the host already exists and
      // works for the capabilities that verified, so re-creating it would
      // 409 and rolling it back would throw away a working enrolment.
      const h = created ?? await api<HostCreated>('/hosts', {
        method: 'POST',
        body: JSON.stringify({ ...f, ssh_consent: f.ssh_enroll }) })
      setCreated(h)
      // Each token is verified against the node individually by
      // POST /hosts/{id}/credentials, so one rejection is one capability's
      // failure, not the enrolment's.
      const done = [...storedCaps]
      const failed: Record<string, string> = {}
      for (const key of caps) {
        const t = capTokens[key]
        if (done.includes(key) || !t?.id || !t?.secret) continue
        try {
          await api(`/hosts/${h.id}/credentials`, {
            method: 'POST',
            body: JSON.stringify({ token_id: t.id, token_secret: t.secret,
                                  capability: key }) })
          done.push(key)
        } catch (err) { failed[key] = `${labelOf(key)}: ${errText(err)}` }
      }
      setStoredCaps(done); setCapErrors(failed)
      if (!Object.keys(failed).length) onCreated(h)
    } catch (e) { setError(errText(e)) } finally { setBusy(false) }
  }
```

- [ ] **Step 4: Render the fields and the partial-failure panel**

Inside the "Don't have a token yet?" panel, directly after the `CAPABILITY_CHOICES` checkbox row and before the node-power checkbox, add the per-capability token fields:

```tsx
        {caps.length > 0 && (
          <div className="mt-3 space-y-3 border-t border-line-soft pt-3">
            <p className="text-[11.5px] text-text-3">
              The script prints one token per capability. Paste them here, or
              leave a pair blank and add it later from the host's Edit dialog.
            </p>
            {CAPABILITY_CHOICES.filter(c => caps.includes(c.key)).map(({ key, label }) => (
              <div key={key} className="grid gap-2 sm:grid-cols-2">
                <div>
                  <label htmlFor={`cap-${key}-id`}
                    className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
                    {label} token id
                  </label>
                  <input id={`cap-${key}-id`} className={inputCls}
                    placeholder={`proxploy@pve!${key}`}
                    disabled={storedCaps.includes(key)}
                    value={capTokens[key]?.id ?? ''}
                    onChange={e => setCapToken(key, 'id', e.target.value)} />
                </div>
                <div>
                  <label htmlFor={`cap-${key}-secret`}
                    className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
                    {label} token secret
                  </label>
                  <input id={`cap-${key}-secret`} type="password" className={inputCls}
                    disabled={storedCaps.includes(key)}
                    value={capTokens[key]?.secret ?? ''}
                    onChange={e => setCapToken(key, 'secret', e.target.value)} />
                </div>
                {storedCaps.includes(key) && (
                  <p className="text-[11.5px] text-green sm:col-span-2">{label} token stored.</p>
                )}
                {capErrors[key] && (
                  <p className="text-[12px] text-red sm:col-span-2">{capErrors[key]}</p>
                )}
              </div>
            ))}
          </div>
        )}
```

Above the submit row, the honest partial-failure banner:

```tsx
      {created && Object.keys(capErrors).length > 0 && (
        <div className="rounded-ctl border border-amber/30 bg-amber-dim p-3">
          <p className="text-[12.5px] text-amber">
            {created.name} was added and is working. Proxmox rejected the token for{' '}
            {Object.keys(capErrors).map(labelOf).join(', ')}, so that capability is
            not configured yet. Everything else was stored.
          </p>
          <p className="mt-1.5 text-[11.5px] text-text-3">
            Correct the token above and retry just that one, or continue and add it
            later from the host's Edit dialog.
          </p>
          <div className="mt-2 flex gap-2">
            <Button type="button" variant="ghost"
              onClick={() => onCreated(created)}>Continue without it</Button>
          </div>
        </div>
      )}
```

And make the submit button say what it now does:

```tsx
        <Button type="submit" disabled={busy}>
          {busy ? (created ? 'Retrying…' : 'Adding…')
                : (created ? 'Retry rejected token' : 'Add host')}
        </Button>
```

- [ ] **Step 5: Run the new tests and the existing HostForm suites**

Run: `cd frontend && npx vitest run src/tests/host-form-capabilities.test.tsx src/tests/onboarding.test.tsx src/tests/host-form-errors.test.tsx`
Expected: PASS. `onboarding.test.tsx` has a `screen.getByLabelText(/lifecycle/i)` on the capability *checkbox*; the new "Lifecycle token id"/"Lifecycle token secret" labels make that regex ambiguous. Tighten those queries to `/^Lifecycle$/` in the same commit — do not rename the new fields to dodge it.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/HostForm.tsx frontend/src/tests/host-form-capabilities.test.tsx frontend/src/tests/onboarding.test.tsx
git commit -m "feat(hosts): capture every selected capability's token during onboarding"
```

---

### Task 3: The four-capability list, in the host Edit dialog

**Files:**
- Create: `frontend/src/components/HostCapabilityList.tsx`
- Modify: `frontend/src/components/HostEditDialog.tsx`
- Test: `frontend/src/tests/host-capability-list.test.tsx` (create)

**Interfaces:**
- Consumes: `GET /hosts/{id}` from Task 1 — `{ capabilities: Record<string, boolean> }` — and `POST /hosts/{id}/credentials`.
- Produces: `export function HostCapabilityList({ hostId }: { hostId: number })`. Self-fetching on query key `['hosts', hostId]` so no call site has to thread capability state through props.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/tests/host-capability-list.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { ApiError } = vi.hoisted(() => ({
  ApiError: class extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) { super(`API ${status}`); this.status = status; this.body = body }
  },
}))

const calls: { path: string; body: any }[] = []
let capabilities: Record<string, boolean> = {
  monitoring: true, lifecycle: false, console: false, backup: false,
}
let reject = false

vi.mock('../api/client', () => ({
  ApiError,
  api: vi.fn((path: string, opts?: RequestInit) => {
    const body = opts?.body ? JSON.parse(String(opts.body)) : null
    calls.push({ path, body })
    if (path.endsWith('/credentials')) {
      if (reject) {
        return Promise.reject(new ApiError(502, {
          error: 'token_rejected',
          detail: 'the new token did not work against https://10.0.0.9:8006, '
                + 'the old one is still in place: auth failed',
        }))
      }
      return Promise.resolve({ id: 3, rotated: [`api_token:${body.capability}`] })
    }
    return Promise.resolve({ id: 3, name: 'pve-01', capabilities })
  }),
}))

import { HostCapabilityList } from '../components/HostCapabilityList'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: {
    queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}>
    <HostCapabilityList hostId={3} />
  </QueryClientProvider>)
}

describe('HostCapabilityList', () => {
  beforeEach(() => {
    calls.length = 0; reject = false
    capabilities = { monitoring: true, lifecycle: false, console: false, backup: false }
  })
  afterEach(() => vi.restoreAllMocks())

  it('lists every capability, stored and missing alike', async () => {
    wrap()
    expect(await screen.findByText('Monitoring')).toBeInTheDocument()
    for (const label of ['Lifecycle', 'Console', 'Backup']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it('renders a capability the backend added without a second list here', async () => {
    capabilities = { ...capabilities, teleportation: false }
    wrap()
    expect(await screen.findByText('Teleportation')).toBeInTheDocument()
  })

  it('offers monitoring as rotate-only, never missing or removable', async () => {
    wrap()
    await screen.findByText('Monitoring')
    expect(screen.getByRole('button', { name: 'Rotate Monitoring token' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /remove monitoring/i })).not.toBeInTheDocument()
    // Its fields are behind the rotate control, not open as an unfilled gap.
    expect(screen.queryByLabelText('Monitoring token id')).not.toBeInTheDocument()
  })

  it('shows a missing capability as an open field, and stores it with its own key', async () => {
    wrap()
    await screen.findByText('Lifecycle')
    fireEvent.change(screen.getByLabelText('Lifecycle token id'),
                     { target: { value: 'proxploy@pve!lifecycle' } })
    fireEvent.change(screen.getByLabelText('Lifecycle token secret'),
                     { target: { value: 'lc' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add Lifecycle token' }))

    await waitFor(() => expect(calls.at(-1)).toEqual({
      path: '/hosts/3/credentials',
      body: { token_id: 'proxploy@pve!lifecycle', token_secret: 'lc',
              capability: 'lifecycle' },
    }))
  })

  it('names the capability when the node rejects its token', async () => {
    reject = true
    wrap()
    await screen.findByText('Backup')
    fireEvent.change(screen.getByLabelText('Backup token id'), { target: { value: 'x' } })
    fireEvent.change(screen.getByLabelText('Backup token secret'), { target: { value: 'y' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add Backup token' }))
    expect(await screen.findByText(/Backup: .*did not work/i)).toBeInTheDocument()
  })

  it('never submits half a token pair', async () => {
    wrap()
    await screen.findByText('Console')
    fireEvent.change(screen.getByLabelText('Console token id'), { target: { value: 'only-id' } })
    const btn = screen.getByRole('button', { name: 'Add Console token' })
    expect(btn).toBeDisabled()
    fireEvent.click(btn)
    expect(calls.filter(c => c.path.endsWith('/credentials'))).toHaveLength(0)
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/tests/host-capability-list.test.tsx`
Expected: FAIL — cannot resolve `../components/HostCapabilityList`.

- [ ] **Step 3: Write the component**

Create `frontend/src/components/HostCapabilityList.tsx`:

```tsx
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../api/client'
import { inputCls } from './LoginForm'
import { Button } from './ui/button'

/**
 * Every capability the backend knows about, with its state: stored (rotate)
 * or missing (paste it in). Shown in full rather than only the gaps, because
 * a capability with no token fails at the moment the operator tries to use
 * the feature, far from any explanation.
 *
 * Fetches GET /hosts/{id} itself on the ['hosts', id] key rather than taking
 * the state through props, so no call site has to thread it down. The rows
 * come from the response's own `capabilities` map, which the backend keys off
 * services/pveum.py::CAPABILITIES -- there is deliberately no capability list
 * in this file to drift from it.
 */
type HostCapabilities = { capabilities?: Record<string, boolean> }

// Title-case beats a label table, which would be exactly the second list the
// spec forbids.
const labelOf = (key: string) => key.charAt(0).toUpperCase() + key.slice(1)

const detailOf = (e: unknown) =>
  e instanceof ApiError && typeof (e.body as { detail?: unknown })?.detail === 'string'
    ? (e.body as { detail: string }).detail
    : 'Request failed, try again.'

function CapabilityRow({ hostId, name, stored }: {
  hostId: number; name: string; stored: boolean
}) {
  const qc = useQueryClient()
  const label = labelOf(name)
  // A missing capability opens straight into its field: the gap IS the
  // prompt. A stored one stays behind Rotate so replacing a working token is
  // never one stray keystroke away.
  const [open, setOpen] = useState(!stored)
  const [tokenId, setTokenId] = useState('')
  const [tokenSecret, setTokenSecret] = useState('')
  const [error, setError] = useState('')
  const halfFilled = Boolean(tokenId) !== Boolean(tokenSecret)

  const save = useMutation({
    mutationFn: () => api(`/hosts/${hostId}/credentials`, {
      method: 'POST',
      body: JSON.stringify({ token_id: tokenId, token_secret: tokenSecret,
                            capability: name }) }),
    onSuccess: () => {
      setTokenId(''); setTokenSecret(''); setError(''); setOpen(false)
      // Prefix match: refreshes both the hosts table and this host's detail.
      qc.invalidateQueries({ queryKey: ['hosts'] })
    },
    // The route names the address and says the old credential is still in
    // place; naming the capability is what turns it from a bare 502 into
    // something the operator can act on.
    onError: (e) => setError(`${label}: ${detailOf(e)}`),
  })

  return (
    <div className="border-t border-line-soft py-2 first:border-t-0">
      <div className="flex items-center justify-between gap-3">
        <span className="text-[13px] text-text">{label}</span>
        <div className="flex items-center gap-2">
          <span className={`text-[11.5px] ${stored ? 'text-green' : 'text-text-3'}`}>
            {stored ? 'stored' : 'not configured'}
          </span>
          {stored && !open && (
            <Button type="button" variant="ghost" className="px-2 py-1 text-[11px]"
              aria-label={`Rotate ${label} token`}
              onClick={() => setOpen(true)}>Rotate</Button>
          )}
        </div>
      </div>
      {open && (
        <div className="mt-2 space-y-2">
          <div>
            <label htmlFor={`cap-${name}-id`}
              className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
              {label} token id
            </label>
            <input id={`cap-${name}-id`} className={inputCls} value={tokenId}
              placeholder={`proxploy@pve!${name}`}
              onChange={(e) => setTokenId(e.target.value)} />
          </div>
          <div>
            <label htmlFor={`cap-${name}-secret`}
              className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
              {label} token secret
            </label>
            <input id={`cap-${name}-secret`} type="password" className={inputCls}
              value={tokenSecret} onChange={(e) => setTokenSecret(e.target.value)} />
          </div>
          {halfFilled && (
            <p className="text-[12px] text-red">
              Token id and secret must both be filled in.
            </p>
          )}
          {error && <p className="text-[12px] text-red">{error}</p>}
          <div className="flex justify-end gap-2">
            {stored && (
              <Button type="button" variant="ghost"
                onClick={() => { setOpen(false); setError('') }}>Cancel</Button>
            )}
            <Button type="button"
              aria-label={`${stored ? 'Rotate' : 'Add'} ${label} token`}
              disabled={!tokenId || !tokenSecret || save.isPending}
              onClick={() => save.mutate()}>
              {save.isPending ? 'Verifying…' : stored ? 'Rotate' : 'Add'}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

export function HostCapabilityList({ hostId }: { hostId: number }) {
  const host = useQuery({
    queryKey: ['hosts', hostId],
    queryFn: () => api<HostCapabilities>(`/hosts/${hostId}`),
  })
  const caps = host.data?.capabilities
  if (!caps) return null
  return (
    <div>
      <p className="mb-1 text-[11px] uppercase tracking-wide text-text-3">
        Capability tokens
      </p>
      <p className="mb-2 text-[11.5px] text-text-3">
        The setup script prints one token per capability. A capability with no
        token fails the first time you use the feature, not here.
      </p>
      {Object.entries(caps).map(([name, stored]) => (
        <CapabilityRow key={name} hostId={hostId} name={name}
          // monitoring is required=True and the host cannot exist without it,
          // so it is rotate-only and never shown as a gap.
          stored={stored || name === 'monitoring'} />
      ))}
    </div>
  )
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/tests/host-capability-list.test.tsx`
Expected: PASS (6 tests).

- [ ] **Step 5: Wire it into the Edit dialog**

In `frontend/src/components/HostEditDialog.tsx`, import it:

```tsx
import { HostCapabilityList } from './HostCapabilityList'
```

and render it after the existing token secret field's block, before the `halfFilled` warning:

```tsx
        {/* The dialog's own two token fields rotate monitoring, which is what
            Save has always done. The other three capabilities have their own
            rows here, each verified individually by the same route. */}
        <div className="border-t border-line-soft pt-3">
          <HostCapabilityList hostId={hostId} />
        </div>
```

- [ ] **Step 6: Run the edit-dialog and actions-menu suites**

Run: `cd frontend && npx vitest run src/tests/host-edit-dialog.test.tsx src/tests/host-actions-menu.test.tsx src/tests/host-capability-list.test.tsx`
Expected: PASS. `host-edit-dialog.test.tsx` mocks `../api/client` wholesale, so the new `GET /hosts/{id}` inside the dialog returns whatever that mock returns; if it returns no `capabilities`, the list renders `null` and the existing assertions are unaffected. If any test there renders without a `QueryClientProvider`, wrap it — do not make the component tolerate a missing provider.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/HostCapabilityList.tsx frontend/src/components/HostEditDialog.tsx frontend/src/tests/host-capability-list.test.tsx
git commit -m "feat(hosts): show every capability token's state in the host Edit dialog"
```

---

### Task 4: The same list reachable from Settings

**Files:**
- Modify: `frontend/src/routes/settings.tsx` (hosts table row actions, around :305-:345)
- Test: `frontend/src/tests/settings-host-tokens.test.tsx` (create)

**Interfaces:**
- Consumes: `HostCapabilityList` from Task 3, `Dialog` from `../components/ui/dialog`.
- Produces: nothing exported. A per-row "Tokens" button opening the list in a dialog.

**Why:** the spec's problem statement is that the docs tell operators to add the other tokens in settings and settings has no such control. Settings' existing "Rotate" dialog is monitoring + SSH and is deliberately left alone — this adds a second, narrower entry point rather than restructuring a working dialog.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/tests/settings-host-tokens.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  api: vi.fn((path: string) => {
    if (path === `/hosts/3`) {
      return Promise.resolve({ id: 3, name: 'pve-01', capabilities: {
        monitoring: true, lifecycle: false, console: false, backup: false } })
    }
    return Promise.resolve({})
  }),
}))

import { HostTokensDialog } from '../routes/settings'

describe('Settings host tokens', () => {
  it('opens the capability list for one host', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={qc}>
      <HostTokensDialog hostId={3} hostName="pve-01" onClose={() => {}} />
    </QueryClientProvider>)
    expect(await screen.findByText('Lifecycle')).toBeInTheDocument()
    expect(screen.getByLabelText('Lifecycle token id')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/tests/settings-host-tokens.test.tsx`
Expected: FAIL — `HostTokensDialog` is not exported from `../routes/settings`.

- [ ] **Step 3: Add the dialog and the button**

In `frontend/src/routes/settings.tsx`, import the list and the dialog primitive alongside the existing imports:

```tsx
import { HostCapabilityList } from '../components/HostCapabilityList'
import { Dialog } from '../components/ui/dialog'
```

Add the component near the other host helpers in that file:

```tsx
/** The four capability tokens for one host. Settings is where the docs tell
 *  operators to add them, and until now it had no control for them at all.
 *  Separate from HostRotateDialog on purpose: that one is monitoring + the
 *  SSH key, and merging the two would put two different rotate paths for the
 *  same token in one card. */
export function HostTokensDialog({ hostId, hostName, onClose }: {
  hostId: number; hostName: string; onClose: () => void
}) {
  return (
    <Dialog title={<>Capability tokens, {hostName}</>} width={440} onClose={onClose}>
      <div className="mt-4">
        <HostCapabilityList hostId={hostId} />
      </div>
    </Dialog>
  )
}
```

Add the state next to `rotatingHost`:

```tsx
  const [tokensHost, setTokensHost] = useState<{ id: number; name: string } | null>(null)
```

Add the button in the row's action group, immediately after "Rotate":

```tsx
                          <Button variant="ghost" className="px-2 py-1 text-[11px]"
                            onClick={() => setTokensHost(h)}>Tokens</Button>
```

And render it beside the other dialogs at the bottom of the Hosts card:

```tsx
        {tokensHost && (
          <HostTokensDialog hostId={tokensHost.id} hostName={tokensHost.name}
            onClose={() => setTokensHost(null)} />
        )}
```

- [ ] **Step 4: Run the test and the settings suites**

Run: `cd frontend && npx vitest run src/tests/settings-host-tokens.test.tsx src/tests/host-rotate.test.tsx`
Expected: PASS.

- [ ] **Step 5: Run the whole frontend and backend suites**

Run: `cd frontend && npm test`
Expected: PASS. The hosts table gained a column-width's worth of button; if `harness:cards`/`harness:dialog` overflow checks are part of the gate, run `npm run harness` too and fix any overflow by wrapping, not by shrinking the card.

Run: `cd backend && python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/settings.tsx frontend/src/tests/settings-host-tokens.test.tsx
git commit -m "feat(hosts): reach the capability token list from Settings"
```

---

## Notes carried out of the spec

- **Not built, on purpose:** no credential delete (rotation replaces), no provisioning, no change to `services/pveum.py`, no change to the SSH key path, and no new backend route beyond the one field on the two existing reads.
- **Verification stays where it is.** Every token in every surface here goes through `POST /hosts/{host_id}/credentials`. If a check feels missing, it belongs in that route, not in a caller.
- **The partial-failure state is the load-bearing one.** Task 2's "host created, one token rejected" path is the only place this design pays for reusing the existing route instead of duplicating verification. Reviewers should look hardest there.
