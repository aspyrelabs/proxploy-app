import { describe, expect, it } from 'vitest'
import type { CatalogRow } from '../api/catalog'
import { DEFAULT_SORT, STORE_SORTS, isStoreSort, sortEntries } from '../lib/store-order'

const BASE: CatalogRow = {
  slug: 'base', name: 'Base', category: 'Databases', type: 'ct', description: null,
  icon_url: null, popularity: 100, website: null, docs_url: null,
  default_cpu: 1, default_ram_mb: 1024, default_disk_gb: 4,
  default_os: 'debian', default_os_version: '13',
  installable: true, unsupported_reason: null, upstream_state: 'listed', synced_at: null,
  popularity_synced_at: null, script_created: '2024-01-01T00:00:00',
  script_updated: '2024-01-01T00:00:00', has_arm: true, updateable: true,
  privileged: false, architectures: ['amd64'], port: null,
  script_path: 'ct/base.sh', upstream_sha: '3d9a7c25d68913a5f91e7ae34107c29da3fbbccf',
}

const row = (over: Partial<CatalogRow> & { slug: string }): CatalogRow => ({ ...BASE, ...over })
const slugs = (rows: CatalogRow[]) => rows.map((r) => r.slug)

describe('store sort keys', () => {
  it('offers exactly the four keys the server allowlists, defaulting to popularity', () => {
    // These names are the URL contract and are shared with GET /catalog's own
    // `sort` allowlist. Renaming one here silently desyncs the two, so the
    // "Most installed" -> "Popularity" relabel deliberately left the KEY alone.
    expect(Object.keys(STORE_SORTS)).toEqual(['name', 'popularity', 'newest', 'updated'])
    expect(DEFAULT_SORT).toBe('popularity')
  })

  it('rejects anything outside the allowlist, including the empty string', () => {
    expect(isStoreSort('popularity')).toBe(true)
    expect(isStoreSort('populariti')).toBe(false)
    expect(isStoreSort('')).toBe(false)
    expect(isStoreSort(undefined)).toBe(false)
    expect(isStoreSort('toString')).toBe(false)  // not an inherited Object key either
  })
})

describe('sortEntries', () => {
  it('sorts by name ascending by default, falling back to slug for an unnamed row', () => {
    const rows = [row({ slug: 'zabbix', name: 'Zabbix' }), row({ slug: 'adguard', name: null }),
                  row({ slug: 'plex', name: 'Plex' })]
    expect(slugs(sortEntries(rows, 'name'))).toEqual(['adguard', 'plex', 'zabbix'])
  })

  it('sorts most installed first, not least', () => {
    const rows = [row({ slug: 'quiet', popularity: 4 }),
                  row({ slug: 'docker', popularity: 126196 }),
                  row({ slug: 'middling', popularity: 1001 })]
    expect(slugs(sortEntries(rows, 'popularity'))).toEqual(['docker', 'middling', 'quiet'])
  })

  it('sorts newest and recently-updated by their own dates, descending', () => {
    const rows = [
      row({ slug: 'old', script_created: '2024-05-02T00:00:00', script_updated: '2026-08-13T00:00:00' }),
      row({ slug: 'new', script_created: '2026-08-13T00:00:00', script_updated: '2024-05-02T00:00:00' }),
    ]
    // The two keys are genuinely different columns; a row can be the newest
    // script and the least recently touched one at the same time.
    expect(slugs(sortEntries(rows, 'newest'))).toEqual(['new', 'old'])
    expect(slugs(sortEntries(rows, 'updated'))).toEqual(['old', 'new'])
  })

  it('sorts NULLS LAST on every descending sort, so a row with no measurement never heads the list', () => {
    // THE null test. The 9 unlisted rows carry no script dates at all, and
    // upstream nulls are "we do not know", never zero and never the epoch.
    // A naive comparator puts undefined wherever the sort happens to land it,
    // which is how "no data" ends up presented as "newest" or "most
    // installed". Asserted on all three descending keys because each one has
    // its own null source.
    const known = row({ slug: 'known', popularity: 5, script_created: '2020-01-01T00:00:00',
                        script_updated: '2020-01-01T00:00:00' })
    const unknown = row({ slug: 'unlisted', popularity: null, script_created: null,
                          script_updated: null })
    for (const sort of ['popularity', 'newest', 'updated'] as const) {
      // null last whichever way round the input arrives, so this cannot pass
      // by accident on an already-favourable order
      expect(slugs(sortEntries([unknown, known], sort)), sort).toEqual(['known', 'unlisted'])
      expect(slugs(sortEntries([known, unknown], sort)), sort).toEqual(['known', 'unlisted'])
    }
  })

  it('breaks ties by name, and keeps all-null rows in name order at the bottom', () => {
    const rows = [
      row({ slug: 'b', name: 'Beta', popularity: null }),
      row({ slug: 'a', name: 'Alpha', popularity: null }),
      row({ slug: 'd', name: 'Delta', popularity: 7 }),
      row({ slug: 'c', name: 'Charlie', popularity: 7 }),
    ]
    expect(slugs(sortEntries(rows, 'popularity'))).toEqual(['c', 'd', 'a', 'b'])
  })

  it('never reorders the caller\'s array in place', () => {
    // The rows come straight from the React Query cache; sorting that array in
    // place would reorder it for every other consumer of the same cache entry.
    const rows = [row({ slug: 'z', name: 'Zed' }), row({ slug: 'a', name: 'Ay' })]
    const sorted = sortEntries(rows, 'name')
    expect(slugs(rows)).toEqual(['z', 'a'])
    expect(slugs(sorted)).toEqual(['a', 'z'])
  })
})
