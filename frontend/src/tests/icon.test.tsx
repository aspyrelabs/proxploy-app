import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Icon } from '../components/ui/icon'
import { MATERIAL_SYMBOLS_CODEPOINTS } from '../lib/material-symbols-codepoints.mjs'

/**
 * The Icon component is the one place that turns a Material Symbols name
 * into markup. It renders the glyph's Private Use Area codepoint (see
 * lib/material-symbols-codepoints.ts for why: the font's ligature names
 * subset to megabytes, the codepoints subset to kilobytes), not the name
 * itself as literal text -- but the DOM still carries a text node either
 * way, and a screen reader has no defined pronunciation for a PUA
 * character, so every consumer MUST still be aria-hidden by default. This
 * file pins that contract, plus the sizing contract (font-size, not
 * Tailwind width/height classes) and the data-icon introspection hook
 * tooling (and src/tests/icon-subset.test.tsx) reads the logical name from.
 */
describe('Icon', () => {
  it('renders the codepoint for the given name as the text content', () => {
    const { container } = render(<Icon name="settings" />)
    expect(container.textContent).toBe(String.fromCodePoint(MATERIAL_SYMBOLS_CODEPOINTS.settings))
  })

  it('exposes the logical name via data-icon, for tooling that needs it', () => {
    const { container } = render(<Icon name="settings" />)
    expect(container.firstElementChild?.getAttribute('data-icon')).toBe('settings')
  })

  it('carries the material-symbols-outlined class that binds the font', () => {
    const { container } = render(<Icon name="settings" />)
    expect(container.querySelector('.material-symbols-outlined')).not.toBeNull()
  })

  it('is aria-hidden by default, so it never gets announced beside a label', () => {
    const { container } = render(<Icon name="settings" />)
    expect(container.firstElementChild?.getAttribute('aria-hidden')).toBe('true')
  })

  it('defaults to an 18px box, matching the Heroicons size it replaces', () => {
    const { container } = render(<Icon name="settings" />)
    const el = container.firstElementChild as HTMLElement
    expect(el.style.fontSize).toBe('18px')
    expect(el.style.width).toBe('18px')
    expect(el.style.height).toBe('18px')
  })

  it('sizes by a single size prop, not by Tailwind width/height classes', () => {
    const { container } = render(<Icon name="refresh" size={20} />)
    const el = container.firstElementChild as HTMLElement
    expect(el.style.fontSize).toBe('20px')
    expect(el.style.width).toBe('20px')
    expect(el.style.height).toBe('20px')
  })

  it('accepts extra classes for a caller to layer on, e.g. animate-spin', () => {
    const { container } = render(<Icon name="refresh" className="animate-spin" />)
    expect(container.firstElementChild?.className).toContain('animate-spin')
  })

  it('throws in dev for a name with no codepoint mapping, rather than rendering nothing', () => {
    expect(() => render(<Icon name="not_a_real_icon" />)).toThrow(/not_a_real_icon/)
  })
})
