import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import {
  alertToastSeverity, applyAlert, applyJob, applyMetrics, applyResource, jobToastSeverity,
} from '../api/live'

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

describe('applyResource, Phase 6 resource types', () => {
  it('routes storage/backup/network events to their own keys, never to vms', () => {
    const qc = client()
    const spy = vi.spyOn(qc, 'invalidateQueries')
    applyResource(qc, { type: 'storage', id: 1, change: 'content' })
    applyResource(qc, { type: 'backup', id: 1, change: 'list' })
    applyResource(qc, { type: 'network', id: 1, change: 'list' })
    expect(spy).toHaveBeenCalledWith({ queryKey: ['storage'] })
    expect(spy).toHaveBeenCalledWith({ queryKey: ['backups'] })
    expect(spy).toHaveBeenCalledWith({ queryKey: ['network'] })
    // the whole point: the old else-branch sent all three here
    expect(spy).not.toHaveBeenCalledWith({ queryKey: ['vms'] })
  })

  it('ignores an unknown type instead of guessing a cache to invalidate', () => {
    const qc = client()
    const spy = vi.spyOn(qc, 'invalidateQueries')
    applyResource(qc, { type: 'wormhole', id: 1, change: 'list' })
    expect(spy).not.toHaveBeenCalled()
  })

  it('never runs the id-keyed status patch for a non-guest type', () => {
    // A storage event's `id` is a HOST id, and ['storage'] rows have no `id`
    // at all, patching by id there would silently corrupt whichever row
    // happened to collide.
    const qc = client()
    qc.setQueryData(['storage'], [{ host_id: 7, storage: 'local', status: 'available' }])
    applyResource(qc, { type: 'storage', id: 7, change: 'status', status: 'inactive' })
    expect((qc.getQueryData(['storage']) as any)[0].status).toBe('available')
  })
})

describe('applyJob, Phase 6 target types', () => {
  const terminal = (target_type: string) =>
    ({ id: 1, kind: `${target_type}.thing`, status: 'succeeded', target_type })

  it('invalidates the matching resource cache for storage/backup/network jobs', () => {
    for (const [target, key] of [['storage', 'storage'], ['backup', 'backups'],
                                 ['network', 'network']] as const) {
      const qc = new QueryClient()
      const spy = vi.spyOn(qc, 'invalidateQueries')
      applyJob(qc, terminal(target))
      expect(spy).toHaveBeenCalledWith({ queryKey: [key] })
      expect(spy).toHaveBeenCalledWith({ queryKey: ['jobs'] })
    }
  })

  it('still invalidates vms for a vm job, which prefix-covers the snapshots key', () => {
    const qc = new QueryClient()
    const spy = vi.spyOn(qc, 'invalidateQueries')
    applyJob(qc, terminal('vm'))
    expect(spy).toHaveBeenCalledWith({ queryKey: ['vms'] })
  })
})

describe('applyAlert', () => {
  it('invalidates the firing-alerts query and the activity feed', () => {
    const qc = new QueryClient()
    const spy = vi.spyOn(qc, 'invalidateQueries')
    applyAlert(qc, { id: 1, state: 'firing', severity: 'warning', message: 'x' })
    const keys = spy.mock.calls.map(c => JSON.stringify((c[0] as any).queryKey))
    expect(keys).toContain(JSON.stringify(['alerts', 'firing']))
    expect(keys).toContain(JSON.stringify(['cluster', 'activity']))
  })

  it('toasts a firing alert at warning and above', () => {
    const qc = new QueryClient()
    const seen: any[] = []
    applyAlert(qc, { id: 1, state: 'firing', severity: 'warning', message: 'hot' },
               (t) => seen.push(t))
    expect(seen).toEqual([{ kind: 'err', text: 'hot', alertId: 1 }])
  })

  it('stays quiet for an info-severity alert (doc 06: warning+)', () => {
    const qc = new QueryClient()
    const seen: any[] = []
    applyAlert(qc, { id: 1, state: 'firing', severity: 'info', message: 'meh' },
               (t) => seen.push(t))
    expect(seen).toEqual([])
  })

  it('toasts a resolution as good news, whatever the severity', () => {
    const qc = new QueryClient()
    const seen: any[] = []
    applyAlert(qc, { id: 1, state: 'resolved', severity: 'critical',
                     message: 'Resolved: host-02 CPU' }, (t) => seen.push(t))
    expect(seen).toEqual([{ kind: 'ok', text: 'Resolved: host-02 CPU', alertId: 1 }])
  })
})

// LiveProvider's SSE handlers render a NotificationCard via toast.custom
// rather than plain toast.success/toast.error; these two pure functions are
// the mapping from an applyJob/applyAlert toast payload to the card's
// severity, kept here (next to the payload shapes they read) so the mapping
// itself is unit-testable without standing up an EventSource + Toaster.
describe('jobToastSeverity', () => {
  it('maps a job err event to the destructive card', () => {
    expect(jobToastSeverity('err')).toBe('destructive')
  })
  it('maps a job ok event to the success card', () => {
    expect(jobToastSeverity('ok')).toBe('success')
  })
  it('maps anything else (queued/running/progress) to the info card', () => {
    expect(jobToastSeverity('info')).toBe('info')
  })
})

describe('alertToastSeverity', () => {
  it('maps a resolution to success, whatever the payload severity was', () => {
    expect(alertToastSeverity('ok', 'critical')).toBe('success')
    expect(alertToastSeverity('ok', 'warning')).toBe('success')
  })
  it('maps a firing critical-severity alert to destructive', () => {
    expect(alertToastSeverity('err', 'critical')).toBe('destructive')
  })
  it('maps a firing warning-severity alert to warning, not destructive', () => {
    expect(alertToastSeverity('err', 'warning')).toBe('warning')
  })
})
