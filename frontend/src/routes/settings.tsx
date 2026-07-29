import { useState } from 'react'
import { createRoute } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { shellRoute } from './shell'
import { api } from '../api/client'
import { useEntitlements } from '../api/hooks'
import { ChannelForm } from '../components/ChannelForm'
import type { ChannelRow } from '../components/ChannelForm'
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

  const [addingChannel, setAddingChannel] = useState(false)
  const channels = useQuery({
    queryKey: ['notifications', 'channels'],
    queryFn: () => api<ChannelRow[]>('/notifications/channels'),
  })
  const testChannel = useMutation({
    mutationFn: (id: number) =>
      api<{ sent: boolean }>(`/notifications/channels/${id}/test`, { method: 'POST' }),
    onSuccess: (r) => toast[r.sent ? 'success' : 'error'](
      r.sent ? 'Test notification sent' : 'Channel unreachable'),
    onSettled: () => qc.invalidateQueries({ queryKey: ['notifications', 'channels'] }),
  })
  const deleteChannel = useMutation({
    mutationFn: (id: number) =>
      api(`/notifications/channels/${id}`, { method: 'DELETE' }),
    onSettled: () => qc.invalidateQueries({ queryKey: ['notifications', 'channels'] }),
  })

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

      <Card title="Notifications"
            action={<Button variant="ghost" onClick={() => setAddingChannel(a => !a)}>
              {addingChannel ? 'Close' : 'Add channel'}
            </Button>}>
        <table className="w-full text-left text-[13px]">
          <thead><tr className="text-[10.5px] uppercase tracking-wide text-text-3">
            <th className="pb-2">Name</th><th>Kind</th><th>Events</th><th>State</th><th /></tr></thead>
          <tbody>
            {(channels.data ?? []).map(ch => (
              <tr key={ch.id} className="border-t border-line-soft hover:bg-panel-2">
                <td className="py-2">{ch.name}</td>
                <td className="font-mono text-text-2">{ch.kind}</td>
                <td className="font-mono text-[11.5px] text-text-3">
                  {ch.events.length ? ch.events.join(', ') : 'all events'}
                </td>
                <td className={ch.enabled ? 'text-green' : 'text-text-3'}>
                  {ch.enabled ? 'enabled' : 'disabled'}
                </td>
                <td className="py-2 text-right">
                  <Button variant="ghost" className="px-2 py-1 text-[11px]"
                          onClick={() => testChannel.mutate(ch.id)}>Test</Button>
                  <Button variant="danger" className="ml-2 px-2 py-1 text-[11px]"
                          onClick={() => deleteChannel.mutate(ch.id)}>Remove</Button>
                </td>
              </tr>
            ))}
            {!channels.data?.length && (
              <tr><td colSpan={5} className="py-4 text-text-3">
                No channels yet. Add one to get told when a job fails.
              </td></tr>
            )}
          </tbody>
        </table>
        {addingChannel && <div className="mt-4 border-t border-line-soft pt-4">
          <ChannelForm onSaved={() => {
            setAddingChannel(false)
            qc.invalidateQueries({ queryKey: ['notifications', 'channels'] })
          }} />
        </div>}
      </Card>

      <Card title="General">
        <p className="text-[12.5px] text-text-3">
          Scheduled auto-updates and catalog sync configuration arrive in
          Phases 4–7; this page grows with them.
        </p>
      </Card>
    </div>
  )
}
