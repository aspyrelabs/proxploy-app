import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const APP = {
  id: 1, name: 'jellyfin', slug: 'jellyfin', host_id: 1, host_name: 'pve-a',
  node: 'pve-a', ctid: 150, category: null, catalog_slug: null,
  icon_initials: null, icon_colors: null, web_port: 8096, web_protocol: 'http',
  web_path: '/', status: 'running', ip: '10.0.0.5', cpu_pct: null,
  mem_bytes: null, mem_total_bytes: null, uptime_s: null,
  update_available: null, adopted: true,
}

const calls: { path: string; method?: string; body?: any }[] = []
// Whether DELETE should demand a fresher confirm phrase, simulating the app
// having been renamed after this dialog opened (the 409 defensive path).
let requireFreshPhrase = false

const { navigateMock } = vi.hoisted(() => ({ navigateMock: vi.fn() }))

vi.mock('../api/client', () => {
  class ApiError extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) { super(`API ${status}`); this.status = status; this.body = body }
  }
  return {
    ApiError,
    api: vi.fn((path: string, opts?: RequestInit) => {
      const method = opts?.method
      const body = opts?.body ? JSON.parse(String(opts.body)) : undefined
      calls.push({ path, method, body })
      if (path === '/apps/1' && method === 'DELETE') {
        if (body?.keep_ct) return Promise.resolve({ removed: true, ct_kept: true })
        if (requireFreshPhrase && body?.confirm !== 'jellyfin-renamed') {
          return Promise.reject(new ApiError(409, {
            error: 'confirm_required', confirm_phrase: 'jellyfin-renamed',
            detail: 'jellyfin-renamed destroys CT 150 and its disk. This cannot be undone.',
          }))
        }
        if (!requireFreshPhrase && body?.confirm === 'jellyfin') {
          return Promise.resolve({ job: { id: 77, kind: 'app.uninstall', status: 'queued' } })
        }
        if (requireFreshPhrase && body?.confirm === 'jellyfin-renamed') {
          return Promise.resolve({ job: { id: 77, kind: 'app.uninstall', status: 'queued' } })
        }
        return Promise.reject(new ApiError(409, {
          error: 'confirm_required', confirm_phrase: 'jellyfin',
          detail: 'Type the name to confirm.',
        }))
      }
      if (path === '/jobs/77/events') return Promise.resolve([])
      return Promise.reject(new Error(`unexpected path ${path} ${method}`))
    }),
  }
})

vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  useNavigate: () => navigateMock,
}))

import { UninstallDialog } from '../components/UninstallDialog'

const wrap = (onClose = vi.fn()) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const utils = render(
    <QueryClientProvider client={qc}>
      <UninstallDialog app={APP as any} onClose={onClose} />
    </QueryClientProvider>,
  )
  return { ...utils, onClose }
}

describe('UninstallDialog', () => {
  it('destroy path: opens the typed confirm, sends {confirm: app.name}, surfaces the returned job', async () => {
    calls.length = 0
    requireFreshPhrase = false
    navigateMock.mockClear()
    const { onClose } = wrap()

    fireEvent.click(screen.getByRole('button', { name: 'Destroy container…' }))
    const input = screen.getByLabelText(/type/i)
    fireEvent.change(input, { target: { value: 'jellyfin' } })
    fireEvent.click(screen.getByRole('button', { name: /confirm/i }))

    await waitFor(() => expect(calls.some((c) => c.path === '/apps/1' && c.method === 'DELETE')).toBe(true))
    const del = calls.find((c) => c.path === '/apps/1' && c.method === 'DELETE')
    expect(del?.body).toEqual({ confirm: 'jellyfin' })

    // The job is surfaced with the shared JobLog view, not an immediate
    // navigate away, matching CloneDialog/MigrateDialog's job-view pattern.
    expect(await screen.findByRole('button', { name: 'Close' })).toBeInTheDocument()
    expect(navigateMock).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(navigateMock).toHaveBeenCalledWith(expect.objectContaining({ to: '/apps' }))
    expect(onClose).toHaveBeenCalled()
  })

  // Same shape as HostRemoveDialog's gate test. Converting to AlertDialog is
  // exactly the kind of change that quietly drops a guard like this.
  it('blocks the destroy until the app name is typed exactly', async () => {
    calls.length = 0
    requireFreshPhrase = false
    wrap()

    fireEvent.click(screen.getByRole('button', { name: 'Destroy container…' }))
    const confirm = screen.getByRole('button', { name: /^confirm$/i })
    expect(confirm).toBeDisabled()

    fireEvent.change(screen.getByLabelText(/type/i), { target: { value: 'jellyfi' } })
    expect(confirm).toBeDisabled()
    fireEvent.click(confirm)
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)

    fireEvent.change(screen.getByLabelText(/type/i), { target: { value: 'jellyfin' } })
    expect(confirm).toBeEnabled()
  })

  it('is a modal alertdialog that Escape closes', async () => {
    const { onClose } = wrap()

    const panel = await screen.findByRole('alertdialog')
    expect(panel).toHaveAttribute('aria-modal', 'true')

    fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' })
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })

  it('forget path: sends {keep_ct: true} with no confirm, navigates on success', async () => {
    calls.length = 0
    requireFreshPhrase = false
    navigateMock.mockClear()
    const { onClose } = wrap()

    fireEvent.click(screen.getByRole('button', { name: 'Forget, keep container running' }))

    await waitFor(() => expect(calls.some((c) => c.path === '/apps/1' && c.method === 'DELETE')).toBe(true))
    const del = calls.find((c) => c.path === '/apps/1' && c.method === 'DELETE')
    expect(del?.body).toEqual({ keep_ct: true })
    expect(del?.body.confirm).toBeUndefined()

    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith(expect.objectContaining({ to: '/apps' })))
    expect(onClose).toHaveBeenCalled()
  })

  it('handles a 409 confirm_required defensively and lets the operator retry with the fresh phrase', async () => {
    calls.length = 0
    requireFreshPhrase = true
    navigateMock.mockClear()
    wrap()

    fireEvent.click(screen.getByRole('button', { name: 'Destroy container…' }))
    fireEvent.change(screen.getByLabelText(/type/i), { target: { value: 'jellyfin' } })
    fireEvent.click(screen.getByRole('button', { name: /confirm/i }))

    expect(await screen.findByText(/The app name changed, retype it to confirm\./)).toBeInTheDocument()
    // The typed-confirm dialog closed rather than staying open on a stale phrase.
    expect(screen.queryByLabelText(/type/i)).not.toBeInTheDocument()

    // Retry with the refreshed phrase the server returned.
    fireEvent.click(screen.getByRole('button', { name: 'Destroy container…' }))
    fireEvent.change(screen.getByLabelText(/type/i), { target: { value: 'jellyfin-renamed' } })
    fireEvent.click(screen.getByRole('button', { name: /confirm/i }))

    await waitFor(() => {
      const deletes = calls.filter((c) => c.path === '/apps/1' && c.method === 'DELETE')
      expect(deletes.length).toBe(2)
      expect(deletes[1].body).toEqual({ confirm: 'jellyfin-renamed' })
    })
    expect(await screen.findByRole('button', { name: 'Close' })).toBeInTheDocument()
  })
})
