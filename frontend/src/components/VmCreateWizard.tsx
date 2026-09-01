import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import { poolsFrom, type StorageRow } from './install/pools'
import type { JobRow } from '../api/jobs'
import { JobLog } from './JobLog'
import { KVGrid } from './KVGrid'
import { inputCls } from './LoginForm'
import { StepRail, type RailStep } from './StepRail'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'
import { isoName } from './VmCdromDialog'
import { Loading } from './ui/loading'

// Deliberately local row types: the wizard reads endpoints directly, so the
// Storage and Network pages stay free to reshape their own hook signatures.
type HostRow = { id: number; name: string; cluster_name?: string | null }
type NodeRow = { host_id: number; node: string }
type ContentRow = { volid: string; size: number }
type BridgesOut = { nodes: { host_id: number; node: string; interfaces: { iface: string; type: string }[] }[] }

const STEPS = ['Target', 'OS', 'System', 'Disks', 'CPU & Memory', 'Network', 'Confirm'] as const

// PVE `ostype` values for qemu. The full list is longer; these four cover
// everything Proxploy's own install paths produce plus an honest escape hatch.
const OS_TYPES = [
  ['l26', 'Linux (kernel 2.6-6.x)'],
  ['win11', 'Windows 11 / Server 2022'],
  ['win10', 'Windows 10 / Server 2016-2019'],
  ['other', 'Other / unspecified'],
] as const

const MACHINE_TYPES = [
  ['i440fx', 'Default (i440fx)'],
  ['q35', 'q35'],
] as const

const BIOS_TYPES = [
  ['seabios', 'SeaBIOS'],
  ['ovmf', 'OVMF (UEFI)'],
] as const

const VGA_TYPES = [
  ['', 'Default'],
  ['std', 'Standard VGA'],
  ['qxl', 'SPICE'],
  ['vmware', 'VMware compatible'],
  ['virtio', 'VirtIO GPU'],
  ['serial0', 'Serial terminal 0'],
  ['none', 'None'],
] as const

const SCSIHW_TYPES = [
  ['virtio-scsi-single', 'VirtIO SCSI single'],
  ['virtio-scsi-pci', 'VirtIO SCSI'],
  ['lsi', 'LSI 53C895A'],
  ['lsi53c810', 'LSI 53C810'],
  ['megasas', 'MegaRAID SAS 8708EM2'],
  ['pvscsi', 'VMware PVSCSI'],
] as const

const TPM_VERSIONS = [
  ['v2.0', 'v2.0'],
  ['v1.2', 'v1.2'],
] as const

const AGENT_TYPES = [
  ['virtio', 'VirtIO'],
  ['isa', 'ISA'],
] as const

const DISK_BUSES = [
  ['scsi', 'SCSI'],
  ['virtio', 'VirtIO block'],
  ['sata', 'SATA'],
  ['ide', 'IDE'],
] as const

const DISK_CACHES = [
  ['', 'Default (no cache)'],
  ['none', 'No cache'],
  ['writethrough', 'Write through'],
  ['writeback', 'Write back'],
  ['unsafe', 'Write back (unsafe)'],
  ['directsync', 'Direct sync'],
] as const

const DISK_AIOS = [
  ['', 'Default'],
  ['native', 'Native'],
  ['threads', 'Threads'],
  ['io_uring', 'io_uring'],
] as const

const NET_MODELS = [
  ['virtio', 'VirtIO (paravirtualized)'],
  ['e1000', 'Intel E1000'],
  ['rtl8139', 'Realtek RTL8139'],
  ['vmxnet3', 'VMware vmxnet3'],
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

function Check({ id, label, checked, onChange }: {
  id: string; label: string; checked: boolean; onChange: (v: boolean) => void
}) {
  return (
    <div className="flex items-center gap-2">
      <input id={id} type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <label htmlFor={id} className="text-[13px] text-text-2">{label}</label>
    </div>
  )
}

function Advanced({ children }: { children: React.ReactNode }) {
  return (
    <details className="rounded-ctl border border-line-soft">
      <summary className="cursor-pointer px-3 py-2 text-[12.5px] text-text-2">Advanced</summary>
      <div className="grid grid-cols-2 gap-3 border-t border-line-soft p-3">{children}</div>
    </details>
  )
}

const numOrNull = (v: string) => (v === '' ? null : Number(v))

export function VmCreateWizard({ onClose }: { onClose: (vmid?: number) => void }) {
  const qc = useQueryClient()
  const [step, setStep] = useState(0)
  const [jobId, setJobId] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [f, setF] = useState({
    host_id: '', node: '', name: '',
    pool: '', tags: '', onboot: false,
    startup_order: '', startup_up: '', startup_down: '', start: false,

    iso_storage: '', iso: '', virtio_storage: '', virtio_iso: '', ostype: 'l26',

    machine: 'i440fx' as 'i440fx' | 'q35',
    bios: 'seabios' as 'seabios' | 'ovmf',
    vga: '' as '' | 'std' | 'qxl' | 'vmware' | 'virtio' | 'serial0' | 'none',
    scsihw: 'virtio-scsi-single',
    efi_disk: false, efi_storage: '', efi_pre_enrolled_keys: true,
    tpm: false, tpm_storage: '', tpm_version: 'v2.0' as 'v2.0' | 'v1.2',
    agent: false, agent_type: 'virtio' as 'virtio' | 'isa', agent_fstrim: false,

    disk_bus: 'scsi' as 'scsi' | 'virtio' | 'sata' | 'ide',
    disk_gb: '32', storage: '',
    disk_cache: '', disk_aio: '',
    disk_discard: false, disk_iothread: false, disk_ssd: false,
    disk_backup: true, disk_replicate: true,
    disk_mbps_rd: '', disk_mbps_wr: '', disk_iops_rd: '', disk_iops_wr: '',

    sockets: '1', cores: '2', cpu_type: '', cpu_flags: '',
    vcpus: '', cpulimit: '', cpuunits: '', numa: false,

    memory_mb: '2048', ballooning: true, balloon_mb: '', shares: '',

    net: true, bridge: '', vlan_tag: '',
    net_model: 'virtio' as 'virtio' | 'e1000' | 'rtl8139' | 'vmxnet3',
    net_macaddr: '', net_mtu: '', net_queues: '', net_rate: '',
    net_firewall: false, net_link_down: false,
  })
  const set = <K extends keyof typeof f>(k: K, v: typeof f[K]) => setF((s) => ({ ...s, [k]: v }))
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
  const virtioIsos = useQuery({
    queryKey: ['storage', hostId, f.virtio_storage, f.node, 'iso'],
    enabled: hostId > 0 && f.virtio_storage !== '' && f.node !== '',
    queryFn: () => api<ContentRow[]>(
      `/storage/${hostId}/${f.virtio_storage}/content?node=${encodeURIComponent(f.node)}&content=iso`),
  })
  const bridges = useQuery({
    queryKey: ['network', 'bridges', hostId],
    enabled: hostId > 0,
    queryFn: () => api<BridgesOut>(`/network/bridges?host=${hostId}`),
  })

  const nodeOpts = (nodes.data ?? []).filter((n) => n.host_id === hostId)

  // A host is almost always a single PVE node; pre-fill it when there is one
  // answer and only a real cluster host (nodeOpts.length > 1) gets the select.
  useEffect(() => {
    if (nodeOpts.length === 1 && f.node !== nodeOpts[0].node) set('node', nodeOpts[0].node)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hostId, nodeOpts.length, nodeOpts[0]?.node])
  useEffect(() => {
    if (f.bios === 'ovmf' && !f.efi_disk) set('efi_disk', true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [f.bios])
  // poolsFrom, not a local filter: /storage drops host_id from its dedupe key,
  // so a host_id+node filter here collapses shared datastores across a cluster.
  // pools.ts already fixes this; sharing the function stops the two drifting.
  const selectedHost = (hosts.data ?? []).find((h) => h.id === hostId)
  const storeOpts = (kind: string) =>
    poolsFrom(storages.data, hostId, f.node, selectedHost?.cluster_name, kind)
  const bridgeOpts = (bridges.data?.nodes ?? [])
    .filter((n) => n.node === f.node)
    .flatMap((n) => n.interfaces)
    .filter((i) => i.type === 'bridge')

  const create = useMutation<{ job: JobRow; vmid: number }, ApiError, void>({
    mutationFn: () => api<{ job: JobRow; vmid: number }>('/vms', {
      method: 'POST',
      body: JSON.stringify({
        host_id: hostId, node: f.node || null, name: f.name.trim(), vmid: null,
        pool: f.pool, tags: f.tags, onboot: f.onboot,
        startup_order: f.startup_order, startup_up: f.startup_up, startup_down: f.startup_down,
        start: f.start,

        iso: f.iso || null, virtio_iso: f.virtio_iso, ostype: f.ostype,

        machine: f.machine, bios: f.bios, vga: f.vga, scsihw: f.scsihw,
        efi_disk: f.efi_disk, efi_storage: f.efi_storage,
        efi_pre_enrolled_keys: f.efi_pre_enrolled_keys,
        tpm: f.tpm, tpm_storage: f.tpm_storage, tpm_version: f.tpm_version,
        agent: f.agent, agent_type: f.agent_type, agent_fstrim: f.agent_fstrim,

        disk_bus: f.disk_bus, disk_gb: Number(f.disk_gb), storage: f.storage,
        disk_cache: f.disk_cache, disk_aio: f.disk_aio,
        disk_discard: f.disk_discard, disk_iothread: f.disk_iothread,
        disk_ssd: f.disk_bus === 'virtio' ? false : f.disk_ssd,
        disk_backup: f.disk_backup, disk_replicate: f.disk_replicate,
        disk_mbps_rd: numOrNull(f.disk_mbps_rd), disk_mbps_wr: numOrNull(f.disk_mbps_wr),
        disk_iops_rd: numOrNull(f.disk_iops_rd), disk_iops_wr: numOrNull(f.disk_iops_wr),

        sockets: Number(f.sockets), cores: Number(f.cores),
        cpu_type: f.cpu_type, cpu_flags: f.cpu_flags,
        vcpus: numOrNull(f.vcpus), cpulimit: numOrNull(f.cpulimit), cpuunits: numOrNull(f.cpuunits),
        numa: f.numa,

        memory_mb: Number(f.memory_mb), ballooning: f.ballooning,
        balloon_mb: numOrNull(f.balloon_mb), shares: numOrNull(f.shares),

        net: f.net, bridge: f.bridge || 'vmbr0', vlan_tag: numOrNull(f.vlan_tag),
        net_model: f.net_model, net_macaddr: f.net_macaddr,
        net_mtu: numOrNull(f.net_mtu), net_queues: numOrNull(f.net_queues), net_rate: numOrNull(f.net_rate),
        net_firewall: f.net_firewall, net_link_down: f.net_link_down,
      }),
    }),
    // useLifecycle's rule: the job is only *accepted* here, so refetching ['vms']
    // would show nothing new. ['jobs'] is what actually moved.
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
    },
  })

  const efiTpmOk = (!f.efi_disk || f.efi_storage !== '') && (!f.tpm || f.tpm_storage !== '')
  const ok = [
    hostId > 0 && f.node !== '' && f.name.trim() !== '',
    f.iso_storage !== '' && f.iso !== '',
    efiTpmOk,
    Number(f.disk_gb) > 0 && f.storage !== '',
    Number(f.sockets) > 0 && Number(f.cores) > 0 && Number(f.memory_mb) > 0,
    f.net ? f.bridge !== '' : true,
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

  const confirmRows: [string, React.ReactNode][] = [
    ['Name', f.name],
    ['Host / node', `${(hosts.data ?? []).find((h) => h.id === hostId)?.name ?? 'unknown'} / ${f.node}`],
    ['OS type', f.ostype],
    ['ISO', f.iso],
    ['Cores', f.cores],
    ['Memory', `${f.memory_mb} MB`],
    ['Disk', `${f.disk_gb} GB on ${f.storage}`],
    ['Network', f.net ? (f.vlan_tag ? `${f.bridge} tag ${f.vlan_tag}` : f.bridge) : 'None'],
  ]
  if (f.pool) confirmRows.push(['Resource pool', f.pool])
  if (f.tags) confirmRows.push(['Tags', f.tags])
  if (f.onboot) confirmRows.push(['Start at boot', 'Yes'])
  if (f.startup_order || f.startup_up || f.startup_down) {
    confirmRows.push(['Startup order',
      [f.startup_order, f.startup_up, f.startup_down].filter(Boolean).join(' / ')])
  }
  if (f.start) confirmRows.push(['Start after creation', 'Yes'])
  if (f.virtio_iso) confirmRows.push(['VirtIO drivers ISO', f.virtio_iso])
  if (f.machine === 'q35') confirmRows.push(['Machine', 'q35'])
  if (f.bios === 'ovmf') confirmRows.push(['BIOS', 'OVMF (UEFI)'])
  if (f.vga) confirmRows.push(['Graphic card', f.vga])
  if (f.scsihw !== 'virtio-scsi-single') confirmRows.push(['SCSI controller', f.scsihw])
  if (f.efi_disk) {
    confirmRows.push(['EFI disk',
      `${f.efi_storage}${f.efi_pre_enrolled_keys ? '' : ', no pre-enrolled keys'}`])
  }
  if (f.tpm) confirmRows.push(['TPM', `${f.tpm_storage} (${f.tpm_version})`])
  if (f.agent) confirmRows.push(['QEMU guest agent', `${f.agent_type}${f.agent_fstrim ? ', fstrim' : ''}`])
  if (f.disk_bus !== 'scsi') confirmRows.push(['Disk bus', f.disk_bus])
  if (f.disk_cache) confirmRows.push(['Disk cache', f.disk_cache])
  if (f.disk_aio) confirmRows.push(['Async IO', f.disk_aio])
  if (f.disk_discard) confirmRows.push(['Discard', 'On'])
  if (f.disk_iothread) confirmRows.push(['IO thread', 'On'])
  if (f.disk_ssd) confirmRows.push(['SSD emulation', 'On'])
  if (!f.disk_backup) confirmRows.push(['Backup', 'Off'])
  if (!f.disk_replicate) confirmRows.push(['Replication', 'Skipped'])
  if (f.disk_mbps_rd) confirmRows.push(['Read limit', `${f.disk_mbps_rd} MB/s`])
  if (f.disk_mbps_wr) confirmRows.push(['Write limit', `${f.disk_mbps_wr} MB/s`])
  if (f.disk_iops_rd) confirmRows.push(['Read limit (IOPS)', f.disk_iops_rd])
  if (f.disk_iops_wr) confirmRows.push(['Write limit (IOPS)', f.disk_iops_wr])
  if (f.sockets !== '1') confirmRows.push(['Sockets', f.sockets])
  if (f.cpu_type) confirmRows.push(['CPU type', f.cpu_type])
  if (f.cpu_flags) confirmRows.push(['Extra CPU flags', f.cpu_flags])
  if (f.vcpus) confirmRows.push(['VCPUs', f.vcpus])
  if (f.cpulimit) confirmRows.push(['CPU limit', f.cpulimit])
  if (f.cpuunits) confirmRows.push(['CPU units', f.cpuunits])
  if (f.numa) confirmRows.push(['NUMA', 'On'])
  if (!f.ballooning) confirmRows.push(['Ballooning', 'Off'])
  if (f.balloon_mb) confirmRows.push(['Minimum memory', `${f.balloon_mb} MB`])
  if (f.shares) confirmRows.push(['Shares', f.shares])
  if (f.net_model !== 'virtio') confirmRows.push(['NIC model', f.net_model])
  if (f.net_macaddr) confirmRows.push(['MAC address', f.net_macaddr])
  if (f.net_mtu) confirmRows.push(['MTU', f.net_mtu])
  if (f.net_queues) confirmRows.push(['Multiqueue', f.net_queues])
  if (f.net_rate) confirmRows.push(['Rate limit', `${f.net_rate} MB/s`])
  if (f.net_firewall) confirmRows.push(['Firewall', 'On'])
  if (f.net_link_down) confirmRows.push(['Disconnect', 'On'])

  return (
    <Dialog
      title="New VM"
      width={760}
      onClose={onClose}
    >
    <div className="mt-2 flex flex-col gap-4 md:flex-row">
      <aside className="shrink-0 border-b border-line pb-4 md:w-[160px] md:border-b-0 md:border-r md:pb-0 md:pr-4">
        <StepRail steps={railSteps} view={step} onSelect={setStep} />
      </aside>
      <div className="min-w-0 flex-1">
    {jobId ? (
      <div>
        <JobLog jobId={jobId} />
        <Button className="mt-3" variant="ghost"
                onClick={() => onClose(create.data?.vmid)}>Close</Button>
      </div>
    ) : (
      <>
        {step === 0 && (
          <div className="space-y-3">
            <Field id="vm-host" label="Host">
              {/* `isLoading`, never `isPending`: enabled-gated queries sit at
                  isPending forever while disabled, so it would label a waiting
                  select "loading" indefinitely. isLoading = isPending &&
                  isFetching, true only while a request is out. */}
              <select id="vm-host" className={inputCls} value={f.host_id}
                disabled={hosts.isError || hosts.isLoading}
                onChange={(e) => {
                  set('host_id', e.target.value); set('node', '')
                  set('iso_storage', ''); set('iso', '')
                  set('virtio_storage', ''); set('virtio_iso', '')
                  set('storage', ''); set('efi_storage', ''); set('tpm_storage', '')
                  set('bridge', '')
                }}>
                {hosts.isError
                  ? <option value="">Could not load hosts</option>
                  : hosts.isLoading
                    ? <option value="">Loading hosts…</option>
                    : <option value="">Select a host…</option>}
                {(hosts.data ?? []).map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
              </select>
            </Field>
            {nodeOpts.length !== 1 && (
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
            )}
            <Field id="vm-name" label="VM name">
              <input id="vm-name" className={inputCls} placeholder="ubuntu-lab"
                value={f.name} onChange={(e) => set('name', e.target.value)} />
            </Field>
            <Field id="vm-pool" label="Resource pool">
              <input id="vm-pool" className={inputCls} placeholder="none"
                value={f.pool} onChange={(e) => set('pool', e.target.value)} />
            </Field>
            <Field id="vm-tags" label="Tags">
              <input id="vm-tags" className={inputCls} placeholder="none"
                value={f.tags} onChange={(e) => set('tags', e.target.value)} />
            </Field>
            <Check id="vm-onboot" label="Start at boot" checked={f.onboot}
              onChange={(v) => set('onboot', v)} />
            <Check id="vm-start" label="Start after creation" checked={f.start}
              onChange={(v) => set('start', v)} />
            <Advanced>
              <Field id="vm-startup-order" label="Startup order">
                <input id="vm-startup-order" type="number" min="0" className={inputCls}
                  value={f.startup_order} onChange={(e) => set('startup_order', e.target.value)} />
              </Field>
              <Field id="vm-startup-up" label="Startup delay (seconds)">
                <input id="vm-startup-up" type="number" min="0" className={inputCls}
                  value={f.startup_up} onChange={(e) => set('startup_up', e.target.value)} />
              </Field>
              <Field id="vm-startup-down" label="Shutdown delay (seconds)">
                <input id="vm-startup-down" type="number" min="0" className={inputCls}
                  value={f.startup_down} onChange={(e) => set('startup_down', e.target.value)} />
              </Field>
            </Advanced>
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
                {storeOpts('iso').map((s) => <option key={s} value={s}>{s}</option>)}
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
                {(isos.data ?? []).map((v) => (
                  <option key={v.volid} value={v.volid}>{isoName(v.volid)}</option>
                ))}
              </select>
            </Field>
            <Field id="vm-ostype" label="OS type">
              <select id="vm-ostype" className={inputCls} value={f.ostype}
                onChange={(e) => set('ostype', e.target.value)}>
                {OS_TYPES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
              </select>
            </Field>
            <Field id="vm-virtio-store" label="VirtIO drivers storage">
              <select id="vm-virtio-store" className={inputCls} value={f.virtio_storage}
                disabled={storages.isError || storages.isLoading}
                onChange={(e) => { set('virtio_storage', e.target.value); set('virtio_iso', '') }}>
                {storages.isError
                  ? <option value="">Could not load datastores</option>
                  : storages.isLoading
                    ? <option value="">Loading datastores…</option>
                    : <option value="">None</option>}
                {storeOpts('iso').map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </Field>
            {f.virtio_storage !== '' && (
              <Field id="vm-virtio-iso" label="VirtIO drivers ISO">
                <select id="vm-virtio-iso" className={inputCls} value={f.virtio_iso}
                  disabled={virtioIsos.isError || virtioIsos.isLoading}
                  onChange={(e) => set('virtio_iso', e.target.value)}>
                  {virtioIsos.isError
                    ? <option value="">Could not load ISOs</option>
                    : virtioIsos.isLoading
                      ? <option value="">Loading ISOs…</option>
                      : <option value="">Select an ISO…</option>}
                  {(virtioIsos.data ?? []).map((v) => (
                    <option key={v.volid} value={v.volid}>{isoName(v.volid)}</option>
                  ))}
                </select>
              </Field>
            )}
            <p className="text-[12px] text-text-3">
              No ISOs listed? Upload one on the Storage page, this list is the
              datastore's own <span className="font-mono">content=iso</span> listing.
            </p>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <Field id="vm-machine" label="Machine">
                <select id="vm-machine" className={inputCls} value={f.machine}
                  onChange={(e) => set('machine', e.target.value as 'i440fx' | 'q35')}>
                  {MACHINE_TYPES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                </select>
              </Field>
              <Field id="vm-bios" label="BIOS">
                <select id="vm-bios" className={inputCls} value={f.bios}
                  onChange={(e) => set('bios', e.target.value as 'seabios' | 'ovmf')}>
                  {BIOS_TYPES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                </select>
              </Field>
              <Field id="vm-vga" label="Graphic card">
                <select id="vm-vga" className={inputCls} value={f.vga}
                  onChange={(e) => set('vga', e.target.value as typeof f.vga)}>
                  {VGA_TYPES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                </select>
              </Field>
              <Field id="vm-scsihw" label="SCSI controller">
                <select id="vm-scsihw" className={inputCls} value={f.scsihw}
                  onChange={(e) => set('scsihw', e.target.value)}>
                  {SCSIHW_TYPES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                </select>
              </Field>
            </div>
            <Check id="vm-efi-disk" label="Add EFI disk" checked={f.efi_disk}
              onChange={(v) => set('efi_disk', v)} />
            {f.efi_disk && (
              <div className="grid grid-cols-2 gap-3">
                <Field id="vm-efi-storage" label="EFI storage">
                  <select id="vm-efi-storage" className={inputCls} value={f.efi_storage}
                    disabled={storages.isError || storages.isLoading}
                    onChange={(e) => set('efi_storage', e.target.value)}>
                    {storages.isError
                      ? <option value="">Could not load datastores</option>
                      : storages.isLoading
                        ? <option value="">Loading datastores…</option>
                        : <option value="">Select a datastore…</option>}
                    {storeOpts('images').map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </Field>
                <div className="flex items-end pb-2">
                  <Check id="vm-efi-keys" label="Pre-enrolled keys" checked={f.efi_pre_enrolled_keys}
                    onChange={(v) => set('efi_pre_enrolled_keys', v)} />
                </div>
              </div>
            )}
            <Check id="vm-tpm" label="Add TPM" checked={f.tpm}
              onChange={(v) => set('tpm', v)} />
            {f.tpm && (
              <div className="grid grid-cols-2 gap-3">
                <Field id="vm-tpm-storage" label="TPM storage">
                  <select id="vm-tpm-storage" className={inputCls} value={f.tpm_storage}
                    disabled={storages.isError || storages.isLoading}
                    onChange={(e) => set('tpm_storage', e.target.value)}>
                    {storages.isError
                      ? <option value="">Could not load datastores</option>
                      : storages.isLoading
                        ? <option value="">Loading datastores…</option>
                        : <option value="">Select a datastore…</option>}
                    {storeOpts('images').map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </Field>
                <Field id="vm-tpm-version" label="TPM version">
                  <select id="vm-tpm-version" className={inputCls} value={f.tpm_version}
                    onChange={(e) => set('tpm_version', e.target.value as 'v2.0' | 'v1.2')}>
                    {TPM_VERSIONS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                  </select>
                </Field>
              </div>
            )}
            <Check id="vm-agent" label="QEMU guest agent" checked={f.agent}
              onChange={(v) => set('agent', v)} />
            {f.agent && (
              <div className="grid grid-cols-2 gap-3">
                <Field id="vm-agent-type" label="Agent type">
                  <select id="vm-agent-type" className={inputCls} value={f.agent_type}
                    onChange={(e) => set('agent_type', e.target.value as 'virtio' | 'isa')}>
                    {AGENT_TYPES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                  </select>
                </Field>
                <div className="flex items-end pb-2">
                  <Check id="vm-agent-fstrim" label="Run fstrim after a clone or move" checked={f.agent_fstrim}
                    onChange={(v) => set('agent_fstrim', v)} />
                </div>
              </div>
            )}
          </div>
        )}

        {step === 3 && (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <Field id="vm-bus" label="Bus">
                <select id="vm-bus" className={inputCls} value={f.disk_bus}
                  onChange={(e) => set('disk_bus', e.target.value as 'scsi' | 'virtio' | 'sata' | 'ide')}>
                  {DISK_BUSES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                </select>
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
                  {storeOpts('images').map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </Field>
              <Field id="vm-cache" label="Cache">
                <select id="vm-cache" className={inputCls} value={f.disk_cache}
                  onChange={(e) => set('disk_cache', e.target.value)}>
                  {DISK_CACHES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                </select>
              </Field>
            </div>
            <Check id="vm-discard" label="Discard" checked={f.disk_discard}
              onChange={(v) => set('disk_discard', v)} />
            <Check id="vm-iothread" label="IO thread" checked={f.disk_iothread}
              onChange={(v) => set('disk_iothread', v)} />
            {f.disk_bus !== 'virtio' && (
              <Check id="vm-ssd" label="SSD emulation" checked={f.disk_ssd}
                onChange={(v) => set('disk_ssd', v)} />
            )}
            <Check id="vm-backup" label="Backup" checked={f.disk_backup}
              onChange={(v) => set('disk_backup', v)} />
            <Advanced>
              <Field id="vm-aio" label="Async IO">
                <select id="vm-aio" className={inputCls} value={f.disk_aio}
                  onChange={(e) => set('disk_aio', e.target.value)}>
                  {DISK_AIOS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                </select>
              </Field>
              <div className="flex items-end pb-2">
                <Check id="vm-skip-replicate" label="Skip replication" checked={!f.disk_replicate}
                  onChange={(v) => set('disk_replicate', !v)} />
              </div>
              <Field id="vm-mbps-rd" label="Read limit (MB/s)">
                <input id="vm-mbps-rd" type="number" min="0" step="any" className={inputCls}
                  placeholder="unlimited" value={f.disk_mbps_rd}
                  onChange={(e) => set('disk_mbps_rd', e.target.value)} />
              </Field>
              <Field id="vm-mbps-wr" label="Write limit (MB/s)">
                <input id="vm-mbps-wr" type="number" min="0" step="any" className={inputCls}
                  placeholder="unlimited" value={f.disk_mbps_wr}
                  onChange={(e) => set('disk_mbps_wr', e.target.value)} />
              </Field>
              <Field id="vm-iops-rd" label="Read limit (IOPS)">
                <input id="vm-iops-rd" type="number" min="0" className={inputCls}
                  placeholder="unlimited" value={f.disk_iops_rd}
                  onChange={(e) => set('disk_iops_rd', e.target.value)} />
              </Field>
              <Field id="vm-iops-wr" label="Write limit (IOPS)">
                <input id="vm-iops-wr" type="number" min="0" className={inputCls}
                  placeholder="unlimited" value={f.disk_iops_wr}
                  onChange={(e) => set('disk_iops_wr', e.target.value)} />
              </Field>
            </Advanced>
          </div>
        )}

        {step === 4 && (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <Field id="vm-sockets" label="Sockets">
                <input id="vm-sockets" type="number" min="1" max="4" className={inputCls}
                  value={f.sockets} onChange={(e) => set('sockets', e.target.value)} />
              </Field>
              <Field id="vm-cores" label="Cores">
                <input id="vm-cores" type="number" min="1" className={inputCls}
                  value={f.cores} onChange={(e) => set('cores', e.target.value)} />
              </Field>
              <Field id="vm-cputype" label="CPU type">
                <input id="vm-cputype" className={inputCls} placeholder="Default (kvm64)"
                  value={f.cpu_type} onChange={(e) => set('cpu_type', e.target.value)} />
              </Field>
              <Field id="vm-mem" label="Memory (MB)">
                <input id="vm-mem" type="number" min="16" step="128" className={inputCls}
                  value={f.memory_mb} onChange={(e) => set('memory_mb', e.target.value)} />
              </Field>
              <Field id="vm-balloon-mb" label="Minimum memory (MB)">
                <input id="vm-balloon-mb" type="number" min="0" step="128" className={inputCls}
                  placeholder="same as memory" value={f.balloon_mb}
                  onChange={(e) => set('balloon_mb', e.target.value)} />
              </Field>
            </div>
            <Check id="vm-numa" label="Enable NUMA" checked={f.numa}
              onChange={(v) => set('numa', v)} />
            <Check id="vm-ballooning" label="Ballooning device" checked={f.ballooning}
              onChange={(v) => set('ballooning', v)} />
            <Advanced>
              <Field id="vm-cpuflags" label="Extra CPU flags">
                <input id="vm-cpuflags" className={inputCls} placeholder="e.g. +aes;+pdpe1gb"
                  value={f.cpu_flags} onChange={(e) => set('cpu_flags', e.target.value)} />
              </Field>
              <Field id="vm-vcpus" label="VCPUs">
                <input id="vm-vcpus" type="number" min="1" className={inputCls}
                  placeholder="sockets × cores" value={f.vcpus}
                  onChange={(e) => set('vcpus', e.target.value)} />
              </Field>
              <Field id="vm-cpulimit" label="CPU limit">
                <input id="vm-cpulimit" type="number" min="0" step="any" className={inputCls}
                  placeholder="unlimited" value={f.cpulimit}
                  onChange={(e) => set('cpulimit', e.target.value)} />
              </Field>
              <Field id="vm-cpuunits" label="CPU units">
                <input id="vm-cpuunits" type="number" min="1" max="262144" className={inputCls}
                  placeholder="default" value={f.cpuunits}
                  onChange={(e) => set('cpuunits', e.target.value)} />
              </Field>
              <Field id="vm-shares" label="Shares">
                <input id="vm-shares" type="number" min="0" max="50000" className={inputCls}
                  placeholder="default" value={f.shares}
                  onChange={(e) => set('shares', e.target.value)} />
              </Field>
            </Advanced>
          </div>
        )}

        {step === 5 && (
          <div className="space-y-3">
            <Check id="vm-no-net" label="No network device" checked={!f.net}
              onChange={(v) => set('net', !v)} />
            {f.net && (
              <>
                <div className="grid grid-cols-2 gap-3">
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
                  <Field id="vm-net-model" label="Model">
                    <select id="vm-net-model" className={inputCls} value={f.net_model}
                      onChange={(e) => set('net_model', e.target.value as typeof f.net_model)}>
                      {NET_MODELS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                    </select>
                  </Field>
                </div>
                <Check id="vm-net-firewall" label="Firewall" checked={f.net_firewall}
                  onChange={(v) => set('net_firewall', v)} />
                <Advanced>
                  <Field id="vm-net-mac" label="MAC address">
                    <input id="vm-net-mac" className={inputCls} placeholder="auto"
                      value={f.net_macaddr} onChange={(e) => set('net_macaddr', e.target.value)} />
                  </Field>
                  <Field id="vm-net-mtu" label="MTU">
                    <input id="vm-net-mtu" type="number" min="576" max="65520" className={inputCls}
                      placeholder="default" value={f.net_mtu}
                      onChange={(e) => set('net_mtu', e.target.value)} />
                  </Field>
                  <Field id="vm-net-queues" label="Multiqueue">
                    <input id="vm-net-queues" type="number" min="1" max="64" className={inputCls}
                      placeholder="off" value={f.net_queues}
                      onChange={(e) => set('net_queues', e.target.value)} />
                  </Field>
                  <Field id="vm-net-rate" label="Rate limit (MB/s)">
                    <input id="vm-net-rate" type="number" min="0" step="any" className={inputCls}
                      placeholder="unlimited" value={f.net_rate}
                      onChange={(e) => set('net_rate', e.target.value)} />
                  </Field>
                  <div className="flex items-end pb-2">
                    <Check id="vm-net-down" label="Disconnect" checked={f.net_link_down}
                      onChange={(v) => set('net_link_down', v)} />
                  </div>
                </Advanced>
              </>
            )}
          </div>
        )}

        {step === 6 && (
          <div className="rounded-ctl border border-line-soft bg-elev p-3">
            <KVGrid items={confirmRows} />
          </div>
        )}

        {error && <p className="mt-3 text-[12.5px] text-red">{error}</p>}

        <div className="mt-4 flex items-center justify-end gap-2">
          {/* No progress callbacks in the create path, so the ring, never a number. */}
          {create.isPending && <Loading label="Creating the VM" size={18} className="mr-auto" />}
          <Button variant="ghost" onClick={() => onClose()}>Cancel</Button>
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
