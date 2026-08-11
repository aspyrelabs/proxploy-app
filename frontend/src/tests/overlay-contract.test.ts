import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * The audit that started this change found the same four defects in 18
 * hand-rolled dialogs: no Escape, no focus trap, no focus restore, no
 * aria-modal. Those behaviours are now supplied once, by the shared primitive,
 * and proved once, in ui-dialog.test.tsx.
 *
 * This test is what makes that proof cover all of them: it fails if any file
 * grows its own scrim again. A per-dialog copy of the same behavioural test
 * would assert the same thing 20 times and still miss the 21st dialog someone
 * writes next month.
 */

// LockVeil is not a dialog. It is a decorative overlay drawn over a card to
// show an unentitled feature, with nothing to focus and nothing to escape.
const NOT_A_DIALOG = ['components/LockVeil.tsx']

// The primitive is allowed to contain the scrim. It is the scrim.
const THE_PRIMITIVE = ['components/ui/overlay.ts', 'components/ui/dialog.tsx']

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((e) => {
    const p = join(dir, e)
    return statSync(p).isDirectory() ? walk(p) : p.endsWith('.tsx') || p.endsWith('.ts') ? [p] : []
  })
}

describe('overlay contract', () => {
  it('no component hand-rolls a modal scrim', () => {
    const src = join(__dirname, '..')
    const offenders: string[] = []

    for (const file of walk(src)) {
      const rel = file.slice(src.length + 1)
      if (rel.startsWith('tests/')) continue
      if ([...NOT_A_DIALOG, ...THE_PRIMITIVE].some((a) => rel.endsWith(a))) continue

      readFileSync(file, 'utf8').split('\n').forEach((line, i) => {
        // A full-viewport fixed layer carrying a dim. That is a scrim, and a
        // scrim means someone is building a modal by hand again.
        if (/fixed inset-0/.test(line) && /bg-scrim|bg-black\/|bg-ink\//.test(line)) {
          offenders.push(`${rel}:${i + 1}  ${line.trim()}`)
        }
      })
    }

    expect(offenders, offenders.join('\n')).toEqual([])
  })

  // Not an overlay concern, but the same failure: a panel that states a pixel
  // width and never says what to do when the viewport is narrower than that.
  // Scoped to rounded-card so it means "a panel", and does not catch the
  // 236px sidebar or the fixed-width form fields, which are neither.
  it('no card panel states a width without a cap', () => {
    const src = join(__dirname, '..')
    const offenders: string[] = []

    for (const file of walk(src)) {
      const rel = file.slice(src.length + 1)
      if (rel.startsWith('tests/')) continue

      readFileSync(file, 'utf8').split('\n').forEach((line, i) => {
        if (!/\bw-\[\d+px\]/.test(line) || !/rounded-card/.test(line)) return
        if (/max-w-/.test(line)) return
        offenders.push(`${rel}:${i + 1}  ${line.trim()}`)
      })
    }

    expect(offenders, offenders.join('\n')).toEqual([])
  })
})
