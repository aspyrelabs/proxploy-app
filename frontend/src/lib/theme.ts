const STORAGE_KEY = 'pp_theme'

/** Point the tab icon at the mark for `theme`.
 *
 * The favicon pair is named by THEME, not by ink (Logo.tsx explains why the
 * lockup pair is named the other way round): -dark is the near-white mark that
 * belongs on a dark tab strip.
 *
 * index.html declares the two icons scoped to prefers-color-scheme, which is
 * what a browser shows before this module loads and all it ever shows with
 * JavaScript off. That follows the OPERATING SYSTEM. This function then
 * overrides it to follow the app's own toggle, because someone who switches
 * the app to light and watches the mark in the tab stay put reads it as
 * broken, which is exactly how it was reported.
 *
 * The known cost, accepted deliberately: with a dark OS and a light app, a
 * dark-inked mark now sits on a dark tab strip and is hard to see. The toggle
 * is the thing the operator just touched, so it wins.
 *
 * Every existing icon link is REMOVED first and one is added. Anything left
 * beside it competes: measured in a real Chromium, a second icon link is
 * fetched alongside the first and wins in both schemes wherever it sits, which
 * is what made the earlier attempt at this look like it had done nothing.
 * Removing and re-adding rather than editing `href` in place is also what
 * makes Chrome notice at all.
 */
export function applyFavicon(theme: string): void {
  const href = theme === 'light'
    ? '/proxploy-favicon-light.svg'
    : '/proxploy-favicon-dark.svg'
  document.querySelectorAll('link[rel~="icon"]').forEach((l) => l.remove())
  const link = document.createElement('link')
  link.rel = 'icon'
  link.type = 'image/svg+xml'
  link.href = href
  document.head.appendChild(link)
}

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
  applyFavicon(theme)
  return theme
}

export function setStoredTheme(theme: string): void {
  document.documentElement.dataset.theme = theme
  applyFavicon(theme)
  localStorage.setItem(STORAGE_KEY, theme)
}
