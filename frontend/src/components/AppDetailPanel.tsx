import type { AppRow } from '../api/hooks'
import { UpdatePanel } from '../routes/apps'
import { MetricChart } from './charts/MetricChart'
import { GuestFirewallLine } from './GuestFirewallLine'
import { KVGrid } from './KVGrid'
import { StatusPill } from './StatusPill'
import { fmtBytes, fmtPct, fmtUptime } from '../lib/format'

// p-4, not the page's p-5: these cards sit inside a table row that already
// carries the table's own padding, and the extra ring of space read as a gap
// rather than as a card.
const card = 'rounded-card border border-line-soft bg-panel-2 p-4'

/**
 * One app's detail, rendered inline in the Apps table. `app` is a prop and
 * there is no query for it here: the row object is already in hand.
 */
export function AppDetailPanel({ app }: { app: AppRow }) {
  const memPct = app.mem_bytes != null && app.mem_total_bytes
    ? (app.mem_bytes / app.mem_total_bytes) * 100 : null
  const idleNote = app.status === 'running' ? undefined
    : 'No readings while this container is stopped.'
  return (
    <div>
      {/* @container, not a viewport `lg:`: this box is a table cell sharing the
          page with a sidebar, so the viewport says nothing about how wide the
          cards get. Two flexible columns + an auto one (not three equal
          thirds) because the third column only holds a status pill and the
          update box. Below @3xl everything stacks to one column. */}
      <div className="@container">
        {/* minmax(0,1fr), NOT a bare 1fr: a bare 1fr is minmax(auto,1fr), and
            that auto minimum is min-content — here a fixed-pixel uPlot canvas
            — so the track can never shrink below the canvas width. Only a
            hand-written template reintroduces this (Tailwind's grid-cols-3 is
            already minmax(0,1fr)). It renders in a <td colSpan={8}>, so the
            overflow widened the whole Apps table with it. */}
        <div className="grid grid-cols-1 gap-4 @3xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
          <div className={card}>
            <MetricChart idleNote={idleNote} target={`app:${app.id}`} metric="cpu_pct"
              unit="percent" label="CPU" accent="amber" />
          </div>
          <div className={card}>
            <MetricChart idleNote={idleNote} target={`app:${app.id}`} metric="mem_pct"
              unit="percent" label="Memory" accent="cyan" />
            {/* The chart is a percentage over time; this line is what that
                percentage is a percentage OF, which the chart cannot say. */}
            <div className="mt-2 font-mono text-[11px] text-text-3">
              {fmtBytes(app.mem_bytes)} of {fmtBytes(app.mem_total_bytes)} ({fmtPct(memPct)})
            </div>
          </div>
          {/* Two boxes stacked (Status, Update). Grid items stretch, so the
              column is exactly one chart card tall and the three columns line
              up without hard-coded height. Update's body scrolls instead of
              growing, so its variable content (one line up to a live job log)
              never drags the charts taller. */}
          <div className="flex flex-col gap-4 @3xl:w-56">
            <div className={card}>
              <h3 className="mb-1.5 text-[11px] uppercase tracking-wide text-text-3">Status</h3>
              <StatusPill status={app.status} />
              <div className="mt-2 font-mono text-[12px] text-text-2">up {fmtUptime(app.uptime_s)}</div>
              <div className="mt-2"><GuestFirewallLine guestType="app" guestId={app.id} /></div>
            </div>
            {/* min-h-0 on both the box and its body: a flex child's automatic
                minimum is its content, so without it the box refuses to shrink
                and overflow-y-auto never has a smaller box to scroll inside. */}
            <div className={`${card} flex min-h-0 flex-1 flex-col`}>
              <h3 className="mb-1.5 text-[11px] uppercase tracking-wide text-text-3">Update</h3>
              <div className="min-h-0 flex-1 overflow-y-auto">
                <UpdatePanel appId={app.id} app={app} />
              </div>
            </div>
          </div>
        </div>
      </div>
      <div className={`${card} mt-4`}>
        <KVGrid items={[
          ['CTID', app.ctid],
          ['Node', app.node],
          ['IP', app.ip ?? 'unknown'],
          ['Category', app.category ?? 'unknown'],
          ['Web port', app.web_port ?? 'unknown'],
          ['Update', app.update_available ?? 'Up to date'],
        ]} />
      </div>
    </div>
  )
}
