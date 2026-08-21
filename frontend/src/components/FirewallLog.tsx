import { QueryState } from './QueryState'
import { useFirewallLog } from '../api/firewall'
import type { LogScope } from '../api/firewall'

/** What PVE returns for a firewall that has logged nothing. Measured on
 *  pve-manager 9.2.11, 2026-08-21: a guest with no logging enabled answers
 *  with exactly one line whose text is "no content". That is PVE's way of
 *  saying the log is empty, not a log entry, and rendering it as one tells the
 *  operator their firewall logged something called "no content". */
const EMPTY = 'no content'

const real = (d: { lines?: { n: number; t: string }[] }) =>
  (d.lines ?? []).filter(l => l.t !== EMPTY)

export function FirewallLog({ scope }: { scope: LogScope }) {
  const q = useFirewallLog(scope)

  // "Nothing logged" and "the log could not be read" are different answers:
  // the first says the firewall is quiet, the second says Proxploy has no
  // idea whether it is.
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
        // Its own scroll container: a firewall log is long and the page must not
        // grow with it. overflow-x too, because a log line is not wrapped and
        // wrapping it would break the columns PVE writes.
        <div className="max-h-[60vh] overflow-auto rounded-ctl border border-line-soft bg-elev p-3">
          <pre className="font-mono text-[12px] leading-[1.55] text-text-2">
            {real(d).map(l => l.t).join('\n')}
          </pre>
        </div>
      )}
    </QueryState>
  )
}
