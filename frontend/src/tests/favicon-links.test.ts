/**
 * The favicon a browser will actually pick, per OS colour scheme.
 *
 * An unconditional <link rel="icon"> is fetched alongside a media-scoped one
 * and wins over it, in BOTH schemes, wherever it sits in the document. That is
 * why proxploy-favicon-light.svg was in the file and never once used, and
 * moving the fallback to the front did not fix it: only removing it did.
 *
 * Measured by watching what a real Chromium requests. Headless does not fetch
 * favicons, so it cannot answer this and neither can a DOM-only assertion;
 * what this file can still hold is the shape that made the answer right.
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

/** The icons a browser could choose from in one scheme. Exactly one, or the
 *  unconditional link is back and the scoped ones are being overridden. */
function candidates(scheme: 'dark' | 'light'): string[] {
  return iconLinks()
    .filter((l) => l.media === null || l.media.includes(`prefers-color-scheme: ${scheme}`))
    .map((l) => l.href)
}

describe('favicon', () => {
  it('gives a dark tab strip the light-inked mark, and nothing competes', () => {
    expect(candidates('dark')).toEqual(['/proxploy-favicon-dark.svg'])
  })

  it('gives a light tab strip the dark-inked mark, and nothing competes', () => {
    expect(candidates('light')).toEqual(['/proxploy-favicon-light.svg'])
  })

  it('carries no unconditional icon link, which is what broke this', () => {
    // An unconditional link is fetched alongside the scoped one and wins in
    // both schemes, wherever it is placed. Re-adding one silently restores
    // the bug, so it is asserted away rather than left to a comment.
    expect(iconLinks().filter((l) => l.media === null)).toEqual([])
  })
})
