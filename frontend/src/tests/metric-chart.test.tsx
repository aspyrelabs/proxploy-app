import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const requested: string[] = []

vi.mock('../api/client', () => ({
  api: vi.fn((path: string) => {
    requested.push(path)
    return Promise.resolve({ target: 'host:1', metric: 'cpu_pct',
                             resolution: '5m', ts: [1, 2], value: [0.1, 0.14] })
  }),
  ApiError: class extends Error {},
}))

import { MetricChart, RANGES } from '../components/charts/MetricChart'

const wrap = (props: Partial<React.ComponentProps<typeof MetricChart>> = {}) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MetricChart target="host:1" metric="cpu_pct" unit="percent" label="CPU" {...props} />
    </QueryClientProvider>,
  )
}

/** Hours between from= and to= in a /metrics/query URL. */
function spanHours(url: string): number {
  const from = new Date(new URL(url, 'http://x').searchParams.get('from')!)
  const to = new Date(new URL(url, 'http://x').searchParams.get('to')!)
  return (to.getTime() - from.getTime()) / 3600_000
}

beforeEach(() => { requested.length = 0 })

describe('MetricChart', () => {
  it('offers 30m, 1h, 12h and 24h and nothing shorter', () => {
    // The poller samples every 30s, so a 5m window is a handful of points
    // pretending to be a trend.
    wrap()
    expect(RANGES.map((r) => r.label)).toEqual(['30m', '1h', '12h', '24h'])
    for (const label of ['30m', '1h', '12h', '24h']) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument()
    }
    expect(screen.queryByRole('button', { name: '5m' })).not.toBeInTheDocument()
  })

  it('starts on 1h and says so', () => {
    wrap()
    expect(screen.getByRole('button', { name: '1h' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('requests the window the picker names', async () => {
    wrap()
    await waitFor(() => expect(requested.length).toBeGreaterThan(0))
    expect(spanHours(requested[0])).toBeCloseTo(1, 1)

    fireEvent.click(screen.getByRole('button', { name: '24h' }))
    await waitFor(() => expect(requested.length).toBeGreaterThan(1))
    expect(spanHours(requested[requested.length - 1])).toBeCloseTo(24, 1)
  })

  it('asks for half an hour, not thirty hours, on 30m', async () => {
    // 30m is the one range expressed as a fraction, so it is the one that
    // would silently become 30 hours if hours/minutes were ever confused.
    wrap()
    fireEvent.click(screen.getByRole('button', { name: '30m' }))
    await waitFor(() => expect(requested.length).toBeGreaterThan(1))
    expect(spanHours(requested[requested.length - 1])).toBeCloseTo(0.5, 2)
  })

  it('each chart keeps its own range', () => {
    // CPU on 30m and storage on 24h is the normal case, not a bug.
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <MetricChart target="host:1" metric="cpu_pct" unit="percent" label="CPU" />
        <MetricChart target="host:1" metric="disk_pct" unit="percent" label="Storage" />
      </QueryClientProvider>,
    )
    const cpu = screen.getByRole('group', { name: 'CPU time range' })
    const storage = screen.getByRole('group', { name: 'Storage time range' })
    fireEvent.click(within(cpu).getByRole('button', { name: '30m' }))
    expect(within(cpu).getByRole('button', { name: '30m' })).toHaveAttribute('aria-pressed', 'true')
    expect(within(storage).getByRole('button', { name: '1h' })).toHaveAttribute('aria-pressed', 'true')
  })
})
