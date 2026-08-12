/** lib/notificationMerge.ts is the other half of the dedupe story: given
 *  GET /jobs (server truth, survives a reload) and the client-side store
 *  (notify.*() actions plus LiveProvider's SSE pushes, gone on reload), it
 *  produces the one list BellPopover renders. A job present in both --
 *  delivered once over SSE, then again the next time /jobs is polled -- must
 *  come out once, not twice. That is the whole point of this file.
 */
import { describe, expect, it } from 'vitest'
import { mergeNotifications } from '../lib/notificationMerge'
import type { TrayItem } from '../lib/notificationMerge'
import type { StoreNotification } from '../lib/notificationStore'
import type { JobRow } from '../api/jobs'

function job(overrides: Partial<JobRow> = {}): JobRow {
  return {
    id: 1, kind: 'app.start', status: 'succeeded', target_type: 'app', target_id: 1,
    params: null, result: null, error: null, progress_pct: null,
    requested_by: null, schedule_id: null, started_at: '2026-08-12T08:00:00Z',
    finished_at: '2026-08-12T08:01:00Z', created_at: '2026-08-12T08:00:00Z',
    ...overrides,
  }
}

function storeItem(overrides: Partial<StoreNotification> = {}): StoreNotification {
  return { id: 'action:1', severity: 'info', title: 'x', createdAt: 1000, ...overrides }
}

const toJobItem = (j: JobRow): TrayItem => ({
  id: `job:${j.id}`, severity: 'success', title: `${j.kind} #${j.id}`,
  jobId: j.id, timestamp: new Date(j.created_at).getTime(),
})

describe('mergeNotifications', () => {
  it('a job present in both the SSE-fed store and GET /jobs appears once, not twice', () => {
    const jobs = [job({ id: 42 })]
    const store = [storeItem({ id: 'job:42', jobId: 42, title: 'app.start succeeded' })]
    const merged = mergeNotifications(jobs, store, toJobItem)
    const forThatJob = merged.filter((m) => m.jobId === 42)
    expect(forThatJob).toHaveLength(1)
    // The /jobs row wins: it is the server's own record, richer and more
    // current than the copy that arrived earlier over SSE.
    expect(forThatJob[0].id).toBe('job:42')
    expect(forThatJob[0].title).toBe('app.start #42')
  })

  it('a store item whose job has not appeared in /jobs yet is kept, not dropped', () => {
    const merged = mergeNotifications([], [storeItem({ id: 'job:99', jobId: 99 })], toJobItem)
    expect(merged).toHaveLength(1)
    expect(merged[0].jobId).toBe(99)
  })

  it('action and alert notifications (no jobId) always pass through untouched', () => {
    const store = [storeItem({ id: 'action:1', title: 'Saved.' }), storeItem({ id: 'alert:1', title: 'host-02 CPU high' })]
    const merged = mergeNotifications([job({ id: 1 })], store, toJobItem)
    expect(merged.map((m) => m.title)).toEqual(
      expect.arrayContaining(['Saved.', 'host-02 CPU high', 'app.start #1']),
    )
    expect(merged).toHaveLength(3)
  })

  it('two different jobs never collide even though both dedupe against the same store', () => {
    const jobs = [job({ id: 1 }), job({ id: 2, kind: 'vm.stop' })]
    const store = [storeItem({ id: 'job:1', jobId: 1 }), storeItem({ id: 'job:2', jobId: 2 })]
    const merged = mergeNotifications(jobs, store, toJobItem)
    expect(merged).toHaveLength(2)
  })

  it('sorts newest first by timestamp', () => {
    const store = [storeItem({ id: 'a', createdAt: 500 }), storeItem({ id: 'b', createdAt: 2000 })]
    const merged = mergeNotifications([], store, toJobItem)
    expect(merged.map((m) => m.id)).toEqual(['b', 'a'])
  })
})
