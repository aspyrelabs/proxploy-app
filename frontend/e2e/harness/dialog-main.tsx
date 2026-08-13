import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createRoot } from 'react-dom/client'
import { StoreDetailContent } from '../../src/components/StoreDetailContent'
import { Dialog } from '../../src/components/ui/dialog'
import './harness.css'

/**
 * Geometry harness for the App Store's detail POPUP, the sibling of
 * main.tsx's card harness and there for the same reason: jsdom has no layout
 * engine, so nothing in vitest can tell whether a panel is taller than the
 * screen or whether its body actually scrolls.
 *
 * The popup shipped uncapped and grew to its content, which is the whole
 * detail page. Anything taller than the viewport also stops being centred,
 * because `place-items-center` has no free space left to distribute, so it
 * overhung the top of the screen with no way to scroll back up to it.
 *
 * The backend is not running here and /store is behind login anyway, so the
 * page stubs `fetch` rather than mocking modules: StoreDetailContent goes
 * through api/client, which is a thin wrapper over fetch('/api/v1' + path).
 * The fixture is deliberately a FULLY POPULATED row, since a sparse one
 * renders a short page and would not test the cap at all.
 */

const META = {
  name: 'Plex Media Server', port: 32400, privileged: false, updateable: true, has_arm: true,
  architectures: ['amd64', 'arm64'], platforms: ['pve'],
  default_user: 'plex', default_passwd: 'changeme', config_path: 'cat /opt/plex/.env',
  website: 'https://www.plex.tv/', documentation: 'https://support.plex.tv/articles/',
  github: 'https://github.com/plexinc', repository: 'https://github.com/plexinc',
  last_update_commit: 'https://github.com/community-scripts/ProxmoxVE/pull/16118',
  script_created: '2024-05-02 00:00:00.000Z', script_updated: '2026-06-11 00:00:00.000Z',
  notes: [
    { text: 'Claim the server from the LAN before exposing it, or the setup wizard locks you out.', type: 'info' },
    { text: 'Hardware transcoding needs the host GPU passed through to the container.', type: 'warning' },
    { text: 'The default library paths live under /mnt and are not created for you.', type: 'info' },
  ],
  install_methods: [
    { type: 'default', script: null, config_path: 'cat /opt/plex/.env',
      resources: { cpu: 2, hdd: 8, os: 'Debian', ram: 2048, version: '13' } },
    { type: 'alpine', script: null, config_path: 'cat /opt/plex/.env',
      resources: { cpu: 1, hdd: 3, os: 'Alpine', ram: 1024, version: '3.24' } },
  ],
  github_data: {
    version: 'v1.41.2', published_at: '2026-06-11T00:00:00Z',
    body: '## Fixed\n- Transcoding no longer stalls on 4K HDR sources\n- Library scans respect the ignore list\n\n## Changed\n- Bumped the bundled ffmpeg\n- Reduced idle memory use by about 12%\n',
  },
}

const ENTRY = {
  slug: 'plex', name: 'Plex Media Server', category: 'Media & Streaming', type: 'ct',
  description: 'Plex organizes all of your personal media so you can enjoy it no matter where you are, on any device.',
  icon_url: null, popularity: 126196, popularity_synced_at: '2026-08-13T00:00:00',
  website: 'https://www.plex.tv/', docs_url: 'https://support.plex.tv/articles/',
  default_cpu: 2, default_ram_mb: 2048, default_disk_gb: 8,
  default_os: 'debian', default_os_version: '13',
  installable: true, unsupported_reason: null, upstream_state: 'listed',
  synced_at: '2026-08-13T08:00:00',
  script_created: '2024-05-02T00:00:00', script_updated: '2026-06-11T00:00:00',
  has_arm: true, updateable: true, privileged: false,
  architectures: ['amd64', 'arm64'], port: 32400,
  raw: { ct_script: '#!/usr/bin/env bash', install_script: '#!/usr/bin/env bash', metadata: META },
}

const json = (body: unknown) =>
  new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } })

window.fetch = (input: RequestInfo | URL) => {
  const url = String(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url)
  if (url.includes('/api/v1/catalog/')) return Promise.resolve(json(ENTRY))
  if (url.includes('/api/v1/apps')) return Promise.resolve(json([]))
  return Promise.resolve(json(null))
}

const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })

createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={qc}>
    <Dialog title="Plex Media Server" width={936} scrollBody onClose={() => {}}>
      <StoreDetailContent slug="plex" onInstall={() => {}} />
    </Dialog>
  </QueryClientProvider>,
)
