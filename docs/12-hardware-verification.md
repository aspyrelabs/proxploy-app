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

The hardware available on 2026-08-14 does not meet this shape: `node1` and
`node2` each carry exactly one `rootdir` pool (`local-lvm`) and one `vztmpl`
pool (`local`), and are standalone rather than clustered. That is enough for
check 3 and for the remembered-value half of 3b, and not enough for 2, 3a, or
the status half of 3b.

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
2. **An explicitly chosen non-default storage is honoured.** In Advanced,
   select a container storage that is NOT the one a single-storage host would
   have auto-picked. Pass: `pct config <ctid>` shows the rootfs on the pool that
   was chosen. Sending the variable is not the claim; the container landing
   there is.
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

   **NOT EXERCISABLE on the 2026-08-14 hardware.** `node1` and `node2` are two
   standalone hosts, not a cluster: each `/cluster/resources` reports only its
   own node, and every storage row comes back `shared: 0`. With no shared pool
   and no second node in either result set, the node-filter exemption this
   check exists to prove is never reached. Still open.
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

   The status half is still open. It needs a pool to go non-`available`, and
   both hosts carry exactly one `rootdir` pool and one `vztmpl` pool, so
   disabling either leaves zero candidates rather than the "one of two
   disappears" shape the check describes. It also cannot be run without
   mutating live storage on the host.

### Install execution, carried from phase 4

4. **A container is created at a chosen CTID on a real node.** Currently proven
   only as far as the command string. Pass: the CT exists at exactly the CTID
   requested.
5. **Blank CTID lands on the node's next available ID**, via
   `${var_ctid:-$NEXTID}`, with `var_ctid` absent from the environment.
6. **`AcceptEnv` behaviour against a real `sshd`.** Env vars are inlined into
   the command string precisely because a real server's `AcceptEnv` config
   makes asyncssh's `env=` silently no-op. The fix is safer either way, but the
   original behaviour was never reproduced against a live `sshd`.

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
