import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { useRunBackup } from '../api/backups'
import { useStorage } from '../api/storage'
import { servedTo } from './install/pools'
import { notify } from '../lib/notify'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'
import { inputCls } from './LoginForm'
import { JobLog } from './JobLog'

/**
 * What the dialog needs to know about the guest it is backing up, and nothing
 * more. Deliberately NOT `AppRow | VmRow`: those two rows agree on almost
 * nothing (an app has `ctid`, a VM has `vmid`; an app has memory and disk
 * totals and an IP, a VM has none of them), so a component taking the union
 * would have to sniff which fields exist to decide what it is looking at, and
 * every new field on either row becomes another branch in here. The caller
 * already knows which kind of guest it holds, so it does the one translation
 * and this dialog stays a single code path.
 *
 * `label` is the identity line an operator reads on the Proxmox side, "CT 150"
 * for an app or "VM 100" for a VM. It is passed in rather than built from
 * `type` and an id field because the two rows spell that id differently, which
 * is the exact sniffing this shape exists to avoid.
 */
export type BackupGuestTarget = {
  type: 'app' | 'vm'
  /** Proxploy's own row id, which is what POST /backups/run resolves. */
  id: number
  name: string
  hostId: number
  hostName: string
  label: string
}

/**
 * The one-guest sibling of routes/backups.tsx's RunDialog. That dialog runs one
 * vzdump job over every guest on a chosen host; this one runs the same job
 * kind over exactly one guest, the app or VM it was opened from. The host is
 * already known (`guest.hostId`), so there is no host picker, and there is
 * nothing to enumerate: the guest list is the single guest.
 *
 * `servedTo`, not `s.host_id === guest.hostId`: GET /storage drops host_id
 * from its dedupe key, so on a cluster a datastore reported by a sibling node
 * comes back owned by whichever host polled first. RunDialog hit this first;
 * see pools.ts::servedTo for the full explanation. `guest.hostId` alone
 * cannot answer that, so this dialog also fetches /hosts (the same
 * ['hosts'] cache RunDialog and Settings already populate) purely to read
 * that host's cluster_name.
 */
export function BackupGuestDialog({ guest, onClose }: {
  guest: BackupGuestTarget
  onClose: () => void
}) {
  const hosts = useQuery({
    queryKey: ['hosts'],
    queryFn: () => api<{ id: number; name: string; cluster_name?: string | null }[]>('/hosts'),
  })
  const storage = useStorage()
  const run = useRunBackup()
  const [store, setStore] = useState('')
  const [jobId, setJobId] = useState<number | null>(null)

  const noun = guest.type === 'vm' ? 'virtual machine' : 'app'
  const clusterName = hosts.data?.find((h) => h.id === guest.hostId)?.cluster_name ?? null
  // Nothing is concluded while either query is still in flight: an empty
  // `stores` list means "not fetched yet" exactly as readily as "nothing
  // there", the same rule RunDialog's `checking` flag enforces.
  const checking = hosts.isPending || storage.isPending
  const stores = checking ? [] : (storage.data ?? []).filter((s) =>
    servedTo(s, guest.hostId, clusterName) && s.content.includes('backup'))
  const target = stores.some((s) => s.storage === store) ? store : (stores[0]?.storage ?? '')
  const blocked = checking ? null
    : stores.length === 0
      ? `No storage on ${guest.hostName} accepts backups. Add one on the Storage page, or `
        + `connect a Proxmox Backup Server.`
      : null

  return (
    <Dialog title={<>Back up <span className="font-mono">{guest.name}</span></>} width={440} onClose={onClose}>
    {jobId != null ? (
      <div className="mt-4">
        <JobLog jobId={jobId} />
        <Button className="mt-3" variant="ghost" onClick={onClose}>Close</Button>
      </div>
    ) : (
      <>
        <p className="mt-2 text-[12.5px] text-text-3">
          Backs up <strong className="text-text-2">{guest.name}</strong> ({guest.label}), in
          snapshot mode, so the {noun} keeps running while the archive is taken.
        </p>
        {blocked ? (
          <p className="mt-3 rounded-ctl border border-amber/30 bg-amber-dim p-2 text-[12.5px] text-text-2">
            {blocked}
          </p>
        ) : !checking && (
          <>
            <label className="mt-4 block text-[11px] uppercase tracking-wide text-text-3"
                   htmlFor="bk-guest-store">Archive lands on</label>
            <select id="bk-guest-store" className={inputCls} value={target}
                    onChange={(e) => setStore(e.target.value)}>
              {stores.map((s) => (
                <option key={s.storage} value={s.storage}>
                  {s.storage}{s.type ? ` (${s.type})` : ''}
                </option>
              ))}
            </select>
          </>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button disabled={blocked != null || checking || run.isPending}
                  title={blocked ?? undefined}
                  onClick={() => run.mutate(
                    { hostId: guest.hostId, storage: target,
                      guests: [{ type: guest.type, id: guest.id }] },
                    {
                      onSuccess: (r) => setJobId(r.job.id),
                      onError: () => notify.error('Could not start the backup, try again.'),
                    })}>
            {run.isPending ? 'Starting…' : 'Start backup'}
          </Button>
        </div>
      </>
    )}
    </Dialog>
  )
}
