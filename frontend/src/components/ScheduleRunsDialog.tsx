import { useState } from 'react'
import type { ScheduleRow } from '../api/schedules'
import { useScheduleRuns } from '../api/schedules'
import type { JobRow } from '../api/jobs'
import { duration, statusLabel } from '../lib/activityDisplay'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'
import { JobLog } from './JobLog'
import { QueryState } from './QueryState'

function outcomeClass(status: string): string {
  return status === 'succeeded' ? 'text-green'
    : status === 'failed' ? 'text-red' : 'text-text-3'
}

function str(v: unknown): string | null {
  if (v == null || v === '') return null
  return typeof v === 'object' ? JSON.stringify(v) : String(v)
}

function details(run: JobRow): [string, string][] {
  const p = run.params ?? {}
  const r = run.result ?? {}
  const vmids = Array.isArray(p.vmids) ? p.vmids : []
  const out: [string, string][] = []

  out.push(['Job', `#${run.id}`])
  if (run.target_name) out.push(['Host', run.target_name])
  out.push(['Started', run.started_at ? new Date(run.started_at).toLocaleString() : 'never started'])
  out.push(['Finished', run.finished_at ? new Date(run.finished_at).toLocaleString() : 'did not finish'])
  const took = duration(run)
  if (took) out.push(['Took', took])

  const storage = str(p.storage)
  out.push(['Archive lands on', storage ?? 'whichever backup storage Proxmox picks'])
  out.push(['What it backs up', vmids.length
    ? vmids.map(String).join(', ')
    : 'every container and virtual machine on the node'])
  const mode = str(p.mode)
  if (mode) out.push(['Mode', mode])
  if (p.verify === true) out.push(['Verify after', 'yes'])

  const guests = str(r.guests)
  if (guests) out.push(['Guests handed to vzdump', guests])
  const exitstatus = str(r.exitstatus)
  if (exitstatus) out.push(['Proxmox exit status', exitstatus])
  const upid = str(r.upid)
  if (upid) out.push(['Proxmox task', upid])
  const detail = str(r.detail)
  if (detail) out.push(['Outcome', detail])
  return out
}

export function ScheduleRunsDialog({ schedule, onClose }: {
  schedule: ScheduleRow
  onClose: () => void
}) {
  const runs = useScheduleRuns(schedule.id)
  const [selected, setSelected] = useState<number | null>(null)
  const rows = runs.data ?? []
  const run = rows.find((r) => r.id === selected) ?? rows[0] ?? null

  return (
    <Dialog title={`Runs: ${schedule.name}`} fit onClose={onClose}>
      <div className="flex h-[calc(60vh-7rem)] w-[calc(60vw-2.5rem)] min-h-0 min-w-0
                      flex-col overflow-hidden">
        <QueryState query={runs}
                    emptyTitle="No runs yet"
                    emptyNote="This schedule has not run in the last 30 days."
                    errorTitle="Run history not readable"
                    errorNote="Proxploy could not reach the backend for this schedule's runs.">
          {() => (
            <div className="flex min-h-0 min-w-0 flex-1 gap-4">
              <div className="w-[34%] min-w-0 shrink-0 overflow-y-auto pr-1">
                <table className="w-full text-left text-[12.5px]">
                  <thead><tr className="text-[10px] uppercase tracking-wide text-text-3">
                    <th className="pb-1">When</th><th>Outcome</th><th>Took</th></tr></thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.id}
                          className={`cursor-pointer border-t border-line-soft hover:bg-panel-2
                                     ${run?.id === r.id ? 'bg-panel-2' : ''}`}
                          onClick={() => setSelected(r.id)}>
                        <td className="py-1.5 pr-2">
                          {new Date(r.started_at ?? r.created_at).toLocaleString()}
                        </td>
                        <td className={`pr-2 ${outcomeClass(r.status)}`}>{statusLabel(r.status)}</td>
                        <td className="text-text-3">{duration(r) ?? ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-3">
                {run && (
                  <div className="max-h-[40%] shrink-0 overflow-y-auto rounded-tile
                                  border border-line-soft bg-panel-2 p-3">
                    <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-[12px]">
                      {details(run).map(([k, v]) => (
                        <div key={k} className="flex min-w-0 gap-2">
                          <span className="shrink-0 text-text-3">{k}</span>
                          <span className="truncate text-text-2" title={v}>{v}</span>
                        </div>
                      ))}
                    </div>
                    {run.status === 'failed' && run.error && (
                      <div className="mt-2 break-words border-t border-line-soft pt-2
                                      text-[12px] text-red">
                        {run.error}
                      </div>
                    )}
                  </div>
                )}
                <div className="flex min-h-0 min-w-0 flex-1 flex-col
                                [&>div]:min-h-0 [&>div]:min-w-0 [&>div]:flex-1">
                  {run && <JobLog jobId={run.id} height="fill" />}
                </div>
              </div>
            </div>
          )}
        </QueryState>
      </div>
      <Button className="mt-3 shrink-0" variant="ghost" onClick={onClose}>Close</Button>
    </Dialog>
  )
}
