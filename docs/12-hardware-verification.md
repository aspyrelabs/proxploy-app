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
against. Two notes for anyone rebuilding it:

- Joining a node replaces its `/etc/pve`, so `node2`'s Proxmox API token was
  destroyed and Proxploy lost it with a 401 until its host row was repointed at
  the now cluster-wide credentials. Root SSH went the other way and fixed
  itself: `/root/.ssh/authorized_keys` is a symlink into `/etc/pve/priv/`, so
  `node2` inherited `node1`'s key on join.
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

### Two things the first real install surfaced

Neither is a storage finding, and both were invisible to every fake.

**`build.func` now renders an interactive whiptail dialog mid-install.** A
"TELEMETRY & DIAGNOSTICS" menu with `<Confirm>` / `<Exit>` buttons drew itself
into the job transcript on 2026-08-14, in a non-TTY SSH session. It did not
block this run, but an interactive prompt reaching a session with no terminal
on the other end is precisely the failure class the storage work exists to
prevent, and it arrived from upstream without us changing anything. Worth a
standing check: nothing in `misc/build.func` should be able to ask a question
during a Proxploy install, and only reading the real transcript catches a new
one appearing.

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
8. **Network apply on a real bridge.** Applying a NIC change to a live guest,
   including the failure path where the change costs connectivity to the node
   performing it.
9. **Whole-storage prune.** Pruning across an entire storage, where the count
   of affected volumes and the time taken both differ materially from a fake.

## Privileges and identity

10. **Monitoring-token privilege paths.** A token lacking `Sys.PowerMgmt`
    should warn ahead of a power action rather than refuse it, and
    `node_power_missing` should be recomputed at enrolment and by
    `POST /hosts/{id}/test`. The tri-state (null meaning "not checked") is
    exactly the kind of thing a fake reports too cleanly.
11. **OIDC against a real IdP.** Proven against a local mock provider with a
    real discovery document, real PKCE, and RS256 tokens verified against a real
    JWKS endpoint. Everything except a third-party implementation on the wire.
    See `docs/superpowers/plans/2026-08-05-phase-8-scale.md`.

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
