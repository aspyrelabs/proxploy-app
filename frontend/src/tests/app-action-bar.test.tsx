import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

let features: Record<string, boolean> = { 'apps.lifecycle': true, 'apps.open_ui': true }
let capabilities: Record<string, boolean> = { lifecycle: true, console: true }

vi.mock('../api/client', () => ({
  api: vi.fn((path: string) => {
    if (path === '/entitlements') {
      return Promise.resolve({ tier: 'builtin', grace: null, clock_skew: false, features })
    }
    if (path.startsWith('/hosts')) {
      return Promise.resolve([{ id: 1, name: 'pve-a', capabilities }])
    }
    return Promise.resolve(null)
  }),
  ApiError: class extends Error {},
}))

import { AppActionBar } from '../components/AppActionBar'
import type { AppRow } from '../api/hooks'

const APP: AppRow = {
  id: 1, name: 'Immich', slug: 'immich', host_id: 1, host_name: 'pve-a',
  node: 'pve-a', ctid: 150, category: null, catalog_slug: 'immich',
  icon_initials: 'IM', icon_colors: null, icon_url: null,
  web_port: null, web_protocol: 'http', web_path: '/', catalog_port: 8096,
  status: 'running', ip: '10.0.0.5', cpu_pct: 12,
  mem_bytes: 1, mem_total_bytes: 2, uptime_s: 1,
  update_available: null, adopted: false,
  disk_bytes: 1, disk_total_bytes: 2, net_in_bps: 1, net_out_bps: 1,
}

const wrap = (app: AppRow) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><AppActionBar app={app} /></QueryClientProvider>)
}

const labels = () =>
  within(screen.getByRole('group')).getAllByRole('button').map((b) => b.textContent?.trim())

describe('AppActionBar', () => {
  beforeEach(() => {
    features = { 'apps.lifecycle': true, 'apps.open_ui': true }
    capabilities = { lifecycle: true, console: true }
  })

  it('offers Stop, Restart, Web UI and Console while the app is running', () => {
    wrap(APP)
    expect(labels()).toEqual(['Stop', 'Restart', 'Web UI', 'Console'])
  })

  it('offers Start instead of Stop while it is not running', () => {
    // Never both: an app is either running or it is not, and offering the
    // pair would invite the wrong one.
    wrap({ ...APP, status: 'stopped' })
    expect(labels()).toEqual(['Start', 'Web UI', 'Console'])
  })

  it('colours Start green and Stop red, the two opposite outcomes', () => {
    wrap(APP)
    expect(screen.getByRole('button', { name: 'Stop' }).className).toContain('text-red')
    wrap({ ...APP, id: 2, status: 'stopped' })
    expect(screen.getByRole('button', { name: 'Start' }).className).toContain('text-green')
  })

  it('leaves Restart neutral, since it lands back where it started', () => {
    wrap(APP)
    const restart = screen.getByRole('button', { name: 'Restart' }).className
    expect(restart).not.toContain('text-red')
    expect(restart).not.toContain('text-green')
  })

  it('hides Web UI when there is nothing to point a tab at', () => {
    // Absent, not disabled: a dead button invites a click that cannot go
    // anywhere.
    wrap({ ...APP, catalog_port: null })
    expect(labels()).toEqual(['Stop', 'Restart', 'Console'])
  })

  it('welds the actions into one group rather than loose buttons', () => {
    wrap(APP)
    // ButtonGroup carries role="group"; the separators are decorative and add
    // nothing to the accessible tree.
    expect(screen.getByRole('group')).toBeInTheDocument()
  })
})
