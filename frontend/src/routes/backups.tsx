import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { createRoute } from '@tanstack/react-router'
import { toast } from 'sonner'
import { shellRoute } from './shell'
import { api } from '../api/client'
import { useEntitlements } from '../api/hooks'
import { useBackups, useDeleteBackup, usePrunePreview, useRunBackup } from '../api/backups'
import type { BackupRow, BackupsResponse, PruneParams } from '../api/backups'
import { useSchedules } from '../api/schedules'
import { EmptyState } from '../components/EmptyState'
import { JobLog } from '../components/JobLog'
import { LockVeil } from '../components/LockVeil'
import { RestoreDialog } from '../components/RestoreDialog'
import { ScheduleForm } from '../components/ScheduleForm'
import { StorageForm } from '../components/StorageForm'
import { UsageBar, STORAGE_GRADIENT } from '../components/UsageBar'
import { Button } from '../components/ui/button'
import { inputCls } from '../components/LoginForm'
import { fmtBytes, fmtPct } from '../lib/format'

const card = 'rounded-card border border-line-soft bg-panel p-5'
const th = 'pb-2 font-medium'

function fmtWhen(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : '—'
}

function StatCard({ label, value, note }: { label: string; value: string; note: React.ReactNode }) {
  return (
    <div className={card}>
      <div className="text-[11px] uppercase tracking-wide text-text-3">{label}</div>
      <div className="mt-1 font-mono text-[20px] text-text">{value}</div>
      <div className="mt-2 text-[12px] text-text-3">{note}</div>
    </div>
  )
}

/** Run now → one vzdump job over every guest on the chosen host, then the log. */
function RunDialog({ onClose }: { onClose: () => void }) {
  const { data: hosts } = useQuery({
    queryKey: ['hosts'], queryFn: () => api<{ id: number; name: string }[]>('/hosts'),
  })
  const run = useRunBackup()
  const [picked, setPicked] = useState<number | null>(null)
  const [jobId, setJobId] = useState<number | null>(null)
  // One vzdump task runs on one node, so the backend requires host_id whenever
  // more than one host is registered; with exactly one there is nothing to ask.
  const hostId = picked ?? (hosts?.length === 1 ? hosts[0].id : null)

  return (
    <div role="dialog" aria-label="Run backup"
         className="fixed inset-0 z-30 grid place-items-center bg-[rgba(11,15,22,.72)] backdrop-blur-[3px]">
      <div className="w-[480px] max-w-[92vw] rounded-card border border-line bg-panel p-5">
        <h2 className="font-display text-[16px] font-semibold">Run a backup now</h2>
        {jobId != null ? (
          <div className="mt-4">
            <JobLog jobId={jobId} />
            <Button className="mt-3" variant="ghost" onClick={onClose}>Close</Button>
          </div>
        ) : (
          <>
            <p className="mt-2 text-[12.5px] text-text-3">
              Backs up every guest on the selected host in snapshot mode, to that host&apos;s
              default backup datastore.
            </p>
            <select className={`${inputCls} mt-4`} value={hostId ?? ''}
                    aria-label="Host"
                    onChange={(e) => setPicked(Number(e.target.value) || null)}>
              <option value="">Select a host…</option>
              {(hosts ?? []).map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
            </select>
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="ghost" onClick={onClose}>Cancel</Button>
              <Button disabled={hostId == null || run.isPending}
                      onClick={() => run.mutate({ hostId }, {
                        onSuccess: (r) => setJobId(r.job.id),
                        onError: () => toast.error('Could not start the backup — try again.'),
                      })}>
                {run.isPending ? 'Starting…' : 'Start backup'}
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

/** "New job" → a backup.run schedule, in the same dialog shell as RunDialog. */
function ScheduleDialog({ onClose }: { onClose: () => void }) {
  return (
    <div role="dialog" aria-label="New scheduled job"
         className="fixed inset-0 z-30 grid place-items-center bg-[rgba(11,15,22,.72)] backdrop-blur-[3px]">
      <div className="w-[480px] max-w-[92vw] rounded-card border border-line bg-panel p-5">
        <h2 className="font-display text-[16px] font-semibold">New scheduled backup job</h2>
        <div className="mt-4">
          <ScheduleForm jobKind="backup.run" onSaved={onClose} />
        </div>
        <div className="mt-4 flex justify-end">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
        </div>
      </div>
    </div>
  )
}

const MARK_CLS: Record<string, string> = {
  keep: 'border-green/30 bg-green-dim text-green',
  remove: 'border-red/30 bg-red-dim text-red',
  protected: 'border-blue/30 bg-blue-dim text-blue',
}

/**
 * Retention preview (Pro). A dry run and nothing else.
 *
 * ponytail: POST /backups/prune is deliberately not wired. A one-shot "prune
 * now" button whose keep-* rules cannot be saved anywhere is the wrong half of
 * retention to ship first; this view is what proves the spec does what the
 * operator meant before a scheduled `backup.prune` is worth building. That
 * job kind isn't offered under Settings → Schedules yet — its handler needs
 * a datastore + keep-rule payload this preview doesn't collect — so there is
 * nowhere to wire it up to today.
 */
function RetentionSection({ data }: { data: BackupsResponse | undefined }) {
  const ent = useEntitlements()
  const locked = ent.data != null && !ent.has('backups.retention')
  const stores = data?.stats.datastores ?? []
  const [storage, setStorage] = useState('')
  const [keepLast, setKeepLast] = useState('3')
  const [keepDaily, setKeepDaily] = useState('7')
  const [params, setParams] = useState<PruneParams | null>(null)
  const preview = usePrunePreview(params)

  const chosen = storage || stores[0]?.storage || ''
  const hostId = data?.backups.find((b) => b.storage === chosen)?.host_id ?? null
  const rows = preview.data ?? []
  const count = (m: string) => rows.filter((r) => r.mark === m).length

  return (
    <div className="mt-4">
      <LockVeil locked={locked}
        title="Retention preview is a Pro feature"
        subtitle="See exactly which archives a keep-rule would drop, before anything is deleted.">
        <section className={card}>
          <h2 className="font-display text-[16px] font-semibold">Retention preview</h2>
          <p className="mt-1 rounded-ctl border border-amber/30 bg-amber-dim p-2 text-[12.5px] text-text-2">
            <span className="text-amber">Dry run.</span> This preview only asks Proxmox what a
            retention rule <em>would</em> do — it deletes nothing, and there is no button here
            that does.
          </p>

          <div className="mt-4 flex flex-wrap items-end gap-3">
            <div>
              <label className="mb-1 block text-[11px] uppercase tracking-wide text-text-3"
                     htmlFor="rt-store">Datastore</label>
              <select id="rt-store" className={inputCls} value={chosen}
                      onChange={(e) => setStorage(e.target.value)}>
                {stores.map((s) => <option key={s.storage} value={s.storage}>{s.storage}</option>)}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-[11px] uppercase tracking-wide text-text-3"
                     htmlFor="rt-last">Keep last</label>
              <input id="rt-last" type="number" min={0} className={inputCls}
                     value={keepLast} onChange={(e) => setKeepLast(e.target.value)} />
            </div>
            <div>
              <label className="mb-1 block text-[11px] uppercase tracking-wide text-text-3"
                     htmlFor="rt-daily">Keep daily</label>
              <input id="rt-daily" type="number" min={0} className={inputCls}
                     value={keepDaily} onChange={(e) => setKeepDaily(e.target.value)} />
            </div>
            <Button variant="ghost"
                    disabled={hostId == null || !chosen}
                    onClick={() => setParams({
                      hostId: hostId as number, storage: chosen,
                      keepLast: Number(keepLast) || 0, keepDaily: Number(keepDaily) || 0,
                    })}>
              Preview retention
            </Button>
          </div>

          {preview.isError && (
            <p className="mt-3 text-[12.5px] text-red">
              Proxmox refused that rule — at least one keep value must be above zero.
            </p>
          )}

          {rows.length > 0 && (
            <>
              <div className="mt-4 font-mono text-[12px] text-text-3">
                {count('keep')} keep · {count('remove')} remove · {count('protected')} protected
              </div>
              <table className="mt-2 w-full text-left text-[13px]">
                <thead>
                  <tr className="text-[11px] uppercase text-text-3">
                    <th scope="col" className={th}>Volume</th>
                    <th scope="col" className={th}>Guest</th>
                    <th scope="col" className={th}>Created</th>
                    <th scope="col" className={th}>Mark</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.volid} className="border-t border-line-soft hover:bg-panel-2">
                      <td className="py-2.5 font-mono text-[11.5px] text-text-2 break-all">{r.volid}</td>
                      <td className="py-2.5 font-mono text-text-2">
                        {r.type ?? '—'} {r.vmid ?? ''}
                      </td>
                      <td className="py-2.5 text-text-2">
                        {r.ctime ? new Date(r.ctime * 1000).toLocaleDateString() : '—'}
                      </td>
                      <td className="py-2.5">
                        <span className={`rounded-full border px-2 py-0.5 text-[11px] ${MARK_CLS[r.mark] ?? ''}`}>
                          {r.mark}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </section>
      </LockVeil>
    </div>
  )
}

export function BackupsPage() {
  const ent = useEntitlements()
  const { data, isError } = useBackups()
  const [running, setRunning] = useState(false)
  const [restoring, setRestoring] = useState<BackupRow | null>(null)
  const [connecting, setConnecting] = useState(false)
  const [scheduling, setScheduling] = useState(false)
  const del = useDeleteBackup()

  const schedules = useSchedules()
  const nextBackup = (schedules.data ?? [])
    .filter((s) => s.enabled && s.job_kind === 'backup.run' && s.next_run_at)
    .sort((a, b) => (a.next_run_at! < b.next_run_at! ? -1 : 1))[0]

  const stats = data?.stats
  const stores = stats?.datastores ?? []
  const biggest = stores[0]
  const runDenied = ent.data != null && !ent.has('backups.run')
  const restoreDenied = ent.data != null && !ent.has('backups.restore')
  // DELETE /backups/{id} moved from backups.pbs to backups.retention in the
  // final Phase 6 review (BLOCKING 3/item 6) — gate the button on the same
  // key the route now checks, or a tenant with backups.pbs but not
  // backups.retention sees a Delete button that just 403s.
  const deleteDenied = ent.data != null && !ent.has('backups.retention')

  const drop = (b: BackupRow) => {
    if (!window.confirm(
      `Delete ${b.volid}? The archive is removed from ${b.storage} and cannot be recovered.`)) return
    del.mutate(b.id, {
      onError: () => toast.error('Could not delete that archive — try again.'),
    })
  }

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-[22px] font-semibold">Backups</h1>
          <div className="text-[12px] text-text-3">
            {data
              ? (biggest
                  ? `Proxmox Backup Server · ${biggest.storage}`
                  : 'No backup datastore found yet')
              : '…'}
            {data?.stale && <span className="ml-2 text-amber">· refreshing from Proxmox…</span>}
          </div>
        </div>
        <div className="flex gap-2">
          {/* doc 10's "PBS datastore connect". Connecting PBS is exactly
              attaching a storage of type `pbs`, so this opens Task 13's
              StorageForm pre-set rather than duplicating it. Shown always,
              not only when empty — a second datastore is a normal thing to
              add. Server enforces `storage.manage`; the form carries its own
              LockVeil, so no gate is needed on the trigger. */}
          <Button variant="ghost" onClick={() => setConnecting(true)}>
            Connect PBS
          </Button>
          <Button variant="ghost" onClick={() => setScheduling(true)}>
            New job
          </Button>
          <Button disabled={runDenied}
                  title={runDenied ? 'Not included in your plan' : undefined}
                  onClick={() => setRunning(true)}>
            Run now
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <StatCard label="Next scheduled"
          value={nextBackup ? new Date(nextBackup.next_run_at!).toLocaleString() : '—'}
          note={nextBackup
            ? `${nextBackup.name} · ${nextBackup.cron} ${nextBackup.timezone}`
            : 'No backup schedule yet — "New job" creates one.'} />
        <StatCard label="Datastore used" value={fmtBytes(stats?.total_bytes)}
          note={
            <>
              <UsageBar gradient={STORAGE_GRADIENT}
                pct={stats?.total_bytes && biggest ? (biggest.size_bytes / stats.total_bytes) * 100 : 0} />
              <span className="mt-2 block">
                {biggest ? `${biggest.storage} holds ${fmtBytes(biggest.size_bytes)} of it` : 'No archives yet'}
                {' '}· datastore capacity lives on the Storage page.
              </span>
            </>
          } />
        <StatCard label="Success rate · 30d"
          value={stats?.success_rate_30d == null ? '—' : fmtPct(stats.success_rate_30d)}
          note={stats?.success_rate_30d == null
            ? 'Nothing verified in the last 30 days — unverified archives are left out rather than counted as passes.'
            : `${stats.ok_count} verified · ${stats.failed_count} failed`} />
      </div>

      <div className={`${card} mt-4`}>
        <h2 className="mb-3 font-display text-[16px] font-semibold">Recent backups</h2>
        {isError ? (
          <EmptyState title="Backups not readable"
            note="Proxploy mirrors archives from each host's backup datastores — check that the host is connected." />
        ) : (data?.backups.length ?? 0) === 0 ? (
          <EmptyState title="No backups yet"
            note="Archives Proxmox already holds appear here after the first sync." />
        ) : (
          <table className="w-full text-left text-[13px]">
            <thead>
              <tr className="text-[11px] uppercase text-text-3">
                <th scope="col" className={th}>Guest</th>
                {/* GET /backups returns host_name; the `backups` table has no node
                    column, so this is labelled honestly (doc 06 says "Node"). */}
                <th scope="col" className={th}>Host</th>
                <th scope="col" className={th}>When</th>
                <th scope="col" className={th}>Size</th>
                <th scope="col" className={th}>Status</th>
                <th scope="col" className={th}></th>
              </tr>
            </thead>
            <tbody>
              {(data?.backups ?? []).map((b) => (
                <tr key={b.id} className="border-t border-line-soft hover:bg-panel-2">
                  <td className="py-2.5 font-mono">
                    {b.guest_name ?? '—'}
                    <span className="ml-2 text-[11px] text-text-3">
                      {b.guest_type?.toUpperCase()} {b.guest_vmid}
                    </span>
                  </td>
                  <td className="py-2.5 text-text-2">{b.host_name ?? '—'}</td>
                  <td className="py-2.5 text-text-2">{fmtWhen(b.taken_at)}</td>
                  <td className="py-2.5 font-mono text-text-2">{fmtBytes(b.size_bytes)}</td>
                  <td className={`py-2.5 text-[12px] ${
                    b.verify_state === 'ok' ? 'text-green'
                      : b.verify_state === 'failed' ? 'text-red' : 'text-text-3'}`}>
                    {b.verify_state === 'ok' ? 'verified'
                      : b.verify_state === 'failed' ? 'failed' : 'unverified'}
                  </td>
                  <td className="py-2.5 text-right">
                    <Button variant="ghost" className="px-2 py-1 text-[11px]"
                            disabled={restoreDenied}
                            title={restoreDenied ? 'Not included in your plan' : undefined}
                            onClick={() => setRestoring(b)}>
                      Restore
                    </Button>
                    <Button variant="danger" className="ml-2 px-2 py-1 text-[11px]"
                            disabled={deleteDenied}
                            title={deleteDenied ? 'Not included in your plan' : undefined}
                            onClick={() => drop(b)}>
                      Delete
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <RetentionSection data={data} />

      {running && <RunDialog onClose={() => setRunning(false)} />}
      {restoring && <RestoreDialog backup={restoring} onClose={() => setRestoring(null)} />}
      {connecting && (
        <StorageForm existing={null} defaultType="pbs" onClose={() => setConnecting(false)} />
      )}
      {scheduling && <ScheduleDialog onClose={() => setScheduling(false)} />}
    </div>
  )
}

// shellRoute from ./shell, never ../router (cluster.tsx:273-277).
export const backupsRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/backups',
  component: BackupsPage,
})
