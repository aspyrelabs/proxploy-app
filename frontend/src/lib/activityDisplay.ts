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

/** What a row acted on, named for a person.
 *
 *  `target_name` is captured by the backend when the job or audit row is
 *  written, not looked up when it is read, so it survives the thing being
 *  deleted. That is the case that matters: "vm 3" a month after the delete
 *  names nothing anybody remembers, and there is no row left to ask.
 *
 *  Rows written before that column existed carry no name and fall back to the
 *  type and id pair they always showed, rather than guessing at one.
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
 *
 * The tray used to say "Finished on anytype-server on node1", which names what
 * was acted on and never says WHAT WAS DONE. It reads as broken English, and
 * once target_name started carrying "<guest> on <node>" it also doubled the
 * "on". The verb was always the missing half of the sentence; the target name
 * only made its absence obvious.
 *
 * A TABLE, not a conjugator. Deriving "installing" from "install" needs the
 * silent-e rule (migrate, clone, create, delete), consonant doubling (stop,
 * run) and a hand-written exception for "backing up" anyway, which is a
 * grammar engine to save thirty lines of data and would still be wrong for the
 * next irregular verb somebody adds.
 *
 * An unmapped kind is a deliberate MISS, not a guess: gerundFor returns null
 * and messageOf falls back to the verbless sentence it always wrote. New job
 * kinds land backend-side regularly, and today's plain sentence is a better
 * failure than confident wrong English.
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
  'catalog.refresh': 'refreshing the catalog on',
  'host.reboot': 'rebooting',
  'host.shutdown': 'shutting down',
  'metrics.maintain': 'tidying metrics on',
  'migrate.app': 'migrating',
  'network.apply': 'applying network changes on',
  'storage.upload': 'uploading to',
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
 * state of the row. actionLabel() adds only the verdict word after a failed,
 * canceled or interrupted one, and nothing else: no prefix, no suffix. A denied
 * row reads by its own name and the Result column carries the refusal.
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
  // All three network config identifiers read "Network Edit". Doc 13's "Guest
  // Network" and "Host Network" carried no verb, so a failure read "Guest
  // Network Failed", which sounds like the network went down rather than the
  // edit being refused. Guest vs host comes from the target column.
  //
  // guest_config_read is folded in here too, by product decision, even though
  // it is written only when READING the guest's current NIC list failed
  // (api/network.py:112) before anything was sent. The known cost: a failed
  // read now reads as a failed edit, which overstates what was attempted.
  // Doc 13 item 7 is also wrong that this case shares the write identifier.
  'network.guest_config': 'Network Edit',
  'network.guest_config_read': 'Network Edit',
  'network.host_config': 'Network Edit',
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
 * value.
 *
 * `denied` and `error` are not in doc 13, which spends its denied row on the
 * "Blocked" title prefix and never names the Result cell. Without them the
 * audit log printed a polished "Complete" in one row and a bare lowercase
 * "denied" in the next. Refused and Error were chosen so the column says
 * something the title does not already say.
 */
export const STATUS_LABEL: Record<string, string> = {
  // Not "Pending", which is what a QUEUE is: this one means the guest is
  // being acted on right now and its real status is not known until the
  // action reports back.
  pending: 'Working',
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
 * plus a status word. "Backup Run Done" is what the two-part rule produced,
 * and it is not a sentence anyone says: a backup starts, completes, fails or
 * is stopped, and each of those is its own event to an operator watching a
 * 40-minute vzdump.
 *
 * Deliberately narrow. The two-part composition below is still the rule, and
 * a kind stays out of here unless its outcomes genuinely have their own names;
 * an entry that only reworded "Done" would be a second vocabulary for nothing.
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
                            status?: string | null): string {
  if (!raw) return 'Unknown'
  const label = derive(raw)
  // NO affix is ever added to a label beyond the verdict words below. The two
  // that used to be, "Blocked" on a denied row and "Requested" on a job-backed
  // one, are gone: both broke doc 13 rule 1 by taking a label to three words,
  // "Requested" broke rule 2 as well by being past tense while not being a
  // verdict, and neither was in the map, so the test that enforces the
  // two-word rule over ACTION_LABEL could not see either of them.
  //
  // What carried the information instead:
  //   denied  -> the Result column already renders `denied` in red, and it is
  //              the column whose job is the verdict.
  //   queued  -> a job-backed audit row records the ASKING, written when the
  //              job was queued. The job beside it carries the real outcome,
  //              and that distinction now belongs anywhere but the name.
  if (status != null && Object.hasOwn(OUTCOME, status)) return `${label} ${OUTCOME[status]}`
  return label
}
