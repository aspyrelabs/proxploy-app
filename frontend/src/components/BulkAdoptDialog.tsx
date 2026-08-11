import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import type { DiscoveredRow } from '../api/hooks'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'

export function BulkAdoptDialog({ items, onClose }: {
  items: DiscoveredRow[]; onClose: () => void
}) {
  const [checked, setChecked] = useState<Set<string>>(
    new Set(items.map((i) => `${i.host_id}:${i.ctid}`)))
  const qc = useQueryClient()
  const adopt = useMutation({
    mutationFn: (payload: { items: { host_id: number; ctid: number; name: string; catalog_slug: string | null }[] }) =>
      api<{ adopted: number[] }>('/apps/adopt', { method: 'POST', body: JSON.stringify(payload) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['apps'] })
      onClose()
    },
  })

  const toggle = (key: string) => setChecked((prev) => {
    const next = new Set(prev)
    next.has(key) ? next.delete(key) : next.add(key)
    return next
  })

  const submit = () => {
    const payload = items
      .filter((i) => checked.has(`${i.host_id}:${i.ctid}`))
      .map((i) => ({ host_id: i.host_id, ctid: i.ctid, name: i.name ?? `CT ${i.ctid}`,
                    catalog_slug: i.suggestion }))
    adopt.mutate({ items: payload })
  }

  return (
    <Dialog title={'Adopt discovered containers'} width={480} onClose={onClose}>
    <div className="mt-3 space-y-1">
      {items.map((i) => {
        const key = `${i.host_id}:${i.ctid}`
        return (
          <label key={key} className="flex items-center gap-2 font-mono text-[12px] text-text-2">
            <input type="checkbox" checked={checked.has(key)} onChange={() => toggle(key)} />
            CT {i.ctid} · {i.name ?? 'unknown'} · {i.host_name}
            {i.suggestion && <span className="text-amber">matches "{i.suggestion}"</span>}
          </label>
        )
      })}
    </div>
    <div className="mt-4 flex justify-end gap-2">
      <Button variant="ghost" onClick={onClose}>Cancel</Button>
      <Button variant="primary" disabled={checked.size === 0 || adopt.isPending} onClick={submit}>
        Adopt {checked.size} container{checked.size === 1 ? '' : 's'}
      </Button>
    </div>
    </Dialog>
  )
}
