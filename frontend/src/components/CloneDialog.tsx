import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, ApiError } from '../api/client'
import type { VmRow } from '../api/hooks'
import type { JobRow } from '../api/jobs'
import { JobLog } from './JobLog'
import { inputCls } from './LoginForm'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'

type StorageRow = { host_id: number; node: string; storage: string; content: string[] }

/**
 * Clone a VM: new name, full vs linked, target storage. Same InstallDialog
 * pattern, fire, keep the job id, swap the body for the job log.
 */
export function CloneDialog({ vm, onClose }: { vm: VmRow; onClose: () => void }) {
  const qc = useQueryClient()
  const [name, setName] = useState(`${vm.name}-clone`)
  const [full, setFull] = useState(true)
  const [storage, setStorage] = useState('')
  const [jobId, setJobId] = useState<number | null>(null)
  const [error, setError] = useState('')

  const storages = useQuery({ queryKey: ['storage'], queryFn: () => api<StorageRow[]>('/storage') })
  const storeOpts = (storages.data ?? [])
    .filter((s) => s.host_id === vm.host_id && (s.content ?? []).includes('images'))

  const clone = useMutation<{ job: JobRow }, ApiError, void>({
    mutationFn: () => api<{ job: JobRow }>(`/vms/${vm.id}/clone`, {
      method: 'POST',
      body: JSON.stringify({ name: name.trim(), full, storage: storage || null }),
    }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['cluster', 'activity'] })
    },
  })

  const submit = () => {
    setError('')
    clone.mutate(undefined, {
      onSuccess: (r) => setJobId(r.job.id),
      // Linked clone is only valid from a template and Proxploy does not track
      // template-ness, so the option is offered unconditionally and PVE's own
      // rejection is shown verbatim rather than guessed at up front.
      onError: (e) => setError(
        e instanceof ApiError
          ? String((e.body as any)?.detail ?? (e.body as any)?.error ?? e.message)
          : 'Request failed'),
    })
  }

  return (
    <Dialog title={<>Clone <span className="font-mono">{vm.name}</span></>} width={520} onClose={onClose}>

    {jobId ? (
      <div className="mt-4">
        <JobLog jobId={jobId} />
        <Button className="mt-3" variant="ghost" onClick={onClose}>Close</Button>
      </div>
    ) : (
      <>
        <div className="mt-4 space-y-3">
          <div>
            <label htmlFor="clone-name" className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
              New name
            </label>
            <input id="clone-name" className={inputCls} value={name}
              onChange={(e) => setName(e.target.value)} />
          </div>
          <fieldset className="space-y-1.5">
            <legend className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">Mode</legend>
            <label htmlFor="clone-full" className="flex items-center gap-2 text-[13px] text-text-2">
              <input id="clone-full" type="radio" name="clone-mode" checked={full}
                onChange={() => setFull(true)} />
              Full clone, an independent copy of every disk
            </label>
            <label htmlFor="clone-linked" className="flex items-center gap-2 text-[13px] text-text-2">
              <input id="clone-linked" type="radio" name="clone-mode" checked={!full}
                onChange={() => setFull(false)} />
              Linked clone, shares the base disk, template sources only
            </label>
          </fieldset>
          <div>
            <label htmlFor="clone-storage" className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
              Target storage
            </label>
            <select id="clone-storage" className={inputCls} value={storage}
              disabled={storages.isError}
              onChange={(e) => setStorage(e.target.value)}>
              {storages.isError
                ? <option value="">Could not load datastores</option>
                : <option value="">Same as source</option>}
              {storeOpts.map((s) => <option key={s.storage} value={s.storage}>{s.storage}</option>)}
            </select>
          </div>
          {!full && (
            <p className="text-[12px] text-text-3">
              Proxmox only accepts a linked clone when the source is a template.
              Proxploy does not track template-ness, so if this VM is not one,
              Proxmox&apos;s own error is shown here unchanged.
            </p>
          )}
          {error && <p className="text-[12.5px] text-red">{error}</p>}
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button disabled={clone.isPending || name.trim() === ''} onClick={submit}>Clone</Button>
        </div>
      </>
    )}
    </Dialog>
  )
}
