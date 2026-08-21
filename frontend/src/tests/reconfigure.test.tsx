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
let patchOutcome: 'ok' | 'pve_error' = 'ok'

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
      if (path === '/apps/1' && method === 'PATCH') {
        if (patchOutcome === 'pve_error') {
          return Promise.reject(new ApiError(502, {
            error: 'pve_error', detail: 'PVE says: memory 16 is below the CT minimum',
          }))
        }
        return Promise.resolve({ id: 1, changed: body })
      }
      return Promise.reject(new Error(`unexpected path ${path} ${method}`))
    }),
  }
})

import { ReconfigureDialog } from '../components/ReconfigureDialog'

const wrap = (onClose = vi.fn()) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const utils = render(
    <QueryClientProvider client={qc}>
      <ReconfigureDialog app={APP as any} onClose={onClose} />
    </QueryClientProvider>,
  )
  return { ...utils, onClose }
}

describe('ReconfigureDialog', () => {
  it('prefills the Proxploy-side fields from the app and leaves cores/memory/swap blank', () => {
    wrap()
    expect(screen.getByLabelText('Name')).toHaveValue('jellyfin')
    expect(screen.getByLabelText('Web port')).toHaveValue(8096)
    expect(screen.getByLabelText('Protocol')).toHaveValue('http')
    expect(screen.getByLabelText('Path')).toHaveValue('/')
    expect(screen.getByLabelText('Cores')).toHaveValue(null)
    expect(screen.getByLabelText('Memory (MB)')).toHaveValue(null)
    expect(screen.getByLabelText('Swap (MB)')).toHaveValue(null)
  })

  it('offers only http, https and letting Proxploy ask the app', async () => {
    // Free text here used to mean any string became the scheme a URL was
    // built from. The blank option is the one that matters: it clears the
    // stored value so the app is asked which scheme it speaks on open,
    // which is how an https app on a plain-looking port gets opened right.
    calls.length = 0
    patchOutcome = 'ok'
    wrap()
    const select = screen.getByLabelText('Protocol')
    expect([...select.querySelectorAll('option')].map((o) => o.value))
      .toEqual(['', 'http', 'https'])

    fireEvent.change(select, { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ web_protocol: '' })
  })

  it('disables Save with no edits, and sends only the changed field', async () => {
    calls.length = 0
    patchOutcome = 'ok'
    wrap()
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()

    fireEvent.change(screen.getByLabelText('Cores'), { target: { value: '4' } })
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(calls.some((c) => c.path === '/apps/1' && c.method === 'PATCH')).toBe(true))
    const patch = calls.find((c) => c.path === '/apps/1' && c.method === 'PATCH')
    expect(patch?.body).toEqual({ cores: 4 })
  })

  it('sends multiple changed fields together, omitting untouched ones', async () => {
    calls.length = 0
    patchOutcome = 'ok'
    wrap()

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'jellyfin-2' } })
    fireEvent.change(screen.getByLabelText('Path'), { target: { value: '/web' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(calls.some((c) => c.path === '/apps/1' && c.method === 'PATCH')).toBe(true))
    const patch = calls.find((c) => c.path === '/apps/1' && c.method === 'PATCH')
    expect(patch?.body).toEqual({ name: 'jellyfin-2', web_path: '/web' })
  })

  it('shows the 502 pve_error detail verbatim', async () => {
    calls.length = 0
    patchOutcome = 'pve_error'
    wrap()

    fireEvent.change(screen.getByLabelText('Memory (MB)'), { target: { value: '16' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText('PVE says: memory 16 is below the CT minimum')).toBeInTheDocument()
  })
})
