import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, ApiError } from '../api/client'
import { SCHEDULABLE } from '../api/schedules'
import { Button } from './ui/button'

const input = 'w-full rounded-ctl border border-line bg-panel-2 px-3 py-2 text-[13px] text-text'
const label = 'mb-1 block text-[11.5px] uppercase tracking-wide text-text-3'

type Named = { id: number; name: string }

/** Create one schedule. `jobKind` pins the kind and hides the picker, which is
 *  how the Backups page's "New job" reuses this without a second component. */
export function ScheduleForm({ jobKind, onSaved }:
  { jobKind?: string; onSaved: () => void }) {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [kind, setKind] = useState(jobKind ?? 'backup.run')
  const [cron, setCron] = useState('0 2 * * *')
  // The browser's zone, not UTC: someone typing "2am" means 2am where they
  // live, and the backend stores an IANA name so DST is handled for them.
  const [tz, setTz] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC')
  const [targetId, setTargetId] = useState('')

  const spec = SCHEDULABLE.find((s) => s.kind === kind)
  const needs = spec?.needs ?? null

  const targets = useQuery({
    queryKey: needs === 'app' ? ['apps'] : ['hosts'],
    queryFn: () => api<Named[]>(needs === 'app' ? '/apps' : '/hosts'),
    enabled: needs != null,
  })

  const create = useMutation({
    mutationFn: () => {
      const params: Record<string, number> = {}
      if (needs === 'host' && targetId) params.host_id = Number(targetId)
      if (needs === 'app' && targetId) params.app_id = Number(targetId)
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
    onError: (e) => toast.error(
      e instanceof ApiError && typeof (e.body as any)?.detail === 'string'
        ? (e.body as any).detail
        : 'Could not create that schedule — check the fields and try again.'),
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
          <select id="sc-target" className={input} value={targetId}
                  onChange={(e) => setTargetId(e.target.value)}>
            <option value="">Select…</option>
            {(targets.data ?? []).map((t) =>
              <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </div>
      )}

      <div>
        <label className={label} htmlFor="sc-cron">Cron (5 fields)</label>
        <input id="sc-cron" className={`${input} font-mono`} value={cron} required
               onChange={(e) => setCron(e.target.value)} />
        <span className="mt-1 block text-[11px] text-text-3">
          min hour day-of-month month day-of-week — e.g. <code>0 2 * * *</code> is 02:00 daily
        </span>
      </div>

      <div>
        <label className={label} htmlFor="sc-tz">Timezone</label>
        <input id="sc-tz" className={`${input} font-mono`} value={tz} required
               onChange={(e) => setTz(e.target.value)} />
      </div>

      <div className="sm:col-span-2">
        <Button type="submit" disabled={create.isPending}>Create schedule</Button>
      </div>
    </form>
  )
}
