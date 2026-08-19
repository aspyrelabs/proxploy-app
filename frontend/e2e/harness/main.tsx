import { createRoot } from 'react-dom/client'
import type { CatalogRow } from '../../src/api/catalog'
import { StoreCard, StoreCardSkeleton } from '../../src/components/StoreCard'
import './harness.css'

/**
 * Geometry harness for StoreCard. NOT part of the app: it lives under e2e/,
 * builds with its own Vite config into e2e/harness/dist (gitignored), and is
 * never imported by src/, so it cannot reach the shipped bundle.
 *
 * WHY IT EXISTS. StoreCard has a fixed height, and the 224px version shipped
 * with its own text overlapping through a fully green vitest suite. jsdom has
 * no layout engine: getBoundingClientRect returns zeroes there, so every
 * height assertion in store.test.tsx compares CLASS NAMES. This renders the
 * real component with the real stylesheet in real Chromium, where
 * scrollHeight and offsetHeight mean something.
 *
 * It renders the states that actually stress the fixed height, not a happy
 * path, and it reproduces the shell's lane (a 236px sidebar plus main's p-6)
 * so the column count and the chip row's single-line behaviour match the app
 * at each viewport width.
 */

const BASE: CatalogRow = {
  slug: 'redis', name: 'Redis', category: 'Databases', type: 'ct',
  description: 'Redis is an open source, in-memory data structure store used as a database, cache and message broker.',
  icon_url: null, popularity: 2110, website: 'https://redis.io/', docs_url: null,
  default_cpu: 1, default_ram_mb: 1024, default_disk_gb: 4,
  default_os: 'debian', default_os_version: '13',
  installable: true, unsupported_reason: null, upstream_state: 'listed', synced_at: null,
  popularity_synced_at: '2026-08-13T00:00:00',
  script_created: '2024-05-02T00:00:00', script_updated: '2026-06-11T00:00:00',
  has_arm: true, updateable: true, privileged: false,
  architectures: ['amd64', 'arm64'], port: 6379,
  script_path: 'ct/redis.sh', upstream_sha: '3d9a7c25d68913a5f91e7ae34107c29da3fbbccf',
}

const row = (over: Partial<CatalogRow>): CatalogRow => ({ ...BASE, ...over })

// The real reason string for the five addon-delegating apps, which is the
// longest one the corpus actually carries.
const LONG_REASON =
  'no install script upstream; it installs via an addon script run inside the container'

const STATES: { label: string; entry: CatalogRow; installed?: boolean }[] = [
  { label: 'installable', entry: row({ slug: 'a-installable' }) },
  { label: 'installed', entry: row({ slug: 'b-installed' }), installed: true },
  { label: 'not-installable-long-reason',
    entry: row({ slug: 'c-not-installable', installable: false, unsupported_reason: LONG_REASON }) },
  { label: 'unclassified-null', entry: row({ slug: 'd-null', installable: null }) },
  // The chip-heavy worst case: type chip plus all three tag chips, measured at
  // ~281px of chips, which is what decides whether the row stays on one line.
  { label: 'chip-heavy',
    entry: row({ slug: 'e-chips', privileged: true, has_arm: false, updateable: false }) },
  // An unlisted row: no upstream record at all, so no description, no tags, no
  // install count, and the badge instead.
  { label: 'unlisted-bare',
    entry: row({ slug: 'f-unlisted', name: null, description: null, upstream_state: 'unlisted',
                 popularity: null, popularity_synced_at: null, has_arm: null, updateable: null,
                 privileged: null, architectures: null, port: null, website: null }) },
  { label: 'widest-count', entry: row({ slug: 'g-docker', name: 'Docker', popularity: 126196 }) },
  { label: 'null-count', entry: row({ slug: 'h-nocount', popularity: null, popularity_synced_at: null }) },
  { label: 'long-name',
    entry: row({ slug: 'i-longname',
                 name: 'Alpine Borgbackup Server With A Deliberately Very Long Display Name' }) },
  // A single unbreakable token: nothing for the browser to wrap at, so this is
  // the case that would blow the name line out if `truncate` ever came off.
  { label: 'long-unbreakable-name',
    entry: row({ slug: 'j-unbreakable',
                 name: 'Supercalifragilisticexpialidociousnextcloudpiholeadguardhomeassistant' }) },
  // Longest real description in the corpus shape, to prove the clamp holds.
  { label: 'long-description',
    entry: row({ slug: 'k-longdesc',
                 description: 'Plex organizes all of your personal media so you can enjoy it no matter where you are. '.repeat(4) }) },
  { label: 'chip-heavy-and-not-installable',
    entry: row({ slug: 'l-worst', privileged: true, has_arm: false, updateable: false,
                 installable: false, unsupported_reason: LONG_REASON }) },
]

function Harness() {
  return (
    // Reproduces AppShell: a w-[236px] sidebar that hides below 720px, beside
    // <main className="min-w-0 flex-1 p-6">. Without this the lane is the whole
    // viewport and the column count is wrong at every width.
    <div className="flex">
      <div className="w-[236px] shrink-0 max-[720px]:hidden" />
      <main className="min-w-0 flex-1 p-6">
        <div className="grid grid-cols-[repeat(auto-fill,minmax(min(360px,100%),1fr))] gap-4">
          {STATES.map((s) => (
            <div key={s.entry.slug} data-state={s.label}>
              <StoreCard entry={s.entry} installCount={s.installed ? 1 : 0}
                onInstall={() => {}} onOpenDetail={() => {}} />
            </div>
          ))}
          {/* The loading placeholder, measured beside the cards it stands in
              for. A skeleton whose height differs from the real card makes the
              grid resize the moment the catalog lands, and that is exactly the
              failure this page's equal-heights check catches: it is a
              `.rounded-card` like the rest, so it is held to the same 240px. */}
          <div data-state="skeleton"><StoreCardSkeleton /></div>
        </div>
      </main>
    </div>
  )
}

createRoot(document.getElementById('root')!).render(<Harness />)
