import type { UseQueryResult } from '@tanstack/react-query'

import { EmptyState } from './EmptyState'
import { LoadingBlock } from './ui/loading'

/**
 * Four distinct states: loading, error, empty, data.
 *
 * `isError` must be checked first: a failed query is neither pending nor has
 * data, so the pending/data guard would otherwise render "Loading…" forever.
 */
export function QueryState<T>({
  query, children, emptyTitle, emptyNote, emptyAction, empty,
  errorTitle = 'Unavailable right now',
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
    // No `value`: a query never carries a real completion signal, so this is
    // always the indeterminate ring, never a number dressed up as one.
    return loading ?? <LoadingBlock />
  }
  const isEmpty = empty ? empty(query.data)
    : Array.isArray(query.data) && query.data.length === 0
  if (isEmpty) return <EmptyState title={emptyTitle} note={emptyNote} action={emptyAction} />
  return <>{children(query.data)}</>
}
