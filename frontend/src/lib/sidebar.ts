const STORAGE_KEY = 'pp_sidebar'

/** Whether the sidebar is collapsed to its icon rail. Defaults to expanded:
 *  a first-time user should see the labels before being asked to recognise
 *  ten icons cold. */
export function readSidebarCollapsed(): boolean {
  return localStorage.getItem(STORAGE_KEY) === 'collapsed'
}

export function setSidebarCollapsed(collapsed: boolean): void {
  localStorage.setItem(STORAGE_KEY, collapsed ? 'collapsed' : 'expanded')
}
