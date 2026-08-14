import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { AppCardSkeleton } from '../components/AppCard'
import { NodeCardSkeleton } from '../components/NodeCard'
import { QueryState } from '../components/QueryState'
import { StorageCardSkeleton } from '../components/StorageCard'
import { StoreCardSkeleton } from '../components/StoreCard'
import {
  Skeleton, SkeletonGroup, SkeletonLine, SkeletonMeterRow, SkeletonTable,
} from '../components/ui/skeleton'

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('Skeleton', () => {
  it('pulses, and stops pulsing for a reader who asked for less motion', () => {
    const { container } = render(<Skeleton className="h-4 w-8" />)
    const el = container.firstElementChild!
    expect(el.className).toContain('animate-pulse')
    // jsdom evaluates no media queries, so the opt-out is checked the same way
    // the rest of this codebase checks it: the utility is on the element.
    expect(el.className).toContain('motion-reduce:animate-none')
  })

  it('takes its colour from a token, never a literal', () => {
    const { container } = render(<Skeleton />)
    const cls = container.firstElementChild!.className
    // --elev is #1B2531 dark and #E7ECF2 light, so one class is right in both
    // themes. A hex here would be right in exactly one of them.
    expect(cls).toContain('bg-elev')
    expect(cls).not.toMatch(/#[0-9a-fA-F]{3,8}/)
  })

  it('is scaffolding, not content: every placeholder is hidden from readers', () => {
    const { container } = render(
      <SkeletonGroup label="Loading apps"><AppCardSkeleton /></SkeletonGroup>)
    const group = screen.getByRole('status')
    expect(group).toHaveAttribute('aria-busy', 'true')
    expect(group).toHaveAttribute('aria-label', 'Loading apps')
    // One announcement for the whole group; nothing inside speaks for itself.
    expect(container.querySelectorAll('[role="status"]')).toHaveLength(1)
    for (const bar of container.querySelectorAll('.animate-pulse')) {
      expect(bar.closest('[aria-hidden="true"]')).not.toBeNull()
    }
  })
})

describe('SkeletonLine', () => {
  it('claims exactly one line box of the font size it is given', () => {
    // 1.45 is the body line-height in styles/tokens.css and it is unitless, so
    // `1.45em` IS one line of whatever text the bar stands in for. jsdom has no
    // layout engine, so this is the only place the arithmetic can be checked.
    const { container } = render(<SkeletonLine className="w-24 text-[13px]" />)
    const cls = container.firstElementChild!.className
    expect(cls).toContain('h-[1.45em]')
    expect(cls).toContain('py-[0.3em]')
    expect(cls).toContain('text-[13px]')
  })
})

describe('SkeletonTable', () => {
  it('draws the shape of the table it stands in for, not a grey block', () => {
    const { container } = render(
      <SkeletonTable rows={3} cols={['w-28', 'w-24', 'w-16']} />)
    expect(container.querySelectorAll('thead th')).toHaveLength(3)
    expect(container.querySelectorAll('tbody tr')).toHaveLength(3)
    expect(container.querySelectorAll('tbody td')).toHaveLength(9)
    // The per-column widths are the shape. Identical bars would read as a grid.
    const widths = [...container.querySelectorAll('tbody tr:first-child td > div')]
      .map((d) => [...d.classList].find((c) => c.startsWith('w-')))
    expect(widths).toEqual(['w-28', 'w-24', 'w-16'])
  })
})

describe('the shaped card placeholders', () => {
  // Each one mirrors a real card in the same file. What is checked here is that
  // it mirrors the card's OUTER box, since that is what decides whether the
  // grid resizes when the data lands. The internal rhythm of the Store card is
  // measured for real in Chromium by e2e/harness (npm run harness), which
  // fails on unequal heights among .rounded-card matches.
  it.each([
    ['app', <AppCardSkeleton key="a" />, 'p-4'],
    ['node', <NodeCardSkeleton key="n" />, 'p-4'],
    ['storage', <StorageCardSkeleton key="s" />, 'p-5'],
    ['store', <StoreCardSkeleton key="t" />, 'p-4'],
  ])('%s: same card box as the card it replaces', (_name, el, padding) => {
    const { container } = render(el)
    const cls = container.firstElementChild!.className
    expect(cls).toContain('rounded-card')
    expect(cls).toContain('border-line-soft')
    expect(cls).toContain('bg-panel')
    expect(cls).toContain(padding)
  })

  it('pins the Store card placeholder to the real card\'s fixed height', () => {
    // StoreCard is h-[240px] by a budget derived in that file. The placeholder
    // has to be the same number or the Store grid jumps when the catalog lands.
    const { container } = render(<StoreCardSkeleton />)
    expect(container.firstElementChild!.className).toContain('h-[240px]')
  })

  it('draws one meter row per real meter row', () => {
    // AppCard shows CPU and RAM; NodeCard adds Disk. A placeholder with the
    // wrong count is a card of the wrong height.
    const meters = (ui: React.ReactNode) =>
      render(ui).container.querySelectorAll('.rounded-full.h-1\\.5, .h-1\\.5.rounded-full').length
    expect(meters(<SkeletonMeterRow />)).toBe(1)
    expect(meters(<AppCardSkeleton />)).toBe(2)
    expect(meters(<NodeCardSkeleton />)).toBe(3)
  })
})

describe('QueryState pending', () => {
  function Subject({ promise }: { promise: Promise<string[]> }) {
    const query = useQuery({ queryKey: ['skeleton-subject'], queryFn: () => promise })
    return (
      <QueryState query={query}
                  loading={<SkeletonGroup label="Loading apps" className="grid">
                    <AppCardSkeleton />
                  </SkeletonGroup>}
                  emptyTitle="No apps yet" emptyNote="">
        {(rows) => <p>{rows.join(', ')}</p>}
      </QueryState>
    )
  }

  it('shows the skeleton while pending and replaces it with the real content', async () => {
    let resolve!: (rows: string[]) => void
    const promise = new Promise<string[]>((r) => { resolve = r })
    const { container } = wrap(<Subject promise={promise} />)

    // Pending: the placeholder, and none of the other three answers.
    expect(screen.getByRole('status')).toHaveAttribute('aria-label', 'Loading apps')
    expect(container.querySelectorAll('.animate-pulse').length).toBeGreaterThan(0)
    expect(screen.queryByText('No apps yet')).not.toBeInTheDocument()

    resolve(['Immich', 'Plex'])

    await waitFor(() => expect(screen.getByText('Immich, Plex')).toBeInTheDocument())
    // Gone, not merely covered: a skeleton left under real content keeps
    // animating forever.
    expect(container.querySelectorAll('.animate-pulse')).toHaveLength(0)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('leaves the ring in place where no shape is known', async () => {
    // QueryState's default is still ui/loading.tsx's indeterminate ring, and it
    // stays that way on purpose: a skeleton can only be drawn where the shape
    // of the content is known up front. Passing `loading` is opt-in per surface.
    const query = { isPending: true, isError: false, data: undefined } as never
    wrap(<QueryState query={query} emptyTitle="none" emptyNote="">{() => <p>never</p>}</QueryState>)
    expect(screen.getByRole('status')).toHaveAttribute('aria-busy', 'true')
    expect(document.querySelectorAll('.animate-pulse')).toHaveLength(0)
  })
})
