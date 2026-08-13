# App Store installs: Default and Advanced modes, and an optional CTID

Date: 2026-08-13
Status: approved, ready for an implementation plan

## What this supersedes, and what it does not

This supersedes `2026-08-13-addon-delegated-installs-design.md` **in principle**.
That document proposed that Proxploy answer an installer's prompts itself, from
a hand-curated allowlist, with no human present. Its own non-goals said "no
human is required". That premise is rejected: the human belongs in the loop,
choosing options in a form, not represented by a hidden answer table.

**Proxploy never auto-answers a prompt on the operator's behalf.** Either the
operator chose the value in a form, or the operator answers it live. There is no
third path. This is the governing rule of all install work from here.

The superseded document's *analysis* remains sound and is carried forward
verbatim where relevant: the unpinned `tools.func` problem, artefact
verification rather than exit status, and the finding that the five
addon-delegating apps build an empty container that upstream reports as success.

### Scope of THIS spec

Two pieces only:

1. Default and Advanced install modes, with a container-customization form.
2. CTID becomes optional, validated for collisions.

### Deferred to their own specs

- Curated per-app answer schemas for app-specific prompts.
- The live terminal fallback for uncurated apps.
- Addon-payload execution for the five empty-container apps.
- Per-app artefact verification.

Until those land, the five (`coolify`, `dockge`, `dokploy`, `komodo`,
`runtipi`) stay not-installable with their accurate reason: "no install script
upstream; it installs via an addon script run inside the container". They are
not dragged into this scope to make them green.

## Why this is mostly plumbing

The execution mechanism already exists and is unused.
`services/appstore.py::run_install` already does:

```python
env = {"TERM": "xterm", "mode": "default", "PHS_SILENT": "1"}
for key, val in overrides.items():
    env[f"var_{key}"] = str(val)
env["var_ctid"] = str(ctid)   # last, so it wins over an overrides entry
```

`InstallDialog` has always sent `overrides: {}`. This spec fills it.

`VmCreateWizard` already implements this form's shape for VMs: it queries
`/storage`, picks bridge and VLAN, and collects node, cores, memory and disk.
`/network/bridges` exists as a live passthrough. Follow that pattern rather than
inventing a second one.

## The two modes

`InstallDialog` gains a Default/Advanced choice with **Default preselected**.

- **Default**: proceeds on the app's own defaults. No questions **that have an
  honest default**.
- **Advanced**: expands the form in place, same dialog, same submit.

"No questions that have an honest default" is deliberate wording, not a hedge.
On a host with two `rootdir` pools there is no default to proceed on: build.func
has none, and this spec does not invent one. So Default asks that one question,
because only the operator can answer it. One candidate means no question and
Default stays a single click, which is the common case.

The answer is **remembered per host**, so it is asked once rather than on every
install. It is stored per host and per content type, since a node can have one
`rootdir` candidate and several `vztmpl` ones.

Remembering must not become deciding silently. Two rules keep it visible:

- The Default confirmation **displays** the pools it will use, as text rather
  than a question. The operator always sees where the container is going.
- Advanced shows the picker **prefilled** with the remembered value, so it is
  changeable rather than buried.

A remembered pool is re-validated against the node's content list at install
time. If it no longer exists or no longer carries the required content, the
question is asked again. It is never silently replaced with another pool.

Install always opens the dialog. A dialog-free Default was considered and
rejected: the Store card's Install button is ~25px on a card that itself opens
a popup on click, so a mis-aimed click would create a container and run a
third-party script as root with no confirmation and no undo.

## Consent moves from per-install to per-host

Today every install requires ticking "I understand this runs as root on the
node". That becomes a **per-host acknowledgement, recorded once**, so Default is
genuinely one deliberate action rather than one action plus a repeated checkbox.

It hangs off the existing enrolment moment: `HostForm.tsx:180`, "Enable App
Store installs (SSH key enrolment)". Enrolling an SSH key for installs *is* the
grant of root execution, so that is where the acknowledgement belongs.

New nullable column on `Host` recording the acknowledgement and when it was
given. An install targeting a host without it must obtain it before proceeding.

### Existing hosts: backfill, deliberately

Hosts enrolled before this column exists are **backfilled as acknowledged, if
and only if they have App Store installs enabled** (an enrolled SSH key). The
reasoning, which belongs in the migration as a comment and not merely here:
those operators already performed the SSH key enrolment, which is the same
grant, and they ticked the per-install box on every install they ran. Requiring
a re-tick would be friction that surfaces no new information.

Hosts **without** installs enabled are not backfilled. They never granted
anything to backfill.

This must be an explicit, commented decision in the migration, not an accident
of a default value.

## The form

### Core, always visible

| Field | Variable | Default from |
|---|---|---|
| CTID | `var_ctid` | blank (next available) |
| Hostname | `var_hostname` | app name |
| CPU | `var_cpu` | `default_cpu` |
| RAM (MB) | `var_ram` | `default_ram_mb` |
| Disk (GB) | `var_disk` | `default_disk_gb` |
| OS | `var_os` | `default_os` |
| OS version | `var_version` | `default_os_version` |
| Target host | n/a (request field) | sole host, else chosen |
| Container storage | `var_container_storage` | see below, always sent |
| Template storage | `var_template_storage` | see below, always sent |
| Bridge | `var_brg` | `vmbr0` upstream |
| Unprivileged | `var_unprivileged` | `1` |

Note **two** storage variables, not one. There is no `var_storage`. A single
"Storage pool" field would be wrong; either expose both or set both from one
control, deliberately. They also select on different content types: `rootdir`
for the container, `vztmpl` for the template, so a host can have one candidate
for one and several for the other.

### Storage is a live bug, and sending the variables does not fix it

**Investigated and confirmed against the pinned `build.func`.** An earlier draft
of this spec said "always send both storage variables" and treated that as the
fix. That was wrong, and the reason is worth recording because it is the same
mistake in a new place: the sentence was plausible and nobody had read the
source.

`ensure_storage_selection_for_vars_file` (`build.func:1954`) reads the **vars
file**, not the environment:

```bash
tpl=$(grep -E '^var_template_storage=' "$vf" | cut -d= -f2- || true)
ct=$(grep -E '^var_container_storage=' "$vf" | cut -d= -f2- || true)
```

So `var_container_storage` in `env` is not consulted on this path at all.
Sending it changes nothing.

**What actually happens today.** We send `mode=default`, which reaches
`build.func:3468` and, uniquely among the mode branches, runs
`defaults_target="$(ensure_global_default_vars_file)"`. That file is `touch`ed
empty on a fresh host, both greps miss, and `choose_and_set_storage_for_file`
runs for each class. With one candidate it auto-picks. With two or more it calls
`select_storage`, which builds a whiptail menu. With no TTY whiptail fails,
`|| exit_script` fires, and `exit_script` (`core.func:964`) does `exit 0`.

So it is **not a hang. It is a silent `exit 0`.** `run_install`'s post-check
catches it and reports "install script exited 0 but CT N does not exist", which
is accurate and says nothing about storage. The only breadcrumb is
`User exited script` in the job log.

`PHS_SILENT` and `mode` do not suppress it. Upstream has `is_unattended()`
(`core.func:1180`), which returns true for `mode=default`, `PHS_SILENT=1` and
`! -t 0`, and guards `check_storage_health` with it, but never calls it on the
storage-selection path. That is an upstream oversight, not our misconfiguration.

A populated `default.vars` does not rescue it either: that branch sets
`TEMPLATE_STORAGE`/`CONTAINER_STORAGE` but not `var_*_storage`, and
`build_container` (`build.func:4531`) then clobbers both back from the empty
`var_*`, landing in `select_storage` a second time.

### The fix, which ships as its own bugfix ahead of the form

Two changes, neither sufficient alone:

1. **`mode=generated` instead of `mode=default`.** The `generated` branch
   (`build.func:3517`) is byte-identical to `default` except for `METHOD=` and
   the absence of the `defaults_target` line, so it never calls
   `ensure_storage_selection_for_vars_file`. `METHOD` is assignment-only and
   reaches nothing but the telemetry payload. `is_unattended()` has no
   `generated` case but falls through to its `PHS_SILENT=1` branch, so
   unattended behaviour elsewhere is preserved.
2. **Then send both storage variables**, which `build.func:4531` reads and
   `create_lxc_container` accepts via `resolve_storage_preselect`.

This changes every install, including single-storage hosts that work today: they
move from build.func auto-picking to us sending the value explicitly. That is
better, but it means our resolution must be correct for single-pool hosts too,
not only multi-pool ones.

**A supplied value must be validated against the node's real content list.**
`resolve_storage_preselect` returns 238 for a pool the node's content does not
include, after which `build.func:6553`'s `while true` spins with an empty body:
a genuine infinite hang, which our 1800s SSH timeout would surface as
`TimeoutError` with an empty message. Sending an unvalidated pool name is worse
than sending none.

### The backend never picks a pool

Which pool a container lives on is a question, and this spec's governing rule is
that Proxploy never answers a question on the operator's behalf. Auto-picking
"the one with the most free space" is answering it.

Resolution order at install time:

1. The operator's choice for this install, if the form supplied one.
2. The host's remembered choice, if set and **still valid** for that content type
   on that node.
3. The sole candidate, if the node has exactly one for that content type. This
   is not a pick; there is nothing to choose.
4. Otherwise **refuse**, with a message naming the candidates.

Until the form exists, step 4 is what a multi-pool host gets. That is a strict
improvement on today's silent `exit 0`, and it stops being a refusal the moment
the picker lands.

### Storage is not optional, and this is the sharpest finding in the spec

Leaving the storage variables unset does **not** fall back to a default. From
`build.func` around line 880:

```bash
# If only one storage exists for the content type, auto-pick. Else always ask
count=$(pvesm status -content "$content" | awk 'NR>1{print $1}' | wc -l)
if [[ "$count" -eq 1 ]]; then
  STORAGE_RESULT=<the only one>
else
  select_storage "$class" || return 150     # INTERACTIVE
fi
```

One candidate auto-picks. **Two or more prompts interactively**, which in a
non-interactive SSH install means the run hangs or dies on a picker nobody can
see.

So the form **always sends both storage variables**, in Default mode as well as
Advanced. Relying on the auto-pick would make installs work on single-storage
hosts and hang on everyone else, which is the worst possible distribution of a
bug: invisible in development, reproducible only on the more serious
deployments.

`var_brg` is different and genuinely safe unset: `build.func:1104` is
`BRG=${var_brg:-"vmbr0"}`. The form still offers it, but blank is defensible
there in a way it is not for storage.

**Verify whether this is already broken.** `overrides` is empty in every install
today, so `var_container_storage` is never set, so a host with two or more
`rootdir` storages should already be hitting that picker. Either current installs
fail on multi-storage hosts, or something upstream of this (`PHS_SILENT`,
`mode=default`) suppresses it. Establish which before building, because if it is
a live bug it is a bugfix that need not wait for the form.

**This rule is a test, not an implementation detail.** It has the same
silent-ignore failure mode as the variable-name pinning, and the same shape of
seductive future "optimization": omitting storage when the operator did not
change it looks like sending less noise, and reintroduces the hang, and only on
multi-storage hosts, so it passes every test written on a single-storage
development box. The test asserts that a **Default** install, with no user input
at all, produces an `env` containing both `var_container_storage` and
`var_template_storage`. See Testing.

### The picker must offer real candidates, per content type, per host

Because both variables are always sent, the form has to send *valid* ones. It
cannot ship a free-text box or a guess.

The form queries the storages available on the **selected host** and offers them
filtered by content type:

- Container storage: pools whose content includes **`rootdir`**
- Template storage: pools whose content includes **`vztmpl`**

Filtering by content type is not cosmetic. Offering every pool for both fields
would let an operator pick a `vztmpl`-only pool as the container rootfs, which
fails at `pct create` time with a raw Proxmox error, after the form told them it
was fine.

No new endpoint is needed. `/storage` already returns `content: string[]` per
row (`api/storage.py::_content_list`, which normalises PVE's raw
`"iso,vztmpl,backup"` string), and `VmCreateWizard`'s `StorageRow` type already
carries it. This is a client-side filter over data the app already fetches.

Storages are per host, so the candidate list **re-queries when the target host
changes**, exactly as the CTID collision check does. Selecting a storage that
exists on host A and then switching to host B must not silently submit a pool
that does not exist there.

### Collapsed "Advanced options"

`var_gpu`, `var_nesting`, `var_tags`, `var_timezone`, `var_ssh`,
`var_ssh_authorized_key`, and static networking: `var_net`, `var_gateway`,
`var_vlan`, `var_mtu`.

`var_gpu` and `var_nesting` are the highest-demand options in the whole form:
GPU passthrough is what Plex and Jellyfin need for hardware transcoding, and
nesting is what Docker-based apps need to run containers inside the LXC. They
are also safe, being booleans that add capability rather than constrain
reachability.

### Validation in the collapsed group

The collapsed group needs light validation, because static networking is where
an operator can lock themselves out of a container they just created.

- `var_net`: blank means DHCP. This is upstream's own behaviour, not our
  convention: `build.func:1106` is `NET=${var_net:-"dhcp"}`. State it in the UI
  so blank does not read as broken.
- `var_net` when non-blank: CIDR format.
- `var_gateway`: IP address format.
- `var_mtu`: integer in a sane range.
- `var_vlan`: integer 1-4094.

Format validation only. We do not attempt to verify a gateway is reachable.
The goal is that the collapsed group cannot *quietly* produce an unreachable
container through a typo.

`var_gpu` and `var_nesting` need no validation beyond being booleans.

## Defaults come from the script, never from metadata

Prefill from the discovery-parsed columns `default_cpu`, `default_ram_mb`,
`default_disk_gb`, `default_os`, `default_os_version`, which
`services/catalog.py::parse_ct_script` reads out of `var_cpu="${var_cpu:-2}"`
and friends in the file that actually runs.

**Not** from `install_methods[].resources` in the cached PocketBase metadata,
for three reasons:

1. It is wrong where the two disagree. Measured on the real catalog, they agree
   everywhere except addon-style entries, where metadata carries zeros:
   `dockge` is 2/2048/18 in the script and **0/0/0** in metadata.
2. It would breach the presentation-only rule, which is structurally enforced in
   `catalog_metadata.apply_writable_fields` and exists precisely because
   metadata answering a scripts-owned question caused the five-slug near-miss.
   Feeding metadata into `var_cpu` is a softer violation of the same shape.
3. The script's own defaults are what actually happens if the operator changes
   nothing, which makes the form an honest preview rather than a second opinion.

Metadata's one real advantage, per-method resources for multi-method apps such
as `syncthing` and `redis`, matters only when install-method choice is surfaced,
which is deferred.

## CTID becomes optional

Requiring a CTID today is a bug: `InstallDialog`'s `canSubmit` includes
`ctid.trim() !== ''`.

**Blank** means the installer assigns the next available ID.
`build.func:1083` is `local requested_id="${var_ctid:-$NEXTID}"`.

**Typed** is validated in the form against the selected host before submit,
with an inline error naming the collision and Install disabled while it stands.
IDs are per-host, so the check re-runs when the target host changes.

**The backend is the real gate.** `run_install` already refuses via `_lxc_ids`
and that stays authoritative: a guest can be created between form validation and
submit, and client-side validation is bypassable. The form check is a friendly
early warning, not the enforcement.

### The blank-CTID contract is absence, not empty string

When no CTID is given, `var_ctid` must be **absent from the environment**, not
present and empty.

`build.func:1083` uses `${var_ctid:-$NEXTID}`, whose colon form falls through on
unset *or* empty, so an empty string happens to work today. But `build.func:1086`
separately branches on `[[ -n "${var_ctid:-}" ]]`, and a future change to the
non-colon `${var_ctid-...}` would make empty and unset behave differently.
Asserting absence is the contract that survives both readers.

Note this inverts the current code: `run_install` sets `var_ctid` last
unconditionally. It must now set it last **only when one was supplied**, keeping
the win-over-overrides property for the typed case.

## The variable-mapping test is the most important test in this spec

A wrong variable name does not error. The installer simply ignores it, uses its
own default, and reports success. The operator gets defaults while believing
they got their choices, and nothing anywhere says otherwise. `var_storage`
versus `var_container_storage` is exactly this class: it reviews cleanly and
fails on hardware.

So the field-to-variable map is pinned in a test against the real name list
extracted from `build.func`. The authoritative set, as of
`3d9a7c25d68913a5f91e7ae34107c29da3fbbccf`:

```
var_apt_cacher var_apt_cacher_ip var_brg var_container_storage var_cpu
var_ctid var_disk var_fuse var_gateway var_github_token var_gpu var_hostname
var_http_no_proxy var_http_proxy var_ignore_disable var_ignore_os_mismatch
var_inherit_host_ca var_install var_ipv var_key var_keyctl var_mac var_mknod
var_mount_fs var_mtu var_nesting var_net var_ns var_os var_post_install
var_protection var_pw var_ram var_sdn_vnet var_searchdomain var_ssh
var_ssh_authorized_key var_tags var_template_storage var_timezone var_tun
var_unprivileged var_val var_verbose var_version var_vlan
```

Every variable the form emits must appear in that set. A typo or an upstream
rename fails a test rather than silently sending an override into the void.

The list is pinned as a fixture rather than fetched at test time, so the suite
stays offline and deterministic. Refreshing it is a deliberate act with a
visible diff.

## Testing

- Every emitted variable name is in the pinned `build.func` set.
- Container storage maps to `var_container_storage`, not `var_storage`.
- A blank CTID produces an environment with **no** `var_ctid` key at all.
- A typed CTID reaches `env` and is set last, so it wins over an `overrides`
  entry of the same name.
- A colliding CTID is blocked in the form and rejected by the backend
  independently, proven separately.
- Defaults prefill from the script-parsed columns; a row whose metadata
  disagrees (use `dockge`, 2/2048/18 against 0/0/0) prefills the script values.
- Static networking format validation rejects a malformed gateway, CIDR, MTU
  and VLAN; blank `var_net` is accepted and documented as DHCP.
- **A Default install with no user input produces an `env` containing both
  `var_container_storage` and `var_template_storage`.** Named as a regression
  test, not folded into a broader assertion, because the regression it prevents
  is a future change that omits storage when the operator did not touch it. That
  change would look like a tidy-up, would pass on any single-storage host, and
  would hang installs only where there are two or more candidates.
- The container storage picker offers only pools whose content includes
  `rootdir`, and the template picker only those including `vztmpl`. A pool
  valid for one must not be offered for the other.
- Changing the target host re-queries the storage candidates, and a selection
  that does not exist on the newly selected host is not submitted.
- **`mode=generated` is sent, never `mode=default`.** Pinned by name, with the
  reason in the assertion, because reverting it silently reintroduces the
  interactive picker. Note `test_appstore_install.py:157` currently pins the
  exact command string including `mode=default` and must be updated in the same
  change.
- The backend refuses, with the candidates named, when a host has two or more
  pools for a content type and neither the form nor the host's remembered choice
  supplied one. It must never auto-pick.
- A remembered pool that no longer carries the required content causes the
  question to be asked again, not a silent substitution.
- A supplied pool is validated against the node's content list before being
  sent, since an invalid one reaches `resolve_storage_preselect`'s 238 path and
  hangs `build.func` in an empty `while true`.
- Single-candidate hosts still install correctly under `mode=generated`, which
  is the regression this change could plausibly cause and the one no
  multi-storage test would catch.
- A host without acknowledgement cannot install; a backfilled host can.
- The migration backfills only hosts with installs enabled.
- Advanced values survive the round trip from form to `env`.

## Hardware verification

Everything above is testable against fakes, and the fakes are exactly what hid
the storage problem: the e2e harness models `pct` over SSH but not
`pvesm status`, so nothing in the suite exercises `build.func`'s storage
resolution at all. A green suite here proves we **send** the right variables. It
cannot prove a real node **does** the right thing with them.

Three checks require real hardware and a host with **at least two pools carrying
`rootdir` and at least two carrying `vztmpl`**. A single-storage host cannot
exercise any of them, which is the whole point.

1. **Default install, no user input, does not reach `select_storage`.** Pass:
   the container is created and the job completes. Fail: the job hangs, times
   out, or logs a storage prompt.
2. **An explicitly chosen non-default storage is honoured.** Choose a container
   storage other than the one a single-storage host would auto-pick. Pass:
   `pct config <ctid>` shows the rootfs on the chosen pool. Sending the variable
   is not the claim; the container landing there is.
3. **A `vztmpl`-only pool is not offered as rootfs.** Confirm the container
   storage picker excludes pools whose content lacks `rootdir`. Provable in a
   browser against a real host's storage list without running an install.

These are recorded in `docs/12-hardware-verification.md` alongside the other
standing items (cross-host migration, network apply, whole-storage prune, the
monitoring-token privilege paths, and the phase-4 install checks that are proven
only as far as the command string). Do not mark this spec verified on the
strength of the automated suite alone.

## Unchanged constraints

- Scripts stay SHA-pinned. Metadata is presentation-only and never decides
  installability, type, or now, resource defaults.
- The flat 2-`api.github.com`-call discovery ceiling. All payload fetches are
  `raw.githubusercontent.com`.
- Installs run over root SSH via `pct`, the channel the existing post-install
  checks and the e2e harness already model.
- LXC-only Store. The classifier's interactive-input finding is not softened.
- No fork or vendor of upstream scripts.

## Non-goals

- Answering any prompt on the operator's behalf.
- Making the five empty-container apps installable.
- Install-method choice (the Debian/Alpine variants).
- Verifying that a supplied gateway is reachable.
