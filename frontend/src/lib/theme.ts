const STORAGE_KEY = 'pp_theme'

/** What the operating system asks for. Defaults to dark when the browser
 *  cannot say (jsdom has no matchMedia), which keeps the old behaviour as the
 *  fallback rather than as the rule. */
export function systemTheme(): 'dark' | 'light' {
  return window.matchMedia?.('(prefers-color-scheme: light)').matches
    ? 'light'
    : 'dark'
}

/** Reads the stored theme and stamps it onto <html>. Must run before the app
 * shell mounts so every route, including /login, honours the user's choice
 * instead of index.html's static data-theme.
 *
 * With nothing stored, the system preference decides. It used to be a flat
 * default of dark, so someone whose machine is in light mode was handed a dark
 * app and had to go and find the toggle. An explicit choice still wins over
 * the system for as long as it is stored, because someone who reached for the
 * toggle meant it. */
export function applyStoredTheme(): string {
  const theme = localStorage.getItem(STORAGE_KEY) ?? systemTheme()
  document.documentElement.dataset.theme = theme
  return theme
}

export function setStoredTheme(theme: string): void {
  document.documentElement.dataset.theme = theme
  localStorage.setItem(STORAGE_KEY, theme)
}
