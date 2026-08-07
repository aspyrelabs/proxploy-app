import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

// Terminal and console surfaces are dark in BOTH themes on purpose, a
// terminal that follows a light theme stops looking like a terminal. That
// intent was previously unrecorded anywhere; this list is where it lives now.
const INTENTIONALLY_DARK = [
  'components/ScriptPanel.tsx',
  'components/TerminalPanel.tsx',
  'components/terminal/Terminal.tsx',
  'components/console/VncConsole.tsx',
  'routes/onboarding.tsx',
]

// Gradient stops are multi-colour brand ramps with no token equivalent; they
// are theme-neutral by construction (they sit on their own fill, not on a
// surface that flips).
const ALLOWED_LINE = /GRADIENT\s*=|linearGradient|stopColor=\{/

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((e) => {
    const p = join(dir, e)
    return statSync(p).isDirectory() ? walk(p) : p.endsWith('.tsx') || p.endsWith('.ts') ? [p] : []
  })
}

describe('no hardcoded colours', () => {
  it('every colour comes from a token', () => {
    const src = join(__dirname, '..')
    const offenders: string[] = []
    for (const file of walk(src)) {
      const rel = file.slice(src.length + 1)
      if (rel.startsWith('tests/') || INTENTIONALLY_DARK.some((d) => rel.endsWith(d))) continue
      readFileSync(file, 'utf8').split('\n').forEach((line, i) => {
        if (ALLOWED_LINE.test(line)) return
        if (/(style=\{\{[^}]*|stroke=|fill=)["'\s:]*#[0-9a-fA-F]{3,8}\b/.test(line)) {
          offenders.push(`${rel}:${i + 1}  ${line.trim()}`)
        }
      })
    }
    expect(offenders, offenders.join('\n')).toEqual([])
  })
})
