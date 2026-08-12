import { QueryClient, QueryClientProvider, useMutation, useQuery } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { CardLoadingOverlay } from '../components/ui/card-loading-overlay'

// A stand-in call site: exactly the shape a real card wires up. `firstLoad`
// tracks the query's own `isPending` (true only until data has ever loaded
// once), `mutating` tracks a mutation's `isPending`. Neither is `isFetching`,
// which is the whole point -- see the third test.
function TestCard({ queryFn, refetchInterval, mutationFn, fireMutation }: {
  queryFn: () => Promise<string>
  refetchInterval?: number
  mutationFn?: () => Promise<void>
  fireMutation?: boolean
}) {
  const q = useQuery({ queryKey: ['test-card'], queryFn, refetchInterval })
  const m = useMutation({ mutationFn: mutationFn ?? (() => Promise.resolve()) })
  if (fireMutation && !m.isPending && !m.isSuccess) m.mutate()
  return (
    <CardLoadingOverlay state={{ firstLoad: q.isPending, mutating: m.isPending }}>
      <div data-testid="content">{q.data ?? 'no data yet'}</div>
    </CardLoadingOverlay>
  )
}

const wrap = (ui: React.ReactElement) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

// A promise the test controls the resolution of, so it can inspect state
// mid-flight rather than only before/after.
function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((r) => { resolve = r })
  return { promise, resolve }
}

describe('CardLoadingOverlay', () => {
  it('shows the veil on first load and marks the card aria-busy', async () => {
    const d = deferred<string>()
    wrap(<TestCard queryFn={() => d.promise} />)

    const busyContainer = (await screen.findByTestId('content')).closest('[aria-busy]')!
    expect(busyContainer).toHaveAttribute('aria-busy', 'true')
    expect(screen.getByRole('status')).toBeInTheDocument()

    d.resolve('loaded')
    await waitFor(() => expect(busyContainer).toHaveAttribute('aria-busy', 'false'))
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('shows the veil while a mutation is in flight, with previous content still in the DOM', async () => {
    const d = deferred<void>()
    wrap(<TestCard queryFn={() => Promise.resolve('existing data')}
                    mutationFn={() => d.promise} fireMutation />)

    // The query resolved already; the mutation is what is holding the veil up.
    await screen.findByText('existing data')
    await waitFor(() => expect(screen.getByRole('status')).toBeInTheDocument())
    // The old content is still there underneath the veil, not unmounted.
    expect(screen.getByTestId('content')).toHaveTextContent('existing data')
    expect(screen.getByTestId('content').closest('[aria-busy]')).toHaveAttribute('aria-busy', 'true')

    d.resolve()
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())
  })

  it('does NOT show the veil on a background refetch when data is already present', async () => {
    // This is the regression the shared component exists to prevent: a poll
    // (or any refetch that is not a first load) must not re-veil a card that
    // already has content, even while genuinely `isFetching`.
    let calls = 0
    const d2 = deferred<string>()
    wrap(<TestCard queryFn={() => {
      calls += 1
      return calls === 1 ? Promise.resolve('first page') : d2.promise
    }} refetchInterval={10} />)

    await screen.findByText('first page')
    expect(screen.queryByRole('status')).not.toBeInTheDocument()

    // Wait for the interval to kick a background refetch off. It is now
    // genuinely `isFetching`, mid-flight, with the old data still shown --
    // and the veil must stay hidden through all of it.
    await waitFor(() => expect(calls).toBeGreaterThan(1))
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.getByText('first page')).toBeInTheDocument()

    d2.resolve('second page')
    await waitFor(() => expect(screen.getByText('second page')).toBeInTheDocument())
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('spins the progress_activity glyph, Material Symbols\' purpose-built spinner icon', async () => {
    const d = deferred<string>()
    const { container } = wrap(<TestCard queryFn={() => d.promise} />)

    await screen.findByRole('status')
    const spinner = container.querySelector('.material-symbols-outlined')
    expect(spinner).not.toBeNull()
    expect(spinner!.textContent).toBe('progress_activity')

    d.resolve('loaded')
  })
})
