import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Icon } from '../components/ui/icon'

/**
 * The Icon component is the one place that turns a Material Symbols name
 * into markup. The font now loads from the Google Fonts CDN as a ligature
 * font: typing the name ("settings") as literal text is what makes the
 * glyph appear, so the DOM text node IS the readable word, not a decoded
 * Private Use Area character. A screen reader has no reason to stay quiet
 * about a real word, though -- so every instance still needs aria-hidden,
 * now for a more ordinary reason: the label sitting next to the icon is
 * already the accessible name, and a screen reader reading "settings"
 * out loud beside "Settings" would announce it twice. This file pins that
 * contract, plus the sizing contract (font-size, not Tailwind width/height
 * classes).
 */
describe('Icon', () => {
  it('renders the name as its text content', () => {
    const { container } = render(<Icon name="settings" />)
    expect(container.textContent).toBe('settings')
  })

  it('is aria-hidden by default, so it never gets announced beside a label', () => {
    const { container } = render(<Icon name="settings" />)
    expect(container.firstElementChild?.getAttribute('aria-hidden')).toBe('true')
  })

  it('carries the material-symbols-outlined class that binds the font', () => {
    const { container } = render(<Icon name="settings" />)
    expect(container.querySelector('.material-symbols-outlined')).not.toBeNull()
  })

  it('defaults to an 18px box, matching the Heroicons size it replaced', () => {
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
})
