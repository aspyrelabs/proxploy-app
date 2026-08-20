import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { useEntitlements } from '../api/hooks'
import { notify } from '../lib/notify'
import { Button } from './ui/button'

/** Doc 06 Cluster overview: the "Update all" action. One confirm covers the
 *  whole batch, the backend still requires explicit consent, and enqueues one
 *  job per stale app so each has its own transcript.
 *
 *  It lives in components/ rather than beside a route because it moved off the
 *  Hosts page onto the Apps page, and a control that has already moved once is
 *  not one to leave nested inside whichever route happens to render it today. */
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
      // ['cluster','activity'] used to be invalidated here too, to move the
      // Recent activity feed that sat beside this button. The feed is gone and
      // nothing reads that key any more, so invalidating it would be work with
      // no reader. The toast points at the bell, which LiveProvider fills from
      // the SSE stream rather than from a query.
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
