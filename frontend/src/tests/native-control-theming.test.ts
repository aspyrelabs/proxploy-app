/**
 * The native controls, checked against the theme they are supposed to follow.
 *
 * Checkboxes, radios, range sliders and progress bars are drawn by the
 * browser. No class in this app reaches them, so the only thing that makes
 * them match the palette is two declarations in tokens.css, and the only
 * symptom of losing either one is a system-blue tick or a white box on a dark
 * panel. Nothing else in the suite would fail.
 */
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const SRC = join(__dirname, '..')
const css = readFileSync(join(SRC, 'styles', 'tokens.css'), 'utf8')

/** The theme block's body, from its selector to its closing brace. */
const block = (selector: string) => {
  const start = css.indexOf(selector)
  expect(start, `${selector} is missing from tokens.css`).toBeGreaterThan(-1)
  return css.slice(start, css.indexOf('}', start))
}

describe('native form controls follow the theme', () => {
  it('the dark theme paints the checked fill with the brand amber', () => {
    // On :root as well as [data-theme="dark"], and by inheritance rather
    // than a selector, so a new checkbox anywhere is themed by default.
    expect(block(':root, [data-theme="dark"]')).toContain('accent-color: var(--amber)')
  })

  it('each theme declares its own color-scheme', () => {
    // accent-color re-resolves on its own because --amber is a var. This
    // one cannot: it is a keyword, so both blocks have to say it.
    expect(block(':root, [data-theme="dark"]')).toContain('color-scheme: dark')
    expect(block('[data-theme="light"]')).toContain('color-scheme: light')
  })

  it('no component sets its own accent colour', () => {
    // A per-call-site accent is the thing this replaced. One would still
    // look right today and drift the moment the token moves.
    const offenders = readdirSync(SRC, { recursive: true, encoding: 'utf8' })
      .filter((f) => /\.tsx$/.test(f) && !f.startsWith('tests'))
      // The Tailwind utility only. TimeChart has a local `accentColor`
      // variable for its canvas stroke, which is not a form control.
      .filter((f) => /\baccent-(amber|green|red|blue|\[)/.test(readFileSync(join(SRC, f), 'utf8')))

    expect(offenders).toEqual([])
  })
})
