import { useNavigate, useSearch } from '@tanstack/react-router'
import { useJobs, useCancelJob } from '../api/jobs'
import type { JobRow } from '../api/jobs'
import { JobLog } from './JobLog'
import { QueryState } from './QueryState'
import { UsageBar } from './UsageBar'
import { Button } from './ui/button'

type DrawerSearch = { drawer?: 'activity'; job?: number }

/** Search-param state so the drawer overlays any page (doc 06). */
export function useActivityDrawer() {
  const search = useSearch({ strict: false }) as DrawerSearch
  const navigate = useNavigate()
  // as never: the search type can't be narrowed from a strict:false read, 
  // same router-typing workaround used across the route files.
  const set = (patch: DrawerSearch) =>
    navigate({ search: ((prev: DrawerSearch) => ({ ...prev, ...patch })) as never,
               replace: true })
  return {
    open: search.drawer === 'activity',
    jobId: search.job ?? null,
    toggle: () => set({ drawer: search.drawer === 'activity' ? undefined : 'activity' }),
    openJob: (id: number) => set({ drawer: 'activity', job: id }),
    close: () => set({ drawer: undefined, job: undefined }),
  }
}

const STATUS_CLASS: Record<string, string> = {
  succeeded: 'text-green', failed: 'text-red', canceled: 'text-text-3',
  interrupted: 'text-amber', running: 'text-blue', queued: 'text-text-3',
}

function JobItem({ job, expanded, onExpand }:
  { job: JobRow; expanded: boolean; onExpand: () => void }) {
  const cancel = useCancelJob()
  const live = job.status === 'running' || job.status === 'queued'
  return (
    <div data-testid="drawer-job" className="border-b border-line-soft px-4 py-3">
      <div className="flex items-center gap-2">
        <button className="flex-1 text-left" onClick={onExpand}>
          <div className="font-mono text-[12.5px] text-text">{job.kind}</div>
          <div className="font-mono text-[11px] text-text-3">
            #{job.id} · {job.target_type ?? 'system'}
            {job.target_id != null ? ` ${job.target_id}` : ''}
          </div>
        </button>
        <span className={`font-mono text-[11px] ${STATUS_CLASS[job.status] ?? 'text-text-2'}`}>
          {job.status}
        </span>
        {live && (
          <Button variant="ghost" className="px-2 py-1 text-[11px]"
            disabled={cancel.isPending} onClick={() => cancel.mutate(job.id)}>
            Cancel
          </Button>
        )}
      </div>
      {live && <div className="mt-2"><UsageBar pct={job.progress_pct} /></div>}
      {job.error && <div className="mt-1 text-[11.5px] text-red">{job.error}</div>}
      {expanded && <div className="mt-3"><JobLog jobId={job.id} /></div>}
    </div>
  )
}

export function ActivityDrawer() {
  const { open, jobId, openJob, close } = useActivityDrawer()
  // GET /jobs already orders newest-first server-side (doc 06). Do not
  // re-sort here: string-comparing ISO created_at timestamps client-side
  // reproduces the zero-microsecond tie bug the backend explicitly avoids, 
  // a bare 'Z' sorts after a fractional-second suffix like '.123456Z', so a
  // zero-microsecond row would sort as newer than a genuinely later
  // same-second row.
  const jobsQuery = useJobs({ enabled: open })
  if (!open) return null
  return (
    <aside
      role="dialog"
      aria-label="Activity"
      className="fixed inset-y-0 right-0 z-20 flex w-[400px] max-w-full flex-col border-l border-line bg-panel-2"
    >
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <h2 className="font-display text-[15px] font-semibold">Activity</h2>
        <Button variant="ghost" className="px-2 py-1 text-[12px]" onClick={close}>
          Close
        </Button>
      </div>
      <div className="flex-1 overflow-auto">
        <QueryState query={jobsQuery}
                    emptyTitle="No jobs yet."
                    emptyNote="Lifecycle actions, installs and backups show up here."
                    errorTitle="Activity not readable"
                    errorNote="Proxploy could not reach the backend to list recent jobs.">
          {(sorted) => (
            <>
              {sorted.map((j) => (
                <JobItem key={j.id} job={j} expanded={jobId === j.id}
                  onExpand={() => openJob(j.id)} />
              ))}
            </>
          )}
        </QueryState>
      </div>
    </aside>
  )
}
