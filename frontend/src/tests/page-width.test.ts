import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

// Settings, Alerts and Audit each capped their own page at a different width
// (3xl / 4xl / 5xl) while every other page filled the shell, so the app looked
// like three different products depending on which tab you were on. Pages size
// to the browser; a component inside one may still cap itself.
describe('page width', () => {
  it('no route page caps its own width', () => {
    const dir = join(__dirname, '..', 'routes')
    const offenders: string[] = []
    for (const file of readdirSync(dir).filter(f => f.endsWith('.tsx'))) {
      readFileSync(join(dir, file), 'utf8').split('\n').forEach((line, i) => {
        // Only the PAGE ROOT, identified by this codebase's convention of
        // `space-y-*` on the outermost element of a route component. A cap on
        // an inner element is fine and usually right: a password field has no
        // business being 2000px wide. An earlier version of this test matched
        // any max-w- anywhere and flagged exactly those legitimate cases.
        //
        // Arbitrary values like max-w-[92vw] stay unmatched on purpose: those
        // are viewport-relative, which is the opposite of the problem.
        if (/className="[^"]*\bmax-w-(sm|md|lg|xl|[2-7]xl)\b[^"]*\bspace-y-/.test(line)
            || /className="[^"]*\bspace-y-[^"]*\bmax-w-(sm|md|lg|xl|[2-7]xl)\b/.test(line)) {
          offenders.push(`${file}:${i + 1}  ${line.trim()}`)
        }
      })
    }
    expect(offenders, offenders.join('\n')).toEqual([])
  })
})
