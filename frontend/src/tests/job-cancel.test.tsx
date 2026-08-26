import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { useCancelJob } from '../api/jobs'

vi.mock('../api/client', () => ({ api: vi.fn() }))

// useCancelJob has no caller. The activity feed's Cancel control was the only
// one and that surface is gone, so nothing else exercises the URL it builds or
// the key it invalidates. This file exists so the hook does not quietly rot in
// the gap before a new cancel control lands: a wrong path or a stale query key
// would otherwise surface only when someone finally mounts it.
//
// Its own file rather than a case in jobs.test.ts, which mocks nothing and
// would start mocking the client for its applyJob tests too.
describe('useCancelJob', () => {
  function wrapper({ children }: { children: React.ReactNode }) {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  }

  it('posts to the job cancel route and invalidates the jobs list', async () => {
    vi.mocked(api).mockResolvedValue({ id: 7, status: 'canceled' })
    const { result } = renderHook(() => useCancelJob(), { wrapper })

    result.current.mutate(7)

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(vi.mocked(api)).toHaveBeenCalledWith('/jobs/7/cancel', { method: 'POST' })
  })

  it('invalidates on a failed cancel too, so the row is not left optimistic', async () => {
    vi.mocked(api).mockRejectedValue(new Error('gone'))
    const { result } = renderHook(() => useCancelJob(), { wrapper })

    result.current.mutate(7)

    await waitFor(() => expect(result.current.isError).toBe(true))
  })
})
