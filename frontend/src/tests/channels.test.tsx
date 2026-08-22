import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const posted: { path: string; body: any }[] = []
let failNext: { status: number; detail: string } | null = null

const KINDS = [
  { kind: 'ntfy', label: 'ntfy', setup_url: 'https://appriseit.com/services/ntfy/',
    fields: [
      { key: 'host', label: 'Server', required: true, secret: false,
        placeholder: '', default: 'ntfy.sh', help: 'Leave as ntfy.sh unless you run your own.' },
      { key: 'topic', label: 'Topic', required: true, secret: false,
        placeholder: 'proxploy-alerts', default: '', help: '' },
    ] },
  { kind: 'telegram', label: 'Telegram', setup_url: 'https://appriseit.com/services/telegram/',
    fields: [
      { key: 'bot_token', label: 'Bot token', required: true, secret: true,
        placeholder: '', default: '', help: 'What BotFather gave you.' },
      { key: 'chat_id', label: 'Chat ID', required: true, secret: false,
        placeholder: '123456789', default: '', help: '' },
    ] },
]

vi.mock('../api/client', () => {
  // Declared inside the factory: vi.mock is hoisted above the imports, so a
  // class referenced from the returned object literal would be in its TDZ.
  class ApiError extends Error {
    status: number
    detail: string
    constructor(status: number, detail: string) {
      super(detail)
      this.status = status
      this.detail = detail
    }
  }
  return {
  ApiError,
  api: vi.fn((path: string, opts?: RequestInit) => {
    if (path === '/entitlements') {
      return Promise.resolve({
        tier: 'builtin',
        features: { 'notify.channels': true, 'notify.routing': true },
        grace: null, clock_skew: false,
      })
    }
    if (path === '/notifications/kinds') return Promise.resolve(KINDS)
    posted.push({ path, body: opts?.body ? JSON.parse(String(opts.body)) : null })
    if (failNext) {
      const e = new ApiError(failNext.status, failNext.detail)
      failNext = null
      return Promise.reject(e)
    }
    return Promise.resolve({ id: 2, name: 'x', kind: 'telegram', events: [],
                             enabled: true, last_notified_at: null })
  }),
  }
})

import { ChannelForm } from '../components/ChannelForm'

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('ChannelForm', () => {
  beforeEach(() => { posted.length = 0; failNext = null })

  /** The form used to ask for a name and an Apprise URL, so adding Telegram
   *  meant already knowing it is tgram://bottoken/ChatID. */
  it('offers the services by name and asks that service its own questions', async () => {
    wrap(<ChannelForm onSaved={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Telegram' }))
    expect(await screen.findByLabelText('Bot token')).toHaveAttribute('type', 'password')
    expect(screen.getByLabelText('Chat ID')).toBeInTheDocument()
    expect(screen.queryByLabelText(/apprise url/i)).not.toBeInTheDocument()
  })

  it('prefills a field that ships with a default', async () => {
    wrap(<ChannelForm onSaved={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'ntfy' }))
    expect(await screen.findByLabelText('Server')).toHaveValue('ntfy.sh')
  })

  it('posts the fields, never an assembled URL', async () => {
    wrap(<ChannelForm onSaved={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Telegram' }))
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Bot' } })
    fireEvent.change(await screen.findByLabelText('Bot token'), { target: { value: '123:abc' } })
    fireEvent.change(screen.getByLabelText('Chat ID'), { target: { value: '42' } })
    fireEvent.click(screen.getByRole('button', { name: /add channel/i }))
    await waitFor(() => expect(posted).toHaveLength(1))
    expect(posted[0].body).toEqual({
      name: 'Bot', kind: 'telegram',
      fields: { bot_token: '123:abc', chat_id: '42' }, events: [],
    })
    expect(posted[0].body.url).toBeUndefined()
  })

  it('keeps a paste-a-URL escape hatch for services we do not list', async () => {
    wrap(<ChannelForm onSaved={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: /paste a url/i }))
    const url = await screen.findByLabelText(/apprise url/i)
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Raw' } })
    fireEvent.change(url, { target: { value: 'sinch://a/b/c/+15551234567' } })
    fireEvent.click(screen.getByRole('button', { name: /add channel/i }))
    await waitFor(() => expect(posted).toHaveLength(1))
    expect(posted[0].body).toEqual({
      name: 'Raw', url: 'sinch://a/b/c/+15551234567', events: [],
    })
  })

  it('shows what the server said when the details are not sendable', async () => {
    // The 422 body from _resolve_url names the field, so surface it verbatim
    // rather than replacing it with "Could not add that channel".
    failNext = { status: 422, detail: 'Topic is required for ntfy.' }
    wrap(<ChannelForm onSaved={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'ntfy' }))
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'n' } })
    fireEvent.change(await screen.findByLabelText('Topic'), { target: { value: 'x' } })
    fireEvent.click(screen.getByRole('button', { name: /add channel/i }))
    expect(await screen.findByText('Topic is required for ntfy.')).toBeInTheDocument()
  })

  it('does not offer the dead app.updated event any more', async () => {
    // It was tickable for the life of the old form and no backend code ever
    // emitted it. Routing now lives in the Events matrix entirely.
    wrap(<ChannelForm onSaved={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'ntfy' }))
    expect(screen.queryByLabelText('app.updated')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('job.failed')).not.toBeInTheDocument()
  })

  it('lets you go back and pick a different service', async () => {
    wrap(<ChannelForm onSaved={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Telegram' }))
    fireEvent.click(await screen.findByRole('button', { name: /back/i }))
    expect(await screen.findByRole('button', { name: 'ntfy' })).toBeInTheDocument()
  })
})
