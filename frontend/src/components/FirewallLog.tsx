import { QueryState } from './QueryState'
import { useFirewallLog } from '../api/firewall'
import type { LogScope } from '../api/firewall'

/** PVE answers an empty firewall log with one line whose text is "no content"
 *  (seen on pve-manager 9.2.11): a sentinel meaning "log is empty", not an
 *  entry, so it is filtered out rather than shown to the operator. */
const EMPTY = 'no content'

const real = (d: { lines?: { n: number; t: string }[] }) =>
  (d.lines ?? []).filter(l => l.t !== EMPTY)

export function FirewallLog({ scope }: { scope: LogScope }) {
  const q = useFirewallLog(scope)

  return (
    <QueryState query={q}
      loading={<p className="text-[13px] text-text-3">Reading the firewall log...</p>}
      empty={(d) => real(d).length === 0}
      emptyTitle="Nothing logged yet"
      emptyNote={'Proxmox only writes here for rules that have a log level set, '
        + "and for the firewall's own incoming and outgoing log levels in Options."}
      errorTitle="Could not read the firewall log"
      errorNote={'Proxploy could not read this log, so nothing here says whether '
        + 'the firewall has been quiet or busy.'}>
      {(d) => (
        // A log line is not wrapped; wrapping it would break the columns PVE
        // writes, so scroll both axes instead of letting the page grow.
        <div className="max-h-[60vh] overflow-auto rounded-ctl border border-line-soft bg-elev p-3">
          <pre className="font-mono text-[12px] leading-[1.55] text-text-2">
            {real(d).map(l => l.t).join('\n')}
          </pre>
        </div>
      )}
    </QueryState>
  )
}
