const STORAGE_KEY = 'pp_theme'

/** Point the tab icon at the mark for `theme`.
 *
 *  The pair is named by THEME not ink: -dark is the near-white mark for a dark
 *  tab strip. index.html scopes the icons to prefers-color-scheme (the OS),
 *  which is all a browser shows until JS runs; this overrides that to follow
 *  the app's own toggle. Known cost, accepted: dark OS + light app puts a dark
 *  mark on a dark strip, hard to see — the toggle the operator just touched
 *  wins.
 *
 *  Every existing icon link is REMOVED first and one added. In Chromium a
 *  second icon link is fetched alongside the first and wins wherever it sits,
 *  so leaving one beside the new mark made an earlier attempt look inert; the
 *  remove-then-add is also what makes Chrome notice at all. */
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

/** OS preference; defaults to dark when the browser can't say (jsdom has no
 *  matchMedia), preserving the old fallback. */
export function systemTheme(): 'dark' | 'light' {
  return window.matchMedia?.('(prefers-color-scheme: light)').matches
    ? 'light'
    : 'dark'
}

/** Reads the stored theme and stamps it onto <html>. Must run before the app
 *  shell mounts so every route (including /login) honours the choice instead
 *  of index.html's static data-theme.
 *
 *  With nothing stored, the system preference decides; an explicit choice wins
 *  over the system for as long as it is stored. */
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
