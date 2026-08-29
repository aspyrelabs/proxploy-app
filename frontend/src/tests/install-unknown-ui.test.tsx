/**
 * The UI half of the UNKNOWN install state.
 *
 * The backend work made an interrupted install honest. The frontend did not
 * know the status existed, and the failure mode was not that it said the wrong
 * thing: it was that it said nothing. `unknown` was missing from TERMINAL, so
 * the transcript polled forever, no toast fired, and neither ['jobs'] nor
 * ['apps'] was ever invalidated. Then the operator pressed Install again and
 * the new 409 made the button do literally nothing, because the mutation had
 * no onError and there was no global handler either.
 *
 * These pin the pieces that turn that into something an operator can read.
 */
import { describe, expect, it } from 'vitest'

import { TERMINAL, jobLabel } from '../api/jobs'
import {
  JOB_STATUS_LABEL, jobUnknownMessage, statusLabel,
} from '../lib/activityDisplay'

describe('unknown is a finished job', () => {
  it('is terminal, so nothing waits on it forever', () => {
    // The single most consequential line. useJob, MigrateDialog and store.tsx
    // all stop polling on TERMINAL, and applyJob returns early before its
    // toast and its invalidations when a status is not in it.
    expect(TERMINAL).toContain('unknown')
  })

  it('has a label of its own rather than rendering the raw string', () => {
    expect(statusLabel('unknown')).toBe('Checking')
    expect(statusLabel('unknown')).not.toBe('unknown')
  })

  it('does not share a word with a missing status', () => {
    // Two meanings, one string, in the function every surface routes through.
    expect(statusLabel(null)).toBe('No status')
    expect(statusLabel(null)).not.toBe(statusLabel('unknown'))
  })

  it('names every job status, so a new one cannot render raw', () => {
    // Record<JobStatus, string>: adding a status to the union without a label
    // is a compile error now. This asserts the runtime half of that.
    for (const s of TERMINAL) {
      expect(JOB_STATUS_LABEL[s], `no label for ${s}`).toBeTruthy()
    }
  })
})

describe('what the operator is told', () => {
  it('says interrupted and checking, and names the host', () => {
    expect(jobUnknownMessage('node1'))
      .toBe('Interrupted, checking what happened on node1.')
  })

  it('never says failed, which would be the claim the backend work removed', () => {
    const msg = jobUnknownMessage('node1').toLowerCase()
    expect(msg).not.toContain('failed')
    expect(msg).not.toContain('did not')
  })

  it('still reads as a sentence when the host is not known', () => {
    expect(jobUnknownMessage(null)).toContain('the host')
    expect(jobUnknownMessage(null)).not.toContain('null')
  })

  it('gives the install and its check their own phrases', () => {
    // "App Install Checking" was what the composed form produced, which reads
    // as a status on the install rather than what happened to it.
    expect(jobLabel({ kind: 'app.install', status: 'unknown' }))
      .toBe('Install Interrupted')
    expect(jobLabel({ kind: 'app.install.reconcile', status: 'running' }))
      .toBe('Checking the Node')
    expect(jobLabel({ kind: 'app.install.reconcile', status: 'succeeded' }))
      .toBe('Install Resolved')
  })
})
