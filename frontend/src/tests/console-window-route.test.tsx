/** The node shell, after it stopped being a greyed-out button on the page.
 *
 *  It is now a control in the host page header beside "Open Proxmox web UI",
 *  always visible, which opens a Proxploy-hosted terminal in its own window.
 *  The two gates it used to hide behind a tooltip (the per-host opt-in and the
 *  terminal.node entitlement) are now said out loud when the control is used,
 *  because a tooltip is invisible on touch and easy to miss, which is exactly
 *  how the grey button ended up confusing.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/client', () => ({
  api: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number
    body: unknown
    constructor(status: number, body: unknown) { super('api'); this.status = status; this.body = body }
  },
}))
import { api } from '../api/client'

const { toastError } = vi.hoisted(() => ({ toastError: vi.fn() }))
vi.mock('../lib/notify', () => ({
  notify: { error: toastError, success: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  // The window route is /shell/$kind/$id now; one route serves the node
  // shell, the app console and the VM console.
  useParams: () => params,
  useNavigate: () => vi.fn(),
  useSearch: () => ({}),
  Link: ({ children }: { children?: unknown }) => <a>{children as never}</a>,
  Outlet: () => null,
}))

// The window route is /shell/$kind/$id: one route serves the node shell, the
// app console and the VM console. Mutable so a test can point it at each.
// Carries hostId/node as well: the host-page tests further down render the
// hosts route through this same useParams mock.
const DEFAULT_PARAMS = { hostId: '7', node: 'pve1', kind: 'host', id: '7' }
let params: Record<string, string> = { ...DEFAULT_PARAMS }

// xterm needs a real canvas and noVNC needs a socket; the window under test
// only has to prove WHICH renderer it mounts, never that either one drew.
vi.mock('../components/terminal/Terminal', () => ({
  Terminal: () => <div data-testid="terminal" />,
}))
vi.mock('../components/console/VncConsole', () => ({
  VncConsole: () => <div data-testid="vnc" />,
}))

const withQuery = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

let shellEnabled = true
let features: Record<string, boolean> = { 'terminal.node': true }

beforeEach(() => {
  params = { ...DEFAULT_PARAMS }
  shellEnabled = true
  features = { 'terminal.node': true }
  toastError.mockClear()
  vi.mocked(api).mockImplementation((path: string) => {
    if (path.includes('/entitlements')) {
      return Promise.resolve({ tier: 'pro', features, grace: null, clock_skew: false })
    }
    if (path === '/hosts/7') {
      return Promise.resolve({ id: 7, name: 'pve1', address: 'https://10.0.0.5:8006',
                               node_shell_enabled: shellEnabled })
    }
    return Promise.resolve([])
  })
})

describe('the node shell control', () => {
  it('is gone from the page body, and lives in the header instead', async () => {
    const { NodeDetailPage, NodeOverview } = await import('../routes/hosts')
    const { unmount } = withQuery(<NodeOverview />)
    await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalled())
    expect(screen.queryByRole('heading', { name: /node shell/i })).not.toBeInTheDocument()
    unmount()

    withQuery(<NodeDetailPage />)
    expect(await screen.findByRole('button', { name: /node shell/i })).toBeInTheDocument()
  })

  it('sits beside the Proxmox web UI link, and is never greyed out', async () => {
    shellEnabled = false
    features = { 'terminal.node': false }
    const { NodeDetailPage } = await import('../routes/hosts')
    withQuery(<NodeDetailPage />)
    expect(await screen.findByRole('link', { name: /proxmox web ui/i })).toBeInTheDocument()
    // Both gates shut, and it is STILL enabled: the whole point is that it
    // says why rather than going quietly grey.
    expect(await screen.findByRole('button', { name: /node shell/i })).toBeEnabled()
  })

  it('opens the shell in its own window when both gates are open', async () => {
    const open = vi.fn()
    vi.stubGlobal('open', open)
    const { NodeDetailPage } = await import('../routes/hosts')
    withQuery(<NodeDetailPage />)
    await screen.findByRole('link', { name: /proxmox web ui/i })
    fireEvent.click(screen.getByRole('button', { name: /node shell/i }))
    await waitFor(() => expect(open).toHaveBeenCalled())
    expect(String(open.mock.calls[0][0])).toBe('/shell/host/7')
    vi.unstubAllGlobals()
  })

  it('says node shells are off for this host, and where to switch them on', async () => {
    shellEnabled = false
    const open = vi.fn()
    vi.stubGlobal('open', open)
    const { NodeDetailPage } = await import('../routes/hosts')
    withQuery(<NodeDetailPage />)
    // wait for the host detail to land, otherwise the gate is merely unknown
    await screen.findByRole('link', { name: /proxmox web ui/i })
    fireEvent.click(screen.getByRole('button', { name: /node shell/i }))
    await waitFor(() => expect(toastError).toHaveBeenCalled())
    // The title says what is wrong, the description says where to fix it. Both
    // are asserted because splitting them is exactly how the "where" could get
    // dropped without a test noticing.
    expect(String(toastError.mock.calls[0][0])).toMatch(/switched off/i)
    expect(String(toastError.mock.calls[0][1]?.description)).toMatch(/settings/i)
    // and no dead window: a blank popup is the failure mode being complained about
    expect(open).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })

  it('names the plan when the entitlement is what is missing', async () => {
    // Both gates shut, so no click can open a window whatever the timing;
    // the entitlement is the outer gate and is what gets named.
    features = { 'terminal.node': false }
    shellEnabled = false
    const open = vi.fn()
    vi.stubGlobal('open', open)
    const { NodeDetailPage } = await import('../routes/hosts')
    withQuery(<NodeDetailPage />)
    const btn = await screen.findByRole('button', { name: /node shell/i })
    await waitFor(() => {
      fireEvent.click(btn)
      expect(String(toastError.mock.lastCall?.[0])).toMatch(/plan|pro/i)
    })
    expect(open).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })
})

describe('the node shell window', () => {
  it('renders a terminal once a ticket is minted', async () => {
    vi.mocked(api).mockImplementation((path: string) => {
      if (path.endsWith('/shell/tickets')) {
        return Promise.resolve({ ticket: 'abc', expires_at: '2026-01-01T00:00:00Z' })
      }
      return Promise.resolve({ id: 7, name: 'pve1' })
    })
    const { ConsoleWindow } = await import('../routes/console-window')
    withQuery(<ConsoleWindow />)
    expect(await screen.findByTestId('terminal')).toBeInTheDocument()
  })

  it('names Sys.Console when Proxmox is the one refusing', async () => {
    const { ApiError } = await import('../api/client')
    vi.mocked(api).mockImplementation((path: string) => {
      if (path.endsWith('/shell/tickets')) {
        return Promise.reject(new ApiError(409, 'permission denied on /nodes/pve1'))
      }
      return Promise.resolve({ id: 7, name: 'pve1' })
    })
    const { ConsoleWindow } = await import('../routes/console-window')
    withQuery(<ConsoleWindow />)
    expect(await screen.findByText(/Sys\.Console/)).toBeInTheDocument()
  })

  it('explains the per-host opt-in rather than showing a blank window', async () => {
    const { ApiError } = await import('../api/client')
    vi.mocked(api).mockImplementation((path: string) => {
      if (path.endsWith('/shell/tickets')) {
        return Promise.reject(new ApiError(409, 'node shell is not enabled for this host'))
      }
      return Promise.resolve({ id: 7, name: 'pve1' })
    })
    const { ConsoleWindow } = await import('../routes/console-window')
    withQuery(<ConsoleWindow />)
    expect(await screen.findByText(/not enabled for this host/i)).toBeInTheDocument()
  })
})


describe('one window route, three kinds', () => {
  it('mounts a terminal for a host and for an app', async () => {
    const { ConsoleWindow } = await import('../routes/console-window')
    for (const kind of ['host', 'app']) {
      params = { ...DEFAULT_PARAMS, kind, id: '42' }
      const { unmount } = withQuery(<ConsoleWindow />)
      expect(await screen.findByTestId('terminal')).toBeInTheDocument()
      // The ticket is minted for the kind in the URL, not always for a host.
      expect(vi.mocked(api).mock.calls.some(
        (c) => String(c[0]).includes(`/${kind}s/42/console/ticket`)
          || String(c[0]).includes(`/${kind === 'host' ? 'hosts' : 'apps'}/42/`),
      )).toBe(true)
      unmount()
    }
  })

  it('mounts VNC for a VM, because a VM console is a screen and not a shell', async () => {
    params = { ...DEFAULT_PARAMS, kind: 'vm', id: '9' }
    const { ConsoleWindow } = await import('../routes/console-window')
    withQuery(<ConsoleWindow />)
    expect(await screen.findByTestId('vnc')).toBeInTheDocument()
    expect(screen.queryByTestId('terminal')).toBeNull()
  })

  it('refuses a kind it does not serve rather than guessing one', async () => {
    // The address bar is reachable; a typo must not silently open a console
    // against some other object with the same id.
    params = { ...DEFAULT_PARAMS, kind: 'switch', id: '9' }
    const { ConsoleWindow } = await import('../routes/console-window')
    withQuery(<ConsoleWindow />)
    expect(await screen.findByText(/no such console/i)).toBeInTheDocument()
    expect(screen.queryByTestId('terminal')).toBeNull()
    expect(screen.queryByTestId('vnc')).toBeNull()
  })
})
