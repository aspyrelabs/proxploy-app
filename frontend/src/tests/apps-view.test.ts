import { beforeEach, describe, expect, it } from 'vitest'
import { DEFAULT_APPS_VIEW, readAppsView, writeAppsView } from '../lib/apps-view'

describe('apps view persistence', () => {
  beforeEach(() => localStorage.clear())

  it('defaults to the detailed view with nothing stored', () => {
    expect(readAppsView()).toBe('detailed')
    expect(DEFAULT_APPS_VIEW).toBe('detailed')
  })

  it('round-trips a choice', () => {
    writeAppsView('icon')
    expect(readAppsView()).toBe('icon')
  })

  it('falls back rather than throwing on a value it does not recognise', () => {
    // A hand-edited localStorage value reaches the renderer directly. One that
    // is not a view mode must not be able to take the page down, which is the
    // same reason isStoreSort exists in lib/store-order.ts.
    localStorage.setItem('pp_apps_view', 'toString')
    expect(readAppsView()).toBe('detailed')
    localStorage.setItem('pp_apps_view', '{"not":"a view"}')
    expect(readAppsView()).toBe('detailed')
  })
})
