import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'

/**
 * The Store's app detail page.
 *
 * Two rules do most of the work in here and both are load-bearing:
 *
 *  1. A field with no data renders NOTHING. The 9 `unlisted` rows have no
 *     upstream metadata record at all and still have to produce a usable page
 *     out of discovery fields alone, so "renders the section" and "omits the
 *     section entirely" are both asserted, on the same component, from two
 *     different rows.
 *  2. The changelog is third-party markdown from GitHub release notes. It is
 *     rendered as TEXT. The test for that puts markup in the changelog and
 *     asserts it comes out as characters, because the failure mode of getting
 *     this wrong is an XSS hole, not a layout bug.
 */

// The real ApiError is kept (the page distinguishes a 404 from a dead backend
// through `instanceof`), only the transport is faked.
vi.mock('../api/client', async (orig) => ({
  ...(await orig() as object),
  api: vi.fn(),
}))
import { api } from '../api/client'

let slug = '2fauth'
vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ children }: { children?: unknown }) => <a>{children as never}</a>,
  useParams: () => ({ slug }),
}))

import { StoreDetailPage } from '../routes/store-detail'

/** A row as api/catalog.py::_serialize actually returns it, plus `raw`. The
 *  shape is deliberately the served one rather than CatalogRow's declared
 *  subset: several presentation columns are served but not yet typed there,
 *  and the page reads them defensively for exactly that reason. */
type Row = Record<string, unknown>

// Real values, copied from the dev DB's `2fauth` row: a fully covered app.
const rich: Row = {
  slug: '2fauth', name: '2FAuth', category: 'Authentication & Security', type: 'ct',
  description: '2FAuth is a web based self-hosted alternative to One Time Passcode generators.',
  icon_url: 'https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/2fauth.webp',
  popularity: 2110, popularity_synced_at: '2026-08-13T08:26:08.284465',
  website: 'https://2fauth.app/', docs_url: 'https://docs.2fauth.app/',
  default_cpu: 1, default_ram_mb: 512, default_disk_gb: 2,
  default_os: 'debian', default_os_version: '13',
  installable: true, unsupported_reason: null, upstream_state: 'listed',
  synced_at: '2026-08-13T08:00:00', script_created: null, script_updated: null,
  has_arm: null, architectures: null, updateable: null, privileged: null, port: null,
  raw: {
    ct_script: '#!/usr/bin/env bash', install_script: '#!/usr/bin/env bash',
    metadata: {
      name: '2FAuth', port: 80, privileged: false, updateable: true, has_arm: true,
      architectures: ['amd64', 'arm64'], platforms: ['pve'],
      default_user: '', default_passwd: '', config_path: 'cat /opt/2fauth/.env',
      website: 'https://2fauth.app/', documentation: 'https://docs.2fauth.app/',
      github: 'https://github.com/Bubka/2FAuth',
      repository: 'https://github.com/Bubka/2FAuth',
      last_update_commit: 'https://github.com/community-scripts/ProxmoxVE/pull/16118',
      script_created: '2024-12-20 00:00:00.000Z', script_updated: '2026-07-28 00:00:00.000Z',
      install_methods: [{
        type: 'default', script: null, config_path: 'cat /opt/2fauth/.env',
        resources: { cpu: 1, hdd: 2, os: 'Debian', ram: 512, version: '13' },
      }],
      notes: [
        { text: 'Database credentials: `cat ~/2FAuth.creds`', type: 'info' },
        { text: 'The very first account created is automatically set up as an administrator account.', type: 'info' },
      ],
      github_data: {
        version: 'v8.0.1',
        changelog: '### Fixed\r\n\r\n- [issue #558](https://github.com/Bubka/2FAuth/issues/558) docker container crashes while startup',
        github_synced_at: '2026-08-13T07:51:42.481Z',
      },
    },
  },
}

// Real values from the dev DB's `mysql` row: discovered, classified as not
// installable, and with NO upstream metadata record whatsoever.
const unlisted: Row = {
  slug: 'mysql', name: 'MySQL', category: 'Databases', type: 'ct',
  description: null, icon_url: null,
  popularity: 3524, popularity_synced_at: '2026-08-13T08:26:08.284465',
  website: 'https://www.mysql.com/products/community', docs_url: null,
  default_cpu: 1, default_ram_mb: 1024, default_disk_gb: 4,
  default_os: 'debian', default_os_version: '12',
  installable: false,
  unsupported_reason: 'install script requires interactive input, no non-interactive entrypoint',
  upstream_state: 'unlisted', synced_at: '2026-08-13T08:00:00',
  raw: { ct_script: '#!/usr/bin/env bash', install_script: '#!/usr/bin/env bash' },
}

// Real values from `syncthing`: one app, two profiles that size very
// differently, which is the entire reason profiles are listed at all.
const twoMethods: Row = {
  ...rich,
  slug: 'syncthing', name: 'Syncthing', description: null, popularity: null,
  default_cpu: 2, default_ram_mb: 2048, default_disk_gb: 8,
  raw: {
    metadata: {
      install_methods: [
        { type: 'default', script: null, config_path: null,
          resources: { cpu: 2, hdd: 8, os: 'Debian', ram: 2048, version: '13' } },
        { type: 'alpine', script: null, config_path: null,
          resources: { cpu: 1, hdd: 1, os: 'Alpine', ram: 256, version: '3.24' } },
      ],
      notes: [],
    },
  },
}

function mount(row: Row | Error) {
  vi.mocked(api).mockImplementation(() =>
    row instanceof Error ? Promise.reject(row) : Promise.resolve(row as never))
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}><StoreDetailPage /></QueryClientProvider>)
}

beforeEach(() => {
  slug = '2fauth'
  vi.mocked(api).mockReset()
})

describe('StoreDetailPage, a fully covered app', () => {
  it('renders every section the card has no room for', async () => {
    const { container } = mount(rich)
    expect(await screen.findByRole('heading', { name: '2FAuth', level: 1 })).toBeInTheDocument()
    expect(api).toHaveBeenCalledWith('/catalog/2fauth')

    // Discovery owns feasibility and the parsed defaults.
    expect(screen.getByText('Installable.')).toBeInTheDocument()
    expect(screen.getByText('Defaults from the install script')).toBeInTheDocument()
    // Twice over, and deliberately so: the script parse and upstream's own
    // published profile are two different claims that happen to agree here.
    expect(screen.getAllByText('512.0 MiB')).toHaveLength(2)
    expect(screen.getAllByText('Debian 13')).toHaveLength(2)

    // Upstream metadata owns everything below.
    expect(screen.getByText('Install profile')).toBeInTheDocument()
    expect(screen.getByText(/first account created is automatically/)).toBeInTheDocument()
    expect(screen.getByText('First run')).toBeInTheDocument()
    expect(screen.getByText('80')).toBeInTheDocument()
    // The config path lives with the profile that owns it, once, even though
    // upstream repeats it on the record itself.
    expect(screen.getAllByText('cat /opt/2fauth/.env')).toHaveLength(1)
    expect(screen.getByText('v8.0.1')).toBeInTheDocument()
    expect(screen.getByText('Runs on ARM')).toBeInTheDocument()
    expect(screen.getByText('Unprivileged container')).toBeInTheDocument()
    expect(screen.getByText('Updateable in place')).toBeInTheDocument()
    expect(screen.getByText('arm64')).toBeInTheDocument()

    // Links out, deduplicated: github and repository are the same URL here and
    // must not both be listed.
    const hrefs = Array.from(container.querySelectorAll('a[href]'))
      .map((a) => a.getAttribute('href'))
    expect(hrefs).toContain('https://2fauth.app/')
    expect(hrefs).toContain('https://docs.2fauth.app/')
    expect(hrefs).toContain('https://github.com/Bubka/2FAuth')
    expect(hrefs.filter((h) => h === 'https://github.com/Bubka/2FAuth')).toHaveLength(1)
  })

  it('shows the raw popularity figure only with its whole caveat', async () => {
    mount(rich)
    expect(await screen.findByText('2,110')).toBeInTheDocument()
    // Attempts, not installs, not a rating, and never the word "downloads".
    const caveat = screen.getByText(/Install attempts of the upstream script/)
    expect(caveat).toHaveTextContent(/failed or were cancelled/)
    expect(caveat).toHaveTextContent(/Nothing reports an uninstall/)
    expect(caveat).toHaveTextContent(/lower bound/)
    expect(caveat).toHaveTextContent(/23 hours/)
    expect(caveat).toHaveTextContent(/not a rating/)
    expect(document.body.textContent).not.toMatch(/download/i)
    // popularity_synced_at is served but not declared on CatalogRow; the page
    // reads it defensively, and this is what proves it actually arrives.
    expect(screen.getByText(/^As of /)).toBeInTheDocument()
    // Date format pinned to en-US with a worded month, identically to
    // components/StoreCard.tsx, which shows the same "as of" beside the same
    // count. Asserted as a literal, with both numeric renderings asserted
    // absent, so the two files cannot drift apart unnoticed on a machine
    // whose locale happens to match one of them.
    expect(screen.getByText(/^As of /)).toHaveTextContent('Aug 13, 2026')
    expect(document.body.textContent).not.toContain('13/8/2026')
    expect(document.body.textContent).not.toContain('8/13/2026')
  })

  const withChangelog = (changelog: string) => ({
    ...rich,
    raw: {
      ...(rich.raw as Record<string, unknown>),
      metadata: {
        ...((rich.raw as { metadata: Record<string, unknown> }).metadata),
        github_data: { version: 'v8.0.1', changelog, github_synced_at: null },
      },
    },
  })

  it('renders the changelog as markdown, not as literal syntax', async () => {
    // This used to render the raw characters in a <pre>, so readers saw
    // "### Fixed" and a bare markdown link. 504 of the 556 store-visible rows
    // carry a changelog, so that was most of them.
    const { container } = mount(withChangelog(
      '### Fixed\r\n\r\n- [issue #558](https://github.com/Bubka/2FAuth/issues/558) crash on startup\r\n- **bold** and `code`'))

    expect(await screen.findByRole('heading', { name: 'Fixed' })).toBeInTheDocument()
    expect(container.querySelector('li')).not.toBeNull()
    expect(container.querySelector('strong')?.textContent).toBe('bold')
    expect(container.querySelector('code')?.textContent).toBe('code')
    // the syntax itself is gone from the text now that it is structure
    expect(container.textContent).not.toContain('### Fixed')
    expect(container.textContent).not.toContain('](https://')
    // CRLF is still normalised; a stray carriage return breaks the parse
    expect(container.textContent).not.toContain('\r')
  })

  it('opens changelog links in a new tab, with the noreferrer pair', async () => {
    const { container } = mount(withChangelog('[issue](https://github.com/Bubka/2FAuth/issues/558)'))
    const link = await screen.findByRole('link', { name: 'issue' })
    expect(link).toHaveAttribute('href', 'https://github.com/Bubka/2FAuth/issues/558')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link.getAttribute('rel')).toContain('noreferrer')
    expect(link.getAttribute('rel')).toContain('noopener')
    expect(container.querySelector('a[href^="javascript"]')).toBeNull()
  })

  it('never executes the third-party changelog, whatever is in it', async () => {
    // The rule that did NOT change when this stopped being a <pre>. This is
    // release-note text written by whoever maintains the app upstream, so it
    // is attacker-influenced. components/ui/markdown.tsx renders React
    // elements and never an HTML string, so there is no innerHTML sink; raw
    // HTML in the source is inert because rehype-raw is deliberately absent.
    const { container } = mount(withChangelog(
      '### Fixed\r\n\r\n- <b>bold</b> <img src=x onerror="alert(1)"> gone\r\n'
      + '- <script>alert(document.cookie)</script>\r\n'
      + '- [click me](javascript:alert(1))\r\n'
      + '- [data uri](data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)'))

    await screen.findByRole('heading', { name: 'Fixed' })
    // Scoped to the changelog box: the page's own app logo is a legitimate
    // <img>, so an unscoped querySelector would find that and prove nothing.
    const log = container.querySelector('.max-h-72')!
    expect(log).not.toBeNull()
    // Raw HTML survives as characters, exactly as before.
    expect(log.textContent).toContain('<b>bold</b>')
    expect(log.textContent).toContain('<script>alert(document.cookie)</script>')
    // and never as elements
    expect(log.querySelector('b')).toBeNull()
    expect(log.querySelector('img')).toBeNull()
    expect(log.querySelector('script')).toBeNull()
    expect(log.querySelector('[onerror]')).toBeNull()
    // Dangerous schemes never reach an href. safeUrl blanks them, and a link
    // with no safe destination renders as its own words instead.
    for (const a of Array.from(log.querySelectorAll('a'))) {
      expect(a.getAttribute('href') ?? '').toMatch(/^https?:\/\//)
    }
    expect(log.textContent).toContain('click me')
    expect(log.textContent).toContain('data uri')
  })

  it('drops elements outside the allowlist but keeps their words', async () => {
    // Allowlist, not denylist: an <img> or a table is not enumerated as
    // forbidden, it simply is not in ALLOWED, so anything new upstream adds
    // is dropped by default rather than admitted by default.
    const { container } = mount(withChangelog('![shot](https://example.com/x.png)\n\nafter'))
    await screen.findByText('after')
    const log = container.querySelector('.max-h-72')!
    expect(log.querySelector('img')).toBeNull()
    // An image has no child nodes to unwrap (its alt is an attribute, not a
    // child), so it drops entirely rather than leaving its alt text behind.
    // Prose around it is untouched, which is the property that matters: one
    // unsupported node does not blank the whole changelog.
    expect(log.textContent).toContain('after')
  })

})

describe('StoreDetailPage, a row with no upstream metadata', () => {
  it('renders a usable page from discovery alone and omits every empty section', async () => {
    slug = 'mysql'
    mount(unlisted)
    expect(await screen.findByRole('heading', { name: 'MySQL', level: 1 })).toBeInTheDocument()

    // Discovery still has plenty to say.
    expect(screen.getByText(/Not installable/)).toBeInTheDocument()
    expect(screen.getByText(/requires interactive input/)).toBeInTheDocument()
    expect(screen.getByText('1.0 GiB')).toBeInTheDocument()
    expect(screen.getByText('Debian 12')).toBeInTheDocument()
    // A served column with no upstream record behind it still links out.
    expect(screen.getByText('Website')).toBeInTheDocument()
    // Upstream stopped listing it, which the page says without calling the
    // app dead.
    expect(screen.getByText(/no longer lists this app/)).toBeInTheDocument()

    // Nothing upstream-owned may render a heading over an empty body.
    for (const gone of ['Install profile', 'Install profiles', 'Before and after you install',
                        'First run', 'Upstream release', 'Container']) {
      expect(screen.queryByText(gone)).toBeNull()
    }
    // And no placeholder VALUES anywhere: nothing renders "unknown", "none",
    // "null" or a lone dash where it has no data. (Exact-text queries, so the
    // popularity caveat's prose "unknown multiple" is not what is being
    // matched here; a KV cell reading "unknown" is.)
    for (const placeholder of ['unknown', 'Unknown', 'none', 'null', '—', '-', 'n/a']) {
      expect(screen.queryByText(placeholder)).toBeNull()
    }
  })
})

describe('StoreDetailPage, install profiles', () => {
  it('renders both profiles of a two-method app with their own sizing', async () => {
    slug = 'syncthing'
    const { container } = mount(twoMethods)
    expect(await screen.findByText('Install profiles')).toBeInTheDocument()
    expect(screen.getByText('default')).toBeInTheDocument()
    expect(screen.getByText('alpine')).toBeInTheDocument()
    // 2 GiB Debian next to 256 MiB Alpine: the figures that differ are the
    // reason both are shown. The 2 GiB appears twice, once as the profile and
    // once as the script parse's own default.
    expect(screen.getAllByText('2.0 GiB')).toHaveLength(2)
    expect(screen.getByText('256.0 MiB')).toBeInTheDocument()
    expect(screen.getByText('Alpine 3.24')).toBeInTheDocument()
    // `install_methods[].script` is null in the real data and must never be
    // printed as the word "null".
    expect(container.textContent).not.toContain('null')
  })

  it('drops a profile whose figures are all zero rather than claiming 0 vCPU', async () => {
    slug = 'coolify'
    mount({
      ...twoMethods, slug: 'coolify', name: 'Coolify',
      default_cpu: null, default_ram_mb: null, default_disk_gb: null,
      default_os: null, default_os_version: null,
      raw: { metadata: { install_methods: [{ type: 'default', script: null, config_path: null,
                                             resources: { cpu: 0, hdd: 0, ram: 0 } }] } },
    })
    expect(await screen.findByRole('heading', { name: 'Coolify', level: 1 })).toBeInTheDocument()
    expect(screen.queryByText('Install profile')).toBeNull()
    expect(screen.queryByText('Defaults from the install script')).toBeNull()
    expect(document.body.textContent).not.toContain('0 GB')
  })

  it('renders nothing at all for a null popularity, not a zero', async () => {
    slug = 'syncthing'
    mount(twoMethods)
    expect(await screen.findByText('Install profiles')).toBeInTheDocument()
    expect(screen.queryByText('Reported installs')).toBeNull()
    expect(screen.queryByText('0')).toBeNull()
    expect(document.body.textContent).not.toMatch(/install attempts/i)
  })
})

describe('StoreDetailPage, states other than a loaded row', () => {
  it('says feasibility is unknown rather than "not installable" while it is', async () => {
    mount({ ...rich, installable: null, unsupported_reason: null })
    expect(await screen.findByText(/has not been able to confirm/)).toBeInTheDocument()
    expect(screen.queryByText(/^Not installable/)).toBeNull()
    expect(screen.getByRole('button', { name: 'Check again' })).toBeInTheDocument()
  })

  it('renders a not-found page for an unknown slug, naming it', async () => {
    slug = 'nope'
    mount(new ApiError(404, { detail: 'not found' }))
    expect(await screen.findByText(/No app called/)).toBeInTheDocument()
    expect(screen.getByText(/nope/)).toBeInTheDocument()
    // A 404 is not "the backend is unreachable" and must not say so.
    expect(document.body.textContent).not.toMatch(/could not reach the backend/i)
  })

  it('distinguishes an unreachable backend from a missing slug', async () => {
    mount(new ApiError(500, null))
    await waitFor(() =>
      expect(screen.getByText(/could not reach the backend/i)).toBeInTheDocument())
    expect(screen.queryByText(/No app called/)).toBeNull()
  })
})
