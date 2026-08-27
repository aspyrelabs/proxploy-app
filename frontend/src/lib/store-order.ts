import type { CatalogRow } from '../api/catalog'

/**
 * Ordering and popularity banding for the App Store grid.
 *
 * WHY THIS IS CLIENT SIDE. `GET /catalog` accepts the same four `sort` keys
 * server-side, and this deliberately does not use them. The Store fetches the
 * whole ct/ catalog exactly once and already does category filtering and
 * paging in the browser, so threading `sort` into the query key would put a
 * 556-row round trip behind a control that reorders a list we are holding in
 * memory, and make sort the only interaction on the page with a loading
 * state. The key names match the server's allowlist exactly, so the URL
 * contract is identical either way and switching to the server ordering later
 * is a one-line change.
 *
 * The cost of owning it here is null placement, which is the whole reason the
 * server ordering exists, so `sortEntries` below is explicit about it rather
 * than leaving it to whatever a naive comparator happens to do.
 */
export const STORE_SORTS = {
  name: 'Name (A to Z)',
  popularity: 'Popularity',
  newest: 'Newest',
  updated: 'Recently updated',
} as const

export type StoreSort = keyof typeof STORE_SORTS

export const DEFAULT_SORT: StoreSort = 'popularity'

/** Own keys only. `'toString' in STORE_SORTS` is true, because `in` walks the
 *  prototype chain, so the obvious version of this accepts "?sort=toString"
 *  and then hands SORT_KEYS a key it does not have, which throws inside the
 *  comparator and takes the whole page down. A hand-typed URL must not be
 *  able to do that. */
export function isStoreSort(v: unknown): v is StoreSort {
  return typeof v === 'string' && Object.hasOwn(STORE_SORTS, v)
}

const displayName = (r: CatalogRow): string => r.name ?? r.slug

/** Name is the tiebreak everywhere, so equal measurements stay in a stable,
 *  readable order rather than whatever order the fetch happened to return. */
function byName(a: CatalogRow, b: CatalogRow): number {
  return displayName(a).localeCompare(displayName(b))
}

// ISO 8601 strings compare correctly as strings, so dates and counts share one
// comparator. Both are "bigger is more recent / more popular".
const SORT_KEYS: Record<Exclude<StoreSort, 'name'>, (r: CatalogRow) => number | string | null> = {
  popularity: (r) => r.popularity,
  newest: (r) => r.script_created,
  updated: (r) => r.script_updated,
}

/**
 * Returns a NEW array; never sorts the caller's list in place, because the
 * rows come straight from the React Query cache and mutating that array would
 * reorder every other consumer of the same cache entry.
 *
 * NULLS LAST on all three descending sorts, matching the server's ordering.
 * "No measurement" is not a low measurement: the 7 unlisted rows have no
 * script dates at all, and sorting them as though they were zero or epoch
 * would put "we do not know" at the top of "Newest".
 */
export function sortEntries(rows: readonly CatalogRow[], sort: StoreSort): CatalogRow[] {
  const out = [...rows]
  if (sort === 'name') return out.sort(byName)
  const key = SORT_KEYS[sort]
  return out.sort((a, b) => {
    const av = key(a)
    const bv = key(b)
    if (av == null && bv == null) return byName(a, b)
    if (av == null) return 1   // a sinks
    if (bv == null) return -1  // b sinks
    if (av === bv) return byName(a, b)
    return av < bv ? 1 : -1    // descending
  })
}
