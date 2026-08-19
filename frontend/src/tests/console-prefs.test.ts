import { beforeEach, describe, expect, it } from 'vitest'
import {
  CONSOLE_THEMES, DEFAULT_CONSOLE_PREFS, FONT_SIZE_RANGE,
  readConsolePrefs, setConsolePrefs,
} from '../lib/console-prefs'

beforeEach(() => localStorage.clear())

describe('console preferences', () => {
  it('defaults to the console Proxploy has always drawn', () => {
    expect(readConsolePrefs()).toEqual(DEFAULT_CONSOLE_PREFS)
    expect(CONSOLE_THEMES[DEFAULT_CONSOLE_PREFS.theme].theme.background).toBe('#0a0e14')
  })

  it('round-trips a choice', () => {
    setConsolePrefs({ theme: 'solarized-light', fontSize: 16 })
    expect(readConsolePrefs()).toEqual({ theme: 'solarized-light', fontSize: 16 })
  })

  it('falls back when the stored theme is not one we ship', () => {
    // Renaming or dropping a theme id would otherwise hand xterm `undefined`
    // and paint an unreadable console, which is the failure this whole setting
    // exists to let an operator get out of.
    localStorage.setItem('pp_console_theme', 'gruvbox-that-never-shipped')
    expect(readConsolePrefs().theme).toBe(DEFAULT_CONSOLE_PREFS.theme)
  })

  it('clamps a font size rather than trusting what is in storage', () => {
    const [min, max] = FONT_SIZE_RANGE
    setConsolePrefs({ theme: 'black', fontSize: 999 })
    expect(readConsolePrefs().fontSize).toBe(max)
    localStorage.setItem('pp_console_font_size', '2')
    expect(readConsolePrefs().fontSize).toBe(min)
    localStorage.setItem('pp_console_font_size', 'not a number')
    expect(readConsolePrefs().fontSize).toBe(DEFAULT_CONSOLE_PREFS.fontSize)
  })

  it('gives every theme a label and a background to preview', () => {
    for (const [id, t] of Object.entries(CONSOLE_THEMES)) {
      expect(t.label, id).toBeTruthy()
      expect(t.theme.background, id).toMatch(/^#[0-9a-f]{6}$/i)
      expect(t.theme.foreground, id).toMatch(/^#[0-9a-f]{6}$/i)
    }
  })
})
