import { describe, expect, it } from 'vitest'
import { NAV } from '../components/SidebarNav'

describe('fixed nav (doc 01 §0 — never reshaped by tier/config/entitlement)', () => {
  it('is exactly the 9 pages in order', () => {
    const labels = NAV.flatMap(g => g.items.map(i => i.label))
    expect(labels).toEqual(['Cluster', 'Apps', 'App Store', 'Virtual Machines',
                            'Storage', 'Network', 'Backups', 'Alerts', 'Settings'])
  })
  it('groups: Overview then Infrastructure', () => {
    expect(NAV.map(g => g.label)).toEqual(['Overview', 'Infrastructure'])
  })
})
