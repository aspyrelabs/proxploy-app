import { useState } from 'react'
import type { Attachment, NicPatch } from '../api/network'
import { errBody, useSetNic } from '../api/network'
import { notify } from '../lib/notify'
import { inputCls } from './LoginForm'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'

/**
 * Edit one guest NIC: bridge and VLAN tag. Nothing else.
 *
 * Deliberately NOT the firewall flag, even though the API accepts it: see the
 * comment beside the state line below.
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
  const [error, setError] = useState('')
  // Containers only, and that is PVE's own split rather than a choice made here:
  // `pct set --netN` carries ip/gw, `qm set --netN` has no such field, and a VM's
  // address is a cloud-init key that a Windows guest ignores entirely. So a VM
  // gets the truth from its guest agent instead of a form it cannot honour.
  const isContainer = nic.guest_type === 'app'
  // '' means the key is absent, which is not the same as dhcp: PVE treats an
  // absent ip as unconfigured, and clearing back to that is a real intent.
  const [ipMode, setIpMode] = useState(
    nic.ip === 'dhcp' || nic.ip === 'manual' ? nic.ip : nic.ip ? 'static' : '')
  const [ipCidr, setIpCidr] = useState(
    nic.ip && nic.ip !== 'dhcp' && nic.ip !== 'manual' ? nic.ip : '')
  const [gw, setGw] = useState(nic.gw ?? '')

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    const patch: NicPatch = {}
    if (bridge && bridge !== nic.bridge) patch.bridge = bridge
    const nextTag = tag.trim() === '' ? null : Number(tag)
    if (nextTag !== nic.tag) patch.tag = nextTag   // explicit null clears the key
    if (isContainer) {
      // null clears, exactly like tag: "no address configured" is a state PVE
      // has and an operator can want back.
      const nextIp = ipMode === 'static' ? ipCidr.trim() || null : ipMode || null
      if (nextIp !== nic.ip) patch.ip = nextIp
      const nextGw = gw.trim() || null
      if (nextGw !== nic.gw) patch.gw = nextGw
    }
    if (Object.keys(patch).length === 0) { onClose(); return }
    set.mutate({ guestType: nic.guest_type, guestId: nic.guest_id, iface: nic.iface, patch }, {
      onSuccess: (r) => {
        // pending_reboot means PVE filed the change under the guest's PENDING
        // section, say so plainly instead of a green "saved".
        if (r.pending_reboot) notify.info(r.detail)
        else notify.success(`${nic.iface} updated`)
        onClose()
      },
      onError: (err) =>
        setError(String(errBody(err)?.detail ?? 'Could not update this NIC, try again.')),
    })
  }

  const label = 'mb-1 block text-[11px] uppercase tracking-wide text-text-3'

  return (
    <Dialog title={<>{nic.name ?? `guest ${nic.vmid}`} · <span className="font-mono">{nic.iface}</span></>} width={420} onClose={onClose}>
    <div className="mt-2 rounded-ctl border border-line-soft bg-elev p-2 font-mono text-[11px] text-text-3">
      <div>{nic.model ?? 'unknown'} · {nic.macaddr ?? 'unknown'}</div>
      <div className="mt-1 break-all">{nic.raw}</div>
    </div>
    <p className="mt-2 text-[12px] text-text-3">
      The adapter model and MAC address are preserved exactly as Proxmox stores
      them, this form only changes the fields below.
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

      {isContainer ? (
        <>
          <div>
            <label className={label} htmlFor="nic-ip">IPv4 address</label>
            <select id="nic-ip" className={inputCls} value={ipMode}
                    onChange={(e) => setIpMode(e.target.value)}>
              <option value="">Not configured</option>
              <option value="dhcp">DHCP</option>
              <option value="static">Static</option>
              <option value="manual">Manual, configured inside the guest</option>
            </select>
          </div>
          {ipMode === 'static' && (
            <div>
              <label className={label} htmlFor="nic-cidr">Address and prefix</label>
              <input id="nic-cidr" className={inputCls} placeholder="192.168.1.50/24"
                     value={ipCidr} onChange={(e) => setIpCidr(e.target.value)} />
              {/* Proxmox wants the prefix, and rejects a bare address. Said here
                  rather than only in the error, since the error costs a round
                  trip to learn something the field could have told you. */}
              <p className="mt-1 text-[11.5px] text-text-3">
                Include the prefix length. Proxmox does not accept a bare address.
              </p>
            </div>
          )}
          {ipMode === 'static' && (
            <div>
              <label className={label} htmlFor="nic-gw">Gateway (optional)</label>
              <input id="nic-gw" className={inputCls} placeholder="192.168.1.1"
                     value={gw} onChange={(e) => setGw(e.target.value)} />
            </div>
          )}
        </>
      ) : (
        /* A VM's address is not editable here, and saying so beats a field that
           silently does nothing. PVE addresses VMs through cloud-init, which a
           Windows guest ignores unless Cloudbase-Init is installed, and nothing
           out here can see inside a guest. What CAN be said honestly is what the
           guest agent reports, so that is what is shown. */
        <div className="rounded-ctl border border-line-soft bg-elev p-2">
          <div className={label}>Address</div>
          {nic.agent_ips == null ? (
            <p className="text-[12.5px] text-text-3">
              Unknown. The QEMU guest agent is not answering on this VM, and a
              virtual machine keeps its address inside the guest.
            </p>
          ) : nic.agent_ips.length === 0 ? (
            <p className="text-[12.5px] text-text-3">
              The guest agent reports no address on this VM.
            </p>
          ) : (
            <p className="font-mono text-[12.5px] text-text-2">
              {nic.agent_ips.join(', ')}
              <span className="ml-1 font-sans text-[11.5px] text-text-3">
                (reported by the guest agent, across all its interfaces)
              </span>
            </p>
          )}
          <p className="mt-1 text-[11.5px] text-text-3">
            Proxmox sets a virtual machine&apos;s address through cloud-init, which
            Proxploy does not write yet. Set it inside the guest, or with a DHCP
            reservation.
          </p>
        </div>
      )}
      {/* No firewall TOGGLE. Proxploy has no firewall feature: there is no rule,
          security group, alias or IP set management anywhere in it, at guest,
          node or cluster level. A switch here would read as though there were
          one, and turning it on can leave a guest unreachable with nothing in
          this product able to permit traffic again. Removed 2026-08-18, doc 11
          carries the decision. Proxmox's own UI is where the firewall lives.

          The STATE is still shown, and only when it is on, because a guest whose
          traffic is being filtered by a flag nobody can see here is worse than
          one line of explanation. Same principle as the sidebar health line:
          speak when it matters, stay quiet otherwise. */}
      {nic.firewall && (
        <p className="rounded-ctl border border-line-soft bg-elev p-2 text-[12px] text-text-3">
          Proxmox&apos;s firewall is enabled on this NIC. Its rules are managed in
          the Proxmox web UI, not here.
        </p>
      )}
      {error && <p className="text-[12.5px] text-red">{error}</p>}
      <div className="flex justify-end gap-2 pt-1">
        <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
        <Button type="submit" disabled={set.isPending}>
          {set.isPending ? 'Saving…' : 'Save NIC'}
        </Button>
      </div>
    </form>
    </Dialog>
  )
}
