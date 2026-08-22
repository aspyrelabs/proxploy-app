import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
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
    // Radix's FocusScope queues its unmount-auto-focus event on a timer that
    // outlives the closed dialog. Left pending at the end of this FILE, it
    // fires during the next file's run, by which point jsdom has swapped
    // realms and the dispatch throws "parameter 1 is not of type 'Event'" as
    // an unhandled error attributed to whichever file happened to be running.
    // Draining it here keeps that timer inside the lifetime of the dialog
    // that scheduled it.
    await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
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
        { kind: 'app', id: 1, label: 'Plex', sublabel: 'host-01 · CT 150', href: '/apps?open=1', status: 'running' },
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
    // An app is a row that expands on the Apps table now, so its href carries
    // a query. Router navigate takes the path and the search separately: a
    // `to` of "/apps?open=1" would be looked up as a route by that literal
    // name and match nothing.
    expect(navigateMock).toHaveBeenCalledWith({ to: '/apps', search: { open: '1' } })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('finds a store entry the server matched on its description', async () => {
    // This assertion used to live in store.test.tsx, against the App Store's
    // own search box, which is gone. The capability moved to GET /search,
    // which matches name OR slug OR description (api/search.py), so what the
    // frontend has to prove now is that a store row the server returned for a
    // description match actually reaches the operator's eyes.
    searchResults = {
      query: 'organizes',
      results: [
        { kind: 'store', id: 'plex', label: 'Plex Media Server',
          sublabel: 'Media & Streaming', href: '/store/plex', status: null },
      ],
    }
    withQuery(<CommandPalette />)
    openViaShortcut()
    fireEvent.change(await screen.findByRole('combobox'), { target: { value: 'organizes' } })

    await waitFor(() => expect(api).toHaveBeenCalledWith('/search?q=organizes'))
    expect(await screen.findByText('Store')).toBeInTheDocument()
    expect(screen.getByText('Plex Media Server')).toBeInTheDocument()
  })

  it('opens on Ctrl+K with neither entitlement, showing the plan message instead of doing nothing', async () => {
    features = { 'ui.global_search': false, 'store.catalog': false }
    withQuery(<CommandPalette />)
    openViaShortcut()
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(await screen.findByText(/not included in your plan/i)).toBeInTheDocument()
    expect(screen.getByRole('combobox')).toBeDisabled()
  })

  it('stays usable for a store-only plan, and says so instead of refusing', async () => {
    // The App Store's own search box never checked ui.global_search, and it
    // has been removed. Showing this plan a flat "not included" would be a
    // capability taken away and called a cleanup, so the palette degrades to
    // store-only rather than to nothing (api/search.py gates per group).
    features = { 'ui.global_search': false, 'store.catalog': true }
    searchResults = {
      query: 'plex',
      results: [
        { kind: 'store', id: 'plex', label: 'Plex Media Server',
          sublabel: 'Media & Streaming', href: '/store/plex', status: null },
      ],
    }
    withQuery(<CommandPalette />)
    openViaShortcut()

    const input = await screen.findByRole('combobox')
    await waitFor(() => expect(input).toBeEnabled())
    // The copy promises the store and nothing else, in the placeholder and in
    // the standing note, rather than offering the whole fleet and quietly
    // returning one group.
    expect(input).toHaveAttribute('placeholder', expect.stringMatching(/store/i))
    expect(input).not.toHaveAttribute('placeholder', expect.stringMatching(/VMs/i))
    expect(screen.getByText(/apps, vms and hosts need global search/i)).toBeInTheDocument()
    expect(screen.queryByText(/upgrade to search apps/i)).toBeNull()

    fireEvent.change(input, { target: { value: 'plex' } })
    await waitFor(() => expect(api).toHaveBeenCalledWith('/search?q=plex'))
    expect(await screen.findByText('Plex Media Server')).toBeInTheDocument()
  })

  it('leaves a full plan untouched, with the whole fleet in the copy', async () => {
    features = { 'ui.global_search': true, 'store.catalog': true }
    withQuery(<CommandPalette />)
    openViaShortcut()
    const input = await screen.findByRole('combobox')
    expect(input).toBeEnabled()
    expect(input).toHaveAttribute('placeholder', expect.stringMatching(/apps, vms, hosts/i))
    expect(screen.queryByText(/need global search/i)).toBeNull()
    expect(screen.getByText(/type to search across the fleet/i)).toBeInTheDocument()
  })
})


describe('CommandPalette reaches Settings sections', () => {
  beforeEach(() => {
    features = { 'ui.global_search': true }
    searchResults = { query: '', results: [] }
    navigateMock.mockClear()
    vi.mocked(api).mockClear()
  })

  const type = (v: string) => {
    withQuery(<CommandPalette />)
    openViaShortcut()
    fireEvent.change(screen.getByRole('combobox'), { target: { value: v } })
  }

  it('jumps straight to a section, by its ?section= URL', async () => {
    type('updates')
    fireEvent.click(await screen.findByRole('option', { name: /Updates/ }))
    expect(navigateMock).toHaveBeenCalledWith(
      { to: '/settings', search: { section: 'updates' } })
  })

  it('finds Profile by what is inside it, not only by its name', async () => {
    // The whole reason the section table carries keywords: merging Two-factor,
    // Sessions and Trusted devices under "Profile" took all three names out of
    // the rail, so without these the merge would have cost an operator every
    // way of finding them.
    for (const term of ['trusted devices', '2fa', 'recovery codes', 'sign out']) {
      const { unmount } = withQuery(<CommandPalette />)
      openViaShortcut()
      fireEvent.change(screen.getByRole('combobox'), { target: { value: term } })
      expect(await screen.findByRole('option', { name: /Profile/ }),
             `"${term}" should reach Profile`).toBeInTheDocument()
      unmount()
    }
  })

  it('answers before the fleet search does, and asks the backend nothing', () => {
    type('console')
    // On screen with no debounce and no round trip: the 250ms wait exists for
    // the server's LIKE scan, and a section has nothing to scan.
    expect(screen.getByRole('option', { name: /Console/ })).toBeInTheDocument()
    expect(vi.mocked(api).mock.calls.some(([path]) =>
      String(path).startsWith('/search'))).toBe(false)
  })

  it('does not say "no results" above a section it just listed', async () => {
    type('plan')
    await waitFor(() =>
      expect(screen.getByRole('option', { name: /Plan/ })).toBeInTheDocument())
    expect(screen.queryByText(/no results for/i)).toBeNull()
    expect(screen.queryByText('Searching…')).toBeNull()
  })

  it('still says "no results" when nothing matched anywhere', async () => {
    type('zzzznothing')
    expect(await screen.findByText(/no results for/i)).toBeInTheDocument()
  })
})
