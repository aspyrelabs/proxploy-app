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
  'metrics.maintain': 'Metrics Maintained',
  'migrate.app': 'App Migrated',
  'network.apply': 'Network Changes Applied',
  'network.guest_config': 'Guest Network Configured',
  'network.host_config': 'Host Network Configured',
  'network.revert': 'Network Changes Reverted',
  'schedule.create': 'Schedule Created',
  'schedule.delete': 'Schedule Deleted',
  'schedule.disable': 'Schedule Disabled',
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

/** Words the naive title-caser below would otherwise mangle into 'Vm', 'Api'. */
const ACRONYMS = new Set(['vm', 'api', 'apikey', 'ssh', 'ip', 'tls', 'vnc', 'cpu', 'lxc', 'ct'])

/**
 * Friendly name for a raw identifier, deriving one when the map has no entry.
 * New actions and job kinds get added backend-side all the time and must never
 * render as a blank title, so an unmapped `foo.bar_baz` still reads as
 * 'Foo Bar Baz' rather than as nothing.
 */
export function actionLabel(raw: string | null | undefined): string {
  if (!raw) return 'Unknown'
  return ACTION_LABEL[raw] ?? raw.split(/[._\-:]/).filter(Boolean)
    .map((w) => (ACRONYMS.has(w.toLowerCase())
      ? w.toUpperCase() : w[0].toUpperCase() + w.slice(1)))
    .join(' ')
}
