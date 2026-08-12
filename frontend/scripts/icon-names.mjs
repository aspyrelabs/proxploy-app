import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

// Three shapes cover every icon name in this codebase:
//   1. <Icon name="settings" .../>            -- a direct string literal
//   2. <Icon name={cond ? 'a' : 'b'} .../>     -- a ternary between two
//      literals (ThemeToggle, SidebarNav's collapse chevron): both branches
//      are kept, since which one renders depends on runtime state
//   3. icon: 'dns'                             -- a data table like NAV,
//      whose rows feed <Icon name={item.icon} .../> a step removed
// All three bottom out in plain string literals somewhere in the source
// text, never a value that only exists at runtime (an import, a function
// call) -- an icon name that can't be read straight out of the source can't
// go into the Google Fonts link's icon_names parameter either (see
// vite-plugin-material-symbols-link.mjs), so it isn't a name this extractor
// resolves.
const ICON_NAME_ATTR = /<Icon\b[^>]*?\bname\s*=\s*(?:"([a-z][a-z0-9_]*)"|'([a-z][a-z0-9_]*)'|\{([^{}]*)\})/g
const ICON_FIELD = /\bicon\s*:\s*(?:"([a-z][a-z0-9_]*)"|'([a-z][a-z0-9_]*)')/g
// Only the two OUTCOME branches of `cond ? 'a' : 'b'`, anchored on the `?`
// and `:` tokens -- deliberately not "any quoted string in the braces",
// which would also catch a literal the condition compares against (e.g.
// `theme === 'dark' ? ... : ...`) and pull an unrelated word into the font.
const TERNARY_BRANCHES = /\?\s*(?:"([a-z][a-z0-9_]*)"|'([a-z][a-z0-9_]*)')\s*:\s*(?:"([a-z][a-z0-9_]*)"|'([a-z][a-z0-9_]*)')/

// src/tests is fixtures and assertions, never shipped -- a negative test
// asserting on a deliberately-fake name (e.g. "not_a_real_icon") must not
// leak into what the production font actually subsets.
const SKIP_DIRS = new Set(['tests'])

function walk(dir) {
  return readdirSync(dir).flatMap((entry) => {
    if (SKIP_DIRS.has(entry)) return []
    const path = join(dir, entry)
    if (statSync(path).isDirectory()) return walk(path)
    return /\.(tsx?|jsx?)$/.test(path) ? [path] : []
  })
}

function collectLiterals(text, pattern, into) {
  for (const match of text.matchAll(pattern)) {
    into.add(match[1] ?? match[2])
  }
}

/** name={...} can hold an arbitrary expression. The one real shape in this
 *  codebase is a ternary between two literals (ThemeToggle, SidebarNav's
 *  collapse chevron); anything else -- a plain variable reference like
 *  `name={item.icon}` included -- contributes nothing here on purpose. A
 *  variable's name is expected to show up instead via the icon: '...'
 *  field pattern at its own definition site (e.g. NAV); if some future
 *  shape resolves through neither, src/tests/icon-subset.test.tsx's
 *  render-vs-extract comparison is the backstop that catches it. */
function collectIconNameAttrs(text, into) {
  for (const match of text.matchAll(ICON_NAME_ATTR)) {
    if (match[1]) { into.add(match[1]); continue }
    if (match[2]) { into.add(match[2]); continue }
    if (match[3] === undefined) continue
    const branches = TERNARY_BRANCHES.exec(match[3])
    if (!branches) continue
    into.add(branches[1] ?? branches[2])
    into.add(branches[3] ?? branches[4])
  }
}

/** Every Material Symbols name referenced anywhere under `srcDir`, as a Set.
 *  This is the single source of truth for both the Google Fonts CDN link's
 *  `icon_names` parameter (vite-plugin-material-symbols-link.mjs) and the
 *  rendered-vs-extracted coverage guard
 *  (src/tests/icon-names-coverage.test.tsx) -- there is no separately
 *  hand-maintained list of icon names to drift out of sync with either one. */
export function extractIconNames(srcDir) {
  const names = new Set()
  for (const file of walk(srcDir)) {
    const text = readFileSync(file, 'utf8')
    collectIconNameAttrs(text, names)
    collectLiterals(text, ICON_FIELD, names)
  }
  return names
}
