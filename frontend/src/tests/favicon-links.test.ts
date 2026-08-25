/**
 * The favicon a browser will actually pick, per OS colour scheme.
 *
 * A browser takes the LAST <link rel="icon"> whose media matches. The
 * unconditional fallback used to sit after the two scoped links, so it matched
 * in both schemes and won in both: proxploy-favicon-light.svg was in the
 * document and never once used, and a light desktop got the near-white mark
 * meant for a dark tab strip. Measured in Chromium before the fix, both
 * schemes resolved to proxploy-favicon-dark.svg.
 *
 * This asserts the resolution, not the order, so the file can be rearranged
 * however it likes as long as the answer stays right.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const html = readFileSync(join(__dirname, '..', '..', 'index.html'), 'utf8')

/** Every <link rel="icon">, in document order, with its media query. */
function iconLinks(): { href: string; media: string | null }[] {
  return [...html.matchAll(/<link\b[^>]*rel="icon"[^>]*>/g)].map((m) => ({
    href: /href="([^"]+)"/.exec(m[0])?.[1] ?? '',
    media: /media="([^"]+)"/.exec(m[0])?.[1] ?? null,
  }))
}

/** What the browser lands on: last match wins. */
function resolve(scheme: 'dark' | 'light'): string {
  const matching = iconLinks().filter(
    (l) => l.media === null || l.media.includes(`prefers-color-scheme: ${scheme}`))
  return matching[matching.length - 1].href
}

describe('favicon', () => {
  it('gives a dark tab strip the light-inked mark', () => {
    expect(resolve('dark')).toBe('/proxploy-favicon-dark.svg')
  })

  it('gives a light tab strip the dark-inked mark', () => {
    // The one that regressed: an unconditional link placed last overrides this.
    expect(resolve('light')).toBe('/proxploy-favicon-light.svg')
  })

  it('still carries an unconditional icon for a browser that reads no media', () => {
    expect(iconLinks().some((l) => l.media === null)).toBe(true)
  })
})
