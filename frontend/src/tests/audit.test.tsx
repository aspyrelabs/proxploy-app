import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { auditExportUrl } from '../api/audit'

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  api: vi.fn((path: string) => {
    if (path === '/entitlements') {
      return Promise.resolve({ tier: 'pro', features: { 'audit.log': true }, grace: null })
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
