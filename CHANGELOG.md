# Changelog

## 1.2.1 (2026-09-01)

5 commits since the 1.2.0 release build.

### Read this before upgrading

The update button does not work on 1.2.0 or anything older, and it cannot be
what brings this release in. Taking 1.2.1 needs one command on the box:

    curl -fsSL https://proxploy.com/install.sh | bash

That installs the missing piece. Every update after it runs from the app.

### Updates

- Self-update works. Pressing update on 1.2.0 swapped a progress bar in and
  then sat there forever, because the app runs as an unprivileged user that
  is not allowed to start the update, and the refusal was thrown away instead
  of shown. The app now writes the version it wants to a request file and a
  root owned watcher does the update.
- The watcher decides for itself which release channel a version comes from,
  reading it off the version already installed. The app asks for a version
  and nothing else, so a compromised app process cannot point a root process
  at a server of its own choosing.
- An update that cannot start says so straight away rather than appearing to
  begin.
- The update writes a log and a status file that outlive the restart, so the
  Updates card shows what the update is doing while it does it, and what went
  wrong afterwards if something did. Before this the app came back up with no
  idea an update had ever run.

### Install

- The installer no longer refuses a machine for not having python3 already,
  nine lines before it installs python3 itself. A minimal Debian 12, which is
  what a fresh container or a stripped template is, could not get past it.
- The check that confirms the app is serving waits for it instead of asking
  once. systemd calls a service active the moment it forks, so a slower box
  could finish a perfectly good install and be told nothing was serving.

### Packaging and development

- shellcheck can read install.sh again. One valid but unparseable line had
  been costing the whole file its static checking, and the checks that would
  have caught the two installer bugs above had been skipping rather than
  passing.
- The end to end journey follows the VM wizard through all seven of its
  steps, having still been clicking through the five it used to have.

## 1.2.0 (2026-09-01)

5 commits since the 1.1.0 release build.

### Read this before upgrading

Every install made before this release points at dev infrastructure. The
published installer defaulted to `PROXPLOY_ENV=dev`, because that default was
correct while the licence server at api.proxploy.com was not yet answering and
it was never flipped once it was. A box installed from proxploy.com therefore
wrote `PROXPLOY_ENV=dev` into `/etc/proxploy/proxploy.env`, licensed against
api.proxploy.dev and fetched its own updates from web.proxploy.dev.

Taking this release fixes that. `proxploy-update` rewrites `PROXPLOY_ENV=dev`
to `prod` in place, keeping a timestamped backup of the file beside it, and
every later update comes from proxploy.com. Re-running the installer does NOT
fix it: install.sh leaves an existing env file alone on purpose so a re-run
cannot clobber an operator's settings.

An operator who genuinely wants the dev pair adds `PROXPLOY_ENV_PINNED=1` to
the same file. It is checked first and is never overwritten. There is no
record of which URL a box was installed from, so a deliberate dev install
cannot be told apart from one that inherited the broken default, and the pin
is the way to say which is which.

The dev release channel keeps serving until every install has taken this
release. It is the only route to a box that has not yet been migrated.

### Virtual machines

- The create wizard covers the whole Proxmox create surface rather than seven
  fields: machine type, BIOS, EFI disk, TPM, guest agent, SCSI controller, the
  VirtIO driver ISO, disk bus and cache, CPU, memory and the network settings.
  A plain Linux VM is still the same few clicks, with the rarely touched
  settings behind a disclosure in each step.
- Windows 11 can be built and installed. It needs q35, OVMF, an EFI disk and a
  TPM, and none of those could be set before.
- An install ISO now boots ahead of the empty disk, so a new VM reaches the
  installer instead of stopping at "no bootable option or device found".
- An ISO can be mounted and ejected on an existing guest, from the row menu.
  The write refuses rather than overwrite an ide slot holding a data disk.
- A guest that is not running reads unknown for CPU, memory and network
  instead of reporting zero, and draws no graph line for a period it was not
  running. Allocations still read true, because what a guest is assigned does
  not stop being true when it stops.
- A newly created VM appears in the list in about a second rather than
  whenever the next poll happened to land.

### Proxmox privileges

- Every privilege Proxploy needs is granted by the onboarding script. Two were
  not: `Sys.Console`, which rode a flag wired to an unrelated checkbox and so
  was granted by accident or not at all, and `Datastore.AllocateTemplate`,
  which was in no role, meaning uploads could not work. `Pool.Allocate` and
  `VM.Config.CDROM` were added for the create wizard's resource pool field and
  for changing a guest's media.
- An existing install has its roles repaired automatically at boot, over the
  SSH key Proxploy already holds. Every repair is audited and notified: it
  widens Proxploy's own access and must never be invisible.
- A repair writes the union of the live role and what the product needs, never
  the product's list alone. `pveum role modify` replaces, so writing our list
  would delete privileges an operator added by hand.
- A short token is reported as a gap on the Hosts page instead of the host
  reading clean, because the gap probe and the setup script now read the same
  list.

### Storage

- Uploading an ISO reports real progress the whole way, including the long
  leg from Proxploy to the node, which previously sat silent for minutes.
- An upload can be cancelled at any stage, or left running in the background
  so the session stays free.
- An upload that stops because the server restarted says so instead of leaving
  a progress bar that will never move.
- The upload form opens on ISO rather than whichever content type Proxmox
  happened to list first, and follows the file that is picked, so an ISO is no
  longer filed as a container template.
- A finished upload appears in the datastore without a manual refresh, and the
  list keeps polling as a fallback when the event stream is down.

### Fixes

- Open Proxmox web UI adds the port when the stored address has none. Only the
  browser link was affected: every API path already defaulted to 8006.
- An explicit API timeout replaces the HTTP library's 5 second default, which
  a directory listing on a busy NFS datastore already exceeded.
- Node shell is on by default for a new host, a cluster peer included. An SSH
  key and install consent are still never inherited by a peer.
- Long values no longer widen the panel they sit in. A grid or flex child
  defaults to a minimum width of its content, so an ISO filename pushed its
  container open instead of being clipped.
- A meter with no reading draws no bar at all, rather than an empty track
  beside the word unknown that reads as a real measurement of nothing.

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
