import { useState } from 'react'
import { toast } from 'sonner'
import type { Attachment, NicPatch } from '../api/network'
import { errBody, useSetNic } from '../api/network'
import { inputCls } from './LoginForm'
import { Button } from './ui/button'

/**
 * Edit one guest NIC: bridge, VLAN tag, firewall. Nothing else.
 *
 * The NIC's model and MAC are shown but never submitted. Proxmox stores them in
 * the netN head token (`virtio=AA:BB:CC:DD:EE:FF`), and the backend edits the
 * string it read rather than rebuilding one, so this form sends only the keys
 * the operator touched and the head token survives untouched.
 */
export function NicForm({ nic, bridges, onClose }: {
  nic: Attachment; bridges: string[]; onClose: () => void
}) {
  const set = useSetNic()
  const [bridge, setBridge] = useState(nic.bridge ?? '')
  const [tag, setTag] = useState(nic.tag == null ? '' : String(nic.tag))
  const [firewall, setFirewall] = useState(nic.firewall)
  const [error, setError] = useState('')

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    const patch: NicPatch = {}
    if (bridge && bridge !== nic.bridge) patch.bridge = bridge
    const nextTag = tag.trim() === '' ? null : Number(tag)
    if (nextTag !== nic.tag) patch.tag = nextTag   // explicit null clears the key
    if (firewall !== nic.firewall) patch.firewall = firewall
    if (Object.keys(patch).length === 0) { onClose(); return }
    set.mutate({ guestType: nic.guest_type, guestId: nic.guest_id, iface: nic.iface, patch }, {
      onSuccess: (r) => {
        // pending_reboot means PVE filed the change under the guest's PENDING
        // section, say so plainly instead of a green "saved".
        if (r.pending_reboot) toast(r.detail)
        else toast.success(`${nic.iface} updated`)
        onClose()
      },
      onError: (err) =>
        setError(String(errBody(err)?.detail ?? 'Could not update this NIC, try again.')),
    })
  }

  const label = 'mb-1 block text-[11px] uppercase tracking-wide text-text-3'

  return (
    <div role="dialog" aria-label="Edit guest NIC"
         className="fixed inset-0 z-30 grid place-items-center bg-scrim backdrop-blur-[3px]">
      <div className="w-[420px] max-w-[92vw] rounded-card border border-line bg-panel p-5">
        <h2 className="font-display text-[16px] font-semibold">
          {nic.name ?? `guest ${nic.vmid}`} · <span className="font-mono">{nic.iface}</span>
        </h2>
        <div className="mt-2 rounded-ctl border border-line-soft bg-elev p-2 font-mono text-[11px] text-text-3">
          <div>{nic.model ?? 'unknown'} · {nic.macaddr ?? 'unknown'}</div>
          <div className="mt-1 break-all">{nic.raw}</div>
        </div>
        <p className="mt-2 text-[12px] text-text-3">
          The adapter model and MAC address are preserved exactly as Proxmox stores
          them, this form only changes the three fields below.
        </p>

        <form onSubmit={submit} className="mt-4 space-y-3">
          <div>
            <label className={label} htmlFor="nic-bridge">Bridge</label>
            <select id="nic-bridge" className={inputCls} value={bridge}
                    onChange={(e) => setBridge(e.target.value)}>
              {bridge === '' && <option value="">Select a bridge…</option>}
              {bridges.map((b) => <option key={b} value={b}>{b}</option>)}
              {bridge !== '' && !bridges.includes(bridge) &&
                <option value={bridge}>{bridge}</option>}
            </select>
          </div>
          <div>
            <label className={label} htmlFor="nic-tag">VLAN tag (blank = untagged)</label>
            <input id="nic-tag" type="number" min={1} max={4094} className={inputCls}
                   value={tag} onChange={(e) => setTag(e.target.value)} />
          </div>
          <label className="flex items-center gap-2 text-[13px] text-text-2">
            <input type="checkbox" checked={firewall}
                   onChange={(e) => setFirewall(e.target.checked)} />
            Firewall enabled on this NIC
          </label>
          {error && <p className="text-[12.5px] text-red">{error}</p>}
          <div className="flex justify-end gap-2 pt-1">
            <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={set.isPending}>
              {set.isPending ? 'Saving…' : 'Save NIC'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
