const STORAGE_KEY = 'pp_theme'

/** Reads the stored theme (defaulting to dark) and stamps it onto <html>. Must
 * run before the app shell mounts so every route, including /login, honours
 * the user's choice instead of index.html's static data-theme="dark". */
export function applyStoredTheme(): string {
  const theme = localStorage.getItem(STORAGE_KEY) ?? 'dark'
  document.documentElement.dataset.theme = theme
  return theme
}

export function setStoredTheme(theme: string): void {
  document.documentElement.dataset.theme = theme
  localStorage.setItem(STORAGE_KEY, theme)
}
