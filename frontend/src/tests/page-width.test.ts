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
        // Tailwind's named page-scale caps. Arbitrary values like
        // max-w-[92vw] are viewport-relative and are the opposite of the
        // problem, so they are deliberately not matched here.
        if (/className="[^"]*\bmax-w-(sm|md|lg|xl|[2-7]xl)\b/.test(line)) {
          offenders.push(`${file}:${i + 1}  ${line.trim()}`)
        }
      })
    }
    expect(offenders, offenders.join('\n')).toEqual([])
  })
})
