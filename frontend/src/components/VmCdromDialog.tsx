import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { VmRow } from '../api/hooks'
import { errBody } from '../api/network'
import { poolsFrom, type StorageRow } from './install/pools'
import { inputCls } from './LoginForm'
import { notify } from '../lib/notify'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'
import { Loading } from './ui/loading'

export type CdromStatus = { key: string | null; volid: string | null; mounted: boolean }
type ContentRow = { volid: string; size: number }
type HostRow = { id: number; cluster_name?: string | null }

const smallLabel = 'mb-1 block text-[11px] uppercase tracking-wide text-text-3'

/** The filename half of a volid, e.g. "local:iso/debian-12.7.0-amd64.iso"
 *  becomes "debian-12.7.0-amd64.iso". The store and path prefix are already
 *  said elsewhere; the filename is the part worth reading at a glance. */
export function isoName(volid: string): string {
  const slash = volid.lastIndexOf('/')
  return slash === -1 ? volid : volid.slice(slash + 1)
}

/** What is mounted in a VM's CD-ROM drive. Shared by this dialog's own
 *  controls and the read only line VmDetailPanel shows beside the VM's
 *  other facts. */
export function useVmCdromStatus(vmId: number) {
  return useQuery({
    queryKey: ['vms', vmId, 'cdrom'],
    queryFn: () => api<CdromStatus>(`/vms/${vmId}/cdrom`),
  })
}

/**
 * A VM's CD-ROM drive: what is mounted, plus mount and eject. Opens from the
 * VM's three dot menu, since VmDetailPanel is read only.
 *
 * The datastore and ISO pickers follow VmCreateWizard's own iso step: same
 * `/storage/{hostId}/{store}/content?node=...&content=iso` query, same
 * `poolsFrom` filter for which datastores to offer.
 */
export function VmCdromDialog({ vm, onClose }: { vm: VmRow; onClose: () => void }) {
  const qc = useQueryClient()
  const [store, setStore] = useState('')
  const [iso, setIso] = useState('')

  const status = useVmCdromStatus(vm.id)
  const hosts = useQuery({ queryKey: ['hosts'], queryFn: () => api<HostRow[]>('/hosts') })
  const storages = useQuery({ queryKey: ['storage'], queryFn: () => api<StorageRow[]>('/storage') })
  const isos = useQuery({
    queryKey: ['storage', vm.host_id, store, vm.node, 'iso'],
    enabled: store !== '' && !!vm.node,
    queryFn: () => api<ContentRow[]>(
      `/storage/${vm.host_id}/${store}/content?node=${encodeURIComponent(vm.node ?? '')}&content=iso`),
  })

  const thisHost = (hosts.data ?? []).find((h) => h.id === vm.host_id)
  const storeOpts = poolsFrom(storages.data, vm.host_id, vm.node, thisHost?.cluster_name, 'iso')

  const write = useMutation<CdromStatus, unknown, string | null>({
    mutationFn: (volid) => api<CdromStatus>(`/vms/${vm.id}/cdrom`, {
      method: 'PUT', body: JSON.stringify({ volid }),
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['vms', vm.id, 'cdrom'] })
      setStore('')
      setIso('')
    },
    onError: (e) => {
      const msg = errBody(e)?.detail
      notify.error(typeof msg === 'string' ? msg : 'Could not change the CD-ROM drive, try again.')
    },
  })

  return (
    <Dialog title={<>CD-ROM for <span className="font-mono">{vm.name}</span></>}
            width={460} onClose={onClose}>
      {status.isError ? (
        <p className="mt-3 text-[12.5px] text-red">
          Could not read this VM's CD-ROM drive from Proxmox.
        </p>
      ) : status.isPending ? (
        <div className="mt-3"><Loading label="Reading the CD-ROM drive" size={16} /></div>
      ) : (
        <div className="mt-3">
          <p className="mb-3 font-mono text-[12.5px] text-text-2">
            {status.data?.mounted && status.data.volid
              ? isoName(status.data.volid)
              : 'Nothing mounted'}
          </p>
          <div className="flex flex-wrap items-end gap-2">
            <div>
              <label htmlFor="vmcdrom-store" className={smallLabel}>Datastore</label>
              <select id="vmcdrom-store" className={inputCls} value={store}
                disabled={storages.isError || storages.isLoading}
                onChange={(e) => { setStore(e.target.value); setIso('') }}>
                <option value="">Select a datastore…</option>
                {storeOpts.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor="vmcdrom-iso" className={smallLabel}>ISO image</label>
              <select id="vmcdrom-iso" className={inputCls} value={iso}
                disabled={store === '' || isos.isError || isos.isLoading}
                onChange={(e) => setIso(e.target.value)}>
                {isos.isError
                  ? <option value="">Could not load ISOs</option>
                  : isos.isLoading
                    ? <option value="">Loading ISOs…</option>
                    : <option value="">Select an ISO…</option>}
                {(isos.data ?? []).map((v) => <option key={v.volid} value={v.volid}>{v.volid}</option>)}
              </select>
            </div>
            <Button size="sm" disabled={!iso || write.isPending} onClick={() => write.mutate(iso)}>
              Mount
            </Button>
            {status.data?.mounted && (
              <Button size="sm" variant="ghost" disabled={write.isPending}
                onClick={() => write.mutate(null)}>
                Eject
              </Button>
            )}
          </div>
        </div>
      )}
    </Dialog>
  )
}
