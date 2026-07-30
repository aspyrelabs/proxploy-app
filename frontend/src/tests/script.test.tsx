import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ScriptPanel } from '../components/ScriptPanel'

vi.mock('../api/client', () => ({ api: vi.fn() }))

describe('ScriptPanel', () => {
  it('renders the pinned script content and its source', async () => {
    const { api } = await import('../api/client')
    vi.mocked(api).mockResolvedValue({
      version: 1, content: 'msg_ok done\n', source: 'upstream', diff_vs_upstream: null,
    })
    const qc = new QueryClient()
    render(
      <QueryClientProvider client={qc}>
        <ScriptPanel appId={1} />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(screen.getByText(/msg_ok done/)).toBeInTheDocument())
    expect(screen.getByText(/version 1 · upstream/i)).toBeInTheDocument()
    expect(screen.getByText(/matches upstream/i)).toBeInTheDocument()
  })

  it('shows the real diff banner and diff body when the pinned script has drifted', async () => {
    const { api } = await import('../api/client')
    const diff = '--- upstream\n+++ pinned\n@@ -1 +1 @@\n-msg_ok done\n+msg_ok edited\n'
    vi.mocked(api).mockResolvedValue({
      version: 2, content: 'msg_ok edited\n', source: 'edited', diff_vs_upstream: diff,
    })
    const qc = new QueryClient()
    render(
      <QueryClientProvider client={qc}>
        <ScriptPanel appId={1} />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(screen.getByText(/differs from upstream/i)).toBeInTheDocument())
    expect(screen.getByText(/-msg_ok done/)).toBeInTheDocument()
    expect(screen.getByText(/\+msg_ok edited/)).toBeInTheDocument()
  })
})
