import type { UseQueryResult } from '@tanstack/react-query'

import { EmptyState } from './EmptyState'

/**
 * Loading, error, empty and data are four different answers and must look
 * like four different things.
 *
 * Before this component the codebase spelled every list as `(data ?? []).map`,
 * which renders a failed fetch as "No VMs discovered" — the UI stating
 * confidently that you have nothing when the truth is that it has no idea.
 * `isPending` is likewise not `isError`: react-query flips isPending false on
 * failure too, so a `!data` guard shows "Loading…" forever after a hard error.
 */
export function QueryState<T>({
  query, children, emptyTitle, emptyNote, emptyAction, empty,
  errorTitle = 'Something went wrong',
  errorNote = 'Proxploy could not reach the backend. It may be restarting.',
  loading,
}: {
  query: UseQueryResult<T>
  children: (data: T) => React.ReactNode
  emptyTitle: string
  emptyNote: string
  emptyAction?: React.ReactNode
  empty?: (data: T) => boolean
  errorTitle?: string
  errorNote?: string
  loading?: React.ReactNode
}) {
  if (query.isError) return <EmptyState title={errorTitle} note={errorNote} />
  if (query.isPending || query.data === undefined) {
    return loading ?? (
      <div role="status" aria-live="polite"
           className="grid place-items-center rounded-card border border-dashed border-line py-20 text-[12.5px] text-text-3">
        Loading…
      </div>
    )
  }
  const isEmpty = empty ? empty(query.data)
    : Array.isArray(query.data) && query.data.length === 0
  if (isEmpty) return <EmptyState title={emptyTitle} note={emptyNote} action={emptyAction} />
  return <>{children(query.data)}</>
}
