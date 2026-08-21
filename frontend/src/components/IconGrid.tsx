import { useNavigate } from '@tanstack/react-router'
import type { AppRow, VmRow } from '../api/hooks'
import { statusLabel } from '../lib/activityDisplay'
import { osIconUrl } from '../lib/os-icon'
import { AppIconMenu } from './AppIconMenu'
import { IconTile } from './IconTile'
import { VmActionsMenu } from './VmActionsMenu'
import { Icon } from './ui/icon'
import { Skeleton, SkeletonLine } from './ui/skeleton'

/**
 * The two inventories on the Hosts page, apps and VMs, as one visual language.
 *
 * They live in ONE file because they are one design that happens to have two
 * data sources: the same cell rhythm, the same status vocabulary, the same
 * grouping. Two files drifted into two row heights the first time anyone
 * touched one of them; a shared cell cannot.
 *
 * The two grids genuinely differ in exactly two places, and those are the two
 * props IconGridCell takes: which menu opens off the artwork (AppIconMenu vs
 * VmActionsMenu), and where the artwork comes from (an app wears the logo of
 * the Store entry it came from, a VM has no such entry and wears its OS).
 */

/** auto-fill with a FLOOR, not a fixed column count.
 *
 *  A count (sm:grid-cols-2 xl:grid-cols-4) decided how many columns there were
 *  and let each one be whatever width was left over, so at four across on a
 *  narrow page an app name was cut to a few characters. A floor plus auto-fill
 *  lets the browser fit as many columns as the space allows while keeping any
 *  single column readable.
 *
 *  The floor is 10rem and the column gap is 12px, down from 13rem and 24px.
 *  These two sections sit in half the page each, which is 570px at a 1440px
 *  window once the sidebar, the page padding and the gap between the two
 *  columns come out. Measured in a browser at that width rather than worked
 *  out on paper: the old pair fitted 2 columns of 256px, the new pair fits 3
 *  of 171px, and none of the app names on the reference fleet truncate at
 *  171px, `changedetection` at fifteen characters included. The cell still
 *  carries `truncate` and a `title` for names longer than that.
 *
 *  Shared with the skeleton so the placeholder cannot lay out differently from
 *  the thing it stands in for. */
const GRID = 'grid grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-x-3 gap-y-4'

/** The card the grids sit in, kept OUT of GRID.
 *
 *  It used to be welded onto the end of the same class string, which was fine
 *  while there was one grid per inventory. There is now one grid per node, and
 *  a card per node would draw five floating boxes for a five node cluster and
 *  read as five separate inventories. One panel with a rule between sections
 *  reads as what it is: a single list of what is installed, grouped by the
 *  machine it runs on. */
const PANEL = 'rounded-card border border-line-soft bg-panel p-4'

/**
 * State, as a glyph and the word, for the icon grid.
 *
 * The COLOURS are StatusPill's, and the WORD is statusLabel's, so this view
 * cannot drift from the status vocabulary the rest of the app uses.
 *
 * Every status gets its own entry rather than collapsing to running/stopped:
 * paused and unknown are not "not running", and an operator who cannot tell
 * them apart cannot tell a container someone suspended from one PVE has lost
 * track of. `icon:` is the field shape scripts/icon-names.mjs reads, which is
 * why these are literals in a table rather than a computed name.
 *
 * `pending` is not one of StatusPill's STYLES keys either (it falls to its
 * `unknown` grey there): it is the optimistic patch useLifecycle applies for
 * the span between a click and the job's own resolution, covered here for
 * the same reason. `connected`/`online` are node-only statuses StatusPill
 * also carries, never a value AppRow.status takes, so they are left out.
 *
 * Shared by the app cell and the VM cell: the two kinds of guest report the
 * same words for the same states, and a VM that read "Stopped" in one colour
 * on one half of the page and another colour on the other half would be the
 * page contradicting itself.
 */
const STATE: Record<string, { icon: string; cls: string }> = {
  running: { icon: 'play_arrow', cls: 'text-green' },
  paused: { icon: 'pause', cls: 'text-amber' },
  stopped: { icon: 'stop', cls: 'text-red' },
  pending: { icon: 'hourglass_empty', cls: 'text-amber' },
  error: { icon: 'error', cls: 'text-red' },
  unknown: { icon: 'help', cls: 'text-text-3' },
}

/** The fields both inventories carry and this file needs. */
type Guest = { id: number; name: string; host_name: string; node?: string | null }

type NodeGroup<T> = {
  /** The node name, the host name it fell back to, or null for neither. */
  key: string | null
  /** The heading: the node's own name, or the host's when no node was reported. */
  label: string
  /** Hosts these rows came in through, for the line under the heading. */
  hosts: string[]
  rows: T[]
}

/**
 * The most guests one inventory draws, across every node in it.
 *
 * 50 for the apps and 50 for the VMs, not 50 each per node: the number that
 * matters is how much of the page a section can take, and that is the total.
 * One host showing 50 apps and two hosts showing 25 apiece cost the operator
 * the same scroll.
 *
 * The cap exists because the sections are uncapped otherwise, and a fleet with
 * three hundred containers turned the Hosts page into a list nobody reads on
 * the way to the thing they came for. Both sections link to their full table,
 * which is where a fleet that size belongs.
 */
const CAP = 50

/**
 * How many rows each node section may draw, dealt round-robin.
 *
 * Round-robin rather than a slice off the front, because a slice is the bug
 * this file already carries a comment about: take the first 50 of a sorted
 * list and node1 eats all of them while node2 renders empty, so an operator
 * reading the page cannot tell a node with no apps from a node that lost the
 * draw. Dealing one at a time gives 25/25 for two even nodes and spends the
 * remainder on whoever still has rows left, so every node is represented
 * before any node is complete.
 *
 * Terminates: every pass either hands out at least one row or every group is
 * already full, and `left` never exceeds the rows that exist.
 */
function quotas(sizes: number[], cap: number): number[] {
  const out = sizes.map(() => 0)
  let left = Math.min(cap, sizes.reduce((a, b) => a + b, 0))
  while (left > 0) {
    for (let i = 0; i < sizes.length && left > 0; i++) {
      if (out[i] < sizes[i]) {
        out[i]++
        left--
      }
    }
  }
  return out
}

/** "4 apps", or "25 of 40 apps" when the cap took the rest. The count is the
 *  only place the page can admit it is not showing everything, so it says the
 *  total rather than quietly drawing a shorter list. */
function counted(shown: number, total: number, word: string): string {
  const plural = `${word}${total === 1 ? '' : 's'}`
  return shown === total ? `${total} ${plural}` : `${shown} of ${total} ${plural}`
}

/** Rows with neither a node nor a host name. They are still somebody's guests,
 *  so they get a section of their own at the end rather than being dropped on
 *  the floor, which is what a `if (!node) continue` would have done. */
const UNPLACED = 'Node not reported yet'

/**
 * Guests grouped by the machine they actually run on.
 *
 * The key is the GUEST'S OWN node, not the host it was read through, and that
 * distinction is the whole point of this change. A Host record in Proxploy is
 * one Proxmox API endpoint; on a cluster that one endpoint answers for every
 * node in the cluster, so a container sitting on pve3 arrives with
 * host_name "host-01" because host-01 is the endpoint we asked. Grouping on
 * host_name would file every guest in the cluster under one heading and say
 * "host-01" over a list of containers that are running on three different
 * machines, which is the exact question the operator opened this page to
 * answer.
 *
 * host_name is the FALLBACK, for the rows where node is null: a standalone
 * host whose poller has not filled the field in yet still belongs somewhere,
 * and its host name is the truest thing we can say about where it lives.
 *
 * Sorted by name, and sorted within each group by name, for the same reason
 * the node cards above are: /apps and /vms answer in no defined order, so an
 * unsorted list reshuffles under the operator on every 30s refetch.
 */
function groupByNode<T extends Guest>(rows: T[]): NodeGroup<T>[] {
  // null is the key of the group for rows with neither, and null cannot
  // collide with any name a node or a host could have.
  const groups = new Map<string | null, NodeGroup<T>>()
  for (const r of rows) {
    const node = r.node?.trim() || null
    const host = r.host_name?.trim() || null
    // A row with no node joins the group of its host's name rather than
    // starting one beside it. On a standalone machine the host record is
    // usually named after its only node, so keeping them apart would draw two
    // sections with the same heading over one machine.
    const key = node ?? host
    let g = groups.get(key)
    if (!g) {
      g = { key, label: key ?? UNPLACED, hosts: [], rows: [] }
      groups.set(key, g)
    }
    // Several hosts can answer for one node (two endpoints into one cluster),
    // so this is a list, not a field.
    if (host && !g.hosts.includes(host)) g.hosts.push(host)
    g.rows.push(r)
  }
  const rank = (g: NodeGroup<T>) => (g.key == null ? 1 : 0)
  return [...groups.values()]
    .sort((a, b) => rank(a) - rank(b) || a.label.localeCompare(b.label))
    .map((g) => ({
      ...g,
      hosts: [...g.hosts].sort((a, b) => a.localeCompare(b)),
      rows: [...g.rows].sort((a, b) => a.name.localeCompare(b.name)),
    }))
}

/** One panel, one section per node, a rule between them. */
function NodeSections<T extends Guest>({ rows, word, children }: {
  rows: T[]
  /** "app" or "VM", the one noun the two inventories do not share. */
  word: string
  children: (rows: T[]) => React.ReactNode
}) {
  // Grouped first, capped second. The cap is a total across the sections, so
  // it cannot be applied to `rows` before the groups exist without deciding
  // which node loses out by sort order alone.
  const groups = groupByNode(rows)
  const share = quotas(groups.map((g) => g.rows.length), CAP)
  return (
    <div className={PANEL}>
      {groups.map((g, i) => {
        // The host is worth saying only when it is a DIFFERENT machine from
        // the heading: "pve3 · on host-01" tells the operator which endpoint
        // answers for that node, while "node1 · on node1.lab.local" is
        // the same box named twice.
        //
        // Compared on the first DNS label, not the whole string. A host is
        // routinely registered by its fully qualified name while PVE reports
        // the node as the short one, so an exact compare called them different
        // machines and repeated the name in every heading.
        const sameBox = (h: string) =>
          h.split('.')[0].toLowerCase() === g.label.split('.')[0].toLowerCase()
        const via = g.hosts.filter((h) => !sameBox(h))
        return (
          <section key={g.key ?? UNPLACED}
            className={i > 0 ? 'mt-4 border-t border-line-soft pt-4' : undefined}>
            <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="font-mono text-[13px] text-text">{g.label}</h3>
              {/* One string, not two children: split across text nodes it
                  reads the same on screen and is a great deal harder to assert
                  on, and it is one sentence either way. */}
              <span className="text-[11px] text-text-3">
                {(via.length > 0 ? `on ${via.join(', ')} · ` : '')
                  + counted(share[i], g.rows.length, word)}
              </span>
            </div>
            <div className={GRID}>{children(g.rows.slice(0, share[i]))}</div>
          </section>
        )
      })}
    </div>
  )
}

/**
 * One guest: its artwork, which is the menu, and its name and state beside it.
 *
 * `menu` is a function rather than a wrapped child because the two menus take
 * different props (AppIconMenu wants the app row, VmActionsMenu the VM row)
 * while both want the SAME trigger, tile size and all. Handing them a trigger
 * this component built is what keeps the two grids on one row rhythm.
 */
function IconGridCell({ name, testId, iconUrl, initials, colors, status, onOpen, menu }: {
  name: string
  testId: string
  iconUrl: string | null
  initials?: string | null
  colors?: { c1: string; c2: string } | null
  status: string
  onOpen: () => void
  menu: (trigger: React.ReactNode) => React.ReactNode
}) {
  const state = STATE[status] ?? STATE.unknown
  return (
    <div className="flex items-center gap-3">
      {/* The artwork is the menu. Nothing is drawn ON it: the tile is the
          guest's own picture and a badge over it would compete with whatever
          that picture already puts in the corner. */}
      {menu(
        <button type="button" data-testid={testId}
          aria-label={`Actions for ${name}`}
          className="shrink-0 rounded-tile transition hover:brightness-110">
          <IconTile name={name} iconUrl={iconUrl} size={32}
                    initials={initials} colors={colors} />
        </button>,
      )}
      <div className="min-w-0">
        {/* The name is the way to the detail, which is a row that expands on
            the Apps or VMs table rather than a page of its own. */}
        <button type="button"
          title={name}
          className="block max-w-full truncate text-left text-[13px] text-text
                     transition hover:text-amber"
          onClick={onOpen}>
          {name}
        </button>
        <div className={`flex items-center gap-1 font-mono text-[11px] uppercase ${state.cls}`}>
          <Icon name={state.icon} size={14} />
          {statusLabel(status)}
        </div>
      </div>
    </div>
  )
}

/** Every installed app up to CAP, grouped under the node it runs on. The page
 *  once showed the first eight in whatever order the API answered, which on a
 *  cluster meant an operator could not tell whether a missing app was stopped,
 *  gone, or simply the ninth. The cap that replaced no cap at all is dealt
 *  across the nodes and stated in each section's count, so neither of those
 *  readings is possible: a section that is holding rows back says so. */
export function AppIconGrid({ apps }: { apps: AppRow[] }) {
  const navigate = useNavigate()
  return (
    <NodeSections rows={apps} word="app">
      {(rows) => rows.map((a) => (
        <IconGridCell key={a.id} name={a.name} testId={`app-icon-${a.id}`}
          iconUrl={a.icon_url} initials={a.icon_initials} colors={a.icon_colors}
          status={a.status}
          onOpen={() => navigate({ to: '/apps' as never,
                                   search: { open: a.id } as never })}
          menu={(trigger) => <AppIconMenu app={a}>{trigger}</AppIconMenu>} />
      ))}
    </NodeSections>
  )
}

/** Every VM up to CAP, the same grid, grouped and capped the same way.
 *
 *  A VM has no catalog entry and so no logo. osIconUrl returns null both for
 *  an ostype we do not recognise and for a VM whose ostype PVE has not told us
 *  yet, and IconTile treats a null url as "no artwork" and falls back to the
 *  initials tile, so an unknown OS looks like an app with no logo rather than
 *  like a broken image. */
export function VmIconGrid({ vms }: { vms: VmRow[] }) {
  const navigate = useNavigate()
  return (
    <NodeSections rows={vms} word="VM">
      {(rows) => rows.map((v) => (
        <IconGridCell key={v.id} name={v.name} testId={`vm-icon-${v.id}`}
          iconUrl={osIconUrl(v.os_type)} status={v.status}
          onOpen={() => navigate({ to: '/vms' as never,
                                   search: { open: v.id } as never })}
          menu={(trigger) => <VmActionsMenu vm={v}>{trigger}</VmActionsMenu>} />
      ))}
    </NodeSections>
  )
}

/** The placeholder for either grid, mirroring the section heading, the 32px
 *  tile and the two text lines so the page below does not shift when the rows
 *  land. ONE placeholder for both grids because there is one cell: edited with
 *  IconGridCell, never separately. */
export function IconGridSkeleton({ count = 8 }: { count?: number }) {
  return (
    <div className={PANEL}>
      <div className="mb-3 flex items-baseline justify-between gap-2">
        <SkeletonLine className="w-20 text-[13px]" />
        <SkeletonLine className="w-24 text-[11px]" />
      </div>
      <div className={GRID}>
        {Array.from({ length: count }, (_, i) => (
          <div key={i} className="flex items-center gap-3">
            <Skeleton className="h-8 w-8 shrink-0 rounded-tile" />
            <div className="min-w-0 flex-1">
              <SkeletonLine className="w-24 text-[13px]" />
              <SkeletonLine className="w-16 text-[11px]" />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
