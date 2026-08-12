# The host page, redesigned: identity on the left, activity on the right

**Date:** 2026-08-12
**Status:** approved in principle, not started.
**Supersedes nothing.** This is stage 2 of
`docs/superpowers/specs/2026-08-11-visual-rebuild-brief.md`, which named the
host page as the pilot surface and then stalled: the SDD ledger for stage 1
records "Task 2: HELD — user asked to see a design mockup before more of the
rebuild lands." This document is the answer to that, and the thing that
unblocks it.

## What was decided, and by whom

Four options were put in front of the user as rendered mockups, not prose.
The choices below are theirs; the reasoning is recorded so a later reader
knows which parts are settled and which are merely convenient.

1. **Scope: elevated, same identity.** The `#0B0F16`/`#F5B544` palette and the
   Space Grotesk / Inter / JetBrains Mono pairing are untouched. What changes
   is hierarchy, density and width behaviour on this one surface. A new visual
   identity was offered and declined, consistent with the brief.
2. **Layout: two columns — identity rail, then activity.** Chosen over
   "vitals first" (four big numbers, facts folded into a disclosure) and
   "Overview is now" (facts moved wholesale to the Hardware tab). The rail
   hides nothing, which is why it won.
3. **Rail treatment: four labelled groups at one weight.** Chosen over a
   two-tier "Right now / Specification" split. The user's words: the two-tier
   version decides for you what matters. The grouping is the only judgement
   this rail makes.
4. **Machinery: plain Tailwind and the existing tokens.** Not shadcn. See
   §"The machinery question" below.

## The problems this solves

All four were confirmed by the user as real, not hypothetical:

- **The fact strip is flat.** `HostFacts` renders up to 17 key/value rows at
  one uniform weight. Reading "is this box healthy" means scanning all of it.
- **Non-entry nodes look broken.** Charts and the node-shell button render
  only for the entry node, deliberately and for good reasons (the `host:<id>`
  metric series and the shell ticket both belong to the node Proxploy connects
  through). But the page says nothing about it, so a correct decision reads as
  a missing feature.
- **Guests are two visual languages.** Under one "Guests on this host"
  heading, apps render as a 4-up `AppCard` grid and VMs render as a bare
  three-column table.
- **Nothing adapts to width.** Outside the chart row and the app grid, the
  page has no breakpoint. It is one of the 127 of 140 `.tsx` files with none.

## Layout

`NodeDetailPage` keeps its header and tab strip exactly as they are — node
name, `cluster · PVE version`, the node-shell button, the Proxmox web UI link,
the status pill, and the Overview/Hardware tabs as router child routes. None of
that is in scope.

`NodeOverview`'s body becomes:

```
lg and up            base .. lg
┌────────┬─────────┐  ┌──────────────┐
│  rail  │ charts  │  │     rail     │
│ 290px  │  3-up   │  ├──────────────┤
│ sticky ├─────────┤  │ charts, 1-up │
│        │ guests  │  ├──────────────┤
└────────┴─────────┘  │    guests    │
                      └──────────────┘
```

A `grid-cols-[290px_minmax(0,1fr)]` at `lg`, one column below it. The
`minmax(0,1fr)` is not decorative: without it the charts' SVG content sets the
column's min-content width and the grid refuses to shrink below 1440px, which
is the exact bug this stage exists to fix.

## The rail

`NodeIdentityRail` replaces `HostFacts`. `HostFacts` is imported in exactly two
places — `routes/hosts.tsx` and its own test — so this is a replacement, not a
parallel component.

One card. `lg:sticky` beneath the sticky topbar, so identity stays on screen
while a long guest list scrolls. Contents, top to bottom:

**The usage bars, unchanged:** Load, RAM, Storage, Root. Same `UsageBar`, same
gradients, same normalisation of load by thread count. Note that Load and Root
are already `/status`-gated today and stay that way — a node that refuses
`/status` shows two bars, not four.

**Then four labelled groups:**

| Group | Rows |
|---|---|
| Identity | Node, PVE version, Kernel, Architecture, Uptime |
| Processor | Model, Cores, Sockets, Load (1 · 5 · 15), IO delay |
| Memory & storage | Memory, Storage, Root filesystem, Swap |
| Boot | Mode, and `· secure boot` when set |

Rows are label-left / value-right, values in JetBrains Mono. This is
deliberately **not** `KVGrid`, whose label-above-value grid is built for wide
containers; `KVGrid` stays exactly as it is and keeps its six other callers.

**The two-source merge is preserved exactly.** `HostFacts` merges the poller's
snapshot (always present, and the only source anywhere for the deduped
datastore fill) with the node's own `/status` (on demand, refusable by a narrow
token). The snapshot half always renders; the status-only rows — Kernel,
Architecture, Processor, Cores, Sockets, Load, IO delay, Root filesystem, Swap,
Boot — disappear when the node will not answer. That behaviour is load-bearing
and does not change.

**One new rule follows from grouping:** a group whose rows have all vanished is
not rendered at all. Without it, a node that refuses `/status` shows a
"Processor" heading over nothing and a "Boot" heading over nothing — grouping
would have made the degraded case worse than the flat strip it replaced.

**Apps and VMs counts leave the rail.** They move to the guests heading, which
already carries a total. Two places stating the same count is what the
2026-08-11 "one KV strip, not two that repeat each other" commit was about.

## The non-entry node

Where the charts would be, a non-entry node gets an explicit panel:

> Metrics and the node shell are recorded on **pve1**, the node Proxploy
> connects through. → Open pve1

Amber left rule, panel background, and a real link to the entry node's page.
The entry node's name comes from the same `useNodeContext` data the page
already has. This replaces silence, which is the whole point.

## Guests

One `GuestList` component, one row shape for both kinds.

**Unification must go upward, not downward.** `AppCard` currently carries an
icon tile, an update badge, `host · CT id`, a status pill, CPU and RAM bars,
`LifecycleActions` and a Console button. The VM table row carries name, VMID
and a status pill. Flattening both to a bare row — as the first mockup drew
it — would strip working controls off every app on the page. So VMs come up to
parity instead.

Each row: type chip (`app` / `vm`), name in mono, id (`CT 104` / `VM 201`),
status pill, a CPU bar, memory, then `LifecycleActions` and Console.

**The one asymmetry, stated rather than hidden:** `AppRow` has both
`mem_bytes` and `mem_total_bytes`; `VmRow` has only `mem_bytes`. So memory
renders as text — `39.1 GB / 64 GB` for an app, `39.1 GB` for a VM — rather
than as a bar that would need a denominator the VM side does not have. CPU is a
bar for both, because both have `cpu_pct`. Inventing a VM memory total to make
the two rows match would be making up a number.

`LifecycleActions` already accepts `target="vm"` and gates on `vms.lifecycle`,
so the VM side needs no new backend or entitlement work.

**`AppCard` itself is not touched.** It keeps its two other callers: the apps
page (`routes/apps.tsx`) and the cluster overview's 8-app preview
(`routes/hosts.tsx:257`). Only the host page's own guest section changes.

## Responsive behaviour

| Breakpoint | Behaviour |
|---|---|
| base | One column. Rail first, then charts stacked 1-up, then guests. Guest rows wrap: name and chip on the first line, id / status / usage on the second. |
| `sm` (640) | Guest rows resolve to a single line. |
| `lg` (1024) | Two columns; rail becomes 290px and sticky; charts go 3-up. |

The existing `lg:grid-cols-3` on the chart row is kept; the `sm:grid-cols-2
xl:grid-cols-4` app grid disappears with the grid itself.

## The machinery question

Stage 1 of the brief — the `@/` alias, `cn` (clsx + tailwind-merge), the
shadcn token alias layer and a `cva` Button — was built, reviewed clean, and
then undone at the user's request. Its commits (`bac1a8a`, `2fca0a7`) still
exist but sit on no branch.

**Stage 2 does not revive it.** The rail and the guest list are built with
plain Tailwind against the existing tokens, exactly like the rest of the app.
The reasoning:

- Nothing in the codebase uses `cn` or `cva` today. The Radix overlay work —
  a genuine library adoption across 20 surfaces — landed without any of it,
  which is evidence the shadcn layer is not a prerequisite for buying
  behaviour from libraries.
- This redesign's value is hierarchy, grouping and width. None of that needs a
  variant system.
- Reviving stage 1 would re-land a change the user asked to undo and drag the
  36-call-site `size="sm"` button migration back in with it — unrelated
  churn inside a surface redesign.

If a `cva` Button is wanted later it can land on its own, judged on its own
merits. This spec neither blocks nor assumes it.

## Files

| File | Change |
|---|---|
| `frontend/src/components/NodeIdentityRail.tsx` | Create. The rail: bars, four groups, empty-group suppression, the two-source merge moved across from `HostFacts`. |
| `frontend/src/components/GuestList.tsx` | Create. Unified guest rows for apps and VMs. |
| `frontend/src/components/HostFacts.tsx` | Delete once the rail replaces it. |
| `frontend/src/routes/hosts.tsx` | `NodeOverview` gains the two-column grid, the non-entry note, and swaps the AppCard grid + VM table for `GuestList`. |
| `frontend/src/tests/host-facts.test.tsx` | Rewrite as `node-identity-rail.test.tsx`. |
| `frontend/src/tests/hosts.test.tsx` | Update for the guest list and the non-entry note. |
| `docs/06-frontend-spec.md` | Update the host page section in the same commit as the code. |

## Tests

- **The rail:** all four groups render with `/status` present; only Identity
  and Memory & storage survive when `/status` is refused; **no empty group
  heading is ever rendered**; the snapshot-sourced rows survive a refusal.
- **The guest list:** apps and VMs both render in one list; an app shows
  `x / y` memory and a VM shows a bare figure; lifecycle actions appear for
  both; the heading count spans both kinds.
- **The non-entry node:** the note renders with the entry node's name and a
  link; the charts do not render; the entry node still gets charts and no note.
- **Untouched, and a signal if they move:** `page-width.test.ts` (the panel
  width contract) and `overlay-contract.test.ts` (no hand-rolled scrims).

## Verification, and the honest gap in it

The host page is behind authentication. The driver
(`.claude/skills/run-proxploy/driver.mjs`) has no login step, so it renders the
signed-out state for any authenticated route — which means **this stage cannot
be screenshot-verified by the agent as things stand.** The stage-1 plan hit the
same wall and deferred it.

So, before this stage is called done, one of:

1. The user opens a host page in their own browser and looks at it — at full
   width and narrow. This is the default.
2. The driver is taught to log in, as a separate piece of work, not smuggled
   into this one.

The test suite cannot answer a layout question. Neither can a screenshot of a
login form.

## Explicitly not in scope

- The header and tab strip of `NodeDetailPage`.
- The Hardware tab, including its own "Node facts" card (subscription, DNS,
  timezone, node clock) — a different set of facts from the rail's.
- `AppCard`, `KVGrid`, `UsageBar`, `StatusPill`, `MetricChart`.
- Any shadcn dependency, `cva`, `cn`, or the token alias layer.
- Any other surface. Stage 3 rolls out by surface; this is the pilot that
  agrees the direction first.
- MagicUI and motion.
