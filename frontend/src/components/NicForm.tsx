import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import type { Attachment, NicPatch } from '../api/network'
import { errBody, useSetNic } from '../api/network'
import { notify } from '../lib/notify'
import { inputCls } from './LoginForm'
import { Button, amberLinkCls } from './ui/button'
import { Dialog } from './ui/dialog'
import { Icon } from './ui/icon'

/**
 * Edit one guest NIC: bridge, VLAN tag, and whether Proxmox filters it.
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
  const [firewall, setFirewall] = useState(nic.firewall)

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
    if (firewall !== nic.firewall) patch.firewall = firewall
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
  const BOX = 'space-y-3 rounded-card border border-line-soft bg-panel-2 p-4'

  return (
    <Dialog width={560} onClose={onClose}
      title={
        <span className="flex min-w-0 items-center gap-2.5">
          <span className="grid size-8 shrink-0 place-items-center rounded-tile
                           border border-line bg-panel-2 text-amber">
            <Icon name="lan" size={18} />
          </span>
          <span className="flex min-w-0 flex-col leading-tight">
            <span className="truncate">Edit {nic.iface}</span>
            <span className="truncate font-mono text-[11px] font-normal text-text-3">
              {nic.name ?? `guest ${nic.vmid}`} · {nic.model ?? 'unknown'}
            </span>
          </span>
        </span>}>

    <form onSubmit={submit} className="mt-4 space-y-3">
      <div className="rounded-card border border-line-soft bg-panel-2 p-4">
        <h3 className={label}>As Proxmox holds it</h3>
        <div className="rounded-ctl border border-line-soft bg-elev p-2 font-mono
                        text-[11px] text-text-3">
          <div>{nic.model ?? 'unknown'} · {nic.macaddr ?? 'unknown'}</div>
          <div className="mt-1 break-all">{nic.raw}</div>
        </div>
        <p className="mt-2 text-[12px] text-text-3">
          The adapter model and MAC address are kept exactly as they are. This form
          changes the fields below and nothing else.
        </p>
      </div>

      <div className={BOX}>
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
        /* A VM's address is not editable here: `qm set --netN` has no ip or gw
           field. Shown only when Proxmox knows it (the guest agent, else a
           static cloud-init address); absent otherwise (e.g. a DHCP VM with no
           agent). */
        nic.addresses?.length ? (
          <div className="rounded-ctl border border-line-soft bg-elev p-2">
            <div className={label}>Address</div>
            <p className="font-mono text-[12.5px] text-text-2">
              {nic.addresses.join(', ')}
            </p>
          </div>
        ) : null
      )}
      {/* A guest's firewall rules do nothing unless BOTH this flag and the
          guest's own `enable` option are set. */}
      <div className="flex items-center gap-2">
        <input id="nic-firewall" type="checkbox"
          checked={firewall}
          onChange={(e) => setFirewall(e.target.checked)} />
        <label htmlFor="nic-firewall" className="text-[13px] text-text-2">
          Filter this NIC through the Proxmox firewall
        </label>
      </div>
      <p className="text-[12px] text-text-3">
        Rules for this guest are on its{' '}
        <Link to={`/firewall/guest/${nic.guest_type}/${nic.guest_id}` as never}
          className={amberLinkCls}>Firewall page</Link>.
        With this off, none of them apply to this NIC.
      </p>
      </div>
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
