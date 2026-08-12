import { describe, expect, it, vi } from 'vitest'
import { revealIconsWhenReady } from '../lib/reveal-icons-when-ready'

/**
 * Google's Material Symbols stylesheet (injected by vite.config.ts's
 * materialSymbolsLink plugin) does not set font-display on its @font-face
 * rule (verified by fetching the real CSS2 response), so the browser's
 * default applies -- commonly a short invisible period before falling back
 * to visible fallback-font text. Our Icon component's text content IS the
 * icon's readable name ("settings"), so on a slow or blocked CDN that
 * fallback period expiring means the literal word flashes where a glyph
 * belongs.
 *
 * revealIconsWhenReady keeps every icon invisible (see the CSS rule in
 * styles/tokens.css) until the font has actually finished loading (success
 * or failure), then reveals them all at once via a class on <html> -- so
 * there is never a flash of readable text, on a fast connection or a slow
 * one. It still reveals icons on a failed/never-settling-successfully load
 * rather than hiding them forever, since every icon in this app sits next
 * to a text label that carries the meaning on its own.
 */
function fakeDoc(fonts?: { load: () => Promise<unknown> }) {
  const add = vi.fn()
  const doc = {
    documentElement: { classList: { add } },
    ...(fonts ? { fonts } : {}),
  } as unknown as Document
  return { doc, add }
}

describe('revealIconsWhenReady', () => {
  it('reveals icons immediately when the Font Loading API is unavailable', () => {
    const { doc, add } = fakeDoc()
    revealIconsWhenReady(doc)
    expect(add).toHaveBeenCalledWith('icons-ready')
  })

  it('reveals icons once the Material Symbols font finishes loading', async () => {
    const { doc, add } = fakeDoc({ load: () => Promise.resolve([]) })
    await revealIconsWhenReady(doc)
    expect(add).toHaveBeenCalledWith('icons-ready')
  })

  it('still reveals icons if the font load rejects, rather than hiding them forever', async () => {
    const { doc, add } = fakeDoc({ load: () => Promise.reject(new Error('network')) })
    await revealIconsWhenReady(doc)
    expect(add).toHaveBeenCalledWith('icons-ready')
  })

  it('does not reveal icons before the (still-pending) font load settles', () => {
    const { doc, add } = fakeDoc({ load: () => new Promise(() => {}) })
    revealIconsWhenReady(doc)
    expect(add).not.toHaveBeenCalled()
  })
})
