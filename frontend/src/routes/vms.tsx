import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createRoute, Link, Outlet, useNavigate, useParams } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { consoleWsUrl, useReconnectingTicket } from '../api/consoles'
import { api, ApiError } from '../api/client'
import type { VmRow } from '../api/hooks'
import { useEntitlements, useMetrics } from '../api/hooks'
import type { JobRow } from '../api/jobs'
import { VncConsole } from '../components/console/VncConsole'
import { CloneDialog } from '../components/CloneDialog'
import { ConfirmSelfDialog } from '../components/ConfirmSelfDialog'
import { EmptyState } from '../components/EmptyState'
import { JobLog } from '../components/JobLog'
import { KVGrid } from '../components/KVGrid'
import { LifecycleActions } from '../components/LifecycleActions'
import { QueryState } from '../components/QueryState'
import { SnapshotPanel } from '../components/SnapshotPanel'
import { Sparkline } from '../components/charts/Sparkline'
import { StatusPill } from '../components/StatusPill'
import { Button } from '../components/ui/button'
import { VmCreateWizard } from '../components/VmCreateWizard'
import { fmtBytes, fmtPct, fmtUptime } from '../lib/format'

const card = 'rounded-card border border-line-soft bg-panel p-5'

export function VmsPage() {
  const navigate = useNavigate()
  const ent = useEntitlements()
  const [creating, setCreating] = useState(false)
  const [cloning, setCloning] = useState<VmRow | null>(null)
  const vmsQuery = useQuery({
    queryKey: ['vms', {}],
    queryFn: () => api<VmRow[]>('/vms'),
    refetchInterval: 30_000,
  })
  const vms = vmsQuery.data
  const running = vms?.filter((v) => v.status === 'running').length ?? 0
  // ent.has() is false until /entitlements resolves, gate on ent.data != null
  // too, or every plan sees a dead "New VM" button for the whole first fetch.
  const createDenied = ent.data != null && !ent.has('vms.create')
  const cloneDenied = ent.data != null && !ent.has('vms.clone')
  return (
    <div>
      <div className="mb-5 flex items-center">
        <div>
          <h1 className="font-display text-[22px] font-semibold">Virtual Machines</h1>
          <div className="text-[12px] text-text-3">
            {vms ? `${vms.length} VMs · ${running} running` : '…'}
          </div>
        </div>
        <Button className="ml-auto" disabled={createDenied}
          title={createDenied ? 'Not included in your plan' : undefined}
          onClick={() => setCreating(true)}>
          New VM
        </Button>
      </div>
      <QueryState query={vmsQuery}
                  emptyTitle="No VMs discovered"
                  emptyNote="QEMU guests on connected hosts are mirrored here by the poller."
                  errorTitle="VMs not readable"
                  errorNote="Proxploy could not reach the backend to list your VMs.">
        {(rows) => (
          <div className={card}>
            <table className="w-full text-left text-[13px]">
              <thead>
                <tr className="text-[11px] uppercase text-text-3">
                  <th scope="col" className="pb-2 font-medium">Name</th>
                  <th scope="col" className="pb-2 font-medium">Node</th>
                  <th scope="col" className="pb-2 font-medium">vCPU / RAM</th>
                  <th scope="col" className="pb-2 font-medium">CPU</th>
                  <th scope="col" className="pb-2 font-medium">Status</th>
                  <th scope="col" className="pb-2 font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((v) => (
                  <tr
                    key={v.id}
                    className="cursor-pointer border-t border-line-soft hover:bg-panel-2"
                    onClick={() => navigate({ to: '/vms/$vmId' as never, params: { vmId: String(v.id) } as never })}
                  >
                    <td className="py-2.5 font-mono">{v.name}</td>
                    <td className="py-2.5 text-text-2">{v.host_name}</td>
                    <td className="py-2.5 font-mono text-text-2">
                      {v.cpu_cores ?? 'unknown'} / {fmtBytes(v.mem_bytes)}
                    </td>
                    <td className="py-2.5 font-mono text-text-2">{fmtPct(v.cpu_pct)}</td>
                    <td className="py-2.5"><StatusPill status={v.status} /></td>
                    <td className="py-2.5 flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                      <LifecycleActions target="vm" id={v.id} name={v.name} status={v.status} size="sm" />
                      <Button variant="ghost" className="px-2 py-1 text-[11px]"
                        onClick={() => navigate({ to: '/vms/$vmId/console' as never, params: { vmId: String(v.id) } as never })}>
                        Console
                      </Button>
                      {/* doc 06 §e rule 2: a table-cell button is a "small inline
                          action", so the Pro treatment here is disabled+tooltip,
                          not LockVeil, veiling a 60px cell blurs nothing legible,
                          and a disabled trigger makes a veil inside the dialog
                          unreachable dead code. */}
                      <Button variant="ghost" className="px-2 py-1 text-[11px]"
                        disabled={cloneDenied}
                        title={cloneDenied ? 'Cloning is a Pro feature' : undefined}
                        onClick={() => setCloning(v)}>
                        Clone
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </QueryState>
      {creating && <VmCreateWizard onClose={() => setCreating(false)} />}
      {cloning && <CloneDialog vm={cloning} onClose={() => setCloning(null)} />}
    </div>
  )
}

const TABS = [
  { path: '.', label: 'Overview' },
  { path: 'console', label: 'Console' },
  { path: 'snapshots', label: 'Snapshots' },
] as const

/**
 * DELETE /vms/{id}. The single most destructive route in the product: lives
 * only on the VM's own detail page, never as a list-row action. Typed
 * confirmation of the VM name is mandatory (ConfirmSelfDialog), a running
 * guest is refused up front (the button is disabled with the reason
 * visible) and the backend's own 409 detail is what shows if that state
 * changed underneath us anyway, never a generic failure toast.
 */
function DestroyVmButton({ vm }: { vm: VmRow }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const ent = useEntitlements()
  const [destroying, setDestroying] = useState(false)
  const [jobId, setJobId] = useState<number | null>(null)
  const denied = ent.data != null && !ent.has('vms.create')
  const running = vm.status === 'running'

  const destroy = useMutation<{ job: JobRow }, ApiError, string>({
    mutationFn: (confirm) => api<{ job: JobRow }>(`/vms/${vm.id}`, {
      method: 'DELETE',
      body: JSON.stringify({ confirm }),
    }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['cluster', 'activity'] })
      qc.invalidateQueries({ queryKey: ['vms'] })
    },
  })

  const submit = (typed: string) => {
    destroy.mutate(typed, {
      onSuccess: (r) => { setDestroying(false); setJobId(r.job.id) },
      onError: (e) => {
        const body = e instanceof ApiError ? (e.body as Record<string, unknown>) : null
        // guest_running/confirm_required races (the VM's state changed between
        // opening the dialog and confirming) get the backend's own sentence
        // verbatim; self_target is restated plainly rather than assuming its
        // wording, is_self() is always false today so the real string is
        // untested here.
        const msg = body?.error === 'self_target'
          ? 'Proxploy will not destroy the guest it is running inside.'
          : String(body?.detail ?? 'Could not destroy that VM, try again.')
        toast.error(msg)
      },
    })
  }

  return (
    <>
      <Button variant="danger" disabled={running || denied}
              title={running ? `Stop ${vm.name} before destroying it`
                     : denied ? 'Not included in your plan' : undefined}
              onClick={() => setDestroying(true)}>
        Destroy
      </Button>
      {destroying && (
        <ConfirmSelfDialog
          title="Destroy this VM"
          phrase={vm.name}
          detail={`Destroying ${vm.name} deletes the VM and every disk attached to it. ` +
                  'There is no undo and no automatic backup. Type the VM name to confirm.'}
          onCancel={() => setDestroying(false)}
          onConfirm={submit}
        />
      )}
      {jobId != null && (
        <Dialog title={<>Destroying <span className="font-mono">{vm.name}</span></>} width={480} onClose={() => navigate({ to: '/vms' as never })}>
        <div className="mt-4"><JobLog jobId={jobId} /></div>
        <Button className="mt-3" variant="ghost"
                onClick={() => navigate({ to: '/vms' as never })}>
          Close
        </Button>
        </Dialog>
      )}
    </>
  )
}

export function VmDetail() {
  const { vmId } = useParams({ strict: false }) as { vmId: string }
  const vmQuery = useQuery({
    queryKey: ['vms', Number(vmId)],
    queryFn: () => api<VmRow>(`/vms/${vmId}`),
    refetchInterval: 15_000,
  })
  return (
    <QueryState query={vmQuery} emptyTitle="" emptyNote="" empty={() => false}
                errorTitle="This VM could not be loaded"
                errorNote="Proxploy could not reach the backend, or the VM no longer exists.">
      {(vm) => (
        <div>
          <Link to={'/vms' as never} className="text-[12px] text-text-3 hover:text-text">← Virtual Machines</Link>
          <div className="mt-2 mb-4 flex items-center gap-4">
            <div>
              <h1 className="font-display text-[22px] font-semibold">{vm.name}</h1>
              <div className="font-mono text-[12px] text-text-3">
                VMID {vm.vmid} · {vm.host_name} · {vm.cpu_cores ?? '?'} vCPU / {fmtBytes(vm.mem_bytes)}
              </div>
            </div>
            <div className="ml-auto flex items-center gap-3">
              <LifecycleActions target="vm" id={vm.id} name={vm.name} status={vm.status} />
              <DestroyVmButton vm={vm} />
              <StatusPill status={vm.status} />
            </div>
          </div>
          <div className="mb-5 flex gap-1 border-b border-line-soft">
            {TABS.map((t) => (
              <Link
                key={t.path}
                to={t.path as never}
                from={'/vms/$vmId' as never}
                activeOptions={{ exact: t.path === '.' }}
                className="px-3 py-2 text-[13px] text-text-2 hover:text-text [&.active]:border-b-2 [&.active]:border-amber [&.active]:text-text"
              >
                {t.label}
              </Link>
            ))}
          </div>
          <Outlet />
        </div>
      )}
    </QueryState>
  )
}

export function VmOverview() {
  const { vmId } = useParams({ strict: false }) as { vmId: string }
  const id = Number(vmId)
  const { data: vm } = useQuery({ queryKey: ['vms', id], queryFn: () => api<VmRow>(`/vms/${id}`) })
  const cpu = useMetrics(`vm:${id}`, 'cpu_pct', 24)
  if (!vm) return null
  return (
    <div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className={card}>
          <h2 className="mb-2 text-[13px] uppercase text-text-3">CPU · 24h</h2>
          <Sparkline ts={cpu.data?.ts ?? []} values={cpu.data?.value ?? []} color="#F5B544" />
        </div>
        <div className={card}>
          <h2 className="mb-2 text-[13px] uppercase text-text-3">Status</h2>
          <StatusPill status={vm.status} />
          <div className="mt-2 font-mono text-[12px] text-text-2">up {fmtUptime(vm.uptime_s)}</div>
        </div>
        <div className={card}>
          <h2 className="mb-2 text-[13px] uppercase text-text-3">Resources</h2>
          <div className="font-mono text-[12px] text-text-2">
            {vm.cpu_cores ?? 'unknown'} vCPU · {fmtBytes(vm.mem_bytes)} RAM · {fmtBytes(vm.disk_bytes)} disk
          </div>
        </div>
      </div>
      <div className={`${card} mt-4`}>
        <KVGrid items={[
          ['VMID', vm.vmid],
          ['Node', vm.host_name],
          ['Disk', fmtBytes(vm.disk_bytes)],
          ['OS type', vm.os_type ?? 'unknown'],
          ['Synced', vm.synced_at ?? 'unknown'],
        ]} />
      </div>
    </div>
  )
}

// Route objects, imported by router.tsx (cluster.tsx precedent). shellRoute
// comes from ./shell, not ../router: importing router.tsx here would force
// its eager createRouter() to run mid-cycle when this file is the import
// entry point (e.g. in tests), before vmsRoute/vmDetailRoute exist.
import { shellRoute } from './shell'
import { Dialog } from '../components/ui/dialog'

export const vmsRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/vms',
  component: VmsPage,
})

export const vmDetailRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/vms/$vmId',
  component: VmDetail,
})

export const vmOverviewRoute = createRoute({
  getParentRoute: () => vmDetailRoute,
  path: '/',
  component: VmOverview,
})
function VmConsole() {
  const { vmId } = useParams({ strict: false }) as { vmId: string }
  const id = Number(vmId)
  const { ticket, failed, start, reconnect } = useReconnectingTicket('vm', id)
  useEffect(() => { start() }, [id])
  if (failed) {
    return <EmptyState title="Console connection failed"
      note="Gave up after repeated attempts. Reload the page to try again." />
  }
  if (!ticket.data) return <EmptyState title="Opening console…" note="" />
  // VncConsole has no onDrop today (Task 9 doesn't add one, noVNC's RFB
  // class exposes its own 'disconnect' event for this instead of a generic
  // prop); wire the same reconnect-with-cap behavior via that event. VNC has
  // no JSON control-frame channel (unlike Terminal), so there is no "fatal"
  // signal to short-circuit on here, every drop just counts against the cap.
  return <VncConsoleWithReconnect vmId={id} ticket={ticket.data.ticket} onNeedNewTicket={reconnect} />
}

function VncConsoleWithReconnect({ vmId, ticket, onNeedNewTicket }:
  { vmId: number; ticket: string; onNeedNewTicket: () => void }) {
  return (
    <VncConsole key={ticket} wsUrl={consoleWsUrl('vm', vmId, ticket)}
      onDisconnect={onNeedNewTicket} />
  )
}

export const vmConsoleRoute = createRoute({
  getParentRoute: () => vmDetailRoute, path: 'console', component: VmConsole,
})

function VmSnapshots() {
  const { vmId } = useParams({ strict: false }) as { vmId: string }
  const id = Number(vmId)
  const { data: vm } = useQuery({ queryKey: ['vms', id], queryFn: () => api<VmRow>(`/vms/${id}`) })
  // The tab renders inside VmDetail's Outlet, so the ['vms', id] row is already
  // warm; this read is a cache hit, not a second round trip.
  if (!vm) return null
  return <SnapshotPanel vmId={id} vmName={vm.name} />
}

export const vmSnapshotsRoute = createRoute({
  getParentRoute: () => vmDetailRoute, path: 'snapshots', component: VmSnapshots,
})
