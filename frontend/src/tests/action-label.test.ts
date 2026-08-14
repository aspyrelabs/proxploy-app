import { describe, expect, it } from 'vitest'
import { ACTION_LABEL, actionLabel } from '../components/activityDisplay'

describe('actionLabel', () => {
  it('names a mapped identifier in words', () => {
    expect(actionLabel('app.uninstall')).toBe('App Uninstalled')
    expect(actionLabel('apps.adopt')).toBe('Apps Imported')
  })

  // The word "reaped" means nothing outside the codebase. "App Removed" also
  // has to stay DISTINCT from "App Uninstalled": an uninstall is Proxploy
  // destroying the container, a removal is Proxploy dropping its own row for a
  // container someone else already destroyed. Collapsing them would make the
  // audit log claim a destroy that never happened, so this asserts they differ
  // rather than just asserting each string.
  it('separates removing our record from destroying the container', () => {
    expect(actionLabel('app.reaped')).toBe('App Removed')
    expect(actionLabel('app.forget')).toBe('App Forgotten')
    expect(actionLabel('app.uninstall')).toBe('App Uninstalled')
    expect(actionLabel('app.reaped')).not.toBe(actionLabel('app.uninstall'))
  })

  // Backend actions get added without this map being updated; a new one must
  // still read as words, never as an empty title.
  it('derives a readable name for an identifier it has never seen', () => {
    expect(actionLabel('widget.self_destruct')).toBe('Widget Self Destruct')
    expect(actionLabel('vm.teleport')).toBe('VM Teleport')
    expect(actionLabel('')).toBe('Unknown')
    expect(actionLabel(null)).toBe('Unknown')
  })

  // The whole point of the second argument. A row's title is what people
  // scan, and every label in the map is an assertion of a completed fact, so
  // a refused or blown-up action wearing one makes the audit log claim
  // something that never happened.
  it('never titles a denied or failed row with its success label', () => {
    expect(actionLabel('vm.delete', 'denied')).toBe('VM Delete Denied')
    // "App Migration Denied", not "App Migrate Denied": app.migrate now has an
    // ATTEMPT override, which is what makes the same phrase read correctly as
    // both "... Denied" and "... Requested".
    expect(actionLabel('app.migrate', 'denied')).toBe('App Migration Denied')
    expect(actionLabel('host.remove', 'error')).toBe('Host Remove Failed')
    expect(actionLabel('app.uninstall', 'failed')).toBe('App Uninstall Failed')
    expect(actionLabel('app.install', 'canceled')).toBe('App Install Canceled')
    expect(actionLabel('backup.run', 'interrupted')).toBe('Backup Run Interrupted')

    // One rule, not a list of special cases: no mapped label may survive a
    // non-success result, whichever action it belongs to.
    for (const raw of Object.keys(ACTION_LABEL)) {
      for (const bad of ['denied', 'error', 'failed', 'canceled', 'interrupted']) {
        expect(actionLabel(raw, bad), `${raw} @ ${bad}`).not.toBe(ACTION_LABEL[raw])
      }
    }
  })

  it('states the plain fact when the action actually succeeded', () => {
    expect(actionLabel('vm.delete', 'ok')).toBe('VM Deleted')
    expect(actionLabel('app.install', 'succeeded')).toBe('App Installed')
    // No status to go on (alerts, older callers): unchanged behaviour.
    expect(actionLabel('vm.delete')).toBe('VM Deleted')
    expect(actionLabel('vm.delete', null)).toBe('VM Deleted')
    // A status that is not a known SUCCESS value does not earn the past-tense
    // label, even when it is not a known failure either. 'constructor' is not
    // a status at all, and neither is a status this file has not heard of yet.
    expect(actionLabel('vm.delete', 'constructor')).toBe('VM Delete')
  })

  // The scheduler's automatic give-up (jobs/scheduler.py::_disable, the only
  // writer of schedule.disable) must not read like a person's decision; a
  // person switching a schedule off is logged as schedule.update.
  it('says the scheduler disabled a schedule, not that somebody did', () => {
    expect(actionLabel('schedule.disable')).toBe('Schedule Disabled Automatically')
    expect(actionLabel('schedule.disable')).not.toBe(actionLabel('schedule.update'))
  })

  // A failed READ of the guest's NIC config is not an attempted write.
  it('keeps a failed guest network read out of the configuration wording', () => {
    expect(actionLabel('network.guest_config_read')).toBe('Guest Network Read')
    expect(actionLabel('network.guest_config_read', 'error'))
      .toBe('Network Guest Config Read Failed')
    expect(actionLabel('network.guest_config_read', 'error'))
      .not.toBe(actionLabel('network.guest_config'))
  })

  it('never renders a mapped label as blank', () => {
    for (const [raw, label] of Object.entries(ACTION_LABEL)) {
      expect(label.trim(), raw).not.toBe('')
    }
  })
})

// Both lookups are plain object literals, so an identifier that collides with
// something on Object.prototype must not be answered with that. Asserted for
// ACTION_LABEL as well as OUTCOME: guarding only one of the two reads as an
// oversight the next time somebody looks.
it('does not answer prototype keys out of either lookup table', () => {
  // 'ToString' rather than 'To String' is right: derive() splits on . _ - :
  // and there is no separator here. What matters is that neither call answers
  // with the function living on Object.prototype.
  expect(actionLabel('toString')).toBe('ToString')
  expect(actionLabel('constructor')).toBe('Constructor')
  // An unrecognised status must NOT fall through to the success label: it
  // names the attempt instead, so a status added backend-side later cannot
  // silently start asserting a delete that may not have happened.
  expect(actionLabel('vm.delete', 'timed_out')).toBe('VM Delete')
})

// Renaming a success label is not enough on its own: failure titles come from
// the identifier, so "metrics.maintain" would have gone on failing as
// "Metrics Maintain Failed" long after the success label stopped saying it.
it('keeps a renamed label consistent when the job did not succeed', () => {
  expect(actionLabel('metrics.maintain', 'succeeded')).toBe('Usage Cleanup')
  expect(actionLabel('metrics.maintain', 'failed')).toBe('Usage Cleanup Failed')
  expect(actionLabel('metrics.maintain', 'running')).toBe('Usage Cleanup')
})

// enqueue_and_audit writes its audit row the moment the job is QUEUED, with
// result ok, because what succeeded is the REQUEST. The activity feed hides
// these rows (api/cluster.py filters on job_id, since the job row beside them
// carries the real outcome), so the audit log is the only place the
// past-tense label claimed a finish that had not happened.
describe('job-backed audit rows', () => {
  it('says a job was requested, not that it finished', () => {
    expect(actionLabel('app.install', 'ok', true)).toBe('App Install Requested')
    expect(actionLabel('app.migrate', 'ok', true)).toBe('App Migration Requested')
    // Same ATTEMPT phrase serves both endings, which is why the overrides are
    // worth having: "App Migration" reads as Requested and as Failed, where
    // "App Migrated" reads as neither.
    expect(actionLabel('app.migrate', 'denied')).toBe('App Migration Denied')
  })

  it('leaves rows with no job alone', () => {
    // A denied request never enqueued anything, so it carries no job_id and
    // must keep its verdict rather than becoming "Requested".
    expect(actionLabel('app.install', 'denied', false)).toBe('App Install Denied')
    expect(actionLabel('app.install', 'ok', false)).toBe('App Installed')
    expect(actionLabel('app.install', 'ok')).toBe('App Installed')
  })

  it('does not let a job-backed row outrank a failure', () => {
    // If a job-linked row ever carries a failing result, the failure wins:
    // "Requested" would be the less alarming of the two readings.
    expect(actionLabel('app.install', 'failed', true)).toBe('App Install Failed')
  })
})
