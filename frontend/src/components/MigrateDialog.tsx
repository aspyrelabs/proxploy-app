import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import type { AppRow } from '../api/hooks'
import type { JobRow } from '../api/jobs'
import { TERMINAL } from '../api/jobs'
// One 409 unwrapper for the whole phase.
import { errBody } from '../api/network'
import type { MigrateStrategy, Preflight } from '../api/migrate'
import { useMigrate, usePreflight } from '../api/migrate'
import { fmtBytes } from '../lib/format'
import { ConfirmSelfDialog } from './ConfirmSelfDialog'
import { JobLog } from './JobLog'
import { inputCls } from './LoginForm'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'
import { Loading } from './ui/loading'

type HostRow = { id: number; name: string; status: string }

const STRATEGY_LABEL: Record<MigrateStrategy, (pf: Preflight) => string> = {
  cluster: () => 'These hosts share a cluster, native migration',
  shared_storage: (pf) => `Via shared storage ${pf.shared_storage}`,
  transfer: () => 'Backup, transfer, restore',
}

/**
 * Cross-host migration (backend/proxploy/services/migrate.py).
 *
 * The preflight's est_downtime_s is an ESTIMATE derived from an assumed
 * transfer rate. After the job completes, result.downtime_s is MEASURED
 * wall-clock time. The two numbers are never merged: an estimate presented
 * as a measurement would violate the "accurate downtime shown" acceptance
 * criterion.
 */
export function MigrateDialog({ app, onClose }: { app: AppRow; onClose: () => void }) {
  const [targetHostId, setTargetHostId] = useState<number | null>(null)
  const [pf, setPf] = useState<Preflight | null>(null)
  const [error, setError] = useState('')
  const [guard, setGuard] = useState<{ phrase: string; detail: string } | null>(null)
  const [jobId, setJobId] = useState<number | null>(null)
  // services/migrate.py's on_progress callback (Task 16's SFTP hop) is
  // byte-level, the most granular signal in the product, but it only fires
  // on the transfer strategy; cluster/shared-storage migrations, and every
  // phase before the first frame arrives on any strategy, leave this null.
  // Seeded from the job row rather than assumed zero, same as InstallDialog.
  const [progress, setProgress] = useState<number | null>(null)

  const hosts = useQuery({ queryKey: ['hosts'], queryFn: () => api<HostRow[]>('/hosts') })
  const targets = (hosts.data ?? []).filter((h) => h.id !== app.host_id)

  const preflight = usePreflight()
  const migrate = useMigrate()

  // Independent poll from JobLog's own SSE stream, this only needs to know
  // when `result.downtime_s` (the measured number) shows up, not the
  // transcript. TERMINAL matches jobs.ts's own terminal-status list.
  const job = useQuery({
    queryKey: ['jobs', jobId],
    enabled: jobId != null,
    queryFn: () => api<JobRow>(`/jobs/${jobId}`),
    refetchInterval: (q) => (q.state.data && TERMINAL.includes(q.state.data.status) ? false : 2000),
  })
  const measuredDowntime = job.data?.result?.downtime_s as number | undefined

  // The rootfs pool the operator picked. Null means "whatever preflight
  // defaults to" (the first candidate).
  const [storage, setStorage] = useState<string | null>(null)

  const runPreflight = (hostId: number, pick: string | null = null) => {
    setTargetHostId(hostId)
    setPf(null)
    setError('')
    preflight.mutate({ appId: app.id, targetHostId: hostId, storage: pick }, {
      onSuccess: (r) => setPf(r),
      onError: (e) => setError(String(errBody(e)?.detail ?? 'Could not run preflight, try again.')),
    })
  }

  // Re-previews on the new pool: capacity is per pool, so the answer above the
  // button has to be about the pool that is actually selected.
  const pickStorage = (name: string) => {
    const pick = name || null
    setStorage(pick)
    if (targetHostId != null) runPreflight(targetHostId, pick)
  }

  const fire = (confirm?: string) => {
    if (targetHostId == null) return
    setError('')
    migrate.mutate({ appId: app.id, targetHostId, confirm, storage }, {
      onSuccess: (r) => { setGuard(null); setJobId(r.job.id); setProgress(r.job.progress_pct ?? null) },
      onError: (e) => {
        const b = errBody(e)
        if (b?.error === 'self_target') {
          setGuard({ phrase: String(b.confirm_phrase ?? app.name), detail: String(b.detail ?? '') })
          return
        }
        setGuard(null)
        // A fresh preflight inside the route found blockers the dialog's own
        // (now-stale) preflight didn't, state changed in the gap between
        // opening the dialog and clicking Migrate. Show the real reason, not
        // a bare "migration_blocked".
        if (b?.error === 'migration_blocked' && Array.isArray(b.blockers)) {
          setError(b.blockers.join('; '))
          return
        }
        setError(String(b?.detail ?? b?.error ?? 'Could not start the migration, try again.'))
      },
    })
  }

  return (
    <>
      <Dialog title={<>Migrate <span className="font-mono">{app.name}</span></>} width={560} onClose={onClose}>

      {jobId != null ? (
        <div className="mt-4">
          <div className="mb-3 flex items-center gap-2">
            {/* Determinate only once a real figure has arrived (progress
                seeded from the job row, then updated by JobLog's onProgress,
                the same SSE connection commit 168330d wired for install/
                update). Indeterminate otherwise, cluster and shared-storage
                migrations never emit anything finer than pvetask.py's start/
                end brackets, and even the transfer strategy has nothing to
                show before its SFTP hop begins, never a zero standing in for
                a real value. */}
            <Loading value={progress ?? undefined} label="Migration progress" size={28} />
            <span className="text-[12.5px] text-text-2">Migrating {app.name}…</span>
          </div>
          <div className="mb-3 rounded-ctl border border-line-soft bg-elev p-2 text-[12.5px] text-text-2">
            <div>
              est. downtime: {pf?.est_downtime_s != null ? `${pf.est_downtime_s}s` : 'unknown'} (estimate)
            </div>
            <div>
              actual downtime: {measuredDowntime != null
                ? `${measuredDowntime.toFixed(1)}s (measured)`
                : 'not finished yet'}
            </div>
          </div>
          <JobLog jobId={jobId} onProgress={setProgress} />
          <Button className="mt-3" variant="ghost" onClick={onClose}>Close</Button>
        </div>
      ) : (
        <>
          <div className="mt-4 space-y-3">
            <div>
              <label htmlFor="migrate-target"
                     className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
                Target host
              </label>
              <select id="migrate-target" className={inputCls} value={targetHostId ?? ''}
                      disabled={hosts.isError || hosts.isLoading}
                      onChange={(e) => { const v = e.target.value; if (v) runPreflight(Number(v)) }}>
                {hosts.isError
                  ? <option value="">Could not load hosts</option>
                  : hosts.isLoading
                    ? <option value="">Loading hosts…</option>
                    : <option value="">Select a host…</option>}
                {targets.map((h) => (
                  <option key={h.id} value={h.id} disabled={h.status !== 'connected'}>
                    {h.name}{h.status !== 'connected' ? ` (${h.status})` : ''}
                  </option>
                ))}
              </select>
            </div>

            {preflight.isPending && <p className="text-[12.5px] text-text-3">Checking…</p>}

            {pf && (
              <div className="space-y-2 rounded-ctl border border-line-soft bg-elev p-3 text-[12.5px] text-text-2">
                <div className="text-text">{STRATEGY_LABEL[pf.strategy](pf)}</div>
                <div>
                  transfer size:{' '}
                  {pf.transfer_bytes != null
                    ? `${fmtBytes(pf.transfer_bytes)} (${pf.estimate_basis === 'last_backup' ? 'from last backup' : 'live disk size'})`
                    : 'unknown, no measured backup and no live disk size were available'}
                </div>
                <div>
                  est. downtime: {pf.est_downtime_s != null ? `${pf.est_downtime_s}s` : 'unknown'} (estimate)
                </div>
                <div className="text-text-3">{pf.downtime_statement}</div>
                {(pf.rootfs_options?.length ?? 0) > 0 && (
                  <div className="flex flex-wrap items-center gap-2">
                    <label htmlFor="migrate-storage">lands on:</label>
                    <select id="migrate-storage" value={storage ?? pf.rootfs_storage ?? ''}
                      onChange={(e) => pickStorage(e.target.value)}
                      className="rounded-ctl border border-line bg-panel px-2 py-1
                                 font-mono text-[11.5px] text-text">
                      {pf.rootfs_options?.map((s) => (
                        <option key={s} value={s}>{s}</option>
                      ))}
                    </select>
                    {pf.staging_storage && pf.staging_storage !== pf.rootfs_storage && (
                      <span>
                        staged via{' '}
                        <span className="font-mono text-[11.5px]">{pf.staging_storage}</span>
                      </span>
                    )}
                  </div>
                )}
                <div>
                  {/* Covers both pools: the archive's and the disk's. */}
                  target capacity:{' '}
                  {pf.capacity_ok == null ? 'unknown' : pf.capacity_ok ? 'OK' : 'insufficient'}
                </div>
                {pf.warnings.length > 0 && (
                  <ul className="list-disc space-y-0.5 pl-4 text-amber">
                    {pf.warnings.map((w, i) => <li key={i}>{w}</li>)}
                  </ul>
                )}
                {pf.blockers.length > 0 && (
                  <ul className="list-disc space-y-0.5 pl-4 text-red">
                    {pf.blockers.map((b, i) => <li key={i}>{b}</li>)}
                  </ul>
                )}
              </div>
            )}

            {error && <p className="text-[12.5px] text-red">{error}</p>}
          </div>
          <div className="mt-4 flex items-center justify-end gap-2">
            {/* This is the POST that creates the job, before it has an id: there
                is no honest figure for "how close is starting" regardless of
                whether the job itself later reports byte progress. Ring, not
                a number. */}
            {migrate.isPending && <Loading label="Starting the migration" size={18} className="mr-auto" />}
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button disabled={!pf || pf.blockers.length > 0 || migrate.isPending} onClick={() => fire()}>
              {migrate.isPending ? 'Starting…' : 'Migrate'}
            </Button>
          </div>
        </>
      )}
      </Dialog>

      {guard && (
        <ConfirmSelfDialog
          title={`Migrate ${guard.phrase}`}
          phrase={guard.phrase}
          detail={guard.detail}
          onConfirm={(typed) => fire(typed)}
          onCancel={() => setGuard(null)} />
      )}
    </>
  )
}
