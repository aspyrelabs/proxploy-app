# Phase 6 (Infra) — verification notes

## What shipped, per subsystem

**Storage** — `backend/proxploy/services/hostclient.py::client_for_host(app,
db, host)` (extracted so every route below shares one connection-resolution
path, raises `ProxmoxError`, never `HTTPException`/`JobFailed` directly).
`ProxmoxClient` (`services/proxmox.py`) gained `storages`, `storage_status`,
`storage_content`, `cluster_storage`, `storage_create`/`storage_update`/
`storage_remove`, `storage_upload`, `storage_delete_volume`. The poller
(`pollers/__init__.py`) now enriches `snap_storage` with `type`, `content`,
`shared`, `status` at zero extra PVE calls. `backend/proxploy/api/storage.py`:
`GET /storage`, `/storage/{host_id}/{name}`, `/storage/{host_id}/{name}/
content` (reads); `POST /storage/{host_id}/{name}/content` (multipart upload,
spooled to `data_dir/uploads` in 1 MiB chunks so a multi-GB ISO never sits in
process RAM, deleted in a `finally` on every exit path), `DELETE .../content/
{volid:path}`; `POST /storage`, `PATCH /storage/{host_id}/{name}`, `DELETE
/storage/{host_id}/{name}` (attach/edit/detach, synchronous — no job, no
UPID). `services/storagejobs.py` runs the upload/delete jobs. `main.py`'s
lifespan now `shutil.rmtree`s `data_dir/uploads` on boot, cleaning up any
spool file a crash left behind. Frontend: `api/storage.ts`, `StorageCard.tsx`,
`routes/storage.tsx`, `UploadDialog.tsx`, `StorageForm.tsx` (shared
attach/edit/detach dialog, reused by the Backups page for "Connect PBS").

**Network** — `backend/proxploy/services/netconfig.py` (`parse_net`/
`build_net`/`nic_identity`, an order-preserving `netN=` round-tripper — the
MAC lives in the head token and is never regenerated). `ProxmoxClient` gained
`node_networks`, `guest_config`, `guest_config_update`, `network_create`/
`network_update`/`network_delete`/`network_apply`/`network_revert`.
`backend/proxploy/api/network.py`: `GET /network/bridges` (live passthrough
per node + a guest NIC attachment map), `GET /network/throughput` (reads the
poller's existing `net_in_bps`/`net_out_bps` `MetricSample` rows — no second
metrics path), `POST /network/bridges`, `PUT`/`DELETE .../bridges/{host_id}/
{node}/{iface}` (all three stage into `/etc/network/interfaces.new`, no job),
`POST /network/{host_id}/{node}/apply` (202, job, typed node-name
confirmation — the phrase is the node name because a bad bridge config can
take the node off the network with no in-band undo), `POST .../revert` (200,
no job, no confirmation needed — it only deletes a staged file). Guest NIC
read/edit lives on the apps/vms routers: `GET`/`PUT /apps/{id}/network[/
{iface}]`, `GET`/`PUT /vms/{id}/network[/{iface}]`. Frontend: `api/
network.ts`, `NicForm.tsx`, `BridgeForm.tsx`, `routes/network.tsx`.

**Backups** — `backend/proxploy/services/backupjobs.py`: `parse_volid`
(recognizes both vzdump-on-local-storage and PBS volid shapes),
`sync_host_backups` (mirrors one host's archives into the `backups` table —
a droppable mirror, same shape as the poller's `vms` handling), the
`backup.sync` job, and an anti-stampede `threading.Lock()` around the
check-then-enqueue in `GET /backups` (`GET /backups` is polled every 60 s
from possibly several open tabs; without the lock, concurrent requests can
each see "no sync in flight" before any of their `Job` rows commit and
enqueue duplicate syncs — verified live: an unlocked build genuinely produced
`MultipleResultsFound` under a 16-thread race, the locked build didn't).
`ProxmoxClient` gained `vzdump`, `restore_guest`, `prune_preview`,
`prune_backups`. `backend/proxploy/api/backups.py`: `GET /backups` (served
from the cache table, auto-enqueues a `backup.sync` job when the cache has
gone stale so a fresh install never stays permanently blank — see "What was
NOT verified"), `POST /backups/run`, `POST /backups/{id}/restore` (in-place
or as-new; in-place refuses a missing guest, a self-targeted CT, an
unconfirmed request, and a running guest, in that order), `GET /backups/
prune-preview` (dry-run, GET-only, cannot delete anything), `POST /backups/
prune`, `DELETE /backups/{id}`. Frontend: `api/backups.ts`, `RestoreDialog.
tsx`, `routes/backups.tsx` — and `frontend/src/routes/placeholder.tsx` was
deleted (`git rm`), the last placeholder page in the app.

**VM lifecycle** — `ProxmoxClient` gained `snapshot_create`/
`snapshot_rollback`/`snapshot_delete` (create refuses `vmstate=True` for a
non-qemu kind), `vm_create`, `vm_clone`, `guest_delete`, `cluster_nextid`.
`backend/proxploy/services/guestjobs.py`: job handlers for all of the above
plus `network.apply`, and `_create_params` — the one place a Proxploy create
spec becomes PVE's qemu parameters (`virtio-scsi-single` + a virtio NIC,
matching the Proxmox UI's own defaults, not a passthrough of arbitrary PVE
keys). `backend/proxploy/api/vms.py`: `GET`/`POST /vms/{id}/snapshots`,
`POST .../snapshots/{name}/rollback` (typed VM-name confirmation), `DELETE
.../snapshots/{name}` (no confirmation — it doesn't touch the guest or its
disk), `POST /vms` (create, mints a `vmid` from `cluster_nextid()` when the
caller doesn't supply one), `POST /vms/{id}/clone`, `DELETE /vms/{id}`
(**owner** role, the most destructive route in the phase — checked in order:
self-target refusal, running-guest refusal, typed-confirmation, each denial
writing an audit row before the `HTTPException`). Frontend: `api/
snapshots.ts`, `SnapshotPanel.tsx`, `VmCreateWizard.tsx` (5-step: Target → OS
→ Resources → Network → Confirm), `CloneDialog.tsx`.

**Shared infra** — `backend/proxploy/services/pvetask.py::await_task` (polls
`task_status`, drains `task_log`, raises `JobFailed` on a non-`OK`
`exitstatus` or timeout) and `backend/proxploy/api/jobs.py::enqueue_and_
audit` (enqueue + write the audit row + return `{"job": ...}` in one call),
both extracted from `lifecycle.py`'s existing pattern and reused by every
route above.

## DoD verification map (doc 10 Phase 6)

DoD (doc 10 §Phase 6): *"every nav page now renders real content; a VM can be
created, snapshotted, rolled back, and cloned from the UI; a CT backs up to
PBS and restores as a new CTID; an ISO uploads through Proxploy."*

| Clause | Proving artifact | Verdict |
|---|---|---|
| Every nav page now renders real content | `frontend/src/tests/storage.test.tsx`, `network.test.tsx`, `backups.test.tsx` render each page against mocked endpoints and assert real rows, not placeholder copy; `frontend/src/routes/placeholder.tsx` no longer exists in the tree (confirmed: `ls` returns "No such file or directory"). Backend-side, `dod_verify_phase6.py` §1 proves every page's backing `GET` returns 200 with real fields (`type`, `content`, `shared`, …) | PROVED |
| A VM can be created, snapshotted, rolled back, and cloned from the UI | `dod_verify_phase6.py` §2 drives `POST /vms` → `POST .../snapshots` → `POST .../snapshots/{name}/rollback` (both the 409-without-confirm and the 202-with-confirm paths) → `POST .../clone` through the real routes, real `JobBackend`, and real audit path end to end. `frontend/src/tests/snapshots.test.tsx` and `vmcreate.test.tsx` drive the UI halves (form submission → mutation call → dialog state), under jsdom, not a browser | PROVED (backend end-to-end against `FakePVE`; UI half proved by render/interaction tests, not visually) |
| A CT backs up to PBS and restores as a new CTID | `dod_verify_phase6.py` §3: `POST /backups/run` → job succeeds → `GET /backups` returns the synced row (`guest_type="ct"`, `guest_vmid=150`, `verify_state="ok"`) → `POST /backups/{id}/restore` with `mode="new"` → the restore job's `nodes(node).lxc.post(...)` call carries `vmid=999`, the id `cluster_nextid()` minted, proving it targets a fresh ctid, not CT 150 | PROVED (against `FakePVE`, not a live PBS) |
| An ISO uploads through Proxploy | `dod_verify_phase6.py` §4: a 3 MiB payload POSTed as multipart to `/storage/{host_id}/local/content` returns 202, the job succeeds, `FakePVE.uploads` records the call, and the spool file under `data_dir/uploads` is gone afterward (proves the `finally`-delete) | PROVED for a 3 MiB payload only — see "What was NOT verified" for the real-size gap |

## `dod_verify_phase6.py` — real output

Run three times from `backend/` against `tests.support.make_app` + a real
`TestClient` + `tests/fakes/pve.py`'s `FakePVE` (no live PVE, no browser on
this box, matching every phase's stated limitation), output identical each
run:

```
=== 1. every nav page has a real backing endpoint ===
  GET /api/v1/storage                    -> 200
  GET /api/v1/network/bridges            -> 200
  GET /api/v1/network/throughput         -> 200
  GET /api/v1/backups                    -> 200
  storage rows carry type/content/shared: {'host_id': 1, 'host_name': 'host-01', 'node': 'pve1', 'storage': 'local', 'type': 'dir', 'content': ['iso', 'vztmpl', 'backup'], 'shared': False, 'status': 'available', 'used_bytes': 5368709120, 'total_bytes': 53687091200, 'used_pct': 10.0}

=== 2. VM created, snapshotted, rolled back, cloned ===
  POST /vms                -> 202 {'job': {'id': 2, 'kind': 'vm.create', 'status': 'queued', 'target_type': 'host', 'target_id': 1, 'params': {'host_id': 1, 'node': 'pve1', 'vmid': 999, 'name': 'web-01', 'cores': 2, 'memory_mb': 2048, 'disk_gb': 32, 'storage': 'local-lvm', 'iso': 'local:iso/debian-12.iso', 'bridge': 'vmbr0', 'vlan_tag': None, 'ostype': 'l26', 'start': False}, 'result': None, 'error': None, 'progress_pct': None, 'requested_by': 1, 'schedule_id': None, 'started_at': None, 'finished_at': None, 'created_at': '2026-07-31T16:43:01.832872Z'}, 'vmid': 999}
  create job: ('succeeded', None)
  POST …/snapshots         -> 202 vm.snapshot_create
  snapshot job: ('succeeded', None)
  GET  …/snapshots         -> 200 []
  rollback without confirm -> 409 confirm_required
  rollback with confirm    -> 202
  rollback job: ('succeeded', None)
  POST …/clone             -> 202
  clone job: ('succeeded', None)

=== 3. CT backs up to PBS and restores as a NEW ctid ===
  POST /backups/run        -> 202
  backup job: ('succeeded', None)
  GET  /backups            -> 200 stale: False
  synced backup row: ('ct', 150, 'ok')
  POST …/restore (as new)  -> 202 {'job': {'id': 7, 'kind': 'backup.restore', 'status': 'queued', 'target_type': 'backup', 'target_id': 1, 'params': {'backup_id': 1, 'mode': 'new', 'storage': None}, 'result': None, 'error': None, 'progress_pct': None, 'requested_by': 1, 'schedule_id': None, 'started_at': None, 'finished_at': None, 'created_at': '2026-07-31T16:43:02.188213Z'}}
  restore job: ('succeeded', None)
  restored to a NEW ctid, source CT 150 untouched

=== 4. an ISO uploads through Proxploy ===
  POST …/content (3 MiB)   -> 202 {'job': {'id': 8, 'kind': 'storage.upload', 'status': 'queued', 'target_type': 'storage', 'target_id': 1, 'params': {'host_id': 1, 'node': 'pve1', 'storage': 'local', 'content': 'iso', 'filename': 'debian-12.iso', 'path': '/tmp/phase6_dod/uploads/tmpiujva56t.upload', 'size_bytes': 3145728}, 'result': None, 'error': None, 'progress_pct': None, 'requested_by': 1, 'schedule_id': None, 'started_at': None, 'finished_at': None, 'created_at': '2026-07-31T16:43:02.275240Z'}}
  upload job: ('succeeded', None)
  temp spool files left behind: []

=== 5. every mutation wrote an audit row ===
  audit actions: ['auth.login', 'backup.restore', 'backup.run', 'storage.upload', 'user.create', 'vm.clone', 'vm.create', 'vm.snapshot_create', 'vm.snapshot_rollback']

PROVED: all four doc-10 Phase 6 DoD clauses, through the real routes, the real JobBackend and the real audit path.
```

Two genuine bugs in the script itself were found and fixed while getting this
output (not the production code — both are logged as comments in the script
for the next person who copies it): `tests/fakes/pve.py::content_by_storage`
is typed `dict[str, list[dict]]` and keyed by storage name alone, not a
`(node, storage)` tuple as first drafted — every content lookup silently
returned `[]` until this was caught by re-reading the fake; and `POST
/backups/run`'s own end-of-job resync must see the new archive in
`content_by_storage` *before* the job runs, not after — the first draft set
it after `_await()`-ing the job and got a bare `NoResultFound` because the
job's own resync had already run and found nothing, and `GET /backups`'
stale-triggered resync never fired since the cache was already fresh.

## Gate numbers (real, captured this run)

| Gate | Command | Result |
|---|---|---|
| Backend tests | `pytest tests/ -q -m "not pve_integration and not e2e"` | **491 passed, 2 skipped, 4 deselected**, 178.01s (deselected rose from 3 to 4 — this task's new `pve_integration`-marked test) |
| Executor isolation | `python scripts/check_executor_isolation.py` | **OK** — unaffected, this phase never touches SSH |
| Backend license audit | `pip-licenses --partial-match --ignore-packages proxploy --allow-only "..."` | **FAILS locally** on `psycopg:3.3.4` (LGPL-3.0-only) — pre-existing, documented since Phase 1 and again in Phase 4's notes: `psycopg` lives in the `postgres` extras group, not `dev`; CI's `backend` job only installs `.[dev]`, so this package is never present when the real gate runs. This local venv has `postgres` extras installed too, for Postgres-portability testing. **Not a Phase 6 regression.** Confirmed the two dependencies this phase actually adds are both cleanly inside the allowlist: `python-multipart 0.0.32` → `Apache-2.0`, `requests-toolbelt 1.0.0` → `Apache Software License` |
| Migrations | `pytest tests/test_migrations.py -q` | **7 passed, 2 skipped** |
| Alembic heads | `alembic -c alembic.ini heads` | **`2330a95b98d2` (head)** — unchanged; this phase adds no migration |
| Frontend tests | `npx vitest run` | **118 passed (26 files)** |
| Frontend build | `npm run build` | **clean** (`tsc -b` + vite build; one pre-existing "chunk > 500 kB" warning, not a new regression) |
| Frontend lint | `npm run lint` (oxlint) | **exit 0** — warning-only output (`only-export-components`, `exhaustive-deps`), the same pre-existing classes spread across dozens of pre-Phase-6 files (route/loader co-location, a couple of missing-dep hooks); no errors, nothing new introduced by this phase |

## Every endpoint added this phase

| Method + path | Role | Entitlement | Notes |
|---|---|---|---|
| `GET` `/api/v1/storage` | viewer | `storage.view` | poller-cached |
| `GET` `/api/v1/storage/{hostId}/{name}` | viewer | `storage.view` | live passthrough |
| `GET` `/api/v1/storage/{hostId}/{name}/content` | viewer | `storage.content` | live passthrough |
| `POST` `/api/v1/storage/{hostId}/{name}/content` | admin | `storage.content` | multipart upload → job |
| `DELETE` `/api/v1/storage/{hostId}/{name}/content/{volid}` | admin | `storage.content` | → job |
| `POST` `/api/v1/storage` | admin | `storage.manage` | attach, synchronous |
| `PATCH` `/api/v1/storage/{hostId}/{name}` | admin | `storage.manage` | edit, synchronous |
| `DELETE` `/api/v1/storage/{hostId}/{name}` | owner | `storage.manage` | detach, synchronous |
| `GET` `/api/v1/network/bridges` | viewer | `network.view` | + guest NIC attachment map |
| `GET` `/api/v1/network/throughput` | viewer | `network.view` | reads existing metric rows |
| `GET`/`PUT` `/api/v1/apps/{id}/network[/{iface}]` | viewer / operator | `network.guest_config` | |
| `GET`/`PUT` `/api/v1/vms/{id}/network[/{iface}]` | viewer / operator | `network.guest_config` | |
| `POST` `/api/v1/network/bridges` | admin | `network.host_config` | stages, no job |
| `PUT`/`DELETE` `/api/v1/network/bridges/{hostId}/{node}/{iface}` | admin | `network.host_config` | stages, no job |
| `POST` `/api/v1/network/{hostId}/{node}/apply` | admin | `network.host_config` | typed node-name confirm → job |
| `POST` `/api/v1/network/{hostId}/{node}/revert` | admin | `network.host_config` | no confirm, no job |
| `POST` `/api/v1/backups/run` | operator | `backups.run` | → job |
| `POST` `/api/v1/backups/{id}/restore` | admin | `backups.restore` | in-place or as-new → job |
| `GET` `/api/v1/backups/prune-preview` | admin | `backups.retention` | dry run, GET only |
| `POST` `/api/v1/backups/prune` | admin | `backups.retention` | → job, unconsumed by UI (see Deviations) |
| `DELETE` `/api/v1/backups/{id}` | admin | `backups.retention` | → job — corrected from `backups.pbs` in the final whole-branch review (2026-07-31): that key also gates the read-only backup list, so anyone who could see backups could permanently delete them |
| `GET` `/api/v1/vms/{id}/snapshots` | viewer | `vms.snapshots` | live, filters synthetic `current` |
| `POST` `/api/v1/vms/{id}/snapshots` | operator | `vms.snapshots` | → job |
| `POST` `/api/v1/vms/{id}/snapshots/{name}/rollback` | admin | `vms.snapshots` | typed VM-name confirm → job |
| `DELETE` `/api/v1/vms/{id}/snapshots/{name}` | operator | `vms.snapshots` | no confirm → job |
| `POST` `/api/v1/vms` | admin | `vms.create` | → job |
| `POST` `/api/v1/vms/{id}/clone` | admin | `vms.clone` | → job |
| `DELETE` `/api/v1/vms/{id}` | owner | `vms.create` | 3-gate refusal chain → job |

## Deviations from the plan

- **Phase 6 shipped two new backend dependencies, not one.** Both the plan's
  own header and this task's brief claimed one. `python-multipart>=0.0.9`
  (Apache-2.0) was added in Task 4 Step 0 because FastAPI refuses to define
  an `UploadFile`/`File(...)` route without it — confirmed via a standalone
  script that route registration itself raises. `requests-toolbelt>=1.0`
  (Apache Software License) was added later, in Task 4's own fix round, for a
  reason no fake could surface: `proxmoxer/backends/https.py`'s
  `ProxmoxHttpSession.request` only takes the true streaming-multipart path
  when `requests_toolbelt.MultipartEncoder` is importable *and* the payload
  exceeds proxmoxer's 10 MiB streaming threshold; without the package, an
  upload under proxmoxer's ~2 GiB SSL limit silently falls back to plain
  `requests`, which reads the whole file into memory, and anything larger
  hard-fails with `OverflowError`. `storage_upload_max_bytes` defaults to
  16 GiB, so without this dependency the entire premise of the upload feature
  — that a multi-GB ISO is safe to proxy — was false on the PVE-facing leg,
  and no test caught it because `FakePVE` replaces `self._connect()` wholesale
  and never touches `proxmoxer.backends.https` at all. Fixed with a dedicated
  test (`test_proxmoxer_streams_large_uploads_via_requests_toolbelt`) that
  exercises the real `ProxmoxHttpSession` with only `requests.Session.request`
  monkeypatched, so no network call happens but the real streaming decision
  is genuinely exercised. Both dependencies are inside the CI license
  allowlist, which was never widened for either.
- **Zero Alembic migrations, as planned.** The `backups` table and every
  column this phase populates (`storage`, `volid`, `guest_type`,
  `guest_vmid`, `guest_name`, `taken_at`, `size_bytes`, `verify_state`,
  `notes`, `synced_at`) had existed, unused, since migration 0001 — Task 8
  was the first task to write to it. `alembic heads` is `2330a95b98d2` before
  and after this phase.
- **Doc 05 was amended** (this task, Step 5) for the three real omissions
  the brief named: §Network was missing the guest- and host-network-config
  endpoints entirely (only `/bridges` and `/throughput` were listed); the
  entitlement column was blank on six read endpoints this phase gates
  (`GET /storage`, `/storage/{h}/{n}`, `/storage/{h}/{n}/content`,
  `/network/bridges`, `/network/throughput`, `/vms/{id}/snapshots`) — now
  filled in, with a new §Conventions note explaining a blank cell means
  "never gated," not "forgotten"; and §Backups was missing
  `GET /backups/prune-preview` and `POST /backups/prune` outright. **A
  fourth, unrequested fix found while in the same table**: §Backups listed
  `POST /backups/run` and `POST /backups/{id}/restore` as both gated on
  `backups.pbs`; the code (`api/backups.py`) actually gates them on
  `backups.run` and `backups.restore` respectively — real, distinct
  entitlement keys doc 01 §17's canonical flag index already defines. Fixed
  in the same pass rather than left for whoever next trusts this table.
- **A documentation defect fixed in the same pass**: `api/vms.py`'s
  snapshot-rollback docstring claimed it "reuses the exact 409 body
  `enqueue_lifecycle` uses for a self-targeted stop." It reuses the *shape*
  (`error`/`confirm_phrase`/`detail`) but not the *value* — rollback emits
  `"error": "confirm_required"` because it asks for confirmation from every
  caller, not only a self-targeted one, while `enqueue_lifecycle`'s
  self-targeted-stop 409 emits `"error": "self_target"`. The frontend keys on
  the specific string (`RestoreDialog.tsx` and `LifecycleActions.tsx` each
  branch on one string only, `SnapshotPanel.tsx` deliberately accepts both) —
  the docstring's conflation was corrected, not the code, which was already
  right.
- **An adjudicated design decision, recorded here rather than re-litigated**:
  of the four ways `POST /backups/{id}/restore`'s in-place path can refuse
  (`guest_missing`, `self_target`, `confirm_required`, `guest_running`), only
  `self_target` writes an audit row. The other three are ordinary, retryable
  UX rejections — the guest vanished, the caller typed the wrong name, the
  guest is running — that an operator corrects on the next attempt with no
  adversarial angle to them; auditing every one would flood the log with
  routine friction. `self_target` is different: it is the one refusal a
  caller cannot walk back from by retrying, the non-retryable and
  unbypassable case whose entire purpose is a forensic record that someone
  tried to restore over Proxploy's own container. `vm.delete`'s three-gate
  chain (`self_target`/`guest_running`/`confirm_required`) audits all three
  denials — a narrower, deliberately inconsistent choice, since a VM's
  self-target path is unreachable today (no VM-hosted install exists) and
  its audit cost is effectively zero, so there was no log-flooding tradeoff
  to weigh there.
- **Deliberate simplifications carried forward by name**, none blocking the
  DoD:
  - The staged-network-changes indicator (a "you have unsaved changes"
    badge) was not built. PVE reports pending state as a `changes` property
    that is a *sibling* of `data` on `GET /nodes/{node}/network`, and
    proxmoxer's `.get()` unwraps `data` and discards everything else —
    reading it would mean bypassing the client layer, which `proxmox.py`'s
    own module docstring forbids. Apply/Revert are always offered rather
    than enabled-when-dirty; a no-op apply is a harmless extra `ifreload`.
    Upgrade path: a raw-response accessor on `ProxmoxClient`, if the UI ever
    needs the badge.
  - Linked-clone validity is not pre-checked. Proxploy has no `template`
    column on `Vm` and the poller does not read `/cluster/resources`'s
    `template` field, so PVE's own rejection of a linked clone from a
    non-template guest is surfaced verbatim rather than guessed at here.
  - `POST /backups/prune` ships this phase, entirely unwired to any UI
    control — the prune-preview section is GET-only with a "dry run, deletes
    nothing" banner. Actual pruning-by-policy belongs to Phase 7's
    scheduler.
  - `sync_host_backups` reads only `Host.node_name` — one node per host row.
    Shared datastores (PBS, NFS, CephFS) report identically from any node in
    a cluster, so they sync completely; node-local vzdump archives on a
    cluster's *other* nodes are not discovered until `Host` models more than
    one node.

## What was NOT verified

- **No live Proxmox host.** Every PVE interaction in this phase was proved
  against `tests/fakes/pve.py`'s `FakePVE`, not a real API.
  `backend/tests/test_infra_pve_integration.py` is the placeholder for when
  a disposable one exists. This is the standing limitation every phase since
  Phase 1 has stated, and it bites hardest here: this is the first phase
  whose operations **write** to storage, network, and guest configuration
  rather than only reading them.
- **No browser.** The three new pages and four new dialogs are proved by
  jsdom render tests, not by a human or a headless browser looking at them.
  Layout, the 80%-usage red storage bar, and the `LockVeil` visuals are
  visually unverified.
- **The host-network apply path is the highest-risk unverified code in the
  product.** A wrong bridge config applied to a node can permanently cut
  that node off the network until someone reaches its physical console, and
  no fake can prove PVE's real apply/revert semantics on either PVE 8.x or
  9.x. Said plainly: this is a real risk carried forward, not a hypothetical
  one covered by the typed-confirmation UI.
- **The ISO upload double-transfers** (browser → Proxploy → PVE) and needs
  transient disk on the Proxploy host equal to the file size; the cap is
  `storage_upload_max_bytes` (16 GiB default). `dod_verify_phase6.py`
  exercised only a 3 MiB payload — no real multi-GB ISO was ever pushed
  through this code path on this box. The `requests-toolbelt` fix (see
  Deviations) makes the streaming path *possible*; it does not make the
  large-file path *tested*. **This caveat is load-bearing, not cosmetic**
  (final whole-branch review, 2026-07-31, see BLOCKING 4): the PVE-side task
  for a real multi-GB ISO upload can genuinely exceed `pve_task_timeout_s`,
  and a 3 MiB payload's task finishes too fast to exercise that ceiling at
  all — so this DoD proof and the timeout ceiling are two different unverified
  edges of the same upload path, not one.
- **Correction (final whole-branch review, 2026-07-31): three endpoints ship
  unconsumed by the UI, not two.** The original list named `POST
  /backups/prune` (see Deviations) and the `vmstate` option on non-qemu
  guests (LXC snapshots have no `vmstate` concept; `ProxmoxClient.
  snapshot_create` refuses `vmstate=True` for a non-qemu kind server-side,
  but nothing in the UI exercises the refusal for a human to see), and
  omitted `DELETE /vms/{id}` — which this same document's endpoint table
  calls **the most destructive route in the phase** (owner role, 3-gate
  refusal chain) and which has no frontend consumer at all.
- **`GET /backups` auto-enqueues a sync when the cache is stale**, so the
  first load of a fresh install returns an empty list and fills in moments
  later — correct behavior, but worth knowing before someone reports it as a
  bug. `dod_verify_phase6.py` had to work around exactly this ordering to
  get a deterministic proof (see the script-output section above).
- **`test_concurrent_stale_reads_enqueue_only_one_sync`
  (`tests/test_backups_sync.py`) is slow and timing-variable**: measured
  62s, 62s, and 2s across three isolated runs in this task, passing every
  time. Not a flake in the sense of failing — it genuinely proves the
  anti-stampede lock under a real 16-thread race — but its wall-clock cost is
  uneven and worth knowing about before someone "fixes" a slow CI run by
  deleting it.
- **Correction (final whole-branch review, 2026-07-31): only one of the three
  suspected false-negative tests was actually broken.** The original claim
  here was that all three `window.confirm`-dismissed tests in `src/tests/
  backups.test.tsx` and `src/tests/storage-mutations.test.tsx` (detach,
  volume delete) asserted `calls.length === 0` synchronously right after
  `fireEvent.click` with no flush, and therefore all three would pass even
  with the production `window.confirm` guard removed. The final review
  verified each of the three individually by neutralising its guard and
  re-running: `storage-mutations.test.tsx`'s **detach** test ("confirms
  before detaching and does nothing when the operator cancels") genuinely was
  a false negative and has been fixed with the macrotask-flush idiom (`await
  new Promise(r => setTimeout(r, 10))`, borrowed from `settings.test.tsx`).
  `backups.test.tsx`'s delete-archive test and `storage-mutations.test.tsx`'s
  **volume-delete** test were both proven load-bearing as written — each
  fails when its guard is neutralised, via a `waitFor` already present
  further down in the same test — and were deliberately left untouched.
