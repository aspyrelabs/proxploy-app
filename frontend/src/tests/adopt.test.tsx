import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { BulkAdoptDialog } from '../components/BulkAdoptDialog'
import type { DiscoveredRow } from '../api/hooks'

vi.mock('../api/client', () => ({ api: vi.fn() }))

const ITEMS: DiscoveredRow[] = [
  { host_id: 1, host_name: 'host-01', ctid: 200, name: 'plex', node: 'pve1', status: 'running', suggestion: 'Plex' },
]

describe('BulkAdoptDialog', () => {
  it('selects all by default and posts /apps/adopt with checked items', async () => {
    const { api } = await import('../api/client')
    vi.mocked(api).mockResolvedValue({ adopted: [1] })
    const onClose = vi.fn()
    const qc = new QueryClient()
    render(
      <QueryClientProvider client={qc}>
        <BulkAdoptDialog items={ITEMS} onClose={onClose} />
      </QueryClientProvider>,
    )
    fireEvent.click(screen.getByRole('button', { name: /Adopt 1 container/i }))
    await waitFor(() => expect(api).toHaveBeenCalledWith('/apps/adopt', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ items: [{ host_id: 1, ctid: 200, name: 'plex', catalog_slug: 'Plex' }] }),
    })))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })
})
