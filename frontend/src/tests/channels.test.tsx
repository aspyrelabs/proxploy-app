import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const posted: { path: string; body: any }[] = []

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  api: vi.fn((path: string, opts?: RequestInit) => {
    if (path === '/entitlements') {
      return Promise.resolve({
        tier: 'builtin',
        features: { 'notify.channels': true, 'notify.routing': true },
        grace: null, clock_skew: false,
      })
    }
    if (path === '/notifications/channels' && !opts?.method) {
      return Promise.resolve([
        { id: 1, name: 'Home ntfy', kind: 'ntfy', events: ['job.failed'],
          enabled: true, last_notified_at: null },
      ])
    }
    posted.push({ path, body: opts?.body ? JSON.parse(String(opts.body)) : null })
    if (path.endsWith('/test')) return Promise.resolve({ sent: true })
    return Promise.resolve({ id: 2, name: 'x', kind: 'ntfy', events: [], enabled: true,
                             last_notified_at: null })
  }),
}))

import { ChannelForm } from '../components/ChannelForm'

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('ChannelForm', () => {
  it('defaults the event selection to job.failed', () => {
    posted.length = 0
    wrap(<ChannelForm onSaved={() => {}} />)
    expect((screen.getByLabelText('job.failed') as HTMLInputElement).checked).toBe(true)
    expect((screen.getByLabelText('job.succeeded') as HTMLInputElement).checked).toBe(false)
  })

  it('posts name, url and the selected events', async () => {
    posted.length = 0
    wrap(<ChannelForm onSaved={() => {}} />)
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: 'Home ntfy' } })
    fireEvent.change(screen.getByLabelText(/apprise url/i),
      { target: { value: 'ntfy://ntfy.sh/proxploy' } })
    fireEvent.click(screen.getByRole('button', { name: /add channel/i }))
    await waitFor(() => expect(posted.length).toBe(1))
    expect(posted[0].path).toBe('/notifications/channels')
    expect(posted[0].body).toEqual({
      name: 'Home ntfy', url: 'ntfy://ntfy.sh/proxploy', events: ['job.failed'],
    })
  })

  it('never echoes the url back into the DOM after save', async () => {
    posted.length = 0
    wrap(<ChannelForm onSaved={() => {}} />)
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: 'n' } })
    fireEvent.change(screen.getByLabelText(/apprise url/i),
      { target: { value: 'ntfy://secret-token@host/t' } })
    fireEvent.click(screen.getByRole('button', { name: /add channel/i }))
    await waitFor(() => expect(posted.length).toBe(1))
    await waitFor(() =>
      expect((screen.getByLabelText(/apprise url/i) as HTMLInputElement).value).toBe(''))
  })
})
