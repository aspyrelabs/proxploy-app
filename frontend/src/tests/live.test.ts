import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import { applyMetrics, applyResource } from '../api/live'

function client() {
  const qc = new QueryClient()
  qc.setQueryData(['cluster', 'nodes'], [
    { host_id: 1, cpu_pct: 10, mem_pct: 20 },
  ])
  qc.setQueryData(['apps', { host: undefined, q: undefined }], [
    { id: 5, status: 'stopped', cpu_pct: 0 },
  ])
  qc.setQueryData(['apps', 5], { id: 5, status: 'stopped', cpu_pct: 0 })
  qc.setQueryData(['vms', {}], [{ id: 7, status: 'running', cpu_pct: 3 }])
  return qc
}

describe('applyMetrics', () => {
  it('patches node and guest cpu/mem in place', () => {
    const qc = client()
    applyMetrics(qc, { targets: [
      { t: 'host', id: 1, cpu_pct: 55, mem_pct: 66 },
      { t: 'app', id: 5, cpu_pct: 12, mem_pct: 40 },
      { t: 'vm', id: 7, cpu_pct: 31, mem_pct: 75 },
    ] })
    expect((qc.getQueryData(['cluster', 'nodes']) as any)[0]).toMatchObject({ cpu_pct: 55, mem_pct: 66 })
    expect((qc.getQueryData(['apps', { host: undefined, q: undefined }]) as any)[0].cpu_pct).toBe(12)
    expect((qc.getQueryData(['vms', {}]) as any)[0].cpu_pct).toBe(31)
  })
})

describe('applyResource', () => {
  it('patches status deltas into list and detail caches', () => {
    const qc = client()
    applyResource(qc, { type: 'app', id: 5, change: 'status', status: 'running' })
    expect((qc.getQueryData(['apps', { host: undefined, q: undefined }]) as any)[0].status).toBe('running')
    expect((qc.getQueryData(['apps', 5]) as any).status).toBe('running')
  })
  it('leaves unrelated rows untouched', () => {
    const qc = client()
    applyResource(qc, { type: 'vm', id: 999, change: 'status', status: 'paused' })
    expect((qc.getQueryData(['vms', {}]) as any)[0].status).toBe('running')
  })
})
