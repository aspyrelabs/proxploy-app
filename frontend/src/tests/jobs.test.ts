import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import { applyJob } from '../api/live'
import { jobLabel } from '../api/jobs'

function client() {
  const qc = new QueryClient()
  qc.setQueryData(['jobs', { status: undefined }], [
    { id: 3, kind: 'app.start', status: 'running', progress_pct: 10 },
  ])
  return qc
}

describe('jobLabel', () => {
  // Doc 13: neither half of a job toast is a stored identifier any more. The
  // kind is neutral so no status word can contradict it, and the status is
  // named rather than printed raw.
  it('names both halves rather than printing the stored pair', () => {
    expect(jobLabel({ kind: 'app.start', status: 'succeeded' })).toBe('App Start Done')
    expect(jobLabel({ kind: 'vm.stop', status: 'failed' })).toBe('VM Stop Failed')
    expect(jobLabel({ kind: 'app.restart', status: 'canceled' })).toBe('App Restart Canceled')
    expect(jobLabel({ kind: 'app.install', status: 'queued' })).toBe('App Install Waiting')
  })
})

describe('applyJob', () => {
  it('patches a running job in place without a refetch', () => {
    const qc = client()
    applyJob(qc, { id: 3, kind: 'app.start', status: 'running', progress_pct: 60 })
    const rows = qc.getQueryData(['jobs', { status: undefined }]) as any[]
    expect(rows[0].progress_pct).toBe(60)
  })

  it('fires a toast and invalidates the target on a terminal state', () => {
    const qc = client()
    const spy = vi.spyOn(qc, 'invalidateQueries')
    const toasts: unknown[] = []
    applyJob(qc, { id: 3, kind: 'app.start', status: 'succeeded', target_type: 'app' },
      (t) => toasts.push(t))
    expect(toasts).toEqual([{ kind: 'ok', text: 'App Start Done', jobId: 3 }])
    expect(spy).toHaveBeenCalledWith({ queryKey: ['apps'] })
    expect(spy).toHaveBeenCalledWith({ queryKey: ['cluster', 'activity'] })
  })

  it('uses the error toast kind for a failed job', () => {
    const qc = client()
    const toasts: any[] = []
    applyJob(qc, { id: 3, kind: 'vm.stop', status: 'failed', target_type: 'vm' },
      (t) => toasts.push(t))
    expect(toasts[0].kind).toBe('err')
  })

  it('does not toast for non-terminal transitions', () => {
    const qc = client()
    const toasts: unknown[] = []
    applyJob(qc, { id: 3, kind: 'app.start', status: 'running' }, (t) => toasts.push(t))
    expect(toasts).toEqual([])
  })

  it('does not invalidate anything for a non-terminal delta', () => {
    const qc = client()
    const spy = vi.spyOn(qc, 'invalidateQueries')
    applyJob(qc, { id: 3, kind: 'app.start', status: 'running', progress_pct: 60 })
    expect(spy).not.toHaveBeenCalled()
  })

  it('invalidates the resource cache from the delta alone, no cache seeded', () => {
    // Regression guard: the backend's SSE `job` payload carries target_type
    // directly (doc 05 §Streaming 4 / JobBackend._publish), invalidation
    // must not depend on any job row already sitting in the cache.
    const qc = new QueryClient()
    const spy = vi.spyOn(qc, 'invalidateQueries')
    applyJob(qc, { id: 9, kind: 'vm.start', status: 'succeeded', target_type: 'vm' })
    expect(spy).toHaveBeenCalledWith({ queryKey: ['vms'] })
    expect(spy).not.toHaveBeenCalledWith({ queryKey: ['apps'] })
  })

  it('patches the single-job detail cache (object shape), not just list caches', () => {
    const qc = new QueryClient()
    qc.setQueryData(['jobs', 3], { id: 3, kind: 'app.start', status: 'running', progress_pct: 10 })
    applyJob(qc, { id: 3, kind: 'app.start', status: 'running', progress_pct: 70 })
    expect((qc.getQueryData(['jobs', 3]) as any).progress_pct).toBe(70)
  })

  it('toasts once for a terminal delta, not again for a duplicate delivery', () => {
    const qc = client()
    const toasts: unknown[] = []
    const delta = { id: 3, kind: 'app.start', status: 'succeeded', target_type: 'app' } as const
    applyJob(qc, delta, (t) => toasts.push(t))
    applyJob(qc, delta, (t) => toasts.push(t))
    expect(toasts).toHaveLength(1)
  })
})

describe('applyJob, the catalog refresh', () => {
  it('invalidates the catalog when the refresh job finishes', () => {
    // catalog.refresh is enqueued with no target_type, so RESOURCE_KEY cannot
    // reach it and nothing dropped the grid's cache on completion. The only
    // ['catalog'] invalidation happened when the job was enqueued, and the
    // refetch that followed re-armed a 5 minute staleTime with the rows the
    // refresh was about to replace.
    const qc = new QueryClient()
    const spy = vi.spyOn(qc, 'invalidateQueries')
    applyJob(qc, { id: 9, kind: 'catalog.refresh', status: 'succeeded' })
    expect(spy).toHaveBeenCalledWith({ queryKey: ['catalog'] })
  })

  it('leaves the catalog alone for unrelated jobs', () => {
    const qc = new QueryClient()
    const spy = vi.spyOn(qc, 'invalidateQueries')
    applyJob(qc, { id: 10, kind: 'app.start', status: 'succeeded', target_type: 'app' })
    expect(spy).not.toHaveBeenCalledWith({ queryKey: ['catalog'] })
  })
})
