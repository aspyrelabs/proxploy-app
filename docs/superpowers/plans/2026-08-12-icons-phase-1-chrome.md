# Icons Phase 1: the chrome

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put a real icon on every sidebar nav item and on the topbar's chrome,
move the Proxploy logo out of the sidebar into the top header, and let the
sidebar collapse to a 64px icon rail that remembers the choice.

**Architecture:** `NAV` gains an `icon` field holding a Heroicons component
reference, so the nav stays one declarative list. Collapse state lives in
`lib/sidebar.ts`, a two-function module copied in shape from the existing
`lib/theme.ts` — a read that defaults and a write that persists — not a
context. Tooltips come from Radix, matching the overlay decision this codebase
already made.

**Tech Stack:** React 19, TypeScript, Tailwind v4 (`@theme inline`, no config
file), TanStack Router, Vitest 4 + Testing Library, `@heroicons/react`,
`@radix-ui/react-tooltip`.

## Global Constraints

From `docs/superpowers/specs/2026-08-12-icons-and-navigation-design.md`:

- **Two new runtime dependencies, both MIT, and no others.**
  `@heroicons/react` and `@radix-ui/react-tooltip`. No `motion`, no icon
  wrapper library, no CSS-in-JS.
- **The 24px outline set, rendered at 18px.** Import from
  `@heroicons/react/24/outline`. Size with `className="h-[18px] w-[18px]"`.
  Never the solid or mini sets in this phase.
- **Every icon is `aria-hidden` and sized by className.** Heroicons components
  accept both. An icon must never be the only carrier of meaning: it sits
  beside a text label, or its control has an `aria-label`.
- **No `<Icon>` wrapper component.** Heroicons already takes `className`; a
  wrapper would exist only to re-export.
- **No hardcoded colours.** Icons inherit `currentColor`. `src/tests/no-hardcoded-colors.test.ts` fails the build on a literal hex in a non-allowlisted file.
- **Light theme is real.** `[data-theme="light"]` must keep working.
- **`oxlint` baseline is 45 warnings.** Not the 44 that older plan text claims.
- **Baseline entering this plan:** `npm test` → 62 files, 451 passed, 5 skipped.
  `npx tsc -b` clean.
- **`src/tests/nav.test.tsx` must keep passing untouched.** It asserts the ten
  labels in order and the two group names, encoding doc 01 §0's rule that the
  nav is fixed and never reshaped by tier, config or entitlement. Adding a
  field to `NAV` is fine; changing its labels, order or grouping is not.
- **The sidebar stays `max-[720px]:hidden`.** No mobile drawer in this phase.
- **Do not kill ports 8000/5173 and do not run Playwright.** The user runs the
  dev servers out of this checkout. `npm test`, `npx tsc -b`, `npx oxlint` are
  safe.

---

## File Structure

| File | Responsibility |
|---|---|
| `frontend/package.json` (modify, via `npm install`) | The two new dependencies. |
| `frontend/src/components/SidebarNav.tsx` (modify) | `NAV` gains `icon`; the aside gains a collapsed width, a toggle, and tooltips; loses `Brand`. |
| `frontend/src/lib/sidebar.ts` (create) | Collapse state read/write against `localStorage`, shaped like `lib/theme.ts`. |
| `frontend/src/components/Topbar.tsx` (modify) | Gains `Brand` at far left; `🔎`/`🔔` become Heroicons. |
| `frontend/src/components/ThemeToggle.tsx` (modify) | `☀︎`/`☾` become `SunIcon`/`MoonIcon`. |
| `frontend/src/tests/sidebar-nav.test.tsx` (create) | Icons render, collapse toggles, choice persists, tooltips name the items. |
| `frontend/src/tests/topbar-brand.test.tsx` (create) | The logo is in the header, and the icon swap kept every accessible name. |
| `docs/06-frontend-spec.md` (modify) | The nav, topbar and collapse behaviour as shipped. |

---

### Task 1: The dependencies and the ten nav icons

**Files:**
- Modify: `frontend/package.json` (via `npm install`)
- Modify: `frontend/src/components/SidebarNav.tsx`
- Test: `frontend/src/tests/sidebar-nav.test.tsx` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `NAV` with an `icon` field on every item, typed as a Heroicons
  component (`(props: React.ComponentProps<'svg'>) => React.ReactElement`).
  Task 3 renders the same icons in the collapsed rail.

- [ ] **Step 1: Install the dependencies**

```bash
cd frontend && npm install @heroicons/react @radix-ui/react-tooltip
```

Both are installed now, in one reviewable commit, even though the tooltip is
not used until Task 3 — the dependency decision is one decision.

- [ ] **Step 2: Write the failing test**

Create `frontend/src/tests/sidebar-nav.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

// The nav renders TanStack Router <Link>s. This file only cares about the
// nav's own markup, so Link becomes a plain anchor carrying its target.
vi.mock('@tanstack/react-router', () => ({
  Link: ({ to, children, className }: {
    to: string; children: React.ReactNode; className?: string
  }) => <a href={to} data-to={to} className={className}>{children}</a>,
}))

// HealthFooter runs its own queries and is not what this file tests.
vi.mock('../components/HealthFooter', () => ({ HealthFooter: () => null }))

import { NAV, SidebarNav } from '../components/SidebarNav'

describe('SidebarNav icons', () => {
  it('gives every one of the ten nav items an icon', () => {
    const items = NAV.flatMap((g) => g.items)
    expect(items).toHaveLength(10)
    for (const item of items) {
      expect(item.icon, `${item.label} has no icon`).toBeTypeOf('function')
    }
  })

  it('renders an svg beside each label, hidden from the accessibility tree', () => {
    render(<SidebarNav />)
    // Every nav link holds exactly one svg, and that svg is aria-hidden: the
    // label beside it is the accessible name, so an icon announcing itself
    // would make every item read twice.
    for (const item of NAV.flatMap((g) => g.items)) {
      const link = screen.getByText(item.label).closest('a')
      expect(link, `${item.label} link missing`).not.toBeNull()
      const svgs = link!.querySelectorAll('svg')
      expect(svgs).toHaveLength(1)
      expect(svgs[0].getAttribute('aria-hidden')).toBe('true')
    }
  })

  it('keeps the label text, so the nav is still readable without icons', () => {
    render(<SidebarNav />)
    expect(screen.getByText('Virtual Machines')).toBeInTheDocument()
    expect(screen.getByText('App Store')).toBeInTheDocument()
  })
})
```

- [ ] **Step 3: Run it and watch it fail**

```bash
cd frontend && npx vitest run src/tests/sidebar-nav.test.tsx
```

Expected: FAIL — `item.icon` is undefined, so the first test fails on
"Hosts has no icon".

- [ ] **Step 4: Add the icons to `NAV`**

In `frontend/src/components/SidebarNav.tsx`, add the import and give every item
its icon. Keep `as const`, keep the labels, the order and the two groups
exactly as they are — `nav.test.tsx` asserts all three.

```tsx
import {
  ArchiveBoxIcon, BellAlertIcon, CircleStackIcon, ClipboardDocumentListIcon,
  Cog6ToothIcon, ComputerDesktopIcon, GlobeAltIcon, ServerStackIcon,
  ShoppingBagIcon, Squares2X2Icon,
} from '@heroicons/react/24/outline'

export const NAV = [
  { label: 'Overview', items: [
    { label: 'Hosts', to: '/hosts', icon: ServerStackIcon },
    { label: 'Apps', to: '/apps', icon: Squares2X2Icon },
    { label: 'App Store', to: '/store', icon: ShoppingBagIcon },
    { label: 'Virtual Machines', to: '/vms', icon: ComputerDesktopIcon },
  ]},
  { label: 'Infrastructure', items: [
    { label: 'Storage', to: '/storage', icon: CircleStackIcon },
    { label: 'Network', to: '/network', icon: GlobeAltIcon },
    { label: 'Backups', to: '/backups', icon: ArchiveBoxIcon },
    { label: 'Alerts', to: '/alerts', icon: BellAlertIcon },
    { label: 'Audit', to: '/audit', icon: ClipboardDocumentListIcon },
    { label: 'Settings', to: '/settings', icon: Cog6ToothIcon },
  ]},
] as const
```

- [ ] **Step 5: Render the icon in each link**

Still in `SidebarNav.tsx`, the nav item's `<Link>` body becomes an icon plus a
label. The existing `className` and `activeProps` are unchanged except that the
link becomes a flex row:

```tsx
              <Link key={item.to} to={item.to as never}
                className="relative flex items-center gap-3 rounded-tile px-3 py-2 text-[13.5px] text-text-2 hover:bg-panel-2 hover:text-text"
                activeProps={{ className: 'bg-panel-2 !text-text before:absolute before:left-0 before:top-1.5 before:bottom-1.5 before:w-[3px] before:rounded before:bg-amber' }}>
                <item.icon aria-hidden className="h-[18px] w-[18px] shrink-0" />
                {item.label}
              </Link>
```

`shrink-0` matters: without it the icon squashes when a long label like
"Virtual Machines" competes for the 236px width.

- [ ] **Step 6: Run the tests**

```bash
cd frontend && npx vitest run src/tests/sidebar-nav.test.tsx src/tests/nav.test.tsx
```

Expected: PASS — 3 new tests, and `nav.test.tsx`'s 2 still passing untouched.

- [ ] **Step 7: Verify the suite, types and lint**

```bash
cd frontend && npm test && npx tsc -b && npx oxlint
```

Expected: 63 files, 454 passed, 5 skipped; `tsc` clean; oxlint 45 warnings.

- [ ] **Step 8: Commit**

```bash
git add frontend/package.json frontend/package-lock.json \
        frontend/src/components/SidebarNav.tsx frontend/src/tests/sidebar-nav.test.tsx
git commit -m "feat(nav): ten nav items stop being text-only"
```

---

### Task 2: The logo moves to the header, and the topbar's emoji go

**Files:**
- Modify: `frontend/src/components/SidebarNav.tsx` (remove `Brand`)
- Modify: `frontend/src/components/Topbar.tsx`
- Modify: `frontend/src/components/ThemeToggle.tsx`
- Test: `frontend/src/tests/topbar-brand.test.tsx` (create)

**Interfaces:**
- Consumes: `@heroicons/react` (Task 1 installed it).
- Produces: nothing later tasks depend on. Task 3 replaces the sidebar header
  row this task empties.

**Read this before starting.** The sidebar is `max-[720px]:hidden`, so today
**the product shows no logo at all on a phone**. Moving `Brand` into the
always-visible header is a fix, not only a preference. Say so in the commit.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/tests/topbar-brand.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../api/client', () => ({
  api: vi.fn((path: string) =>
    path === '/entitlements'
      ? Promise.resolve({ tier: 'pro', features: { 'notify.inapp': true } })
      : Promise.resolve([])),
  ApiError: class extends Error {},
}))
vi.mock('../components/AccountMenu', () => ({ AccountMenu: () => null }))
vi.mock('../components/TierPill', () => ({ TierPill: () => null }))
vi.mock('../components/ActivityDrawer', () => ({
  useActivityDrawer: () => ({ toggle: vi.fn() }),
}))
vi.mock('../components/CommandPalette', () => ({ openCommandPalette: vi.fn() }))

import { Topbar } from '../components/Topbar'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><Topbar /></QueryClientProvider>)
}

describe('Topbar', () => {
  // The sidebar is max-[720px]:hidden, so before this the product showed no
  // logo at all on a phone. The header is the one chrome that is always there.
  it('carries the brand mark', () => {
    const { container } = wrap()
    expect(container.querySelector('header svg')).not.toBeNull()
  })

  // The emoji became SVGs; the accessible names must not have moved with them.
  it('keeps the search control named and reachable', () => {
    wrap()
    expect(screen.getByRole('button', { name: /search/i })).toBeInTheDocument()
  })

  it('keeps the activity control named', async () => {
    wrap()
    expect(await screen.findByRole('button', { name: 'Activity' })).toBeInTheDocument()
  })

  it('has no emoji left in it', () => {
    const { container } = wrap()
    const header = container.querySelector('header')!
    expect(header.textContent ?? '').not.toMatch(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u)
  })
})
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd frontend && npx vitest run src/tests/topbar-brand.test.tsx
```

Expected: FAIL — no `svg` inside `header`, and the emoji assertion fails on
`🔎`.

- [ ] **Step 3: Put `Brand` in the header and swap the two emoji**

In `frontend/src/components/Topbar.tsx`, add the imports:

```tsx
import { BellIcon, MagnifyingGlassIcon } from '@heroicons/react/24/outline'
import { Brand } from './LoginForm'
```

Add `Brand` as the header's first child, before the search button, and give it
a right margin so it does not crowd the control beside it:

```tsx
      <Brand />
```

Replace `<span aria-hidden>🔎</span>` with:

```tsx
        <MagnifyingGlassIcon aria-hidden className="h-[18px] w-[18px]" />
```

Replace `<span aria-hidden>🔔</span>` with:

```tsx
          <BellIcon aria-hidden className="h-[18px] w-[18px]" />
```

The search button already keeps `mr-auto`, which is what pushes everything
after it to the right; `Brand` sits before it and needs no `mr-auto` of its
own. Keep every existing `aria-label` exactly as it is — they are the
accessible names the test asserts, and the icons are `aria-hidden` precisely so
those labels stay the whole name.

**Use `Logo`, not `Brand`.** `Brand` is `<Logo className="h-[30px] w-auto
text-amber" />`, and 30px is taller than the topbar's `h-8` controls. Do not
edit `Brand` — `LoginForm` renders it at 30px on the login card and that is
correct there. Import `Logo` directly and size it for this bar:

```tsx
import { Logo } from './Logo'
```

```tsx
      <Logo className="h-6 w-auto shrink-0 text-amber" />
```

So the header's first child is that `Logo`, and the `Brand` import mentioned
above is not needed in `Topbar` at all.

- [ ] **Step 4: Take the logo out of the sidebar**

In `frontend/src/components/SidebarNav.tsx`, delete the header row:

```tsx
      <div className="px-4 py-4"><Brand /></div>
```

and drop the now-unused `Brand` import. Task 3 fills this space with the
collapse toggle; leaving it empty between tasks is expected and fine.

- [ ] **Step 5: Swap `ThemeToggle`'s two emoji**

In `frontend/src/components/ThemeToggle.tsx`, import the icons and replace the
label expression. The button keeps its `aria-label` and `title`:

```tsx
import { MoonIcon, SunIcon } from '@heroicons/react/24/outline'
```

```tsx
      {theme === 'dark'
        ? <><SunIcon aria-hidden className="h-4 w-4" /> Light</>
        : <><MoonIcon aria-hidden className="h-4 w-4" /> Dark</>}
```

and add `inline-flex items-center gap-1.5` to the button's existing className so
the icon and word sit on one line.

- [ ] **Step 6: Run the tests**

```bash
cd frontend && npx vitest run src/tests/topbar-brand.test.tsx
```

Expected: PASS, 4 tests.

- [ ] **Step 7: Verify the suite, types and lint**

```bash
cd frontend && npm test && npx tsc -b && npx oxlint
```

Expected: 64 files, 458 passed, 5 skipped; `tsc` clean; oxlint 45.

If a test elsewhere asserted on `'☀︎ Light'`, `'☾ Dark'`, `🔎` or `🔔`, it is
asserting on something deliberately removed. Update it to the new accessible
name rather than restoring the emoji, and say which tests you touched.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/Topbar.tsx frontend/src/components/SidebarNav.tsx \
        frontend/src/components/ThemeToggle.tsx frontend/src/tests/topbar-brand.test.tsx
git commit -m "feat(chrome): the logo moves to the one bar every viewport has"
```

---

### Task 3: The sidebar collapses, and remembers

**Files:**
- Create: `frontend/src/lib/sidebar.ts`
- Modify: `frontend/src/components/SidebarNav.tsx`
- Modify: `frontend/src/tests/sidebar-nav.test.tsx`
- Modify: `docs/06-frontend-spec.md`

**Interfaces:**
- Consumes: `NAV`'s `icon` field (Task 1), the emptied sidebar header row
  (Task 2), `@radix-ui/react-tooltip` (Task 1 installed it).
- Produces: `readSidebarCollapsed(): boolean` and
  `setSidebarCollapsed(v: boolean): void` from `src/lib/sidebar.ts`.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/tests/sidebar-nav.test.tsx`. Keep the existing mocks at
the top of the file, and extend its imports with exactly these two lines:

```tsx
import userEvent from '@testing-library/user-event'
```

and add `beforeEach` to the existing `vitest` import, so it reads
`import { beforeEach, describe, expect, it, vi } from 'vitest'`.

```tsx
describe('SidebarNav collapse', () => {
  beforeEach(() => localStorage.clear())

  it('starts expanded, showing labels', () => {
    render(<SidebarNav />)
    expect(screen.getByText('Hosts')).toBeInTheDocument()
    expect(screen.getByText('Overview')).toBeInTheDocument()
  })

  it('collapses to icons when the toggle is pressed', async () => {
    const user = userEvent.setup()
    render(<SidebarNav />)
    await user.click(screen.getByRole('button', { name: /collapse sidebar/i }))
    // The labels go; the links, and their icons, stay.
    expect(screen.queryByText('Hosts')).not.toBeInTheDocument()
    expect(screen.getAllByRole('link')).toHaveLength(10)
    // and the group headings become a rule rather than text
    expect(screen.queryByText('Infrastructure')).not.toBeInTheDocument()
  })

  it('names every icon for assistive tech once the label is gone', async () => {
    const user = userEvent.setup()
    render(<SidebarNav />)
    await user.click(screen.getByRole('button', { name: /collapse sidebar/i }))
    // With no visible text, the link itself must carry the name.
    expect(screen.getByRole('link', { name: 'Virtual Machines' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'App Store' })).toBeInTheDocument()
  })

  it('remembers the choice across a remount', async () => {
    const user = userEvent.setup()
    const { unmount } = render(<SidebarNav />)
    await user.click(screen.getByRole('button', { name: /collapse sidebar/i }))
    unmount()
    render(<SidebarNav />)
    expect(screen.queryByText('Hosts')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /expand sidebar/i })).toBeInTheDocument()
  })

  it('expands again', async () => {
    const user = userEvent.setup()
    render(<SidebarNav />)
    await user.click(screen.getByRole('button', { name: /collapse sidebar/i }))
    await user.click(screen.getByRole('button', { name: /expand sidebar/i }))
    expect(screen.getByText('Hosts')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd frontend && npx vitest run src/tests/sidebar-nav.test.tsx
```

Expected: FAIL — no button named "Collapse sidebar".

- [ ] **Step 3: Write the persistence module**

Create `frontend/src/lib/sidebar.ts`. Shaped like `lib/theme.ts`: a read that
defaults and a write that persists, no context, no hook.

```ts
const STORAGE_KEY = 'pp_sidebar'

/** Whether the sidebar is collapsed to its icon rail. Defaults to expanded:
 *  a first-time user should see the labels before being asked to recognise
 *  ten icons cold. */
export function readSidebarCollapsed(): boolean {
  return localStorage.getItem(STORAGE_KEY) === 'collapsed'
}

export function setSidebarCollapsed(collapsed: boolean): void {
  localStorage.setItem(STORAGE_KEY, collapsed ? 'collapsed' : 'expanded')
}
```

- [ ] **Step 4: Make the sidebar collapsible**

Rewrite `SidebarNav`'s body. The `NAV` constant above it is untouched.

```tsx
import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import * as Tooltip from '@radix-ui/react-tooltip'
import { ChevronDoubleLeftIcon, ChevronDoubleRightIcon } from '@heroicons/react/24/outline'
import { HealthFooter } from './HealthFooter'
import { readSidebarCollapsed, setSidebarCollapsed } from '../lib/sidebar'

export function SidebarNav() {
  const [collapsed, setCollapsed] = useState(readSidebarCollapsed)
  const toggle = () => {
    setCollapsed((c) => {
      setSidebarCollapsed(!c)
      return !c
    })
  }
  return (
    <Tooltip.Provider delayDuration={200}>
      <aside className={`sticky top-0 flex h-screen shrink-0 flex-col border-r border-line-soft bg-panel/60 transition-[width] duration-200 motion-reduce:transition-none max-[720px]:hidden ${collapsed ? 'w-16' : 'w-[236px]'}`}>
        <div className={`flex px-2 py-3 ${collapsed ? 'justify-center' : 'justify-end'}`}>
          <button type="button" onClick={toggle}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            className="grid h-8 w-8 place-items-center rounded-tile text-text-3 hover:bg-panel-2 hover:text-text">
            {collapsed
              ? <ChevronDoubleRightIcon aria-hidden className="h-[18px] w-[18px]" />
              : <ChevronDoubleLeftIcon aria-hidden className="h-[18px] w-[18px]" />}
          </button>
        </div>
        <nav className="flex-1 overflow-y-auto px-2">
          {NAV.map((group) => (
            <div key={group.label} className="mb-4">
              {collapsed
                // The heading's job is to separate the two groups. With no
                // room for the word, a rule does that job and the word does
                // not fit; keeping it truncated would be worse than a line.
                ? <div className="mx-2 mb-2 border-t border-line-soft" />
                : <div className="px-2 pb-1 text-[10.5px] font-semibold uppercase tracking-[.08em] text-text-3">{group.label}</div>}
              {group.items.map((item) => (
                <NavItem key={item.to} item={item} collapsed={collapsed} />
              ))}
            </div>
          ))}
        </nav>
        <HealthFooter />
      </aside>
    </Tooltip.Provider>
  )
}

function NavItem({ item, collapsed }: {
  item: (typeof NAV)[number]['items'][number]
  collapsed: boolean
}) {
  const link = (
    // cast: circular router-tree imports across route files defeat
    // full inference of the nav's `to` union in this TS/router version
    <Link to={item.to as never}
      // aria-label only when collapsed: with the text visible it would
      // override the label the user can actually read, and the two must not
      // drift apart.
      aria-label={collapsed ? item.label : undefined}
      className={`relative flex items-center gap-3 rounded-tile py-2 text-[13.5px] text-text-2 hover:bg-panel-2 hover:text-text ${collapsed ? 'justify-center px-0' : 'px-3'}`}
      activeProps={{ className: 'bg-panel-2 !text-text before:absolute before:left-0 before:top-1.5 before:bottom-1.5 before:w-[3px] before:rounded before:bg-amber' }}>
      <item.icon aria-hidden className="h-[18px] w-[18px] shrink-0" />
      {!collapsed && item.label}
    </Link>
  )
  if (!collapsed) return link
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>{link}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content side="right" sideOffset={6}
          className="z-50 rounded-tile border border-line bg-elev px-2 py-1 text-[12px] text-text shadow-lg">
          {item.label}
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  )
}
```

- [ ] **Step 5: Run the tests**

```bash
cd frontend && npx vitest run src/tests/sidebar-nav.test.tsx
```

Expected: PASS — the 3 icon tests and the 5 collapse tests.

If the "names every icon" test fails because Radix's `Tooltip.Trigger asChild`
changed the link's accessible name, that is a real finding, not a test to
loosen: the `aria-label` on the `Link` must survive being a tooltip trigger.
Report it rather than deleting the assertion.

- [ ] **Step 6: Verify the suite, types and lint**

```bash
cd frontend && npm test && npx tsc -b && npx oxlint
```

Expected: 64 files, 463 passed, 5 skipped; `tsc` clean; oxlint 45.

- [ ] **Step 7: Look at it**

The sidebar is behind auth, so the driver cannot reach it and no screenshot can
prove this one. State that plainly in your report rather than implying visual
verification happened.

- [ ] **Step 8: Update the frontend spec**

In `docs/06-frontend-spec.md`, update the navigation section: the ten items now
carry Heroicons (24/outline at 18px), the sidebar collapses to a 64px rail with
Radix tooltips carrying the labels, the choice persists in `pp_sidebar`, group
headings become a rule when collapsed, and the brand mark now lives in the
topbar — noting that the sidebar's `max-[720px]:hidden` meant no logo showed on
a phone before. Match the surrounding sections' voice.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/lib/sidebar.ts frontend/src/components/SidebarNav.tsx \
        frontend/src/tests/sidebar-nav.test.tsx docs/06-frontend-spec.md
git commit -m "feat(nav): the sidebar collapses to its icons, and remembers"
```

---

## Done when

- `npm test`, `npx tsc -b` and `npx oxlint` are green, lint still at 45.
- All ten nav items render an `aria-hidden` icon beside their label.
- The logo is in the topbar and gone from the sidebar; no emoji remain in
  `Topbar` or `ThemeToggle`.
- The sidebar collapses to 64px, every collapsed link is still named for
  assistive tech, and the choice survives a reload.
- `nav.test.tsx` passes untouched.
- **The user has looked at it.** Nothing here is screenshot-verifiable by an
  agent: the sidebar is behind authentication and the driver has no login step.

## Explicitly not in this phase

- The other fourteen files carrying emoji (phase 2).
- Action-button icons (phase 3) and empty-state icons (phase 4).
- A mobile navigation drawer; `max-[720px]:hidden` is unchanged.
- Replacing `Logo` or `StatRings`' hand-written SVGs.
- Any animation beyond the CSS width transition.
