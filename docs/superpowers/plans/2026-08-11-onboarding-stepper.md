# Onboarding Stepper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the onboarding wizard's forward-only chip row with a vertical
left rail whose completed steps tick green and stay clickable, so a mistake made
earlier in setup can be corrected without finishing setup first.

**Architecture:** The wizard keeps deriving *where you must be* from server state
(`stepFrom`), and gains a separate *what you are looking at* (`view`) that can
move backwards. The rail is a new presentational component driven by a status
array the wizard computes. Revisiting a completed step shows an edit affordance
built only from endpoints that already exist.

**Tech Stack:** React 19, TanStack Router + Query, Tailwind CSS v4, Vitest +
Testing Library, Playwright.

Spec: `docs/superpowers/specs/2026-08-11-onboarding-stepper-design.md`

## Global Constraints

- **Frontend only.** No file under `backend/` is modified by this plan.
- **Colours come from tokens**, never hex. `src/tests/no-hardcoded-colors.test.ts`
  allowlists `routes/onboarding.tsx` but **not** new components. Available
  tokens: `panel`, `panel-2`, `elev`, `line`, `line-soft`, `text`, `text-2`,
  `text-3`, `amber`, `amber-dim`, `green`, `green-dim`, `red`, `red-dim`, `ink`.
  Radii: `rounded-card`, `rounded-ctl`.
- **Vitest must be run with `--no-file-parallelism`** — suites flake without it
  (README "Tests").
- **The 10 existing tests in `src/tests/onboarding.test.tsx` stay green.** Tests
  asserting on chip markup get updated, never deleted.
- **Every transition sits behind `prefers-reduced-motion: reduce`.**
- `PROXPLOY_*` env, API paths, and the `/api/v1` prefix are untouched; the
  frontend `api()` helper already prefixes.

---

## File Structure

| File | Responsibility |
|---|---|
| Create `src/components/OnboardingRail.tsx` | Presentational rail. Renders four steps with status, handles clicks. No data fetching. |
| Create `src/components/AdminAccountStep.tsx` | Step 1 in both modes: create form, and the revisit/edit panel. |
| Create `src/tests/onboarding-rail.test.tsx` | Rail unit tests. |
| Modify `src/routes/onboarding.tsx` | Two-pane shell, `view` state, step status derivation, host/ssh/done steps. |
| Modify `src/styles/tokens.css` | Two keyframes for the rail + content motion. |
| Modify `src/tests/onboarding.test.tsx` | Extend the `api` mock; update chip assertions; add back-navigation tests. |
| Modify `e2e/journey.spec.ts` | One back-navigation assertion. |

---

### Task 1: The rail component

**Files:**
- Create: `frontend/src/components/OnboardingRail.tsx`
- Test: `frontend/src/tests/onboarding-rail.test.tsx`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  ```ts
  export type StepStatus = 'done' | 'current' | 'todo' | 'skipped'
  export type RailStep = { label: string; status: StepStatus
                           detail?: string; reachable: boolean }
  export function OnboardingRail(props: { steps: RailStep[]; view: number
                                          onSelect: (index: number) => void }): JSX.Element
  ```
  Task 2 imports both the type and the component.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/tests/onboarding-rail.test.tsx
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { OnboardingRail, type RailStep } from '../components/OnboardingRail'

const steps: RailStep[] = [
  { label: 'Admin account', status: 'done', detail: 'ops@acme.io', reachable: true },
  { label: 'First host', status: 'current', reachable: true },
  { label: 'Authorize installs', status: 'todo', reachable: false },
  { label: 'Done', status: 'todo', reachable: false },
]

describe('OnboardingRail', () => {
  it('marks the completed step done and the active step current', () => {
    render(<OnboardingRail steps={steps} view={1} onSelect={() => {}} />)
    expect(screen.getByRole('button', { name: /admin account/i })
      .getAttribute('data-status')).toBe('done')
    expect(screen.getByRole('button', { name: /first host/i })
      .getAttribute('aria-current')).toBe('step')
  })

  it('shows the summary detail on a completed step', () => {
    render(<OnboardingRail steps={steps} view={1} onSelect={() => {}} />)
    expect(screen.getByText('ops@acme.io')).toBeInTheDocument()
  })

  it('calls onSelect for a reachable step', () => {
    const onSelect = vi.fn()
    render(<OnboardingRail steps={steps} view={1} onSelect={onSelect} />)
    fireEvent.click(screen.getByRole('button', { name: /admin account/i }))
    expect(onSelect).toHaveBeenCalledWith(0)
  })

  it('does not call onSelect for an unreachable step', () => {
    const onSelect = vi.fn()
    render(<OnboardingRail steps={steps} view={1} onSelect={onSelect} />)
    fireEvent.click(screen.getByRole('button', { name: /authorize installs/i }))
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('renders a skipped step as skipped and still reachable', () => {
    const skipped: RailStep[] = [
      ...steps.slice(0, 1),
      { label: 'First host', status: 'skipped', detail: 'Skipped', reachable: true },
      ...steps.slice(2),
    ]
    const onSelect = vi.fn()
    render(<OnboardingRail steps={skipped} view={3} onSelect={onSelect} />)
    const host = screen.getByRole('button', { name: /first host/i })
    expect(host.getAttribute('data-status')).toBe('skipped')
    fireEvent.click(host)
    expect(onSelect).toHaveBeenCalledWith(1)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/tests/onboarding-rail.test.tsx --no-file-parallelism`
Expected: FAIL — cannot resolve `../components/OnboardingRail`.

- [ ] **Step 3: Write minimal implementation**

```tsx
// frontend/src/components/OnboardingRail.tsx
export type StepStatus = 'done' | 'current' | 'todo' | 'skipped'

export type RailStep = {
  label: string
  status: StepStatus
  detail?: string
  reachable: boolean
}

// A step is a <button> even when unreachable: disabled buttons keep the step
// list one uniform control type for the screen reader, and `reachable` is what
// decides whether the click does anything.
const dot: Record<StepStatus, string> = {
  done: 'bg-green text-ink border-green',
  current: 'bg-transparent text-amber border-amber shadow-[0_0_0_4px_var(--color-amber-dim)]',
  todo: 'bg-transparent text-text-3 border-line',
  skipped: 'bg-transparent text-text-3 border-line border-dashed',
}

const label: Record<StepStatus, string> = {
  done: 'text-text-2', current: 'text-text font-semibold',
  todo: 'text-text-3', skipped: 'text-text-3',
}

export function OnboardingRail({ steps, view, onSelect }: {
  steps: RailStep[]; view: number; onSelect: (index: number) => void
}) {
  return (
    <ol className="flex gap-1 md:flex-col md:gap-0">
      {steps.map((s, i) => (
        <li key={s.label} className="relative flex-1 md:flex-none">
          {i < steps.length - 1 && (
            <span aria-hidden
              className={`absolute left-[7.5px] top-4 hidden h-[calc(100%-1rem)] w-px origin-top
                md:block ${s.status === 'done' ? 'bg-green pp-rail-fill' : 'bg-line'}`} />
          )}
          <button
            type="button"
            data-status={s.status}
            aria-current={s.status === 'current' ? 'step' : undefined}
            disabled={!s.reachable}
            onClick={() => s.reachable && onSelect(i)}
            className={`flex w-full items-start gap-2.5 pb-4 text-left transition
              ${s.reachable ? 'cursor-pointer hover:opacity-80' : 'cursor-default'}`}
          >
            <span className={`grid size-4 shrink-0 place-items-center rounded-full border
              text-[9px] font-bold transition ${dot[s.status]}`}>
              {s.status === 'done' ? <span className="pp-tick">✓</span>
                : s.status === 'skipped' ? '–' : i + 1}
            </span>
            <span className="min-w-0">
              <span className={`block text-[11px] leading-tight ${label[s.status]}`}>{s.label}</span>
              {s.detail && (
                <span className="mt-0.5 block truncate text-[9.5px] text-text-3">{s.detail}</span>
              )}
            </span>
          </button>
        </li>
      ))}
    </ol>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/tests/onboarding-rail.test.tsx --no-file-parallelism`
Expected: PASS, 5 tests.

- [ ] **Step 5: Verify the colour guard still passes**

Run: `cd frontend && npx vitest run src/tests/no-hardcoded-colors.test.ts --no-file-parallelism`
Expected: PASS. `OnboardingRail.tsx` is not allowlisted, so any hex here fails the build.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/OnboardingRail.tsx frontend/src/tests/onboarding-rail.test.tsx
git commit -m "feat(onboarding): add the vertical step rail component"
```

---

### Task 2: Two-pane shell and backward navigation

**Files:**
- Modify: `frontend/src/routes/onboarding.tsx`
- Modify: `frontend/src/tests/onboarding.test.tsx`

**Interfaces:**
- Consumes: `OnboardingRail`, `RailStep` from Task 1.
- Produces: `Wizard` keeps its existing named export. Internally exposes
  `view: number`, `setView(n: number)`, and `railSteps(): RailStep[]`. Task 3
  and Task 4 render inside the content pane this task creates.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/tests/onboarding.test.tsx`, inside `describe('onboarding wizard')`:

```tsx
  it('lets you go back to a completed step', async () => {
    mockOnboarding({ admin_exists: true, host_added: false, ssh_pending: false, complete: false })
    renderWizard()
    // Lands on the host step, per the resume behaviour above.
    expect(await screen.findByLabelText('API token id')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /admin account/i }))
    expect(await screen.findByText(/cannot be changed/i)).toBeInTheDocument()
  })

  it('does not let you jump forward past the step the server is on', async () => {
    mockOnboarding({ admin_exists: true, host_added: false, ssh_pending: false, complete: false })
    renderWizard()
    await screen.findByLabelText('API token id')
    expect(screen.getByRole('button', { name: /authorize installs/i }))
      .toBeDisabled()
  })
```

Extend the `api` mock's handler (it currently returns `null` for unknown paths)
so `/auth/me` resolves. Inside the `vi.mock('../api/client', ...)` factory, add
this line immediately after the `/meta/onboarding` line:

```ts
      if (path === '/auth/me') return Promise.resolve({ id: 1, email: 'ops@acme.io',
        display_name: 'Ops', role: 'owner', totp_enabled: false })
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/tests/onboarding.test.tsx --no-file-parallelism`
Expected: FAIL — no button named "Admin account" exists; the chips are `<span>`.

- [ ] **Step 3: Write minimal implementation**

In `frontend/src/routes/onboarding.tsx`, replace the `advanced` state and the
whole returned JSX shell. Keep `stepFrom`, `verifySsh`, `createAdmin`, `finish`,
and the `storedHost` query exactly as they are.

```tsx
import { OnboardingRail, type RailStep } from '../components/OnboardingRail'

const STEPS = ['Admin account', 'First host', 'Authorize installs', 'Done'] as const
```

State, replacing `const [advanced, setAdvanced] = useState<number | null>(null)`:

```tsx
  // `serverStep` is where setup actually is; `view` is what is on screen and is
  // the only thing that may move backwards. Keeping them apart is what makes
  // Back possible without pretending a committed step can be undone.
  const serverStep = ob.data ? stepFrom(ob.data) : 0
  const [view, setView] = useState<number | null>(null)
  const [skipped, setSkipped] = useState(false)
  const step = view ?? serverStep
  const [dir, setDir] = useState<1 | -1>(1)

  function go(n: number) {
    setDir(n >= step ? 1 : -1)
    setView(n)
  }

  // Advancing past a step also drops the local view override, so the server's
  // opinion takes over again on the next render and a reload re-derives.
  function advance(n: number) {
    setDir(1)
    setView(n)
    qc.invalidateQueries({ queryKey: ['onboarding'] })
  }
```

Status derivation and the rail model:

```tsx
  const me = useQuery({ queryKey: ['me'], queryFn: () => api<MeOut>('/auth/me'),
    enabled: !!ob.data?.admin_exists })

  const done = [
    !!ob.data?.admin_exists,
    !!ob.data?.host_added,
    !!ob.data?.host_added && !ob.data?.ssh_pending,
    false,
  ]

  const railSteps: RailStep[] = STEPS.map((label, i) => {
    const status: RailStep['status'] =
      i === step ? 'current'
        : done[i] ? 'done'
          : skipped && (i === 1 || i === 2) ? 'skipped'
            : 'todo'
    const detail = i === 0 && done[0] ? me.data?.email
      : status === 'skipped' ? 'Skipped'
        : undefined
    // Reachable means "clicking this does something": anything already done,
    // anything skipped (so changing your mind costs one click), and the step
    // the server is actually on. Never a step in front of the server.
    return { label, status, detail,
             reachable: done[i] || status === 'skipped' || i <= serverStep }
  })
```

Add the type alongside the existing ones:

```tsx
type MeOut = { id: number; email: string; display_name: string }
```

The shell, replacing the outer two `<div>`s and the chip header:

```tsx
  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <aside className="shrink-0 border-b border-line bg-panel px-5 py-4
                        md:w-[152px] md:border-b-0 md:border-r md:py-6">
        <Brand />
        <p className="mb-4 mt-1 text-[9px] uppercase tracking-wide text-text-3 md:mb-5">
          Setup · {Math.min(step + 1, STEPS.length)} of {STEPS.length}
        </p>
        <OnboardingRail steps={railSteps} view={step} onSelect={go} />
      </aside>

      <main className="grid flex-1 place-items-center px-5 py-8">
        <div key={step} className={`w-full max-w-[380px] ${dir === 1 ? 'pp-in-fwd' : 'pp-in-back'}`}>
          {step > 0 && (
            <button type="button" onClick={() => go(step - 1)}
              className="mb-3 cursor-pointer text-[12px] text-text-3 transition hover:text-text-2">
              ← Back
            </button>
          )}
          {/* step panels unchanged from here, see Tasks 3 and 4 */}
        </div>
      </main>
    </div>
  )
```

Keep the existing `{step === 0 && ...}` … `{step === 3 && ...}` blocks inside
that `max-w-[380px]` div for now. Change only the skip handler on step 1:

```tsx
            <Button variant="ghost" onClick={() => { setSkipped(true); advance(3) }}>
              Skip for now
            </Button>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/tests/onboarding.test.tsx --no-file-parallelism`
Expected: PASS. The "lets you go back" test still fails at this point — it
depends on Task 3's read-only email copy. Mark it `it.skip` with the comment
`// unskipped in Task 3` and unskip it there. Every other test, including all 10
pre-existing ones, must pass now.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/onboarding.tsx frontend/src/tests/onboarding.test.tsx
git commit -m "feat(onboarding): two-pane shell with a rail you can navigate backwards"
```

---

### Task 3: Revisiting the admin step

**Files:**
- Create: `frontend/src/components/AdminAccountStep.tsx`
- Modify: `frontend/src/routes/onboarding.tsx`
- Modify: `frontend/src/tests/onboarding.test.tsx`

**Interfaces:**
- Consumes: `MeOut` shape from Task 2 (`{ id, email, display_name }`).
- Produces:
  ```ts
  export function AdminAccountStep(props: {
    existing: { id: number; email: string; display_name: string } | null
    onCreated: () => void
  }): JSX.Element
  ```
  `existing === null` renders the create form; non-null renders the edit panel.

- [ ] **Step 1: Write the failing test**

Unskip the "lets you go back to a completed step" test from Task 2, and add:

```tsx
  it('re-logs in after a password reset so the wizard is not logged out', async () => {
    const { api } = await import('../api/client')
    mockOnboarding({ admin_exists: true, host_added: false, ssh_pending: false, complete: false })
    renderWizard()
    await screen.findByLabelText('API token id')
    fireEvent.click(screen.getByRole('button', { name: /admin account/i }))

    fireEvent.change(await screen.findByLabelText('New password'),
      { target: { value: 'correct-horse-battery' } })
    fireEvent.click(screen.getByRole('button', { name: /set new password/i }))

    await screen.findByText(/password updated/i)
    const calls = (api as unknown as { mock: { calls: [string, RequestInit?][] } }).mock.calls
    const paths = calls.map(c => c[0])
    // The reset revokes every session including this one, so the login that
    // follows it is what keeps the wizard usable.
    expect(paths).toContain('/users/1/password')
    expect(paths.indexOf('/auth/login')).toBeGreaterThan(paths.indexOf('/users/1/password'))
  })
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/tests/onboarding.test.tsx --no-file-parallelism`
Expected: FAIL — no "New password" label, and no `/cannot be changed/` copy.

- [ ] **Step 3: Write minimal implementation**

```tsx
// frontend/src/components/AdminAccountStep.tsx
import { useState } from 'react'
import { api } from '../api/client'
import { inputCls } from './LoginForm'
import { Button } from './ui/button'

type Existing = { id: number; email: string; display_name: string }

export function AdminAccountStep({ existing, onCreated }: {
  existing: Existing | null
  onCreated: () => void
}) {
  const [admin, setAdmin] = useState({ email: '', password: '', display_name: '' })
  const [error, setError] = useState('')

  async function createAdmin(e: React.FormEvent) {
    e.preventDefault(); setError('')
    try {
      await api('/users', { method: 'POST', body: JSON.stringify(admin) })
      await api('/auth/login', { method: 'POST',
        body: JSON.stringify({ email: admin.email, password: admin.password }) })
      onCreated()
    } catch { setError('Could not create the admin account (password: 12+ characters).') }
  }

  if (existing) return <EditPanel existing={existing} />

  return (
    <form onSubmit={createAdmin} className="space-y-4">
      <Heading title="Create your admin account"
        sub="This is the account you will sign in with. Its email cannot be changed later." />
      {([['email', 'Email', 'email'], ['display_name', 'Display name', 'text'],
         ['password', 'Password (12+ chars)', 'password']] as const).map(([k, label, type]) => (
        <div key={k}>
          <label htmlFor={k} className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">{label}</label>
          <input id={k} type={type} required={k !== 'display_name'} className={inputCls}
            value={admin[k]} onChange={e => setAdmin(a => ({ ...a, [k]: e.target.value }))} />
        </div>
      ))}
      {error && <p className="text-[12.5px] text-red">{error}</p>}
      <Button type="submit" className="w-full">Create admin account</Button>
    </form>
  )
}

function Heading({ title, sub }: { title: string; sub: string }) {
  return (
    <div>
      <h1 className="text-[15px] font-semibold text-text">{title}</h1>
      <p className="mt-0.5 text-[12px] text-text-3">{sub}</p>
    </div>
  )
}

function EditPanel({ existing }: { existing: Existing }) {
  const [name, setName] = useState(existing.display_name ?? '')
  const [pw, setPw] = useState('')
  const [note, setNote] = useState('')
  const [error, setError] = useState('')

  async function saveName() {
    setError(''); setNote('')
    // PATCH rejects a no-op body with 422, so skip the call when nothing moved.
    if (name === existing.display_name) { setNote('Display name unchanged.'); return }
    try {
      await api(`/users/${existing.id}`, { method: 'PATCH',
        body: JSON.stringify({ display_name: name }) })
      setNote('Display name updated.')
    } catch { setError('Could not update the display name.') }
  }

  async function savePassword() {
    setError(''); setNote('')
    try {
      await api(`/users/${existing.id}/password`, { method: 'POST',
        body: JSON.stringify({ password: pw }) })
      // The reset revokes every session, this one included. Logging straight
      // back in is what stops the wizard dropping you at the login screen.
      await api('/auth/login', { method: 'POST',
        body: JSON.stringify({ email: existing.email, password: pw }) })
      setPw(''); setNote('Password updated.')
    } catch { setError('Could not set the password (12+ characters).') }
  }

  return (
    <div className="space-y-4">
      <Heading title="Your admin account" sub="Created already, so some of it is now fixed." />

      <div>
        <span className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">Email</span>
        <p className="rounded-ctl border border-line bg-panel-2 px-3 py-2 text-[13.5px] text-text-2">
          {existing.email}
        </p>
        <p className="mt-1 text-[11.5px] text-text-3">
          The email cannot be changed once the account exists. Create a second
          account from Settings if you need a different one.
        </p>
      </div>

      <div>
        <label htmlFor="edit-name" className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
          Display name
        </label>
        <input id="edit-name" className={inputCls} value={name}
          onChange={e => setName(e.target.value)} />
      </div>

      <div>
        <label htmlFor="edit-pw" className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
          New password
        </label>
        <input id="edit-pw" type="password" className={inputCls} value={pw}
          onChange={e => setPw(e.target.value)} />
      </div>

      {note && <p className="text-[12.5px] text-green">{note}</p>}
      {error && <p className="text-[12.5px] text-red">{error}</p>}

      <div className="flex gap-2">
        <Button variant="ghost" onClick={saveName}>Save display name</Button>
        <Button onClick={savePassword} disabled={pw.length < 12}>Set new password</Button>
      </div>
    </div>
  )
}
```

In `onboarding.tsx`, delete the inline `createAdmin` and the `admin` state, and
replace the `{step === 0 && (...)}` block with:

```tsx
        {step === 0 && (
          <AdminAccountStep
            existing={ob.data?.admin_exists && me.data ? me.data : null}
            onCreated={() => advance(1)}
          />
        )}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/tests/onboarding.test.tsx --no-file-parallelism`
Expected: PASS, including the previously skipped back-navigation test.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/AdminAccountStep.tsx frontend/src/routes/onboarding.tsx frontend/src/tests/onboarding.test.tsx
git commit -m "feat(onboarding): edit the admin account after it exists"
```

---

### Task 4: Revisiting the host step

**Files:**
- Modify: `frontend/src/routes/onboarding.tsx`
- Modify: `frontend/src/tests/onboarding.test.tsx`

**Interfaces:**
- Consumes: `HostRemoveDialog({ hostId, hostName, onClose, onRemoved })` from
  `src/components/HostRemoveDialog.tsx`, unchanged.
- Produces: nothing new for later tasks.

- [ ] **Step 1: Write the failing test**

```tsx
  it('offers remove-and-re-add when you go back to a host already added', async () => {
    mockOnboarding({ admin_exists: true, host_added: true, ssh_pending: true, complete: false })
    mockStoredHost({ id: 7, credentials: [] })
    renderWizard()
    await screen.findByRole('button', { name: 'Verify access' })
    fireEvent.click(screen.getByRole('button', { name: /first host/i }))
    expect(await screen.findByRole('button', { name: /remove and re-add/i })).toBeInTheDocument()
    // The add form must NOT be offered while a host still exists.
    expect(screen.queryByLabelText('API token id')).not.toBeInTheDocument()
  })

  it('keeps a skipped host step clickable', async () => {
    mockOnboarding({ admin_exists: true, host_added: false, ssh_pending: false, complete: false })
    renderWizard()
    await screen.findByLabelText('API token id')
    fireEvent.click(screen.getByRole('button', { name: /skip for now/i }))
    const host = await screen.findByRole('button', { name: /first host/i })
    expect(host.getAttribute('data-status')).toBe('skipped')
    expect(host).not.toBeDisabled()
  })
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/tests/onboarding.test.tsx --no-file-parallelism`
Expected: FAIL — no "Remove and re-add" button.

- [ ] **Step 3: Write minimal implementation**

Add to `onboarding.tsx`:

```tsx
import { HostRemoveDialog } from '../components/HostRemoveDialog'

  const [removing, setRemoving] = useState(false)
```

Replace the `{step === 1 && (...)}` block:

```tsx
        {step === 1 && (ob.data?.host_added ? (
          <div className="space-y-3">
            <h1 className="text-[15px] font-semibold text-text">Your first host</h1>
            <p className="text-[12.5px] text-text-2">
              {storedHostName ?? 'A host'} is connected. Its address and API token
              cannot be edited in place; to correct either one, remove it and add it again.
            </p>
            <Button variant="danger" onClick={() => setRemoving(true)}>Remove and re-add</Button>
            {removing && hostId != null && (
              <HostRemoveDialog
                hostId={hostId}
                hostName={storedHostName ?? ''}
                onClose={() => setRemoving(false)}
                onRemoved={() => {
                  setRemoving(false); setHost(null)
                  qc.invalidateQueries({ queryKey: ['onboarding'] })
                  qc.invalidateQueries({ queryKey: ['onboarding-host'] })
                }}
              />
            )}
          </div>
        ) : (
          <div className="space-y-3">
            <h1 className="text-[15px] font-semibold text-text">Add your first host</h1>
            <p className="text-[12px] text-text-3">Proxploy connects over the Proxmox API.</p>
            <HostForm onCreated={h => { setHost(h); advance(h.ssh_public_key ? 2 : 3) }} />
            <Button variant="ghost" onClick={() => { setSkipped(true); advance(3) }}>Skip for now</Button>
            <p className="text-[12px] text-text-3">
              You can add a host later from Settings. Everything except managing nodes works without one.
            </p>
          </div>
        ))}
```

The `storedHost` query is currently gated on `step === 2 && !host`. Widen it so
the host summary can name the host on step 1 too:

```tsx
  const needStoredHost = (step === 1 || step === 2) && !host
```

and add, beside `hostId`:

```tsx
  const storedHostName = host?.name ?? storedHost.data?.name ?? null
```

Extend the `HostDetail` type with `name`:

```tsx
type HostDetail = { id: number; name: string
                    credentials: { kind: string; public_meta: string | null }[] }
```

Update `mockStoredHost` calls in the test file to include a name, e.g.
`mockStoredHost({ id: 7, name: 'pve1', credentials: [] })`, and add `name: 'pve1'`
to the `HostDetail` type declared at the top of the test file.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run --no-file-parallelism`
Expected: PASS across the whole frontend suite.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/onboarding.tsx frontend/src/tests/onboarding.test.tsx
git commit -m "feat(onboarding): correct a host by removing and re-adding it"
```

---

### Task 5: Motion, and the end-to-end back path

**Files:**
- Modify: `frontend/src/styles/tokens.css`
- Modify: `frontend/e2e/journey.spec.ts`

**Interfaces:**
- Consumes: the `pp-rail-fill`, `pp-tick`, `pp-in-fwd`, `pp-in-back` class names
  emitted by Tasks 1 and 2.
- Produces: nothing.

- [ ] **Step 1: Write the failing e2e step**

In `e2e/journey.spec.ts`, immediately after the existing
`test.step('onboarding: admin account', ...)` block, add:

```ts
  await test.step('onboarding: the admin step is reachable again', async () => {
    await page.getByRole('button', { name: /admin account/i }).click()
    await expect(page.getByText(/cannot be changed/i)).toBeVisible()
    await page.getByRole('button', { name: /← back|first host/i }).first().click()
  })
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npx playwright test journey.spec.ts`
Expected: FAIL if the rail is not reachable from that point in the journey.
If the journey's helper skips the wizard entirely (`e2e/helpers.ts` documents
that it does), delete this e2e step instead and rely on the Vitest coverage —
record that decision in the commit message rather than leaving a broken test.

- [ ] **Step 3: Add the keyframes**

Append to `frontend/src/styles/tokens.css`:

```css
/* Onboarding rail + step motion. Every rule here is opt-out by default under
   prefers-reduced-motion, at the bottom of this block. */
@keyframes pp-rail-fill { from { transform: scaleY(0) } to { transform: scaleY(1) } }
@keyframes pp-tick      { from { transform: scale(.4); opacity: 0 } to { transform: scale(1); opacity: 1 } }
@keyframes pp-in-fwd    { from { opacity: 0; transform: translateX(8px) } to { opacity: 1; transform: none } }
@keyframes pp-in-back   { from { opacity: 0; transform: translateX(-8px) } to { opacity: 1; transform: none } }

.pp-rail-fill { animation: pp-rail-fill .35s ease-out both }
.pp-tick      { animation: pp-tick .25s cubic-bezier(.2,.9,.3,1.4) both; display: inline-block }
.pp-in-fwd    { animation: pp-in-fwd .22s ease-out both }
.pp-in-back   { animation: pp-in-back .22s ease-out both }

@media (prefers-reduced-motion: reduce) {
  .pp-rail-fill, .pp-tick, .pp-in-fwd, .pp-in-back { animation: none }
}
```

- [ ] **Step 4: Verify in the running app**

Run the dev servers (`backend/.venv/bin/uvicorn --factory proxploy.main:create_app --reload --port 8000`
and `cd frontend && npm run dev`), open `http://localhost:5173/onboarding`
(note: `localhost`, not `127.0.0.1` — Vite 8 binds IPv6 here), and confirm the
rail fills and the tick pops when a step completes.

- [ ] **Step 5: Run the full suite**

Run: `cd frontend && npx vitest run --no-file-parallelism && npx tsc -b && npx oxlint`
Expected: all pass, no type errors, no lint errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/styles/tokens.css frontend/e2e/journey.spec.ts
git commit -m "feat(onboarding): animate the rail, honouring reduced-motion"
```

---

## Self-Review

**Spec coverage.** Layout → Task 2. Step state (`serverStep`/`view`) → Task 2.
Per-step back behaviour: admin → Task 3, host → Task 4, authorize and done →
unchanged, covered by the existing suite. Skip reachability → Tasks 2 and 4.
Motion → Task 5. Testing → each task's own steps plus Task 5's full-suite gate.
No spec section is unimplemented.

**Placeholders.** None. Every code step carries the actual code. Task 5 Step 2
names an explicit fallback rather than leaving the outcome open.

**Type consistency.** `RailStep`/`StepStatus` defined in Task 1 and imported in
Task 2. `MeOut` defined in Task 2 and consumed by Task 3's `Existing` (same
three fields). `HostDetail` gains `name` in Task 4, and the test fixture is
updated in the same step. `HostRemoveDialog`'s four props match its current
signature in `src/components/HostRemoveDialog.tsx`.
