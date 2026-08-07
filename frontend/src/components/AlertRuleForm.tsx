import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, ApiError } from '../api/client'
import { useAlertMetrics } from '../api/alerts'
import type { AppRow, VmRow } from '../api/hooks'
import { Button } from './ui/button'

const input = 'w-full rounded-ctl border border-line bg-panel-2 px-3 py-2 text-[13px] text-text'
const label = 'mb-1 block text-[11.5px] uppercase tracking-wide text-text-3'

type HostRow = { id: number; name: string }

/** Create one alert rule. The metric enum, and which target kinds each metric
 *  supports, come from GET /alert-rules/metrics; never a second hard-coded
 *  copy that can drift from services/alerts.py::METRIC_TARGETS. */
export function AlertRuleForm({ onSaved }: { onSaved: () => void }) {
  const qc = useQueryClient()
  const metrics = useAlertMetrics()
  const specs = metrics.data?.metrics ?? []

  const [name, setName] = useState('')
  const [metric, setMetric] = useState('cpu_pct')
  const [targetType, setTargetType] = useState('any')
  const [targetId, setTargetId] = useState('')
  const [operator, setOperator] = useState<'gt' | 'lt'>('gt')
  const [threshold, setThreshold] = useState('85')
  const [durationS, setDurationS] = useState('300')
  const [severity, setSeverity] = useState('warning')

  const spec = specs.find((s) => s.metric === metric)
  const needsThreshold = spec?.needs_threshold ?? true
  // 'any' only makes sense when more than one kind is on offer; a host-only
  // metric collapses to a host target rather than pretending otherwise.
  const targetKinds = spec?.targets ?? ['host', 'app', 'vm']
  const targetOptions = targetKinds.length > 1 ? ['any', ...targetKinds] : targetKinds

  const hosts = useQuery({
    queryKey: ['hosts'], queryFn: () => api<HostRow[]>('/hosts'),
    enabled: targetType === 'host',
  })
  // Same query keys cluster.tsx/store.tsx/vms.tsx already fetch under, so this
  // shares their cache instead of adding a second /apps or /vms request.
  const apps = useQuery({
    queryKey: ['apps', {}], queryFn: () => api<AppRow[]>('/apps'),
    enabled: targetType === 'app',
  })
  const vms = useQuery({
    queryKey: ['vms', {}], queryFn: () => api<VmRow[]>('/vms'),
    enabled: targetType === 'vm',
  })

  const create = useMutation({
    mutationFn: () => api('/alert-rules', {
      method: 'POST',
      body: JSON.stringify({
        name, metric,
        target_type: targetType,
        target_id: targetType === 'any' ? null : Number(targetId) || null,
        operator, threshold: needsThreshold ? Number(threshold) : 0,
        duration_s: Number(durationS) || 0, severity, channel_ids: [],
        enabled: true,
      }),
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['alert-rules'] })
      onSaved()
    },
    // The backend's 422s are the useful ones ("disk_pct can only target host"),
    // so surface the message rather than a generic failure.
    onError: (e) => toast.error(
      e instanceof ApiError && typeof (e.body as any)?.detail === 'string'
        ? (e.body as any).detail
        : 'Could not create that rule, check the fields and try again.'),
  })

  function pickMetric(next: string) {
    setMetric(next)
    const kinds = specs.find((s) => s.metric === next)?.targets ?? []
    // Reset a target the new metric cannot carry (disk_pct on a VM), or the
    // form would post a combination the backend correctly rejects.
    if (kinds.length === 1) {
      setTargetType(kinds[0])
    } else if (targetType !== 'any' && !kinds.includes(targetType)) {
      setTargetType('any')
    }
  }

  return (
    <form className="grid grid-cols-1 gap-3 sm:grid-cols-2"
          onSubmit={(e) => { e.preventDefault(); create.mutate() }}>
      <div className="sm:col-span-2">
        <label className={label} htmlFor="ar-name">Name</label>
        <input id="ar-name" className={input} value={name} required
               onChange={(e) => setName(e.target.value)} />
      </div>

      <div>
        <label className={label} htmlFor="ar-metric">Metric</label>
        <select id="ar-metric" className={input} value={metric}
                disabled={metrics.isError}
                onChange={(e) => pickMetric(e.target.value)}>
          {metrics.isError && <option value="">Could not load metrics</option>}
          {specs.map((s) => <option key={s.metric} value={s.metric}>{s.metric}</option>)}
        </select>
      </div>

      <div>
        <label className={label} htmlFor="ar-target">Target</label>
        <select id="ar-target" className={input} value={targetType}
                onChange={(e) => { setTargetType(e.target.value); setTargetId('') }}>
          {targetOptions.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>

      {targetType === 'host' && (
        <div>
          <label className={label} htmlFor="ar-host">Host</label>
          <select id="ar-host" className={input} value={targetId}
                  disabled={hosts.isError}
                  onChange={(e) => setTargetId(e.target.value)}>
            {hosts.isError
              ? <option value="">Could not load hosts</option>
              : <option value="">Select…</option>}
            {(hosts.data ?? []).map((h) =>
              <option key={h.id} value={h.id}>{h.name}</option>)}
          </select>
        </div>
      )}

      {targetType === 'app' && (
        <div>
          <label className={label} htmlFor="ar-app">App</label>
          <select id="ar-app" className={input} value={targetId}
                  disabled={apps.isError}
                  onChange={(e) => setTargetId(e.target.value)}>
            {apps.isError
              ? <option value="">Could not load apps</option>
              : <option value="">Select…</option>}
            {(apps.data ?? []).map((a) =>
              <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </div>
      )}

      {targetType === 'vm' && (
        <div>
          <label className={label} htmlFor="ar-vm">VM</label>
          <select id="ar-vm" className={input} value={targetId}
                  disabled={vms.isError}
                  onChange={(e) => setTargetId(e.target.value)}>
            {vms.isError
              ? <option value="">Could not load VMs</option>
              : <option value="">Select…</option>}
            {(vms.data ?? []).map((v) =>
              <option key={v.id} value={v.id}>{v.name}</option>)}
          </select>
        </div>
      )}

      {needsThreshold && (
        <>
          <div>
            <label className={label} htmlFor="ar-op">Condition</label>
            <select id="ar-op" className={input} value={operator}
                    onChange={(e) => setOperator(e.target.value as 'gt' | 'lt')}>
              <option value="gt">above</option>
              <option value="lt">below</option>
            </select>
          </div>
          <div>
            <label className={label} htmlFor="ar-threshold">Threshold</label>
            <input id="ar-threshold" className={input} type="number" step="any"
                   value={threshold} onChange={(e) => setThreshold(e.target.value)} />
          </div>
        </>
      )}

      <div>
        <label className={label} htmlFor="ar-duration">For at least (seconds)</label>
        <input id="ar-duration" className={input} type="number" min="0"
               value={durationS} onChange={(e) => setDurationS(e.target.value)} />
      </div>

      <div>
        <label className={label} htmlFor="ar-severity">Severity</label>
        <select id="ar-severity" className={input} value={severity}
                onChange={(e) => setSeverity(e.target.value)}>
          <option value="info">info</option>
          <option value="warning">warning</option>
          <option value="critical">critical</option>
        </select>
      </div>

      <div className="sm:col-span-2">
        <Button type="submit" disabled={create.isPending}>Create rule</Button>
        <span className="ml-3 text-[12px] text-text-3">
          Notifications go to every channel subscribed to <code>alert.fired</code>.
        </span>
      </div>
    </form>
  )
}
