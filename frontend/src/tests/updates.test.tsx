import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const posted: { path: string; method: string; body: any }[] = []
const getPaths: string[] = []
let app: any = null
let updateInfo: any = null
let features: Record<string, boolean> = {
  'store.updates': true, 'store.update': true, 'store.update_all': true,
}

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  api: vi.fn((path: string, opts?: RequestInit) => {
    const method = (opts?.method ?? 'GET').toUpperCase()
    if (method !== 'GET') {
      posted.push({ path, method, body: opts?.body ? JSON.parse(String(opts.body)) : null })
      if (path === '/apps/update-all') return Promise.resolve({ jobs: [{ id: 1 }], skipped: [] })
      return Promise.resolve({ job: { id: 1, kind: 'app.update' } })
    }
    getPaths.push(path)
    if (path.endsWith('/update')) return Promise.resolve(updateInfo)
    if (path.startsWith('/apps/')) return Promise.resolve(app)
    if (path === '/entitlements') return Promise.resolve({ tier: 'builtin', features, grace: null, clock_skew: false })
    return Promise.resolve([])
  }),
}))

import { UpdatePanel } from '../routes/apps'
import { UpdateAllButton } from '../components/UpdateAllButton'

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: {
    queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('UpdatePanel', () => {
  it('says up to date when nothing is pending', async () => {
    posted.length = 0
    app = { id: 1, name: 'Redis', update_available: null }
    updateInfo = { update_available: null, from_ref: 'a'.repeat(40),
                   to_ref: 'a'.repeat(40), diff_vs_upstream: null }
    wrap(<UpdatePanel appId={1} app={app} />)
    await waitFor(() => expect(screen.getByText(/up to date/i)).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /update to/i })).toBeNull()
  })

  it('offers "Update to <sha>" when one is available', async () => {
    posted.length = 0
    app = { id: 1, name: 'Redis', update_available: 'b'.repeat(7) }
    updateInfo = { update_available: 'b'.repeat(7), from_ref: 'a'.repeat(40),
                   to_ref: 'b'.repeat(40), diff_vs_upstream: '--- upstream\n+++ pinned\n' }
    wrap(<UpdatePanel appId={1} app={app} />)
    await waitFor(() => expect(
      screen.getByRole('button', { name: new RegExp(`update to ${'b'.repeat(7)}`, 'i') })
    ).toBeInTheDocument())
  })

  it('requires the root-consent checkbox before it will post', async () => {
    posted.length = 0
    app = { id: 1, name: 'Redis', update_available: 'b'.repeat(7) }
    updateInfo = { update_available: 'b'.repeat(7), from_ref: 'a'.repeat(40),
                   to_ref: 'b'.repeat(40), diff_vs_upstream: null }
    wrap(<UpdatePanel appId={1} app={app} />)
    const btn = await screen.findByRole('button', { name: /update to/i })
    expect(btn).toBeDisabled()
    fireEvent.click(screen.getByLabelText(/runs as root/i))
    await waitFor(() => expect(btn).not.toBeDisabled())
    fireEvent.click(btn)
    await waitFor(() => expect(posted.length).toBe(1))
    expect(posted[0]).toMatchObject({ path: '/apps/1/update', method: 'POST',
                                      body: { consent: true } })
  })

  it('shows the upstream diff so the operator sees what will run', async () => {
    posted.length = 0
    app = { id: 1, name: 'Redis', update_available: 'b'.repeat(7) }
    updateInfo = { update_available: 'b'.repeat(7), from_ref: 'a'.repeat(40),
                   to_ref: 'b'.repeat(40),
                   diff_vs_upstream: '--- upstream\n+++ pinned\n-old\n+new\n' }
    wrap(<UpdatePanel appId={1} app={app} />)
    await waitFor(() => expect(screen.getByText(/\+new/)).toBeInTheDocument())
  })

  it('does not fetch update info or offer the button without store.updates', async () => {
    getPaths.length = 0
    app = { id: 1, name: 'Redis', update_available: 'b'.repeat(7) }
    updateInfo = { update_available: 'b'.repeat(7), from_ref: 'a'.repeat(40),
                   to_ref: 'b'.repeat(40), diff_vs_upstream: null }
    features = { 'store.updates': false, 'store.update': false, 'store.update_all': false }
    wrap(<UpdatePanel appId={1} app={app} />)
    await waitFor(() => expect(screen.getByText(/not included in your plan/i)).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /update to/i })).toBeNull()
    expect(getPaths.some((p) => p.endsWith('/update'))).toBe(false)
    features = { 'store.updates': true, 'store.update': true, 'store.update_all': true }
  })
})

describe('UpdateAllButton', () => {
  it('posts update-all with consent after confirming', async () => {
    posted.length = 0
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    wrap(<UpdateAllButton />)
    const btn = screen.getByRole('button', { name: /update all/i })
    await waitFor(() => expect(btn).not.toBeDisabled())
    fireEvent.click(btn)
    await waitFor(() => expect(posted.length).toBe(1))
    expect(posted[0]).toMatchObject({ path: '/apps/update-all', method: 'POST',
                                      body: { consent: true } })
  })

  it('posts nothing when the confirm is dismissed', async () => {
    posted.length = 0
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    wrap(<UpdateAllButton />)
    const btn = screen.getByRole('button', { name: /update all/i })
    await waitFor(() => expect(btn).not.toBeDisabled())
    fireEvent.click(btn)
    await new Promise((r) => setTimeout(r, 0))
    expect(posted.length).toBe(0)
  })
})
