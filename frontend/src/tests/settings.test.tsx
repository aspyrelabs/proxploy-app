import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const calls: { path: string; method?: string; body: unknown }[] = []
let notifyChannels = true

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  api: vi.fn((path: string, opts?: RequestInit) => {
    if (path === '/entitlements') {
      return Promise.resolve({
        tier: 'builtin', features: { 'notify.channels': notifyChannels }, grace: null,
      })
    }
    if (path === '/hosts') return Promise.resolve([])
    if (path === '/notifications/channels' && !opts?.method) {
      return Promise.resolve([
        { id: 1, name: 'Home ntfy', kind: 'ntfy', events: ['job.failed'],
          enabled: true, last_notified_at: null },
      ])
    }
    calls.push({ path, method: opts?.method, body: opts?.body ? JSON.parse(String(opts.body)) : null })
    if (path.endsWith('/test')) return Promise.resolve({ sent: true })
    if (opts?.method === 'DELETE') return Promise.resolve(null)
    return Promise.resolve({ id: 1, name: 'Home ntfy', kind: 'ntfy', events: ['job.failed'],
                             enabled: false, last_notified_at: null })
  }),
}))

vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ children }: { children?: unknown }) => <a>{children as never}</a>,
  useNavigate: () => () => {},
  useSearch: () => ({}),
}))

import { SettingsPage } from '../routes/settings'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}><SettingsPage /></QueryClientProvider>)
}

describe('SettingsPage — notification channels', () => {
  beforeEach(() => { calls.length = 0; notifyChannels = true })

  it('asks for confirmation before deleting a channel, and skips the call on cancel', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Remove' }))
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('Home ntfy'))
    await new Promise((r) => setTimeout(r, 10))
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
  })

  it('deletes the channel once the confirmation is accepted', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Remove' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE')).toBe(true))
  })

  it('toggles enabled/disabled via PATCH', async () => {
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Disable' }))
    await waitFor(() => expect(calls.some((c) =>
      c.method === 'PATCH' && c.path === '/notifications/channels/1'
      && JSON.stringify(c.body) === JSON.stringify({ enabled: false }))).toBe(true))
  })

  it('gates the Notifications card behind notify.channels: no fetch, no Add channel, when the plan lacks it', async () => {
    notifyChannels = false
    wrap()
    expect(await screen.findByText('Not included in your plan.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add channel' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Remove' })).toBeNull()
    expect(calls.some((c) => c.path === '/notifications/channels')).toBe(false)
  })
})

afterEach(() => vi.restoreAllMocks())
