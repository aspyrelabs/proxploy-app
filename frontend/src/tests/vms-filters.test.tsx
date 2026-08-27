import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useSyncExternalStore } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../components/ui/icon', () => ({
  Icon: ({ name, size }: { name: string; size?: number }) => (
    <span data-icon={name} data-size={size ?? 18} />
  ),
}))

const VMS = [
  { id: 1, host_id: 1, host_name: 'pve-a', vmid: 201, name: 'win11', status: 'running',
    os_type: 'win11', cpu_cores: 2, cpu_pct: 3, mem_bytes: 1, mem_total_bytes: 2,
    disk_bytes: 1, disk_total_bytes: 2, net_in_bps: null, net_out_bps: null,
    uptime_s: 1, guest_agent_ok: null },
  { id: 2, host_id: 2, host_name: 'pve-b', vmid: 305, name: 'debian', status: 'stopped',
    os_type: 'l26', cpu_cores: 1, cpu_pct: 1, mem_bytes: 1, mem_total_bytes: 2,
    disk_bytes: 1, disk_total_bytes: 2, net_in_bps: null, net_out_bps: null,
    uptime_s: 1, guest_agent_ok: null },
]
const HOSTS = [{ id: 1, name: 'pve-a' }, { id: 2, name: 'pve-b' }]

vi.mock('../api/client', () => ({
  api: vi.fn((path: string) => {
    if (path.startsWith('/vms')) return Promise.resolve(VMS)
    if (path === '/hosts') return Promise.resolve(HOSTS)
    if (path === '/entitlements') {
      return Promise.resolve({ tier: 'builtin', features: {}, grace: null, clock_skew: false })
    }
    return Promise.resolve([])
  }),
  ApiError: class extends Error {},
}))

let mockSearch: { host?: number; q?: string; open?: number } = {}
const listeners = new Set<() => void>()
vi.mock('@tanstack/react-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@tanstack/react-router')>()),
  useSearch: () => useSyncExternalStore(
    (cb) => { listeners.add(cb); return () => listeners.delete(cb) },
    () => mockSearch,
  ),
  useNavigate: () => (opts: { search: typeof mockSearch }) => {
    mockSearch = opts.search
    listeners.forEach((cb) => cb())
  },
}))

import { VmsPage } from '../routes/vms'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><VmsPage /></QueryClientProvider>)
}

const filterBox = () => screen.getByPlaceholderText(/filter virtual machines/i)

describe('VmsPage filters', () => {
  beforeEach(() => { mockSearch = {} })

  it('renders an All hosts segment plus one segment per host', async () => {
    wrap()
    await waitFor(() => expect(screen.getByText('win11')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'All hosts' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'pve-a' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'pve-b' })).toBeInTheDocument()
  })

  it('narrows the rows and updates the shown count as the filter box is typed into', async () => {
    wrap()
    await waitFor(() => expect(screen.getByText('win11')).toBeInTheDocument())
    expect(screen.getByText('2 shown')).toBeInTheDocument()
    fireEvent.change(filterBox(), { target: { value: 'win' } })
    expect(screen.getByText('win11')).toBeInTheDocument()
    expect(screen.queryByText('debian')).not.toBeInTheDocument()
    expect(screen.getByText('1 shown')).toBeInTheDocument()
  })

  it('shows the no-match copy instead of an empty table', async () => {
    wrap()
    await waitFor(() => expect(screen.getByText('win11')).toBeInTheDocument())
    fireEvent.change(filterBox(), { target: { value: 'zzz' } })
    expect(screen.getByText('No virtual machines match your filter.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('matches on vmid', async () => {
    wrap()
    await waitFor(() => expect(screen.getByText('win11')).toBeInTheDocument())
    fireEvent.change(filterBox(), { target: { value: '305' } })
    expect(screen.getByText('debian')).toBeInTheDocument()
    expect(screen.queryByText('win11')).not.toBeInTheDocument()
  })

  it('matches on host name', async () => {
    wrap()
    await waitFor(() => expect(screen.getByText('win11')).toBeInTheDocument())
    fireEvent.change(filterBox(), { target: { value: 'pve-b' } })
    expect(screen.getByText('debian')).toBeInTheDocument()
    expect(screen.queryByText('win11')).not.toBeInTheDocument()
  })
})
