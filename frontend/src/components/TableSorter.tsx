import { useMemo, useState } from 'react'

/**
 * Sorting the Apps and VMs lists, client-side, shared by both (TablePager
 * precedent: a hook plus the small control that drives it, in one file).
 *
 * Client-side because both pages already hold every row they draw. GET /apps
 * and GET /vms answer in one go, so ordering them here asks the server for
 * nothing and reorders on the same frame the operator picks the option, with
 * no refetch and no skeleton flash in between.
 */

/** What the two pages can be sorted by. `none` is the default and means the
 *  order the API sent, which is what both lists showed before this existed. */
export type SortKey = 'none' | 'name' | 'host' | 'status'

/** The three fields both row shapes carry. Deliberately not AppRow | VmRow:
 *  the sort has no business knowing about ctids, guest agents or update
 *  markers, and a structural type is what lets the tests drive it with three
 *  strings instead of two full API rows. */
type Sortable = { name: string; host_name: string; status: string }

/**
 * Status sorts by URGENCY, not by the alphabet.
 *
 * Alphabetically this is paused, running, stopped, which buries the guests
 * that are up under the ones that are not and puts the two states an operator
 * acts on at opposite ends of the list. Sorting by status is asking "what is
 * the state of my estate", and the useful answer leads with what is serving
 * traffic, then what is halfway (paused), then what is off, then what nobody
 * could read.
 *
 * Anything not listed here sorts after `unknown`: a status PVE invents later
 * is by definition something we cannot rank, and the bottom is where it can
 * be seen rather than silently mixed in with running guests.
 */
export const STATUS_ORDER = ['running', 'paused', 'stopped', 'unknown']

const statusRank = (s: string) => {
  const i = STATUS_ORDER.indexOf(s)
  return i === -1 ? STATUS_ORDER.length : i
}

/** Case-insensitive and locale-aware, because these are names an operator
 *  typed: `'Plex' < 'immich'` is true of raw code points and false of every
 *  expectation a human has about a list of names. */
const cmpText = (a: string, b: string) =>
  a.localeCompare(b, undefined, { sensitivity: 'base' })

/** Order rows by one key. Exported for the tests and for anything that already
 *  holds the chosen key; pages use the hook below. */
export function sortRows<T extends Sortable>(rows: T[], sort: SortKey): T[] {
  if (sort === 'none') return rows
  // A copy, never in place: these arrays come straight out of react-query's
  // cache and nothing is allowed to reorder what other readers are holding.
  return [...rows].sort((a, b) => {
    const by = sort === 'status' ? statusRank(a.status) - statusRank(b.status)
      : sort === 'host' ? cmpText(a.host_name, b.host_name)
      : 0
    // Name is the tiebreak for every key, so two guests on one host or two
    // that are both running keep one fixed order across renders instead of
    // swapping places on the next poll. Sorting by name falls straight
    // through to it.
    return by || cmpText(a.name, b.name)
  })
}

/** Sort a list client-side, holding the chosen key. Starts at `none`, so a
 *  page that renders this and changes nothing else looks exactly as it did. */
export function useSorted<T extends Sortable>(rows: T[]) {
  const [sort, setSort] = useState<SortKey>('none')
  return { sort, setSort, rows: useMemo(() => sortRows(rows, sort), [rows, sort]) }
}

// ScheduleForm's `input`/`label` vocabulary, minus the two rules that only
// make sense in a stacked form: no `w-full`, because this select sits in a
// row of filters and would eat it, and no `mb-1 block` on the label for the
// same reason.
const input = 'rounded-ctl border border-line bg-panel-2 px-3 py-1.5 text-[13px] text-text'
const label = 'text-[11.5px] uppercase tracking-wide text-text-3'

const OPTIONS: { key: SortKey; text: string }[] = [
  // Named for what it is rather than "None": the list is in an order either
  // way, and this one is the server's.
  { key: 'none', text: 'Default order' },
  { key: 'name', text: 'Name' },
  { key: 'host', text: 'Host' },
  { key: 'status', text: 'Status' },
]

/** The control. A native select rather than a row of buttons: four mutually
 *  exclusive choices is what a select is for, and it costs no width on a
 *  toolbar that already carries host segments and a filter box. */
export function TableSorter({ sort, onSort, label: what }: {
  sort: SortKey
  onSort: (s: SortKey) => void
  /** Named for what is being sorted ("apps", "virtual machines"), so the
   *  control is told apart by anyone not looking at it. Renamed to `what` on
   *  the way in only because `label` is already the class const above. */
  label: string
}) {
  return (
    <label className="flex items-center gap-2">
      <span className={label}>Sort</span>
      <select className={input} value={sort} aria-label={`Sort ${what}`}
              onChange={(e) => onSort(e.target.value as SortKey)}>
        {OPTIONS.map((o) => <option key={o.key} value={o.key}>{o.text}</option>)}
      </select>
    </label>
  )
}
