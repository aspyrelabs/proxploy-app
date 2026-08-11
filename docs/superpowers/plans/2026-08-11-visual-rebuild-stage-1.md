# Visual Rebuild Stage 1: shadcn infrastructure, no visual change

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the shadcn/ui machinery — dependencies, `@/` alias, `cn`, the token
alias layer, and one primitive rebuilt on `cva` — so that stage 2 can rebuild a
whole surface without any of this being in the way.

**Architecture:** shadcn's token vocabulary is aliased *onto* Proxploy's existing
tokens in one CSS block, so there is one palette with two names for each colour
rather than two palettes. Components are added with the shadcn CLI but their
hex literals are replaced with those aliases before they are committed. The
hand-rolled `Button` becomes the proof: same tokens, same pixels, now on `cva`.

**Tech Stack:** React 19, Tailwind v4 (`@theme inline`, no config file), Vite 8,
Vitest 4, `class-variance-authority`, `clsx`, `tailwind-merge`.

## Global Constraints

Copied from `docs/superpowers/specs/2026-08-11-visual-rebuild-brief.md`:

- **No hardcoded colours.** `src/tests/no-hardcoded-colors.test.ts` fails the
  build on a literal hex in a non-allowlisted file. Every shadcn component must
  be themed through tokens, not the hex values shadcn ships with.
- **417 tests are the safety net.** They assert on current markup and copy.
  Treat a test that needs changing as a question ("did the meaning change?"),
  not a chore. Baseline as of this plan: `npm test` → 59 files, 417 passed, 5
  skipped.
- **`docs/06-frontend-spec.md` is normative** for the component set. Update it in
  the same commit as any component it describes.
- **Light theme is real.** `[data-theme="light"]` must keep working; the alias
  layer must not pin a dark value.
- **Dependency weight.** Three runtime additions in this stage —
  `class-variance-authority`, `clsx`, `tailwind-merge`. No Radix package, no
  `motion`, and no icon library until a component actually needs one. This
  codebase has 12 runtime dependencies and 2 files containing an `<svg>`; a
  shadcn component that arrives importing `lucide-react` gets its icons inlined
  or is not added yet.
- **Do not kill ports 8000/5173 and do not run Playwright.** The user runs the
  dev servers. Screenshots via
  `.claude/skills/run-proxploy/driver.mjs shot` are fine and touch neither.
- **Stage 1 is a visual no-op.** Every screenshot must be indistinguishable from
  its before, with the single deliberate exception recorded in Task 3.

---

## File Structure

| File | Responsibility |
|---|---|
| `frontend/components.json` (create) | Tells the shadcn CLI where this project keeps things. Not read at runtime. |
| `frontend/src/lib/cn.ts` (create) | `clsx` + `tailwind-merge`. The only class-joining helper in the codebase. |
| `frontend/vite.config.ts` (modify) | `@/` → `src/`, so CLI-generated imports resolve. |
| `frontend/tsconfig.app.json` (modify) | The same alias for the type-checker. |
| `frontend/src/styles/tokens.css` (modify) | Adds the shadcn alias layer after both theme blocks, and exposes it to Tailwind through `@theme inline`. |
| `frontend/src/components/ui/button.tsx` (modify) | Same rendering, now `cva` variants plus a `size` scale. |
| `frontend/src/tests/cn.test.ts` (create) | That `cn` resolves conflicts rather than concatenating them. |
| `frontend/src/tests/token-aliases.test.ts` (create) | That every shadcn alias exists and points at a Proxploy token, in both themes. This is the guard that stops a future `shadcn init` from pasting its own palette in. |
| `frontend/src/tests/button.test.tsx` (create) | Variant and size classes, and that a caller's `className` wins. |

---

### Task 1: `cn`, the `@/` alias, and `components.json`

**Files:**
- Modify: `frontend/package.json` (via `npm install`)
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/tsconfig.app.json`
- Create: `frontend/src/lib/cn.ts`
- Create: `frontend/components.json`
- Test: `frontend/src/tests/cn.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: `cn(...inputs: ClassValue[]): string` from `src/lib/cn.ts`, and the
  `@/` path alias. Task 3 imports `cn` from `@/lib/cn`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/tests/cn.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { cn } from '@/lib/cn'

describe('cn', () => {
  it('joins classes', () => {
    expect(cn('a', 'b')).toBe('a b')
  })

  it('drops falsy values', () => {
    expect(cn('a', false && 'b', undefined, 'c')).toBe('a c')
  })

  // The reason tailwind-merge is here rather than plain clsx: a caller who
  // passes px-2 to a component whose base is px-3.5 should get px-2, not a
  // coin flip decided by the order Tailwind happened to emit the two rules.
  it('lets the last conflicting utility win', () => {
    expect(cn('px-3.5 py-2', 'px-2')).toBe('py-2 px-2')
  })

  it('resolves arbitrary values too', () => {
    expect(cn('text-[13px]', 'text-[11px]')).toBe('text-[11px]')
  })
})
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd frontend && npx vitest run src/tests/cn.test.ts
```

Expected: FAIL — `Failed to resolve import "@/lib/cn"`.

- [ ] **Step 3: Install the three dependencies**

```bash
cd frontend && npm install clsx tailwind-merge class-variance-authority
```

`class-variance-authority` is not used until Task 3; it is installed here so the
dependency decision lands in one reviewable commit.

- [ ] **Step 4: Add the `@/` alias to Vite**

In `frontend/vite.config.ts`, add the import and the `resolve` block:

```ts
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // shadcn's CLI writes imports as `@/components/ui/x`. Aliasing it here (and
  // in tsconfig.app.json) means generated components need no rewriting.
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  // ...leave the existing test block and its comment untouched
})
```

- [ ] **Step 5: Add the same alias to TypeScript**

In `frontend/tsconfig.app.json`, inside `compilerOptions`:

```json
    "baseUrl": ".",
    "paths": { "@/*": ["./src/*"] },
```

- [ ] **Step 6: Write `cn`**

Create `frontend/src/lib/cn.ts`:

```ts
import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** Join class names, letting the last conflicting Tailwind utility win. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}
```

- [ ] **Step 7: Run the test**

```bash
cd frontend && npx vitest run src/tests/cn.test.ts
```

Expected: PASS, 4 tests.

- [ ] **Step 8: Add `components.json`**

Create `frontend/components.json`. Note `utils` points at `@/lib/cn`, not
shadcn's default `@/lib/utils` — this codebase names files after what they do
(`format.ts`, `theme.ts`) and has no junk drawer.

```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "new-york",
  "rsc": false,
  "tsx": true,
  "tailwind": {
    "config": "",
    "css": "src/styles/tokens.css",
    "baseColor": "neutral",
    "cssVariables": true,
    "prefix": ""
  },
  "aliases": {
    "components": "@/components",
    "ui": "@/components/ui",
    "lib": "@/lib",
    "hooks": "@/hooks",
    "utils": "@/lib/cn"
  }
}
```

Do **not** run `npx shadcn@latest init` — it rewrites `tailwind.css` with its own
palette, which is exactly what Task 2 exists to prevent. `npx shadcn@latest add
<component>` is fine and is how stage 2 pulls components in; every added file
gets read for hex literals and `lucide-react` imports before it is committed.

- [ ] **Step 9: Verify the whole suite and the type-check still pass**

```bash
cd frontend && npm test && npm run build
```

Expected: 60 files passed, 421 passed / 5 skipped; build succeeds.

- [ ] **Step 10: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vite.config.ts \
        frontend/tsconfig.app.json frontend/src/lib/cn.ts frontend/components.json \
        frontend/src/tests/cn.test.ts
git commit -m "build(frontend): the shadcn machinery, minus any shadcn styling"
```

---

### Task 2: The token alias layer

**Files:**
- Modify: `frontend/src/styles/tokens.css`
- Modify: `docs/06-frontend-spec.md`
- Test: `frontend/src/tests/token-aliases.test.ts`

**Interfaces:**
- Consumes: the existing `--ink/--panel/--text/--amber/...` tokens.
- Produces: CSS variables `--background`, `--foreground`, `--card`,
  `--card-foreground`, `--popover`, `--popover-foreground`, `--primary`,
  `--primary-foreground`, `--secondary`, `--secondary-foreground`, `--muted`,
  `--muted-foreground`, `--accent`, `--accent-foreground`, `--destructive`,
  `--destructive-foreground`, `--border`, `--input`, `--ring`, `--radius`, and
  the matching `--color-*` entries so `bg-background`, `text-muted-foreground`,
  `border-border` and `ring-ring` become real Tailwind utilities.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/tests/token-aliases.test.ts`:

```ts
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const css = readFileSync(join(__dirname, '../styles/tokens.css'), 'utf8')

// The names shadcn components reference. If a component needs one that is not
// here, add it to this list AND to the alias block — never let the component
// carry its own colour.
const ALIASES = [
  'background', 'foreground',
  'card', 'card-foreground',
  'popover', 'popover-foreground',
  'primary', 'primary-foreground',
  'secondary', 'secondary-foreground',
  'muted', 'muted-foreground',
  'accent', 'accent-foreground',
  'destructive', 'destructive-foreground',
  'border', 'input', 'ring',
]

describe('shadcn token aliases', () => {
  it.each(ALIASES)('--%s is defined as a Proxploy token, not a literal', (name) => {
    const decl = new RegExp(`^\\s*--${name}\\s*:\\s*([^;]+);`, 'm').exec(css)
    expect(decl, `--${name} is not declared in tokens.css`).not.toBeNull()
    // var(--something) only. A hex here means someone pasted shadcn's palette
    // in and the app now has two palettes that drift apart.
    expect(decl![1].trim()).toMatch(/^var\(--[a-z0-9-]+\)$/)
  })

  it.each(ALIASES)('--%s is exposed to Tailwind as a utility', (name) => {
    expect(css).toMatch(new RegExp(`--color-${name}\\s*:\\s*var\\(--${name}\\)`))
  })

  // The aliases are declared once, after both theme blocks, and resolve per
  // element. Declaring them inside [data-theme="dark"] would pin the dark
  // value and silently break the light theme.
  it('declares the aliases after the light theme block', () => {
    expect(css.indexOf('--background:')).toBeGreaterThan(css.indexOf('[data-theme="light"]'))
  })
})
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd frontend && npx vitest run src/tests/token-aliases.test.ts
```

Expected: FAIL — every alias "is not declared in tokens.css".

- [ ] **Step 3: Add the alias block**

In `frontend/src/styles/tokens.css`, immediately after the closing brace of the
`[data-theme="light"]` block and before `@theme inline`:

```css
/* shadcn/ui's vocabulary, aliased onto the tokens above. One palette, two sets
   of names — not two palettes.

   Declared ONCE rather than per theme on purpose: `var(--ink)` is resolved
   against whichever element the alias is read on, so a page under
   [data-theme="light"] gets the light --ink through the same declaration.
   Repeating the block per theme would be two places to forget. */
:root {
  --background: var(--ink);
  --foreground: var(--text);
  --card: var(--panel);
  --card-foreground: var(--text);
  --popover: var(--panel);
  --popover-foreground: var(--text);
  --primary: var(--amber);
  --primary-foreground: var(--amber-ink);
  --secondary: var(--panel-2);
  --secondary-foreground: var(--text);
  --muted: var(--panel-2);
  --muted-foreground: var(--text-3);
  --accent: var(--elev);
  --accent-foreground: var(--text);
  --destructive: var(--red);
  --destructive-foreground: var(--text);
  --border: var(--line);
  --input: var(--line);
  --ring: var(--amber);
  --radius: var(--radius-ctl, 10px);
}
```

- [ ] **Step 4: Add `--amber-ink` to both theme blocks**

`--primary-foreground` is the only alias with no existing token behind it: it is
the text colour that sits *on* amber. `button.tsx` currently hardcodes `#20160a`
inside a class string, which the colour guard does not catch because it only
scans `style=`/`stroke=`/`fill=`. Give it a name.

In the `:root, [data-theme="dark"]` block, on the `--amber` line:

```css
  --amber:#F5B544; --amber-dim:rgba(245,181,68,.13); --amber-ink:#20160A;
```

In the `[data-theme="light"]` block:

```css
  --amber:#C77E14; --amber-dim:rgba(199,126,20,.13); --amber-ink:#20160A;
```

The light value is deliberately the same. The primary button's fill is a fixed
amber gradient in both themes today (Task 3 keeps it that way), so the text on
it must not change either. When the gradient is tokenised in a later stage,
this is the pair that gets revisited together.

- [ ] **Step 5: Expose the aliases to Tailwind**

Inside the existing `@theme inline` block, after the `--color-scrim` line:

```css
  /* shadcn components use bg-background / text-muted-foreground / border-border
     / ring-ring. Those utilities only exist if the names are registered here. */
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-popover: var(--popover);
  --color-popover-foreground: var(--popover-foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-secondary: var(--secondary);
  --color-secondary-foreground: var(--secondary-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent);
  --color-accent-foreground: var(--accent-foreground);
  --color-destructive: var(--destructive);
  --color-destructive-foreground: var(--destructive-foreground);
  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);
  --color-amber-ink: var(--amber-ink);
```

- [ ] **Step 6: Run the tests**

```bash
cd frontend && npx vitest run src/tests/token-aliases.test.ts src/tests/no-hardcoded-colors.test.ts
```

Expected: PASS. `no-hardcoded-colors` still passes because `tokens.css` is not a
`.ts`/`.tsx` file — the guard has never covered it, which is precisely why the
alias test above checks for literals itself.

- [ ] **Step 7: Confirm nothing rendered changed**

Nothing consumes the aliases yet, so this is a pure addition. Verify anyway:

```bash
cd frontend && npm test
```

Expected: 61 files passed, 424 passed / 5 skipped.

- [ ] **Step 8: Record it in the frontend spec**

In `docs/06-frontend-spec.md`, in the design-tokens section, add a subsection
naming the alias layer, stating that shadcn components must use the aliased
names, and reproducing the mapping table from
`docs/superpowers/specs/2026-08-11-visual-rebuild-brief.md` with the additions
made here (`--secondary`, the `-foreground` pairs, `--amber-ink`, `--radius`).

- [ ] **Step 9: Commit**

```bash
git add frontend/src/styles/tokens.css frontend/src/tests/token-aliases.test.ts docs/06-frontend-spec.md
git commit -m "feat(tokens): give shadcn its vocabulary without giving it a palette"
```

---

### Task 3: `Button` on `cva`

**Files:**
- Modify: `frontend/src/components/ui/button.tsx`
- Modify: the call sites that pass `px-2 py-1 text-[11px]` (≈36 of them)
- Modify: `docs/06-frontend-spec.md`
- Test: `frontend/src/tests/button.test.tsx`

**Interfaces:**
- Consumes: `cn` from `@/lib/cn` (Task 1), `--amber-ink` (Task 2).
- Produces: `Button` with props `variant?: 'primary' | 'ghost' | 'danger' | 'go'`
  (default `'primary'`) and `size?: 'sm' | 'md'` (default `'md'`), plus the
  exported `buttonVariants` for elements that must be an `<a>` rather than a
  `<button>`. The four variant names are unchanged, so all 48 importing files
  keep working untouched.

**Read this before starting.** Introducing `tailwind-merge` changes behaviour at
every call site that overrides a base utility. 36 call sites pass
`px-2 py-1 text-[11px]` against a base of `px-3.5 py-2 text-[13px]`; today both
utilities land in the class list and the winner is decided by the order Tailwind
emitted them, not by the caller. After `cn`, the caller wins deterministically.
That is the one deliberate visual change in stage 1, and it is why Step 6 exists:
find out which way those buttons render today, then make `size="sm"` produce
that same intent explicitly rather than letting a merge silently resize 36
controls.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/tests/button.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Button } from '../components/ui/button'

describe('Button', () => {
  it('is primary by default', () => {
    render(<Button>Go</Button>)
    expect(screen.getByRole('button').className).toContain('shadow-')
  })

  it('renders each variant with its own token colours', () => {
    const { rerender } = render(<Button variant="ghost">x</Button>)
    expect(screen.getByRole('button').className).toContain('bg-panel-2')
    rerender(<Button variant="danger">x</Button>)
    expect(screen.getByRole('button').className).toContain('text-red')
    rerender(<Button variant="go">x</Button>)
    expect(screen.getByRole('button').className).toContain('text-amber')
  })

  it('has a small size that does not need per-call-site overrides', () => {
    render(<Button size="sm">x</Button>)
    const cls = screen.getByRole('button').className
    expect(cls).toContain('px-2')
    expect(cls).not.toContain('px-3.5')
  })

  // The whole reason for tailwind-merge: the caller's utility must win.
  it('lets a caller override a base utility', () => {
    render(<Button className="px-8">x</Button>)
    const cls = screen.getByRole('button').className
    expect(cls).toContain('px-8')
    expect(cls).not.toContain('px-3.5')
  })

  it('forwards button attributes', () => {
    render(<Button disabled type="submit">x</Button>)
    const btn = screen.getByRole('button') as HTMLButtonElement
    expect(btn.disabled).toBe(true)
    expect(btn.type).toBe('submit')
  })
})
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd frontend && npx vitest run src/tests/button.test.tsx
```

Expected: FAIL on the `size` and override cases.

- [ ] **Step 3: Rewrite `button.tsx` on `cva`**

Replace `frontend/src/components/ui/button.tsx` entirely:

```tsx
import type { ButtonHTMLAttributes } from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/cn'

export const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 rounded-ctl cursor-pointer transition disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60',
  {
    variants: {
      variant: {
        // The fill is a fixed gradient in both themes; --amber-ink is the text
        // that sits on it. Tokenising the gradient itself is a later stage.
        primary: 'bg-[linear-gradient(150deg,#F5B544,#E79126)] text-amber-ink font-semibold shadow-[0_6px_18px_rgba(245,181,68,.25)] hover:brightness-105',
        ghost: 'bg-panel-2 text-text border border-line hover:bg-elev',
        danger: 'bg-red-dim text-red border border-red/30 hover:bg-red/20',
        go: 'bg-amber-dim text-amber border border-amber/30 hover:bg-amber/20',
      },
      size: {
        md: 'px-3.5 py-2 text-[13px]',
        sm: 'px-2 py-1 text-[11px]',
      },
    },
    defaultVariants: { variant: 'primary', size: 'md' },
  },
)

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof buttonVariants>

export function Button({ variant, size, className, ...props }: ButtonProps) {
  return <button className={cn(buttonVariants({ variant, size }), className)} {...props} />
}
```

Two changes beyond the mechanical port, both intentional:
`focus-visible:ring-*` (the hand-rolled button had no focus ring at all, which
is one of the reasons for this rebuild), and `text-amber-ink` replacing the
`#20160a` literal.

- [ ] **Step 4: Run the button test**

```bash
cd frontend && npx vitest run src/tests/button.test.tsx
```

Expected: PASS, 5 tests.

- [ ] **Step 5: Run the whole suite**

```bash
cd frontend && npm test
```

Expected: green. If a test fails, ask whether the meaning changed before editing
it — a failure here is most likely the `tailwind-merge` behaviour change, which
is real and belongs in Step 6, not papered over.

- [ ] **Step 6: Settle which padding wins today — from the stylesheet, not by eye**

The 36 small buttons live on authenticated surfaces, and the driver opens a
fresh unauthenticated browser, so a screenshot cannot answer this. The built
stylesheet can, exactly: two utilities set the same property, so the one Tailwind
emits *later* wins. Check on the pre-change build:

```bash
cd frontend && git stash && npm run build && \
  grep -n -o '\.px-3\\.5{[^}]*}\|\.px-2{[^}]*}\|\.text-\[11px\]{[^}]*}\|\.text-\[13px\]{[^}]*}' dist/assets/*.css ; \
  git stash pop
```

Record the line numbers. The larger line number is the utility that renders
today. Write the answer into the commit message in Step 11 — "the 36 small
buttons were rendering at px-3.5/13px, i.e. not small at all" or "they already
rendered small; `size=\"sm\"` just says so" — because it is the one fact that
tells a reviewer whether this task changed pixels.

- [ ] **Step 7: Migrate the call sites to `size="sm"`**

Find them:

```bash
cd frontend && grep -rn 'className="[^"]*px-2 py-1 text-\[11px\]' src --include="*.tsx"
```

For each one that is a `<Button>`, replace the size utilities with `size="sm"`,
keeping any unrelated classes (`ml-2`, `mt-3`, `w-full`) in `className`. Do not
touch non-Button elements that happen to share the class string.

- [ ] **Step 8: Verify**

```bash
cd frontend && npm test && npm run build && npx oxlint
```

Expected: green, and no `px-2 py-1 text-[11px]` left on a `Button`.

- [ ] **Step 9: Look at it**

Screenshot the public surfaces the driver can reach, which do render `Button`:

```bash
node .claude/skills/run-proxploy/driver.mjs shot /tmp/pp-login.png /login
node .claude/skills/run-proxploy/driver.mjs shot /tmp/pp-onboarding.png /onboarding
```

Read the images. They must be indistinguishable from before, except that a
focused button now shows a ring.

The authenticated surfaces — where the 36 small buttons are — cannot be reached
by the driver, which has no login step. Do not guess at them: if Step 6 showed
the sizing changes, say so and ask the user to look at a host page in their own
browser before this stage is called done. Offer to teach the driver to log in as
a separate piece of work rather than smuggling it into this task.

- [ ] **Step 10: Update the frontend spec**

In `docs/06-frontend-spec.md`, update the `Button` entry: the four variants are
unchanged, `size` is new, the component is built on `cva` + `cn`, and it now has
a focus ring.

- [ ] **Step 11: Commit**

```bash
git add frontend/src/components/ui/button.tsx frontend/src/tests/button.test.tsx \
        frontend/src docs/06-frontend-spec.md
git commit -m "refactor(button): same button, now a primitive with a size and a focus ring"
```

---

## Done when

- `npm test`, `npm run build` and `npx oxlint` are green.
- `/login` and `/onboarding` screenshot identically to before, focus ring aside.
- The small-button sizing question from Task 3 Step 6 is answered in writing, and
  if it changed pixels, the user has looked at an authenticated surface.
- `components.json`, `cn`, the alias layer and one `cva` primitive are in, and
  `npx shadcn@latest add <component>` resolves paths correctly.
- Stage 2 (pilot the host page) can start without touching any of this again.

## Explicitly not in this stage

- Any Radix package, `motion`/MagicUI, or an icon library.
- Responsive breakpoints. Stage 3 fixes those per surface as it touches them.
- Tokenising the primary button's gradient, and the fact that it does not change
  between themes. Recorded here so it is not lost.
