import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import type { AppRow } from '../api/hooks'
import { errBody } from '../api/network'
import { notify } from '../lib/notify'
import { inputCls } from './LoginForm'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'

const label = 'mb-1 block text-[11px] uppercase tracking-wide text-text-3'

/**
 * PATCH /apps/{id}: cores/memory_mb/swap_mb go straight to PVE (synchronous,
 * no job); name/web_port/web_protocol/web_path are Proxploy-only. Only
 * fields the operator actually touched are sent, an absent key means "leave
 * alone" server-side and the backend 422s on an empty body ("nothing to
 * change"), so a submit with no edits is disabled here rather than sent.
 *
 * GET /apps/{id} never reports the CT's current cores/memory/swap (doc 05's
 * App row is presentation state, not PVE's own config), so those three start
 * blank: there is nothing honest to prefill them with.
 */
export function ReconfigureDialog({ app, onClose }: { app: AppRow; onClose: () => void }) {
  const qc = useQueryClient()
  const [cores, setCores] = useState('')
  const [memoryMb, setMemoryMb] = useState('')
  const [swapMb, setSwapMb] = useState('')
  const [name, setName] = useState(app.name)
  const [webPort, setWebPort] = useState(app.web_port != null ? String(app.web_port) : '')
  const [webProtocol, setWebProtocol] = useState(app.web_protocol ?? '')
  const [webPath, setWebPath] = useState(app.web_path ?? '')
  const [error, setError] = useState('')

  const changed = (): Record<string, unknown> => {
    const body: Record<string, unknown> = {}
    if (cores.trim() !== '') body.cores = Number(cores)
    if (memoryMb.trim() !== '') body.memory_mb = Number(memoryMb)
    if (swapMb.trim() !== '') body.swap_mb = Number(swapMb)
    if (name.trim() !== '' && name.trim() !== app.name) body.name = name.trim()
    const basePort = app.web_port != null ? String(app.web_port) : ''
    if (webPort !== basePort && webPort.trim() !== '') body.web_port = Number(webPort)
    if (webProtocol !== (app.web_protocol ?? '')) body.web_protocol = webProtocol
    if (webPath !== (app.web_path ?? '')) body.web_path = webPath
    return body
  }
  const body = changed()
  const dirty = Object.keys(body).length > 0

  const reconfigure = useMutation<{ id: number; changed: Record<string, unknown> },
    unknown, Record<string, unknown>>({
    mutationFn: (b) => api(`/apps/${app.id}`, { method: 'PATCH', body: JSON.stringify(b) }),
    onSettled: () => qc.invalidateQueries({ queryKey: ['apps'] }),
  })

  const submit = () => {
    if (!dirty) return
    setError('')
    reconfigure.mutate(body, {
      onSuccess: () => { notify.success('Saved.'); onClose() },
      onError: (e) => {
        const b = errBody(e)
        // 502 pve_error's `detail` is Proxmox's own rejection reason, the only
        // actionable part of this failure, shown verbatim rather than
        // paraphrased. Every other 4xx here (404/409/422) also carries a
        // plain string `detail` (see main.py::problem_handler).
        setError(String(b?.detail ?? 'Could not save the change, try again.'))
        notify.error(String(b?.detail ?? 'Could not save the change.'))
      },
    })
  }

  return (
    <Dialog title={<>Reconfigure <span className="font-mono">{app.name}</span></>} width={520} onClose={onClose}>

    <div className="mt-4 space-y-4">
      <fieldset className="space-y-2">
        <legend className="mb-1 text-[12px] font-semibold text-text">
          Resources (pushed to Proxmox live)
        </legend>
        <div className="grid grid-cols-3 gap-2">
          <div>
            <label htmlFor="reconf-cores" className={label}>Cores</label>
            <input id="reconf-cores" className={inputCls} type="number" min={1}
              placeholder="unchanged" value={cores}
              onChange={(e) => setCores(e.target.value)} />
          </div>
          <div>
            <label htmlFor="reconf-mem" className={label}>Memory (MB)</label>
            <input id="reconf-mem" className={inputCls} type="number" min={16}
              placeholder="unchanged" value={memoryMb}
              onChange={(e) => setMemoryMb(e.target.value)} />
          </div>
          <div>
            <label htmlFor="reconf-swap" className={label}>Swap (MB)</label>
            <input id="reconf-swap" className={inputCls} type="number" min={0}
              placeholder="unchanged" value={swapMb}
              onChange={(e) => setSwapMb(e.target.value)} />
          </div>
        </div>
      </fieldset>

      <fieldset className="space-y-2">
        <legend className="mb-1 text-[12px] font-semibold text-text">
          Presentation (Proxploy only, no PVE call)
        </legend>
        <div>
          <label htmlFor="reconf-name" className={label}>Name</label>
          <input id="reconf-name" className={inputCls} value={name}
            onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="grid grid-cols-3 gap-2">
          <div>
            <label htmlFor="reconf-port" className={label}>Web port</label>
            <input id="reconf-port" className={inputCls} type="number" min={1}
              value={webPort} onChange={(e) => setWebPort(e.target.value)} />
          </div>
          <div>
            <label htmlFor="reconf-protocol" className={label}>Protocol</label>
            <input id="reconf-protocol" className={inputCls} value={webProtocol}
              onChange={(e) => setWebProtocol(e.target.value)} />
          </div>
          <div>
            <label htmlFor="reconf-path" className={label}>Path</label>
            <input id="reconf-path" className={inputCls} value={webPath}
              onChange={(e) => setWebPath(e.target.value)} />
          </div>
        </div>
      </fieldset>

      {error && <p className="text-[12.5px] text-red">{error}</p>}
    </div>

    <div className="mt-4 flex justify-end gap-2">
      <Button variant="ghost" onClick={onClose}>Cancel</Button>
      <Button disabled={!dirty || reconfigure.isPending} onClick={submit}>
        {reconfigure.isPending ? 'Saving…' : 'Save'}
      </Button>
    </div>
    </Dialog>
  )
}
