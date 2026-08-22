import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const posted: { path: string; body: any }[] = []
let failNext: { status: number; detail: string } | null = null

const KINDS = [
  { kind: 'ntfy', label: 'ntfy', setup_url: 'https://appriseit.com/services/ntfy/',
    fields: [
      { key: 'host', label: 'Server', required: true, secret: false,
        placeholder: '', default: 'ntfy.sh', help: 'Leave as ntfy.sh unless you run your own.',
        pattern: '^[A-Za-z0-9][A-Za-z0-9.\\-]*(:\\d{1,5})?$',
        hint: 'A hostname or address, optionally with :port. No scheme, no path.' },
      { key: 'topic', label: 'Topic', required: true, secret: false,
        placeholder: 'proxploy-alerts', default: '', help: '',
        pattern: '^[A-Za-z0-9_-]{1,64}$',
        hint: 'Letters, numbers, dashes and underscores, up to 64 characters.' },
    ] },
  { kind: 'telegram', label: 'Telegram', setup_url: 'https://appriseit.com/services/telegram/',
    fields: [
      { key: 'bot_token', label: 'Bot token', required: true, secret: true,
        placeholder: '', default: '', help: 'What BotFather gave you.',
        pattern: '^[0-9]+:[A-Za-z0-9_-]+$',
        hint: 'Digits, a colon, then the key, exactly as BotFather sent it.' },
      { key: 'chat_id', label: 'Chat ID', required: true, secret: false,
        placeholder: '123456789', default: '', help: '',
        pattern: '^(-?[0-9]+|@[A-Za-z0-9_]+)$', hint: 'A numeric id, or @channelname.' },
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

  it('offers services and nothing else, no raw URL tile among them', async () => {
    // "Paste a URL" sat in a row of real service names and named an
    // implementation detail rather than anything an operator wants. The
    // POST /channels url path still exists for the API and for rows created
    // before this, it is just not a thing the picker offers.
    wrap(<ChannelForm onSaved={() => {}} />)
    await screen.findByRole('button', { name: 'ntfy' })
    expect(screen.queryByRole('button', { name: /paste a url/i })).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/apprise url/i)).not.toBeInTheDocument()
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


describe('field rules', () => {
  beforeEach(() => { posted.length = 0; failNext = null })

  it('says what is wrong before you can submit, not after', async () => {
    wrap(<ChannelForm onSaved={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'ntfy' }))
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'n' } })
    fireEvent.change(await screen.findByLabelText('Topic'),
                     { target: { value: 'NOT A TOPIC!!' } })
    expect(await screen.findByText(
      'Letters, numbers, dashes and underscores, up to 64 characters.'))
      .toBeInTheDocument()
    expect(screen.getByRole('button', { name: /add channel/i })).toBeDisabled()
    expect(posted).toHaveLength(0)
  })

  it('clears the complaint once the value is right', async () => {
    wrap(<ChannelForm onSaved={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'ntfy' }))
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'n' } })
    const topic = await screen.findByLabelText('Topic')
    fireEvent.change(topic, { target: { value: 'bad topic' } })
    await screen.findByText(/up to 64 characters/)
    fireEvent.change(topic, { target: { value: 'good-topic' } })
    await waitFor(() =>
      expect(screen.queryByText(/up to 64 characters/)).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: /add channel/i })).toBeEnabled()
  })

  it('does not complain about an empty optional field', async () => {
    wrap(<ChannelForm onSaved={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Telegram' }))
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'n' } })
    expect(screen.queryByText(/BotFather sent it/)).not.toBeInTheDocument()
  })

  it('marks the offending field for a screen reader, not just visually', async () => {
    wrap(<ChannelForm onSaved={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'ntfy' }))
    const topic = await screen.findByLabelText('Topic')
    fireEvent.change(topic, { target: { value: '!!' } })
    await waitFor(() => expect(topic).toHaveAttribute('aria-invalid', 'true'))
  })

  it('shows a skeleton while the services are still loading, not an empty box', () => {
    wrap(<ChannelForm onSaved={() => {}} />)
    expect(screen.getByRole('status', { name: /loading/i })).toBeInTheDocument()
  })
})

describe('credentials for the wrong service', () => {
  beforeEach(() => { posted.length = 0; failNext = null })

  it('refuses a Slack webhook pasted into a Telegram bot token', async () => {
    // It satisfies plenty of token rules on length alone, which is exactly
    // why the URL check runs before the field's own pattern.
    wrap(<ChannelForm onSaved={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Telegram' }))
    fireEvent.change(await screen.findByLabelText('Bot token'),
      { target: { value: 'https://hooks.slack.com/services/T0/B0/abcdefghijkl' } })
    expect(await screen.findByText(/not a whole URL/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /add channel/i })).toBeDisabled()
  })

  it('refuses an Apprise URL for another service just the same', async () => {
    wrap(<ChannelForm onSaved={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'ntfy' }))
    fireEvent.change(await screen.findByLabelText('Topic'),
      { target: { value: 'slack://TokenA/TokenB/TokenC' } })
    expect(await screen.findByText(/not a whole URL/)).toBeInTheDocument()
  })

  it('says to add that service rather than leaving you stuck', async () => {
    wrap(<ChannelForm onSaved={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'ntfy' }))
    fireEvent.change(await screen.findByLabelText('Server'),
      { target: { value: 'https://ntfy.sh' } })
    expect(await screen.findByText(/add that service instead/)).toBeInTheDocument()
  })
})
