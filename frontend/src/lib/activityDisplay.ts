/**
 * Shared naming and relative-time formatting for anything that renders a
 * job/audit/alert row: BellPopover, the audit log, StatusPill, and the job
 * toasts api/jobs.ts writes.
 */

/**
 * What a row acted on, named for a person.
 *
 * `target_name` is captured when the row is written, not looked up on read, so
 * it survives the thing being deleted. Rows written before the column existed
 * fall back to the type/id pair.
 */
export function targetLabel(row: {
  target_type: string | null
  target_id: number | null
  target_name?: string | null
}): string | null {
  if (row.target_name) return row.target_name
  if (!row.target_type) return null
  return `${row.target_type}${row.target_id != null ? ` ${row.target_id}` : ''}`
}

/**
 * The verb for a job kind, as a gerund, for the sentence the tray writes.
 * A table, not a conjugator (silent-e, doubling, and "backing up" exceptions).
 * An unmapped kind is a deliberate miss: gerundFor returns null and messageOf
 * falls back to the verbless sentence.
 */
export const GERUND: Record<string, string> = {
  'app.install': 'installing',
  'app.uninstall': 'uninstalling',
  'app.update': 'updating',
  'app.reconfigure': 'reconfiguring',
  'app.start': 'starting',
  'app.stop': 'stopping',
  'app.restart': 'restarting',
  'app.shutdown': 'shutting down',
  'apps.adopt': 'importing',
  'backup.run': 'backing up',
  'backup.restore': 'restoring',
  'backup.delete': 'deleting the backup for',
  'backup.prune': 'pruning backups on',
  'backup.sync': 'syncing backups on',
  'backup.verify': 'verifying the backups of',
  'backup.test_restore': 'test restoring',
  'catalog.classify_backlog': 'checking compatibility on',
  'db.compact': 'reclaiming database space on',
  'catalog.refresh': 'refreshing the catalog on',
  'host.reboot': 'rebooting',
  'host.shutdown': 'shutting down',
  'metrics.maintain': 'tidying metrics on',
  'jobs.prune': 'trimming job history on',
  'migrate.app': 'migrating',
  'network.apply': 'applying network changes on',
  'sessions.cleanup': 'clearing expired sign-ins on',
  'storage.upload': 'uploading to',
  'update.check': 'checking for a new release on',
  'storage.delete_volume': 'deleting a volume on',
  'vm.create': 'creating',
  'vm.clone': 'cloning',
  'vm.delete': 'destroying',
  'vm.snapshot_create': 'snapshotting',
  'vm.snapshot_delete': 'deleting a snapshot on',
  'vm.snapshot_rollback': 'rolling back',
  'vm.start': 'starting',
  'vm.stop': 'stopping',
  'vm.restart': 'restarting',
  'vm.shutdown': 'shutting down',
  'vm.pause': 'pausing',
  'vm.resume': 'resuming',
}

/** The gerund for a job kind, or null when nobody has written one. Null is the
 *  signal to fall back to a sentence with no verb in it, never to invent one. */
export function gerundFor(kind: string | null | undefined): string | null {
  return kind ? GERUND[kind] ?? null : null
}

export function duration(row: { started_at: string | null; finished_at: string | null }): string | null {
  if (!row.started_at || !row.finished_at) return null
  const ms = new Date(row.finished_at).getTime() - new Date(row.started_at).getTime()
  if (!Number.isFinite(ms) || ms < 0) return null
  return ms < 1000 ? `${ms}ms` : ms < 60_000 ? `${(ms / 1000).toFixed(1)}s`
                                             : `${Math.round(ms / 60_000)}m`
}

export function ago(iso: string): string {
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000))
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  return `${Math.round(s / 86400)}d ago`
}

/**
 * Raw job kind / audit action -> human label. Deliberately a FRONTEND concern:
 * the API keeps emitting the stored identifiers so consumers keep matching on
 * real values.
 *
 * Two words, neutral, bare verb (doc 13): the label names the action and the
 * status word says how it went, so one entry serves every state. actionLabel()
 * adds only the verdict after a failed, canceled or interrupted row.
 *
 * Covers every `action=` written by write_audit and every HANDLERS key;
 * anything newer falls through to derive()'s word splitting.
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
  // Deliberately the SAME label as app.forget, decided by the product owner
  // and overriding doc 13's "Collisions this pass removed" section, which
  // argued these must differ so the feed says whether the container still
  // exists. It does not: both read App Unlink. Do not "fix" this back from
  // the doc without asking.
  'app.reaped': 'App Unlink',
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
  'backup.test_restore': 'Test Restore',
  'backup.verify': 'Backup Verify',
  'catalog.classify_backlog': 'Compatibility Check',
  'catalog.refresh': 'Store Refresh',
  'console.open': 'Console Open',
  'db.compact': 'Database Compact',
  'entitlement.refresh': 'Plan Refresh',
  'host.create': 'Host Add',
  'host.credentials': 'Credentials Rotate',
  'host.reboot': 'Host Reboot',
  'host.remove': 'Host Disconnect',
  'host.shutdown': 'Host Shutdown',
  'host.ssh_verify': 'Fingerprint Verify',
  'host.sync': 'Host Sync',
  'host.test': 'Connection Test',
  // "Job", not doc 13's "Task": every other surface says job, including the
  // Cancel button, the bell tray, the failure toast and the /jobs API.
  'job.cancel': 'Job Cancel',
  'jobs.prune': 'History Cleanup',
  'metrics.maintain': 'Usage Cleanup',
  'sessions.cleanup': 'Sign-in Cleanup',
  'update.check': 'Update Check',
  // Doc 13 asks for "Migration Refused", but api/apps.py writes action="app.migrate"
  // for every REAL migration (result ok + job_id), and migrate.app is the job
  // kind, not a second audit action. Both identifiers carry the same neutral
  // label — the same event seen twice; the Blocked prefix does the refusal work.
  'app.migrate': 'App Migrate',
  'migrate.app': 'App Migrate',
  'network.apply': 'Network Apply',
  // All three network config identifiers read "Network Edit": doc 13's "Guest
  // Network"/"Host Network" carried no verb, so a failure read as the network
  // going down. Guest vs host comes from the target column. guest_config_read is
  // folded in here too (product decision); the cost is a failed read now reads
  // as a failed edit.
  'network.guest_config': 'Network Edit',
  'network.guest_config_read': 'Network Edit',
  'network.host_config': 'Network Edit',
  'network.revert': 'Network Revert',
  'schedule.create': 'Schedule Create',
  'schedule.delete': 'Schedule Delete',
  // Not a person switching a schedule off (that's api/schedules.py `schedule.update`).
  // Written only by jobs/scheduler.py::_disable, when the scheduler gives up on
  // an unrunnable row (unparseable cron, unknown timezone, no handler). The label
  // says who did it, so the automatic give-up isn't read as a decision.
  'schedule.disable': 'Schedule Auto-Disable',
  'schedule.fire': 'Schedule Trigger',
  'schedule.run': 'Schedule Run',
  // jobs/scheduler.py::fire_one, on a job whose catch-up box is unticked and
  // whose start was missed by more than the grace window. Auto- for the same
  // reason schedule.disable carries it: nobody chose this, the scheduler did.
  'schedule.skip': 'Schedule Auto-Skip',
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
 * Keyed on the raw API value so one map serves the bell, the audit log and
 * StatusPill; anything absent falls through to the raw value.
 *
 * `denied` and `error` are not in doc 13; without them the audit log mixed
 * "Complete" with a bare lowercase "denied".
 */
export const STATUS_LABEL: Record<string, string> = {
  // Not "Pending", which is what a QUEUE is: this one means the guest is
  // being acted on right now and its real status is not known until the
  // action reports back.
  pending: 'Working',
  // An app being uninstalled. Its own word rather than "Working", because a
  // removal is the one action that ends with the row gone.
  removing: 'Removing',
  queued: 'Waiting',
  running: 'Running',
  succeeded: 'Done',
  ok: 'Complete',
  denied: 'Refused',
  error: 'Error',
  resolved: 'Cleared',
  canceled: 'Canceled',
  interrupted: 'Interrupted',
  failed: 'Failed',
  unreachable: 'Host Unreachable',
}

/**
 * Kinds that read better as one phrase per outcome than as a neutral label
 * plus a status word. Deliberately narrow: the two-part composition is still
 * the rule, and a kind stays out unless its outcomes have their own names.
 */
const JOB_PHRASE: Record<string, Record<string, string>> = {
  'backup.run': {
    queued: 'Backup Queued',
    running: 'Backup Started',
    succeeded: 'Backup Completed',
    failed: 'Backup Failed',
    canceled: 'Backup Stopped',
    interrupted: 'Backup Interrupted',
  },
  'backup.restore': {
    queued: 'Restore Queued',
    running: 'Restore Started',
    succeeded: 'Restore Completed',
    failed: 'Restore Failed',
    canceled: 'Restore Stopped',
    interrupted: 'Restore Interrupted',
  },
  'backup.delete': {
    queued: 'Delete Queued',
    running: 'Deleting Backup',
    succeeded: 'Backup Deleted',
    failed: 'Delete Failed',
    canceled: 'Delete Stopped',
    interrupted: 'Delete Interrupted',
  },
  'backup.prune': {
    queued: 'Prune Queued',
    running: 'Pruning Backups',
    succeeded: 'Backups Pruned',
    failed: 'Prune Failed',
    canceled: 'Prune Stopped',
    interrupted: 'Prune Interrupted',
  },
  'backup.sync': {
    queued: 'Refresh Queued',
    running: 'Refreshing Backups',
    succeeded: 'Backups Refreshed',
    failed: 'Refresh Failed',
    canceled: 'Refresh Stopped',
    interrupted: 'Refresh Interrupted',
  },
  // "Check Finished", not "Check Passed": the job succeeding means the check
  // RAN, and whether the archive passed is the row's own verdict. A toast
  // reading "Verify Failed" over an archive that is merely corrupt would state
  // the opposite of what happened.
  'backup.verify': {
    queued: 'Verify Queued',
    running: 'Verifying Backup',
    succeeded: 'Verify Finished',
    failed: 'Verify Could Not Run',
    canceled: 'Verify Stopped',
    interrupted: 'Verify Interrupted',
  },
  'backup.test_restore': {
    queued: 'Test Restore Queued',
    running: 'Test Restore Started',
    succeeded: 'Test Restore Completed',
    failed: 'Test Restore Failed',
    canceled: 'Test Restore Stopped',
    interrupted: 'Test Restore Interrupted',
  },
}

/** The phrase for one (kind, status), or null when the kind has no map and
 *  the caller should compose a label and a status the usual way. */
export function jobPhrase(kind: string | null | undefined,
                          status: string | null | undefined): string | null {
  if (!kind || !status) return null
  const byStatus = Object.hasOwn(JOB_PHRASE, kind) ? JOB_PHRASE[kind] : null
  return byStatus && Object.hasOwn(byStatus, status) ? byStatus[status] : null
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
 * otherwise 'vm.snapshot_delete' -> 'VM Snapshot Delete'. The map is neutral
 * now, so the fallback is word splitting for unmapped identifiers, which are
 * verb-final (migrate.app is the exception, and it is mapped).
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
 * `denied` is deliberately NOT here: a refusal is prefixed, not suffixed
 * (doc 13). Keyed by result, never by action, so one rule covers every action
 * and job kind. Unknown statuses get the bare label.
 */
const OUTCOME: Record<string, string> = {
  error: 'Failed',
  failed: 'Failed',
  canceled: 'Canceled',
  interrupted: 'Interrupted',
}

/**
 * Friendly name for a raw identifier, deriving one when the map has no entry,
 * so an unmapped `foo.bar_baz` still reads 'Foo Bar Baz'. `status` is the
 * row's audit result or job status; passing it adds the verdict.
 */
export function actionLabel(raw: string | null | undefined,
                            status?: string | null): string {
  if (!raw) return 'Unknown'
  const label = derive(raw)
  // No affix beyond the verdict words below.
  if (status != null && Object.hasOwn(OUTCOME, status)) return `${label} ${OUTCOME[status]}`
  return label
}
