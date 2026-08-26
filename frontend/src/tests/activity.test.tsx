import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../lib/notify', () => ({ notify: { error: vi.fn(), success: vi.fn(), info: vi.fn(), warning: vi.fn() } }))

const { ApiError } = vi.hoisted(() => ({
  ApiError: class extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) { super(`API ${status}`); this.status = status; this.body = body }
  },
}))

let jobEventsError = false

vi.mock('../api/client', () => ({
  ApiError,
  api: vi.fn((path: string) => {
    if (path.startsWith('/jobs/12/events')) {
      if (jobEventsError) return Promise.reject(new Error('boom'))
      return Promise.resolve([
        { seq: 1, ts: '2026-07-29T09:00:00Z', stream: 'stdout', message: 'starting CT 150' },
        { seq: 2, ts: '2026-07-29T09:00:04Z', stream: 'status', message: 'succeeded: ok' },
      ])
    }
    if (path === '/entitlements') {
      return Promise.resolve({ tier: 'builtin', features: {}, grace: null, clock_skew: false })
    }
    return Promise.resolve(null)
  }),
}))

import { JobLog } from '../components/JobLog'
import { TerminalPanel } from '../components/TerminalPanel'
import { FakeEventSource, installFakeEventSource } from './fakeEventSource'

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('TerminalPanel', () => {
  it('renders each line and tags the stream', () => {
    wrap(<TerminalPanel lines={[
      { stream: 'stdout', message: 'starting CT 150' },
      { stream: 'stderr', message: 'warning: low disk' },
    ]} />)
    expect(screen.getByText('starting CT 150')).toBeInTheDocument()
    expect(screen.getByText('warning: low disk')).toBeInTheDocument()
  })

  it('shows an honest empty state instead of a blank box', () => {
    wrap(<TerminalPanel lines={[]} />)
    expect(screen.getByText(/no output yet/i)).toBeInTheDocument()
  })
})

describe('JobLog', () => {
  beforeEach(() => { jobEventsError = false })

  it('renders the archived transcript', async () => {
    wrap(<JobLog jobId={12} />)
    expect(await screen.findByText('starting CT 150')).toBeInTheDocument()
  })

  it('says the transcript could not be loaded rather than showing "no output yet"', async () => {
    // TerminalPanel stays dark by design (doc 06 §c) so this isn't a
    // QueryState card, it's a distinct line inside the same terminal box,
    // but it still must not look like a job that legitimately produced
    // nothing.
    jobEventsError = true
    wrap(<JobLog jobId={12} />)
    expect(await screen.findByText(/could not load this job.s transcript/i)).toBeInTheDocument()
    expect(screen.queryByText(/no output yet/i)).not.toBeInTheDocument()
  })

  // The enabling half of the determinate ring: JobLog owns the one
  // EventSource for a job, so a caller that wants live progress has to get
  // it through JobLog rather than opening a second connection.
  it('calls onProgress when the stream emits a progress frame', async () => {
    const restore = installFakeEventSource()
    const onProgress = vi.fn()
    wrap(<JobLog jobId={12} onProgress={onProgress} />)
    await screen.findByText('starting CT 150')

    FakeEventSource.last.emit('progress', { pct: 55 })

    expect(onProgress).toHaveBeenCalledWith(55)
    restore()
  })

  it('does not call onProgress for a line or status frame', async () => {
    const restore = installFakeEventSource()
    const onProgress = vi.fn()
    wrap(<JobLog jobId={12} onProgress={onProgress} />)
    await screen.findByText('starting CT 150')

    FakeEventSource.last.emit('line', { stream: 'stdout', message: 'hi' })
    FakeEventSource.last.emit('status', { status: 'succeeded' })

    expect(onProgress).not.toHaveBeenCalled()
    restore()
  })
})
