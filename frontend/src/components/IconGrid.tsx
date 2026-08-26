import { useNavigate } from '@tanstack/react-router'
import type { AppRow, VmRow } from '../api/hooks'
import { statusLabel } from '../lib/activityDisplay'
import { osIconUrl } from '../lib/os-icon'
import { AppIconMenu } from './AppIconMenu'
import { IconTile, type IconColors } from './IconTile'
import { linkCls } from './ui/button'
import { VmActionsMenu } from './VmActionsMenu'
import { Icon } from './ui/icon'
import { Skeleton, SkeletonLine } from './ui/skeleton'

/**
 * The two inventories on the Hosts page, apps and VMs, as one visual language.
 *
 * They live in ONE file because they are one design with two data sources: the
 * same cell rhythm, the same status vocabulary, the same grouping. Two files
 * drifted into two row heights; a shared cell cannot.
 *
 * They differ in exactly two places, which are the two props IconGridCell
 * takes: which menu opens off the artwork, and where the artwork comes from.
 */

/** auto-fill with a FLOOR, not a fixed column count.
 *
 *  A fixed count (sm:grid-cols-2 xl:grid-cols-4) let each column be whatever
 *  width was left over, so at four across on a narrow page an app name was cut
 *  to a few characters. A floor plus auto-fill fits as many columns as the
 *  space allows while keeping any one readable.
 *
 *  10rem floor, 12px gap, measured in a browser at the 570px each section gets
 *  on a 1440px window: 3 columns of 171px, and no app name on the reference
 *  fleet truncates at that width. The cell still carries `truncate` and a
 *  `title`.
 *
 *  Shared with the skeleton so the placeholder cannot lay out differently. */
const GRID = 'grid grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-x-3 gap-y-4'

/** The card the grids sit in, kept OUT of GRID.
 *
 *  There is one grid per NODE, so a card welded onto the grid string would
 *  draw five floating boxes for a five node cluster and read as five separate
 *  inventories. One panel with a rule between sections reads as one list,
 *  grouped by the machine each guest runs on. */
const PANEL = 'rounded-card border border-line-soft bg-panel p-4'

/**
 * State, as a glyph and the word, for the icon grid.
 *
 * The COLOURS are StatusPill's and the WORD is statusLabel's, so this cannot
 * drift from the vocabulary the rest of the app uses, and the app cell and the
 * VM cell share it so one state never reads in two colours.
 *
 * Every status gets its own entry rather than collapsing to running/stopped:
 * paused and unknown are not "not running". `icon:` is the field shape
 * scripts/icon-names.mjs reads, which is why these are literals in a table.
 *
 * `pending` is not one of StatusPill's STYLES keys: it is the optimistic patch
 * useLifecycle applies between a click and the job's resolution.
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
 * 50 for the apps and 50 for the VMs, not 50 per node: what matters is how
 * much of the page a section can take, and that is the total. Without a cap, a
 * fleet with three hundred containers turned the Hosts page into a list nobody
 * reads on the way to what they came for. Both sections link to their full
 * table.
 */
const CAP = 50

/**
 * How many rows each node section may draw, dealt round-robin.
 *
 * Not a slice off the front: take the first 50 of a sorted list and node1 eats
 * all of them while node2 renders empty, so an operator cannot tell a node
 * with no apps from a node that lost the draw. Dealing one at a time gives
 * 25/25 for two even nodes and spends the remainder on whoever has rows left.
 *
 * Terminates: every pass either hands out a row or every group is full, and
 * `left` never exceeds the rows that exist.
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
 *  only place the page can admit it is not showing everything. */
function counted(shown: number, total: number, word: string): string {
  const plural = `${word}${total === 1 ? '' : 's'}`
  return shown === total ? `${total} ${plural}` : `${shown} of ${total} ${plural}`
}

/** Rows with neither a node nor a host name. Still somebody's guests, so they
 *  get a section of their own at the end rather than being dropped by an
 *  `if (!node) continue`. */
const UNPLACED = 'Node not reported yet'

/**
 * Guests grouped by the machine they actually run on.
 *
 * The key is the GUEST'S OWN node, not the host it was read through. A Host
 * record is one Proxmox API endpoint, and on a cluster that endpoint answers
 * for every node, so a container on pve3 arrives with host_name "host-01".
 * Grouping on host_name would file every guest in the cluster under one
 * heading, over containers running on three different machines.
 *
 * host_name is the FALLBACK for rows where node is null: a standalone host
 * whose poller has not filled the field in yet still belongs somewhere.
 *
 * Sorted by name, and within each group by name, because /apps and /vms answer
 * in no defined order and an unsorted list reshuffles on every 30s refetch.
 */
function groupByNode<T extends Guest>(rows: T[]): NodeGroup<T>[] {
  // null is the key for rows with neither, and it cannot collide with any
  // name a node or a host could have.
  const groups = new Map<string | null, NodeGroup<T>>()
  for (const r of rows) {
    const node = r.node?.trim() || null
    const host = r.host_name?.trim() || null
    // A row with no node joins the group of its host's name rather than
    // starting one beside it: on a standalone machine the host record is
    // usually named after its only node.
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
  // Grouped first, capped second: the cap is a total across the sections, so
  // applying it to `rows` first would decide which node loses out by sort
  // order alone.
  const groups = groupByNode(rows)
  const share = quotas(groups.map((g) => g.rows.length), CAP)
  return (
    <div className={PANEL}>
      {groups.map((g, i) => {
        // The host is worth saying only when it is a DIFFERENT machine from
        // the heading: "node1 · on node1.lab.local" is the same box
        // named twice. Compared on the first DNS label, since a host is
        // routinely registered by its fully qualified name while PVE reports
        // the node as the short one.
        const sameBox = (h: string) =>
          h.split('.')[0].toLowerCase() === g.label.split('.')[0].toLowerCase()
        const via = g.hosts.filter((h) => !sameBox(h))
        return (
          <section key={g.key ?? UNPLACED}
            className={i > 0 ? 'mt-4 border-t border-line-soft pt-4' : undefined}>
            <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="font-mono text-[13px] text-text">{g.label}</h3>
              {/* One string, not two children: split across text nodes it
                  reads the same on screen, and it is one sentence either
                  way. */}
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
 * different props while both want the SAME trigger, tile size and all, which
 * is what keeps the two grids on one row rhythm.
 */
function IconGridCell({ name, testId, iconUrl, initials, colors, status, onOpen, menu }: {
  name: string
  testId: string
  iconUrl: string | null
  initials?: string | null
  colors?: IconColors | null
  status: string
  onOpen: () => void
  menu: (trigger: React.ReactNode) => React.ReactNode
}) {
  const state = STATE[status] ?? STATE.unknown
  return (
    <div className="flex items-center gap-3">
      {/* The artwork is the menu. Nothing is drawn ON it: the tile is the
          guest's own picture, and a badge would compete with whatever that
          picture already puts in the corner. */}
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
          className={`block max-w-full truncate text-left text-[13px] ${linkCls}`}
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

/** Every installed app up to CAP, grouped under the node it runs on. The cap
 *  is dealt across the nodes and stated in each section's count, so a section
 *  holding rows back says so, and a missing app cannot mean "stopped, gone, or
 *  simply the ninth". */
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
 *  an unrecognised ostype and for one PVE has not reported yet, and IconTile
 *  falls back to the initials tile on a null url, so an unknown OS looks like
 *  an app with no logo rather than a broken image. */
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
 *  land. ONE placeholder for both grids because there is one cell. */
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
