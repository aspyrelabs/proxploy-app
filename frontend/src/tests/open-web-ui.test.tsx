import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { notifyError } = vi.hoisted(() => ({ notifyError: vi.fn() }))
vi.mock('../lib/notify', () => ({
  notify: { error: notifyError, success: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

// Both `ip` and `web_protocol` here are deliberately WRONG for the URL the
// backend resolves below: `ip` is the row's own (effectively always-stale,
// see api/apps.py::_app_out) cached address, and `web_protocol` is the "http"
// that used to be written onto every app whether or not it was true. A test
// that read either by mistake opens the wrong place and fails loudly instead
// of passing by coincidence.
const APP = {
  id: 1, name: 'Immich', slug: 'immich', host_id: 1, host_name: 'pve-a',
  node: 'pve-a', ctid: 150, category: null, catalog_slug: 'immich',
  icon_initials: 'IM', icon_colors: null, web_port: null, web_protocol: 'http',
  web_path: '/', installed_url: null, catalog_port: 8096 as number | null,
  status: 'running', ip: '10.0.0.5', cpu_pct: null, icon_url: null,
  mem_bytes: null, mem_total_bytes: null, uptime_s: null,
  disk_bytes: null, disk_total_bytes: null,
  net_in_bps: null, net_out_bps: null,
  update_available: null, adopted: true,
}

const calls: string[] = []

vi.mock('../api/client', () => ({
  api: vi.fn((path: string) => {
    calls.push(path)
    if (path === '/apps/1') return Promise.resolve({ ...APP })
    if (path === '/entitlements') {
      return Promise.resolve({
        tier: 'builtin', grace: null, clock_skew: false,
        features: { 'apps.open_ui': true, 'apps.lifecycle': true },
      })
    }
    // The whole URL comes from the backend now: it reads the guest's address
    // live AND asks the app itself whether it speaks http or https, neither
    // of which this page can do. The scheme is the half that was wrong, so
    // the fixture serves https, the way Actual Budget really answers.
    if (path === '/apps/1/web-url') {
      if (webUrlError) return Promise.reject(webUrlError)
      return Promise.resolve({ url: webUrl, protocol: 'https',
                               protocol_decided_by: 'asked the app' })
    }
    return Promise.resolve(null)
  }),
  ApiError: class extends Error {},
  apiErrorDetail: (_e: unknown, fallback: string) => errorDetail ?? fallback,
}))

let webUrl = 'https://10.9.9.9:5006/'
let webUrlError: Error | null = null
let errorDetail: string | null = null

vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  useNavigate: () => () => {},
  useSearch: () => ({}),
}))

// The app detail PAGE is gone; the Open button lives on the action bar every
// app row carries, using the same useOpenWebUi call the page used to make.
import { AppActionBar } from '../components/AppActionBar'
import type { AppRow } from '../api/hooks'

const withQuery = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('AppActionBar Open', () => {
  beforeEach(() => {
    calls.length = 0
    webUrl = 'https://10.9.9.9:5006/'
    webUrlError = null
    errorDetail = null
    notifyError.mockClear()
  })

  it('opens the URL the backend resolved, keeping the https it found', async () => {
    // The bug: this used to be built in the browser as
    // `${app.web_protocol || 'http'}` over an address fetched from /network,
    // and every row said "http" because install and adopt wrote that string
    // whether or not it was true. Actual Budget serves https on 5006, so
    // Open landed on a page that could not load. Nothing on the row decides
    // this any more, which is why the fixture's own web_protocol still says
    // "http" and the tab must still go to https.
    APP.catalog_port = 5006
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)
    withQuery(<AppActionBar app={APP as AppRow} />)

    fireEvent.click(await screen.findByRole('button', { name: 'Open' }))

    await waitFor(() => expect(calls).toContain('/apps/1/web-url'))
    await waitFor(() => expect(openSpy).toHaveBeenCalledWith(
      'https://10.9.9.9:5006/', '_blank', 'noopener,noreferrer'))
    // And the address is not read off the row either: APP.ip is deliberately
    // a different address from the one the backend resolved live.
    expect(calls).not.toContain('/apps/1/network')
    openSpy.mockRestore()
  })

  it('says what actually went wrong when no URL could be built', async () => {
    // The backend's 409 names the real reason ("did not answer ... cannot
    // tell whether it uses http or https"), which is the point of refusing
    // rather than guessing, so it has to reach the operator rather than be
    // flattened into one generic sentence.
    webUrlError = new Error('API 409')
    errorDetail = 'Immich did not answer at 10.9.9.9:5006, so Proxploy cannot tell'
    APP.catalog_port = 5006
    const close = vi.fn()
    const openSpy = vi.spyOn(window, 'open')
      .mockImplementation(() => ({ close } as unknown as Window))
    withQuery(<AppActionBar app={APP as AppRow} />)

    fireEvent.click(await screen.findByRole('button', { name: 'Open' }))
    await waitFor(() => expect(notifyError).toHaveBeenCalledWith(errorDetail))
    // The blank tab the click opened is closed, not left on about:blank.
    expect(close).toHaveBeenCalled()
    openSpy.mockRestore()
  })

  it('hides the action entirely when nothing names a port', async () => {
    APP.catalog_port = null
    withQuery(<AppActionBar app={APP as AppRow} />)

    // The overflow menu is always there, so its arrival is what proves the
    // bar has rendered rather than the assertion below passing on an empty
    // tree.
    await screen.findByRole('button', { name: /More actions/ })
    expect(screen.queryByRole('button', { name: 'Open' })).not.toBeInTheDocument()
  })
})
