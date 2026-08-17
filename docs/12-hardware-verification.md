# Hardware verification: what the fakes cannot prove

Every automated suite in this repo runs against fakes. `tests/fakes/ssh.py`
answers as a Proxmox node would, `FakePVE` answers as the API would, and jsdom
answers as a browser would. That is the right default: it is fast, offline, and
deterministic.

It is also why this list exists. A fake proves that we *send* the right thing.
It cannot prove that a real node *does* the right thing with it. Those are
different claims, and conflating them is how a bug reaches production through a
green suite.

The clearest example is already recorded in `docs/notes/phase-4-store.md`:
`var_ctid=150` is "demonstrably *sent*", proven by asserting on the exact command
string handed to `create_process`, and `build.func`'s
`local requested_id="${var_ctid:-$NEXTID}"` was read from the real upstream
source to confirm it is honoured. But no container has ever actually been
created at a chosen CTID on a real node from this environment.

This document is the standing list of checks that require real hardware. Each
entry says what to run, on what shape of host, and what would count as a pass.
Add to it whenever a change's correctness depends on behaviour a fake supplies.

## How to use it

These are not a release gate today. They are the honest inventory of what
remains unproven, so that a claim of "verified" can be scoped accurately, and so
that anyone who does get access to real hardware knows exactly what to exercise.

When a check is performed, record the date, the PVE version, and the outcome
next to the entry rather than deleting it. A check that passed on PVE 8.4 is not
a check that passed on PVE 9.

## App Store installs

### Storage selection on a multi-storage host

**Why it is here.** `misc/build.func` auto-picks a storage pool only when
exactly one candidate exists for the content type, and otherwise calls
`select_storage`, which is interactive. The e2e harness models `pct` over SSH
but not `pvesm status`, so no fake exercises that branch at all. This is the
gap that produced the "storage is not optional" finding in
`docs/superpowers/specs/2026-08-13-app-install-modes-design.md`.

**Host shape required:** at least two pools carrying `rootdir`, and at least two
carrying `vztmpl`. A single-storage host cannot exercise any of these. Checks 3a
and 3b additionally need a *shared* pool (NFS, CIFS, Ceph) attached to a
multi-node cluster; a standalone host cannot exercise them.

The hardware available on 2026-08-14 initially did not meet this shape:
`node1` and `node2` each carried exactly one `rootdir` pool (`local-lvm`) and
one `vztmpl` pool (`local`), and were standalone rather than clustered. That
was enough for check 3 and the remembered-value half of 3b, and nothing else.

Later the same day the two nodes were clustered as `lab-cluster` and an Unraid NFS
export (`192.168.50.8:/mnt/user/test`) was attached cluster-wide as
`nfs-shared` carrying `rootdir,vztmpl,images,iso,backup`. That is the shape
this section asks for, and it is what checks 3a and 3b were finally run
against.

**Detached at some point before 2026-08-17, and reattached that day.** It was
found missing from both nodes (only `local` and `local-lvm` remained, and only
`local` carried `backup`), and was recreated with the same shape:
`type=nfs server=192.168.50.8 export=/mnt/user/test`,
`content=rootdir,vztmpl,images,iso,backup`, 617.5 GiB, active on both nodes.

Two things worth keeping from doing that. `shared` is NOT a valid property for
`type=nfs` on PVE 9.2.10; passing it gets `500 unexpected property 'shared'`,
because NFS is shared by definition, and the per-node listing reports
`shared=1` back anyway. And a freshly created NFS storage reports `active=0`
with `avail=0` on the node that did not create it for a few seconds, because
PVE mounts it lazily. Anything that reads `active` immediately after attaching
a shared pool sees a pool that looks dead. Two notes for anyone rebuilding it:

- Joining a node replaces its `/etc/pve`, so `node2`'s Proxmox API token was
  destroyed and Proxploy lost it with a 401 until its host row was repointed at
  the now cluster-wide credentials. Root SSH went the other way and fixed
  itself: `/root/.ssh/authorized_keys` is a symlink into `/etc/pve/priv/`, so
  `node2` inherited `node1`'s key on join.
- The two-node cluster runs with `two_node: 1` in `/etc/pve/corosync.conf`
  (config_version 3, applied 2026-08-14). Without it quorum is 2 of 2, so
  losing either node puts the survivor's `/etc/pve` into read-only and every
  Proxploy write against it fails. Corosync enables `wait_for_all` alongside
  `two_node`, which has its own consequence worth knowing before you debug it
  at 2am: after a cold start of BOTH nodes, the first one back is NOT quorate
  until it has seen the other at least once. `pvecm expected 1` is the manual
  escape. A QDevice would remove both caveats and needs a third host.

- The Unraid share is exported "Public", which squashes root to `99:100`.
  This was expected to break a container rootfs and did NOT: CT 152 was
  created on it, ran, and its disk sat at
  `/mnt/pve/nfs-shared/images/152/vm-152-disk-0.raw` owned `99:100`. Root
  writes are remapped to the anonymous uid rather than refused, and that uid
  owns the file it just created, so an unprivileged LXC works. Recorded
  because the opposite was assumed here first.

**Updated 2026-08-14.** The install dialog now recreates the backend's candidate
set client-side (`frontend/src/components/install/pools.ts`) to decide whether
there is a question worth asking. That computation is the thing these checks
exercise, and every input it depends on comes from a fake today: which pools
exist, which node reports them, whether a pool is `shared`, whether its status
is `available`, and how its `content` is spelled. Checks 3a and 3b are new
because a code review found both cases reachable and neither provable offline.

1. **Default install, no user input, does not reach `select_storage`.**
   Install an app in Default mode without touching the form. Pass: the container
   is created and the job completes. Fail: the job hangs, times out, or logs a
   storage prompt.

   **PASSED 2026-08-14, PVE 9.2.10**, and on the harder shape than the one
   this check was written for: `node1` had TWO `rootdir` candidates at the
   time (`local-lvm` and the shared `nfs-shared`), which is exactly the case
   that sends bare `build.func` into its interactive picker. The transcript
   shows it resolved without asking:

       Storage 'local-lvm' (lvmthin) validated
       Template storage 'local' validated
       Container ID: 150

   No storage prompt, no hang, job `succeeded`, CT running.
2. **An explicitly chosen non-default storage is honoured.** In Advanced,
   select a container storage that is NOT the one a single-storage host would
   have auto-picked. Pass: `pct config <ctid>` shows the rootfs on the pool that
   was chosen. Sending the variable is not the claim; the container landing
   there is.

   **PASSED 2026-08-14, PVE 9.2.10.** Installed to `nfs-shared` rather than
   the local default. `pct config 152` reported
   `rootfs: nfs-shared:152/vm-152-disk-0.raw,size=1G`, and the backing file
   was present on the NFS export itself. The container landed there, which is
   the claim; the variable being sent was never in doubt.

   This install doubles as **3a's install half**: it was made against host
   `node1`, whose `node_name` is `node1`, using the shared pool whose collapsed
   `GET /storage` row named `node2`. So the pool a foreign-node row exempted
   from the node filter is one an install can actually use.
3. **A `vztmpl`-only pool is not offered as rootfs.** In Advanced, confirm the
   container storage picker excludes pools whose content lacks `rootdir`. Pass:
   the pool is absent from that control. This one is client-side and provable in
   a browser against a real host's storage list, without an install.

   The filtering itself is now covered by unit tests, so what is left to prove
   here is narrower and worth stating exactly: that a real node's `content`
   field parses into the strings the filter compares against. The poller splits
   PVE's raw comma string (`pollers/__init__.py:256`), and
   `api/storage.py::_content_list` accepts either that or a list. A real
   `/cluster/resources` row is the only thing that proves the spelling matches.

   **PASSED 2026-08-14, PVE 9.2.10**, against two standalone hosts
   (`node1` 192.168.50.199, `node2` 192.168.50.200). Both endpoints the code
   reads return `content` as a comma string, and the spelling matches the
   literals the filters compare against:

   - `/cluster/resources` (poller): `local-lvm` -> `"rootdir,images"`,
     `local` -> `"import,backup,iso,vztmpl"`.
   - `/nodes/{node}/storage` (`appstore.py::_storage_pools`, the install-time
     authority): same values, plus `enabled: 1` and `active: 1` present as
     ints on every row, so the `row.get("enabled", 1)` defaults are a fallback
     and not the live path.

   Order is NOT stable between nodes (`"rootdir,images"` on node1,
   `"images,rootdir"` on node2), which the membership tests are already
   indifferent to. Backend and client-side candidate sets agree exactly on both
   hosts: rootdir `["local-lvm"]`, vztmpl `["local"]`.

   In the browser, on the real `/store` install dialog for each host: the
   Container storage picker offers `local-lvm` only, so `local` (vztmpl, no
   `rootdir`) is absent, and the Template storage picker offers `local` only,
   so `local-lvm` (rootdir, no `vztmpl`) is absent. Default mode asked nothing
   and showed `Storage: container local-lvm · template local`. No console
   errors.
3a. **A shared pool is offered on every node of the cluster.** `GET /storage`
   collapses a shared datastore to ONE row keyed by `(host_id, storage)`, keeping
   whichever node the poller saw first, so its `node` may name a node other than
   the host being installed to. The dialog exempts shared rows from its node
   filter for exactly this reason. Pass: with a shared `rootdir` pool attached
   to several nodes, that pool appears in the picker for a host whose
   `node_name` is NOT the node on the row, and an install to it lands there.
   Fail: the pool is missing from the picker, or Default installs without asking
   on a host that genuinely has two candidates.

   **PICKER HALF PASSED 2026-08-14, PVE 9.2.10**, on the `lab-cluster` cluster with
   `nfs-shared` attached. The case arose on its own rather than having to be
   contrived: `/cluster/resources` reports `nfs-shared` once per node with
   `shared: 1`, and `GET /storage` collapsed it to a single row naming
   **node2** for BOTH host rows, including the one whose `node_name` is
   `node1`. That is precisely the row the node filter would drop. With the
   `|| r.shared` exemption it is kept, and the dialog for host `node1`:

   - offers `nfs-shared` in both pickers, once, not once per reporting node,
   - and asks BOTH storage questions in Default mode, `local-lvm` +
     `nfs-shared` for rootdir and `local` + `nfs-shared` for vztmpl, with an
     empty settled-storage summary because nothing is settled.

   So the documented failure mode (pool missing from the picker, or Default
   installing without asking on a host with two real candidates) does not
   occur. The install half, that a container placed there actually lands on
   the shared pool, still needs a container create and is open.

   Also newly proven by the same setup, and previously fake-only: with two
   nodes carrying identically named local pools, `GET /storage` returns
   `local` and `local-lvm` once per node per host, four rows where the backend
   sees two candidates. The node filter plus dedupe collapses that to one
   candidate per content type, and Default correctly asked nothing before
   `nfs-shared` was attached.
3b. **A pool the node is not serving is never offered.** The dialog keeps only
   rows whose `status` is exactly `available`, a literal taken from
   `/cluster/resources`. Pass: disable or detach one pool on the node and
   confirm it disappears from the picker, and that a host which had remembered
   that pool asks the storage question again instead of showing it as settled.
   Fail: the pool is still offered, or the remembered value is presented as
   fact and the job then refuses with "no longer available".

   **HALF PASSED 2026-08-14, PVE 9.2.10.** The remembered-value half was run
   against the real pool list on `node1` by varying
   `Host.default_container_storage` only, with nothing changed on the node:

   - `local-lvm` (a live candidate): settled, no question, summary reads
     `Storage: container local-lvm · template local`.
   - `nvme-gone` (a name no pool carries): the Container storage question is
     re-asked with `local-lvm` offered, and the summary drops to
     `Storage: template local` rather than presenting the stale name as fact.
   - `local` (a real pool, but not a `rootdir` candidate): also re-asked, and
     NOT quietly swapped for `local-lvm` despite it being the sole survivor,
     which is the `knownPool` / `resolve_storage_pools` agreement.

   **BEHAVIOURAL HALF PASSED 2026-08-14** on the `lab-cluster` cluster, in the
   "one of two disappears" shape this check describes. With `nfs-shared`
   attached and remembered as host `node1`'s `default_container_storage`,
   running `pvesm set nfs-shared --disable 1` produced exactly the documented
   pass: the pool left both pickers, and the host re-asked the container
   question offering `local-lvm` alone rather than presenting the remembered
   `nfs-shared` as fact. The template question settled back to `local` as the
   sole survivor. Re-enabling restored all of it.

   **STATUS HALF PASSED 2026-08-14**, but only after finding that the obvious
   way to run it does not work. A DISABLED pool does not come back from
   `/cluster/resources` with a non-`available` status, it does not come back
   AT ALL: `--disable 1` removes the row entirely. Nothing reachable by
   disabling a storage ever reaches the `status` comparison.

   What does reach it is a pool that stays ENABLED and goes INACTIVE. The
   cheapest way to produce one, with no dead NFS mount to hang `pvestatd` on,
   is a `dir` storage with `is_mountpoint` set on a path that is not a mount:

       pvesm add dir stale-test --path /mnt/stale-test --content rootdir,vztmpl
       pvesm set stale-test --is_mountpoint 1

   Two steps, not one, because `pvesm add` refuses to create a storage it
   cannot immediately activate.

   **The literal that came back is `unknown`, not `unavailable` or
   `inactive`.** `/cluster/resources` reported
   `"storage":"stale-test","status":"unknown"` with `content` of
   `rootdir,vztmpl`, and `GET /storage` passed it through unfiltered, exactly
   as its docstring says it does. The pool was absent from both pickers on
   both hosts while `local-lvm`, `local` and `nfs-shared` remained. So the
   positive match on `available` is now proven against real hardware, and it
   is also the reason this works: a filter written as a blocklist of known-bad
   statuses would have had to guess `unknown`, and would have offered an
   unmountable pool as a rootfs candidate.

### Install execution, carried from phase 4

4. **A container is created at a chosen CTID on a real node.**
   **PASSED 2026-08-14, PVE 9.2.10.** Requested 150, got 150: `pct list` showed
   `150 running alpine` and `pct config 150` confirmed it. No longer proven
   only as far as the command string.
5. **Blank CTID lands on the node's next available ID**, via
   `${var_ctid:-$NEXTID}`, with `var_ctid` absent from the environment.
   **PASSED 2026-08-14, PVE 9.2.10**, and the result is more convincing than a
   sequential one would have been: with 150 already taken, the node assigned
   **100**, its genuinely lowest free id, not 151. Nothing in Proxploy could
   have produced that number, which is the point of the check.
6. **`AcceptEnv` behaviour against a real `sshd`.** Env vars are inlined into
   the command string precisely because a real server's `AcceptEnv` config
   makes asyncssh's `env=` silently no-op. The fix is safer either way, but the
   original behaviour was never reproduced against a live `sshd`.

   **CONFIRMED 2026-08-17** against `node1`'s real sshd, OpenSSH_10.0p2
   Debian-7+deb13u4, through asyncssh itself (the same library
   `executor/ssh.py` uses) and the app's own stored key. Effective config from
   `sshd -T`:

       acceptenv LANG
       acceptenv LC_*
       acceptenv COLORTERM
       acceptenv NO_COLOR

   Three cases, which together name the cause rather than just observing the
   symptom:

   - `env={"var_ctid": "150"}`: the node saw `''`. Silently dropped, exactly as
     the comment says.
   - `env={"LC_TEST_CTID": "150"}`: the node saw `'150'`. **This is the control
     that matters.** A name the allowlist matches DOES arrive through `env=`,
     so asyncssh sends environment correctly and it is sshd's allowlist that
     refuses the other one. Without this case the result would be
     indistinguishable from asyncssh being broken.
   - inlined as `var_ctid=150 sh -c ...`, which is what Proxploy does: the node
     saw `'150'`.

   So inlining is load-bearing, not belt-and-braces, and the reason is
   `AcceptEnv`, not the client library. Note the default allowlist here is
   WIDER than the LANG/LC_* usually quoted (it also carries `COLORTERM` and
   `NO_COLOR`), which is worth knowing before anyone assumes a name is safe
   because it is not `var_*`.

### Two things the first real install surfaced

Neither is a storage finding, and both were invisible to every fake.

**`build.func` renders an interactive whiptail dialog mid-install, and we only
survived it by accident.** A "TELEMETRY & DIAGNOSTICS" radiolist with
`<Confirm>` / `<Exit>` buttons drew itself into the job transcript on
2026-08-14, in a non-TTY SSH session.

Why it did not block: `diagnostics_check()` prompts whenever
`/usr/local/community-scripts/diagnostics` is missing, and its whiptail call
ends in `|| result="no"`. A session with no terminal falls through that
fallback to "no" and then WRITES the file, so only the FIRST install on a node
ever saw the dialog. The file on `node1` is stamped 20:06, the first install of
the day. That is error handling we happened to land in, not a supported
non-interactive path, and it is one upstream edit away from being a hang.

There is no environment variable for it, which is worth recording because the
obvious fix does not work: `variables()` does a hard `DIAGNOSTICS="no"`
assignment rather than `${DIAGNOSTICS:-no}`, so anything exported is
overwritten before `diagnostics_check()` runs, and that function branches on
the FILE regardless of the variable's value. Adding `DIAGNOSTICS=no` next to
`PHS_SILENT` would look like protection and provide none. Proxploy now writes
the config file itself, before the script runs and only when it is absent, so
an operator who opted in from the node's own shell keeps their answer.

**VERIFIED END TO END 2026-08-15, PVE 9.2.10.** The opt-out was previously
only unit tested, with the shell command tested separately on hardware; the two
had never run together. Deleting
`/usr/local/community-scripts/diagnostics` from node2 to make it look like a
fresh node, then installing through the App Store:

- the file came back **15 bytes containing exactly `DIAGNOSTICS=no`**, which is
  Proxploy's `printf`. `diagnostics_check()` writes a 628 byte version with a
  comment block, so the size alone says which of the two got there first.
- the job transcript contains no "TELEMETRY" and no "share anonymous data"
  anywhere, against 41 events. The first install of 2026-08-14 had the entire
  whiptail dialog rendered into its log.

So the prompt is not merely survived now, it is never reached.

**The standing lesson is bigger than telemetry.** `misc/build.func` is fetched
live from `main` at execution time (see the residual limitation recorded in
`services/appstore.py`), so upstream can introduce a NEW interactive prompt at
any moment, with no change on our side and no version bump to notice. Two of
these are now known, `select_storage` and `diagnostics_check`, and both were
found by reading a real transcript rather than by any test. Every fake in this
repo answers as though no question was asked. So: after any real install,
read the transcript for whiptail output, and treat a new prompt as a
regression in Proxploy even though nothing here changed. There is no automated
check that can replace this, which is exactly why it belongs in this document.

**A node that cannot resolve `download.proxmox.com` fails at exit 223 with a
misleading message.** The install reported `Template ... not available in
storage local after download` right after claiming `Template download
successful.`, which reads as a storage fault. It was DNS: the node's resolver
timed out on that name (while resolving others fine), so `pveam download`
never fetched anything. If a template-download failure is ever reported
against a storage pool, check name resolution on the node before believing the
message.

## Migration, networking and storage operations

7. **Cross-host migration without a cluster.** Proven against two `FakePVE`
   instances plus a fake SFTP layer driving the real preflight, handler and
   route code. Never against two real non-clustered hosts. See
   `docs/11-risks-open-decisions.md` section 2.

   **STILL OPEN, and 2026-08-17 established that it is harder to reach from
   here than it looks.** Two independent reasons, both worth writing down so
   nobody plans an afternoon around it again:

   - **Leaving a PVE cluster has no clean API.** `pvecm delnode`, and its
     `DELETE /cluster/config/nodes/{node}` equivalent, only removes the node
     from the REMAINING node's view. The removed node still believes it is
     clustered, and cleaning it means a shell on that node: stop
     `pve-cluster`, delete `/etc/pve/corosync.conf` and `/var/lib/corosync/*`,
     restart pmxcfs locally. PVE's own guidance is to wipe and reinstall a
     removed node rather than reuse it. So unclustering this pair is a one-way
     trip unless someone is at the nodes.
   - **Unclustering alone would not reach this strategy anyway.** With
     `nfs-shared` attached to both nodes, `preflight` finds a shared pool in
     common and picks `STRATEGY_SHARED`. Confirmed against the real API on
     2026-08-17: unclustered, this pair would select `shared_storage`, shared
     in common `['nfs-shared']`. Reaching `STRATEGY_TRANSFER` needs the nodes
     unclustered AND the shared pool detached.

   **What was verified instead, 2026-08-17, PVE 9.2.10.** The parts of this
   code reachable on a clustered pair, all previously fake-only:

   - **Strategy selection against real API output.** `_cluster_name` over real
     `cluster_status()` returned `'lab-cluster'` for both nodes and selected
     `STRATEGY_CLUSTER`, and `_storage_names` over real `cluster_storage()`
     found `nfs-shared` shared on both. So the selection logic agrees with real
     data, not just with fixtures.
   - **`migrate_guest()` against a real guest.** A throwaway alpine CT moved
     `node2` -> `node1` and came up on the target from the same volume.
   - **A container rootfs on the shared NFS pool.** Created as
     `nfs-shared:100/vm-100-disk-0.raw,size=1G`, started on `node2`, migrated,
     and started again on `node1` from that same volume. This is the PVE-level
     half of 3a's open install question: the shared pool really does accept and
     boot a container rootfs. It is NOT 3a's App Store half, which still needs
     the install dialog.

   **Two things about measurement, so these numbers are not misread.** The
   task waiter polls every 2s, so every "2.1s" in that run is the polling
   floor and not a timing: create, start, stop, migrate and delete all
   completed inside one poll. The one real measurement is the first boot on the
   target, **45.0s**, against an under-2s boot on the source. And
   `/cluster/resources` reported `status=unknown` for the guest immediately
   after start and after migration before settling, which is the same lag
   check 12 found: that endpoint trails reality, and code that reads it
   straight after an action sees a state that is not yet true.
8. **Network apply on a real bridge.** Applying a NIC change to a live guest,
   including the failure path where the change costs connectivity to the node
   performing it.

   **THE SAFE HALF PASSED 2026-08-17, PVE 9.2.10**, on `node1`. Staged an
   UNUSED bridge (`vmbr99`, no `bridge_ports`, no address), applied it, then
   removed it and applied again. That runs the whole real path, stage to
   `/etc/network/interfaces.new`, promote, `ifreload -a`, remove, promote,
   without the lockout the risky half carries, because nothing depends on the
   interface being reloaded. Both applies returned OK in 2.1s, `vmbr99` came up
   `active=1 autostart=1`, `vmbr0` stayed `active=1` on 192.168.50.199/24, the
   node answered throughout, and the interface set afterwards matched the set
   before.

   **The `ponytail:` claim at `api/network.py:302` is confirmed.** With a clean
   config, `GET /nodes/{node}/network` returns top-level keys `['data']`. With
   a staged config it returns `['changes', 'data']`, where `changes` is a
   unified diff of `interfaces` against `interfaces.new`. So PVE really does
   report pending state as a sibling of `data`, proxmoxer's `.get()` really
   does discard it, and the documented upgrade path (a raw-response accessor)
   would work if a "you have unsaved changes" badge is ever wanted.

   **An apply is never only your change, and no fake shows this.** The staged
   diff was not limited to `vmbr99`. PVE's generated `.new` also rewrote the
   rest of the file: it added `iface nic1 inet manual` and
   `iface wlp0s20f3 inet manual` stanzas and a comment block that were not in
   the running config, and moved `nic1` above `vmbr0`. So an operator who
   stages one bridge and hits Apply also promotes PVE's normalisation of
   everything else in `/etc/network/interfaces`. Harmless on this node, since
   the added stanzas are `manual` with no `auto`, but it means the diff an
   operator should be shown is PVE's `changes`, not the one field they edited.

   **THE LOCKOUT HALF PASSED 2026-08-17, PVE 9.2.10**, and it is the more
   interesting half. Run on `node1` after arming recovery on the node itself as
   a transient systemd timer (`systemd-run --on-active=150`) that restores the
   backed-up `interfaces` file, runs `ifreload -a` and force-sets the address.
   systemd owns that timer, so it fires whether or not sshd, pveproxy or the
   network are reachable, and it does not care that the session which armed it
   is gone. That is what makes this check runnable without standing at the node.
   Nothing was broken until the timer was confirmed armed.

   `vmbr0` was moved from 192.168.50.199/24 to 10.99.99.99/24. PVE's own
   `changes` diff showed exactly that one line, so the staged change was
   understood before applying it.

   **What Proxploy sees is the finding, and it is worse than a plain failure:**

   1. `network_apply` **returned a UPID in 0.1 seconds**, successfully.
      `ifreload -a` is an asynchronous `srvreload` task, so the POST completes
      before the reload takes effect. Proxploy has every reason to believe the
      call worked.
   2. `/version` **still answered 9.2.10** immediately afterwards. An immediate
      health check gives a false all-clear.
   3. Then the node vanished, for 193 seconds as measured from the apply.
   4. So the job's UPID polling (`pvetask.py`) hits an unreachable host and the
      job reports a FAILURE.
   5. **But the apply genuinely succeeded.** Read after the node returned, that
      same UPID reports `status: stopped`, `exitstatus: OK`, `TASK OK`.

   In other words: a successful apply that costs the node its network is
   reported to the operator as a failed one, and the truth is only recoverable
   after the node comes back, at which point the task record settles it. That
   is a strictly worse failure mode than "the job hangs", because the operator
   is told the opposite of what happened. Nothing about it is reachable with a
   fake, which answers this entry's original question about the failure path.

   Two timings worth keeping. Recovery was NOT instant once the config was
   restored: the timer fired about 140s after the apply and the API answered at
   193s, so roughly 50s passed between `ifreload -a` putting the address back
   and pveproxy being reachable again. And the whole outage was survivable only
   because recovery was armed in advance; without it this is a console trip,
   which is why `apply_network` demands the node name typed back.

   Afterwards `vmbr0` was `active=1` on 192.168.50.199/24, the running config
   matched the backup byte for byte, the staged config was discarded, and the
   timer and backup file were removed.
9. **Whole-storage prune.** Pruning across an entire storage, where the count
   of affected volumes and the time taken both differ materially from a fake.

   **PASSED 2026-08-17, PVE 9.2.10**, on `node2`'s `local`. Both nodes held zero
   backups, so the check made its own: four `vzdump`s of CT 101 in `snapshot`
   mode, 391 MiB each, 8.2s each, with the container running throughout. Then
   `keep-last=1` through the route's own `_prune_spec`/`_prune_call`.

   **The number worth keeping: the dry run took 33 ms and the real prune took
   2.1 s, 65x.** A fake answers both instantly, so any code that treats prune as
   costing what its preview costs is wrong on hardware. The two agreed exactly
   on which volumes were affected, `remove` 3 and `keep` 1, which is what
   `prune_preview`'s "the two must stay in sync" comment asks of the pair, and
   `keep-last` retained the NEWEST rather than the first.

   Worth noting for anyone re-running it: the script refuses to start if the
   target storage already holds a backup, so it can only delete what it created.
   That also means it refuses until the one retained volume is removed.

## Cluster quorum

12. **Proxploy against a cluster that has lost quorum.** Never exercised, and
    the failure shape is the reason it is worth writing down: quorum loss makes
    `/etc/pve` read-only, so `pct create`, storage edits and any config write
    fail, while `/cluster/resources` keeps answering perfectly. The poller
    would therefore report every host `connected` and every node healthy, and
    the UI would look entirely normal right up until a write is attempted.
    That is the "a fake reports too cleanly" pattern this document exists to
    catch, except here the REAL API reports too cleanly as well.

    Reproduce by stopping corosync on one node of the pair
    (`systemctl stop corosync`) with `two_node` removed, or on a plain
    two-node cluster before that setting is applied. Pass: an install or any
    config write refuses with something an operator can act on, and the host
    is not presented as healthy while it cannot accept writes. Fail: the job
    hangs, or fails with a raw Proxmox error about a read-only filesystem that
    names no cause.

    Deliberately not run on 2026-08-14: it means deliberately breaking the
    cluster the other checks were using.

    **RUN 2026-08-17, PVE 9.2.10, and it did not reach the documented state.**
    corosync was stopped on `node2` through `POST
    /nodes/node2/services/corosync/stop`, which is worth knowing on its own:
    the check is reachable over the API with no shell, and the same API starts
    it again, which is what makes it recoverable rather than a console trip.

    `node1` stayed **`quorate=1`** for the whole outage and an `/etc/pve` write
    (creating and deleting a pool, which writes `user.cfg`) SUCCEEDED while
    `node2` was out. So quorum was never lost. **Confirmed by reading
    `/etc/pve/corosync.conf` later the same day**, once shell access was
    available through the app's own stored SSH key:

        quorum {
          provider: corosync_votequorum
          two_node: 1
        }

    and `pvecm status` reporting `Expected votes: 2`, `Quorum: 1`,
    `Flags: 2Node Quorate WaitForAll`. A quorum of 1 out of 2 expected votes is
    why the survivor stayed quorate, so this is now a read fact rather than an
    inference from behaviour. The same file also confirms check 13's reading:
    `ring0_addr` is 192.168.50.199 / 192.168.50.200, the management addresses.

    **It did surface the "reports too cleanly" pattern, in a shape this entry
    did not predict.** With `node2`'s corosync stopped:

    - `/cluster/status` was CORRECT: `nodes={'node1': 1, 'node2': 0}`, so the
      departure is visible to anything that reads it.
    - `/cluster/resources` still reported `lxc 101 status=running node=node2`,
      the guest on the node that had left the membership.

    So a poller that reads `cluster_resources` alone presents a departed node's
    guests as healthy, while `cluster_status` right next to it knows better.
    That is the same class of failure as the read-only-`/etc/pve` case and it is
    reachable without breaking quorum at all, which makes it the more useful
    finding of the two.

    **Still open: actual quorum loss.** Reaching it means removing `two_node`
    from `/etc/pve/corosync.conf` and bumping `config_version`, a cluster
    config edit with real risk of leaving the pair unable to form a cluster.
    Not attempted.

## Privileges and identity

10. **Monitoring-token privilege paths.** A token lacking `Sys.PowerMgmt`
    should warn ahead of a power action rather than refuse it, and
    `node_power_missing` should be recomputed at enrolment and by
    `POST /hosts/{id}/test`. The tri-state (null meaning "not checked") is
    exactly the kind of thing a fake reports too cleanly.

    **HARDWARE HALF PASSED 2026-08-15, PVE 9.2.10.** Run against a throwaway
    `pp-probe@pve!probe` token granted only `PVEAuditor` at `/`, then deleted.
    Calling the real `api/hosts.py` probes against it:

    - `/access/permissions` was readable, 7 privileges, so the tri-state's
      "could not tell" branch was NOT taken and the answer below is a real one.
    - `_missing_privileges` returned `[]`. PVEAuditor holds all five of
      `VM.Audit`, `Datastore.Audit`, `Sys.Audit`, `Pool.Audit`, `SDN.Audit`, so
      a PVEAuditor token is a legitimate monitoring token.
    - `_node_power_missing` returned **True**, correctly seeing that the same
      token has no `Sys.PowerMgmt`.

    That is the part only real hardware could answer: what a genuinely
    restricted token reports. What is still open is the null branch, which
    needs a token REFUSED `/access/permissions` and PVE grants that read to
    everyone for their own permissions, and the UI half, that the warning
    appears ahead of a power action rather than the action refusing.

    **Worth recording about this lab specifically:** both hosts authenticate as
    `root@pam!proxploy`, a root token holding every privilege. So in this
    environment NO privilege-degradation path is ever exercised: not
    `node_power_missing`, not `_missing_privileges`, not the degraded-poll path
    that exists because a narrow token can read `/cluster/resources` and still
    403 on `rrddata`. Those branches are live code that this hardware never
    reaches, which is worth knowing before reading a green run as coverage.
11. **OIDC against a real IdP.** Proven against a local mock provider with a
    real discovery document, real PKCE, and RS256 tokens verified against a real
    JWKS endpoint. Everything except a third-party implementation on the wire.
    See `docs/superpowers/plans/2026-08-05-phase-8-scale.md`.

## Cluster peer enrolment

Everything in this section is answered in one run by
`backend/scripts/verify_cluster_peers.py`, which calls the same
`services/proxmox.py` functions the app calls and writes nothing:

```
PROXPLOY_TOKEN_SECRET=... .venv/bin/python scripts/verify_cluster_peers.py \
    --address https://<node1>:8006 --token-id 'root@pam!proxploy'
```

**Host shape required:** two nodes in one cluster, both online, with a token on
the origin that PVE has replicated cluster-wide. A standalone node cannot
exercise any of it and the script says so and stops.

13. **The addresses `/cluster/status` reports are answerable by the API.** The
    peer panel builds every address as `https://{row["ip"]}:8006` from the node
    rows PVE returns, and `FakePVE` returns rows we wrote, so no suite has ever
    disagreed with itself here. On real hardware that `ip` is the corosync
    ring0 address. On a cluster whose corosync ring runs on a dedicated network
    the API does not listen on, every peer the panel offers would be one that
    can never be enrolled. Pass: each peer's reported address completes a TLS
    handshake on 8006. Fail: the handshake times out, which the panel would
    render as an unreachable row with the enrolment checkbox disabled, correct
    behaviour hiding a wrong address.

    Also checked here, because the same rows carry it: exactly one node row
    carries `local`. That flag is the only thing stopping a host being offered
    as its own peer, and it is set by PVE, not by us.

    **PASSED 2026-08-17, PVE 9.2.10**, in cluster `lab-cluster`, between `node1`
    (192.168.50.199) and `node2` (192.168.50.200). Both node rows carried an
    `ip`, the peer's completed a TLS handshake on 8006, and `local: 1` appeared
    on exactly one row.

    **The hazard this check exists for was NOT exercised.** This lab runs
    corosync on the management network, so each node's ring0 address IS the
    address its API listens on, and the two can agree here while diverging on a
    cluster built with a dedicated cluster network. A pass on this hardware says
    the field is present and usable, not that it is the API's address
    everywhere.

    **The hazard is real, established 2026-08-17 without a second network.**
    `GET /cluster/config/join` on PVE 9.2.10 returns, per node, a `ring0_addr`
    and a `pve_addr` as SEPARATE fields. On this cluster they hold the same
    value, which is why every check above passes, but PVE storing them
    independently is what says they can diverge. So a cluster joined with a
    dedicated corosync link has a real chance of reporting an address the API
    does not answer on, and the panel's unreachable row is a real mitigation
    rather than dead code.

    Still not distinguished, and no longer worth breaking a cluster over: WHICH
    of those two fields the `ip` in `/cluster/status` reflects. With both equal
    here, the run cannot tell. The better answer is to stop depending on it, see
    below.

    **`/cluster/config/join` is a better source than `/cluster/status` for this,
    and the panel does not use it yet.** It carries `pve_addr`, the address PVE
    itself designates for API access, alongside `pve_fp`, PVE's own record of
    that node's API certificate. Building peer addresses from `pve_addr` would
    make this entire check moot. Two things to settle before relying on it:

    - **Settled 2026-08-17, PVE 9.2.10: a narrow token may read it.** Against a
      throwaway `pp-probe@pve!probe` holding only `PVEAuditor` at `/` (created,
      asked, and deleted in one run), `/cluster/config/join` was READABLE and
      returned `pve_addr`, `ring0_addr` and `pve_fp` for both nodes, as were
      `/cluster/status` and `/cluster/config/nodes`. `PVEAuditor` carries
      `Sys.Audit` at `/`, which is what that endpoint wants. So the monitoring
      credential the peer panel runs on is sufficient, and this is no longer an
      obstacle. The token was created with `privsep=0` so it inherited the
      user's role; PVE's default `privsep=1` gives a token nothing until the
      token itself appears in an ACL, which would have made a refusal say
      nothing about `PVEAuditor`.
    - `pve_fp` is recorded at join time. A node whose certificate was replaced
      after it joined would report a stale one, so `pve_fp` is worth having as a
      second opinion and is NOT a substitute for reading the live certificate.

    **Deliberately not built, 2026-08-17.** Both prerequisites are now cheap or
    cleared, and the change is still deferred: no cluster with a dedicated
    corosync link has been reported, and the behaviour on one today is already
    honest rather than broken (an unreachable row, a disabled checkbox, and an
    enrolment refused with the reason). Build it when a real cluster needs it.
    What it would be is one call swapped for another, plus `pve_fp` as a second
    opinion on the fingerprint the socket already returns.

14. **Each node presents the certificate the panel showed, and still presents
    it a moment later.** This is the foundational one: the entire trust model
    is that an operator reads a fingerprint, ticks the node, and
    `POST /hosts/{id}/peers` re-reads the certificate and refuses the node if
    it has changed. Every test of that logic supplies both fingerprints from
    the same fixture, so the suites prove the comparison is made and cannot
    prove what a real node presents on two separate reads. Pass: two reads
    seconds apart return the same fingerprint, on every node. Fail: they
    differ, which means the echo check refuses honest enrolments and its alarm
    text ("if you did not just replace its certificate, stop and investigate")
    is crying wolf.

    **PASSED 2026-08-17, PVE 9.2.10.** Each node returned the same fingerprint
    on two reads seconds apart, so the echo comparison in `enrol_peers` is not
    fighting a moving target on real hardware. This is the one the whole design
    rests on.

    **Corroborated by PVE itself, 2026-08-17.** `pve_fp` in
    `/cluster/config/join` matched, character for character, the fingerprint
    read off the wire for both nodes and now pinned in the dev database. So two
    independent sources, a TLS handshake and Proxmox's own join record, agree on
    what each node's API certificate is. That is the strongest statement
    available here that the pinning pins the right thing.

    The script also reports whether the nodes present *distinct* certificates.
    They are expected to: the code fetches each peer's own certificate rather
    than inheriting the origin's, and a comment in `enrol_peers` says an
    inherited pin "would refuse every connection". If a cluster turns out to
    share one certificate nothing breaks, but that comment is wrong about this
    hardware and should say so.

    Confirmed distinct on this hardware: `node1` served
    `47:43:8A:A0:...:C1:74` and `node2` served `8D:99:03:50:...:3E:5B`. So the
    comment in `enrol_peers` is right about why a peer must not inherit the
    origin's pin.

15. **The origin's token authenticates against its peers.** The premise of
    copying one node's stored token to the rest of the cluster. Proven only
    against `FakePVE`, which accepts any token it was configured with at any
    address. Pass: `/version` through each peer's address, with the origin's
    token, returns a version. Fail: a peer 401s, and the feature's central
    assumption about cluster-wide token replication is wrong; the code already
    degrades to a per-row "refused the monitoring token" failure rather than a
    broken host, so this is a design question rather than a crash.

    **PASSED 2026-08-17, PVE 9.2.10.** `node1`'s stored `api_token:monitoring`
    authenticated against `node2`'s address and returned its version, so PVE
    does replicate an API token cluster-wide and the copy the feature performs
    is copying something that works. Note that this lab's token is
    `root@pam!proxploy`, which holds every privilege; a narrow token's
    replication is the same mechanism but is not what was tested.

16. **A pin is actually enforced.** `_connect` only consults
    `tls_fingerprint` when `verify_tls` is off, which is every default install,
    and an unenforced pin is worse than no pin because the UI states the node
    is pinned. Pass: connecting with the node's real fingerprint succeeds, and
    connecting with a deliberately corrupted one is refused with
    `kind="tls_fingerprint"`. Fail: the corrupted pin connects anyway.

    **PASSED 2026-08-17, PVE 9.2.10.** `node2` connected with its real
    fingerprint pinned, and refused a corrupted one with `kind="tls_fingerprint"`.
    The pin is load-bearing, not decoration.

    Not covered by the script, and still open: whether a *genuine* certificate
    replacement on a node produces the refusal in the UI. That needs
    `pvenode cert set` on a live node between opening the panel and ticking the
    box, which is a manual sequence rather than a scripted one.

**Run in both directions, 2026-08-17, PVE 9.2.10.** All of 13 to 16 were run
twice, once with each node as the origin, and passed both times. That is worth
doing rather than trusting one direction, because it cross-confirms the piece
neither run can check about itself: the certificate `node2` presents at its own
address is byte for byte the one read at the address `node1` reported for it,
and the same in reverse. So the `ip` in a peer's `/cluster/status` row leads to
the machine that node believes it does, and not merely to something that
answers on 8006. Token replication proved bidirectional too, each node's stored
monitoring token authenticating against the other.

## Frontend geometry

Card and dialog geometry moved off this list on 2026-08-13. `npm run harness`
measures both in real Chromium against the built CSS and fails CI on overflow,
unequal heights, or a panel exceeding its cap. It needs no host, so it is
automated rather than pending.

What remains unproven in a browser is anything requiring an authenticated
session: `/store` and every page behind login cannot be reached by the driver,
which has no way to log in.

## Known bug: SPA deep links 404 in production

`main.py` mounts `StaticFiles(directory=dist, html=True)` at `/`. That serves
`index.html` for a DIRECTORY, never for a client-side route, and every route in
this product is client-side. So refreshing on `/settings` or `/store/plex`
against the backend returns the app's 404 problem+json instead of the page.
Verified 2026-08-13: `:8000/settings` is 404 while `:5173/settings` is 200,
because Vite does the fallback in dev and nothing does it in production.

A first attempt at a fix registered a 404 exception handler that returned
`index.html` for HTML-accepting non-`/api` GETs. It worked for the SPA case and
broke two tests, because it also replaced the body of every OTHER 404: routes
that raise `HTTPException(404, {"error": "oidc_not_configured"})` pass a
structured detail that the replacement flattened away. Reverted.

The fix must leave every non-SPA 404 exactly as it is, which means delegating to
the app's existing handler rather than re-implementing its shape.
