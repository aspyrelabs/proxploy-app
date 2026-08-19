import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { ConsoleCard } from '../components/ConsoleCard'
import { CONSOLE_THEMES, readConsolePrefs } from '../lib/console-prefs'

beforeEach(() => localStorage.clear())

describe('ConsoleCard', () => {
  it('offers every theme Proxploy ships', () => {
    render(<ConsoleCard />)
    for (const t of Object.values(CONSOLE_THEMES)) {
      expect(screen.getByRole('option', { name: t.label })).toBeInTheDocument()
    }
  })

  it('persists a theme choice', () => {
    render(<ConsoleCard />)
    fireEvent.change(screen.getByLabelText(/theme/i), { target: { value: 'black' } })
    expect(readConsolePrefs().theme).toBe('black')
  })

  it('persists a font size choice', () => {
    render(<ConsoleCard />)
    fireEvent.change(screen.getByLabelText(/font size/i), { target: { value: '16' } })
    expect(readConsolePrefs().fontSize).toBe(16)
  })

  it('previews the chosen colours, so a choice is not made blind', () => {
    const { container } = render(<ConsoleCard />)
    fireEvent.change(screen.getByLabelText(/theme/i),
      { target: { value: 'solarized-light' } })
    const hex = CONSOLE_THEMES['solarized-light'].theme.background as string
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))
    // jsdom normalises hex to rgb() on serialisation (storage.test.tsx says so
    // too), hence the conversion rather than a literal.
    const preview = [...container.querySelectorAll('[style*="background"]')]
      .find((el) => (el.getAttribute('style') ?? '').includes(`rgb(${r}, ${g}, ${b})`))
    expect(preview, 'no element painted the chosen background').toBeTruthy()
  })

  it('starts from what is already stored, not from the default', () => {
    localStorage.setItem('pp_console_theme', 'solarized-dark')
    localStorage.setItem('pp_console_font_size', '18')
    render(<ConsoleCard />)
    expect((screen.getByLabelText(/theme/i) as HTMLSelectElement).value)
      .toBe('solarized-dark')
    expect((screen.getByLabelText(/font size/i) as HTMLSelectElement).value).toBe('18')
  })
})
