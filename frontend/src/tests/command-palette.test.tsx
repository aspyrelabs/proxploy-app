import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

let features: Record<string, boolean> = { 'ui.global_search': true }
let searchResults: { query: string; results: unknown[] } = { query: '', results: [] }

vi.mock('../api/client', () => ({
  api: vi.fn((path: string) => {
    if (path === '/entitlements') return Promise.resolve({ tier: 'builtin', features, grace: null, clock_skew: false })
    if (path.startsWith('/search')) return Promise.resolve(searchResults)
    return Promise.resolve(null)
  }),
  ApiError: class extends Error {},
}))

const navigateMock = vi.fn()
vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  useNavigate: () => navigateMock,
}))

import { api } from '../api/client'
import { CommandPalette } from '../components/CommandPalette'

const withQuery = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const openViaShortcut = () => fireEvent.keyDown(window, { key: 'k', ctrlKey: true })

// Ctrl+K is still the component's own window listener. Escape is not: Radix
// dismisses the dialog from a document-level handler, and an event dispatched
// at window never reaches document, so this has to fire inside the tree.
const closeViaEscape = () => fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' })

describe('CommandPalette', () => {
  beforeEach(() => {
    features = { 'ui.global_search': true }
    searchResults = { query: '', results: [] }
    navigateMock.mockClear()
    vi.mocked(api).mockClear()
  })

  // Every test closes the palette before returning; `paletteOpen` is a
  // module-level flag shared across renders in this file, so leaving it open
  // would leak into the next test's initial state.
  afterEach(async () => {
    closeViaEscape()
    // Closing now settles through a Radix effect rather than synchronously, so
    // the module-level flag is not clear until the next tick.
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('opens on Ctrl+K and closes on Escape', async () => {
    withQuery(<CommandPalette />)
    expect(screen.queryByRole('dialog')).toBeNull()

    openViaShortcut()
    expect(await screen.findByRole('dialog')).toBeInTheDocument()

    closeViaEscape()
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('fires no request for a query under 2 characters', async () => {
    withQuery(<CommandPalette />)
    openViaShortcut()
    const input = await screen.findByRole('combobox')
    fireEvent.change(input, { target: { value: 'p' } })

    // Debounce is 250ms; wait past it and confirm /search was never called.
    await new Promise((r) => setTimeout(r, 350))
    expect(vi.mocked(api).mock.calls.some(([p]) => String(p).startsWith('/search'))).toBe(false)
  })

  it('renders results grouped by kind and Enter navigates to the selected href', async () => {
    searchResults = {
      query: 'plex',
      results: [
        { kind: 'app', id: 1, label: 'Plex', sublabel: 'host-01 · CT 150', href: '/apps/1', status: 'running' },
        { kind: 'vm', id: 2, label: 'plex-vm', sublabel: 'host-02', href: '/vms/2', status: null },
      ],
    }
    withQuery(<CommandPalette />)
    openViaShortcut()
    const input = await screen.findByRole('combobox')
    fireEvent.change(input, { target: { value: 'plex' } })

    await waitFor(() => expect(api).toHaveBeenCalledWith('/search?q=plex'))
    expect(await screen.findByText('Apps')).toBeInTheDocument()
    expect(screen.getByText('VMs')).toBeInTheDocument()
    expect(screen.getByText('Plex')).toBeInTheDocument()
    expect(screen.getByText('plex-vm')).toBeInTheDocument()

    fireEvent.keyDown(input, { key: 'Enter' })
    expect(navigateMock).toHaveBeenCalledWith({ to: '/apps/1' })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('opens on Ctrl+K even without the entitlement, showing the plan message instead of doing nothing', async () => {
    features = { 'ui.global_search': false }
    withQuery(<CommandPalette />)
    openViaShortcut()
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(await screen.findByText(/not included in your plan/i)).toBeInTheDocument()
    expect(screen.getByRole('combobox')).toBeDisabled()
  })
})
