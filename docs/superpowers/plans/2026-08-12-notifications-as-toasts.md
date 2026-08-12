# Notifications as Toasts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make toasts the only in-app notification surface — each with its own
close button and a way to clear them all — and delete the activity drawer.

**Architecture:** No new surface is built. `LiveProvider` already turns SSE
`job` and `alert` events into `toast.success`/`toast.error`, so the toast path
exists and works; this plan removes the second surface layered on top of it and
gives the toasts the two controls they lack. `sonner` supplies both natively:
`closeButton` on `<Toaster>`, and `toast.dismiss()` with no argument. A small
`ClearAllToasts` component tracks how many toasts are live and renders a single
control when more than one is.

**Tech Stack:** React 19, TypeScript, Tailwind v4 (CSS-variable tokens, no
config file), TanStack Router, `sonner` 2.0.7, Vitest 4 + Testing Library.

## Why there is no MagicUI here

The request that started this was `npx shadcn@latest add @magicui/animated-list`.
It is deliberately not in this plan, and that is a decision, not an oversight:

- **It is a landing-page device.** Its own registry description says "on your
  landing page". It reveals children one per second on a timer
  (`delay = 1000`) and stops at the initial child count, so a real feed of N
  items takes N seconds to read and live arrivals are never shown.
- **It would duplicate `sonner`,** which is already installed, already mounted
  in `AppShell`, and already receives every job and alert event. Replacing it
  with a hand-rolled stack means losing dismissal, stacking limits, timers and
  the `aria-live` region, and gaining a dependency (`motion`).
- **It needs infrastructure this repo deliberately abandoned.** The component
  imports `cn` from `@/lib/utils`; there is no `cn`, no `@/` alias and no
  `components.json`, because stage 1 of the visual rebuild was undone on
  2026-08-11. `npx shadcn@latest add` would force an `init` that rewrites
  `tokens.css` with shadcn's palette.

If a different toast *feel* is wanted later, `sonner` toasts are styleable
through `toastOptions.className` with no new dependency. That is a separate,
smaller piece of work.

## Global Constraints

- **No new runtime dependencies.** Not `motion`, not MagicUI, not shadcn.
- **No hardcoded colours.** `src/tests/no-hardcoded-colors.test.ts` fails the
  build on a literal hex in a non-allowlisted file. Token classes only.
- **Light theme is real.** `[data-theme="light"]` must keep working.
- **`oxlint` baseline is 45 warnings.**
- **Baseline entering this plan:** 65 test files, 470 passed, 5 skipped;
  `npx tsc -b` clean; backend 984 passed.
- **`notify.inapp` still gates the surface, not the data.** `LiveProvider`
  checks it before showing anything; that check does not move or change.
- **Do not kill ports 8000/5173 and do not run Playwright.** The user runs the
  dev servers out of this checkout.

## File Structure

| File | Responsibility |
|---|---|
| `frontend/src/components/ClearAllToasts.tsx` (create) | Counts live toasts and renders one "Clear all" control when more than one is showing. |
| `frontend/src/components/AppShell.tsx` (modify) | `<Toaster closeButton>`, mounts `ClearAllToasts`, drops `<ActivityDrawer />`. |
| `frontend/src/components/Topbar.tsx` (modify) | The bell keeps its running-job badge but links to `/hosts` instead of toggling a drawer. |
| `frontend/src/components/ActivityDrawer.tsx` (delete) | The surface being removed. |
| `frontend/src/routes/shell.tsx` (modify) | Drops the `drawer`/`job` search params the drawer owned. |
| `frontend/src/components/ui/dialog.tsx` + `ui/overlay.ts` (modify) | Remove the `sheet` variant, which the drawer was the only caller of. |
| `frontend/src/tests/toasts.test.tsx` (create) | Close button present; clear-all appears only with 2+ and dismisses everything. |
| `frontend/src/tests/activity.test.tsx` (modify) | Drops the drawer's cases; keeps `ActivityFeed`'s. |
| `docs/06-frontend-spec.md` (modify) | Activity is toasts plus the feed on Hosts; no drawer. |

---

### Task 1: Toasts gain a close button and a clear-all

**Files:**
- Create: `frontend/src/components/ClearAllToasts.tsx`
- Modify: `frontend/src/components/AppShell.tsx`
- Test: `frontend/src/tests/toasts.test.tsx` (create)

**Interfaces:**
- Consumes: `toast`, `Toaster` from `sonner`.
- Produces: `<ClearAllToasts />`, rendered once beside `<Toaster />`.

**Read this first.** `sonner` does not expose a live toast count, so
`ClearAllToasts` keeps its own. Sonner's `toast()` returns the new toast's id,
and `<Toaster>` does not notify on dismissal — so the count is maintained by
subscribing to sonner's own store rather than by wrapping every call site.
`sonner` exports `useSonner()` which returns `{ toasts }`, the live array.
**Verify that export exists in the installed 2.0.7 before building on it**
(`grep -r "useSonner" node_modules/sonner/dist/index.d.ts`); if it does not,
report NEEDS_CONTEXT rather than wrapping all 68 `toast.*` call sites.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/tests/toasts.test.tsx`:

```tsx
/** Toasts are the only in-app notification surface, so they carry their own
 *  controls: an x on each, and one way to clear the lot. */
import { render, screen, act } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { Toaster, toast } from 'sonner'
import { ClearAllToasts } from '../components/ClearAllToasts'

const wrap = () => render(<><Toaster closeButton /><ClearAllToasts /></>)

afterEach(() => act(() => { toast.dismiss() }))

describe('toast controls', () => {
  it('offers no clear-all when nothing is showing', () => {
    wrap()
    expect(screen.queryByRole('button', { name: /clear all/i })).not.toBeInTheDocument()
  })

  // One toast already has its own x. A "clear all" beside a single item is
  // two controls for one action.
  it('offers no clear-all for a single toast', async () => {
    wrap()
    act(() => { toast('one') })
    expect(await screen.findByText('one')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /clear all/i })).not.toBeInTheDocument()
  })

  it('offers clear-all once a second toast arrives', async () => {
    wrap()
    act(() => { toast('one'); toast('two') })
    expect(await screen.findByRole('button', { name: /clear all/i })).toBeInTheDocument()
  })

  it('clears every toast when pressed', async () => {
    const { getByRole } = wrap()
    act(() => { toast('one'); toast('two') })
    await screen.findByRole('button', { name: /clear all/i })
    act(() => { getByRole('button', { name: /clear all/i }).click() })
    expect(screen.queryByText('one')).not.toBeInTheDocument()
    expect(screen.queryByText('two')).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd frontend && npx vitest run src/tests/toasts.test.tsx
```

Expected: FAIL — `Failed to resolve import "../components/ClearAllToasts"`.

- [ ] **Step 3: Write the component**

Create `frontend/src/components/ClearAllToasts.tsx`:

```tsx
import { toast, useSonner } from 'sonner'

/** One control to dismiss every toast at once.
 *
 *  Only shown from two toasts up: sonner's own close button already handles a
 *  single one, and a "clear all" beside one item is two controls for the same
 *  action.
 *
 *  The count comes from sonner's own store via useSonner() rather than from a
 *  counter of our own, because toasts also disappear on their duration timer
 *  and on the per-toast x — a hand-kept tally would drift out of sync with
 *  what is actually on screen. */
export function ClearAllToasts() {
  const { toasts } = useSonner()
  if (toasts.length < 2) return null
  return (
    <div className="fixed bottom-2 right-4 z-[9999]">
      <button type="button" onClick={() => toast.dismiss()}
        className="rounded-ctl border border-line bg-panel-2 px-2.5 py-1 text-[11px]
                   text-text-2 shadow-lg transition hover:bg-elev hover:text-text">
        Clear all ({toasts.length})
      </button>
    </div>
  )
}
```

- [ ] **Step 4: Run the test**

```bash
cd frontend && npx vitest run src/tests/toasts.test.tsx
```

Expected: PASS, 4 tests.

- [ ] **Step 5: Mount it, and give every toast its x**

In `frontend/src/components/AppShell.tsx`, add `closeButton` to the existing
`<Toaster>` and mount `ClearAllToasts` beside it:

```tsx
      <Toaster
        position="bottom-right"
        duration={2600}
        closeButton
        toastOptions={{
          className: 'rounded-ctl border border-line bg-panel-2 text-text text-[13px]',
        }}
      />
      <ClearAllToasts />
```

- [ ] **Step 6: Verify**

```bash
cd frontend && npm test && npx tsc -b && npx oxlint
```

Expected: green, oxlint 45.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/ClearAllToasts.tsx frontend/src/components/AppShell.tsx \
        frontend/src/tests/toasts.test.tsx
git commit -m "feat(notify): every toast gets an x, and a way to clear the lot"
```

---

### Task 2: The activity drawer is removed

**Files:**
- Delete: `frontend/src/components/ActivityDrawer.tsx`
- Modify: `frontend/src/components/AppShell.tsx`, `frontend/src/components/Topbar.tsx`, `frontend/src/routes/shell.tsx`
- Modify: `frontend/src/components/ui/dialog.tsx`, `frontend/src/components/ui/overlay.ts`
- Modify: `frontend/src/tests/activity.test.tsx`, and any test asserting on the drawer
- Modify: `docs/06-frontend-spec.md`

**Interfaces:**
- Consumes: Task 1's toasts, which are now the only notification surface.
- Produces: nothing. This task is a removal.

**Read this first.** `ActivityFeed` is **not** being deleted — it is also
rendered on the Hosts page (`routes/hosts.tsx:302`), which is what keeps a
history of activity reachable after the drawer goes. Only the sheet wrapper is
removed. Check `grep -rn "ActivityFeed"` before touching anything.

- [ ] **Step 1: Point the bell at the feed that still exists**

In `frontend/src/components/Topbar.tsx`, the bell currently calls
`drawer.toggle`. It keeps its badge and its `aria-label` but becomes a link:

```tsx
        <Link
          to={'/hosts' as never}
          aria-label="Activity"
          className="relative grid h-8 w-8 place-items-center rounded-tile bg-panel-2 text-text-2 hover:bg-elev"
        >
          <BellIcon aria-hidden className="h-[18px] w-[18px]" />
          {count > 0 && (
            <span className="absolute -right-1 -top-1 rounded-full bg-amber px-1 font-mono text-[9px] text-amber-ink">
              {count}
            </span>
          )}
        </Link>
```

Note the badge's text colour: the existing markup hardcodes `text-[#20160a]`,
which the colour guard does not catch because it only scans `style=`/`stroke=`/
`fill=`. If `--amber-ink` is not a token in `tokens.css`, leave the literal
exactly as it is and report it as a concern — do **not** invent a token in this
task.

Drop the now-unused `useActivityDrawer` import.

- [ ] **Step 2: Unmount the drawer and delete it**

In `frontend/src/components/AppShell.tsx`, remove `<ActivityDrawer />` and its
import. Then:

```bash
cd frontend && rm src/components/ActivityDrawer.tsx
```

- [ ] **Step 3: Drop the search params the drawer owned**

In `frontend/src/routes/shell.tsx`, `validateSearch` declares `drawer` and
`job` solely for the drawer. Remove both, and the comment block explaining
them, leaving `validateSearch` off entirely if nothing else uses it.

**Check first:** `grep -rn "search.*drawer\|search.*job\b" src` — if anything
else reads those params, stop and report NEEDS_CONTEXT.

The comment there warns that an inferred type with required-but-possibly-undefined
keys would make `search` mandatory on every `<Link to>` in the app. Removing
`validateSearch` entirely avoids that problem rather than reintroducing it.

- [ ] **Step 4: Remove the sheet variant**

`variant="sheet"` had exactly one caller, the drawer. In
`frontend/src/components/ui/dialog.tsx` and `ui/overlay.ts`, remove the `sheet`
variant and `sheetPanelClass`/`sheetOverlayClass`.

**Check first:** `grep -rn "sheet" src --include="*.tsx" --include="*.ts"`. If
anything else references it, leave it in place and say so — dead code is
cheaper than a broken dialog.

`src/tests/overlay-contract.test.ts` guards that no file grows its own scrim.
It must keep passing untouched.

- [ ] **Step 5: Update the tests**

`src/tests/activity.test.tsx` covers both the drawer and `ActivityFeed`. Remove
the drawer's cases; keep every `ActivityFeed` case. Then run the whole suite and
fix any other test that asserted on the drawer, the bell's toggle behaviour, or
the `drawer`/`job` search params — naming each one in your report.

- [ ] **Step 6: Verify**

```bash
cd frontend && npm test && npx tsc -b && npx oxlint
```

Expected: green, oxlint 45. Test count drops by the drawer's cases and rises by
Task 1's four.

- [ ] **Step 7: Update the frontend spec**

In `docs/06-frontend-spec.md`, replace the activity-drawer description: in-app
notification is toasts (each with a close button, plus a clear-all above two),
and the activity history lives in `ActivityFeed` on the Hosts page. `notify.inapp`
still gates the surface rather than the data. Remove the sheet variant from the
component inventory.

- [ ] **Step 8: Commit**

```bash
git add -A frontend/src docs/06-frontend-spec.md
git commit -m "refactor(notify): the drawer goes; toasts are the surface"
```

---

## Done when

- `npm test`, `npx tsc -b`, `npx oxlint` green, warnings still 45.
- Every toast has a close button; a clear-all appears at two or more and
  dismisses all of them.
- `ActivityDrawer.tsx` is gone and nothing imports it; the `sheet` variant is
  gone or explicitly justified.
- The bell keeps its running-job count and reaches the activity feed.
- `overlay-contract.test.ts` passes untouched.
- **The user has looked at it.** Toast behaviour is timing- and
  pointer-dependent; the suite cannot see stacking, hover-pause or the x.

## Explicitly not in this plan

- MagicUI, `motion`, `cn`, the `@/` alias, `components.json`, or any shadcn
  init. See "Why there is no MagicUI here".
- Restyling toasts beyond adding the close button.
- Any change to `ActivityFeed` itself, or to the SSE events feeding it.
- A notification history or "mark as read" model. Toasts are ephemeral by
  design and the feed on Hosts is the record.
