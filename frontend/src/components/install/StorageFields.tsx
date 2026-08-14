import { useStoragePools } from './pools'

const lbl = 'mb-1 block text-[11px] uppercase tracking-wide text-text-3'
const selectCls = 'w-full rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px]'

/**
 * The two storage pickers in the install dialog's Advanced block, each
 * filtered by content type.
 *
 * `rootdir` and `vztmpl` are different questions: a pool that holds container
 * templates cannot necessarily hold a container's rootfs. Offering every pool
 * for both fields lets an operator choose a vztmpl-only pool as the rootfs,
 * which fails at `pct create` with a raw Proxmox error, AFTER this form told
 * them it was fine. `resolve_storage_pools`
 * (backend/proxploy/services/appstore.py) still revalidates against the
 * node's live content list and refuses an invalid or ambiguous pool; this
 * filter is only the friendly early path, not the enforcement, and must not
 * try to duplicate that check.
 *
 * Candidates come from useStoragePools (pools.ts), the SAME computation
 * Default mode's prompt counts, so the two modes can never disagree about how
 * many pools a host has: they are per host AND per node, deduped, and
 * status-filtered there. InstallDialog owns clearing any already-picked pool
 * name when the target host changes, since a name valid on the old host is
 * not necessarily valid on the new one.
 */
export function StorageFields({ hostId, node, container, template, onChange }: {
  hostId: number | null
  node: string | null | undefined
  container: string
  template: string
  onChange: (next: { container: string; template: string }) => void
}) {
  const { rootdir, vztmpl } = useStoragePools(hostId, node)

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
