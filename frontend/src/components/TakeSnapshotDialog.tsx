import { useState } from 'react'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'
import { inputCls } from './LoginForm'

export function TakeSnapshotDialog({ vmName, pending, onSubmit, onClose }: {
  vmName: string
  pending: boolean
  onSubmit: (v: { name: string; description: string; vmstate: boolean }) => void
  onClose: () => void
}) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [vmstate, setVmstate] = useState(false)

  return (
    <Dialog title={<>Take a snapshot of <span className="font-mono">{vmName}</span></>}
            width={460} onClose={onClose}>
      <form className="mt-2"
        onSubmit={(e) => { e.preventDefault(); onSubmit({ name: name.trim(), description, vmstate }) }}>
        <label htmlFor="snap-name" className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
          Snapshot name
        </label>
        <input id="snap-name" autoFocus className={inputCls} value={name} placeholder="pre-upgrade"
          onChange={(e) => setName(e.target.value)} />

        <label htmlFor="snap-desc" className="mt-4 mb-1 block text-[11px] uppercase tracking-wide text-text-3">
          Description (optional)
        </label>
        <input id="snap-desc" className={inputCls} value={description}
          onChange={(e) => setDescription(e.target.value)} />

        <label htmlFor="snap-ram" className="mt-4 flex items-center gap-2 text-[13px] text-text-2">
          <input id="snap-ram" type="checkbox" checked={vmstate}
            onChange={(e) => setVmstate(e.target.checked)} />
          Include RAM (vmstate)
        </label>
        <p className="mt-1.5 text-[12px] text-text-3">
          Including RAM captures the running state so a rollback resumes mid-boot,
          but writes the whole memory allocation to disk and briefly pauses the guest.
        </p>

        <div className="mt-5 flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          {/* PVE requires a name; a nameless submit is a guaranteed 400. */}
          <Button type="submit" disabled={pending || name.trim() === ''}>
            {pending ? 'Starting…' : 'Take snapshot'}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
