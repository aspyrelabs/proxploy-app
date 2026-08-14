import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  api: vi.fn((path: string) => {
    if (path === `/hosts/3`) {
      return Promise.resolve({ id: 3, name: 'pve-01', capabilities: {
        monitoring: true, lifecycle: false, console: false, backup: false } })
    }
    return Promise.resolve({})
  }),
}))

import { HostTokensDialog } from '../routes/settings'

describe('Settings host tokens', () => {
  it('opens the capability list for one host', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={qc}>
      <HostTokensDialog hostId={3} hostName="pve-01" onClose={() => {}} />
    </QueryClientProvider>)
    expect(await screen.findByText('Lifecycle')).toBeInTheDocument()
    expect(screen.getByLabelText('Lifecycle token id')).toBeInTheDocument()
  })
})
