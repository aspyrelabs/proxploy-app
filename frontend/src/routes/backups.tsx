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
import { useSchedules } from '../api/schedules'
import { useStorage } from '../api/storage'
import { BackupLimitsDialog, limitsAcknowledged } from '../components/BackupLimitsDialog'
import { EmptyState } from '../components/EmptyState'
import { JobLog } from '../components/JobLog'
import { LockVeil } from '../components/LockVeil'
import { RestoreDialog } from '../components/RestoreDialog'
import { ScheduleForm } from '../components/ScheduleForm'
// From the route, not a copy: SchedulesCard owns the row actions (run, enable,
// edit, remove) and there is no second implementation of them.
import { SchedulesCard } from './settings'
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
  // The label is known before the data is, so it stays put and only the two
  // lines under it wait. Without this the row stated three answers on every
  // cold load ("unknown", "No backup schedule yet", "Nothing verified in the
  // last 30 days") that read as findings rather than as a page still loading,
  // to an operator who has a nightly schedule and a month of verified
  // archives.
  return (
    <div className={card}>
      <div className="text-[11px] uppercase tracking-wide text-text-3">{label}</div>
      {loading ? (
        <SkeletonGroup label={`Loading ${label.toLowerCase()}`}>
          <SkeletonLine className="mt-1 w-32 text-[20px]" />
          <SkeletonLine className="mt-2 w-48 max-w-full text-[12px]" />
        </SkeletonGroup>
      ) : (
        <>
          <div className="mt-1 font-mono text-[20px] text-text">{value}</div>
          <div className="mt-2 text-[12px] text-text-3">{note}</div>
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
  // The two honest preconditions for a backup, neither of which is "a Proxmox
  // Backup Server is connected": vzdump writes to ANY storage carrying `backup`
  // content (a plain directory store and an NFS share both qualify, and a lab
  // with no PBS at all backs up perfectly well), and it needs at least one
  // guest to dump. The second one is what went wrong: a run over a node with
  // no containers and no VMs dumped nothing and reported success, so the
  // dialog now says so before the click rather than after it
  // (services/backupjobs.py::run_backup carries the same check server-side,
  // because a schedule fires with no dialog in front of it).
  //
  // Same query keys the Apps, VMs and Storage pages already fetch under, so
  // this shares their cache rather than adding three requests.
  const run = useRunBackup()
  const sweep = useVerifySweep()
  const [picked, setPicked] = useState<number | null>(null)
  const [store, setStore] = useState('')
  // null is "every guest on the host", which POST /backups/run still receives
  // as `all`: a subset is a list of ids, and the two are different requests.
  const [only, setOnly] = useState<Set<string> | null>(null)
  // Both on by default: a backup you have not read back is a backup you are
  // guessing about, so the pair is the normal thing to want.
  //
  // They are independent, and that is the point. Backup alone writes archives
  // and leaves them; Verify Backup alone reads back what is already there,
  // which is the same host sweep a schedule fires (POST /backups/verify) and
  // needs no backup to have been taken just now. Untick both and there is
  // nothing to start, which the button says rather than guesses at.
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
  // Ticked, not just counted. The scope of this button used to be every guest
  // on the node with no way to say otherwise, so an operator who wanted one
  // container had to dump the lot; vzdump takes a vmid list and always did.
  const onHost = useHostGuests(hostId)
  const guests = onHost.guests.length
  const chosen = only ?? new Set(onHost.guests.map((g) => g.key))
  const store$ = useBackupStores(
    hostId, (hosts.data ?? []).find((h) => h.id === hostId)?.cluster_name)
  const stores = store$.stores
  // Nothing is concluded while those are still in flight: an empty list means
  // "not fetched yet" exactly as readily as "nothing there", and this page
  // must not state a finding before it has looked (StatCard's rule).
  const checking = onHost.pending || store$.pending
  // Reset to the first eligible store whenever the chosen host changes, so a
  // leftover name from the previous host is never sent to a node that has no
  // such store. Never left empty while a store exists: an unset storage is
  // exactly the "PVE picked, nobody knows which" case this dialog now avoids.
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
        {/* Fed by the job's own progress frames, which now carry vzdump's
            per-guest percentage out of the task log rather than sitting on 10
            until the whole run finishes (services/pvetask.py::await_task). */}
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
          /* A host is chosen and the three lists it is judged against (apps,
             VMs, storage) are still in flight, so `blocked` is deliberately
             null and the branch below is deliberately not drawn yet. That left
             the dialog as a lone host select with the Start button under it,
             and then the guest sentence and the whole "Archive lands on" field
             appeared and shoved the buttons down, under a cursor already on
             its way to them. */
          <SkeletonGroup label="Checking what is on this host">
            {/* "N guests on host will be backed up: a, b, c" wraps to two
                lines as often as not, so two bars, the second short. */}
            <SkeletonLine className="mt-3 w-full text-[12.5px]" />
            <SkeletonLine className="w-2/3 text-[12.5px]" />
            {/* The label and the select, spelled the way the real pair below
                is: an 11px caption, then inputCls (px-3 py-2, text-[13.5px],
                1px border) which is 16 + 2 + 13.5 * 1.45 = 38px. */}
            <SkeletonLine className="mt-4 w-32 text-[11px]" />
            <Skeleton className="h-[38px] w-full rounded-ctl" />
          </SkeletonGroup>
        ) : hostId != null && (
          <>
            {/* The scope, before the click, and now editable. "One vzdump over
                every guest on the chosen host" was only ever in this file's
                comments; the list is what stops "Run now" reading as an
                unqualified "backup" of something unspecified. */}
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
            {/* Verify is queued as its own job once the run has written the
                archives, so the backup's own result never depends on how the
                check goes. With Backup unticked there is no run to follow and
                Verify sweeps what is already on the host instead. */}
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
                            // sweep is about archives already written and does
                            // not care which guests are ticked.
                            // An empty EXPLICIT list only, see ScheduleForm: a
                            // host with no guests is already `blocked` above.
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
                      // sending `all` and a guest created between opening this
                      // dialog and the job running is still included.
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
    <Dialog title={'New scheduled backup job'} width={480} onClose={onClose}>
    {/* Same sentence as RunDialog, for the same reason: "backup" on its own
        reads as an unqualified backup of something unspecified, and an operator
        reasonably wondered whether these buttons were about Proxploy's own
        data. They are about the guests. No longer promises "every" one of
        them: the form below picks which. */}
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
 * Retention preview (Pro), plus the execution that acts on exactly what it
 * showed. Preview stays a dry run through and through: "Prune now" only
 * appears once a preview has actually run, and it fires POST /backups/prune
 * with the very same PruneParams the preview was computed from, not a
 * second, separately-typed form.
 */
// `pending` is drilled in beside `data` because `data` alone cannot tell the
// two apart: `stats.datastores` is an empty list both when a host really has no
// backup datastore and while GET /backups is still in flight, and this select
// had no third branch at all, so a cold page opened on an empty Datastore box.
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
  // The 422 ("at least one keep-* value is required") is a discovery
  // mechanism of last resort, not the first line of defense: catch it here,
  // against the params the preview itself ran with, not the (possibly since
  // edited) live input fields.
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

          {/* "Preview retention" had no pending state of any kind: the button
              did not change, no row appeared, and the only evidence the click
              had landed was the table showing up a second or two later. This
              is the one surface on the page where somebody is waiting on a
              thing they explicitly asked for.

              `params != null` guards it because usePrunePreview is disabled
              until a preview has been requested, and a disabled query sits at
              pending for ever, which would put this placeholder under the form
              from the moment the page opened. */}
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
  // Whether there is anywhere to back UP to is a question about storage, not
  // about archives. `stats.datastores` (below) is the `backups` cache grouped
  // by store, so it only knows the stores that already hold something.
  const storage = useStorage()
  const backupStores = (storage.data ?? []).filter((s) => s.content.includes('backup'))
  const verify = useVerifyBackup()
  const testRestore = useTestRestore()
  // Which datastores Proxmox Backup Server owns. An archive on one of those is
  // checked properly, on a schedule, against stored digests; our own check
  // reads the whole thing back over the network and knows less, so it is not
  // offered there. Per archive, not per install: PBS for the important guests
  // and an NFS share for the rest is an ordinary layout.
  const pbsStores = new Set((storage.data ?? [])
    .filter((s) => s.type === 'pbs').map((s) => s.storage))
  const pbsOwned = (b: BackupRow) => b.storage != null && pbsStores.has(b.storage)
  // services/backupjobs.py::sync_backups is the only genuinely granular
  // progress in the product (per-host, not a fixed handful of steps), and
  // this stale banner is the one place `backup.sync` is ever displayed:
  // GET /backups enqueues it fire-and-forget and never returns its id.
  const syncJob = useRunningJobOfKind('backup.sync', Boolean(data?.stale))
  const [running, setRunning] = useState(false)
  const [restoring, setRestoring] = useState<BackupRow | null>(null)
  const [connecting, setConnecting] = useState(false)
  const [scheduling, setScheduling] = useState(false)
  // Read once on mount, so "Remind me later" lasts exactly as long as this
  // visit: leaving the page unmounts the route and coming back asks again,
  // while "I understand" is written to localStorage and never asks.
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
  // DELETE /backups/{id} moved from backups.pbs to backups.retention in the
  // final Phase 6 review (BLOCKING 3/item 6), gate the button on the same
  // key the route now checks, or a tenant with backups.pbs but not
  // backups.retention sees a Delete button that just 403s.
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
              /* This used to read off `biggest`, so a datastore that accepts
                 backups but holds none yet, exactly what you have the moment
                 you attach one, was reported as no datastore at all while the
                 Storage page listed it. "Nothing in it yet" is the Datastore
                 used card's line to say, not this one's. It also called every
                 store a Proxmox Backup Server; an NFS export with the backup
                 content type is not one. */
              : storage.isError
                ? 'Could not read the storage list'
                : backupStores.length === 0
                  ? 'No backup datastore found. Add a Proxmox Backup Server, an NFS or '
                    + 'SMB share, or a folder on the node, with Backups ticked as its content.'
                  /* Which stores they are is the Storage page's job; this says
                     whether there is somewhere to write and what is already
                     there. The archive COUNT, because the card below this one
                     reports the size and nothing else reports the count. */
                  : `${backupStores.length} datastore`
                    + `${backupStores.length === 1 ? ' accepts' : 's accept'} backups · `
                    + (stats?.total
                        ? `${stats.total} archive${stats.total === 1 ? '' : 's'}`
                        : 'no archives yet')}
            {data?.stale && (
              <span className="ml-2 inline-flex items-center gap-1.5 text-amber">
                {/* Only when the sync job has actually reported something:
                    before its first host completes, progress_pct is null and
                    a ring here would show a zero that reads as stalled. */}
                {syncJob.data?.progress_pct != null && (
                  <Loading value={syncJob.data.progress_pct} label="Syncing backups" size={16} />
                )}
                <span>· refreshing from Proxmox…</span>
              </span>
            )}
          </div>
        </div>
        <div className="flex gap-2">
          {/* doc 10's "PBS datastore connect", widened: connecting PBS is
              just attaching a storage of type `pbs`, and the same form the
              Storage page uses already attaches any of them, so this says
              what it does rather than naming one plugin. Shown always, not
              only when empty, a second datastore is a normal thing to add.
              Server enforces `storage.manage`; the form carries its own
              LockVeil, so no gate is needed on the trigger. */}
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
        {/* Two different questions, and the label says which one is answered.
            "Verified" is the better one and needs Proxmox Backup Server: it is
            the only thing that writes verify_state, so on a plain NFS or
            directory store this card read "unknown" for ever while backups ran
            perfectly. What is knowable there is whether the RUNS finished,
            which says an archive was written, never that it restores. */}
        {stats?.success_rate_30d != null ? (
          <StatCard label="Verified · 30d" loading={isPending}
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

      {/* The jobs, above the archives they produce. This page listed only what
          had already run, so the one place a scheduled backup could be edited,
          paused, fired by hand or removed was a card in Settings that a person
          looking at their backups had no reason to open. Same card, filtered to
          the kind this page owns. */}
      <div className="mt-4">
        <SchedulesCard only={['backup.run']} title="Scheduled jobs" canAdd={false} />
      </div>

      <div className={`${card} mt-4`}>
        <h2 className="mb-3 font-display text-[16px] font-semibold">Recent backups</h2>
        {isPending ? (
          /* Ordered BEFORE the empty check on purpose. `data?.backups.length
             ?? 0` is 0 while the first fetch is still in flight, so without
             this the page opened on "No backups yet" -- the UI stating you
             have nothing when it has not looked yet. Same failure
             components/QueryState.tsx exists to prevent on the routes that
             use it; this page predates that wrapper. */
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
                    {b.guest_name ?? 'unknown'}
                    <span className="ml-2 text-[11px] text-text-3">
                      {b.guest_type?.toUpperCase()} {b.guest_vmid}
                    </span>
                  </td>
                  <td className="py-2.5 text-text-2">{b.host_name ?? 'unknown'}</td>
                  <td className="py-2.5 text-text-2">{fmtWhen(b.taken_at)}</td>
                  <td className="py-2.5 font-mono text-text-2">{fmtBytes(b.size_bytes)}</td>
                  <td className={`py-2.5 text-[12px] ${
                    b.verify_state === 'ok' ? 'text-green'
                      : b.verify_state === 'failed' ? 'text-red' : 'text-text-3'}`}>
                    {b.verify_state === 'ok' ? 'verified'
                      : b.verify_state === 'failed' ? 'failed' : 'unverified'}
                  </td>
                  <td className="py-2.5 text-right">
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
                    <Button variant="ghost" size="sm" className="ml-2"
                            disabled={testRestore.isPending || pbsOwned(b)}
                            title={pbsOwned(b)
                              ? 'Proxmox Backup Server checks this archive itself'
                              : 'Restore into a throwaway id, then delete it'}
                            onClick={() => testRestore.mutate({ id: b.id }, {
                              onError: (e) => notify.error(
                                apiErrorDetail(e, 'Could not start that test restore, try again.')),
                            })}>
                      Test restore
                    </Button>
                    {/* size="sm", not the px/py/text className these carried:
                        those collide with the component's default size and lose
                        in the emitted CSS, so these two rendered full height
                        next to the two sm buttons above them. */}
                    <Button variant="ghost" size="sm" className="ml-2"
                            disabled={restoreDenied}
                            title={restoreDenied ? 'Not included in your plan' : undefined}
                            onClick={() => setRestoring(b)}>
                      Restore
                    </Button>
                    <Button variant="danger" size="sm" className="ml-2"
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

// shellRoute from ./shell, never ../router (cluster.tsx:273-277).
export const backupsRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/backups',
  component: BackupsPage,
})
