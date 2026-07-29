import { useState } from 'react'
import { createRoute } from '@tanstack/react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { shellRoute } from './shell'
import { api } from '../api/client'
import { useEntitlements } from '../api/hooks'
import { HostForm } from '../components/HostForm'
import { Button } from '../components/ui/button'

export const settingsRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/settings',
  component: SettingsPage,
})

type HostRow = { id: number; name: string; address: string; status: string; pve_version: string | null }

function Card({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="rounded-card border border-line-soft bg-panel p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="font-display text-[15px] font-semibold">{title}</h2>{action}
      </div>
      {children}
    </section>
  )
}

function SettingsPage() {
  const { tier, grace } = useEntitlements()
  const qc = useQueryClient()
  const [adding, setAdding] = useState(false)
  const hosts = useQuery({ queryKey: ['hosts'], queryFn: () => api<HostRow[]>('/hosts') })

  return (
    <div className="max-w-3xl space-y-5">
      <h1 className="font-display text-[22px] font-semibold">Settings</h1>

      <Card title="Plan">
        <p className="text-[13.5px] text-text-2">
          <span className="font-mono text-amber">{tier === 'builtin' ? 'FREE' : tier.toUpperCase()}</span>
          {' — '}all features are enabled. Licensing is dormant; entering a license key
          activates against the Proxploy licensing service.
          {grace?.in_grace && <span className="text-amber"> License refresh failing — working offline until {grace.grace_until}.</span>}
        </p>
      </Card>

      <Card title="Hosts" action={<Button variant="ghost" onClick={() => setAdding(a => !a)}>{adding ? 'Close' : 'Add host'}</Button>}>
        <table className="w-full text-left text-[13px]">
          <thead><tr className="text-[10.5px] uppercase tracking-wide text-text-3">
            <th className="pb-2">Host</th><th>Address</th><th>PVE</th><th>Status</th></tr></thead>
          <tbody>
            {(hosts.data ?? []).map(h => (
              <tr key={h.id} className="border-t border-line-soft hover:bg-panel-2">
                <td className="py-2 font-mono">{h.name}</td>
                <td className="font-mono text-text-2">{h.address}</td>
                <td className="text-text-2">{h.pve_version ?? '—'}</td>
                <td><span className={h.status === 'connected' ? 'text-green' : 'text-red'}>{h.status}</span></td>
              </tr>
            ))}
            {!hosts.data?.length && <tr><td colSpan={4} className="py-4 text-text-3">No hosts yet.</td></tr>}
          </tbody>
        </table>
        {adding && <div className="mt-4 border-t border-line-soft pt-4">
          <HostForm onCreated={() => { setAdding(false); qc.invalidateQueries({ queryKey: ['hosts'] }) }} />
        </div>}
      </Card>

      <Card title="General">
        <p className="text-[12.5px] text-text-3">
          Scheduled auto-updates, notifications and catalog sync configuration arrive in
          Phases 3–7; this page grows with them.
        </p>
      </Card>
    </div>
  )
}
