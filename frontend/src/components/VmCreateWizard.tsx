import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, ApiError } from '../api/client'
import type { JobRow } from '../api/jobs'
import { JobLog } from './JobLog'
import { KVGrid } from './KVGrid'
import { inputCls } from './LoginForm'
import { StepRail, type RailStep } from './StepRail'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'
import { Loading } from './ui/loading'

// Deliberately local, deliberately narrow row types: the wizard reads the
// endpoints Tasks 3, 6 and 11 built, not Tasks 12/14's page hooks, so the
// Storage and Network pages stay free to reshape their own hook signatures.
type HostRow = { id: number; name: string }
type NodeRow = { host_id: number; node: string }
type StorageRow = { host_id: number; node: string; storage: string; content: string[] }
type ContentRow = { volid: string; size: number }
type BridgesOut = { nodes: { host_id: number; node: string; interfaces: { iface: string; type: string }[] }[] }

const STEPS = ['Target', 'OS', 'Resources', 'Network', 'Confirm'] as const

// PVE `ostype` values for qemu. The full list is longer; these four cover
// everything Proxploy's own install paths produce plus an honest escape hatch.
const OS_TYPES = [
  ['l26', 'Linux (kernel 2.6-6.x)'],
  ['win11', 'Windows 11 / Server 2022'],
  ['win10', 'Windows 10 / Server 2016-2019'],
  ['other', 'Other / unspecified'],
] as const

const lbl = 'mb-1 block text-[11px] uppercase tracking-wide text-text-3'

function Field({ id, label, children }: { id: string; label: string; children: React.ReactNode }) {
  return (
    <div>
      <label htmlFor={id} className={lbl}>{label}</label>
      {children}
    </div>
  )
}

/**
 * Doc 06 §(a) row 42's "New VM". Mirrors routes/onboarding.tsx's wizard shape
 * on purpose, a step index, a StepRail down the side, `{step === N && (…)}`
 * blocks; rather than becoming a reusable <Wizard/>: there are exactly two
 * multi-step flows in this app and they share no fields, only the rail's
 * presentation (see StepRail.tsx), which they now both import.
 *
 * On submit it follows InstallDialog: fire the mutation, keep the job id, swap
 * the body for <JobLog/> + Close.
 */
export function VmCreateWizard({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const [step, setStep] = useState(0)
  const [jobId, setJobId] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [f, setF] = useState({
    host_id: '', node: '', name: '',
    iso_storage: '', iso: '', ostype: 'l26',
    cores: '2', memory_mb: '2048', disk_gb: '32', storage: '',
    bridge: '', vlan_tag: '',
  })
  const set = (k: keyof typeof f, v: string) => setF((s) => ({ ...s, [k]: v }))
  const hostId = Number(f.host_id) || 0

  const hosts = useQuery({ queryKey: ['hosts'], queryFn: () => api<HostRow[]>('/hosts') })
  const nodes = useQuery({ queryKey: ['cluster', 'nodes'], queryFn: () => api<NodeRow[]>('/cluster/nodes') })
  const storages = useQuery({ queryKey: ['storage'], queryFn: () => api<StorageRow[]>('/storage') })
  const isos = useQuery({
    queryKey: ['storage', hostId, f.iso_storage, f.node, 'iso'],
    enabled: hostId > 0 && f.iso_storage !== '' && f.node !== '',
    queryFn: () => api<ContentRow[]>(
      `/storage/${hostId}/${f.iso_storage}/content?node=${encodeURIComponent(f.node)}&content=iso`),
  })
  const bridges = useQuery({
    queryKey: ['network', 'bridges', hostId],
    enabled: hostId > 0,
    queryFn: () => api<BridgesOut>(`/network/bridges?host=${hostId}`),
  })

  const nodeOpts = (nodes.data ?? []).filter((n) => n.host_id === hostId)
  const storeOpts = (kind: string) => (storages.data ?? [])
    .filter((s) => s.host_id === hostId && s.node === f.node && (s.content ?? []).includes(kind))
  const bridgeOpts = (bridges.data?.nodes ?? [])
    .filter((n) => n.node === f.node)
    .flatMap((n) => n.interfaces)
    .filter((i) => i.type === 'bridge')

  const create = useMutation<{ job: JobRow }, ApiError, void>({
    mutationFn: () => api<{ job: JobRow }>('/vms', {
      method: 'POST',
      body: JSON.stringify({
        host_id: hostId, node: f.node, name: f.name.trim(), ostype: f.ostype,
        iso: f.iso, cores: Number(f.cores), memory_mb: Number(f.memory_mb),
        disk_gb: Number(f.disk_gb), storage: f.storage, bridge: f.bridge,
        vlan_tag: f.vlan_tag ? Number(f.vlan_tag) : null,
      }),
    }),
    // useLifecycle's rule: the job is only *accepted* here, so refetching ['vms']
    // would show nothing new. ['jobs'] + activity are what actually moved.
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['cluster', 'activity'] })
    },
  })

  const ok = [
    hostId > 0 && f.node !== '' && f.name.trim() !== '',
    f.iso_storage !== '' && f.iso !== '',
    Number(f.cores) > 0 && Number(f.memory_mb) > 0 && Number(f.disk_gb) > 0 && f.storage !== '',
    f.bridge !== '',
    true,
  ]

  // Back to any visited step is always allowed. Forward is only allowed up to
  // the first not-yet-valid step in between, the same gate Next already uses,
  // so the rail can never open a step Next would have refused to reach.
  const reachable = (i: number) => {
    if (i <= step) return true
    for (let j = step; j < i; j++) if (!ok[j]) return false
    return true
  }
  const railSteps: RailStep[] = STEPS.map((label, i) => ({
    label,
    status: i < step ? 'done' : i === step ? 'current' : 'todo',
    reachable: reachable(i),
  }))

  const submit = () => {
    setError('')
    create.mutate(undefined, {
      onSuccess: (r) => setJobId(r.job.id),
      onError: (e) => setError(
        e instanceof ApiError
          ? String((e.body as any)?.detail ?? (e.body as any)?.error ?? e.message)
          : 'Request failed'),
    })
  }

  return (
    <Dialog
      title="New VM"
      width={760}
      onClose={onClose}
    >
    <div className="flex flex-col gap-4 md:flex-row">
      <aside className="shrink-0 border-b border-line pb-4 md:w-[160px] md:border-b-0 md:border-r md:pb-0 md:pr-4">
        <StepRail steps={railSteps} view={step} onSelect={setStep} />
      </aside>
      <div className="min-w-0 flex-1">
    {jobId ? (
      <div>
        <JobLog jobId={jobId} />
        <Button className="mt-3" variant="ghost" onClick={onClose}>Close</Button>
      </div>
    ) : (
      <>
        {step === 0 && (
          <div className="space-y-3">
            <Field id="vm-host" label="Host">
              {/* `isLoading` throughout this wizard, never `isPending`: `isos`
                  and `bridges` are enabled-gated on a host (and a datastore)
                  being picked first, and a disabled query sits at isPending for
                  ever, so isPending would label a select that is waiting on the
                  step before it as "loading" and never stop. isLoading is
                  isPending && isFetching, so it is true only while a request is
                  actually out. */}
              <select id="vm-host" className={inputCls} value={f.host_id}
                disabled={hosts.isError || hosts.isLoading}
                onChange={(e) => { set('host_id', e.target.value); set('node', ''); set('iso_storage', ''); set('iso', ''); set('storage', ''); set('bridge', '') }}>
                {hosts.isError
                  ? <option value="">Could not load hosts</option>
                  : hosts.isLoading
                    ? <option value="">Loading hosts…</option>
                    : <option value="">Select a host…</option>}
                {(hosts.data ?? []).map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
              </select>
            </Field>
            <Field id="vm-node" label="Node">
              <select id="vm-node" className={inputCls} value={f.node}
                disabled={nodes.isError || nodes.isLoading}
                onChange={(e) => set('node', e.target.value)}>
                {nodes.isError
                  ? <option value="">Could not load nodes</option>
                  : nodes.isLoading
                    ? <option value="">Loading nodes…</option>
                    : <option value="">Select a node…</option>}
                {nodeOpts.map((n) => <option key={n.node} value={n.node}>{n.node}</option>)}
              </select>
            </Field>
            <Field id="vm-name" label="VM name">
              <input id="vm-name" className={inputCls} placeholder="ubuntu-lab"
                value={f.name} onChange={(e) => set('name', e.target.value)} />
            </Field>
          </div>
        )}

        {step === 1 && (
          <div className="space-y-3">
            <Field id="vm-isostore" label="ISO storage">
              <select id="vm-isostore" className={inputCls} value={f.iso_storage}
                disabled={storages.isError || storages.isLoading}
                onChange={(e) => { set('iso_storage', e.target.value); set('iso', '') }}>
                {storages.isError
                  ? <option value="">Could not load datastores</option>
                  : storages.isLoading
                    ? <option value="">Loading datastores…</option>
                    : <option value="">Select a datastore…</option>}
                {storeOpts('iso').map((s) => <option key={s.storage} value={s.storage}>{s.storage}</option>)}
              </select>
            </Field>
            <Field id="vm-iso" label="ISO image">
              <select id="vm-iso" className={inputCls} value={f.iso}
                disabled={isos.isError || isos.isLoading}
                onChange={(e) => set('iso', e.target.value)}>
                {isos.isError
                  ? <option value="">Could not load ISOs</option>
                  : isos.isLoading
                    ? <option value="">Loading ISOs…</option>
                    : <option value="">Select an ISO…</option>}
                {(isos.data ?? []).map((v) => <option key={v.volid} value={v.volid}>{v.volid}</option>)}
              </select>
            </Field>
            <Field id="vm-ostype" label="OS type">
              <select id="vm-ostype" className={inputCls} value={f.ostype}
                onChange={(e) => set('ostype', e.target.value)}>
                {OS_TYPES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
              </select>
            </Field>
            <p className="text-[12px] text-text-3">
              No ISOs listed? Upload one on the Storage page, this list is the
              datastore's own <span className="font-mono">content=iso</span> listing.
            </p>
          </div>
        )}

        {step === 2 && (
          <div className="grid grid-cols-2 gap-3">
            <Field id="vm-cores" label="Cores">
              <input id="vm-cores" type="number" min="1" className={inputCls}
                value={f.cores} onChange={(e) => set('cores', e.target.value)} />
            </Field>
            <Field id="vm-mem" label="Memory (MB)">
              <input id="vm-mem" type="number" min="128" step="128" className={inputCls}
                value={f.memory_mb} onChange={(e) => set('memory_mb', e.target.value)} />
            </Field>
            <Field id="vm-disk" label="Disk size (GB)">
              <input id="vm-disk" type="number" min="1" className={inputCls}
                value={f.disk_gb} onChange={(e) => set('disk_gb', e.target.value)} />
            </Field>
            <Field id="vm-storage" label="Target storage">
              <select id="vm-storage" className={inputCls} value={f.storage}
                disabled={storages.isError || storages.isLoading}
                onChange={(e) => set('storage', e.target.value)}>
                {storages.isError
                  ? <option value="">Could not load datastores</option>
                  : storages.isLoading
                    ? <option value="">Loading datastores…</option>
                    : <option value="">Select a datastore…</option>}
                {storeOpts('images').map((s) => <option key={s.storage} value={s.storage}>{s.storage}</option>)}
              </select>
            </Field>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-3">
            <Field id="vm-bridge" label="Bridge">
              <select id="vm-bridge" className={inputCls} value={f.bridge}
                disabled={bridges.isError || bridges.isLoading}
                onChange={(e) => set('bridge', e.target.value)}>
                {bridges.isError
                  ? <option value="">Could not load bridges</option>
                  : bridges.isLoading
                    ? <option value="">Loading bridges…</option>
                    : <option value="">Select a bridge…</option>}
                {bridgeOpts.map((i) => <option key={i.iface} value={i.iface}>{i.iface}</option>)}
              </select>
            </Field>
            <Field id="vm-vlan" label="VLAN tag (optional)">
              <input id="vm-vlan" type="number" min="1" max="4094" className={inputCls}
                placeholder="untagged" value={f.vlan_tag}
                onChange={(e) => set('vlan_tag', e.target.value)} />
            </Field>
          </div>
        )}

        {step === 4 && (
          <div className="rounded-ctl border border-line-soft bg-elev p-3">
            <KVGrid items={[
              ['Name', f.name],
              ['Host / node', `${(hosts.data ?? []).find((h) => h.id === hostId)?.name ?? 'unknown'} / ${f.node}`],
              ['OS type', f.ostype],
              ['ISO', f.iso],
              ['Cores', f.cores],
              ['Memory', `${f.memory_mb} MB`],
              ['Disk', `${f.disk_gb} GB on ${f.storage}`],
              ['Network', f.vlan_tag ? `${f.bridge} tag ${f.vlan_tag}` : f.bridge],
            ]} />
          </div>
        )}

        {error && <p className="mt-3 text-[12.5px] text-red">{error}</p>}

        <div className="mt-4 flex items-center justify-end gap-2">
          {/* Nothing in the VM-create path calls ctx.progress() (checked
              against backend/proxploy/services/), so starting the job is a
              wait with no honest figure to show: the ring, never a number. */}
          {create.isPending && <Loading label="Creating the VM" size={18} className="mr-auto" />}
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          {step > 0 && (
            <Button variant="ghost" onClick={() => setStep(step - 1)}>Back</Button>
          )}
          {step < STEPS.length - 1 ? (
            <Button disabled={!ok[step]} onClick={() => setStep(step + 1)}>Next</Button>
          ) : (
            <Button disabled={create.isPending} onClick={submit}>Create</Button>
          )}
        </div>
      </>
  )}
      </div>
    </div>
</Dialog>
  )
}
