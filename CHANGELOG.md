# Changelog

## 1.1.0 (2026-08-30)

79 commits since the 1.0.0 release build.

### App Store and installs

- Install scripts' own prompts are now recovered from the upstream script and asked in the install dialog, instead of the install refusing anything interactive.
- A prompt is judged sensitive by the sentence it asks, not by the variable name it assigns into, which is what catches an admin password stored in `ziti_pwd` or a JWT read into a variable called `prompt`.
- Sensitive answers never enter `jobs.params`. They are encrypted into their own store and the job carries only a handle, so redaction stopped being load bearing.
- A job transcript is scrubbed by value rather than by key name, so a secret cannot survive in a log line that happens to be worded differently.
- A prompt that can abort the install is recorded as one and is never auto-answered.
- Yes or no questions are asked with Yes and No buttons rather than a tick box, version questions are no longer treated as consent gates, and a prompt that says it can be skipped can be skipped.
- One question per question, not one per variable the script happens to use.
- The install dialog has a shape instead of a stack of fields.
- Store cards lost their chips, shrank, and sort by Popularity first.
- A catalog refresh now says what it changed about the set of installable apps.
- An app with no upstream logo gets an identity of its own, or its own image.

### Apps

- The Logs menu item shows the container's actual logs.
- The update ring stopped pretending to measure progress, and a working update is no longer painted red.
- An app URL that cannot be read no longer fails an install that actually worked.
- An interrupted install is reported as unknown rather than failed, and it blocks a second install of the same app instead of racing it. After a restart, the operator is told what really happened.

### Backups and storage

- Backup run history, with system maintenance jobs alongside it.
- A restore can choose the pool it lands on. An in-place restore stays on the pool the guest already lives on.
- The verified card is now Backup Integrity, with a bigger stat.
- An NFS share can carry its own mount options, and editing a datastore shows what it is configured with.

### Hosts, machines, and settings

- Adding a host happens in a dialog, from either the settings page or the hosts page, built like the install dialog.
- Node power moved to Lifecycle, the token band names the capability it always takes, and the script buttons are one group.
- VM boot order fields are sized, the switch is finished, and the machine gets a name.
- Settings forms that were inline are dialogs now, with a fuller teams table.
- Sessions and Trusted devices name the browser rather than showing a raw user agent.
- Storage bars line up with the CPU and RAM bars, and the host column gives its slack to the name column.
- An old `?section=schedules` link still lands on Maintenance.

### Accounts and access

- A real password policy, login lockout, and account recovery.
- Notifications use TLS by default and send from a real address.
- Console tickets are swept hourly rather than nightly, so a spent Proxmox ticket is not left at rest for a day.

### Plans and licensing

- The entitlement gates are armed: a real free tier, and a denied UI that says which plan a feature needs instead of failing quietly.
- Licence state is pushed over SSE, and a lapsed plan says why it lapsed.
- Pro is offered once, at the end of setup, and nowhere else.
- The `hosts.multi` gate is decided in one place rather than in each caller.
- The production entitlement root is trusted, key drift between the app, the API and the frontend fails the build, and the app refuses to start with no trusted root rather than trusting everything.

### Proxmox privileges

- The monitoring role is granted `VM.GuestAgent.Audit`.
- Every read path was swept for missing privileges, and the three it found are fixed.
- A missing Proxmox privilege is now a build failure rather than a runtime surprise.

### Security

- The DNS rebinding gap in the SSRF guard is recorded, and nanoid is bumped.
- The two items the security sweep left open are closed.

### Updates

- The update toast fires only when there really is an update, and it always links the changelog.

### Packaging and development

- A release ships an allowlist of what belongs in it, rather than an exclude list of what does not. The dev data directory, its master key, and macOS metadata files can no longer reach a published tarball.
- `build_release.sh` builds on macOS again. Three tar calls put the mode after the long options, which GNU tar accepts and bsdtar does not.
- The Playwright suite is alive again and runs against a free-tier install so denials are actually exercised.
- The middle of the role ladder has tests, which nothing covered before.
- The README is a public page, and the project ships the AGPL-3.0 license.
