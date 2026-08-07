import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const LOCAL = {
  host_id: 1, host_name: 'host-01', node: 'pve1', storage: 'local', type: 'dir',
  content: ['iso', 'vztmpl', 'backup'], shared: false, status: 'available',
  used_bytes: 107374182400, total_bytes: 429496729600, used_pct: 25.0,
}
const PBS = {
  host_id: 1, host_name: 'host-01', node: 'pve1', storage: 'pbs-main', type: 'pbs',
  content: ['backup'], shared: true, status: 'available',
  used_bytes: 924000000000, total_bytes: 1000000000000, used_pct: 92.4,
}
const ISO = {
  volid: 'local:iso/ubuntu-24.04.iso', format: 'iso', size: 6000000000, used: 0,
  vmid: null, ctime: 1730000000, content: 'iso', notes: null, verification: null,
}
const DUMP = {
  volid: 'local:backup/vzdump-qemu-100.vma.zst', format: 'vma.zst', size: 900000,
  used: 0, vmid: 100, ctime: 1730000100, content: 'backup', notes: 'nightly',
  verification: { state: 'ok' },
}

const calls: string[] = []
let storageResult: 'ok' | 'empty' | 'error' = 'ok'
vi.mock('../api/client', () => ({
  api: vi.fn((path: string) => {
    calls.push(path)
    if (path.includes('/content')) {
      return Promise.resolve(path.includes('content=backup') ? [DUMP] : [ISO])
    }
    if (path === '/storage/1/local') {
      return Promise.resolve({ ...LOCAL, avail_bytes: 322122547200, nodes: ['pve1'] })
    }
    if (path === '/storage') {
      if (storageResult === 'error') return Promise.reject(new Error('boom'))
      return Promise.resolve(storageResult === 'empty' ? [] : [LOCAL, PBS])
    }
    if (path === '/hosts') return Promise.resolve([{ id: 1, name: 'host-01' }])
    if (path === '/entitlements') {
      return Promise.resolve({ tier: 'pro', features: { 'storage.manage': true }, grace: null })
    }
    return Promise.resolve(null)
  }),
  ApiError: class extends Error {},
}))

vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ children }: { children?: unknown }) => <a>{children as never}</a>,
  useNavigate: () => () => {},
  useSearch: () => ({}),
}))

import { StoragePage } from '../routes/storage'

const withQuery = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('StoragePage', () => {
  beforeEach(() => { storageResult = 'ok' })

  it('says the datastores could not be read rather than showing "no datastores yet"', async () => {
    storageResult = 'error'
    withQuery(<StoragePage />)
    expect(await screen.findByText(/datastores not readable/i)).toBeInTheDocument()
    expect(screen.queryByText('No datastores yet')).not.toBeInTheDocument()
  })

  it('shows the real empty-datastores copy when there genuinely are none', async () => {
    storageResult = 'empty'
    withQuery(<StoragePage />)
    expect(await screen.findByText('No datastores yet')).toBeInTheDocument()
    expect(screen.queryByText(/datastores not readable/i)).not.toBeInTheDocument()
  })

  it('counts the datastores in the header (doc 06 §a row 43)', async () => {
    withQuery(<StoragePage />)
    expect(await screen.findByText('2 datastores across the cluster')).toBeInTheDocument()
  })

  it('renders a card per datastore with the node · type subline and a % badge', async () => {
    withQuery(<StoragePage />)
    expect(await screen.findByText('local')).toBeInTheDocument()
    expect(screen.getByText('pve1 · dir')).toBeInTheDocument()
    expect(screen.getByText('pve1 · pbs')).toBeInTheDocument()
    expect(screen.getByText('25%')).toBeInTheDocument()
    expect(screen.getByText('92%')).toBeInTheDocument()
    expect(screen.getByText('100.0 GiB / 400.0 GiB')).toBeInTheDocument()
  })

  it('turns the usage bar red past 80% and leaves the rest violet', async () => {
    const { container } = withQuery(<StoragePage />)
    await screen.findByText('local')
    // UsageBar paints its fill with an inline `background: <gradient>`; the
    // codebase has no test ids, so read the style the same way a human would.
    // StorageCard's icon tile is *always* violet regardless of danger state,
    // so `div[style*="linear-gradient"]` alone also matches it, narrow to
    // the fill divs, which are the only ones that also carry `width`.
    const bars = [...container.querySelectorAll('div[style*="linear-gradient"]')]
      .map((el) => el.getAttribute('style') ?? '')
      .filter((s) => s.includes('width'))
    // jsdom v30 (@asamuzakjp/css-color) normalizes hex colors to rgb() when it
    // serializes an inline style, so #A78BFA / #F26D6D never appear literally
    // here even though StorageCard sets them verbatim, assert the equivalent
    // rgb() triplet instead.
    expect(bars[0]).toContain('rgb(167, 139, 250)')  // local, 25% → STORAGE_GRADIENT (#A78BFA)
    expect(bars[1]).toContain('rgb(242, 109, 109)')  // pbs-main, 92% → DANGER_GRADIENT (#F26D6D)
  })

  it('opens the content browser on a card click and lists the volumes', async () => {
    withQuery(<StoragePage />)
    fireEvent.click(await screen.findByRole('button', { name: /local/ }))
    expect(await screen.findByText('local:iso/ubuntu-24.04.iso')).toBeInTheDocument()
    expect(screen.getByText('5.6 GiB')).toBeInTheDocument()
    // detail hook supplies the free-space line the list row cannot
    await waitFor(() => expect(screen.getByText('300.0 GiB')).toBeInTheDocument())
  })

  it('refetches through the content endpoint when the content filter changes', async () => {
    withQuery(<StoragePage />)
    fireEvent.click(await screen.findByRole('button', { name: /local/ }))
    await screen.findByText('local:iso/ubuntu-24.04.iso')
    fireEvent.click(screen.getByRole('button', { name: 'Backups' }))
    expect(await screen.findByText('local:backup/vzdump-qemu-100.vma.zst')).toBeInTheDocument()
    expect(calls).toContain('/storage/1/local/content?content=backup')
  })

  it('opens the attach form from the header button', async () => {
    withQuery(<StoragePage />)
    fireEvent.click(await screen.findByRole('button', { name: 'Add storage' }))
    expect(await screen.findByRole('button', { name: 'Attach' })).toBeInTheDocument()
  })

  it('offers Upload and Manage inside the content browser', async () => {
    withQuery(<StoragePage />)
    fireEvent.click(await screen.findByRole('button', { name: /local/ }))
    expect(await screen.findByRole('button', { name: 'Upload' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Manage' })).toBeInTheDocument()
  })
})
