import { useState } from 'react'
import { createRoute } from '@tanstack/react-router'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { shellRoute } from './shell'
import { api } from '../api/client'
import { useAckAlert, useAlertHistory, useAlertMetrics, useAlertRules, useFiringAlerts } from '../api/alerts'
import type { AlertRow, AlertRuleRow } from '../api/alerts'
import { useEntitlements } from '../api/hooks'
import { AlertRuleForm } from '../components/AlertRuleForm'
import { QueryState } from '../components/QueryState'
import { Button } from '../components/ui/button'
import { CardLoadingOverlay } from '../components/ui/card-loading-overlay'

const card = 'rounded-card border border-line-soft bg-panel p-5'
const th = 'text-[10.5px] uppercase tracking-wide text-text-3'

const SEV: Record<string, string> = {
  info: 'bg-blue-dim text-blue',
  warning: 'bg-amber-dim text-amber',
  critical: 'bg-red-dim text-red',
}

function ago(iso: string | null): string {
  if (!iso) return 'unknown'
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000))
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  return `${Math.round(s / 86400)}d ago`
}

function AlertRowView({ a, onAck, acking }:
  { a: AlertRow; onAck: (id: number) => void; acking: boolean }) {
  return (
    <tr className="border-t border-line-soft hover:bg-panel-2">
      <td className="py-2">
        <span className={`rounded-tile px-2 py-0.5 font-mono text-[10.5px] ${SEV[a.severity] ?? SEV.warning}`}>
          {a.severity}
        </span>
      </td>
      <td className="py-2 text-[13px] text-text">{a.message}</td>
      <td className="font-mono text-[12px] text-text-2">{a.target_label ?? 'unknown'}</td>
      <td className="font-mono text-[12px] text-text-3">{ago(a.fired_at)}</td>
      <td className="py-2 text-right">
        {a.acked_at
          ? <span className="text-[11.5px] text-text-3">
              acknowledged by {a.acked_by_email ?? 'someone'}
            </span>
          : <Button variant="ghost" className="px-2 py-1 text-[11px]"
                    disabled={acking} onClick={() => onAck(a.id)}>Ack</Button>}
      </td>
    </tr>
  )
}

export function AlertsPage() {
  const ent = useEntitlements()
  const qc = useQueryClient()
  const firing = useFiringAlerts()
  const [showResolved, setShowResolved] = useState(false)
  const history = useAlertHistory(50)
  const ack = useAckAlert()

  const rulesAllowed = ent.data != null && ent.has('alerts.rules')
  const rules = useAlertRules(rulesAllowed)
  // Warm the metrics-enum cache as soon as the page opens, not when the rule
  // form mounts, AlertRuleForm's metric <select> needs its options in place
  // before "New rule" can be clicked and immediately answered in a test (or
  // by an impatient user).
  useAlertMetrics(rulesAllowed)
  const [adding, setAdding] = useState(false)

  const toggleRule = useMutation({
    mutationFn: (r: AlertRuleRow) => api(`/alert-rules/${r.id}`, {
      method: 'PATCH', body: JSON.stringify({ enabled: !r.enabled }),
    }),
    onError: () => toast.error('Could not update that rule, try again.'),
    onSettled: () => qc.invalidateQueries({ queryKey: ['alert-rules'] }),
  })
  const removeRule = useMutation({
    mutationFn: (id: number) => api(`/alert-rules/${id}`, { method: 'DELETE' }),
    onError: () => toast.error('Could not remove that rule, try again.'),
    onSettled: () => qc.invalidateQueries({ queryKey: ['alert-rules'] }),
  })

  return (
    <div className="space-y-5">
      <h1 className="font-display text-[22px] font-semibold">Alerts</h1>

      <section className={card}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-display text-[15px] font-semibold">Firing</h2>
          <Button variant="ghost" onClick={() => setShowResolved((s) => !s)}>
            {showResolved ? 'Hide resolved' : 'Show resolved'}
          </Button>
        </div>
        <QueryState query={firing}
                    emptyTitle="Nothing is firing"
                    emptyNote="Rules are checked every poll cycle."
                    errorTitle="Alerts not readable"
                    errorNote="Proxploy could not reach the backend to check what is firing.">
          {(rows) => (
            <table className="w-full text-left">
              <thead><tr className={th}>
                <th className="pb-2">Severity</th><th>Alert</th><th>Target</th>
                <th>Since</th><th /></tr></thead>
              <tbody>
                {rows.map((a) => (
                  <AlertRowView key={a.id} a={a} acking={ack.isPending}
                                onAck={(id) => ack.mutate(id)} />
                ))}
              </tbody>
            </table>
          )}
        </QueryState>

        {showResolved && (
          <div className="mt-5 border-t border-line-soft pt-4">
            <h3 className="mb-2 text-[12px] uppercase tracking-wide text-text-3">
              Recently resolved
            </h3>
            <QueryState query={history}
                        empty={(rows) => rows.filter((a) => a.state === 'resolved').length === 0}
                        emptyTitle="No resolved alerts yet."
                        emptyNote=""
                        errorTitle="Alert history not readable"
                        errorNote="Proxploy could not reach the backend to check resolved alerts.">
              {(rows) => (
                <table className="w-full text-left">
                  <tbody>
                    {rows.filter((a) => a.state === 'resolved').map((a) => (
                      <tr key={a.id} className="border-t border-line-soft">
                        <td className="py-2 text-[13px] text-text-2">{a.message}</td>
                        <td className="font-mono text-[12px] text-text-3">
                          {ago(a.resolved_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </QueryState>
          </div>
        )}
      </section>

      {/* This card's own entitlement-gated first load: not yet known whether
          the plan includes alerts.rules, then the rules list's own first
          fetch. `isPending`, not `isFetching`, so it stays quiet on the
          invalidation refetches toggleRule/removeRule trigger below. */}
      <CardLoadingOverlay state={{ firstLoad: ent.isPending || (rulesAllowed && rules.isPending) }}>
      <section className={card}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-display text-[15px] font-semibold">Rules</h2>
          {rulesAllowed && (
            <Button variant="ghost" onClick={() => setAdding((a) => !a)}>
              {adding ? 'Close' : 'New rule'}
            </Button>
          )}
        </div>
        {ent.data != null && !rulesAllowed && (
          <p className="text-[12.5px] text-text-3">Not included in your plan.</p>
        )}
        {rulesAllowed && (
          <>
            <QueryState query={rules}
                        // The overlay above already veils the card for
                        // rules.isPending; suppress the inner placeholder so
                        // the two don't stack.
                        loading={<></>}
                        emptyTitle="No rules yet"
                        emptyNote="Add one to be told when a host runs hot."
                        errorTitle="Alert rules not readable"
                        errorNote="Proxploy could not reach the backend to list your rules.">
              {(rows) => (
                <table className="w-full text-left text-[13px]">
                  <thead><tr className={th}>
                    <th className="pb-2">Name</th><th>Condition</th><th>Target</th>
                    <th>Severity</th><th>State</th><th /></tr></thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.id} className="border-t border-line-soft hover:bg-panel-2">
                        <td className="py-2">{r.name}</td>
                        <td className="font-mono text-[12px] text-text-2">
                          {r.metric}
                          {r.metric.endsWith('_pct')
                            ? ` ${r.operator === 'gt' ? '>' : '<'} ${r.threshold}%`
                            : ''}
                          {r.duration_s ? ` for ${Math.round(r.duration_s / 60)}m` : ''}
                        </td>
                        <td className="font-mono text-[12px] text-text-3">
                          {r.target_type}{r.target_id != null ? ` ${r.target_id}` : ''}
                        </td>
                        <td>
                          <span className={`rounded-tile px-2 py-0.5 font-mono text-[10.5px] ${SEV[r.severity] ?? SEV.warning}`}>
                            {r.severity}
                          </span>
                        </td>
                        <td className={r.enabled ? 'text-green' : 'text-text-3'}>
                          {r.enabled ? 'enabled' : 'disabled'}
                        </td>
                        <td className="py-2 text-right">
                          <Button variant="ghost" className="px-2 py-1 text-[11px]"
                                  disabled={toggleRule.isPending}
                                  onClick={() => toggleRule.mutate(r)}>
                            {r.enabled ? 'Disable' : 'Enable'}
                          </Button>
                          <Button variant="danger" className="ml-2 px-2 py-1 text-[11px]"
                                  onClick={() => {
                                    if (window.confirm(`Remove alert rule "${r.name}"? Its fired alerts go with it.`)) {
                                      removeRule.mutate(r.id)
                                    }
                                  }}>Remove</Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </QueryState>
            {adding && (
              <div className="mt-4 border-t border-line-soft pt-4">
                <AlertRuleForm onSaved={() => setAdding(false)} />
              </div>
            )}
          </>
        )}
      </section>
      </CardLoadingOverlay>
    </div>
  )
}

export const alertsRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/alerts',
  component: AlertsPage,
})
