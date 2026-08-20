import type { AppRow } from '../api/hooks'
import { UpdatePanel } from '../routes/apps'
import { MetricChart } from './charts/MetricChart'
import { KVGrid } from './KVGrid'
import { StatusPill } from './StatusPill'
import { fmtBytes, fmtPct, fmtUptime } from '../lib/format'

// p-4, not the page's p-5: these cards sit inside a table row that already
// carries the table's own padding, and the extra ring of space read as a gap
// rather than as a card.
const card = 'rounded-card border border-line-soft bg-panel-2 p-4'

/**
 * One app's detail, as it appears inside the Apps table rather than on a page
 * of its own.
 *
 * The row object is already in hand by the time this renders, so `app` is a
 * prop and there is no query for it here. The page this replaced fetched
 * /apps/{id} a second time purely because a URL was all it had.
 */
export function AppDetailPanel({ app }: { app: AppRow }) {
  const memPct = app.mem_bytes != null && app.mem_total_bytes
    ? (app.mem_bytes / app.mem_total_bytes) * 100 : null
  return (
    <div>
      {/* @container, not a viewport `lg:`, for the same reason the node
          overview gives (routes/hosts.tsx): a chart card needs roughly 200px
          of inner width to fit its non-wrapping 30m/1h/12h/24h range group,
          and the width of THIS BOX decides that, not the width of the window.
          Here the point is sharper still, because the box is a table cell that
          shares the page with a sidebar and seven other columns, so the
          viewport says nothing useful about how much room the cards get.

          Two flexible columns and an auto one, not three equal thirds: the
          third column holds a status pill and the update box, so a full
          third was mostly empty and took that width off the two charts that
          could use it. The charts split what is left. Below @3xl everything
          stacks to one column and the third block goes full width. */}
      <div className="@container">
        {/* minmax(0,1fr), NOT a bare 1fr. This is the whole reason the row
            used to overflow, and it is measured, not guessed.

            A bare `1fr` is `minmax(auto, 1fr)`, and that `auto` minimum is the
            track's min-content, which here is a fixed-pixel uPlot canvas. So
            the track could never shrink below the width the canvas happened to
            be drawn at: narrowing the window left the cards frozen (613/613/342
            at every viewport from 1500 down to 700), the canvases never
            redrew, and the third column's right edge stayed at 1579 while the
            container ended at 1100. Tailwind's own `grid-cols-3` does not have
            this problem because it already expands to repeat(3,minmax(0,1fr));
            only a hand-written template like this one can reintroduce it.

            The damage was not confined to this panel. It renders inside a
            <td colSpan={8}>, so a grid that refuses to shrink widens the whole
            APPS TABLE, which is what pushed the table's own Storage and
            Network columns off the right edge. */}
        <div className="grid grid-cols-1 gap-4 @3xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
          <div className={card}>
            <MetricChart target={`app:${app.id}`} metric="cpu_pct"
              unit="percent" label="CPU" accent="amber" />
          </div>
          <div className={card}>
            <MetricChart target={`app:${app.id}`} metric="mem_pct"
              unit="percent" label="Memory" accent="cyan" />
            {/* The chart is a percentage over time; this line is what that
                percentage is a percentage OF, which the chart cannot say. */}
            <div className="mt-2 font-mono text-[11px] text-text-3">
              {fmtBytes(app.mem_bytes)} of {fmtBytes(app.mem_total_bytes)} ({fmtPct(memPct)})
            </div>
          </div>
          {/* Third column, two boxes stacked: Status on top, Update filling
              whatever is left. The column is a grid item and grid items
              stretch, so "whatever is left" is exactly the height of one chart
              card, which is what makes the three columns line up along the
              bottom without any height being hard-coded.

              Update's body scrolls rather than growing. Its content is not one
              size: "Up to date." is a single line, a pending update adds a
              consent sentence and a button, and a running one adds a diff and
              a live job log. Letting the tallest of those set the row height
              would drag the charts taller with it every time an update landed,
              so the box keeps the row's height and scrolls inside. */}
          <div className="flex flex-col gap-4 @3xl:w-56">
            <div className={card}>
              <h3 className="mb-1.5 text-[11px] uppercase tracking-wide text-text-3">Status</h3>
              <StatusPill status={app.status} />
              <div className="mt-2 font-mono text-[12px] text-text-2">up {fmtUptime(app.uptime_s)}</div>
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
