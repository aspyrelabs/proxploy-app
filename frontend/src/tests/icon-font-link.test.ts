import { describe, expect, it } from 'vitest'
import { buildIconFontHref } from '../../scripts/icon-font-link.mjs'

/**
 * scripts/icon-font-link.mjs turns a set of icon names into the Google
 * Fonts CDN href that actually serves them (see vite.config.ts, which
 * feeds it the names scripts/icon-names.mjs extracts from src/). These are
 * unit tests of the href-building rule in isolation; src/tests/icon-names-
 * coverage.test.tsx is the end-to-end guard that every icon a real
 * component renders ends up in it.
 */
describe('buildIconFontHref', () => {
  it('points at the Google Fonts css2 endpoint for Material Symbols Outlined', () => {
    const href = buildIconFontHref(['settings'])
    expect(href).toMatch(/^https:\/\/fonts\.googleapis\.com\/css2\?family=Material\+Symbols\+Outlined:/)
  })

  it('requests the full opsz, weight, fill and grade axis ranges this app draws icons from', () => {
    const href = buildIconFontHref(['settings'])
    expect(href).toContain('opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200')
  })

  it('lists every given name in icon_names, comma-separated', () => {
    const href = buildIconFontHref(['close', 'settings'])
    expect(href).toContain('&icon_names=close,settings')
  })

  it('sorts names, so the generated link is stable across runs', () => {
    const href = buildIconFontHref(['settings', 'archive', 'close'])
    expect(href).toContain('icon_names=archive,close,settings')
  })

  it('de-duplicates a name given more than once', () => {
    const href = buildIconFontHref(['close', 'close'])
    expect(href).toContain('icon_names=close')
    expect(href.match(/close/g)).toHaveLength(1)
  })

  it('refuses to build a link with no icon names, rather than requesting the full ~3,600-glyph font', () => {
    expect(() => buildIconFontHref([])).toThrow(/no icon names/)
  })
})
