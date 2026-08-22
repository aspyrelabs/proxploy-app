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

const KINDS = [
  { kind: 'ntfy', label: 'ntfy', setup_url: '', fields: [
    { key: 'host', label: 'Server', required: true, secret: false,
      placeholder: '', default: 'ntfy.sh', help: '',
      pattern: '^[A-Za-z0-9][A-Za-z0-9.\\-]*(:\\d{1,5})?$', hint: 'A hostname.' },
    { key: 'topic', label: 'Topic', required: true, secret: false,
      placeholder: '', default: '', help: '',
      pattern: '^[A-Za-z0-9_-]{1,64}$', hint: 'Letters, numbers, dashes.' },
  ] },
  { kind: 'gotify', label: 'Gotify', setup_url: '', fields: [
    { key: 'host', label: 'Server', required: true, secret: false,
      placeholder: '', default: '', help: '', pattern: '', hint: '' },
    { key: 'token', label: 'App token', required: true, secret: true,
      placeholder: '', default: '', help: '',
      pattern: '^[A-Za-z0-9._-]{8,}$', hint: 'At least 8 characters.' },
  ] },
]

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  api: vi.fn((path: string, opts?: RequestInit) => {
    if (path === '/notifications/kinds') return Promise.resolve(KINDS)
    sent.push({ path, method: opts?.method,
                body: opts?.body ? JSON.parse(String(opts.body)) : null })
    return Promise.resolve({})
  }),
}))

import { ChannelEditForm } from '../components/ChannelEditForm'

const CHANNEL = { id: 4, name: 'Home ntfy', kind: 'ntfy', events: ['job.failed'],
                  enabled: true, last_notified_at: null }

const wrap = (onSaved = () => {}, onCancel = () => {}) => {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <ChannelEditForm channel={CHANNEL} onSaved={onSaved} onCancel={onCancel} />
    </QueryClientProvider>)
}

describe('ChannelEditForm', () => {
  beforeEach(() => { sent.length = 0 })

  it('prefills the name, because a name is not a secret', () => {
    wrap()
    expect(screen.getByLabelText('Name')).toHaveValue('Home ntfy')
  })

  it('does not pretend the credential can be shown', () => {
    wrap()
    expect(screen.getByText(/cannot be shown again/i)).toBeInTheDocument()
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

  it('replacing credentials reopens that service own fields, blank', async () => {
    wrap()
    fireEvent.click(screen.getByRole('button', { name: /replace credentials/i }))
    expect(await screen.findByLabelText('Topic')).toHaveValue('')
    // A field that ships with a default still gets it.
    expect(screen.getByLabelText('Server')).toHaveValue('ntfy.sh')
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
    wrap(() => {}, onCancel)
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Nope' } })
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onCancel).toHaveBeenCalled()
    expect(sent).toHaveLength(0)
  })
})
