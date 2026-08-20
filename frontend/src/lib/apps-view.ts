import { useCallback, useState } from 'react'

/**
 * Which of the three presentations the Apps section draws.
 *
 * Stored per browser in localStorage, the same way lib/console-prefs.ts
 * stores the console theme and font size. A view mode is a per-operator
 * habit, not a per-visit one: someone who wants the dense icon grid wants it
 * every time they open the page, and re-choosing it on every navigation is
 * the kind of small friction that makes the other two views not worth having.
 */
const KEY = 'pp_apps_view'

export const APPS_VIEWS = {
  detailed: { label: 'Detailed view', icon: 'grid_view' },
  list: { label: 'List view', icon: 'view_list' },
  icon: { label: 'Icon view', icon: 'apps' },
} as const

export type AppsView = keyof typeof APPS_VIEWS

export const DEFAULT_APPS_VIEW: AppsView = 'detailed'

/** Own keys only. `'toString' in APPS_VIEWS` is true, because `in` walks the
 *  prototype chain, so the obvious version of this accepts a stored
 *  "toString" and hands the renderer a key the table does not have. A
 *  hand-edited localStorage value must not be able to do that; same guard as
 *  isStoreSort in lib/store-order.ts. */
export function isAppsView(v: unknown): v is AppsView {
  return typeof v === 'string' && Object.hasOwn(APPS_VIEWS, v)
}

export function readAppsView(): AppsView {
  try {
    const v = localStorage.getItem(KEY)
    return isAppsView(v) ? v : DEFAULT_APPS_VIEW
  } catch {
    // Private-mode Safari throws on localStorage access rather than returning
    // null. A view mode is not worth a blank page.
    return DEFAULT_APPS_VIEW
  }
}

export function writeAppsView(view: AppsView): void {
  try { localStorage.setItem(KEY, view) } catch { /* see readAppsView */ }
}

export function useAppsView(): [AppsView, (v: AppsView) => void] {
  const [view, setView] = useState<AppsView>(readAppsView)
  const choose = useCallback((v: AppsView) => { writeAppsView(v); setView(v) }, [])
  return [view, choose]
}
