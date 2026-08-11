/** The host page Overview strip: what this machine actually is. */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

let status: unknown = null
let fails = false

vi.mock('../api/client', () => ({
  api: vi.fn(() => (fails ? Promise.reject(new Error('502')) : Promise.resolve(status))),
  ApiError: class extends Error {},
}))

import { HostFacts } from '../components/HostFacts'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}><HostFacts hostId={1} node="pve1" /></QueryClientProvider>)
}

describe('HostFacts', () => {
  beforeEach(() => {
    fails = false
    status = {
      node: 'pve1', uptime_s: 25029, pve_version: 'pve-manager/9.2.10/43df2e01f27a1a19',
      kernel: '7.0.14-11-pve', arch: 'x86_64', boot_mode: 'efi', secure_boot: false,
      cpu: { model: '13th Gen Intel(R) Core(TM) i5-13500T', vendor: 'GenuineIntel',
             sockets: 1, cores: 14, threads: 20, mhz: '800.000' },
      load: [2.0, 1.0, 0.5], io_delay: 0.00027,
      memory: { total: 33306869760, used: 2161287168 },
      swap: { total: 8589930496, used: 0 },
      rootfs: { total: 100861726720, used: 6425862144 },
    }
  })

  it('separates physical cores from threads', async () => {
    wrap()
    expect(await screen.findByText(/14 physical/i)).toBeInTheDocument()
    expect(screen.getByText(/20 logical/i)).toBeInTheDocument()
  })

  it('shows the processor model and kernel', async () => {
    wrap()
    expect(await screen.findByText(/i5-13500T/)).toBeInTheDocument()
    expect(screen.getByText('7.0.14-11-pve')).toBeInTheDocument()
  })

  it('normalises load by thread count, and still shows the raw triple', async () => {
    wrap()
    // 2.0 over 20 threads is 10% busy, not "200% of one core".
    expect(await screen.findByText(/10%/)).toBeInTheDocument()
    expect(screen.getByText(/2\.00 · 1\.00 · 0\.50/)).toBeInTheDocument()
  })

  it('renders IO delay as a percentage rather than a raw fraction', async () => {
    wrap()
    expect(await screen.findByText(/0\.03%/)).toBeInTheDocument()
  })

  it('shows the PVE version without the manager prefix and build hash', async () => {
    wrap()
    expect(await screen.findByText('9.2.10')).toBeInTheDocument()
  })

  it('costs the strip, not the page, when the node refuses to be read', async () => {
    // A token too narrow for /nodes/{n}/status must not turn the host page
    // into an error page: everything else on it came from the poller.
    fails = true
    const { container } = wrap()
    await waitFor(() => expect(container).toBeEmptyDOMElement())
  })

  it('survives a node that reports no cpuinfo at all', async () => {
    status = { node: 'pve1', uptime_s: null, pve_version: null, kernel: null,
               arch: null, boot_mode: null, secure_boot: false,
               cpu: { model: null, vendor: null, sockets: null, cores: null,
                      threads: null, mhz: null },
               load: [0, 0, 0], io_delay: null, memory: {}, swap: {}, rootfs: {} }
    wrap()
    expect(await screen.findByText(/\? physical/)).toBeInTheDocument()
    // and it must not divide by a zero thread count
    expect(screen.getAllByText('0%').length).toBeGreaterThan(0)
  })
})
