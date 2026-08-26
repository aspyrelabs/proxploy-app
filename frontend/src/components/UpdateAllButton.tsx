import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { useEntitlements } from '../api/hooks'
import { notify } from '../lib/notify'
import { Button } from './ui/button'

/** "Update all": one confirm covers the batch, the backend still requires
 *  explicit consent, and enqueues one job per stale app so each gets its own
 *  transcript. */
export function UpdateAllButton() {
  const ent = useEntitlements()
  const qc = useQueryClient()
  // ent.data != null, not a bare has(): has() is fail-closed and reads false
  // while the first fetch is in flight, which disabled this button with a
  // "Pro" tooltip for every plan on load, and permanently if the fetch
  // failed. Same guard every other gate in the app uses.
  const allowed = ent.data != null && ent.has('store.update_all')
  const run = useMutation({
    mutationFn: () => api<{ jobs: { id: number }[]; skipped: { reason: string }[] }>(
      '/apps/update-all', { method: 'POST', body: JSON.stringify({ consent: true }) }),
    onSuccess: (r) => {
      if (r.jobs.length === 0) {
        // Never a bare silence: "nothing happened" and "it is broken" look
        // identical otherwise.
        notify.info('Nothing to update, every app is on its catalog commit.')
        return
      }
      notify.success(`Updating ${r.jobs.length} app${r.jobs.length === 1 ? '' : 's'}, `
                    + 'follow them in the notifications bell.')
    },
    onError: () => notify.error('Could not start the updates, try again.'),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['apps'] })
      // The toast points at the bell, which LiveProvider fills from the SSE
      // stream rather than from a query, so there is nothing else to refetch.
      qc.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
  return (
    <Button variant="ghost" disabled={run.isPending || !allowed}
      title={!allowed ? 'Pro: Update all' : undefined}
      onClick={() => {
      if (window.confirm('Update every app that has a newer catalog commit? '
                         + 'Each update runs a community script as root on its node.')) {
        run.mutate()
      }
    }}>Update all</Button>
  )
}
