import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { notifyError } = vi.hoisted(() => ({ notifyError: vi.fn() }))
vi.mock('../lib/notify', () => ({ notify: { error: notifyError, success: vi.fn(), info: vi.fn(), warning: vi.fn() } }))

type Call = { path: string; method?: string; body: unknown }
const calls: Call[] = []
let statusBody: Record<string, unknown> = {}
let logBody: Record<string, unknown> = { state: 'none', version: null, from: null, updated_at: null, reason: null, lines: [] }
let logFetchCount = 0

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
    if (path === '/meta/update/log' && !method) { logFetchCount += 1; return Promise.resolve(logBody) }
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
    logFetchCount = 0
    notifyError.mockClear()
    statusBody = {
      current: '1.0.0', latest: '1.0.0', update_available: false,
      notes_url: null, channel: 'stable', error: null,
      install_shape: 'lxc', can_self_apply: true, compose_hint: null,
    }
    logBody = { state: 'none', version: null, from: null, updated_at: null, reason: null, lines: [] }
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
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Update to 1.0.1' }))
    await waitFor(() => expect(calls.some((c) =>
      c.path === '/meta/update' && c.method === 'POST'
      && JSON.stringify(c.body) === JSON.stringify({ version: '1.0.1' }))).toBe(true))
  })

  it('manual steps use the dev channel when the installed version is below 1.2.0', async () => {
    statusBody = { ...statusBody, current: '1.1.0', latest: '1.1.5', update_available: true }
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Prefer to update it yourself?' }))
    expect(await screen.findByText(
      '/opt/proxploy/bin/proxploy-update --to 1.1.5 --channel https://web.proxploy.dev/releases/latest'))
      .toBeInTheDocument()
  })

  it('manual steps use the prod channel when the installed version is at or above 1.2.0', async () => {
    statusBody = { ...statusBody, current: '1.2.0', latest: '1.3.0', update_available: true }
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Prefer to update it yourself?' }))
    expect(await screen.findByText(
      '/opt/proxploy/bin/proxploy-update --to 1.3.0 --channel https://proxploy.com/releases/latest'))
      .toBeInTheDocument()
  })

  it('manual steps compare versions numerically, so 1.10.0 counts as newer than 1.2.0', async () => {
    statusBody = { ...statusBody, current: '1.10.0', latest: '1.11.0', update_available: true }
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Prefer to update it yourself?' }))
    expect(await screen.findByText(
      '/opt/proxploy/bin/proxploy-update --to 1.11.0 --channel https://proxploy.com/releases/latest'))
      .toBeInTheDocument()
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

  it('a running update shows its log lines as they arrive', async () => {
    statusBody = { ...statusBody, latest: '1.0.1', update_available: true }
    logBody = { state: 'running', version: '1.0.1', from: '1.0.0', updated_at: '2026-09-01T12:00:00Z',
      reason: null, lines: ['backing up 1.0.0', 'fetching 1.0.1'] }
    wrap()
    expect(await screen.findByText('backing up 1.0.0')).toBeInTheDocument()
    expect(screen.getByText('fetching 1.0.1')).toBeInTheDocument()
    expect(screen.getByText('Updating Proxploy, it will restart itself.')).toBeInTheDocument()
  })

  it('a terminal failed state shows the reason and stops polling', async () => {
    statusBody = { ...statusBody, latest: '1.0.1', update_available: true }
    logBody = { state: 'failed', version: '1.0.1', from: '1.0.0', updated_at: '2026-09-01T12:00:00Z',
      reason: 'migration failed; nothing was switched', lines: ['backing up 1.0.0', 'migrating database'] }
    wrap()
    expect(await screen.findByText(
      'Update to 1.0.1 failed: migration failed; nothing was switched')).toBeInTheDocument()
    expect(screen.getByText('migrating database')).toBeInTheDocument()

    const fetchesAfterSettling = logFetchCount
    await new Promise((r) => setTimeout(r, 50))
    expect(logFetchCount).toBe(fetchesAfterSettling)
  })

  it('opening the card after a restart shows a succeeded outcome without clicking anything', async () => {
    statusBody = { ...statusBody, latest: '1.0.1', update_available: true }
    logBody = { state: 'succeeded', version: '1.0.1', from: '1.0.0', updated_at: '2026-09-01T12:00:00Z',
      reason: null, lines: ['update to 1.0.1 complete'] }
    wrap()
    expect(await screen.findByText(/Current version:\s*1\.0\.1/)).toBeInTheDocument()
    expect(screen.getByText('Updated, now running 1.0.1.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Update to/ })).toBeNull()
  })
})
