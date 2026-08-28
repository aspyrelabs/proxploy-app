import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { createRoute } from '@tanstack/react-router'
import { shellRoute } from './shell'
import { notify } from '../lib/notify'
import { api, apiErrorDetail } from '../api/client'
import { GuestPicker, useBackupStores, useHostGuests } from '../components/BackupPickers'
import { useEntitlements } from '../api/hooks'
import { useBackups, useDeleteBackup, usePrune, usePrunePreview, useRunBackup,
         useTestRestore, useVerifyBackup, useVerifySweep } from '../api/backups'
import type { BackupRow, BackupsResponse, PruneParams } from '../api/backups'
import { useRunningJobOfKind } from '../api/jobs'
import { SIX_COL, TABLE_MIN, TABLE_SCROLL, TablePager, usePaged } from '../components/TablePager'
import { ButtonGroup, ButtonGroupSeparator } from '../components/ui/button-group'
import { RowActionsMenu } from '../components/ui/row-actions'
import { useSchedules } from '../api/schedules'
import { useStorage } from '../api/storage'
import { BackupLimitsDialog, limitsAcknowledged } from '../components/BackupLimitsDialog'
import { EmptyState } from '../components/EmptyState'
import { JobLog } from '../components/JobLog'
import { LockVeil } from '../components/LockVeil'
import { RestoreDialog } from '../components/RestoreDialog'
import { ScheduleForm } from '../components/ScheduleForm'
// From the route, not a copy: SchedulesCard owns the row actions.
import { SchedulesCard } from './settings'
import { BACKUP_KINDS } from '../api/schedules'
import { StorageForm } from '../components/StorageForm'
import { UsageBar, STORAGE_GRADIENT } from '../components/UsageBar'
import { Button } from '../components/ui/button'
import { inputCls } from '../components/LoginForm'
import { fmtBytes, fmtPct } from '../lib/format'
import { Dialog } from '../components/ui/dialog'
import { Loading } from '../components/ui/loading'
import { Progress, ProgressLabel, ProgressValue } from '../components/ui/progress'
import { Skeleton, SkeletonGroup, SkeletonLine, SkeletonTable } from '../components/ui/skeleton'

const card = 'rounded-card border border-line-soft bg-panel p-5'
const th = 'pb-2 font-medium'

function fmtWhen(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : 'unknown'
}

function StatCard({ label, value, note, loading }: {
  label: string; value: string; note: React.ReactNode; loading?: boolean
}) {
  // The label stays put while data loads. Without this, cold-load
  // unknowns read as findings.
  return (
    <div className={card}>
      <div className="text-[11px] uppercase tracking-wide text-text-3">{label}</div>
      {loading ? (
        <SkeletonGroup label={`Loading ${label.toLowerCase()}`}>
          <SkeletonLine className="mt-1 w-32 text-[24px]" />
          <SkeletonLine className="mt-2 w-48 max-w-full text-[13px]" />
        </SkeletonGroup>
      ) : (
        <>
          <div className="mt-1 font-mono text-[24px] text-text">{value}</div>
          <div className="mt-2 text-[13px] text-text-3">{note}</div>
        </>
      )}
    </div>
  )
}

/** Run now → one vzdump job over every guest on the chosen host, then the log. */
function RunDialog({ onClose }: { onClose: () => void }) {
  const hosts = useQuery({
    queryKey: ['hosts'],
    queryFn: () => api<{ id: number; name: string; cluster_name?: string | null }[]>('/hosts'),
  })
  // vzdump writes to any storage with `backup` content, not just PBS.
  // Needs at least one guest — a run over an empty node dumped nothing
  // and reported success. services/backupjobs.py::run_backup carries the
  // same check server-side.
  const run = useRunBackup()
  const sweep = useVerifySweep()
  const [picked, setPicked] = useState<number | null>(null)
  const [store, setStore] = useState('')
  // null is "every guest on the host", which POST /backups/run still receives
  // as `all`: a subset is a list of ids, and the two are different requests.
  const [only, setOnly] = useState<Set<string> | null>(null)
  // Both on by default: a backup you haven't read back is a guess.
  // Independent: Verify alone reads what's already there, needs no
  // backup taken just now.
  const [doBackup, setDoBackup] = useState(true)
  const [doVerify, setDoVerify] = useState(true)
  const [jobId, setJobId] = useState<number | null>(null)
  // null until the job's first progress frame: an indeterminate bar is the
  // honest state before vzdump has said anything.
  const [pct, setPct] = useState<number | null>(null)
  // One vzdump task runs on one node, so the backend requires host_id whenever
  // more than one host is registered; with exactly one there is nothing to ask.
  const hostId = picked ?? (hosts.data?.length === 1 ? hosts.data[0].id : null)

  const hostName = hosts.data?.find((h) => h.id === hostId)?.name ?? 'that host'
  // Ticked, not just counted. vzdump takes a vmid list — always did.
  const onHost = useHostGuests(hostId)
  const guests = onHost.guests.length
  const chosen = only ?? new Set(onHost.guests.map((g) => g.key))
  const store$ = useBackupStores(
    hostId, (hosts.data ?? []).find((h) => h.id === hostId)?.cluster_name)
  const stores = store$.stores
  // Nothing concluded while in flight: an empty list means "not
  // fetched yet" as readily as "nothing there".
  const checking = onHost.pending || store$.pending
  // Reset to the first eligible store when host changes. Never empty
  // while a store exists: an unset storage is the "PVE picked, nobody
  // knows which" case.
  const target = stores.some((s) => s.storage === store) ? store : (stores[0]?.storage ?? '')
  const blocked = checking || hostId == null ? null
    : guests === 0
      ? `${hostName} has no containers and no virtual machines, so a backup would `
        + `write nothing.`
      : stores.length === 0
        ? `No storage on ${hostName} accepts backups. Add one on the Storage page, or `
          + `connect a Proxmox Backup Server.`
        : null

  return (
    <Dialog title={'Run a backup now'} width={480} onClose={onClose}>
    {jobId != null ? (
      <div className="mt-4">
        {/* Fed by the job's own progress frames via
                    services/pvetask.py::await_task. */}
        <Progress value={pct} className="mb-3">
          <ProgressLabel>Backing up</ProgressLabel>
          <ProgressValue />
        </Progress>
        <JobLog jobId={jobId} onProgress={setPct} />
        <Button className="mt-3" variant="ghost" onClick={onClose}>Close</Button>
      </div>
    ) : (
      <>
        <p className="mt-2 text-[12.5px] text-text-3">
          Backs up the{' '}
          <strong className="text-text-2">containers and virtual machines you tick</strong>{' '}
          below, in snapshot mode, so they keep running. That is your installed apps (each
          one is a container) and your VMs. It does not back up Proxploy&apos;s own settings
          or database.
        </p>
        <select className={`${inputCls} mt-4`} value={hostId ?? ''}
                aria-label="Host" disabled={hosts.isError || hosts.isLoading}
                onChange={(e) => {
                  setPicked(Number(e.target.value) || null); setStore(''); setOnly(null)
                }}>
          {hosts.isError
            ? <option value="">Could not load hosts</option>
            : hosts.isLoading
              ? <option value="">Loading hosts…</option>
              : <option value="">Select a host…</option>}
          {(hosts.data ?? []).map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
        </select>
        {blocked ? (
          <p className="mt-3 rounded-ctl border border-amber/30 bg-amber-dim p-2 text-[12.5px] text-text-2">
            {blocked}
          </p>
        ) : hostId != null && checking ? (
          /* A host is chosen but the three lists are still in flight, so
                       `blocked` is null. */
          <SkeletonGroup label="Checking what is on this host">
            {/* "N guests on host will be backed up: a, b, c" wraps to two lines. */}
            <SkeletonLine className="mt-3 w-full text-[12.5px]" />
            <SkeletonLine className="w-2/3 text-[12.5px]" />
            <SkeletonLine className="mt-4 w-32 text-[11px]" />
            <Skeleton className="h-[38px] w-full rounded-ctl" />
          </SkeletonGroup>
        ) : hostId != null && (
          <>
            {/* The scope, before the click, and now editable. */}
            <div className="mt-3">
              <GuestPicker guests={onHost.guests} selected={only}
                           onChange={setOnly} idPrefix="bk-run" />
            </div>
            <label className="mt-4 block text-[11px] uppercase tracking-wide text-text-3"
                   htmlFor="bk-store">Archive lands on</label>
            <select id="bk-store" className={inputCls} value={target}
                    onChange={(e) => setStore(e.target.value)}>
              {stores.map((s) => (
                <option key={s.storage} value={s.storage}>
                  {s.storage}{s.type ? ` (${s.type})` : ''}
                </option>
              ))}
            </select>
            {/* Verify is queued as its own job once the run has written
                            archives. With Backup unticked there is no run to follow
                            — Verify sweeps what is already on the host. */}
            <div className="mt-3 space-y-2">
              <label className="flex items-center gap-2 text-[12.5px] text-text-2">
                <input type="checkbox" checked={doBackup}
                       onChange={(e) => setDoBackup(e.target.checked)} />
                Backup
              </label>
              <label className="flex items-center gap-2 text-[12.5px] text-text-2">
                <input type="checkbox" checked={doVerify}
                       onChange={(e) => setDoVerify(e.target.checked)} />
                Verify Backup
              </label>
            </div>
          </>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button disabled={hostId == null || blocked != null
                            || run.isPending || sweep.isPending
                            // Neither ticked is not a job. Said on the button
                            // rather than by starting nothing and looking
                            // broken.
                            || (!doBackup && !doVerify)
                            // The guest list only constrains a run; a verify
                            // sweep is about archives already written.
                            || (doBackup && only != null && only.size === 0)}
                  title={!doBackup && !doVerify
                    ? 'Tick Backup, Verify Backup, or both'
                    : blocked ?? undefined}
                  onClick={() => {
                    if (!doBackup) {
                      // Verify on its own: nothing is written, the host's
                      // unchecked archives are read back. Same job kind a
                      // schedule fires, so the feed reads identically.
                      sweep.mutate({ hostId: hostId as number, storage: target }, {
                        onSuccess: (r) => setJobId(r.job.id),
                        onError: () => notify.error(
                          'Could not start that check, try again.'),
                      })
                      return
                    }
                    run.mutate({
                      hostId,
                      storage: target,
                      // Omitted when everything is ticked, so the hook keeps
                      // sending `all`.
                      guests: chosen.size === guests ? undefined
                        : onHost.guests.filter((g) => chosen.has(g.key))
                            .map((g) => ({ type: g.type, id: g.id })),
                      verify: doVerify,
                    }, {
                      onSuccess: (r) => setJobId(r.job.id),
                      onError: () => notify.error('Could not start the backup, try again.'),
                    })
                  }}>
            {run.isPending || sweep.isPending ? 'Starting…'
              : doBackup ? 'Start backup' : 'Start check'}
          </Button>
        </div>
      </>
    )}
    </Dialog>
  )
}

/** "New job" → a backup.run schedule, in the same dialog shell as RunDialog. */
function ScheduleDialog({ onClose }: { onClose: () => void }) {
  return (
    <Dialog title={'New scheduled backup job'} width={480} scrollBody onClose={onClose}>
    {/* Same sentence as RunDialog: "backup" on its own reads as
            unqualified. No longer promises "every" guest: the form below
            picks which. */}
    <p className="mt-2 text-[12.5px] text-text-3">
      Runs on a schedule and backs up the{' '}
      <strong className="text-text-2">containers and virtual machines you tick</strong> on the
      host you choose: your installed apps and your VMs, not Proxploy&apos;s own settings.
    </p>
    <div className="mt-4">
      <ScheduleForm jobKind="backup.run" onSaved={onClose} />
    </div>
    <div className="mt-4 flex justify-end">
      <Button variant="ghost" onClick={onClose}>Cancel</Button>
    </div>
    </Dialog>
  )
}

const MARK_CLS: Record<string, string> = {
  keep: 'border-green/30 bg-green-dim text-green',
  remove: 'border-red/30 bg-red-dim text-red',
  protected: 'border-blue/30 bg-blue-dim text-blue',
}

/**
 * Retention preview (Pro), plus execution on exactly what it showed.
 * "Prune now" only appears once a preview has run, and fires
 * POST /backups/prune with the same PruneParams.
 */
// `pending` is drilled in beside `data`: `stats.datastores` is empty both
// when a host has no datastore and while GET /backups is still in flight.
function RetentionSection({ data, pending }: {
  data: BackupsResponse | undefined; pending: boolean
}) {
  const ent = useEntitlements()
  const locked = ent.data != null && !ent.has('backups.retention')
  const stores = data?.stats.datastores ?? []
  const [storage, setStorage] = useState('')
  const [keepLast, setKeepLast] = useState('3')
  const [keepDaily, setKeepDaily] = useState('7')
  const [params, setParams] = useState<PruneParams | null>(null)
  const preview = usePrunePreview(params)
  const prune = usePrune()
  const [pruneJobId, setPruneJobId] = useState<number | null>(null)

  const chosen = storage || stores[0]?.storage || ''
  const hostId = data?.backups.find((b) => b.storage === chosen)?.host_id ?? null
  const rows = preview.data ?? []
  const count = (m: string) => rows.filter((r) => r.mark === m).length
  // The 422 ("at least one keep-* value is required") is a last resort.
  // Catch it here, against the params the preview itself ran with.
  const canPrune = params != null && (params.keepLast >= 1 || params.keepDaily >= 1)

  const runPrune = () => {
    if (!params || !canPrune) return
    if (!window.confirm(
      `Remove ${count('remove')} archive(s) from ${params.storage}? This cannot be undone.`)) return
    setPruneJobId(null)
    prune.mutate(params, {
      onSuccess: (r) => setPruneJobId(r.job.id),
      onError: () => notify.error('Could not start the prune, try again.'),
    })
  }

  return (
    <div className="mt-4">
      <LockVeil locked={locked}
        title="Retention preview is a Pro feature"
        subtitle="See exactly which archives a keep-rule would drop, before anything is deleted.">
        <section className={card}>
          <h2 className="font-display text-[16px] font-semibold">Retention preview</h2>
          <p className="mt-1 rounded-ctl border border-amber/30 bg-amber-dim p-2 text-[12.5px] text-text-2">
            <span className="text-amber">Dry run.</span> This preview only asks Proxmox what a
            retention rule <em>would</em> do, it deletes nothing on its own. Prune now, below,
            only appears once you have reviewed exactly what a rule would remove.
          </p>

          <div className="mt-4 flex flex-wrap items-end gap-3">
            <div>
              <label className="mb-1 block text-[11px] uppercase tracking-wide text-text-3"
                     htmlFor="rt-store">Datastore</label>
              <select id="rt-store" className={inputCls} value={chosen}
                      disabled={pending}
                      onChange={(e) => setStorage(e.target.value)}>
                {pending && <option value="">Loading datastores…</option>}
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
              Proxmox refused that rule, at least one keep value must be above zero.
            </p>
          )}

          {/* "Preview retention" had no pending state. This is the one
                        surface on the page where someone is waiting on a thing
                        they explicitly asked for. `params != null` guards it
                        because a disabled query sits at pending for ever. */}
          {params != null && preview.isPending && (
            <SkeletonGroup label="Previewing retention">
              <SkeletonLine className="mt-4 w-56 text-[12px]" />
              {/* Volume, Guest, Created, Mark. */}
              <div className="mt-2">
                <SkeletonTable rows={4} cols={['w-56', 'w-20', 'w-24', 'w-16']} />
              </div>
            </SkeletonGroup>
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
                        {r.type ?? 'unknown'} {r.vmid ?? ''}
                      </td>
                      <td className="py-2.5 text-text-2">
                        {r.ctime ? new Date(r.ctime * 1000).toLocaleDateString() : 'unknown'}
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
              <div className="mt-4 flex items-center justify-end gap-3">
                {!canPrune && (
                  <span className="text-[12px] text-text-3">
                    At least one keep value must be 1 or more to prune.
                  </span>
                )}
                <Button variant="danger" disabled={!canPrune || prune.isPending}
                        title={!canPrune ? 'At least one keep value must be 1 or more' : undefined}
                        onClick={runPrune}>
                  {prune.isPending ? 'Pruning…' : `Prune now (${count('remove')} to remove)`}
                </Button>
              </div>
              {pruneJobId != null && <div className="mt-3"><JobLog jobId={pruneJobId} /></div>}
            </>
          )}
        </section>
      </LockVeil>
    </div>
  )
}

export function BackupsPage() {
  const ent = useEntitlements()
  const { data, isError, isPending } = useBackups()
  // Client-side: the rows are already here (GET /backups sends the newest 200
  // in one go), so paging them asks the server for nothing.
  const paged = usePaged(data?.backups ?? [])
  // Whether there is anywhere to back UP to is a question about storage,
  // not about archives. `stats.datastores` only knows stores that already
  // hold something.
  const storage = useStorage()
  const backupStores = (storage.data ?? []).filter((s) => s.content.includes('backup'))
  const verify = useVerifyBackup()
  const testRestore = useTestRestore()
  // Which datastores Proxmox Backup Server owns. PBS checks against stored
  // digests; our own check reads the whole thing back and knows less, so it's
  // not offered. Per archive, not per install.
  const pbsStores = new Set((storage.data ?? [])
    .filter((s) => s.type === 'pbs').map((s) => s.storage))
  const pbsOwned = (b: BackupRow) => b.storage != null && pbsStores.has(b.storage)
  // services/backupjobs.py::sync_backups is the only genuinely granular
  // progress. GET /backups enqueues it fire-and-forget.
  const syncJob = useRunningJobOfKind('backup.sync', Boolean(data?.stale))
  const [running, setRunning] = useState(false)
  const [restoring, setRestoring] = useState<BackupRow | null>(null)
  const [connecting, setConnecting] = useState(false)
  const [scheduling, setScheduling] = useState(false)
  // Read once on mount. "Remind me later" lasts until leaving the page;
  // "I understand" writes to localStorage and never asks again.
  const [limits, setLimits] = useState(() => !limitsAcknowledged())
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
  // DELETE /backups/{id} moved from backups.pbs to backups.retention.
  // Gate the button on the same key the route checks, or a tenant with
  // backups.pbs but not backups.retention sees a Delete button that 403s.
  const deleteDenied = ent.data != null && !ent.has('backups.retention')

  const drop = (b: BackupRow) => {
    if (!window.confirm(
      `Delete ${b.volid}? The archive is removed from ${b.storage} and cannot be recovered.`)) return
    del.mutate(b.id, {
      onError: () => notify.error('Could not delete that archive, try again.'),
    })
  }

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-[22px] font-semibold">Backups</h1>
          <div className="text-[12px] text-text-3">
            {isPending || storage.isPending
              ? (
                <SkeletonGroup label="Loading backup datastore">
                  <SkeletonLine className="w-64 max-w-full text-[12px]" />
                </SkeletonGroup>
              )
              /* Used to read off `biggest`, so a datastore that holds nothing
                               yet was reported as no datastore at all. "Nothing in it
                               yet" is the Datastore used card's line. Also called every
                               store a PBS; an NFS export with backup content type is
                               not one. */
              : storage.isError
                ? 'Could not read the storage list'
                : backupStores.length === 0
                  ? 'No backup datastore found. Add a Proxmox Backup Server, an NFS or '
                    + 'SMB share, or a folder on the node, with Backups ticked as its content.'
                  /* Which stores they are is the Storage page's job; this says
                                       whether there is somewhere to write and what is already
                                       there. The archive COUNT, because nothing else reports
                                       the count. */
                  : `${backupStores.length} datastore`
                    + `${backupStores.length === 1 ? ' accepts' : 's accept'} backups · `
                    + (stats?.total
                        ? `${stats.total} archive${stats.total === 1 ? '' : 's'}`
                        : 'no archives yet')}
            {data?.stale && (
              <span className="ml-2 inline-flex items-center gap-1.5 text-amber">
                {/* Only when the sync job has actually reported something:
                                    progress_pct is null before the first host completes. */}
                {syncJob.data?.progress_pct != null && (
                  <Loading value={syncJob.data.progress_pct} label="Syncing backups" size={16} />
                )}
                <span>· refreshing from Proxmox…</span>
              </span>
            )}
          </div>
        </div>
        <div className="flex gap-2">
          {/* Connecting PBS is just attaching a storage of type `pbs`, and
                        the same form the Storage page uses already attaches any of
                        them. Shown always, not only when empty. Server enforces
                        `storage.manage`; the form carries its own LockVeil. */}
          <Button variant="ghost" onClick={() => setConnecting(true)}>
            Add storage
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
        <StatCard label="Next scheduled" loading={schedules.isPending}
          value={nextBackup ? new Date(nextBackup.next_run_at!).toLocaleString() : 'unknown'}
          note={nextBackup
            ? `${nextBackup.name} · ${nextBackup.cron} ${nextBackup.timezone}`
            : 'No backup schedule yet, "New job" creates one.'} />
        <StatCard label="Datastore used" loading={isPending}
          value={fmtBytes(stats?.total_bytes)}
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
        {/* Two different questions. "Verified" needs PBS: it's the only
                    thing that writes verify_state. On a plain NFS or directory
                    store, what's knowable is whether the RUNS finished — an
                    archive was written, never that it restores. */}
        {stats?.success_rate_30d != null ? (
          <StatCard label="Backup Integrity · 30d" loading={isPending}
            value={fmtPct(stats.success_rate_30d)}
            note={`${stats.ok_count} verified · ${stats.failed_count} failed`} />
        ) : (
          <StatCard label="Backups completed · 30d" loading={isPending}
            value={fmtPct(stats?.run_rate_30d)}
            note={stats?.run_rate_30d == null
              ? 'No backup has run in the last 30 days.'
              : `${stats.runs_ok_30d} finished · ${stats.runs_failed_30d} failed. `
                + 'Nothing checks that an archive can be restored without '
                + 'Proxmox Backup Server.'} />
        )}
      </div>

      {/* The jobs, above the archives they produce. Same card, filtered
                to the kind this page owns. */}
      <div className="mt-4">
        {/* Both kinds this page can CREATE. It filtered to backup.run alone,
                    so the verify-only job was invisible on the page that saved it. */}
        <SchedulesCard only={BACKUP_KINDS} title="Scheduled jobs"
                       canAdd={false} />
      </div>

      <div className={`${card} mt-4`}>
        <h2 className="mb-3 font-display text-[16px] font-semibold">Recent backups</h2>
        {isPending ? (
          /* Ordered BEFORE the empty check on purpose. `data?.backups.length
                       ?? 0` is 0 while the first fetch is still in flight. */
          <SkeletonGroup label="Loading backups">
            {/* Guest, Host, When, Size, Status, actions. */}
            <SkeletonTable cols={['w-32', 'w-24', 'w-28', 'w-16', 'w-20', 'w-24']} />
          </SkeletonGroup>
        ) : isError ? (
          <EmptyState title="Backups not readable"
            note="Proxploy mirrors archives from each host's backup datastores, check that the host is connected." />
        ) : (data?.backups.length ?? 0) === 0 ? (
          <EmptyState title="No backups yet"
            note="Archives Proxmox already holds appear here after the first sync." />
        ) : (
          <>
          <div className={TABLE_SCROLL}>
          <table className={`w-full ${TABLE_MIN} table-fixed text-left text-[13px] [&_td]:pr-4 [&_th]:pr-4`}>
            {SIX_COL}
            <thead>
              <tr className="text-[11px] uppercase text-text-3">
                <th scope="col" className={th}>Guest</th>
                {/* GET /backups returns host_name; the `backups` table has no node
                                    column, so this is labelled honestly. */}
                <th scope="col" className={th}>Host</th>
                <th scope="col" className={th}>When</th>
                <th scope="col" className={th}>Size</th>
                <th scope="col" className={th}>Status</th>
                <th scope="col" className={th}></th>
              </tr>
            </thead>
            <tbody>
              {paged.rows.map((b) => (
                <tr key={b.id} className="border-t border-line-soft hover:bg-panel-2">
                  <td className="truncate py-2.5 font-mono">
                    {b.guest_name ?? 'unknown'}
                    <span className="ml-2 text-[11px] text-text-3">
                      {b.guest_type?.toUpperCase()} {b.guest_vmid}
                    </span>
                  </td>
                  <td className="truncate py-2.5 text-text-2"
                      title={b.host_name ?? 'unknown'}>{b.host_name ?? 'unknown'}</td>
                  <td className="py-2.5 text-text-2">{fmtWhen(b.taken_at)}</td>
                  <td className="py-2.5 font-mono text-text-2">{fmtBytes(b.size_bytes)}</td>
                  <td className={`py-2.5 text-[12px] ${
                    b.verify_state === 'ok' ? 'text-green'
                      : b.verify_state === 'failed' ? 'text-red' : 'text-text-3'}`}>
                    {b.verify_state === 'ok' ? 'verified'
                      : b.verify_state === 'failed' ? 'failed' : 'unverified'}
                  </td>
                  <td className="py-2.5 text-right">
                    <ButtonGroup>
                      <Button variant="ghost" size="sm"
                              disabled={verify.isPending || pbsOwned(b)}
                              title={pbsOwned(b)
                                ? 'Proxmox Backup Server checks this archive itself'
                                : 'Read the archive back and check it is intact'}
                              onClick={() => verify.mutate(b.id, {
                                onError: (e) => notify.error(
                                  apiErrorDetail(e, 'Could not start that check, try again.')),
                              })}>
                        Verify
                      </Button>
                      <ButtonGroupSeparator />
                      <Button variant="ghost" size="sm"
                              disabled={restoreDenied}
                              title={restoreDenied ? 'Not included in your plan' : undefined}
                              onClick={() => setRestoring(b)}>
                        Restore
                      </Button>
                      <ButtonGroupSeparator />
                      <RowActionsMenu label={`More actions for ${b.guest_name ?? 'this backup'}`}
                        actions={[
                          { label: 'Test restore', icon: 'restart_alt',
                            disabled: testRestore.isPending || pbsOwned(b),
                            title: pbsOwned(b)
                              ? 'Proxmox Backup Server checks this archive itself'
                              : 'Restore into a throwaway id, then delete it',
                            onSelect: () => testRestore.mutate({ id: b.id }, {
                              onError: (e) => notify.error(
                                apiErrorDetail(e, 'Could not start that test restore, try again.')),
                            }) },
                          { label: 'Delete', icon: 'delete', destructive: true,
                            disabled: deleteDenied,
                            title: deleteDenied ? 'Not included in your plan' : undefined,
                            onSelect: () => drop(b) },
                        ]} />
                    </ButtonGroup>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
          <TablePager page={paged.page} pages={paged.pages} onPage={paged.setPage}
                      label="Recent backups pages" />
          </>
        )}
      </div>

      <RetentionSection data={data} pending={isPending} />

      {running && <RunDialog onClose={() => setRunning(false)} />}
      {restoring && <RestoreDialog backup={restoring} onClose={() => setRestoring(null)} />}
      {connecting && (
        <StorageForm existing={null} onClose={() => setConnecting(false)} />
      )}
      {scheduling && <ScheduleDialog onClose={() => setScheduling(false)} />}
      {limits && (
        <BackupLimitsDialog onClose={() => setLimits(false)}
                            onAgree={() => setLimits(false)} />
      )}
    </div>
  )
}

// shellRoute from ./shell, never ../router.
export const backupsRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/backups',
  component: BackupsPage,
})
