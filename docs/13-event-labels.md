# Event labels inventory

Every event Proxploy shows a user, what the code actually does, and the label
it should carry.

**Naming rules**

1. Two words. Never more. The only exception is the API Key pair, where the
   product name itself is two words.
2. Neutral, not past tense. A label must read correctly whether the row is
   waiting, running, done, failed or blocked. "App Install" plus "failed" reads
   right; "App Installed" plus "failed" contradicts itself.

   Exception: an event with exactly one possible state, which never carries a
   verdict word, may be past tense. "Backup Failed" and "Job Interrupted" have
   already happened by the time anything renders them, so there is no second
   state for a neutral label to serve, and "Backup Fail" is stilted English
   for a thing that definitely occurred. The test of the exception is whether
   a verdict word can ever be appended: if one can, the label must be neutral.
3. Bare verb, not the -ion form. "VM Create", not "VM Creation". Applied
   everywhere so the list reads as one voice.
4. No brackets, no parentheses, no asides.
5. A system action must not read like a user action.
6. A refusal must not read like a success, and must not collide with the label
   of the thing it refused.

---

## Information events

| Identifier | Current label | What it actually means | Suggested label |
|---|---|---|---|
| `alert.ack` | Alert Acknowledged | A user marked a firing alert as seen. It keeps firing until the condition clears. | Alert Acknowledge |
| `apikey.create` | API Key Created | A new personal API key was generated. | API Key Create |
| `apikey.revoke` | API Key Revoked | An API key was permanently disabled. | API Key Revoke |
| `app.forget` | App Forgotten | Proxploy's record removed, container left running on Proxmox. | App Unlink |
| `app.install` | App Installed | A container was installed onto a host over SSH. | App Install |
| `app.reconfigure` | App Reconfigured | Name, port, protocol or path changed. A name change also pushes a hostname update. | App Reconfigure |
| `app.restart` | App Restarted | Proxmox rebooted the container. | App Restart |
| `app.shutdown` | App Shut Down | Graceful power off. | App Shutdown |
| `app.start` | App Started | Container started. | App Start |
| `app.stop` | App Stopped | Hard kill, not graceful. | App Stop |
| `app.uninstall` | App Uninstalled | Container stopped, destroyed, record deleted. | App Uninstall |
| `app.update` | App Updated | Install script re-run at the current upstream commit. | App Update |
| `apps.adopt` | Apps Adopted | Existing Proxmox containers imported as tracked apps. | App Import |
| `apps.script_edit` | App Script Edited | The stored install script was edited. | Script Edit |
| `apps.script_revert` | App Script Reverted | A saved script version was restored. | Script Restore |
| `auth.login` | Signed In | Successful login. | Sign In |
| `auth.logout` | Signed Out | Session ended. | Sign Out |
| `backup.delete` | Backup Deleted | One archive deleted from storage. | Backup Delete |
| `backup.prune` | Backups Pruned | Retention rule applied, matching archives deleted. | Backup Prune |
| `backup.restore` | Backup Restored | Restored in place or as a new guest. | Backup Restore |
| `backup.run` | Backup Taken | vzdump ran against chosen guests, or all if none chosen. | Backup Run |
| `backup.sync` | Backups Synced | Backup list re-read from Proxmox into the cache. | Backup Sync |
| `catalog.classify_backlog` | Catalog Backlog Classified | Background pass works out which store apps are installable. | Compatibility Check |
| `catalog.refresh` | Catalog Refreshed | Store listing re-read from GitHub, icons and available updates recomputed. | Store Refresh |
| `console.open` | Console Opened | A terminal or VNC session opened. | Console Open |
| `entitlement.refresh` | Entitlements Refreshed | Plan details re-fetched from the licensing service. | Plan Refresh |
| `host.create` | Host Added | A new Proxmox host was connected. | Host Add |
| `host.credentials` | Host Credentials Updated | API token or SSH key rotated. | Credentials Rotate |
| `host.reboot` | Host Rebooted | Proxmox was told to reboot the node. Return is not tracked. | Host Reboot |
| `host.remove` | Host Removed | Host record, token, key and cache deleted. The node is untouched. | Host Disconnect |
| `host.shutdown` | Host Shut Down | Proxmox was told to power off the node. | Host Shutdown |
| `host.ssh_verify` | Host SSH Key Verified | The trusted SSH fingerprint was confirmed. | Fingerprint Verify |
| `host.sync` | Host Synced | Inventory re-polled immediately. | Host Sync |
| `host.test` | Host Connection Tested | Checked the stored credentials still reach the host. | Connection Test |
| `job.cancel` | Job Canceled | A queued or running job was stopped. | Job Cancel |
| `migrate.app` | App Migrated | Container moved to another host. | App Migrate |
| `network.apply` | Network Changes Applied | Staged node network config pushed live. | Network Apply |
| `network.guest_config` | Guest Network Configured | A guest NIC was edited. Takes effect on reboot. | Network Edit |
| `network.guest_config_read` | Guest Network Read | Proxploy could not read a guest's current NIC list. Nothing was written. | Network Edit |
| `network.host_config` | Host Network Configured | An interface in the node's staged config was created, edited or deleted. | Network Edit |
| `network.revert` | Network Changes Reverted | Staged config discarded. | Network Revert |
| `schedule.create` | Schedule Created | A recurring schedule was created. | Schedule Create |
| `schedule.delete` | Schedule Deleted | A schedule was deleted. | Schedule Delete |
| `schedule.fire` | Schedule Fired | The scheduler ran a job on its cron trigger, no user involved. | Schedule Trigger |
| `schedule.run` | Schedule Run Manually | A user clicked run now. | Schedule Run |
| `schedule.update` | Schedule Updated | Cron, timezone, job kind or enabled flag changed. | Schedule Update |
| `settings.update` | Settings Updated | A global setting changed. | Settings Update |
| `storage.create` | Storage Added | A storage pool was attached. | Storage Add |
| `storage.delete_volume` | Storage Volume Deleted | A file was deleted from a storage's contents. | File Delete |
| `storage.remove` | Storage Removed | Storage detached. The pool itself is untouched. | Storage Detach |
| `storage.update` | Storage Updated | Settings of an attached pool changed. | Storage Update |
| `storage.upload` | Uploaded To Storage | A file was uploaded and forwarded to Proxmox storage. | File Upload |
| `team.create` | Team Created | A team was created. | Team Create |
| `team.delete` | Team Deleted | A team was deleted. | Team Delete |
| `team.update` | Team Updated | Team renamed or membership changed. | Team Update |
| `user.create` | User Created | An admin created an account. | User Create |
| `user.delete` | User Deleted | Account, sessions and memberships deleted. | User Delete |
| `user.password_reset` | User Password Reset | An admin set a new password for another user. | Password Reset |
| `user.update` | User Updated | Role, email, active flag or profile changed. | User Update |
| `vm.clone` | VM Cloned | VM duplicated to a new id. | VM Clone |
| `vm.create` | VM Created | New VM created. | VM Create |
| `vm.delete` | VM Deleted | VM and disks destroyed. | VM Delete |
| `vm.pause` | VM Paused | VM suspended. | VM Pause |
| `vm.restart` | VM Restarted | VM rebooted. | VM Restart |
| `vm.resume` | VM Resumed | Suspended VM resumed. | VM Resume |
| `vm.shutdown` | VM Shut Down | Graceful power off. | VM Shutdown |
| `vm.snapshot_create` | VM Snapshot Created | Snapshot taken, optionally with RAM. | Snapshot Create |
| `vm.snapshot_delete` | VM Snapshot Deleted | One snapshot removed, guest untouched. | Snapshot Delete |
| `vm.snapshot_rollback` | VM Snapshot Rolled Back | VM reverted to a snapshot, discarding everything since. | Snapshot Restore |
| `vm.start` | VM Started | VM started. | VM Start |
| `vm.stop` | VM Stopped | Hard kill, not graceful. | VM Stop |
| `metrics.maintain` | Metrics Maintained | Hourly housekeeping: rolls up samples and deletes data past retention. Feeds both charts and alert rules. | Usage Cleanup |
| job status `queued` | queued | Job row exists, not started. | Waiting |
| job status `running` | running | Handler executing. | Running |
| job status `succeeded` | succeeded | Handler finished without raising. | Done |
| audit result `ok` | ok | The action completed without being blocked or erroring. | Complete |
| alert state `resolved` | Resolved | The condition stopped being true, or the rule was deleted or disabled. | Cleared |

---

## Warnings

| Identifier | Current label | What it actually means | Suggested label |
|---|---|---|---|
| `app.reaped` | App Removed | The poller found the container gone from Proxmox and deleted Proxploy's record on its own. Nobody removed anything through Proxploy. | App Unlink |
| job status `canceled` | canceled | A user stopped the job before it finished. | Canceled |
| job status `interrupted` | interrupted | Proxploy restarted mid-job. Outcome unknown, cannot resume. | Interrupted |
| `job.interrupted` notifier | "Proxploy: N job(s) interrupted by restart" | One-time summary after a restart covering every interrupted job. | Tasks Interrupted |
| alert firing `cpu_pct`/`mem_pct`/`disk_pct` | e.g. "host-02 CPU > 85% for 5m" | Value stayed past the threshold for the full duration. | Keep as is |
| alert firing `host_offline` | e.g. "host-02 is offline for 5m" | Host unreachable for at least the configured duration. | Host Offline |
| alert firing `backup_failed` | e.g. "host-02: last backup run failed" | The most recent finished backup job failed. | Backup Failed |
| alert severity | info / warning / critical | Chosen per rule by the admin. | Keep as is |

---

## Errors

| Identifier | Current label | What it actually means | Suggested label |
|---|---|---|---|
| `app.migrate` | App Migrated | Written for BOTH a refused migrate (self-target guard, `result: denied`) and every real one: `api/apps.py` passes `action="app.migrate"` to `enqueue_and_audit`, so a successful request carries `result: ok` and a job id. `migrate.app` is the JOB KIND, not a second audit action. | App Migrate |
| `schedule.disable` | Schedule Disabled | Always the system, never a user. The scheduler turned a schedule off because it could not run it. | Schedule Auto-Disable |
| audit result `denied` | reuses the success label | A destructive action was blocked by permissions or a failed typed confirmation. Nothing happened. | Title: prefix with "Blocked", e.g. Blocked Host Disconnect. Result cell: Refused |
| audit result `error` | error | The handler raised before finishing. | Error |
| job status `failed` | failed | The handler raised. The job's error field carries the reason. | Failed |
| host status `unreachable` | unreachable | Last poll of the host's API failed. | Host Unreachable |
| HTTP 401 | "authentication required" | Session or key missing, expired or wrong. | Session Expired |
| HTTP 403 entitlement | `entitlement_required` plus per-site toast | The current plan does not include this feature. Wording differs per call site. | Plan Required |
| HTTP 403 role | "forbidden" | The user's role or key scope does not permit this. | Permission Denied |
| HTTP 409 confirm | "Type the name to confirm." | A destructive action needs the target's name typed back. | Confirmation Required |
| HTTP 409 self-target | "\<name\> is the container Proxploy itself runs in..." | The action targets Proxploy's own host, app or VM. | Self Protected |
| HTTP 502 Proxmox | Proxmox's error text, verbatim | Host unreachable, token lacks a privilege, or Proxmox errored. | Proxmox Error |
| `JobFailed` messages | e.g. "host 12 not found" | A handler hit a specific expected problem and stopped cleanly. | Keep the specific text |
| `notify.error` toasts | e.g. "Could not cancel that job." | Hardcoded UI copy when a mutation fails. | Keep as is |

Toast bodies stay full sentences. The two-word rule applies to labels, not to
the error text underneath them. HTTP 502 keeps Proxmox's own message under the
"Proxmox Error" label so the source is clear.

---

## The seven that were actively misleading

1. **`app.migrate` read "App Migrated"** on a row that might be a refusal.
   An earlier draft of this list said the identifier was refusal-only and that
   real migrations logged as `migrate.app`; neither half is true. `api/apps.py`
   passes `action="app.migrate"` to `enqueue_and_audit` for every real
   migration, and `migrate.app` is the job kind. Both identifiers therefore
   carry App Migrate, because they are one event seen twice, and the Blocked
   prefix carries the refusal. Labelling `app.migrate` "Migration Refused" made
   a successful migration read "Migration Refused Requested".

2. **`schedule.disable` read like a user flipped a switch.** It is always the
   scheduler disabling something it cannot run. Now Schedule Auto-Disable.

3. **Every denied row reused its success label.** Fixed at render time by
   prefixing "Blocked", not with new map entries.

4. **`app.reaped` read "App Removed"**, identical in voice to two real user
   actions. It is the poller deleting its own record. Now App Unlink, the same
   label as `app.forget`, decided on the grounds that both are Proxploy
   dropping its record and the difference is not worth two labels. See the
   collisions section below for what that costs.

5. **`metrics.maintain` read "Metrics Maintained"** and said nothing. It is
   retention housekeeping over the usage history that both charts and alert
   rules read. Now Usage Cleanup.

6. **`storage.upload` read "Uploaded To Storage"**, the only label that broke
   the pattern. Now File Upload.

7. **A failed read of a guest's NIC list is its own identifier.** It is
   `network.guest_config_read` (`api/network.py:112`), not `network.guest_config`
   audited with `result: error` as an earlier draft of this list claimed. All
   three network config identifiers share the label "Network Edit", so a failed
   read reads as a failed edit. That is a known, accepted cost of collapsing
   them, recorded at the map entry.

---

## Collisions this pass removed

- `app.forget` and `app.reaped` were App Remove and App Removal. Both now read
  App Unlink. This list originally argued they must differ, on the grounds that
  unlink means the container is still running and only Proxploy stopped tracking
  it, while a reap means the container is actually gone. That distinction was
  judged not worth two labels: either way Proxploy has dropped its record.
  The accepted cost is that the feed no longer says whether the container still
  exists, so the code carries a comment saying this is deliberate and not to
  restore the distinction from this document without asking. What still holds is
  that neither collides with `app.uninstall`, the one that destroys the
  container.
- `app.migrate` and `migrate.app` were App Migrate and App Migration. Both now
  read App Migrate, because they are the same event twice over: the audit action
  and the job kind it enqueued. Not "Migration Refused", see item 1 above.
- `app.stop` and `vm.stop` were inconsistent (App Stop vs VM Force Stop) for the
  same hard-kill behaviour. Now App Stop and VM Stop.

---

## Two structural fixes

1. **Denied rows must not reuse success labels.** Prefix "Blocked" at render
   time whenever `result` is denied. One change covers every destructive action,
   now and future.

2. **Keep the derived fallback for unmapped identifiers.** New actions will keep
   arriving and a half-map looks worse than no map. The fallback is the safety
   net, the map is the polish.

---

## Open, found while applying this

1. **`catalog.classify_backlog` -> "Compatibility Check" is misleading.** It
   reads as compatibility with the operator's own hosts or cluster, and a real
   operator read it that way. The job never touches Proxmox: it fetches the
   community-scripts shell scripts from `raw.githubusercontent.com` and reads
   them statically, counting `build_container` calls and looking for
   interactive `read`/`whiptail` prompts, to decide whether a store entry can
   install unattended. Host availability is irrelevant to it, and it reports
   "succeeded" with "classified 0" whenever the backlog is empty, which is
   correct and reads like a failure.

   DECIDED: keep "Compatibility Check". Alternatives naming what it reads
   ("Script Check", "Store Scan") were considered and turned down. Recorded
   here because the label genuinely did mislead a reader once, so anyone
   meeting that confusion again should know it is a known, accepted one and
   not a fresh finding.

2. **Past tense labels: settled, rule 2 now carves them out.** "App Vanished"
   became "App Unlink". "Backup Failed", "Job Interrupted" and the status words
   "Canceled" and "Interrupted" stay past tense, and rule 2 above now says when
   that is allowed instead of being quietly broken by four labels.

3. **Rule 1 now has exactly one exception.** After folding the network read
   into "Network Edit", the API Key pair is the only label longer or shorter
   than two words. A test enforces this with a one-entry allowlist, so adding
   an exception is a deliberate test change.
