/**
 * Shared status colouring and relative-time formatting for anything that
 * renders a job/audit/alert row: ActivityFeed (the dashboard feed) and
 * BellPopover (the bell's job list). Kept in a plain .ts file rather than
 * exported alongside a component so oxlint's react/only-export-components
 * (fast-refresh) rule has nothing to flag here.
 */

export const TINT: Record<string, string> = {
  succeeded: 'bg-green-dim text-green',
  ok: 'bg-green-dim text-green',
  resolved: 'bg-green-dim text-green',
  failed: 'bg-red-dim text-red',
  error: 'bg-red-dim text-red',
  denied: 'bg-red-dim text-red',
  firing: 'bg-red-dim text-red',
  running: 'bg-blue-dim text-blue',
  queued: 'bg-blue-dim text-blue',
  canceled: 'bg-panel-2 text-text-3',
  interrupted: 'bg-amber-dim text-amber',
}

export function ago(iso: string): string {
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000))
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  return `${Math.round(s / 86400)}d ago`
}

/**
 * Raw job kind / audit action -> human label, for anything that shows one to a
 * person. Deliberately a FRONTEND concern: the API keeps emitting the stored
 * identifiers, so the audit filter, the CSV/JSONL export and any API consumer
 * keep matching on the real values rather than on prose that could be reworded
 * at any time.
 *
 * Convention throughout: past tense, "<Thing> <Verbed>", because this is a log
 * of things that already happened. Two entries carry a parenthetical because
 * the bare verb would mislead: those two removals are not the ordinary ones.
 *
 * Every label here is therefore only usable on a row that SUCCEEDED. A denied
 * or failed row is titled by actionLabel from the identifier plus the verdict
 * instead; see OUTCOME below.
 *
 * Covers every `action=` written by write_audit and every key registered in
 * HANDLERS; anything newer falls through to actionLabel()'s derivation, which
 * is why a missing entry degrades rather than breaks.
 */
export const ACTION_LABEL: Record<string, string> = {
  'alert.ack': 'Alert Acknowledged',
  'apikey.create': 'API Key Created',
  'apikey.revoke': 'API Key Revoked',
  'app.forget': 'App Forgotten',
  'app.install': 'App Installed',
  'app.migrate': 'App Migrated',
  'app.reaped': 'App Removed',
  'app.reconfigure': 'App Reconfigured',
  'app.restart': 'App Restarted',
  'app.shutdown': 'App Shut Down',
  'app.start': 'App Started',
  'app.stop': 'App Stopped',
  'app.uninstall': 'App Uninstalled',
  'app.update': 'App Updated',
  'apps.adopt': 'Apps Adopted',
  'apps.script_edit': 'App Script Edited',
  'apps.script_revert': 'App Script Reverted',
  'auth.login': 'Signed In',
  'auth.logout': 'Signed Out',
  'backup.delete': 'Backup Deleted',
  'backup.prune': 'Backups Pruned',
  'backup.restore': 'Backup Restored',
  'backup.run': 'Backup Taken',
  'backup.sync': 'Backups Synced',
  'catalog.classify_backlog': 'Catalog Backlog Classified',
  'catalog.refresh': 'Catalog Refreshed',
  'console.open': 'Console Opened',
  'entitlement.refresh': 'Entitlements Refreshed',
  'host.create': 'Host Added',
  'host.credentials': 'Host Credentials Updated',
  'host.reboot': 'Host Rebooted',
  'host.remove': 'Host Removed',
  'host.shutdown': 'Host Shut Down',
  'host.ssh_verify': 'Host SSH Key Verified',
  'host.sync': 'Host Synced',
  'host.test': 'Host Connection Tested',
  'job.cancel': 'Job Canceled',
  'metrics.maintain': 'Usage Cleanup',
  'migrate.app': 'App Migrated',
  'network.apply': 'Network Changes Applied',
  'network.guest_config': 'Guest Network Configured',
  // Distinct from the line above on purpose: this one is only ever written
  // when READING the guest's current NIC config failed, before anything was
  // sent to the guest, so it must not read as a configuration attempt.
  'network.guest_config_read': 'Guest Network Read',
  'network.host_config': 'Host Network Configured',
  'network.revert': 'Network Changes Reverted',
  'schedule.create': 'Schedule Created',
  'schedule.delete': 'Schedule Deleted',
  // Not the same event as a person switching a schedule off: THAT is written
  // by api/schedules.py as `schedule.update`. This identifier is written from
  // exactly one place, jobs/scheduler.py::_disable, when the scheduler gives
  // up on a row it cannot run at all (unparseable cron, unknown timezone, no
  // handler for its job kind). "Schedule Disabled" made the automatic
  // give-up look like somebody's decision, so the label says who did it.
  'schedule.disable': 'Schedule Disabled Automatically',
  'schedule.fire': 'Schedule Fired',
  'schedule.run': 'Schedule Run Manually',
  'schedule.update': 'Schedule Updated',
  'settings.update': 'Settings Updated',
  'storage.create': 'Storage Added',
  'storage.delete_volume': 'Storage Volume Deleted',
  'storage.remove': 'Storage Removed',
  'storage.update': 'Storage Updated',
  'storage.upload': 'Uploaded To Storage',
  'team.create': 'Team Created',
  'team.delete': 'Team Deleted',
  'team.update': 'Team Updated',
  'user.create': 'User Created',
  'user.delete': 'User Deleted',
  'user.password_reset': 'User Password Reset',
  'user.update': 'User Updated',
  'vm.clone': 'VM Cloned',
  'vm.create': 'VM Created',
  'vm.delete': 'VM Deleted',
  'vm.pause': 'VM Paused',
  'vm.restart': 'VM Restarted',
  'vm.resume': 'VM Resumed',
  'vm.shutdown': 'VM Shut Down',
  'vm.snapshot_create': 'VM Snapshot Created',
  'vm.snapshot_delete': 'VM Snapshot Deleted',
  'vm.snapshot_rollback': 'VM Snapshot Rolled Back',
  'vm.start': 'VM Started',
  'vm.stop': 'VM Stopped',
}

/** Words the naive title-caser below would otherwise mangle into 'Vm', 'Api'.
 *  A map rather than a set of acronyms because 'apikey' is one identifier word
 *  but two English ones, and derived phrases are now shown for every failed or
 *  denied action (see OUTCOME), not just for identifiers nobody mapped. */
const WORDS: Record<string, string> = {
  vm: 'VM', api: 'API', apikey: 'API Key', ssh: 'SSH', ip: 'IP',
  tls: 'TLS', vnc: 'VNC', cpu: 'CPU', lxc: 'LXC', ct: 'CT',
}

/** 'vm.snapshot_delete' -> 'VM Snapshot Delete'. Identifiers in this codebase
 *  are verb-final, so the derivation reads as the ATTEMPT ("VM Delete"), not
 *  as the accomplished fact ("VM Deleted") the map above states. */
// Overrides for identifiers whose derived phrase is wrong or is the jargon we
// are trying to get rid of. Kept deliberately tiny: derive() is right for
// almost everything because the identifiers are verb-final, so this is an
// exceptions list, NOT a second copy of ACTION_LABEL. `metrics.maintain`
// would otherwise fail as "Metrics Maintain Failed", reintroducing the exact
// wording the success label was renamed to remove.
const ATTEMPT: Record<string, string> = {
  'metrics.maintain': 'Usage Cleanup',
}


function derive(raw: string): string {
  if (Object.hasOwn(ATTEMPT, raw)) return ATTEMPT[raw]
  return raw.split(/[._\-:]/).filter(Boolean)
    // hasOwn, not `WORDS[w] ?? ...`: WORDS is a plain object literal, so a
    // word like "constructor" or "toString" answers with the function on
    // Object.prototype, and `??` does not fall through because a function is
    // neither null nor undefined. The title then renders as JS source. Same
    // guard as OUTCOME and ACTION_LABEL below, and this one is the reachable
    // case, since it applies per WORD rather than per identifier.
    .map((w) => {
      const key = w.toLowerCase()
      return Object.hasOwn(WORDS, key) ? WORDS[key] : w[0].toUpperCase() + w.slice(1)
    })
    .join(' ')
}

/**
 * Verdict word for an audit `result` or job `status` that did NOT succeed.
 *
 * Every label in ACTION_LABEL is an ASSERTION: "VM Deleted" says the VM is
 * gone, "Host Removed" says the host is out. write_audit records `ok`,
 * `denied` or `error`, and jobs finish `failed`/`canceled`/`interrupted`, so
 * titling a refused migration "App Migrated" makes the audit log claim a
 * destructive thing that never happened: the worst failure available to a
 * compliance surface. A non-success row is therefore titled from the attempt
 * plus the verdict, "App Migrate Denied" / "VM Delete Failed".
 *
 * Keyed by result, never by action: one rule covers every action and job kind
 * that exists or gets added later, instead of a second map to keep in sync.
 * Statuses absent from here (`ok`, `succeeded`, `resolved`) keep the plain
 * past-tense label, and so do the in-flight `queued`/`running`, whose status
 * every surface that shows them prints right next to the title.
 */
// The only statuses that entitle a row to its past-tense label. Everything
// else, known failure or not, is treated as "did not necessarily succeed".
// Note what is NOT here: `queued` and `running`. A job still in flight has
// not started the app yet, so titling its row "App Started" asserts an
// outcome that has not happened, which is the same defect as "VM Deleted" on
// a denied row. The argument that the status prints beside the title applies
// equally to both, so it cannot justify one without the other. In-flight rows
// therefore read "App Start" next to their `running` status.
const SUCCESS = new Set(['ok', 'succeeded', 'resolved'])

const OUTCOME: Record<string, string> = {
  denied: 'Denied',
  error: 'Failed',
  failed: 'Failed',
  canceled: 'Canceled',
  interrupted: 'Interrupted',
}

/**
 * The job a schedule RUNS, named as the thing it does rather than as a thing
 * that already happened.
 *
 * Deliberately NOT actionLabel(): ACTION_LABEL is past tense by design, so
 * `backup.run` reads "Backup Taken" there, which is right above a finished
 * job and wrong in a column headed "Runs". A schedule does not run a Backup
 * Taken. derive() gives the attempt phrasing the column actually wants, and
 * it consults ATTEMPT on the way, so a kind whose derived name is jargon
 * (metrics.maintain) still gets its override.
 */
export function jobKindLabel(kind: string | null | undefined): string {
  return kind ? derive(kind) : 'Unknown'
}


/**
 * Friendly name for a raw identifier, deriving one when the map has no entry.
 * New actions and job kinds get added backend-side all the time and must never
 * render as a blank title, so an unmapped `foo.bar_baz` still reads as
 * 'Foo Bar Baz' rather than as nothing.
 *
 * `status` is the row's audit result or job status. Pass it wherever one
 * exists: without it this can only state that the action happened.
 */
export function actionLabel(raw: string | null | undefined,
                            status?: string | null): string {
  if (!raw) return 'Unknown'
  // Success is an ALLOWLIST, failure is not. Keying off OUTCOME alone would
  // mean any status this file has not heard of falls through to the past-tense
  // label, so the day the backend adds `timed_out` every timed-out row starts
  // asserting "VM Deleted" again, which is the whole bug this argument exists
  // to prevent. Unknown statuses therefore get the neutral derivation: it
  // names the attempt and claims nothing about how it ended.
  //
  // hasOwn, not `OUTCOME[status]`: a status of 'constructor' or 'toString'
  // would otherwise hit Object.prototype and render as source code.
  if (status != null && !SUCCESS.has(status)) {
    return Object.hasOwn(OUTCOME, status)
      ? `${derive(raw)} ${OUTCOME[status]}`
      : derive(raw)
  }
  // hasOwn here for the same reason as above, not just on OUTCOME: this is a
  // plain object literal, so `ACTION_LABEL['toString']` answers with a
  // function rather than undefined, and `?? derive(raw)` does not catch it
  // because a function is neither null nor undefined.
  return Object.hasOwn(ACTION_LABEL, raw) ? ACTION_LABEL[raw] : derive(raw)
}
