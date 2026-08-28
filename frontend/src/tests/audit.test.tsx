import { DEFAULT_PAGE_SIZE } from '../components/TablePager'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { auditExportUrl } from '../api/audit'

vi.mock('../api/client', () => ({
  // Carries status/body like the real one: the Clear log path reads the
  // backend's own sentence back out of a 403/409 rather than inventing one.
  ApiError: class extends Error {
    status: number; body: unknown
    constructor(status = 500, body: unknown = null) {
      super(`API ${status}`); this.status = status; this.body = body
    }
  },
  // Re-implemented against the class above, same as login-totp.test.tsx does.
  apiErrorDetail: (e: unknown, fallback: string): string => {
    const b = (e as { body?: { detail?: unknown } } | null)?.body
    return typeof b?.detail === 'string' ? b.detail : fallback
  },
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
      { search: 'host.remove', actor: '3', from_: '2026-08-01T00:00', to: '2026-08-07T00:00' },
      'csv',
    )
    const parsed = new URL(url, 'http://x')
    expect(parsed.pathname).toBe('/api/v1/audit/export')
    expect(parsed.searchParams.get('format')).toBe('csv')
    expect(parsed.searchParams.get('search')).toBe('host.remove')
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
    expect(parsed.searchParams.has('search')).toBe(false)
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
    fireEvent.change(await screen.findByLabelText('Item or action'), { target: { value: 'host.remove' } })
    fireEvent.click(screen.getByRole('button', { name: 'Export CSV' }))

    expect(assignSpy).toHaveBeenCalledTimes(1)
    const url = new URL(assignSpy.mock.calls[0][0], 'http://x')
    expect(url.pathname).toBe('/api/v1/audit/export')
    expect(url.searchParams.get('format')).toBe('csv')
    expect(url.searchParams.get('search')).toBe('host.remove')
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

  // The controls are shadcn's Pagination now, and PaginationPrevious/Next
  // carry an aria-label ("Go to previous page" / "Go to next page") which
  // wins over their visible text when the accessible name is computed. The
  // old { name: 'Next' } lookups matched the text; these match the label.
  const prevBtn = () => screen.findByRole('button', { name: 'Go to previous page' })
  const nextBtn = () => screen.findByRole('button', { name: 'Go to next page' })

  it('asks for one row beyond the page so "more" is a fact, not a guess', async () => {
    // One row, not zero: an empty result renders the empty state instead of
    // the table, and this assertion is about the request, not the table.
    await serve(1)
    wrap()
    const { api } = await import('../api/client')
    await nextBtn()
    const call = (api as ReturnType<typeof vi.fn>).mock.calls
      .map((c) => String(c[0])).find((p) => p.startsWith('/audit'))!
    // One past the page size, not the page size: the extra row is the whole
    // mechanism. The default is DEFAULT_PAGE_SIZE, shared with the App Store.
    expect(new URL(call, 'http://x').searchParams.get('per_page'))
      .toBe(String(DEFAULT_PAGE_SIZE + 1))
  })

  it('disables Next on an exactly-full last page, the case the old heuristic got wrong', async () => {
    // Exactly AUDIT_PER_PAGE rows come back, meaning the total was an exact
    // multiple and there is nothing after this page. The old check
    // (rows.length < AUDIT_PER_PAGE) left Next enabled here and walked the
    // user into an empty table.
    await serve(DEFAULT_PAGE_SIZE)
    wrap()
    expect((await nextBtn()) as HTMLButtonElement).toBeDisabled()
  })

  it('enables Next when the extra row shows another page exists', async () => {
    await serve(DEFAULT_PAGE_SIZE + 1)
    wrap()
    expect((await nextBtn()) as HTMLButtonElement).not.toBeDisabled()
  })

  it('disables Previous on page one, where there is nothing behind', async () => {
    await serve(DEFAULT_PAGE_SIZE + 1)
    wrap()
    expect((await prevBtn()) as HTMLButtonElement).toBeDisabled()
    // And it stays a real button, not a link: a link cannot be made inert.
    expect((await prevBtn()).tagName).toBe('BUTTON')
  })

  it('turns the page by refetching with the new page number', async () => {
    await serve(DEFAULT_PAGE_SIZE + 1)
    wrap()
    const { api } = await import('../api/client')
    fireEvent.click(await nextBtn())
    const pages = async () => (api as ReturnType<typeof vi.fn>).mock.calls
      .map((c) => String(c[0])).filter((p) => p.startsWith('/audit'))
      .map((p) => new URL(p, 'http://x').searchParams.get('page'))
    await waitFor(async () => expect(await pages()).toContain('2'))
    // Back again, and Previous is live now that page 2 has something behind it.
    expect((await prevBtn()) as HTMLButtonElement).not.toBeDisabled()
    fireEvent.click(await prevBtn())
    await waitFor(async () => expect((await pages()).at(-1)).toBe('1'))
  })

  // The friendly name is what the row is read by; the raw identifier stays
  // visible because it is what the Action filter and the exports match on.
  it('shows the friendly name and keeps the raw action beside it', async () => {
    await serve(1)
    wrap()
    expect(await screen.findByText('Host Sync')).toBeInTheDocument()
    expect(screen.getByText('host.sync')).toBeInTheDocument()
  })

  // The compliance surface: a denied row must not be readable as the thing
  // it denied. The Result column says "denied" too, but the Action column is
  // the one people scan, so the refusal is the first word it reads.
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
    // The Action column names the action, always, with no prefix. The refusal is
    // the Result column's job and it renders `denied` in red there, which is the
    // column a reader scans for the verdict.
    expect(await screen.findByText('Host Disconnect')).toBeInTheDocument()
    expect(screen.queryByText(/^Blocked/)).not.toBeInTheDocument()
    expect(screen.getByText('Refused')).toBeInTheDocument()
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
    await serve(DEFAULT_PAGE_SIZE + 1)
    wrap()
    await nextBtn()
    // One past the page size is fetched, a page's worth is rendered, plus the
    // header row.
    expect(screen.getAllByRole('row')).toHaveLength(DEFAULT_PAGE_SIZE + 1)
  })
})

// The rename: Date, User, Action, Item, Result, IP. "user #1" and "host #2"
// were ids where the reader wanted a person and a thing.
describe('AuditPage names people and items', () => {
  const qc = () => new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrap = () => render(<QueryClientProvider client={qc()}><AuditPage /></QueryClientProvider>)

  afterEach(() => { vi.restoreAllMocks() })

  const serveRow = async (over: Record<string, unknown>) => {
    const { api } = await import('../api/client')
    ;(api as ReturnType<typeof vi.fn>).mockImplementation((path: string) => {
      if (path === '/entitlements') {
        return Promise.resolve({ tier: 'pro', features: { 'audit.log': true }, grace: null, clock_skew: false })
      }
      if (path === '/users') {
        // Deliberately NOT the row's actor: the Performed by select renders
        // names too, so a shared name would make the cell assertions ambiguous.
        return Promise.resolve([
          { id: 9, email: 'grace@example.com', display_name: 'Grace Hopper', is_active: true, teams: [] },
        ])
      }
      if (path.startsWith('/audit')) {
        return Promise.resolve([{
          id: 1, ts: '2026-08-09T00:00:00Z', actor_type: 'user', actor_id: 1,
          actor_label: 'Ada Lovelace', action: 'host.sync', target_type: 'host',
          target_id: 2, target_label: 'pve-lab-01', result: 'ok', ip: '10.0.0.5',
          job_id: null, params: null, ...over,
        }])
      }
      return Promise.resolve(null)
    })
  }

  it('uses the renamed column headings', async () => {
    await serveRow({})
    wrap()
    for (const name of ['Date', 'User', 'Action', 'Item', 'Result', 'IP']) {
      expect(await screen.findByRole('columnheader', { name })).toBeInTheDocument()
    }
    expect(screen.queryByRole('columnheader', { name: 'Actor' })).not.toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'Target' })).not.toBeInTheDocument()
  })

  it('shows the person and the item by name, not by id', async () => {
    await serveRow({})
    wrap()
    expect(await screen.findByText('Ada Lovelace')).toBeInTheDocument()
    expect(screen.getByText('pve-lab-01')).toBeInTheDocument()
    expect(screen.queryByText('user #1')).not.toBeInTheDocument()
    expect(screen.queryByText('host #2')).not.toBeInTheDocument()
  })

  // The row someone actually came to read: the host was removed, so there is
  // no name left to print. Blanking it would hide the removal itself.
  it('falls back to the raw id when the item no longer exists', async () => {
    await serveRow({ action: 'host.remove', target_label: null })
    wrap()
    expect(await screen.findByText('host #2')).toBeInTheDocument()
  })

  it('does not dress a system row up as a person', async () => {
    await serveRow({ actor_type: 'system', actor_id: null, actor_label: null })
    wrap()
    expect(await screen.findByText('System')).toBeInTheDocument()
  })

  it('names an API key as a key', async () => {
    await serveRow({ actor_type: 'api_key', actor_id: 4, actor_label: 'ci-runner' })
    wrap()
    expect(await screen.findByText('ci-runner (API key)')).toBeInTheDocument()
  })
})

describe('AuditPage filters', () => {
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

  const serveUsers = async () => {
    const { api } = await import('../api/client')
    ;(api as ReturnType<typeof vi.fn>).mockImplementation((path: string) => {
      if (path === '/entitlements') {
        return Promise.resolve({ tier: 'pro', features: { 'audit.log': true }, grace: null, clock_skew: false })
      }
      if (path === '/users') {
        return Promise.resolve([
          { id: 7, email: 'ada@example.com', display_name: 'Ada Lovelace', is_active: true, teams: [] },
        ])
      }
      if (path.startsWith('/audit')) return Promise.resolve([])
      return Promise.resolve(null)
    })
  }

  it('sends one box as the item-or-action search, on the list and the export', async () => {
    await serveUsers()
    wrap()
    fireEvent.change(await screen.findByLabelText('Item or action'),
                     { target: { value: 'pve-lab-01' } })
    fireEvent.click(screen.getByRole('button', { name: 'Export CSV' }))
    const url = new URL(assignSpy.mock.calls[0][0], 'http://x')
    expect(url.searchParams.get('search')).toBe('pve-lab-01')
    // The retired free-text Action box is gone; nothing may still send it.
    expect(url.searchParams.has('action')).toBe(false)
  })

  it('picks the performer from the users list instead of typing an id', async () => {
    await serveUsers()
    wrap()
    const select = await screen.findByLabelText('Performed by')
    // The options come from GET /users, so they arrive after the select does.
    await screen.findByRole('option', { name: 'Ada Lovelace' })
    fireEvent.change(select, { target: { value: '7' } })
    fireEvent.click(screen.getByRole('button', { name: 'Export CSV' }))
    const url = new URL(assignSpy.mock.calls[0][0], 'http://x')
    expect(url.searchParams.get('actor')).toBe('7')
    expect(url.searchParams.has('actor_type')).toBe(false)
  })

  it('can ask for the rows no person wrote, and for anyone again', async () => {
    await serveUsers()
    wrap()
    const select = await screen.findByLabelText('Performed by')
    fireEvent.change(select, { target: { value: 'type:system' } })
    fireEvent.click(screen.getByRole('button', { name: 'Export CSV' }))
    let url = new URL(assignSpy.mock.calls[0][0], 'http://x')
    expect(url.searchParams.get('actor_type')).toBe('system')
    expect(url.searchParams.has('actor')).toBe(false)

    fireEvent.change(select, { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: 'Export CSV' }))
    url = new URL(assignSpy.mock.calls[1][0], 'http://x')
    expect(url.searchParams.has('actor_type')).toBe(false)
    expect(url.searchParams.has('actor')).toBe(false)
  })
})

// Clearing the log. The gate is the point: the backend is owner-only and
// typed-confirmed, and this screen must not offer a one-click way past it.
describe('AuditPage clear log', () => {
  const calls: { path: string; method?: string; body?: Record<string, unknown> }[] = []
  let fail: { status: number; body: unknown } | null = null

  const serve = async () => {
    const { api, ApiError } = await import('../api/client')
    ;(api as ReturnType<typeof vi.fn>).mockImplementation((path: string, opts?: RequestInit) => {
      const method = opts?.method
      if (method != null || path === '/audit') {
        calls.push({ path, method, body: opts?.body ? JSON.parse(String(opts.body)) : undefined })
      }
      if (path === '/audit' && method === 'DELETE') {
        if (fail) return Promise.reject(new (ApiError as never as new (s: number, b: unknown) => Error)(fail.status, fail.body))
        return Promise.resolve({ deleted: 128, before: null })
      }
      if (path === '/entitlements') {
        return Promise.resolve({ tier: 'pro', features: { 'audit.log': true }, grace: null, clock_skew: false })
      }
      if (path === '/users') return Promise.resolve([])
      if (path.startsWith('/audit')) return Promise.resolve([])
      return Promise.resolve(null)
    })
  }

  beforeEach(() => { calls.length = 0; fail = null })
  afterEach(() => { vi.restoreAllMocks() })

  const wrap = () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    return render(<QueryClientProvider client={qc}><AuditPage /></QueryClientProvider>)
  }

  const del = () => calls.find((c) => c.path === '/audit' && c.method === 'DELETE')

  it('will not clear anything until the phrase is typed exactly', async () => {
    await serve()
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Clear log…' }))
    const confirm = screen.getByRole('button', { name: /^confirm$/i })
    expect(confirm).toBeDisabled()

    fireEvent.change(screen.getByLabelText(/type/i), { target: { value: 'clear audit' } })
    fireEvent.click(confirm)
    expect(del()).toBeUndefined()

    fireEvent.change(screen.getByLabelText(/type/i), { target: { value: 'clear audit log' } })
    expect(confirm).toBeEnabled()
    fireEvent.click(confirm)
    await waitFor(() => expect(del()).toBeDefined())
    expect(del()?.body).toEqual({ confirm: 'clear audit log' })
  })

  it('sends the cutoff when one is given, and never the table filters', async () => {
    await serve()
    wrap()
    // A filter is active on the table; the clear must ignore it entirely.
    fireEvent.change(await screen.findByLabelText('Item or action'),
                     { target: { value: 'host' } })
    fireEvent.click(screen.getByRole('button', { name: 'Clear log…' }))
    fireEvent.change(screen.getByLabelText(/older than/i), { target: { value: '2026-01-31' } })
    fireEvent.change(screen.getByLabelText(/type/i), { target: { value: 'clear audit log' } })
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }))

    await waitFor(() => expect(del()).toBeDefined())
    expect(del()?.body).toEqual({ confirm: 'clear audit log', before: '2026-01-31T00:00:00' })
    expect(del()?.body).not.toHaveProperty('search')
  })

  it('says how many entries went and that the clear was recorded', async () => {
    await serve()
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Clear log…' }))
    fireEvent.change(screen.getByLabelText(/type/i), { target: { value: 'clear audit log' } })
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }))
    expect(await screen.findByText(/128 entries/)).toBeInTheDocument()
    expect(screen.getByText(/recorded in the log/)).toBeInTheDocument()
  })

  it('names the rule on a refusal and keeps the server sentence under it', async () => {
    // The owner-only gate holding is a RULE, not a fault. The server's raw
    // sentence alone reads like a bug to the admin who just pressed the button,
    // so the refusal is labelled and the real text is kept underneath: act on
    // the first sentence, verify with the second. Same shape as the host errors.
    await serve()
    fail = { status: 403, body: { detail: 'Your role does not allow this.' } }
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Clear log…' }))
    fireEvent.change(screen.getByLabelText(/type/i), { target: { value: 'clear audit log' } })
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }))
    const note = await screen.findByText(/only the owner can clear the audit log/i)
    // The backend's own words survive, they are not replaced by the label.
    expect(note).toHaveTextContent('Your role does not allow this.')
  })

  it('does not add the owner line to a failure that is not a refusal', async () => {
    // A 500 is a fault, not a rule, and claiming the owner restriction caused it
    // would send the operator after the wrong thing.
    await serve()
    fail = { status: 500, body: { detail: 'database is locked' } }
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Clear log…' }))
    fireEvent.change(screen.getByLabelText(/type/i), { target: { value: 'clear audit log' } })
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }))
    expect(await screen.findByText(/database is locked/)).toBeInTheDocument()
    expect(screen.queryByText(/only the owner/i)).toBeNull()
  })
})
