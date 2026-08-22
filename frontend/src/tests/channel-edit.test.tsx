/**
 * Editing a channel, which had no UI at all: the backend PATCH has always
 * taken a name and a URL, and the card only ever offered Disable, Test and
 * Remove. Rotating a bot token meant deleting the channel and adding it back,
 * which loses its column in the Events matrix and everything ticked in it.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const sent: { path: string; method?: string; body: any }[] = []

// What the channel already had. Secret VALUES are never in this payload; the
// server names the keys that have one so the form can say "leave blank to
// keep" instead of showing dots it could not honour.
let SAVED: any = { kind: 'ntfy', known: true,
                   fields: { host: 'ntfy.sh', topic: 'saved-topic' },
                   secrets_set: [] }

const KINDS = [
  { kind: 'ntfy', label: 'ntfy', setup_url: '', fields: [
    { key: 'host', label: 'Server', required: true, secret: false,
      placeholder: '', default: 'ntfy.sh', help: '', example: 'ntfy.sh',
      pattern: '^[A-Za-z0-9][A-Za-z0-9.\\-]*(:\\d{1,5})?$', hint: 'A hostname.' },
    { key: 'topic', label: 'Topic', required: true, secret: false,
      placeholder: '', default: '', help: '', example: 'proxploy-alerts',
      pattern: '^[A-Za-z0-9_-]{1,64}$', hint: 'Letters, numbers, dashes.' },
  ] },
  { kind: 'gotify', label: 'Gotify', setup_url: '', fields: [
    { key: 'host', label: 'Server', required: true, secret: false,
      placeholder: '', default: '', help: '', pattern: '', hint: '', example: 'gotify.example.com' },
    { key: 'token', label: 'App token', required: true, secret: true,
      placeholder: '', default: '', help: '', example: 'AwQ1nT9zLPmExampleKey',
      pattern: '^[A-Za-z0-9._-]{8,}$', hint: 'At least 8 characters.' },
  ] },
]

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  api: vi.fn((path: string, opts?: RequestInit) => {
    if (path === '/notifications/kinds') return Promise.resolve(KINDS)
    if (path === '/notifications/channels/4/fields') return Promise.resolve(SAVED)
    sent.push({ path, method: opts?.method,
                body: opts?.body ? JSON.parse(String(opts.body)) : null })
    return Promise.resolve({})
  }),
}))

import { ChannelEditForm } from '../components/ChannelEditForm'

const CHANNEL = { id: 4, name: 'Home ntfy', kind: 'ntfy', events: ['job.failed'],
                  enabled: true, last_notified_at: null }

const wrap = (channel = CHANNEL, onSaved = () => {}, onCancel = () => {}) => {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <ChannelEditForm channel={channel} onSaved={onSaved} onCancel={onCancel} />
    </QueryClientProvider>)
}

describe('ChannelEditForm', () => {
  beforeEach(() => {
    sent.length = 0
    SAVED = { kind: 'ntfy', known: true,
              fields: { host: 'ntfy.sh', topic: 'saved-topic' }, secrets_set: [] }
  })

  it('prefills the name, because a name is not a secret', () => {
    wrap()
    expect(screen.getByLabelText('Name')).toHaveValue('Home ntfy')
  })

  it('does not open on the fields, and says what replacing will and will not keep', async () => {
    wrap()
    expect(await screen.findByText(/anything secret stays as it is/i)).toBeInTheDocument()
    expect(screen.queryByLabelText('Topic')).not.toBeInTheDocument()
  })

  it('a rename sends only the name, so the stored credential is untouched', async () => {
    wrap()
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Renamed' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(sent).toHaveLength(1))
    expect(sent[0].method).toBe('PATCH')
    expect(sent[0].path).toBe('/notifications/channels/4')
    expect(sent[0].body).toEqual({ name: 'Renamed' })
  })

  it('prefills what it already had, so one wrong value is one field to fix', async () => {
    wrap()
    fireEvent.click(screen.getByRole('button', { name: /replace credentials/i }))
    expect(await screen.findByLabelText('Topic')).toHaveValue('saved-topic')
    expect(screen.getByLabelText('Server')).toHaveValue('ntfy.sh')
  })

  it('leaves a stored secret blank and says blank means keep it', async () => {
    SAVED = { kind: 'gotify', known: true,
              fields: { host: 'gotify.example.com' }, secrets_set: ['token'] }
    wrap({ ...CHANNEL, kind: 'gotify' })
    fireEvent.click(screen.getByRole('button', { name: /replace credentials/i }))
    const token = await screen.findByLabelText('App token')
    expect(token).toHaveValue('')
    expect(token).toHaveAttribute('placeholder', 'Leave blank to keep the saved one')
    // And Save is not held hostage by a required box that is deliberately empty.
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled()
  })

  it('says so plainly when the channel predates the saved details', async () => {
    SAVED = { kind: 'ntfy', known: false, fields: {}, secrets_set: [] }
    wrap()
    expect(await screen.findByText(/entering them all again/)).toBeInTheDocument()
  })

  it('sends kind and fields once credentials are being replaced', async () => {
    wrap()
    fireEvent.click(screen.getByRole('button', { name: /replace credentials/i }))
    fireEvent.change(await screen.findByLabelText('Topic'),
                     { target: { value: 'new-topic' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(sent).toHaveLength(1))
    expect(sent[0].body).toEqual({
      name: 'Home ntfy', kind: 'ntfy',
      fields: { host: 'ntfy.sh', topic: 'new-topic' },
    })
  })

  it('enforces the same field rules the add form does', async () => {
    wrap()
    fireEvent.click(screen.getByRole('button', { name: /replace credentials/i }))
    fireEvent.change(await screen.findByLabelText('Topic'),
                     { target: { value: 'not a topic!!' } })
    expect(await screen.findByText('Letters, numbers, dashes.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    expect(sent).toHaveLength(0)
  })

  it('refuses a whole URL here too', async () => {
    wrap()
    fireEvent.click(screen.getByRole('button', { name: /replace credentials/i }))
    fireEvent.change(await screen.findByLabelText('Topic'),
                     { target: { value: 'slack://a/b/c' } })
    expect(await screen.findByText(/not a whole URL/)).toBeInTheDocument()
  })

  it('can move the channel to a different service without losing it', async () => {
    wrap()
    fireEvent.click(screen.getByRole('button', { name: /replace credentials/i }))
    fireEvent.click(await screen.findByRole('button', { name: 'Gotify' }))
    fireEvent.change(await screen.findByLabelText('Server'),
                     { target: { value: 'gotify.example.com' } })
    fireEvent.change(screen.getByLabelText('App token'),
                     { target: { value: 'AbCdEfGhIjK' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(sent).toHaveLength(1))
    expect(sent[0].body.kind).toBe('gotify')
    // Same id, so the matrix column and its ticks survive.
    expect(sent[0].path).toBe('/notifications/channels/4')
  })

  it('cancel sends nothing', () => {
    const onCancel = vi.fn()
    wrap(CHANNEL, () => {}, onCancel)
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Nope' } })
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onCancel).toHaveBeenCalled()
    expect(sent).toHaveLength(0)
  })
})
