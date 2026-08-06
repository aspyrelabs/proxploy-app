import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { QueryState } from '../components/QueryState'

// A UseQueryResult is a big interface; these tests only exercise the four
// fields QueryState reads, so a cast keeps the test readable rather than
// constructing a full fake result object.
const q = (over: object) => ({ isPending: false, isError: false, data: undefined, ...over }) as never

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('QueryState', () => {
  it('renders data when the query resolved with rows', () => {
    wrap(<QueryState query={q({ data: [{ id: 1 }] })} emptyTitle="none" emptyNote="">
      {(rows: { id: number }[]) => <p>{rows.length} rows</p>}
    </QueryState>)
    expect(screen.getByText('1 rows')).toBeInTheDocument()
  })

  it('renders the empty state for a resolved-but-empty list', () => {
    wrap(<QueryState query={q({ data: [] })} emptyTitle="No VMs yet" emptyNote="Create one.">
      {() => <p>never</p>}
    </QueryState>)
    expect(screen.getByText('No VMs yet')).toBeInTheDocument()
  })

  it('renders the ERROR state, not the empty state, when the query failed', () => {
    // The regression this component exists to prevent: a failed fetch must
    // never be indistinguishable from "you have nothing".
    wrap(<QueryState query={q({ isError: true })} emptyTitle="No VMs yet" emptyNote="Create one.">
      {() => <p>never</p>}
    </QueryState>)
    expect(screen.queryByText('No VMs yet')).not.toBeInTheDocument()
    expect(screen.getByText(/could not/i)).toBeInTheDocument()
  })

  it('renders loading separately from empty', () => {
    wrap(<QueryState query={q({ isPending: true })} emptyTitle="No VMs yet" emptyNote="Create one.">
      {() => <p>never</p>}
    </QueryState>)
    expect(screen.queryByText('No VMs yet')).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toBeInTheDocument()
  })
})
