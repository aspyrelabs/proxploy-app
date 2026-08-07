import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import type { AppRow } from '../api/hooks'
import type { JobRow } from '../api/jobs'
import { TERMINAL } from '../api/jobs'
// One 409 unwrapper for the whole phase; it landed with the network page.
import { errBody } from '../api/network'
import type { MigrateStrategy, Preflight } from '../api/migrate'
import { useMigrate, usePreflight } from '../api/migrate'
import { fmtBytes } from '../lib/format'
import { ConfirmSelfDialog } from './ConfirmSelfDialog'
import { JobLog } from './JobLog'
import { inputCls } from './LoginForm'
import { Button } from './ui/button'

type HostRow = { id: number; name: string; status: string }

const STRATEGY_LABEL: Record<MigrateStrategy, (pf: Preflight) => string> = {
  cluster: () => 'These hosts share a cluster, native migration',
  shared_storage: (pf) => `Via shared storage ${pf.shared_storage}`,
  transfer: () => 'Backup, transfer, restore',
}

/**
 * Cross-host migration (backend/proxploy/services/migrate.py, doc 05 Tasks
 * 14-16). Pick a target host, run the real preflight, show the honest
 * strategy/size/downtime picture, blockers refuse submission, warnings
 * don't, then fire the job and follow it with the existing JobLog.
 *
 * The preflight's `est_downtime_s` is an ESTIMATE derived from an assumed
 * transfer rate (`est_note`/`downtime_statement` say so themselves). Once
 * the job is running, this dialog polls it and; on completion, shows the
 * job's own `result.downtime_s`, which is MEASURED wall-clock time, right
 * next to the estimate. The two numbers are never merged into one: an
 * estimate presented as a measurement would be exactly the kind of
 * plausible-looking lie doc 10's "accurate downtime shown" DoD exists to
 * rule out.
 */
export function MigrateDialog({ app, onClose }: { app: AppRow; onClose: () => void }) {
  const [targetHostId, setTargetHostId] = useState<number | null>(null)
  const [pf, setPf] = useState<Preflight | null>(null)
  const [error, setError] = useState('')
  const [guard, setGuard] = useState<{ phrase: string; detail: string } | null>(null)
  const [jobId, setJobId] = useState<number | null>(null)

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

  const runPreflight = (hostId: number) => {
    setTargetHostId(hostId)
    setPf(null)
    setError('')
    preflight.mutate({ appId: app.id, targetHostId: hostId }, {
      onSuccess: (r) => setPf(r),
      onError: (e) => setError(String(errBody(e)?.detail ?? 'Could not run preflight, try again.')),
    })
  }

  const fire = (confirm?: string) => {
    if (targetHostId == null) return
    setError('')
    migrate.mutate({ appId: app.id, targetHostId, confirm }, {
      onSuccess: (r) => { setGuard(null); setJobId(r.job.id) },
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
      <div role="dialog" aria-label="Migrate app"
           className="fixed inset-0 z-30 grid place-items-center bg-[rgba(11,15,22,.72)] backdrop-blur-[3px]">
        <div className="w-[560px] max-w-[92vw] rounded-card border border-line bg-panel p-5">
          <h2 className="font-display text-[16px] font-semibold text-text">
            Migrate <span className="font-mono">{app.name}</span>
          </h2>

          {jobId != null ? (
            <div className="mt-4">
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
              <JobLog jobId={jobId} />
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
                          disabled={hosts.isError}
                          onChange={(e) => { const v = e.target.value; if (v) runPreflight(Number(v)) }}>
                    {hosts.isError
                      ? <option value="">Could not load hosts</option>
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
                    <div>
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
              <div className="mt-4 flex justify-end gap-2">
                <Button variant="ghost" onClick={onClose}>Cancel</Button>
                <Button disabled={!pf || pf.blockers.length > 0 || migrate.isPending} onClick={() => fire()}>
                  {migrate.isPending ? 'Starting…' : 'Migrate'}
                </Button>
              </div>
            </>
          )}
        </div>
      </div>

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
