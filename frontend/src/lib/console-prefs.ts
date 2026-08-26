import type { ITheme } from '@xterm/xterm'

/** How the interactive console is drawn, chosen by the operator in Settings.
 *
 *  Stored per browser in localStorage, like lib/theme.ts. The node shell
 *  opens with window.open; localStorage is shared across same-origin windows,
 *  so the popup reads the choice from the main window with nothing passed to
 *  it.
 *
 *  Static log panels (components/TerminalPanel.tsx) do NOT follow this
 *  setting -- they stay dark regardless of app theme. Only the interactive
 *  console follows it.
 */

const THEME_KEY = 'pp_console_theme'
const SIZE_KEY = 'pp_console_font_size'

export const FONT_SIZE_RANGE: readonly [number, number] = [10, 20]

export type ConsoleTheme = { label: string; theme: ITheme }

/** Only the colours the terminal actually sets. Adding one is this shape
 *  again; xterm takes the object as-is. */
export const CONSOLE_THEMES: Record<string, ConsoleTheme> = {
  proxploy: {
    label: 'Proxploy dark',
    theme: {
      background: '#0a0e14', foreground: '#E8EDF4',
      red: '#F26D6D', green: '#3FCF8E', yellow: '#F5B544', blue: '#5B9DF9',
    },
  },
  black: {
    label: 'Black',
    theme: {
      background: '#000000', foreground: '#E6E6E6',
      red: '#FF5555', green: '#50FA7B', yellow: '#F1FA8C', blue: '#6272A4',
    },
  },
  'solarized-dark': {
    label: 'Solarized Dark',
    theme: {
      background: '#002b36', foreground: '#839496',
      red: '#dc322f', green: '#859900', yellow: '#b58900', blue: '#268bd2',
    },
  },
  'solarized-light': {
    label: 'Solarized Light',
    theme: {
      background: '#fdf6e3', foreground: '#657b83',
      red: '#dc322f', green: '#859900', yellow: '#b58900', blue: '#268bd2',
    },
  },
}

export type ConsolePrefs = { theme: string; fontSize: number }

export const DEFAULT_CONSOLE_PREFS: ConsolePrefs = { theme: 'proxploy', fontSize: 12.5 }

function clampSize(raw: string | null): number {
  const n = Number(raw)
  if (!raw || Number.isNaN(n)) return DEFAULT_CONSOLE_PREFS.fontSize
  const [min, max] = FONT_SIZE_RANGE
  return Math.min(max, Math.max(min, n))
}

/** Never returns a theme id we do not ship. A stored id that has since been
 *  renamed or dropped would otherwise reach xterm as `undefined` and paint an
 *  unreadable console, which is the exact state this setting exists to let
 *  someone escape from. */
export function readConsolePrefs(): ConsolePrefs {
  const stored = localStorage.getItem(THEME_KEY)
  return {
    theme: stored && stored in CONSOLE_THEMES ? stored : DEFAULT_CONSOLE_PREFS.theme,
    fontSize: clampSize(localStorage.getItem(SIZE_KEY)),
  }
}

export function setConsolePrefs(prefs: ConsolePrefs): void {
  localStorage.setItem(THEME_KEY, prefs.theme)
  localStorage.setItem(SIZE_KEY, String(prefs.fontSize))
}
