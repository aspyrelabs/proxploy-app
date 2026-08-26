import { SkeletonField, SkeletonGroup } from '../ui/skeleton'
import { useStoragePools } from './pools'

const lbl = 'mb-1 block text-[11px] uppercase tracking-wide text-text-3'
const selectCls = 'w-full rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px]'

/**
 * The two storage pickers in the install dialog's Advanced block.
 *
 * `rootdir` and `vztmpl` are different questions: a pool that holds container
 * templates cannot necessarily hold a container's rootfs, so offering every
 * pool for both would let an operator pick a vztmpl-only pool as the rootfs
 * and fail at `pct create` after this form said it was fine. This filter is
 * only the friendly early path — `resolve_storage_pools`
 * (backend/proxploy/services/appstore.py) revalidates against the node's live
 * content list and refuses invalid or ambiguous pools, so don't duplicate it.
 */
export function StorageFields({ hostId, node, clusterName, container, template,
                                onChange }: {
  hostId: number | null
  node: string | null | undefined
  clusterName?: string | null
  container: string
  template: string
  onChange: (next: { container: string; template: string }) => void
}) {
  const { rootdir, vztmpl, state } = useStoragePools(hostId, node, clusterName)

  // `state`, not just the lists: the snapshot is EMPTY until the first poll
  // after a backend restart and absent entirely on a 403, so an empty list is
  // indistinguishable from "this host has no storage" unless the load state
  // travels with it.
  if (state !== 'ok') {
    return (
      <SkeletonGroup label="Reading the storage pools for this host"
                     className="mt-2 space-y-2">
        <SkeletonField label="w-28" />
        <SkeletonField label="w-24" />
      </SkeletonGroup>
    )
  }

  return (
    <div className="mt-2 space-y-2">
      <div>
        <label htmlFor="container-storage" className={lbl}>Container storage</label>
        <select id="container-storage" className={selectCls} value={container}
          onChange={(e) => onChange({ container: e.target.value, template })}>
          <option value="">Select a pool…</option>
          {rootdir.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>
      <div>
        <label htmlFor="template-storage" className={lbl}>Template storage</label>
        <select id="template-storage" className={selectCls} value={template}
          onChange={(e) => onChange({ container, template: e.target.value })}>
          <option value="">Select a pool…</option>
          {vztmpl.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>
    </div>
  )
}
