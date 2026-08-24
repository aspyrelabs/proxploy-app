import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError, apiErrorDetail } from '../api/client'
import { SCHEDULABLE } from '../api/schedules'
import type { ScheduleRow } from '../api/schedules'
import { fmtCron } from '../lib/format'
import { notify } from '../lib/notify'
import { Button } from './ui/button'
import { GuestPicker, useBackupStores, useHostGuests } from './BackupPickers'

const input = 'w-full rounded-ctl border border-line bg-panel-2 px-3 py-2 text-[13px] text-text'
const label = 'mb-1 block text-[11.5px] uppercase tracking-wide text-text-3'

type Named = { id: number; name: string; cluster_name?: string | null }

/** Every IANA zone the browser knows, no dependency and no bundled list to go
 *  stale: `Intl.supportedValuesOf` is the platform's own answer (418 zones on
 *  the Node this repo builds with). Guarded because it landed in Safari 15.4,
 *  and the fallback is exactly the free-text field this control replaced.
 *
 *  The resolved default is unioned in rather than assumed present: a browser
 *  can resolve to a legacy alias (`Asia/Calcutta`) while the list carries only
 *  the canonical name (`Asia/Kolkata`), and a value with no matching entry is
 *  how a picker silently loses the operator's own zone. */
const BROWSER_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
const TIMEZONES: string[] = typeof Intl.supportedValuesOf === 'function'
  ? [...new Set([...Intl.supportedValuesOf('timeZone'), BROWSER_TZ])].sort()
  : []

/** The presets, and the cron each one builds. `Schedule.cron` stays the stored
 *  format (jobs/scheduler.py parses nothing else), so these are a way of
 *  WRITING cron, never a second schedule format the backend would have to
 *  learn. "Custom" is the escape hatch for anything they do not cover, and
 *  fmtCron describes whichever of the two is in effect. */
type Every = 'hour' | 'day' | 'week' | 'custom'

/** The presets, read backwards, so editing a saved job opens on the control
 *  that WROTE its cron instead of dumping five fields on the operator. Only
 *  the three shapes the presets themselves emit are recognised; anything else
 *  is genuinely custom and is shown as the expression it is. */
function presetOf(cron: string): { every: Every; time: string; dow: string } {
  const f = cron.trim().split(/\s+/)
  const two = (n: string) => String(Number(n)).padStart(2, '0')
  const fallback = { every: 'custom' as Every, time: '02:00', dow: '1' }
  if (f.length !== 5 || f[2] !== '*' || f[3] !== '*') return fallback
  if (f[0] === '0' && f[1] === '*' && f[4] === '*') return { ...fallback, every: 'hour' }
  if (!/^\d{1,2}$/.test(f[0]) || !/^\d{1,2}$/.test(f[1])) return fallback
  const time = `${two(f[1])}:${two(f[0])}`
  if (f[4] === '*') return { every: 'day', time, dow: '1' }
  if (/^[0-6]$/.test(f[4])) return { every: 'week', time, dow: f[4] }
  return fallback
}

/** Create or edit one schedule. `jobKind` pins the kind and hides the picker,
 *  which is how the Backups page's "New job" reuses this without a second
 *  component; `existing` switches the same fields to a PATCH, so editing a job
 *  is the form that made it rather than a second, near-identical one. */
export function ScheduleForm({ jobKind, existing, onSaved }:
  { jobKind?: string; existing?: ScheduleRow; onSaved: () => void }) {
  const qc = useQueryClient()
  const preset = presetOf(existing?.cron ?? '0 2 * * *')
  const savedParams = (existing?.params ?? {}) as Record<string, unknown>
  const [name, setName] = useState(existing?.name ?? '')
  const [kind, setKind] = useState(existing?.job_kind ?? jobKind ?? 'backup.run')
  const [every, setEvery] = useState<Every>(preset.every)
  const [time, setTime] = useState(preset.time)  // native <input type="time">
  const [dow, setDow] = useState(preset.dow)     // cron day-of-week, 0 = Sunday
  const [rawCron, setRawCron] = useState(existing?.cron ?? '0 2 * * *')
  // The browser's zone, not UTC: someone typing "2am" means 2am where they
  // live, and the backend stores an IANA name so DST is handled for them.
  const [tz, setTz] = useState(existing?.timezone ?? BROWSER_TZ)
  const [targetId, setTargetId] = useState(
    String(savedParams.host_id ?? savedParams.app_id ?? ''))
  // Both only apply to backup.run. `store` empty means "the first eligible
  // one", `only` null means "every guest on the host, including any added
  // after this job is saved".
  const [store, setStore] = useState(String(savedParams.storage ?? ''))
  const [only, setOnly] = useState<Set<string> | null>(null)
  // Chains a check per archive after the run. Read back from the saved job the
  // same way `storage` is, so an edit does not silently turn it off.
  const [verifyAfter, setVerifyAfter] = useState(savedParams.verify === true)

  const spec = SCHEDULABLE.find((s) => s.kind === kind)
  const needs = spec?.needs ?? null

  // One derivation, used for the preview AND for the POST, so the sentence
  // shown can never describe a different schedule from the one saved.
  const [hh, mm] = time.split(':')
  // Hourly takes no control at all and fires on the hour: offering a time
  // picker whose hour half is discarded would show a field that does nothing.
  const cron = every === 'custom' ? rawCron
    : every === 'hour' ? '0 * * * *'
      : every === 'day' ? `${Number(mm)} ${Number(hh)} * * *`
        : `${Number(mm)} ${Number(hh)} * * ${dow}`

  const targets = useQuery({
    queryKey: needs === 'app' ? ['apps'] : ['hosts'],
    queryFn: () => api<Named[]>(needs === 'app' ? '/apps' : '/hosts'),
    enabled: needs != null,
  })
  // Mirrors RunDialog's hostId fallback: with exactly one candidate there is
  // nothing to ask, so don't leave "Select…" chosen and let the job KeyError
  // on host_id/app_id at fire time.
  const effectiveTargetId = targetId || (targets.data?.length === 1 ? String(targets.data[0].id) : '')

  // A scheduled backup used to send nothing but host_id, so it dumped every
  // guest on the node onto whichever datastore Proxmox felt like: the same two
  // unanswered questions the ad-hoc Run now dialog already answers, on the runs
  // nobody is watching. services/backupjobs.py::run_backup reads `vmids` and
  // `storage` out of params and always has, so this is the form catching up.
  const isBackup = kind === 'backup.run'
  const hostId = isBackup && effectiveTargetId ? Number(effectiveTargetId) : null
  const onHost = useHostGuests(hostId)
  // A saved job stores PVE vmids; the tick list is keyed on Proxploy row ids,
  // so the two are matched up here once the guest list has loaded. Null all the
  // way through means "everything", which is what an absent `vmids` meant when
  // the job was saved and must still mean after an edit.
  const savedVmids = Array.isArray(savedParams.vmids)
    ? (savedParams.vmids as number[]) : null
  const selected = only ?? (savedVmids
    ? new Set(onHost.guests.filter((g) => savedVmids.includes(g.vmid)).map((g) => g.key))
    : null)
  const chosen = selected ?? new Set(onHost.guests.map((g) => g.key))
  const { stores } = useBackupStores(
    hostId, targets.data?.find((h) => h.id === hostId)?.cluster_name)
  const target = stores.some((s) => s.storage === store) ? store : (stores[0]?.storage ?? '')

  const create = useMutation({
    mutationFn: () => {
      const params: Record<string, unknown> = {}
      if (needs === 'host' && effectiveTargetId) params.host_id = Number(effectiveTargetId)
      if (needs === 'app' && effectiveTargetId) params.app_id = Number(effectiveTargetId)
      if (isBackup) {
        if (target) params.storage = target
        // PVE vmids, not Proxploy row ids: params go straight to the handler,
        // which passes them to vzdump. Omitted when everything is ticked, so
        // the job keeps covering guests created after it was saved.
        if (chosen.size !== onHost.guests.length) {
          params.vmids = onHost.guests.filter((g) => chosen.has(g.key)).map((g) => g.vmid)
        }
        // Absent rather than false when off, so a saved job carries only the
        // keys that mean something.
        if (verifyAfter) params.verify = true
      }
      // PATCH sends the same body: every field on it is one this form owns, so
      // there is nothing to merge and nothing the edit could silently drop.
      // `enabled` is deliberately absent on an edit, it belongs to the row's
      // own Enable/Disable control.
      return existing
        ? api(`/schedules/${existing.id}`, {
          method: 'PATCH',
          body: JSON.stringify({ name, job_kind: kind, cron, timezone: tz, params }),
        })
        : api('/schedules', {
          method: 'POST',
          body: JSON.stringify({ name, job_kind: kind, cron, timezone: tz,
                                 params, enabled: true }),
        })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['schedules'] })
      onSaved()
    },
    // The backend's 422 carries the actual cron parser error ("Wrong number of
    // fields; got 4, expected 5"), which is far more useful than "invalid".
    // The entitlement 403's body has `error`, not `detail`; without this
    // branch it fell through to the generic "check the fields" message,
    // which is wrong advice for a plan limit.
    onError: (e) => {
      if (e instanceof ApiError && e.status === 403
          && (e.body as any)?.error === 'entitlement_required') {
        notify.error('Not included in your plan.')
        return
      }
      notify.error(
        apiErrorDetail(e, 'Could not create that schedule, check the fields and try again.'))
    },
  })

  return (
    <form className="grid grid-cols-1 gap-3 sm:grid-cols-2"
          onSubmit={(e) => { e.preventDefault(); create.mutate() }}>
      <div className="sm:col-span-2">
        <label className={label} htmlFor="sc-name">Name</label>
        <input id="sc-name" className={input} value={name} required
               onChange={(e) => setName(e.target.value)} />
      </div>

      {!jobKind && (
        <div>
          <label className={label} htmlFor="sc-kind">What to run</label>
          <select id="sc-kind" className={input} value={kind}
                  onChange={(e) => {
                    setKind(e.target.value); setTargetId(''); setOnly(null); setStore('')
                  }}>
            {SCHEDULABLE.map((s) =>
              <option key={s.kind} value={s.kind}>{s.label}</option>)}
          </select>
        </div>
      )}

      {needs && (
        <div>
          <label className={label} htmlFor="sc-target">
            {needs === 'app' ? 'App' : 'Host'}
          </label>
          {/* `isLoading` rather than `isPending`: the query is enabled-gated on
              `needs`, and a disabled query stays pending for ever. This block
              only renders when `needs` is set, so here the two agree, but the
              gated spelling is the one that stays correct if that changes. */}
          <select id="sc-target" className={input} value={effectiveTargetId}
                  disabled={targets.isError || targets.isLoading}
                  onChange={(e) => {
                    // A tick list and a datastore from the previous host mean
                    // nothing on this one.
                    setTargetId(e.target.value); setOnly(null); setStore('')
                  }}>
            {targets.isError
              ? <option value="">Could not load {needs === 'app' ? 'apps' : 'hosts'}</option>
              : targets.isLoading
                ? <option value="">Loading {needs === 'app' ? 'apps' : 'hosts'}…</option>
                : <option value="">Select…</option>}
            {(targets.data ?? []).map((t) =>
              <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </div>
      )}

      {isBackup && hostId != null && (
        <>
          <div className="sm:col-span-2">
            <GuestPicker guests={onHost.guests} selected={selected}
                         onChange={setOnly} idPrefix="sc-guest" />
          </div>
          <div className="sm:col-span-2">
            <label className={label} htmlFor="sc-store">Archive lands on</label>
            <select id="sc-store" className={input} value={target}
                    disabled={stores.length === 0}
                    onChange={(e) => setStore(e.target.value)}>
              {stores.length === 0
                ? <option value="">No storage on this host accepts backups</option>
                : stores.map((s) => (
                  <option key={s.storage} value={s.storage}>
                    {s.storage}{s.type ? ` (${s.type})` : ''}
                  </option>
                ))}
            </select>
          </div>
          <div className="sm:col-span-2">
            <label className="flex items-center gap-2 text-[12.5px] text-text-2">
              <input type="checkbox" checked={verifyAfter}
                     onChange={(e) => setVerifyAfter(e.target.checked)} />
              Check each archive afterwards
            </label>
          </div>
        </>
      )}

      <div>
        <label className={label} htmlFor="sc-every">How often</label>
        <select id="sc-every" className={input} value={every}
                onChange={(e) => setEvery(e.target.value as Every)}>
          <option value="hour">Every hour</option>
          <option value="day">Every day</option>
          <option value="week">Every week</option>
          <option value="custom">Custom cron</option>
        </select>
      </div>

      {every === 'custom' ? (
        <div>
          <label className={label} htmlFor="sc-cron">Cron (5 fields)</label>
          <input id="sc-cron" className={`${input} font-mono`} value={rawCron} required
                 onChange={(e) => setRawCron(e.target.value)} />
          <span className="mt-1 block text-[11px] text-text-3">
            min hour day-of-month month day-of-week
          </span>
        </div>
      ) : every !== 'hour' && (
        <div>
          {/* Native time input rather than two number fields: it already knows
              the operator's 12/24-hour convention and validates itself. Cron
              has minute resolution, so the seconds a time input can carry are
              never asked for. */}
          <label className={label} htmlFor="sc-time">At</label>
          <input id="sc-time" type="time" className={input} value={time} required
                 onChange={(e) => setTime(e.target.value || '00:00')} />
        </div>
      )}

      {every === 'week' && (
        <div>
          <label className={label} htmlFor="sc-dow">On</label>
          <select id="sc-dow" className={input} value={dow}
                  onChange={(e) => setDow(e.target.value)}>
            {['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
              .map((d, i) => <option key={d} value={i}>{d}</option>)}
          </select>
        </div>
      )}

      <div>
        <label className={label} htmlFor="sc-tz">Timezone</label>
        {/* A select, not the input+datalist this was: a datalist has no
            affordance at all, so the field sat next to two real dropdowns
            looking like a label that happened to say Asia/Calcutta, and the
            418 zones behind it were invisible. BROWSER_TZ is unioned into the
            list (see TIMEZONES) precisely so the resolved zone always has an
            entry to be selected. The free-text fallback stays for a browser
            with no supportedValuesOf, where there is no list to pick from. */}
        {TIMEZONES.length > 0 ? (
          <select id="sc-tz" className={`${input} font-mono`} value={tz} required
                  onChange={(e) => setTz(e.target.value)}>
            {TIMEZONES.map((z) => <option key={z} value={z}>{z}</option>)}
          </select>
        ) : (
          <input id="sc-tz" className={`${input} font-mono`} value={tz} required
                 onChange={(e) => setTz(e.target.value)} />
        )}
      </div>

      <div className="sm:col-span-2 rounded-ctl border border-line-soft bg-panel-2 px-3 py-2 text-[12.5px] text-text-2">
        {/* Read off `cron`, the exact string that gets posted, not off the
            preset controls: a custom expression is described by the same
            sentence a preset is, and neither can disagree with what fires. */}
        Runs <strong className="text-text">{fmtCron(cron)}</strong>, {tz} time.
        <span className="ml-2 font-mono text-[11.5px] text-text-3">{cron}</span>
      </div>

      <div className="sm:col-span-2">
        <Button type="submit"
                disabled={create.isPending || (needs != null && !effectiveTargetId)
                          // `only` null is "everything", which is still valid on
                          // a host with no guests yet; an EMPTY explicit list is
                          // the operator having cleared every tick.
                          || (selected != null && selected.size === 0)}>
          {existing ? 'Save changes' : 'Create schedule'}
        </Button>
      </div>
    </form>
  )
}
