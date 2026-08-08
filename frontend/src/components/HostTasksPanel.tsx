import { useState } from 'react'
import { useHostTaskLog, useHostTasks } from '../api/hosts'
import { QueryState } from './QueryState'
import { Button } from './ui/button'

function fmtTime(epoch: number | null): string {
  return epoch ? new Date(epoch * 1000).toLocaleString() : 'unknown'
}

/**
 * A passthrough read of the node's own task list (doc: "modest, not a log
 * viewer product"), one level of expansion (task -> its log lines) and no
 * more.
 */
export function HostTasksPanel({ hostId }: { hostId: number }) {
  const tasks = useHostTasks(hostId)
  const [selected, setSelected] = useState<string | null>(null)
  const log = useHostTaskLog(hostId, selected)

  return (
    <div className="py-3">
      <QueryState query={tasks}
                  emptyTitle="No recent tasks."
                  emptyNote=""
                  errorTitle="Tasks not readable"
                  errorNote="Proxploy could not reach the node for its task list.">
        {(rows) => (
          <table className="w-full text-left text-[12.5px]">
            <thead><tr className="text-[10px] uppercase tracking-wide text-text-3">
              <th className="pb-1">Type</th><th>Target</th><th>User</th>
              <th>Status</th><th>Started</th><th /></tr></thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.upid} className="border-t border-line-soft">
                  <td className="py-1 font-mono">{t.type ?? 'unknown'}</td>
                  <td className="font-mono text-text-2">{t.id ?? ''}</td>
                  <td className="text-text-2">{t.user ?? ''}</td>
                  <td className={t.status === 'stopped' && t.exitstatus === 'OK' ? 'text-green'
                    : t.status === 'stopped' ? 'text-red' : 'text-amber'}>
                    {t.status ?? 'unknown'}{t.exitstatus ? ` (${t.exitstatus})` : ''}
                  </td>
                  <td className="text-text-3">{fmtTime(t.starttime)}</td>
                  <td className="text-right">
                    <Button variant="ghost" className="px-2 py-0.5 text-[11px]"
                      onClick={() => setSelected((s) => (s === t.upid ? null : t.upid))}>
                      {selected === t.upid ? 'Hide log' : 'View log'}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </QueryState>
      {selected && (
        <div className="mt-3 border-t border-line-soft pt-3">
          <QueryState query={log}
                      emptyTitle="No log lines."
                      emptyNote=""
                      errorTitle="Log not readable"
                      errorNote="Proxploy could not reach the node for this task's log.">
            {(l) => (
              <pre className="max-h-64 overflow-auto rounded-ctl border border-line
                              bg-panel-2 p-2 font-mono text-[11px] text-text-2">
                {l.lines.join('\n')}
              </pre>
            )}
          </QueryState>
        </div>
      )}
    </div>
  )
}
