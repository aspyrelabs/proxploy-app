import { describe, expect, it } from 'vitest'
import { ACTION_LABEL, actionLabel, statusLabel } from '../components/activityDisplay'

describe('actionLabel', () => {
  it('names a mapped identifier in words', () => {
    expect(actionLabel('app.uninstall')).toBe('App Uninstall')
    expect(actionLabel('apps.adopt')).toBe('App Import')
  })

  // The word "reaped" means nothing outside the codebase, and the label has to
  // stay DISTINCT from both real removals: an uninstall is Proxploy destroying
  // the container, a forget is Proxploy dropping its own row for a container
  // that is still running, a reap is Proxploy cleaning up after a container
  // somebody else already destroyed. Collapsing them would hide the one thing
  // the user cares about, whether their container still exists.
  it('separates removing our record from destroying the container', () => {
    expect(actionLabel('app.reaped')).toBe('App Vanished')
    expect(actionLabel('app.forget')).toBe('App Unlink')
    expect(actionLabel('app.uninstall')).toBe('App Uninstall')
    expect(actionLabel('app.reaped')).not.toBe(actionLabel('app.uninstall'))
    expect(actionLabel('app.reaped')).not.toBe(actionLabel('app.forget'))
  })

  // Backend actions get added without this map being updated; a new one must
  // still read as words, never as an empty title.
  it('derives a readable name for an identifier it has never seen', () => {
    expect(actionLabel('widget.self_destruct')).toBe('Widget Self Destruct')
    expect(actionLabel('vm.teleport')).toBe('VM Teleport')
    expect(actionLabel('')).toBe('Unknown')
    expect(actionLabel(null)).toBe('Unknown')
  })

  // The point of a neutral label: ONE string is correct in every state the row
  // can be in, so nothing has to be rephrased per outcome and nothing can
  // contradict the status printed beside it.
  it('reads correctly waiting, running, done and failed', () => {
    expect(actionLabel('app.install', 'queued')).toBe('App Install')
    expect(actionLabel('app.install', 'running')).toBe('App Install')
    expect(actionLabel('app.install', 'succeeded')).toBe('App Install')
    expect(actionLabel('app.install', 'failed')).toBe('App Install Failed')
    // The status word each of those sits next to, from the same file.
    expect(statusLabel('queued')).toBe('Waiting')
    expect(statusLabel('running')).toBe('Running')
    expect(statusLabel('succeeded')).toBe('Done')
    expect(statusLabel('failed')).toBe('Failed')
  })

  // Doc 13's structural fix: a refusal is PREFIXED, so the first word of the
  // title says nothing happened, instead of the name of the destructive thing
  // that did not happen.
  it('prefixes a denied row with Blocked', () => {
    expect(actionLabel('host.remove', 'denied')).toBe('Blocked Host Disconnect')
    expect(actionLabel('vm.delete', 'denied')).toBe('Blocked VM Delete')
    // Unmapped identifiers get the prefix too: it is one render rule, not a
    // per-action map, so an action added backend-side tomorrow is covered.
    expect(actionLabel('widget.self_destruct', 'denied')).toBe('Blocked Widget Self Destruct')
    // A denied row carrying a job_id (there should be none: a refusal never
    // enqueues) must still read as blocked, not as requested.
    expect(actionLabel('app.install', 'denied', true)).toBe('Blocked App Install')

    // One rule, not a list of special cases: no mapped label survives a
    // non-success result unchanged, whichever action it belongs to.
    for (const raw of Object.keys(ACTION_LABEL)) {
      for (const bad of ['denied', 'error', 'failed', 'canceled', 'interrupted']) {
        expect(actionLabel(raw, bad), `${raw} @ ${bad}`).not.toBe(ACTION_LABEL[raw])
      }
    }
  })

  it('appends the verdict for the other ways a row can end badly', () => {
    expect(actionLabel('host.remove', 'error')).toBe('Host Disconnect Failed')
    expect(actionLabel('app.uninstall', 'failed')).toBe('App Uninstall Failed')
    expect(actionLabel('app.install', 'canceled')).toBe('App Install Canceled')
    expect(actionLabel('backup.run', 'interrupted')).toBe('Backup Run Interrupted')
  })

  it('states the plain action when there is nothing to add', () => {
    expect(actionLabel('vm.delete', 'ok')).toBe('VM Delete')
    expect(actionLabel('vm.delete')).toBe('VM Delete')
    expect(actionLabel('vm.delete', null)).toBe('VM Delete')
    // A status this file has never heard of adds no verdict rather than
    // guessing one. The label is already true without it.
    expect(actionLabel('vm.delete', 'timed_out')).toBe('VM Delete')
  })

  // The scheduler's automatic give-up (jobs/scheduler.py::_disable, the only
  // writer of schedule.disable) must not read like a person's decision; a
  // person switching a schedule off is logged as schedule.update.
  it('says the scheduler disabled a schedule, not that somebody did', () => {
    expect(actionLabel('schedule.disable')).toBe('Schedule Auto-Disable')
    expect(actionLabel('schedule.disable')).not.toBe(actionLabel('schedule.update'))
  })

  // A failed READ of the guest's NIC config is not an attempted write.
  // api/network.py:112 writes this identifier, and only on the read half.
  it('keeps a failed guest network read out of the configuration wording', () => {
    expect(actionLabel('network.guest_config_read')).toBe('Guest Network Read')
    expect(actionLabel('network.guest_config_read', 'error'))
      .toBe('Guest Network Read Failed')
    expect(actionLabel('network.guest_config_read'))
      .not.toBe(actionLabel('network.guest_config'))
  })

  it('never renders a mapped label as blank', () => {
    for (const [raw, label] of Object.entries(ACTION_LABEL)) {
      expect(label.trim(), raw).not.toBe('')
    }
  })

  // Doc 13 rule 1. The API Key pair is the stated exception, and
  // Guest Network Read is api/network.py's read-half identifier, which doc 13
  // does not list (its item 7 assumes the identifier no longer exists).
  it('keeps every label to two words bar the documented exceptions', () => {
    const allowed = new Set(['apikey.create', 'apikey.revoke', 'network.guest_config_read'])
    for (const [raw, label] of Object.entries(ACTION_LABEL)) {
      if (allowed.has(raw)) continue
      expect(label.split(' ').length, `${raw}: ${label}`).toBe(2)
    }
  })
})

// Both lookups are plain object literals, so an identifier that collides with
// something on Object.prototype must not be answered with that.
it('does not answer prototype keys out of either lookup table', () => {
  // 'ToString' rather than 'To String' is right: derive() splits on . _ - :
  // and there is no separator here. What matters is that neither call answers
  // with the function living on Object.prototype.
  expect(actionLabel('toString')).toBe('ToString')
  expect(actionLabel('constructor')).toBe('Constructor')
  expect(actionLabel('vm.delete', 'toString')).toBe('VM Delete')
  expect(statusLabel('constructor')).toBe('constructor')
})

// Renaming a label is no longer two jobs. The failure title is built from the
// same map as the success title, so metrics.maintain cannot go on failing as
// "Metrics Maintain Failed" after its label was renamed.
it('keeps a renamed label consistent however the job ended', () => {
  expect(actionLabel('metrics.maintain', 'succeeded')).toBe('Usage Cleanup')
  expect(actionLabel('metrics.maintain', 'failed')).toBe('Usage Cleanup Failed')
  expect(actionLabel('metrics.maintain', 'running')).toBe('Usage Cleanup')
  expect(actionLabel('metrics.maintain', 'denied')).toBe('Blocked Usage Cleanup')
})

describe('statusLabel', () => {
  it('names every status doc 13 names', () => {
    expect(statusLabel('queued')).toBe('Waiting')
    expect(statusLabel('running')).toBe('Running')
    expect(statusLabel('succeeded')).toBe('Done')
    expect(statusLabel('ok')).toBe('Complete')
    expect(statusLabel('resolved')).toBe('Cleared')
    expect(statusLabel('canceled')).toBe('Canceled')
    expect(statusLabel('interrupted')).toBe('Interrupted')
    expect(statusLabel('failed')).toBe('Failed')
    expect(statusLabel('unreachable')).toBe('Host Unreachable')
  })

  // Doc 13 gives no word for these two; it spends its denied row on the
  // "Blocked" prefix instead. Passing the raw value through beats inventing
  // one here, and this pins that decision so it is noticed, not inherited.
  it('passes through a status the doc does not name', () => {
    expect(statusLabel('denied')).toBe('denied')
    expect(statusLabel('error')).toBe('error')
    expect(statusLabel('stopped')).toBe('stopped')
    expect(statusLabel(null)).toBe('unknown')
  })
})

// enqueue_and_audit writes its audit row the moment the job is QUEUED, with
// result ok, because what succeeded is the REQUEST. The activity feed hides
// these rows (api/cluster.py filters on job_id, since the job row beside them
// carries the real outcome), so the audit log is the only place that has to
// say the row records an asking rather than a finishing.
describe('job-backed audit rows', () => {
  it('says a job was requested, not that it finished', () => {
    expect(actionLabel('app.install', 'ok', true)).toBe('App Install Requested')
    expect(actionLabel('backup.run', 'ok', true)).toBe('Backup Run Requested')
  })

  it('leaves rows with no job alone', () => {
    expect(actionLabel('app.install', 'denied', false)).toBe('Blocked App Install')
    expect(actionLabel('app.install', 'ok', false)).toBe('App Install')
    expect(actionLabel('app.install', 'ok')).toBe('App Install')
  })

  it('does not let a job-backed row outrank a failure', () => {
    // If a job-linked row ever carries a failing result, the failure wins:
    // "Requested" would be the less alarming of the two readings.
    expect(actionLabel('app.install', 'failed', true)).toBe('App Install Failed')
  })
})
