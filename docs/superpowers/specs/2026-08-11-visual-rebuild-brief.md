# Visual rebuild: keep the identity, change the machinery

**Date:** 2026-08-11
**Status:** approved in principle, not started. Written before a Claude restart
so the decisions survive it.

## The decision

Rebuild the frontend on **shadcn/ui** primitives, adding **MagicUI** where it
earns its place, **keeping the existing visual identity**. Explicitly NOT a new
palette or type pairing.

Rejected alternatives, and why:

- *New visual identity.* The current system is coherent and deliberate:
  `#0B0F16` ink, `#F5B544` amber, Space Grotesk display / Inter UI / JetBrains
  Mono for data, from `proxploy-prototype.html` (doc 09's design source of
  truth) and specified per-component in doc 06. Replacing it with shadcn's
  defaults would land somewhere *more* generic, not less.
- *Polish only, no library.* Would fix responsiveness but leaves 60 hand-rolled
  components with no shared primitives, no focus management, and no consistent
  a11y story.

## Why now

Only **13 of 75** components and routes use any responsive breakpoint. Several
dialogs carry fixed widths (`w-[520px]`, `w-[560px]`) — most pair them with
`max-w-[92vw]`, but not all. That is the concrete, measurable gap.

## Constraints the rebuild must respect

1. **`src/tests/no-hardcoded-colors.test.ts`** fails the build on a literal hex
   in a non-allowlisted file. Every shadcn component must be themed through
   tokens, not the hex values shadcn ships with.
2. **417 frontend tests** assert on current markup and copy. They are the
   safety net for a rebuild of this size; expect churn, and treat a test that
   needs changing as a question ("did the meaning change?") rather than a
   chore.
3. **`docs/06-frontend-spec.md`** specifies the component set. It has already
   been corrected twice today for drifting from the code. Update it in the same
   commit as any component it describes.
4. **Light theme is real.** `e2e/light-theme.spec.ts` asserts no dark-only
   literals across every page.
5. **Dependency weight.** shadcn brings Radix + `cva` + `clsx` +
   `tailwind-merge`; MagicUI brings `motion`. Roughly six additions to a
   twelve-dependency runtime, in self-hosted software. Add them once,
   deliberately, and do not accumulate more per component.

## The token mapping is the crux

shadcn assumes `--background`, `--foreground`, `--primary`, `--muted`,
`--border`, `--ring`. Proxploy has `--ink`, `--panel`, `--panel-2`, `--elev`,
`--line`, `--line-soft`, `--text`, `--text-2`, `--text-3`, `--amber`, plus
`--green/--red/--blue/--violet/--cyan` and their `-dim` variants, exposed to
Tailwind through `@theme inline` in `src/styles/tokens.css`.

Map shadcn's names ONTO the existing ones in one place, so there is a single
palette with two vocabularies rather than two palettes:

| shadcn | Proxploy |
|---|---|
| `--background` | `--ink` |
| `--card`, `--popover` | `--panel` |
| `--muted` | `--panel-2` |
| `--accent` | `--elev` |
| `--foreground` | `--text` |
| `--muted-foreground` | `--text-3` |
| `--border`, `--input` | `--line` |
| `--primary`, `--ring` | `--amber` |
| `--destructive` | `--red` |

Both light and dark blocks already exist in `tokens.css`; the mapping goes in
both.

## Staging

Each stage ships and is reviewable on its own.

1. **Infrastructure, no visual change.** Add the dependencies, `components.json`,
   the `cn` helper, and the token mapping. Prove it by rendering one shadcn
   primitive that looks identical to what it replaces. The existing
   hand-rolled `src/components/ui/button.tsx` is the natural first swap — its
   variants (`primary`/`ghost`/`danger`/`go`) become `cva` variants with the
   same tokens.
2. **Pilot one surface.** A single page, rebuilt fully, to agree the direction
   before it is applied 60 times. The host page is the densest and therefore
   the most honest test.
3. **Roll out by surface**, responsiveness fixed as each is touched.
4. **MagicUI selectively.** Only where motion serves the subject: never on
   dense operational tables, which is where it would read as noise.

## Verification protocol

The user runs the dev servers and the browser. Do not kill ports 8000/5173 and
do not run Playwright e2e without asking — it needs port 8000 and takes their
app down. Headless screenshots via
`.claude/skills/run-proxploy/driver.mjs shot` are fine and touch neither.

Visual work cannot be verified by the test suite. Screenshot each stage and
look at it before saying it is done.
