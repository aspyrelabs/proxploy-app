const STORAGE_KEY = 'pp_sidebar'

/** Defaults to expanded: a first-time user should see labels before being
 *  asked to recognise ten icons cold. */
export function readSidebarCollapsed(): boolean {
  return localStorage.getItem(STORAGE_KEY) === 'collapsed'
}

export function setSidebarCollapsed(collapsed: boolean): void {
  localStorage.setItem(STORAGE_KEY, collapsed ? 'collapsed' : 'expanded')
}
