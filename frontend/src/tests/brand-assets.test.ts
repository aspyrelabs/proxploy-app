/**
 * The four brand files, checked against their own names.
 *
 * These were once delivered with the two favicons swapped, and nothing caught
 * it: every test passed, the build was clean, and the only symptom was a dark
 * mark on a dark tab strip. This holds each file to the background it belongs
 * on, whatever the file is called.
 *
 * The two pairs are named on opposite conventions, which is why the lists
 * below look wrong at a glance. The favicons are named for their THEME
 * (-dark sits on dark). The logos are named for their INK (-dark is the dark
 * artwork, so it sits on LIGHT). Logo.tsx says the same at the call site. Do
 * not make them consistent here without recolouring the files.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const PUBLIC = join(__dirname, '..', '..', 'public')
const read = (name: string) => readFileSync(join(PUBLIC, name), 'utf8')

/** Near-white, the ink used on a dark background. */
const LIGHT_INK = 'fill: rgb(248,248,248)'
/** Near-black, the ink used on a light background. */
const DARK_INK = 'fill: rgb(11,13,22)'
/** The brand amber, in every variant of both marks. */
const AMBER = 'fill: rgb(248,179,64)'

describe('brand artwork', () => {
  it.each(['proxploy-logo-light.svg', 'proxploy-favicon-dark.svg'])(
    '%s carries light ink, because it sits on a dark background', (name) => {
      const svg = read(name)
      expect(svg).toContain(LIGHT_INK)
      expect(svg).toContain(AMBER)
    })

  it.each(['proxploy-logo-dark.svg', 'proxploy-favicon-light.svg'])(
    '%s carries dark ink, because it sits on a light background', (name) => {
      const svg = read(name)
      expect(svg).not.toContain(LIGHT_INK)
      expect(svg).toContain(DARK_INK)
      expect(svg).toContain(AMBER)
    })

  it.each([
    ['proxploy-favicon-dark.svg', '418.5 290.5 188 188'],
    ['proxploy-favicon-light.svg', '418.5 290.5 188 188'],
    ['proxploy-logo-dark.svg', '12 224 1010 205'],
    ['proxploy-logo-light.svg', '12 224 1010 205'],
  ])('%s is cropped to its artwork', (name, viewBox) => {
    // The exports arrive on a 1024x768 canvas with the mark floating in the
    // middle of it. Left alone, a favicon renders as a speck in a mostly empty
    // tab icon and the lockup cannot be sized by height.
    expect(read(name)).toContain(`viewBox="${viewBox}"`)
    expect(read(name)).not.toContain('width="1024" height="768"')
  })

  it('the two favicons are a pair, not two copies of one', () => {
    expect(read('proxploy-favicon-dark.svg'))
      .not.toEqual(read('proxploy-favicon-light.svg'))
  })
})
