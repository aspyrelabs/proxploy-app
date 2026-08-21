import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

let LOG: any = { lines: [
  { n: 1, t: '0 5 - 21/Aug/2026:11:12:57 +0530 starting pvefw logger' },
  { n: 2, t: '100 6 tap100i0-IN 21/Aug/2026:11:20:01 +0530 DROP: IN=fwbr100i0' },
], start: 0, limit: 500 }

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  api: vi.fn(() => Promise.resolve(LOG)),
}))

import { FirewallLog } from '../components/FirewallLog'

function renderLog() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <FirewallLog scope={{ kind: 'node', hostId: 1, node: 'pve1' }} />
    </QueryClientProvider>,
  )
}

describe('FirewallLog', () => {
  it('renders each line as Proxmox wrote it', async () => {
    renderLog()
    await screen.findByText(/starting pvefw logger/)
    expect(screen.getByText(/DROP: IN=fwbr100i0/)).toBeTruthy()
  })

  it('says the log is empty rather than showing a blank box', async () => {
    // PVE answers a guest with no logging turned on with a single line reading
    // "no content", which is not a log entry and must not be rendered as one.
    LOG = { lines: [{ n: 1, t: 'no content' }], start: 0, limit: 500 }
    renderLog()
    await waitFor(() => expect(screen.getByText(/nothing logged/i)).toBeTruthy())
    expect(screen.queryByText('no content')).toBeNull()
  })
})
