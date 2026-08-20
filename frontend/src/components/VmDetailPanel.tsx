import type { VmRow } from '../api/hooks'
import { MetricChart } from './charts/MetricChart'
import { InfoHint } from './ui/info-hint'
import { KVGrid } from './KVGrid'
import { SnapshotPanel } from './SnapshotPanel'
import { StatusPill } from './StatusPill'
import { fmtBytes, fmtPct, fmtUptime } from '../lib/format'

// p-4, not the page's p-5: these cards sit inside a table row that already
// carries the table's own padding, and the extra ring of space read as a gap
// rather than as a card.
const card = 'rounded-card border border-line-soft bg-panel-2 p-4'

/** Why "Not installed" matters, in one line. Deliberately short and
 *  deliberately NOT a copy of VmTable's storage hint: this row states the
 *  cause, that hint states the consequence and what to do, and repeating the
 *  whole instruction in both places is how two wordings drift apart. */
const NO_AGENT = 'Storage usage reads unknown for this VM because only the '
               + 'guest agent can report how full its disk is.'

/**
 * One VM's detail, as it appears inside the VMs table rather than on a page
 * of its own.
 *
 * The row object is already in hand by the time this renders, so `vm` is a
 * prop and there is no query for it here. The page this replaced fetched
 * /vms/{id} a second time purely because a URL was all it had.
 */
export function VmDetailPanel({ vm }: { vm: VmRow }) {
  const memPct = vm.mem_bytes != null && vm.mem_total_bytes
    ? (vm.mem_bytes / vm.mem_total_bytes) * 100 : null
  return (
    <div>
      {/* @container, not a viewport `lg:`, for the same reason the node
          overview gives (routes/hosts.tsx): a chart card needs roughly 200px
          of inner width to fit its non-wrapping 30m/1h/12h/24h range group,
          and the width of THIS BOX decides that, not the width of the window.
          Here the point is sharper still, because the box is a table cell that
          shares the page with a sidebar and the table's other columns, so the
          viewport says nothing useful about how much room the cards get.

          Two flexible columns and an auto one, not three equal thirds: the
          third column holds a status pill and a few resource figures, so a
          full third was mostly empty and took that width off the two charts
          that could use it. Below @3xl everything stacks to one column and the
          third block goes full width. */}
      <div className="@container">
        {/* minmax(0,1fr), NOT a bare 1fr. This is the whole reason the Apps
            row used to overflow, and it is measured, not guessed.

            A bare `1fr` is `minmax(auto, 1fr)`, and that `auto` minimum is the
            track's min-content, which here is a fixed-pixel uPlot canvas. So
            the track could never shrink below the width the canvas happened to
            be drawn at: narrowing the window left the cards frozen (613/613/342
            at every viewport from 1500 down to 700), the canvases never
            redrew, and the third column's right edge stayed at 1579 while the
            container ended at 1100. Tailwind's own `grid-cols-3` does not have
            this problem because it already expands to repeat(3,minmax(0,1fr));
            only a hand-written template like this one can reintroduce it.

            The damage was not confined to that panel. It renders inside a
            <td colSpan>, so a grid that refuses to shrink widens the whole
            table, which is what pushed the table's own right-hand columns off
            the edge of the screen. src/tests/grid-track-minimums.test.ts fails
            the build if a bare 1fr comes back. */}
        <div className="grid grid-cols-1 gap-4 @3xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
          <div className={card}>
            <MetricChart target={`vm:${vm.id}`} metric="cpu_pct"
              unit="percent" label="CPU" accent="amber" />
          </div>
          <div className={card}>
            <MetricChart target={`vm:${vm.id}`} metric="mem_pct"
              unit="percent" label="Memory" accent="cyan" />
            {/* The same "x of y" line the Apps panel carries. A VM row used to
                report only one memory figure, the amount assigned, so there was
                no pair to write here; it now reports used and assigned under
                the same two names an app uses, so the sentence is the same
                sentence. */}
            <div className="mt-2 font-mono text-[11px] text-text-3">
              {fmtBytes(vm.mem_bytes)} of {fmtBytes(vm.mem_total_bytes)} ({fmtPct(memPct)})
            </div>
          </div>
          {/* Third column, two boxes stacked: Status on top, Resources filling
              whatever is left. The column is a grid item and grid items
              stretch, so "whatever is left" is exactly the height of one chart
              card, which is what makes the three columns line up along the
              bottom without any height being hard-coded. */}
          <div className="flex flex-col gap-4 @3xl:w-56">
            <div className={card}>
              <h3 className="mb-1.5 text-[11px] uppercase tracking-wide text-text-3">Status</h3>
              <StatusPill status={vm.status} />
              <div className="mt-2 font-mono text-[12px] text-text-2">up {fmtUptime(vm.uptime_s)}</div>
            </div>
            <div className={`${card} flex-1`}>
              <h3 className="mb-1.5 text-[11px] uppercase tracking-wide text-text-3">Resources</h3>
              {/* One figure per line rather than the page's single dotted row:
                  this column is 224px wide, so the three would wrap anywhere. */}
              <div className="space-y-1 font-mono text-[12px] text-text-2">
                {/* ALLOCATION, all three: this box answers how big the VM
                    is, not how hard it is working, and the used figures live
                    in the charts to the left. mem_bytes/disk_bytes used to
                    hold these numbers and no longer do, so reading them here
                    would now label the memory in use as the memory assigned,
                    silently and on every VM. */}
                <div>{vm.cpu_cores ?? 'unknown'} vCPU</div>
                <div>{fmtBytes(vm.mem_total_bytes)} RAM</div>
                <div>{fmtBytes(vm.disk_total_bytes)} disk</div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div className={`${card} mt-4`}>
        <KVGrid items={[
          ['VMID', vm.vmid],
          ['Node', vm.host_name],
          // Allocated, matching the Resources box above. The used figure is
          // null on a VM with no QEMU guest agent, so a row that reported it
          // here would read "unknown" for a disk whose size is known.
          ['Disk', fmtBytes(vm.disk_total_bytes)],
          ['OS type', vm.os_type ?? 'unknown'],
          // Replaced "Last checked", which showed when the poller last
          // stamped this row. That told an operator the poller was running,
          // which every live figure above already tells them, and there was
          // nothing to do about it either way. This row can be acted on: the
          // guest agent is what reports a VM's real disk usage, so "Not
          // installed" here is the answer to why the Storage column on the
          // row above reads unknown. The hint says only that much and leaves
          // the how to the storage hint, which is where somebody looking at
          // the missing number will already be.
          //
          // Three states, not two, and `=== true` / `=== false` rather than a
          // truthiness test on purpose: null means nobody knows (never
          // probed, the VM is stopped so nothing inside it can answer, or its
          // host was unreachable), and printing "Not installed" for that
          // would send an operator to install something that may well already
          // be there. "unknown" is the same word the Storage column uses for
          // the same situation.
          ['Guest agent', vm.guest_agent_ok === true ? 'Installed'
            : vm.guest_agent_ok === false
              ? <span>Not installed <InfoHint text={NO_AGENT} /></span>
              : 'unknown'],
        ]} />
      </div>
      {/* Full width and always open, not behind a dialog or a menu. Snapshots
          are the reason most people open a VM row at all, and a panel that is
          already on screen costs one click fewer than one that has to be
          summoned, then dismissed to get back to the row. */}
      {/* No heading here: SnapshotPanel draws its own, because the heading and
          the "Take snapshot" button share a row and splitting them across two
          components would put the title in one file and its button in another. */}
      <div className={`${card} mt-4`}>
        <SnapshotPanel vmId={vm.id} vmName={vm.name} />
      </div>
    </div>
  )
}
