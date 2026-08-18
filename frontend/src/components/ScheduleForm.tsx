import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError, apiErrorDetail } from '../api/client'
import { SCHEDULABLE } from '../api/schedules'
import { fmtCron } from '../lib/format'
import { notify } from '../lib/notify'
import { Button } from './ui/button'

const input = 'w-full rounded-ctl border border-line bg-panel-2 px-3 py-2 text-[13px] text-text'
const label = 'mb-1 block text-[11.5px] uppercase tracking-wide text-text-3'

type Named = { id: number; name: string }

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

/** Create one schedule. `jobKind` pins the kind and hides the picker, which is
 *  how the Backups page's "New job" reuses this without a second component. */
export function ScheduleForm({ jobKind, onSaved }:
  { jobKind?: string; onSaved: () => void }) {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [kind, setKind] = useState(jobKind ?? 'backup.run')
  const [every, setEvery] = useState<Every>('day')
  const [time, setTime] = useState('02:00')      // native <input type="time">
  const [dow, setDow] = useState('1')            // cron day-of-week, 0 = Sunday
  const [rawCron, setRawCron] = useState('0 2 * * *')
  // The browser's zone, not UTC: someone typing "2am" means 2am where they
  // live, and the backend stores an IANA name so DST is handled for them.
  const [tz, setTz] = useState(BROWSER_TZ)
  const [targetId, setTargetId] = useState('')

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

  const create = useMutation({
    mutationFn: () => {
      const params: Record<string, number> = {}
      if (needs === 'host' && effectiveTargetId) params.host_id = Number(effectiveTargetId)
      if (needs === 'app' && effectiveTargetId) params.app_id = Number(effectiveTargetId)
      return api('/schedules', {
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
                  onChange={(e) => { setKind(e.target.value); setTargetId('') }}>
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
                  onChange={(e) => setTargetId(e.target.value)}>
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
        {/* input + datalist, not a select: the list is a suggestion, so any
            valid IANA name can still be typed (the backend validates it and
            422s with zoneinfo's own message), and a resolved zone missing from
            the list is shown rather than silently dropped. */}
        <input id="sc-tz" className={`${input} font-mono`} value={tz} required
               list={TIMEZONES.length ? 'sc-tz-list' : undefined}
               onChange={(e) => setTz(e.target.value)} />
        {TIMEZONES.length > 0 && (
          <datalist id="sc-tz-list">
            {TIMEZONES.map((z) => <option key={z} value={z} />)}
          </datalist>
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
                disabled={create.isPending || (needs != null && !effectiveTargetId)}>
          Create schedule
        </Button>
      </div>
    </form>
  )
}
