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
 * Convention throughout (doc 13): two words, NEUTRAL, bare verb. Not past
 * tense. One label has to read correctly on a row that is waiting, running,
 * done, failed or blocked, so the label names the ACTION and the surrounding
 * status word says how it went. "App Install" reads right next to "Waiting",
 * next to "Done" and next to "Failed"; "App Installed" reads right next to
 * none of them.
 *
 * Because the label claims nothing about the outcome, one entry serves every
 * state of the row. actionLabel() only decorates it: "Blocked" in front of a
 * denied row, the verdict word after a failed one.
 *
 * Covers every `action=` written by write_audit and every key registered in
 * HANDLERS; anything newer falls through to derive()'s word splitting, which
 * is why a missing entry degrades rather than breaks.
 */
export const ACTION_LABEL: Record<string, string> = {
  'alert.ack': 'Alert Acknowledge',
  'apikey.create': 'API Key Create',
  'apikey.revoke': 'API Key Revoke',
  'app.forget': 'App Unlink',
  'app.install': 'App Install',
  // The poller finding the container gone and dropping Proxploy's own row.
  // Nobody removed anything through Proxploy, so this must not share a voice
  // with app.forget or app.uninstall. Unlink means the container is still on
  // Proxmox and only Proxploy stopped tracking it; vanished means it is gone
  // and Proxploy cleaned up after it.
  'app.reaped': 'App Vanished',
  'app.reconfigure': 'App Reconfigure',
  'app.restart': 'App Restart',
  'app.shutdown': 'App Shutdown',
  'app.start': 'App Start',
  'app.stop': 'App Stop',
  'app.uninstall': 'App Uninstall',
  'app.update': 'App Update',
  'apps.adopt': 'App Import',
  'apps.script_edit': 'Script Edit',
  'apps.script_revert': 'Script Restore',
  'auth.login': 'Sign In',
  // api/auth.py:109, between a correct password and the TOTP code.
  'auth.login.totp_pending': 'Two-Factor Prompt',
  'auth.logout': 'Sign Out',
  'backup.delete': 'Backup Delete',
  'backup.prune': 'Backup Prune',
  'backup.restore': 'Backup Restore',
  'backup.run': 'Backup Run',
  'backup.sync': 'Backup Sync',
  'catalog.classify_backlog': 'Compatibility Check',
  'catalog.refresh': 'Store Refresh',
  'console.open': 'Console Open',
  'entitlement.refresh': 'Plan Refresh',
  'host.create': 'Host Add',
  'host.credentials': 'Credentials Rotate',
  'host.reboot': 'Host Reboot',
  'host.remove': 'Host Disconnect',
  'host.shutdown': 'Host Shutdown',
  'host.ssh_verify': 'Fingerprint Verify',
  'host.sync': 'Host Sync',
  'host.test': 'Connection Test',
  'job.cancel': 'Task Cancel',
  'metrics.maintain': 'Usage Cleanup',
  // Doc 13 asks for "Migration Refused" here, on the premise that app.migrate
  // is only ever written for a refusal and that a real migration is logged
  // under migrate.app. Neither half holds: api/apps.py passes
  // action="app.migrate" to enqueue_and_audit for every REAL migration (that
  // row carries result ok and a job_id), and migrate.app is the JOB KIND, not
  // a second audit action. Applying the doc made a successful migration read
  // "Migration Refused Requested" and its refusal "Blocked Migration Refused",
  // which is both a false statement and the collision rule 6 forbids.
  //
  // So both identifiers carry the same neutral label, which is correct
  // because they are the same event seen twice: the audit action and the job
  // kind it enqueued. The Blocked prefix does the refusal work it was
  // designed for.
  'app.migrate': 'App Migrate',
  'migrate.app': 'App Migrate',
  'network.apply': 'Network Apply',
  'network.guest_config': 'Guest Network',
  // Distinct from the line above on purpose: this one is only ever written
  // when READING the guest's current NIC config failed (api/network.py:112),
  // before anything was sent to the guest, so it must not read as a
  // configuration attempt. Doc 13 item 7 claims both halves now share one
  // identifier; they do not, so this entry stays.
  'network.guest_config_read': 'Guest Network Read',
  'network.host_config': 'Host Network',
  'network.revert': 'Network Revert',
  'schedule.create': 'Schedule Create',
  'schedule.delete': 'Schedule Delete',
  // Not the same event as a person switching a schedule off: THAT is written
  // by api/schedules.py as `schedule.update`. This identifier is written from
  // exactly one place, jobs/scheduler.py::_disable, when the scheduler gives
  // up on a row it cannot run at all (unparseable cron, unknown timezone, no
  // handler for its job kind). A bare "Schedule Disable" would make the
  // automatic give-up look like somebody's decision, so the label says who
  // did it.
  'schedule.disable': 'Schedule Auto-Disable',
  'schedule.fire': 'Schedule Trigger',
  'schedule.run': 'Schedule Run',
  'schedule.update': 'Schedule Update',
  'settings.update': 'Settings Update',
  'storage.create': 'Storage Add',
  'storage.delete_volume': 'File Delete',
  'storage.remove': 'Storage Detach',
  'storage.update': 'Storage Update',
  'storage.upload': 'File Upload',
  'team.create': 'Team Create',
  'team.delete': 'Team Delete',
  'team.update': 'Team Update',
  'user.create': 'User Create',
  'user.delete': 'User Delete',
  'user.password_reset': 'Password Reset',
  'user.update': 'User Update',
  'vm.clone': 'VM Clone',
  'vm.create': 'VM Create',
  'vm.delete': 'VM Delete',
  'vm.pause': 'VM Pause',
  'vm.restart': 'VM Restart',
  'vm.resume': 'VM Resume',
  'vm.shutdown': 'VM Shutdown',
  'vm.snapshot_create': 'Snapshot Create',
  'vm.snapshot_delete': 'Snapshot Delete',
  'vm.snapshot_rollback': 'Snapshot Restore',
  'vm.start': 'VM Start',
  'vm.stop': 'VM Stop',
}

/**
 * Job status, audit result, alert state and host status, as doc 13 names them.
 *
 * Keyed on the raw value the API sends, same as TINT above, so one map serves
 * the activity feed's status line, the audit log's Result column and the
 * StatusPill on hosts and guests. Anything absent falls through to the raw
 * value: `denied` and `error` have no entry because doc 13 gives none, it
 * spends its denied row on the "Blocked" prefix instead.
 */
export const STATUS_LABEL: Record<string, string> = {
  queued: 'Waiting',
  running: 'Running',
  succeeded: 'Done',
  ok: 'Complete',
  resolved: 'Cleared',
  canceled: 'Canceled',
  interrupted: 'Interrupted',
  failed: 'Failed',
  unreachable: 'Host Unreachable',
}

/** hasOwn, not `STATUS_LABEL[s]`: a status of 'toString' would otherwise
 *  answer with the function on Object.prototype and render as JS source. */
export function statusLabel(status: string | null | undefined): string {
  if (!status) return 'unknown'
  return Object.hasOwn(STATUS_LABEL, status) ? STATUS_LABEL[status] : status
}

/** Words the naive title-caser below would otherwise mangle into 'Vm', 'Api'.
 *  A map rather than a set of acronyms because 'apikey' is one identifier word
 *  but two English ones. Only reachable for identifiers ACTION_LABEL has never
 *  heard of, which is exactly the case it exists for. */
const WORDS: Record<string, string> = {
  vm: 'VM', api: 'API', apikey: 'API Key', ssh: 'SSH', ip: 'IP',
  tls: 'TLS', vnc: 'VNC', cpu: 'CPU', lxc: 'LXC', ct: 'CT',
}

/**
 * The neutral name of an action or job kind: the mapped label if there is one,
 * otherwise 'vm.snapshot_delete' -> 'VM Snapshot Delete'.
 *
 * One function, because the map is now neutral too. It used to need a second
 * map (ATTEMPT) to supply a phrase that worked on a row which had not
 * succeeded, since ACTION_LABEL only had past-tense assertions to offer.
 * Every ACTION_LABEL entry is that neutral phrase now, so the fallback is just
 * the word splitting for identifiers nobody has mapped yet.
 *
 * The derivation reads correctly because identifiers in this codebase are
 * verb-final. `migrate.app` is the one that is not, and it is mapped.
 */
function derive(raw: string): string {
  // hasOwn, not `ACTION_LABEL[raw] ?? ...`: ACTION_LABEL is a plain object
  // literal, so 'toString' answers with the function on Object.prototype, and
  // `??` does not fall through because a function is neither null nor
  // undefined. The title would then render as JS source.
  if (Object.hasOwn(ACTION_LABEL, raw)) return ACTION_LABEL[raw]
  return raw.split(/[._\-:]/).filter(Boolean)
    // Same guard, per WORD rather than per identifier.
    .map((w) => {
      const key = w.toLowerCase()
      return Object.hasOwn(WORDS, key) ? WORDS[key] : w[0].toUpperCase() + w.slice(1)
    })
    .join(' ')
}

/**
 * Verdict word appended to a row that ended badly.
 *
 * `denied` is deliberately NOT here: a refusal is prefixed, not suffixed (doc
 * 13, "Two structural fixes"). "Blocked Host Disconnect" says up front that
 * nothing happened, where "Host Disconnect Denied" buries it behind the name
 * of the thing that did not happen.
 *
 * Keyed by result, never by action: one rule covers every action and job kind
 * that exists or gets added later, instead of a second map to keep in sync.
 * A status this file has not heard of gets the bare label, which claims
 * nothing either way, and so do `queued` and `running`, whose status every
 * surface that shows them prints right next to the title.
 */
const OUTCOME: Record<string, string> = {
  error: 'Failed',
  failed: 'Failed',
  canceled: 'Canceled',
  interrupted: 'Interrupted',
}

/**
 * Friendly name for a raw identifier, deriving one when the map has no entry.
 * New actions and job kinds get added backend-side all the time and must never
 * render as a blank title, so an unmapped `foo.bar_baz` still reads as
 * 'Foo Bar Baz' rather than as nothing.
 *
 * `status` is the row's audit result or job status. The label is already true
 * without it; passing it adds the verdict, which is the part the reader wants
 * at a glance.
 */
export function actionLabel(raw: string | null | undefined,
                            status?: string | null,
                            jobLinked = false): string {
  if (!raw) return 'Unknown'
  const label = derive(raw)
  // One rule for every action, present and future, rather than a map entry
  // per denied action. hasOwn on OUTCOME for the prototype-key reason above.
  if (status === 'denied') return `Blocked ${label}`
  if (status != null && Object.hasOwn(OUTCOME, status)) return `${label} ${OUTCOME[status]}`
  // A job-backed audit row is written by enqueue_and_audit the moment the job
  // is QUEUED, with result ok, because what succeeded is the REQUEST. The row
  // is a record of the asking, and the job beside it carries the real outcome,
  // so this says so rather than letting the audit log imply the work is done.
  //
  // The activity feed never shows these rows (api/cluster.py filters audit
  // rows that carry a job_id), so the audit log is the only surface that needs
  // the distinction.
  if (jobLinked) return `${label} Requested`
  return label
}
