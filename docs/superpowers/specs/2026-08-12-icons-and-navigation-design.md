# Icons, the brand's place, and a sidebar that gets out of the way

**Date:** 2026-08-12
**Status:** approved in principle, not started.

Three requests, one dependency decision underneath all of them:

1. The Proxploy logo moves out of the sidebar and into the top header, beside
   the search control.
2. Heroicons replace the current iconography **everywhere**, starting with the
   sidebar's ten nav items.
3. The sidebar collapses to those icons, and expands again.

## The dependency, stated plainly

`@heroicons/react` (MIT) becomes the **19th runtime dependency**, and
`@radix-ui/react-tooltip` (MIT) the 20th — see "Tooltips" below.

The 2026-08-11 visual-rebuild brief deliberately deferred an icon library:
"No Radix package, no `motion`, and no icon library **until a component
actually needs one**." That was a deferral with a trigger, not a ban, and this
work is the trigger firing. It is worth being precise about what the codebase
uses today, because it is worse than "no icons":

- **Two** files contain an `<svg>` at all: `Logo.tsx` and `StatRings.tsx`.
- **Seventeen** non-test files carry literal emoji as iconography — `🔎` and
  `🔔` in the topbar, and thirty-odd more across `hosts`, `network`,
  `backups`, `apps`, `vms`, `OnboardingRail`, `HostForm`, `StoreCard`,
  `SnapshotPanel`, `LockVeil`, `ThemeToggle`, `nodeshell`, `onboarding` and
  `Sparkline`.

Emoji are the actual status quo, and they are a poor one: they render as a
different glyph on every OS, they ignore `currentColor` so they cannot follow
the amber/text tokens or the light theme, and they carry no accessible name of
their own. Replacing them is the single highest-value part of this work, and it
is why the answer to "how far does *throughout* reach" is "all of it."

Heroicons is tree-shaken per-icon, so the bundle cost is the icons actually
imported, not the set.

## Decisions

**Style: the 24px outline set, rendered at 18px.** Heroicons ships outline at
24 only; solid at 24, 20 (mini) and 16 (micro). Scaled to 18px the outline
keeps a 1.5px stroke that matches this UI's hairline `--line` borders and sits
correctly against 13.5px nav text. Solid shapes would read heavier than the
labels beside them. The stroked look also matches the two SVGs already here,
`Logo` and `StatRings`.

Every icon is `aria-hidden` and sized by className (`h-[18px] w-[18px]`, or
`h-4 w-4` at 16px in dense rows). There is **no `<Icon>` wrapper component** —
Heroicons components already take `className`, and a wrapper would exist only
to re-export them.

**Icons never carry meaning alone.** Every icon either sits beside a text label
or its control has an `aria-label`. This is why the emoji replacement is not a
straight swap: `<span aria-hidden>🔎</span>` inside a button already labelled
"Search (Ctrl+K)" is fine, but an emoji used *as* the label needs a real name
when it becomes an SVG.

**Tooltips: `@radix-ui/react-tooltip`.** A collapsed rail of ten unlabelled
icons needs names on hover *and* on keyboard focus, dismissible on Escape,
wired through `aria-describedby`. That is precisely the "subtly hard, easy to
get wrong in ways no test catches" category that `docs/06-frontend-spec.md`'s
2026-08-11 amendment already resolved in Radix's favour for dialogs, menus and
tabs. Adding the tooltip primitive follows that decision rather than reopening
it; a `title` attribute would not be keyboard-accessible in the way this needs.

## Phase 1: the chrome

The only phase specified in full here. It is self-contained, ships on its own,
and establishes the conventions every later phase follows.

### The logo moves to the top header

`Brand` (which renders `Logo` at 30px in amber) leaves `SidebarNav`'s header
and enters `Topbar`, at the far left, before the search control — which today
is the leftmost element via `mr-auto`.

This is a fix as well as a preference: the sidebar is `max-[720px]:hidden`, so
on any phone **the product currently shows no logo at all**. Moving it to the
always-visible header gives every viewport a brand mark, and gives the
collapsed rail one less thing to reflow.

The sidebar's vacated header row becomes the collapse toggle.

### The sidebar collapses

| | Expanded | Collapsed |
|---|---|---|
| Width | `236px` (unchanged) | `64px` |
| Nav item | icon + label, existing amber active rule | centred icon, tooltip carries the label |
| Group heading | "Overview" / "Infrastructure" as today | a `border-line-soft` divider rule |
| `HealthFooter` | as today | its compact state |

State persists in `localStorage` under `pp_sidebar`, following
`lib/theme.ts`'s existing shape exactly — a module with a read that defaults
and a write, not a context. Default is expanded.

Below `720px` the sidebar stays hidden entirely, as it is today. Collapse is a
desktop affordance; this phase does not introduce a mobile drawer.

### The ten nav icons

| Nav item | Heroicon (24/outline) |
|---|---|
| Hosts | `ServerStackIcon` |
| Apps | `Squares2X2Icon` |
| App Store | `ShoppingBagIcon` |
| Virtual Machines | `ComputerDesktopIcon` |
| Storage | `CircleStackIcon` |
| Network | `GlobeAltIcon` |
| Backups | `ArchiveBoxIcon` |
| Alerts | `BellAlertIcon` |
| Audit | `ClipboardDocumentListIcon` |
| Settings | `Cog6ToothIcon` |

`NAV` in `SidebarNav.tsx` is exported and read by exactly one other file,
`tests/nav.test.tsx`, which asserts the ten labels in order and the two group
names. So `NAV` gains an `icon` field rather than being replaced, and that test
must keep passing untouched — it encodes doc 01 §0's rule that the nav is fixed
and never reshaped by tier, config or entitlement.

### The topbar's own emoji go too

`🔎` → `MagnifyingGlassIcon`, `🔔` → `BellIcon`. `ThemeToggle`'s two emoji →
`SunIcon` / `MoonIcon`. These three controls are the phase's proof that the
convention works on non-nav chrome.

## Phases 2-4: the rollout

Each gets its own spec and plan when it is reached. Recorded here so the
sequence is not re-derived, and so no phase is quietly dropped:

**Phase 2 — the remaining emoji.** The other fourteen non-test files. Highest
value per icon, because every one of these is currently an OS-dependent glyph
that ignores the theme. Test churn is real: several tests assert on the emoji
character itself.

**Phase 3 — action buttons.** `LifecycleActions` (Start / Stop / Restart),
Install, Uninstall, Console, Migrate, Add host, across the 48 files that render
a `Button`. Highest test churn of any phase — many tests select buttons by
exact accessible name, and an icon inside a button changes that name unless the
icon is `aria-hidden`. That rule is why it is stated in Decisions above.

**Phase 4 — empty states and section headings.** The 11 `EmptyState` call
sites gain a subject-appropriate icon; section headings gain one where it
distinguishes rather than decorates.

## Constraints for every phase

- **No hardcoded colours.** Icons inherit `currentColor`; never a hex.
- **Light theme is real.** An icon that only reads on the dark ink is a bug.
- **`oxlint` baseline is 45 warnings**, not the 44 some older plan text claims.
- **Do not kill ports 8000/5173, and do not run Playwright** — the user runs
  the dev servers.
- **`tests/nav.test.tsx` consumes `NAV`.** Any change to its shape must keep
  that test passing as written.

## Explicitly not in scope

- A mobile navigation drawer. The sidebar's `max-[720px]:hidden` behaviour is
  unchanged.
- Replacing `Logo` or `StatRings`' hand-written SVGs with library icons.
- Animating the collapse beyond a CSS width transition. No `motion`.
- Any change to what the nav links to, or to the two group names.
