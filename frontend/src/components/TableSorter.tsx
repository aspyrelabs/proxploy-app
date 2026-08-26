import { useMemo, useState } from 'react'

/**
 * Client-side sorting for the Apps and VMs lists, shared by both. Both pages
 * already hold every row they draw, so sorting here asks the server for
 * nothing and reorders on the same frame the operator picks an option.
 */

/** Name is the default: it is the order the API sent. */
export type SortKey = 'name' | 'host' | 'status'

/** A structural type rather than AppRow | VmRow: the sort has no business
 *  knowing the full row shapes, and it lets the tests drive this with three
 *  strings. */
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

/** Sort a list client-side, holding the chosen key. Starts on name. */
export function useSorted<T extends Sortable>(rows: T[]) {
  const [sort, setSort] = useState<SortKey>('name')
  return { sort, setSort, rows: useMemo(() => sortRows(rows, sort), [rows, sort]) }
}

// ScheduleForm's `input`/`label` vocabulary, minus the two rules that only
// make sense in a stacked form, and one step smaller (a toolbar control, not
// a dialog field).
const input = 'rounded-ctl border border-line bg-panel-2 px-2 py-1 text-[11px] text-text'
// Sentence case, not ScheduleForm's uppercase: that vocabulary is a field
// heading stacked above its input, this is a word sitting beside its control.
const label = 'text-[11px] text-text-3'

const OPTIONS: { key: SortKey; text: string }[] = [
  // No "Default order" entry: the server hands these back by name already.
  { key: 'name', text: 'Name' },
  { key: 'host', text: 'Host' },
  { key: 'status', text: 'Status' },
]

/** The control. A native select, not a row of buttons: four mutually
 *  exclusive choices is what a select is for, and it costs no toolbar width. */
export function TableSorter({ sort, onSort, label: what }: {
  sort: SortKey
  onSort: (s: SortKey) => void
  /** Named for what is being sorted ("apps", "virtual machines"). Renamed to
   *  `what` on the way in only because `label` is already the class const. */
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
