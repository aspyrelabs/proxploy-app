import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { auditExportUrl } from '../api/audit'

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  api: vi.fn((path: string) => {
    if (path === '/entitlements') {
      return Promise.resolve({ tier: 'pro', features: { 'audit.log': true }, grace: null, clock_skew: false })
    }
    if (path.startsWith('/audit')) return Promise.resolve([])
    return Promise.resolve(null)
  }),
}))

import { AuditPage } from '../routes/audit'

describe('auditExportUrl', () => {
  it('carries the active filters, including the literal from_ key', () => {
    const url = auditExportUrl(
      { action: 'host.remove', actor: '3', from_: '2026-08-01T00:00', to: '2026-08-07T00:00' },
      'csv',
    )
    const parsed = new URL(url, 'http://x')
    expect(parsed.pathname).toBe('/api/v1/audit/export')
    expect(parsed.searchParams.get('format')).toBe('csv')
    expect(parsed.searchParams.get('action')).toBe('host.remove')
    expect(parsed.searchParams.get('actor')).toBe('3')
    expect(parsed.searchParams.get('from_')).toBe('2026-08-01T00:00')
    expect(parsed.searchParams.get('to')).toBe('2026-08-07T00:00')
    // Never the aliasless "from" -- the backend param is literally "from_".
    expect(parsed.searchParams.has('from')).toBe(false)
  })

  it('omits filters that were never set, and switches format', () => {
    const url = auditExportUrl({}, 'jsonl')
    const parsed = new URL(url, 'http://x')
    expect(parsed.searchParams.get('format')).toBe('jsonl')
    expect(parsed.searchParams.has('action')).toBe(false)
    expect(parsed.searchParams.has('from_')).toBe(false)
  })
})

describe('AuditPage export buttons', () => {
  let assignSpy: ReturnType<typeof vi.fn>

  beforeEach(() => {
    assignSpy = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign: assignSpy })
  })
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

  const wrap = () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return render(<QueryClientProvider client={qc}><AuditPage /></QueryClientProvider>)
  }

  it('navigates to the export URL with the active filters when Export CSV is clicked', async () => {
    wrap()
    fireEvent.change(await screen.findByLabelText('Action'), { target: { value: 'host.remove' } })
    fireEvent.click(screen.getByRole('button', { name: 'Export CSV' }))

    expect(assignSpy).toHaveBeenCalledTimes(1)
    const url = new URL(assignSpy.mock.calls[0][0], 'http://x')
    expect(url.pathname).toBe('/api/v1/audit/export')
    expect(url.searchParams.get('format')).toBe('csv')
    expect(url.searchParams.get('action')).toBe('host.remove')
  })

  it('carries the from_ filter on Export JSONL as well', async () => {
    wrap()
    fireEvent.change(await screen.findByLabelText('From'), { target: { value: '2026-08-01T00:00' } })
    fireEvent.click(screen.getByRole('button', { name: 'Export JSONL' }))

    const url = new URL(assignSpy.mock.calls[0][0], 'http://x')
    expect(url.searchParams.get('format')).toBe('jsonl')
    expect(url.searchParams.get('from_')).toBe('2026-08-01T00:00')
  })
})

describe('AuditPage pagination boundary', () => {
  const qc = () => new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrap = () => render(<QueryClientProvider client={qc()}><AuditPage /></QueryClientProvider>)

  const row = (id: number) => ({
    id, ts: '2026-08-09T00:00:00Z', actor_id: 1, actor_label: 'admin',
    action: 'host.sync', target: null, result: 'ok', ip: '127.0.0.1',
  })

  afterEach(() => { vi.restoreAllMocks() })

  const serve = async (count: number) => {
    const { api } = await import('../api/client')
    ;(api as ReturnType<typeof vi.fn>).mockImplementation((path: string) => {
      if (path === '/entitlements') {
        return Promise.resolve({ tier: 'pro', features: { 'audit.log': true }, grace: null, clock_skew: false })
      }
      if (path.startsWith('/audit')) {
        return Promise.resolve(Array.from({ length: count }, (_, i) => row(i + 1)))
      }
      return Promise.resolve(null)
    })
  }

  it('asks for one row beyond the page so "more" is a fact, not a guess', async () => {
    // One row, not zero: an empty result renders the empty state instead of
    // the table, and this assertion is about the request, not the table.
    await serve(1)
    wrap()
    const { api } = await import('../api/client')
    await screen.findByRole('button', { name: 'Next' })
    const call = (api as ReturnType<typeof vi.fn>).mock.calls
      .map((c) => String(c[0])).find((p) => p.startsWith('/audit'))!
    // 51, not 50: the extra row is the whole mechanism.
    expect(new URL(call, 'http://x').searchParams.get('per_page')).toBe('51')
  })

  it('disables Next on an exactly-full last page, the case the old heuristic got wrong', async () => {
    // Exactly AUDIT_PER_PAGE rows come back, meaning the total was an exact
    // multiple and there is nothing after this page. The old check
    // (rows.length < AUDIT_PER_PAGE) left Next enabled here and walked the
    // user into an empty table.
    await serve(50)
    wrap()
    expect((await screen.findByRole('button', { name: 'Next' })) as HTMLButtonElement)
      .toBeDisabled()
  })

  it('enables Next when the extra row shows another page exists', async () => {
    await serve(51)
    wrap()
    expect((await screen.findByRole('button', { name: 'Next' })) as HTMLButtonElement)
      .not.toBeDisabled()
  })

  // The friendly name is what the row is read by; the raw identifier stays
  // visible because it is what the Action filter and the exports match on.
  it('shows the friendly name and keeps the raw action beside it', async () => {
    await serve(1)
    wrap()
    expect(await screen.findByText('Host Synced')).toBeInTheDocument()
    expect(screen.getByText('host.sync')).toBeInTheDocument()
  })

  // The compliance surface: a denied row must not be readable as the thing
  // it denied. The Result column says "denied" too, but the Action column is
  // the one people scan, and "Host Removed" there is a claim the host is gone.
  it('does not title a denied row with the label for the thing that did not happen', async () => {
    const { api } = await import('../api/client')
    ;(api as ReturnType<typeof vi.fn>).mockImplementation((path: string) => {
      if (path === '/entitlements') {
        return Promise.resolve({ tier: 'pro', features: { 'audit.log': true }, grace: null, clock_skew: false })
      }
      if (path.startsWith('/audit')) {
        return Promise.resolve([{ ...row(1), action: 'host.remove', result: 'denied' }])
      }
      return Promise.resolve(null)
    })
    wrap()
    expect(await screen.findByText('Host Remove Denied')).toBeInTheDocument()
    expect(screen.queryByText('Host Removed')).not.toBeInTheDocument()
    // The stored identifier still shows: the filter and the exports match on it.
    expect(screen.getByText('host.remove')).toBeInTheDocument()
  })

  it('still names an action the label map has never seen', async () => {
    const { api } = await import('../api/client')
    ;(api as ReturnType<typeof vi.fn>).mockImplementation((path: string) => {
      if (path === '/entitlements') {
        return Promise.resolve({ tier: 'pro', features: { 'audit.log': true }, grace: null, clock_skew: false })
      }
      if (path.startsWith('/audit')) {
        return Promise.resolve([{ ...row(1), action: 'gizmo.self_test' }])
      }
      return Promise.resolve(null)
    })
    wrap()
    expect(await screen.findByText('Gizmo Self Test')).toBeInTheDocument()
  })

  it('never renders the probe row', async () => {
    await serve(51)
    wrap()
    await screen.findByRole('button', { name: 'Next' })
    // 51 fetched, 50 rendered, plus the header row.
    expect(screen.getAllByRole('row')).toHaveLength(51)
  })
})
