import { useState } from 'react'
import { toast } from 'sonner'
import type { BridgeConfig, Iface } from '../api/network'
import { errBody, useStageBridge, useUpdateBridge } from '../api/network'
import { inputCls } from './LoginForm'
import { Button } from './ui/button'

/**
 * Create or edit one host bridge. Everything this form does is STAGED: Proxmox
 * writes it to /etc/network/interfaces.new and the live config is untouched
 * until someone presses Apply on the page behind this dialog.
 */
export function BridgeForm({ hostId, node, iface, onClose }: {
  hostId: number; node: string; iface: Iface | null; onClose: () => void
}) {
  const create = useStageBridge()
  const update = useUpdateBridge()
  const editing = iface != null
  const [name, setName] = useState(iface?.iface ?? '')
  const [ports, setPorts] = useState(iface?.bridge_ports ?? '')
  const [cidr, setCidr] = useState(iface?.cidr ?? '')
  const [gateway, setGateway] = useState(iface?.gateway ?? '')
  const [comments, setComments] = useState(iface?.comments ?? '')
  const [vlanAware, setVlanAware] = useState(iface?.vlan_aware ?? false)
  const [autostart, setAutostart] = useState(iface?.autostart ?? true)
  const [error, setError] = useState('')

  const busy = create.isPending || update.isPending

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    const config: BridgeConfig = {
      bridge_vlan_aware: vlanAware ? 1 : 0,
      autostart: autostart ? 1 : 0,
    }
    if (ports.trim()) config.bridge_ports = ports.trim()
    if (cidr.trim()) config.cidr = cidr.trim()
    if (gateway.trim()) config.gateway = gateway.trim()
    if (comments.trim()) config.comments = comments.trim()
    const done = {
      onSuccess: () => {
        toast(`${name} staged on ${node} — nothing changes until you Apply.`)
        onClose()
      },
      onError: (err: unknown) =>
        setError(String(errBody(err)?.detail ?? 'Proxmox rejected that interface config.')),
    }
    if (editing) update.mutate({ hostId, node, iface: name, config }, done)
    else create.mutate({ hostId, node, iface: name, config }, done)
  }

  const label = 'mb-1 block text-[11px] uppercase tracking-wide text-text-3'

  return (
    <div role="dialog" aria-label="Edit host bridge"
         className="fixed inset-0 z-30 grid place-items-center bg-[rgba(11,15,22,.72)] backdrop-blur-[3px]">
      <div className="w-[460px] max-w-[92vw] rounded-card border border-line bg-panel p-5">
        <h2 className="font-display text-[16px] font-semibold">
          {editing ? `Edit ${name} on ${node}` : `New bridge on ${node}`}
        </h2>
        <p className="mt-1 text-[12.5px] text-text-3">
          Staged only. Proxmox writes this to{' '}
          <span className="font-mono">/etc/network/interfaces.new</span>; {node} keeps its
          current network until you apply it.
        </p>

        <form onSubmit={submit} className="mt-4 space-y-3">
          <div>
            <label className={label} htmlFor="br-name">Interface</label>
            <input id="br-name" required disabled={editing} className={inputCls}
                   placeholder="vmbr1" value={name}
                   onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label className={label} htmlFor="br-ports">Bridge ports</label>
            <input id="br-ports" className={inputCls} placeholder="enp3s0 enp4s0"
                   value={ports} onChange={(e) => setPorts(e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={label} htmlFor="br-cidr">CIDR</label>
              <input id="br-cidr" className={inputCls} placeholder="10.9.0.1/24"
                     value={cidr} onChange={(e) => setCidr(e.target.value)} />
            </div>
            <div>
              <label className={label} htmlFor="br-gw">Gateway</label>
              <input id="br-gw" className={inputCls} placeholder="10.9.0.254"
                     value={gateway} onChange={(e) => setGateway(e.target.value)} />
            </div>
          </div>
          <div>
            <label className={label} htmlFor="br-comment">Comment</label>
            <input id="br-comment" className={inputCls} placeholder="lab network"
                   value={comments} onChange={(e) => setComments(e.target.value)} />
          </div>
          <label className="flex items-center gap-2 text-[13px] text-text-2">
            <input type="checkbox" checked={vlanAware}
                   onChange={(e) => setVlanAware(e.target.checked)} /> VLAN aware
          </label>
          <label className="flex items-center gap-2 text-[13px] text-text-2">
            <input type="checkbox" checked={autostart}
                   onChange={(e) => setAutostart(e.target.checked)} /> Start on boot
          </label>
          {error && <p className="text-[12.5px] text-red">{error}</p>}
          <div className="flex justify-end gap-2 pt-1">
            <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={busy || !name.trim()}>
              {busy ? 'Staging…' : 'Stage change'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
