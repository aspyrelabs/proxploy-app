import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { toastError } = vi.hoisted(() => ({ toastError: vi.fn() }))
vi.mock('sonner', () => ({ toast: { error: toastError, success: vi.fn() } }))

type Call = { path: string; method?: string; body: unknown }
const calls: Call[] = []
let statusBody: Record<string, unknown> = {}
let versionBody: Record<string, unknown> = { version: '1.0.0', db_backend: 'sqlite' }

const { ApiError } = vi.hoisted(() => ({
  ApiError: class extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) { super(`API ${status}`); this.status = status; this.body = body }
  },
}))

vi.mock('../api/client', () => ({
  ApiError,
  api: vi.fn((path: string, opts?: RequestInit) => {
    const method = opts?.method
    if (path === '/meta/update' && !method) return Promise.resolve(statusBody)
    if (path === '/meta/update' && method === 'POST') {
      const body = opts?.body ? JSON.parse(String(opts.body)) : null
      calls.push({ path, method, body })
      return Promise.resolve({ ok: true, version: body.version })
    }
    if (path === '/meta/version' && !method) return Promise.resolve(versionBody)
    calls.push({ path, method, body: opts?.body ? JSON.parse(String(opts.body)) : null })
    return Promise.resolve(null)
  }),
}))

import { UpdateCard } from '../components/UpdateCard'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}><UpdateCard /></QueryClientProvider>)
}

describe('UpdateCard', () => {
  beforeEach(() => {
    calls.length = 0
    toastError.mockClear()
    statusBody = {
      current: '1.0.0', latest: '1.0.0', update_available: false,
      notes_url: null, channel: 'stable', error: null,
      install_shape: 'lxc', can_self_apply: true, compose_hint: null,
    }
    versionBody = { version: '1.0.0', db_backend: 'sqlite' }
  })
  afterEach(() => vi.restoreAllMocks())

  it('up-to-date state renders the version and no update button', async () => {
    wrap()
    expect(await screen.findByText(/Current version:\s*1\.0\.0/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Update to/ })).toBeNull()
  })

  it('available + can_self_apply renders "Update to 1.0.1" and the notes link', async () => {
    statusBody = { ...statusBody, latest: '1.0.1', update_available: true,
      notes_url: 'https://example.invalid/v1.0.1' }
    wrap()
    expect(await screen.findByRole('button', { name: 'Update to 1.0.1' })).toBeInTheDocument()
    const link = screen.getByRole('link', { name: 'Release notes' })
    expect(link).toHaveAttribute('href', 'https://example.invalid/v1.0.1')
  })

  it('clicking Update posts /meta/update with {version: "1.0.1"}', async () => {
    statusBody = { ...statusBody, latest: '1.0.1', update_available: true }
    versionBody = { version: '1.0.0', db_backend: 'sqlite' } // unchanged -- keep it simple, no poll assertions here
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Update to 1.0.1' }))
    await waitFor(() => expect(calls.some((c) =>
      c.path === '/meta/update' && c.method === 'POST'
      && JSON.stringify(c.body) === JSON.stringify({ version: '1.0.1' }))).toBe(true))
  })

  it('docker shape renders the compose command and no apply button', async () => {
    statusBody = {
      current: '1.0.0', latest: '1.0.1', update_available: true,
      notes_url: 'https://example.invalid/v1.0.1', channel: 'stable', error: null,
      install_shape: 'docker', can_self_apply: false,
      compose_hint: 'docker compose pull && docker compose up -d',
    }
    wrap()
    expect(await screen.findByText('docker compose pull && docker compose up -d')).toBeInTheDocument()
    expect(screen.getByText(/Proxploy does not update its own container, run this on the Docker host\./))
      .toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Update to/ })).toBeNull()
  })

  it('a channel error renders the message and still shows the current version', async () => {
    statusBody = {
      current: '1.0.0', latest: null, update_available: false,
      notes_url: null, channel: null,
      error: 'could not reach the release channel: timed out',
      install_shape: 'lxc', can_self_apply: true, compose_hint: null,
    }
    wrap()
    expect(await screen.findByText('could not reach the release channel: timed out')).toBeInTheDocument()
    expect(screen.getByText(/Current version:\s*1\.0\.0/)).toBeInTheDocument()
  })

  it('after applying, a /meta/version that changes flips the card to the new version', async () => {
    statusBody = { ...statusBody, latest: '1.0.1', update_available: true }
    versionBody = { version: '1.0.1', db_backend: 'sqlite' } // already-changed once polling starts
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Update to 1.0.1' }))
    expect(await screen.findByText(/Current version:\s*1\.0\.1/)).toBeInTheDocument()
  })
})
