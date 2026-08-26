import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, ApiError } from '../api/client'
import { servedTo } from './install/pools'
import type { VmRow } from '../api/hooks'
import type { JobRow } from '../api/jobs'
import { JobLog } from './JobLog'
import { inputCls } from './LoginForm'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'
import { Loading } from './ui/loading'

type StorageRow = { host_id: number; node: string; storage: string; content: string[]
                   cluster_name: string | null }

export function CloneDialog({ vm, onClose }: { vm: VmRow; onClose: () => void }) {
  const qc = useQueryClient()
  const [name, setName] = useState(`${vm.name}-clone`)
  const [full, setFull] = useState(true)
  const [storage, setStorage] = useState('')
  const [jobId, setJobId] = useState<number | null>(null)
  const [error, setError] = useState('')

  const storages = useQuery({ queryKey: ['storage'], queryFn: () => api<StorageRow[]>('/storage') })
  // Shares the app-wide ['hosts'] cache; this is here only for cluster_name.
  const hosts = useQuery({
    queryKey: ['hosts'],
    queryFn: () => api<{ id: number; cluster_name?: string | null }[]>('/hosts'),
  })
  // servedTo, not `s.host_id === vm.host_id`: GET /storage drops host_id from
  // its dedupe key, so on a cluster every row is owned by whichever host polled
  // first and a clone onto any other host of that cluster had nothing to offer.
  const storeOpts = (storages.data ?? [])
    .filter((s) => servedTo(s, vm.host_id,
                            (hosts.data ?? []).find((h) => h.id === vm.host_id)?.cluster_name)
      && (s.content ?? []).includes('images'))

  const clone = useMutation<{ job: JobRow }, ApiError, void>({
    mutationFn: () => api<{ job: JobRow }>(`/vms/${vm.id}/clone`, {
      method: 'POST',
      body: JSON.stringify({ name: name.trim(), full, storage: storage || null }),
    }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
    },
  })

  const submit = () => {
    setError('')
    clone.mutate(undefined, {
      onSuccess: (r) => setJobId(r.job.id),
      // The linked-clone case is refused by the route now, not by PVE, so the
      // detail this shows names templates instead of a volume path.
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
            {/* Only for a template. PVE accepts a linked clone from nothing
                else and its refusal never says so, so offering the choice on an
                ordinary guest is offering something that always fails (doc 12
                check 18). The row still appears, disabled and explained,
                because silently dropping it would leave an operator who has
                used linked clones before wondering where it went. */}
            <label htmlFor="clone-linked"
              className={`flex items-center gap-2 text-[13px] ${
                vm.template ? 'text-text-2' : 'cursor-not-allowed text-text-3'}`}>
              <input id="clone-linked" type="radio" name="clone-mode" checked={!full}
                disabled={!vm.template}
                onChange={() => setFull(false)} />
              Linked clone, shares the base disk
              {vm.template ? '' : ', needs a template source'}
            </label>
          </fieldset>
          <div>
            <label htmlFor="clone-storage" className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
              Target storage
            </label>
            {/* Third branch, not two: while GET /storage is in flight this read
                "Same as source" over an empty list, which is the same sentence
                a host with no image datastores would produce. */}
            <select id="clone-storage" className={inputCls} value={storage}
              disabled={storages.isError || storages.isLoading}
              onChange={(e) => setStorage(e.target.value)}>
              {storages.isError
                ? <option value="">Could not load datastores</option>
                : storages.isLoading
                  ? <option value="">Loading datastores…</option>
                  : <option value="">Same as source</option>}
              {storeOpts.map((s) => <option key={s.storage} value={s.storage}>{s.storage}</option>)}
            </select>
          </div>
          {!full && (
            <p className="text-[12px] text-text-3">
              Shares the template&apos;s base disk, so the clone is quick and small
              and stays tied to it.
            </p>
          )}
          {error && <p className="text-[12.5px] text-red">{error}</p>}
        </div>
        <div className="mt-4 flex items-center justify-end gap-2">
          {/* The clone path never calls ctx.progress(), so the wait has no
              honest figure: the ring, never a number. */}
          {clone.isPending && <Loading label="Starting the clone" size={18} className="mr-auto" />}
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button disabled={clone.isPending || name.trim() === ''} onClick={submit}>Clone</Button>
        </div>
      </>
    )}
    </Dialog>
  )
}
