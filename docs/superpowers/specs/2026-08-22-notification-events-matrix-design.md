# Notifications: an events matrix, not a channel list

Date: 2026-08-22

## Why

Adding a notification channel today asks the operator to name a thing, paste an
Apprise URL, and only then say which events reach it. That is backwards. Nobody
arrives wanting to create a channel; they arrive wanting to be told when a
backup fails, and they may not want anything delivered outside the app at all.

Three defects follow from the channel-first shape, and this design removes all
three rather than patching them:

* The form offers `app.updated`, which no backend code emits. Ticking it does
  nothing, forever.
* The form does not offer `alert.resolved`, which the backend does emit. The
  all-clear is unreachable through the UI.
* `notify.routing` is Pro, so on Free the event fieldset renders disabled while
  the component still posts `events: ['job.failed']`. A Free channel is
  therefore pinned to one event with no way to change it and can never receive
  an alert.

## Shape

A new rail group **Notifications**, replacing the single Notifications item
that currently sits under General, with two sections.

**Channels** lists what is configured, with an Add button at the top right that
opens the guided service picker (`services/notification_catalog.py`, already
built: 20 services, fields assembled server-side and validated against
Apprise's parser before storage).

**Events** is the matrix. Rows are notification types. Columns are a master
switch followed by one column per configured channel.

| Master | Boxes ticked | Result |
|---|---|---|
| off | any | never told, not even a toast |
| on | none | toast only |
| on | some | toast, plus delivery to those channels |

Zero channels is a supported, unremarkable state. The Events section is fully
useful with none configured: the master switches alone decide what the bell and
toasts say, which is what makes "I find the housekeeping notification annoying"
a one-click fix that never mentions the word channel.

## Registry

One row per notification type. Every job kind maps to exactly one row, so
nothing fires twice.

| Group | Row | Key | Job kinds | Default |
|---|---|---|---|---|
| Apps | App install failed | `app.install.failed` | `app.install` | on |
| Apps | App install succeeded | `app.install.succeeded` | `app.install` | on |
| Apps | App update failed | `app.update.failed` | `app.update` | on |
| Apps | App update succeeded | `app.update.succeeded` | `app.update` | on |
| Apps | App removal failed | `app.uninstall.failed` | `app.uninstall` | on |
| Apps | App removal succeeded | `app.uninstall.succeeded` | `app.uninstall` | on |
| Backups | Backup failed | `backup.failed` | `backup.run`, `backup.sync` | on |
| Backups | Backup succeeded | `backup.succeeded` | `backup.run`, `backup.sync` | on |
| Backups | Restore failed | `backup.restore.failed` | `backup.restore` | on |
| Backups | Restore succeeded | `backup.restore.succeeded` | `backup.restore` | on |
| Housekeeping | Housekeeping failed | `housekeeping.failed` | `catalog.refresh`, `catalog.classify_backlog`, `metrics.maintain`, `backup.delete`, `backup.prune` | **off** |
| Housekeeping | Housekeeping succeeded | `housekeeping.succeeded` | same | **off** |
| Other jobs | Job failed | `job.failed` | every other kind | on |
| Other jobs | Job succeeded | `job.succeeded` | every other kind | on |
| Other jobs | Job cancelled | `job.canceled` | any kind | on |
| Other jobs | Job interrupted | `job.interrupted` | any kind | on |
| Alerts | Alert triggered | `alert.fired` | not a job | on |
| Alerts | Alert resolved | `alert.resolved` | not a job | on |
| Audit | Audited action failed | `audit.error` | not a job | on |

The four `job.*` keys keep the spellings they already have in stored
`notification_channels.events` rows, so no existing subscription changes
meaning. `app.updated` is not in the registry; a channel that has it ticked
simply drops it on first edit, which costs nothing because it never fired.

Nineteen rows rather than a row per job kind: the twenty-two kinds nobody asked
to be told about individually (VM power actions, snapshots, network apply,
storage upload, host reboot, migration) fall under Other jobs, and the catch-all
means today's bell behaviour is preserved rather than quietly narrowed. Adding a
named row later needs no migration, because a row ships with its own default.

### Cancelled and interrupted are global, not per category

Only the failed and succeeded outcomes are categorised. Cancel and interrupt are
rare, uninteresting per category, and would double-fire against a category row
if they were categorised. Each job kind therefore owns exactly two of the four
outcomes, and the other two belong to the two global rows.

### A scheduled run is not its own row

Cron success and failure were requested as separate types, but scheduled-ness is
orthogonal to kind: `schedules.py:198` enqueues an ordinary job, and that job's
kind already owns a row. A scheduled backup that fails fires "Backup failed",
and the notification body names the schedule it came from. A separate
"Scheduled run failed" row would fire alongside it for the same event.

The two built-in system schedules (`catalog.refresh` and `metrics.maintain`,
shown as "Usage cleanup") are the Housekeeping rows, and are the only rows that
ship off. They succeed nightly and have nothing to say.

### Node unreachable stays on the Alerts page

Host unreachable and cluster quorum loss are already seeded alert rules
(`services/alerts.py:115`, `host_offline` at five minutes, critical). They reach
notifications as `alert.fired`. Events carries "Alert triggered" and "Alert
resolved" and links to Alerts for which conditions raise one. Giving node
unreachable its own row would configure one condition in two places, free to
disagree.

## Data

**The checkbox columns need no migration.** A cell is exactly
`notification_channels.events` transposed, so the existing column stores it.

One wrinkle is handled deliberately: an empty `events` list means "every event"
server-side (`notifier.channels_for`). Under a matrix an empty list would read
as "no boxes ticked", the opposite. A channel whose list is empty therefore
renders fully ticked, and materialises the concrete list on its first edit.
Every channel configured before this change keeps behaving identically, and the
server semantics are untouched.

**The master switches are the only new state.** One `AppSetting` key,
`notifications.type_overrides`, holding a `{key: bool}` map of explicit operator
choices only. Anything absent uses the registry's own default. Storing overrides
rather than the full enabled set is what lets a row added next year arrive with
the default we ship, instead of being silently off for everyone who had saved
the page once.

## Entitlements

| Surface | Flag | Tier |
|---|---|---|
| Channels section | `notify.channels` | Free |
| Master switches | none | Free |
| Per-channel columns | `notify.routing` | Pro |
| Toasts and bell | `notify.inapp` | Free |

On Free the channel columns are locked and an enabled type reaches **every**
configured channel, which is the `events: []` semantics the server already has.
"No event routing" therefore means everything goes everywhere, which is the
sense the tier table intends, and is the correct fix for the pinned-to-
`job.failed` defect rather than a workaround for it.

## Emitters

`jobs/backend.py:381` currently discards the job kind and emits `job.{status}`.
It maps (kind, status) through the registry and emits the row's key instead.
This is the whole of the job-side change; no new call sites.

`audit.error` is the one genuinely new emitter: `services/audit.py::write_audit`
gains a notification when `result="error"`.

`notifier.notify` and `channels_for` are unchanged. The master switch is applied
before the fan-out, so a disabled type reaches neither the bus nor Apprise.

## Testing

* Every kind in `HANDLERS` (33 today) maps to exactly one registry row. Fails
  the day someone adds a job kind and forgets this file.
* A named kind fires one event, not two.
* Master off suppresses both the toast and the Apprise send.
* A channel with an empty `events` list renders every box ticked, and its first
  edit writes a concrete list that preserves what it had been receiving.
* On Free, an enabled type reaches every channel.
* The registry contains no key that no emitter can produce, which is the
  `app.updated` defect as a permanent test.

## Out of scope

Per-user notification preferences (channels stay installation-wide), digest and
throttling, and deep-links in the notification body. All three are worth doing
and none of them is this change.
