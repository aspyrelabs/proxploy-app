# Phase 6 (Infra pages) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill in the last three placeholder nav pages, Storage, Network, Backups; with real content, and complete the VM surface with snapshots, a create wizard and clone, so every page in doc 01 §0's fixed nav renders live infrastructure and every guest-shaped operation (create, snapshot, roll back, clone, back up, restore) runs as a tracked, audited job.

**Architecture:** No new persistence. Storage and network are **live reads**, storage list is served from the poller's existing in-memory `HostSnapshot.storage` (enriched this phase with the `plugintype`/`content`/`shared`/`status` fields `/cluster/resources` already returns and the poller currently discards), per-datastore detail and content listings are on-demand passthroughs, and network interfaces are a pure passthrough to `/nodes/{node}/network` (doc 04 defines no storage or network table; doc 05 calls them "live-refreshed cache" and "live passthrough" respectively). Backups reuse the `backups` **cache** table that migration 0001 already created and nothing has ever written (doc 04 §Backups). VM snapshots are read live from Proxmox on every request (doc 05: "List snapshots (live from Proxmox)"). **Phase 6 therefore ships zero Alembic migrations**: a deliberate, verified finding, not an oversight: every column this phase needs already exists. Every mutation (upload, delete volume, backup, restore, prune, snapshot create/rollback/delete, VM create/clone/delete, host-network apply) is a JobBackend job that posts to Proxmox, gets a UPID back, and polls that UPID to completion; the exact shape `services/lifecycle.py::run_lifecycle` already proves, extracted this phase into one shared `await_task` helper so twelve new handlers do not copy-paste it twelve times.

**Tech Stack:** FastAPI + SQLAlchemy 2 + proxmoxer (existing) plus exactly **one new backend dependency**, `python-multipart` (Apache-2.0), which FastAPI hard-requires before it will even define an `UploadFile` route; verified absent from this venv, not assumed present (Task 4 Step 0); React 19 + TanStack Query/Router + uPlot + Tailwind v4 (existing, **zero new frontend dependencies**).

## Global Constraints

- **Zero new Alembic migrations.** Head stays `2330a95b98d2` (0004). The `backups` table and every column this phase writes already exist from migration 0001. If a task believes it needs a new column, stop and re-read `backend/proxploy/models/__init__.py`; it is almost certainly already there. (Adding `metric_samples` targets or `settings` rows needs no migration either.)
- **Exactly one new runtime dependency**, added in Task 4 Step 0 with the doc-03 license-verification protocol run at the moment it is added: `python-multipart>=0.0.9` (Apache-2.0, already inside the CI audit's allowlist). `package.json` is **not** edited by this phase, zero new frontend dependencies.
- **The error envelope is FLAT, and every task depends on this.** `main.py::problem_handler` does `body.update(exc.detail)` when `exc.detail` is a dict, so `raise HTTPException(409, {"error": "confirm_required", "confirm_phrase": name, "detail": "…"})` reaches the browser as `{"type","title","status","error","confirm_phrase","detail"}`, `detail` is the human-readable string, never a nested object. Backend tests assert `r.json()["error"]`; frontend reads `e.body.error`, exactly as `LifecycleActions` already does. Do not write `r.json()["detail"]["error"]`; it raises `TypeError: string indices must be integers`.
- `proxploy/services/proxmox.py`'s module docstring rule holds absolutely: *every* proxmoxer call and *every* PVE-8-vs-9 branch lives in that one module. Routers, job handlers and pollers call `ProxmoxClient` methods; they never touch a proxmoxer object.
- Nothing outside `proxploy/executor/` may `import asyncssh` or reference `get_ssh_private_key` (`backend/scripts/check_executor_isolation.py`, CI-wired). **Unaffected by this phase**: every Phase 6 operation goes through the Proxmox REST API, never SSH.
- All new backend routers are registered in `proxploy/api/__init__.py` via `api_router.include_router(...)`; there is no auto-discovery. All new job-handler modules are imported in `proxploy/main.py`'s lifespan (the `# noqa: F401` block at lines 83-85) or their `HANDLERS` registration never runs.
- **Route-ordering hazard (this phase's single most likely silent bug).** Starlette matches in registration order. `api/vms.py` ends with the catch-all `POST /{vm_id}/{action}` and `api/apps.py` with `POST /{app_id}/{action}`. Every new two-segment sibling (`/vms/{id}/snapshots`, `/vms/{id}/clone`, `/vms/{id}/network`, …) **must be registered above** that wildcard or the wildcard swallows it and the action string arrives as `"snapshots"`. `apps.py:266-271` already carries the warning comment; each task that adds such a route asserts the ordering in a test.
- **Entitlement dependency ordering** (`api/deps.py`): a module-level `_require_<role> = require_role("<role>")` singleton comes **first** in `dependencies=[...]`, the `require_entitlement(...)` second, and the same singleton is reused as the parameter dependency so FastAPI's dependency cache collapses them. A bare `dependencies=[Depends(require_entitlement(k))]` runs before auth and returns 403 to anonymous callers, which `tests/test_route_auth_invariant.py` fails on. Every new route is automatically subject to that invariant test plus `test_no_secret_echo.py`.
- **Entitlement keys are already registered.** All 81 keys ship in `proxploy/entitlements/registry.py`; every key this phase needs (`storage.view/content/manage`, `network.view/guest_config/host_config`, `backups.pbs/run/restore/retention`, `vms.snapshots/create/clone`) already exists and defaults ON. **No registry edits.** Keys never change once shipped (doc 07 §3).
- **Deliberate, documented deviation from doc 05's entitlement column:** doc 05 leaves the entitlement blank on `GET /storage`, `GET /storage/{h}/{n}`, `GET /storage/{h}/{n}/content`, `GET /network/bridges`, `GET /network/throughput` and `GET /vms/{id}/snapshots`. Doc 01 §§4-7 defines `storage.view`, `network.view` and `vms.snapshots` as real features with real keys, and doc 07 §3 is explicit that a feature without a key does not merge. This plan gates those reads with their doc-01 keys so the keys are live rather than dead. Functionally identical today (all flags ON); the phase notes doc records the amendment to doc 05.
- Every DB-touching test uses the existing sqlite-per-`tmp_path` conventions (`tests/support.py::make_db`/`make_app`/`make_job_app`, `tests/conftest.py::client`). No new fixture infrastructure unless a task says so explicitly.
- **No `relationship()` declarations** anywhere in `proxploy/models/__init__.py`, every association is a bare `ForeignKey` plus an explicit query. Follow that.
- Frontend server state lives exclusively in TanStack Query (doc 06 §d). Small UI state (open dialog, active filter) lives in `useState` or URL search params. There is **no form library, no shadcn CLI install, no Radix, no `cn()` helper** in this repo; forms are `useState` + a `submit` handler, dialogs are hand-rolled fixed-overlay divs, tables are hand-rolled `<table>` markup. Match that, do not introduce a UI framework.
- **The nav is fixed** (doc 01 §0) and `src/tests/nav.test.tsx` asserts its exact 8 labels in order. Storage/Network/Backups entries already exist and already point at `/storage`, `/network`, `/backups`. **Do not touch `SidebarNav.tsx` or `nav.test.tsx`.**
- Design tokens: card surface is `rounded-card border border-line-soft bg-panel p-5` (copy the local `const card` string each route file declares). Numeric/identifier text is `font-mono`. Sizes are explicit arbitrary values (`text-[13px]`), not Tailwind's named scale. Violet (`STORAGE_GRADIENT`, `#A78BFA→#6D5AE6`) is reserved for storage; blue for network; red for danger and >80% usage. Terminal/code panels stay `#0a0e14` in both themes.
- **Never hide a gated feature** (doc 06 §e rule 1), veil it. `components/LockVeil.tsx` is written and currently unused; Phase 6's Pro surfaces (`storage.manage`, `network.host_config`, `backups.retention`, `vms.clone`) are its intended first consumers. Small inline actions use the disabled+tooltip treatment instead. Always gate on `ent.data != null && !ent.has(key)`, `has()` returns `false` before the first fetch resolves, so gating on `!has(x)` alone greys the control out for every plan during load.

---

## Reference: what already exists (verified against the tree, 2026-07-31)

This section exists so a task implementer never has to go hunting. Every path,
name and signature below was read out of the repo while writing this plan.

### Backend spine

- **`ProxmoxClient`** (`backend/proxploy/services/proxmox.py`) currently exposes exactly: `version()`, `permissions()`, `cluster_resources()`, `node_rrddata(node, timeframe="hour")`, `guest_action(kind, node, vmid, action)`, `task_status(node, upid)`, `task_log(node, upid, start=0, limit=500)`, `termproxy(kind, node, vmid)`, `node_termproxy(node)`, `vncproxy(node, vmid)`. Module helpers: `ProxmoxError`, `parse_token_id`, `token_public_meta`, `default_factory`, `resolve_target`, `open_validated_tcp_socket`, `tls_fingerprint_sha256`. Private `_wrap(prefix, e)` is the ONE credential-scrubbing point, every new method wraps its proxmoxer call in `try/except Exception as e: raise self._wrap("<prefix>", e)`.
- **JobBackend** (`proxploy/jobs/__init__.py` re-export facade, import from there, never `.backend`): `HANDLERS: dict[str, Callable]` is the whole registry (a plain dict keyed by `"noun.verb"`), `TERMINAL = ("succeeded","failed","canceled","interrupted")`, `JobFailed`, `JobContext` (`.log(message, stream="stdout")`, `.progress(pct)`, `.backend.app`), `handler(kind)` decorator (defined, unused; existing modules assign `HANDLERS["x.y"] = fn` directly), `JobBackend.enqueue(db, *, kind, target_type=None, target_id=None, params=None, requested_by=None, schedule_id=None) -> Job` called as `request.app.state.jobs.enqueue(...)`.
- **Existing job kinds:** `app.{start,stop,restart,shutdown}`, `vm.{start,stop,restart,shutdown,pause,resume}` (`services/lifecycle.py`), `app.install` (`services/appstore.py`), `catalog.refresh` (`services/catalog.py`).
- **`services/lifecycle.py::run_lifecycle`** is the canonical UPID-polling handler; `_resolve(app, target_type, target_id)` is its blocking target→`(client, kind, node, vmid, name)` resolver that opens `app.state.sessionmaker()`, loads the row + `Host` + `HostCredential(kind="api_token")`, `jsonlib.loads(app.state.secretstore.decrypt(cred.encrypted_blob))`, and constructs `ProxmoxClient(..., factory=app.state.proxmox_factory)`.
- **`api/consoles.py:26::_proxmox_client_for_host(app_state, db, host)`** is the same decrypt-then-construct helper, carrying a comment that a 4th call site is the extraction tip-over point. Phase 6 is that tip-over point (Task 1).
- **`api/apps.py::enqueue_lifecycle(request, db, user, *, target_type, target, action, name, confirm)`** is the canonical enqueue+audit+selfguard route helper. `api/jobs.py` exports `job_out(j) -> dict` and `backlog(db, job_id, after=0, limit=5000)`.
- **`services/audit.py::write_audit(db, *, actor_type, action, actor_id=None, target_type=None, target_id=None, params=None, result="ok", ip=None, request_id=None, job_id=None)`**; commits itself, keyword-only after `db`. Also exports `redact(obj)`, `REDACT_KEYS`, `REDACT_SUBSTRINGS = ("secret","password","passwd","token","credential","url","dsn","private")`. Convention: `ip=request.client.host if request.client else None`; a row that spawned a job sets `job_id` (the activity feed skips those to avoid double display).
- **`api/deps.py`**: `ROLE_ORDER = {"viewer":0,"operator":1,"admin":2,"owner":3}`, `get_db`, `get_current_user`, `user_role(db, user)`, `require_role(min_role)`, `default_team(db)`, `get_entitlements(request)`, `require_entitlement(key)`.
- **`services/selfguard.py`**: `DESTRUCTIVE = frozenset({"stop","shutdown","restart","pause"})`, `is_self(db, target_type, target_id) -> bool` (fails open when the `self.ctid` setting is unset). `enqueue_lifecycle` raises `409 {"error":"self_target","confirm_phrase":name}` when `is_self()` and the action is destructive.
- **Poller** (`proxploy/pollers/__init__.py`, one file): `HostSnapshot(host_id, ts, nodes, storage, net, guests, discovered)` dataclass, `ingest_cycle(db, host, resources, rrd_by_node, now) -> CycleResult`, `Poller.snapshots: dict[int, HostSnapshot]` (in-memory only). Per host it makes exactly two kinds of PVE call, one `cluster_resources()` and one `node_rrddata(n)` per node (doc 02 §3's O(nodes) budget; per-guest calls in the poll loop are forbidden). Its current storage handling is the whole storage story today:
  ```python
  storage_rows = [r for r in resources if r.get("type") == "storage"]
  snap_storage = [
      {"storage": r.get("storage"), "node": r.get("node"),
       "used_bytes": int(r.get("disk") or 0),
       "total_bytes": int(r.get("maxdisk") or 0)}
      for r in storage_rows
  ]
  ```
- **`api/cluster.py::cluster_summary`** already aggregates `poller.snapshots[*].storage` deduped by name, with a `# ponytail:` comment at cluster.py:34-36 saying "per-datastore truth arrives with the Phase 6 Storage page". Enriching the snapshot dict must not break it.
- **Models** (`proxploy/models/__init__.py`, single file): `Base`, `TimestampMixin`, `utcnow()`, `BigPK`. Relevant rows, `Host(id, name, address, node_name, cluster_name, verify_tls, tls_fingerprint, status, pve_version, last_seen_at, ssh_host_key_fingerprint, node_shell_enabled, team_id)`, `App(id, host_id, ctid→physical column "ct_id", name, slug, …, status_cached, …)`, `Vm(id, host_id, vmid, name, status, os_type, cpu_cores, mem_bytes, disk_bytes, uptime_s, synced_at)`, `Backup(id, host_id, storage, volid, guest_type, guest_vmid, guest_name, taken_at, size_bytes, verify_state, notes, synced_at)` + `TimestampMixin`, unique `ux_backups(host_id, volid)`, index `ix_backups_guest(guest_type, guest_vmid)`, `Job`, `JobEvent`, `AuditEvent`, `AppSetting(key, value JSON)`.
- **Test infra**: `tests/support.py::make_db(tmp_path)`, `seed_host_row(db, name="host-01", node="pve1", status="connected")`, `make_app(tmp_path, fake=None, ssh_factory=None, **overrides)` (poller OFF by default), `seed_snapshot(app, host_id, **kw)` (builds a `HostSnapshot` and installs it into `poller.snapshots`; this is how a storage-endpoint test injects data without a poll loop), `make_job_app(tmp_path, fake=None, ssh_factory=None)` (must be called from inside a running event loop). `tests/conftest.py` gives exactly three fixtures: `client`, `csrf_header` (callable → `{"X-CSRF-Token": …}`, needed on every non-GET), `bootstrap_admin` (callable → logged-in owner client). `tests/fakes/pve.py::FakePVE(version=None, permissions=None, fail=False, resources=None, rrddata=None, task_exit="OK", running_ticks=0, rrd_fail=False)` + `make_fake_factory(fake)`; its node namespace `_NodeNS` currently wires `.rrddata`, `.tasks(upid).{status,log}`, `.lxc(vmid)`, `.qemu(vmid)`, `.termproxy`. Actions auto-record into `fake.actions` and mint a synthetic UPID; `_task_status` returns `{"status":"running"}` for `running_ticks` polls then `{"status":"stopped","exitstatus": fake.task_exit}`.
- **Test command:** `cd backend && python -m pytest tests/ -q -m "not pve_integration and not e2e"`. Markers: `pve_integration`, `e2e`. Phase 5 left the suite at **340 passed, 2 skipped, 3 deselected**.

### Frontend spine

- **Routing is code-based**, assembled in `src/router.tsx`. Route files import `shellRoute` from `./shell`, **never from `../router`** (importing `router.tsx` forces its eager `createRouter()` to run mid-cycle). Cross-file `Link to=` / `navigate({to})` are all written with `as never` casts because circular route-file imports defeat inference, reproduce that, every existing call site does it. `useParams({ strict: false }) as { … }` is the params idiom.
- **`src/router.tsx` currently declares three placeholder pages** via a local `page(path, title, phase, note)` helper → `storageRoute`, `networkRoute`, `backupsRoute` rendering `PlaceholderPage`. `routes/vms.tsx` declares a local `phaseTab(path, phase, note)` helper → `vmSnapshotsRoute` rendering an `EmptyState`. Phase 6 replaces all four and deletes both helpers plus `src/routes/placeholder.tsx`.
- **`src/api/client.ts`**: `api<T>(path, opts)` prefixes `/api/v1`, sends `credentials: 'include'`, sets `Content-Type` when there is a body, sets `X-CSRF-Token` from the `pp_csrf` cookie on POST/PUT/PATCH/DELETE, returns `null` on 204, throws `ApiError(status, body)` otherwise. **A multipart upload cannot use `api()`**: it would force `Content-Type: application/json` over the `FormData` boundary; Task 13 uses a bare `fetch` that reproduces the CSRF + credentials behaviour.
- **Query keys in use:** `['cluster','summary'|'nodes'|'activity',…]`, `['hosts']`, `['apps',{host,q}]`, `['apps',id]`, `['vms',{}]`, `['vms',id]`, `['catalog',…]`, `['jobs',{status}]`, `['jobs',id]`, `['jobs',id,'events']`, `['metrics',target,metric,hours]`, `['entitlements']`, `['me']`, `['notifications','channels']`. Phase 6 adds `['storage']`, `['storage',hostId,name,…]`, `['network','bridges']`, `['network','throughput']`, `['backups']`, `['vms',id,'snapshots']`.
- **`src/api/live.ts`** is the SSE→cache binding: `applyMetrics(qc,d)`, `applyResource(qc,d)`, `applyJob(qc,d,toast?)`. `applyResource` handles `d.type` of `'host'|'app'|'vm'` only and its `else` branch misroutes anything unknown into `['vms']`; `applyJob` only invalidates resource caches for `target_type` of `app`/`vm`. **Both must be extended for the new `storage`/`backup`/`network` types (Task 12).**
- **`src/api/jobs.ts::useLifecycle`** is the model for every job-firing mutation, including its documented trap: **do not invalidate the resource key on success**, the poll cache would stomp the optimistic `pending` state and re-arm the button while the job is still queued. It invalidates only `['jobs']` and `['cluster','activity']` in `onSettled`.
- **Job progress UI already exists** and needs no new machinery: `LiveProvider` toasts terminal jobs, `Topbar` badges the running count, `ActivityDrawer` (search-param driven, `?drawer=activity&job=N`, legal on every page) lists jobs with progress bars and expands `<JobLog jobId>`, and `InstallDialog` demonstrates the inline pattern; fire mutation → `setJobId(r.job.id)` → swap the dialog body for `<JobLog jobId={jobId}/>` + Close. **Every Phase 6 dialog that fires a job uses that inline pattern.**
- **Components available:** `Button` (`variant: 'primary'|'ghost'|'danger'|'go'`, small = `className="px-2 py-1 text-[11px]"`), `EmptyState({title,note})`, `KVGrid({items: [string, ReactNode][]})`, `StatusPill({status})`, `UsageBar({pct, gradient?})` + `CPU_GRADIENT`/`RAM_GRADIENT`/`STORAGE_GRADIENT`/`DANGER_GRADIENT`, `Ring`, `Sparkline({ts, values, color, width=300, height=52})`, `TerminalPanel({lines, height?})`, `JobLog({jobId})`, `LifecycleActions`, `ConfirmSelfDialog({phrase, detail, onConfirm, onCancel})`, `LockVeil({locked, title, subtitle, children})`, `useEntitlements()` (`{...q, tier, grace, has(key)}`), `lib/format.ts::fmtBytes/fmtUptime/fmtPct/fmtBps` (`fmtBps` was written for the Network page and is currently used only in `cluster.tsx`). Shared input class: `inputCls` exported from `components/LoginForm.tsx`. Toasts: `import { toast } from 'sonner'`. Destructive-but-not-self confirm precedent is native `window.confirm` (`routes/settings.tsx`).
- **Dialog markup precedent** (no primitive exists), from `ConfirmSelfDialog`:
  ```tsx
  <div role="dialog" aria-label="…" className="fixed inset-0 z-30 grid place-items-center bg-[rgba(11,15,22,.72)] backdrop-blur-[3px]">
    <div className="w-[420px] max-w-[92vw] rounded-card border border-line bg-panel p-5">
  ```
  and from `InstallDialog`: `<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"><div className="w-[520px] rounded-card border border-line bg-panel p-5">`.
- **Multi-step wizard precedent:** `src/routes/onboarding.tsx::Wizard`, a single function with `const [step, setStep] = useState(0)`, a `STEPS` const rendering chips, and `{step === N && (…)}` blocks. Not a reusable component; the VM create wizard mirrors it inline.
- **Tests:** vitest + jsdom + testing-library, all flat in `src/tests/<feature>.test.tsx`, **no MSW**, every test does `vi.mock('../api/client', () => ({ api: vi.fn((path: string) => …), ApiError: class extends Error {} }))` and mocks `@tanstack/react-router`'s `Link`/`useNavigate`/`useSearch`. Tests import the **page component**, never the route object. Harness is a fresh `new QueryClient({ defaultOptions: { queries: { retry: false } } })` in a `QueryClientProvider`. Commands: `cd frontend && npx vitest run`, `npm run build` (`tsc -b && vite build`), `npm run lint` (oxlint). Phase 5 left it at **71 passed, 20 files**.
- **doc 06 §(a) rows 43-48** specify these exact page layouts and are normative; `proxploy-prototype.html` at repo root is the visual source of truth. Quote those layouts, do not reinvent them.

---

## File Structure

**Backend, new files:**
- `proxploy/services/hostclient.py`: `client_for_host(app, db, host) -> ProxmoxClient`, the single decrypt-then-construct helper (Task 1), replacing the duplicated bodies in `api/consoles.py` and `services/lifecycle.py`
- `proxploy/services/pvetask.py`: `await_task(ctx, client, node, upid, *, timeout_s, start_pct, end_pct) -> dict`, the shared UPID poll-and-drain loop every mutating job uses (Task 2)
- `proxploy/services/netconfig.py`: `parse_net(value) -> dict`, `build_net(parts) -> str`, the `netN=` string round-tripper that preserves `model=`/`macaddr=` (Task 6)
- `proxploy/services/storagejobs.py`: `storage.upload`, `storage.delete_volume` handlers (Task 4)
- `proxploy/services/backupjobs.py`: `backup.sync`, `backup.run`, `backup.restore`, `backup.delete`, `backup.prune` handlers (Tasks 8-9)
- `proxploy/services/guestjobs.py`: `vm.snapshot_create`, `vm.snapshot_rollback`, `vm.snapshot_delete`, `vm.create`, `vm.clone`, `vm.delete`, `network.apply` handlers (Tasks 7, 10-11)
- `proxploy/api/storage.py`: the `/storage` router (Tasks 3-5)
- `proxploy/api/network.py`: the `/network` router (Tasks 6-7)
- `proxploy/api/backups.py`: the `/backups` router (Tasks 8-9)
- Backend tests: `tests/test_proxmox_infra_reads.py`, `tests/test_pvetask.py`, `tests/test_storage_api.py`, `tests/test_storage_content.py`, `tests/test_storage_manage.py`, `tests/test_network_api.py`, `tests/test_netconfig.py`, `tests/test_network_hostconfig.py`, `tests/test_backups_sync.py`, `tests/test_backups_api.py`, `tests/test_snapshots_api.py`, `tests/test_vm_create_clone.py`

**Backend, modified files:**
- `proxploy/services/proxmox.py`: ~25 new methods across Tasks 1, 4, 5, 6, 7, 9, 10, 11 (each task adds the ones it consumes)
- `proxploy/services/lifecycle.py`: refactored onto `await_task` + `client_for_host` (Tasks 1-2); no behaviour change, existing tests are the regression proof
- `proxploy/api/consoles.py`: `_proxmox_client_for_host` deleted, call sites moved to `client_for_host` (Task 1)
- `proxploy/pollers/__init__.py`: `snap_storage` keeps four more fields `/cluster/resources` already returns (Task 3)
- `proxploy/api/vms.py`: snapshot, clone, delete, create and network routes added **above** the `/{vm_id}/{action}` wildcard (Tasks 6, 10, 11)
- `proxploy/api/apps.py`: guest-network routes added above the `/{app_id}/{action}` wildcard (Task 6)
- `proxploy/api/__init__.py`: register `storage`, `network`, `backups` routers
- `proxploy/main.py`: import `storagejobs`, `backupjobs`, `guestjobs` in the lifespan `# noqa: F401` block
- `proxploy/config.py`: `storage_upload_max_bytes: int`, `backup_sync_stale_s: float`, `pve_task_timeout_s: float`
- `tests/fakes/pve.py`: storage/network/snapshot/config/nextid/vzdump/clone/create leaves (Tasks 1, 4-11)

**Frontend, new files:**
- `src/api/storage.ts`, `src/api/network.ts`, `src/api/backups.ts`, `src/api/snapshots.ts`
- `src/routes/storage.tsx`, `src/routes/network.tsx`, `src/routes/backups.tsx`
- `src/components/StorageCard.tsx`, `src/components/UploadDialog.tsx`, `src/components/StorageForm.tsx`, `src/components/NicForm.tsx`, `src/components/BridgeForm.tsx`, `src/components/RestoreDialog.tsx`, `src/components/SnapshotPanel.tsx`, `src/components/VmCreateWizard.tsx`, `src/components/CloneDialog.tsx`
- Frontend tests: `src/tests/storage.test.tsx`, `src/tests/storage-mutations.test.tsx`, `src/tests/network.test.tsx`, `src/tests/backups.test.tsx`, `src/tests/snapshots.test.tsx`, `src/tests/vmcreate.test.tsx`

**Frontend, modified files:**
- `src/router.tsx`: delete the `page()` helper and the three placeholder consts; import the three real route objects
- `src/routes/vms.tsx`: delete `phaseTab`, real `vmSnapshotsRoute`, "New VM" button, clone row action
- `src/api/live.ts`: `applyResource`/`applyJob` learn the `storage`/`backup`/`network` types
- `src/routes/placeholder.tsx`: **deleted** (dead once all three pages land)

---

## Task list and interface contract

Every task's `Interfaces` block below is **binding**. A later task's implementer
sees only their own task, so these names and types are the contract between
them. Do not rename anything here.

### Task 1: `client_for_host` extraction + `ProxmoxClient` infra reads + FakePVE read leaves
Produces:
- `proxploy/services/hostclient.py::client_for_host(app, db, host: Host) -> ProxmoxClient`
- `ProxmoxClient.storages(node: str) -> list[dict]`
- `ProxmoxClient.storage_status(node: str, storage: str) -> dict`
- `ProxmoxClient.storage_content(node: str, storage: str, content: str | None = None) -> list[dict]`
- `ProxmoxClient.cluster_storage() -> list[dict]`
- `ProxmoxClient.node_networks(node: str, iface_type: str | None = None) -> list[dict]`
- `ProxmoxClient.guest_config(kind: str, node: str, vmid: int) -> dict`
- `ProxmoxClient.snapshots(kind: str, node: str, vmid: int) -> list[dict]`
- `ProxmoxClient.cluster_nextid() -> int`
- FakePVE: `storages_by_node`, `storage_status_response`, `content_by_storage`, `cluster_storage_rows`, `networks_by_node`, `guest_configs`, `snapshots_by_guest`, `nextid` attributes + the namespace classes serving them

### Task 2: shared `await_task` + `enqueue_and_audit`, `lifecycle.py` refactored onto them
Produces:
- `proxploy/services/pvetask.py::await_task(ctx: JobContext, client: ProxmoxClient, node: str, upid: str, *, timeout_s: float = 300.0, start_pct: int = 10, end_pct: int = 100) -> dict`: logs the UPID, polls `task_status`, drains `task_log` into `ctx.log`, raises `JobFailed` on non-`OK` `exitstatus` or timeout, returns the final status dict
- `proxploy/api/jobs.py::enqueue_and_audit(request, db, user, *, kind: str, target_type: str | None, target_id: int | None, params: dict, action: str | None = None) -> dict`: enqueues, writes the audit row with `job_id`, returns `{"job": job_out(job)}`

### Task 3: storage reads: poller enrichment + `GET /storage`, `/storage/{host_id}/{name}`, `/storage/{host_id}/{name}/content`
Produces: `api/storage.py` router; `HostSnapshot.storage` dicts gain `type`, `content`, `shared`, `status`; response shapes
`GET /storage -> [{host_id, host_name, node, storage, type, content: list[str], shared: bool, status: str, used_bytes, total_bytes, used_pct}]`,
`GET /storage/{host_id}/{name} -> {…same…, avail_bytes, nodes: [str]}`,
`GET /storage/{host_id}/{name}/content?node=&content= -> [{volid, format, size, used, vmid, ctime, content, notes, verification}]`

### Task 4: storage content mutations: upload + delete volume
Produces: `ProxmoxClient.storage_upload(node, storage, content, filename, path) -> str` (UPID), `ProxmoxClient.storage_delete_volume(node, storage, volid) -> str | None`; job kinds `storage.upload`, `storage.delete_volume`; routes `POST /storage/{host_id}/{name}/content` (multipart), `DELETE /storage/{host_id}/{name}/content/{volid:path}`

### Task 5: storage manage: attach / edit / detach
Produces: `ProxmoxClient.storage_create(config: dict) -> None`, `storage_update(storage: str, config: dict) -> None`, `storage_remove(storage: str) -> None`; routes `POST /storage`, `PATCH /storage/{host_id}/{name}`, `DELETE /storage/{host_id}/{name}`

### Task 6: network reads + guest NIC read/edit
Produces: `services/netconfig.py::parse_net(value: str) -> dict`, `build_net(parts: dict) -> str`; `ProxmoxClient.guest_config_update(kind, node, vmid, config: dict) -> str | None`; `api/network.py` with `GET /network/bridges?host=`, `GET /network/throughput`; `GET /{apps|vms}/{id}/network`, `PUT /{apps|vms}/{id}/network/{iface}`

### Task 7: host network staging + apply/revert
Produces: `ProxmoxClient.network_create(node, config) -> None`, `network_update(node, iface, config) -> None`, `network_delete(node, iface) -> None`, `network_apply(node) -> str` (UPID), `network_revert(node) -> None`; job kind `network.apply`; routes `POST /network/bridges`, `PUT /network/bridges/{host_id}/{node}/{iface}`, `DELETE /network/bridges/{host_id}/{node}/{iface}`, `POST /network/{host_id}/{node}/apply`, `POST /network/{host_id}/{node}/revert`

### Task 8: backups sync + list + stats
Produces: `services/backupjobs.py` with job kind `backup.sync`; `GET /api/v1/backups -> {backups: [...], stats: {total, total_bytes, ok_count, failed_count, success_rate_30d, datastores: [...]}, synced_at, stale}`

### Task 9: backups run / restore / delete / prune preview
Produces: `ProxmoxClient.vzdump(node, params) -> str`, `restore_guest(kind, node, vmid, params) -> str`, `prune_preview(node, storage, params) -> list[dict]`, `prune_backups(node, storage, params) -> str`; job kinds `backup.run`, `backup.restore`, `backup.delete`, `backup.prune`; routes `POST /backups/run`, `POST /backups/{id}/restore`, `DELETE /backups/{id}`, `GET /backups/prune-preview`, `POST /backups/prune`

### Task 10: VM snapshots API
Produces: `ProxmoxClient.snapshot_create(kind, node, vmid, name, description=None, vmstate=False) -> str`, `snapshot_rollback(kind, node, vmid, name) -> str`, `snapshot_delete(kind, node, vmid, name) -> str`; job kinds `vm.snapshot_create`, `vm.snapshot_rollback`, `vm.snapshot_delete`; routes `GET|POST /vms/{vm_id}/snapshots`, `POST /vms/{vm_id}/snapshots/{name}/rollback`, `DELETE /vms/{vm_id}/snapshots/{name}`, all registered above the `/{vm_id}/{action}` wildcard

### Task 11: VM create / clone / delete API
Produces: `ProxmoxClient.vm_create(node, params) -> str`, `vm_clone(node, vmid, params) -> str`, `guest_delete(kind, node, vmid) -> str`; job kinds `vm.create`, `vm.clone`, `vm.delete`; routes `POST /vms`, `POST /vms/{vm_id}/clone`, `DELETE /vms/{vm_id}`

### Cross-task couplings: read this before starting any task out of order

These are the seams where two tasks touch the same lines. Each was found by
drafting the tasks against each other, and each is the kind of thing a
single-task implementer cannot see.

1. **`tests/fakes/pve.py` is edited by eight tasks.** Task 1 creates the read-side namespaces (`_StorageNS`, `_NetworkNS`, `_SnapshotNS`, `_ConfigLeaf`, root `.storage`, `.cluster.nextid`). Later tasks **replace** rather than duplicate: Task 4 makes the content leaf callable, Task 5 makes root `.storage` callable, Task 7 makes `_NetworkNS` callable, Task 9 adds `_GuestFactory.post()` (recording into `fake.creates`) and wires `prunebackups`, Task 10 makes `_SnapshotNS` callable and adds `nextid_calls`, Task 11 **reuses** Task 9's `_GuestFactory.post()` and only adds a `create_error` injection hook. Each replacement block in the tasks below is self-contained and preserves the earlier `.get()` contract so earlier tasks' tests keep passing, re-run the prior task's test file after any such replacement, which each task's steps tell you to do.
2. **`api/vms.py`'s role singletons get hoisted once.** Tasks 6, 10 and 11 all add routes above the `/{vm_id}/{action}` wildcard. `_require_operator` currently sits at vms.py:54, *below* where those routes must go. **Task 6 hoists `_require_operator` to the top of the file and adds `_require_viewer` / `_require_admin` beside it**; Tasks 10 and 11 use them and must not re-declare them.
3. **`services/guestjobs.py` is created by Task 7** (for `network.apply`) and appended to by Tasks 10 and 11. Task 7 also adds its `main.py` lifespan import; Tasks 10-11 must not add a second one.
4. **`client_for_host(app, db, host)` takes the app, not `app.state`.** Every call site passes `request.app` from a route or `ctx.backend.app` from a handler.
5. **`await_task` gained a keyword-only `poll_s`** beyond the contract signature, because `tests/test_lifecycle_jobs.py` monkeypatches `lifecycle.TASK_POLL_S` and a module constant in `pvetask` would silently break that patch. Purely additive; tasks that do not care omit it.
6. **`ConfirmSelfDialog` gains an optional `title` prop** in Task 14, defaulting to its current hard-coded heading so `LifecycleActions` and `src/tests/lifecycle.test.tsx` stay byte-identical.
7. **Task 16 must land before Task 17**: 16 removes the `phaseTab` helper from `routes/vms.tsx`, 17 rewrites `VmsPage` in the same file.
8. **Two Phase 6 endpoints ship deliberately unconsumed by this phase's UI**, both recorded rather than quietly dropped: `POST /backups/prune` (the *destructive* prune; the preview is wired, but keep-rules have nowhere to live until Phase 7's scheduler owns retention policy) and the `vmstate` snapshot option on non-qemu guests (LXC has no RAM state). Task 18's notes doc carries both forward.

### Task 12: frontend Storage page + `live.ts` extension
### Task 13: frontend storage mutations (upload + attach/edit/detach)
### Task 14: frontend Network page
### Task 15: frontend Backups page
### Task 16: frontend VM snapshots tab
### Task 17: frontend VM create wizard + clone dialog
### Task 18: DoD verification, doc-05 amendment, notes doc, buildlog

---

## Proxmox API call reference (verified paths, for `services/proxmox.py` only)

| Method | proxmoxer expression | Returns |
|---|---|---|
| `storages` | `.nodes(node).storage.get()` | list of `{storage, type, content, active, enabled, shared, used, avail, total}` |
| `storage_status` | `.nodes(node).storage(storage).status.get()` | `{type, content, active, enabled, shared, used, avail, total}` |
| `storage_content` | `.nodes(node).storage(storage).content.get(content=…)` | list of `{volid, format, size, used, vmid, ctime, content, notes, verification}` |
| `cluster_storage` | `.storage.get()` | cluster-level configured storages |
| `storage_create` | `.storage.post(storage=…, type=…, **cfg)` | none |
| `storage_update` | `.storage(name).put(**cfg)` | none |
| `storage_remove` | `.storage(name).delete()` | none |
| `storage_upload` | `.nodes(node).storage(storage).upload.post(content=…, filename=<open file object>)` | UPID |
| `storage_delete_volume` | `.nodes(node).storage(storage).content(volid).delete()` | UPID or `None` |
| `node_networks` | `.nodes(node).network.get()` / `.get(type=…)` | list of `{iface, type, method, address, netmask, cidr, gateway, bridge_ports, bridge_vlan_aware, vlan-id, vlan-raw-device, active, autostart, comments}` |
| `network_create` | `.nodes(node).network.post(iface=…, type=…, **cfg)` | none (stages into `/etc/network/interfaces.new`) |
| `network_update` | `.nodes(node).network(iface).put(**cfg)` | none (stages) |
| `network_delete` | `.nodes(node).network(iface).delete()` | none (stages) |
| `network_apply` | `.nodes(node).network.put()` | UPID (reload) |
| `network_revert` | `.nodes(node).network.delete()` | none (discards staged) |
| `guest_config` | `.nodes(node).lxc(vmid).config.get()` / `.qemu(vmid).config.get()` | full config dict incl. `net0`, `net1`, … |
| `guest_config_update` | `.nodes(node).<kind>(vmid).config.put(**cfg)` | UPID (running qemu) or `None` |
| `snapshots` | `.nodes(node).<kind>(vmid).snapshot.get()` | list of `{name, description, snaptime, vmstate, parent}` (includes the synthetic `current`) |
| `snapshot_create` | `.nodes(node).<kind>(vmid).snapshot.post(snapname=…, description=…, vmstate=…)` | UPID |
| `snapshot_rollback` | `.nodes(node).<kind>(vmid).snapshot(name).rollback.post()` | UPID |
| `snapshot_delete` | `.nodes(node).<kind>(vmid).snapshot(name).delete()` | UPID |
| `vzdump` | `.nodes(node).vzdump.post(vmid=…, storage=…, mode=…, compress=…)` | UPID |
| `restore_guest` (CT) | `.nodes(node).lxc.post(vmid=newid, ostemplate=volid, restore=1, storage=…, force=…)` | UPID |
| `restore_guest` (VM) | `.nodes(node).qemu.post(vmid=newid, archive=volid, storage=…, force=…)` | UPID |
| `vm_create` | `.nodes(node).qemu.post(vmid=…, name=…, cores=…, memory=…, ostype=…, net0=…, scsi0=…, ide2=…, scsihw=…, boot=…)` | UPID |
| `vm_clone` | `.nodes(node).qemu(vmid).clone.post(newid=…, name=…, full=…, target=…, storage=…)` | UPID |
| `guest_delete` | `.nodes(node).<kind>(vmid).delete()` | UPID |
| `prune_preview` | `.nodes(node).storage(storage).prunebackups.get(**{"prune-backups": "keep-last=3,keep-daily=7", "type": …, "vmid": …})` | list of `{volid, type, vmid, ctime, mark: "keep"\|"remove"\|"protected"}` |
| `prune_backups` | `.nodes(node).storage(storage).prunebackups.delete(**{"prune-backups": …})` | UPID |
| `cluster_nextid` | `.cluster.nextid.get()` | `str` (cast to `int`) |

**Hyphenated PVE params** (`prune-backups`, `vlan-id`, `vlan-raw-device`,
`bridge_ports` is underscore but `vlan-id` is not) cannot be Python kwargs, 
build a dict and unpack: `.get(**{"prune-backups": spec})`. Every method that
needs one does this.

**Restore is a create-with-archive**, not its own endpoint: a CT restore POSTs
to `/nodes/{node}/lxc` with `ostemplate=<backup volid>` + `restore=1`, a VM
restore POSTs to `/nodes/{node}/qemu` with `archive=<backup volid>`. Restoring
*in place* reuses the existing vmid and needs `force=1` with the guest stopped;
restoring *as new* takes a fresh vmid from `cluster_nextid()`.

---

## Task 1: `client_for_host` extraction + `ProxmoxClient` infra reads + FakePVE read leaves

**Files:**
- Create: `backend/proxploy/services/hostclient.py`
- Modify: `backend/proxploy/services/proxmox.py`, `backend/proxploy/api/consoles.py`, `backend/proxploy/services/lifecycle.py`, `backend/tests/fakes/pve.py`
- Test: `backend/tests/test_proxmox_infra_reads.py`

**Interfaces:**
- Consumes: `ProxmoxClient.__init__(address, token_id, token_secret, verify_tls=True, tls_fingerprint=None, factory=None)` and `ProxmoxClient._wrap(prefix, e) -> ProxmoxError` (existing, `proxploy/services/proxmox.py:168`/`:180`); `Host`, `HostCredential` (existing, `proxploy/models/__init__.py`); `app.state.secretstore.decrypt(blob)` and `app.state.proxmox_factory` (existing, set in `main.py`'s lifespan / `create_app`).
- Produces:
  - `proxploy/services/hostclient.py::client_for_host(app, db, host: Host) -> ProxmoxClient`: raises `ProxmoxError` when the host has no `api_token` credential
  - `ProxmoxClient.storages(node: str) -> list[dict]`
  - `ProxmoxClient.storage_status(node: str, storage: str) -> dict`
  - `ProxmoxClient.storage_content(node: str, storage: str, content: str | None = None) -> list[dict]`
  - `ProxmoxClient.cluster_storage() -> list[dict]`
  - `ProxmoxClient.node_networks(node: str, iface_type: str | None = None) -> list[dict]`
  - `ProxmoxClient.guest_config(kind: str, node: str, vmid: int) -> dict`
  - `ProxmoxClient.snapshots(kind: str, node: str, vmid: int) -> list[dict]`
  - `ProxmoxClient.cluster_nextid() -> int`
  - FakePVE attributes `storages_by_node`, `storage_status_response`, `content_by_storage`, `cluster_storage_rows`, `networks_by_node`, `guest_configs`, `snapshots_by_guest`, `nextid`, `last_storage_status_call`, `last_content_call` + the namespace classes serving them
- Removes: `api/consoles.py::_proxmox_client_for_host` (deleted, not re-homed), the inline decrypt-then-construct block inside `services/lifecycle.py::_resolve`

- [ ] **Step 1: Write the failing tests for the eight reads and the shared client helper**

```python
# backend/tests/test_proxmox_infra_reads.py
"""Phase 6 Task 1: the infra-read half of ProxmoxClient, plus the one
decrypt-then-construct helper both routers and job handlers now share."""
import json

import pytest
from fastapi.testclient import TestClient

from proxploy.models import Host, HostCredential
from proxploy.services.hostclient import client_for_host
from proxploy.services.proxmox import ProxmoxClient, ProxmoxError
from tests.fakes.pve import FakePVE, make_fake_factory


def _client(fake):
    return ProxmoxClient("https://10.0.0.9:8006", "proxploy@pve!infra",
                         "sekret", verify_tls=False,
                         factory=make_fake_factory(fake))


def _seed_host_with_token(app, secret="s3cret"):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.7:8006",
                    node_name="pve1", status="connected")
        db.add(host)
        db.commit()
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!infra", "token_secret": secret}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token",
                              encrypted_blob=blob, key_version=ver))
        db.commit()
        return host.id


# --- storage reads --------------------------------------------------------

def test_storages_lists_the_nodes_datastores():
    fake = FakePVE()
    fake.storages_by_node = {"pve1": [
        {"storage": "local", "type": "dir", "content": "iso,vztmpl",
         "active": 1, "shared": 0, "used": 5, "avail": 95, "total": 100},
        {"storage": "local-lvm", "type": "lvmthin", "content": "images,rootdir",
         "active": 1, "shared": 0, "used": 20, "avail": 80, "total": 100},
    ]}
    rows = _client(fake).storages("pve1")
    assert [r["storage"] for r in rows] == ["local", "local-lvm"]


def test_storage_status_returns_the_per_datastore_detail():
    fake = FakePVE()
    fake.storage_status_response = {"type": "lvmthin", "content": "images,rootdir",
                                    "active": 1, "enabled": 1, "shared": 0,
                                    "used": 20, "avail": 80, "total": 100}
    out = _client(fake).storage_status("pve1", "local-lvm")
    assert out == fake.storage_status_response
    assert fake.last_storage_status_call == ("pve1", "local-lvm")


def test_storage_content_passes_the_content_filter_through():
    fake = FakePVE()
    fake.content_by_storage = {"local": [
        {"volid": "local:iso/debian-12.iso", "format": "iso", "size": 700,
         "used": 700, "vmid": None, "ctime": 1, "content": "iso",
         "notes": None, "verification": None},
    ]}
    rows = _client(fake).storage_content("pve1", "local", content="iso")
    assert rows[0]["volid"] == "local:iso/debian-12.iso"
    assert fake.last_content_call == ("pve1", "local", "iso")


def test_storage_content_without_a_filter_sends_no_content_kwarg():
    """PVE treats `content=` as a filter; sending content=None would filter on
    the literal string "None" rather than listing everything."""
    fake = FakePVE()
    fake.content_by_storage = {"local": [{"volid": "local:iso/x.iso"}]}
    assert _client(fake).storage_content("pve1", "local") == [{"volid": "local:iso/x.iso"}]
    assert fake.last_content_call == ("pve1", "local", None)


def test_cluster_storage_reads_the_cluster_level_config():
    fake = FakePVE()
    fake.cluster_storage_rows = [{"storage": "nfs-backup", "type": "nfs",
                                  "content": "backup", "shared": 1}]
    assert _client(fake).cluster_storage() == fake.cluster_storage_rows


# --- network reads --------------------------------------------------------

def test_node_networks_lists_every_interface():
    fake = FakePVE()
    fake.networks_by_node = {"pve1": [
        {"iface": "vmbr0", "type": "bridge", "method": "static",
         "cidr": "192.168.1.10/24", "gateway": "192.168.1.1",
         "bridge_ports": "eno1", "active": 1, "autostart": 1},
        {"iface": "eno1", "type": "eth", "method": "manual", "active": 1},
    ]}
    assert [r["iface"] for r in _client(fake).node_networks("pve1")] == ["vmbr0", "eno1"]


def test_node_networks_filters_by_type():
    fake = FakePVE()
    fake.networks_by_node = {"pve1": [
        {"iface": "vmbr0", "type": "bridge"},
        {"iface": "eno1", "type": "eth"},
    ]}
    rows = _client(fake).node_networks("pve1", iface_type="bridge")
    assert [r["iface"] for r in rows] == ["vmbr0"]


# --- guest config + snapshots + nextid ------------------------------------

def test_guest_config_reads_both_lxc_and_qemu():
    fake = FakePVE()
    fake.guest_configs = {
        ("lxc", 150): {"hostname": "immich", "net0": "name=eth0,bridge=vmbr0,ip=dhcp"},
        ("qemu", 201): {"name": "win11", "net0": "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0"},
    }
    c = _client(fake)
    assert c.guest_config("lxc", "pve1", 150)["hostname"] == "immich"
    assert c.guest_config("qemu", "pve1", 201)["name"] == "win11"


def test_snapshots_lists_the_guests_snapshots():
    fake = FakePVE()
    fake.snapshots_by_guest = {("qemu", 201): [
        {"name": "pre-update", "description": "before 24.04", "snaptime": 1,
         "vmstate": 0, "parent": None},
        {"name": "current", "description": "You are here!"},
    ]}
    names = [s["name"] for s in _client(fake).snapshots("qemu", "pve1", 201)]
    assert names == ["pre-update", "current"]


def test_cluster_nextid_returns_an_int():
    """PVE answers /cluster/nextid with a JSON string; every caller wants an int."""
    fake = FakePVE()
    fake.nextid = "205"
    assert _client(fake).cluster_nextid() == 205


def test_a_failing_infra_read_wraps_and_redacts_the_secret():
    fake = FakePVE(fail=True)
    with pytest.raises(ProxmoxError) as exc:
        _client(fake).storages("pve1")
    assert "sekret" not in str(exc.value)
    assert "pve1" in str(exc.value)


# --- the shared decrypt-then-construct helper -----------------------------

def test_client_for_host_builds_a_client_from_the_stored_token(tmp_path):
    from tests.support import make_app

    fake = FakePVE(version={"version": "8.4.1", "release": "8.4"})
    app = make_app(tmp_path, fake=fake)
    with TestClient(app):
        host_id = _seed_host_with_token(app)
        with app.state.sessionmaker() as db:
            client = client_for_host(app, db, db.get(Host, host_id))
            assert client.version()["release"] == "8.4"
    assert fake.kwargs["user"] == "proxploy@pve"
    assert fake.kwargs["token_name"] == "infra"
    assert fake.kwargs["token_value"] == "s3cret"


def test_client_for_host_raises_when_the_host_has_no_api_token(tmp_path):
    from tests.support import make_app

    app = make_app(tmp_path, fake=FakePVE())
    with TestClient(app):
        with app.state.sessionmaker() as db:
            host = Host(name="bare", address="https://10.0.0.8:8006", node_name="pve1")
            db.add(host)
            db.commit()
            with pytest.raises(ProxmoxError, match="no API token credential"):
                client_for_host(app, db, host)


def test_consoles_no_longer_carries_its_own_copy_of_the_helper():
    """Root-cause DRY, not a third copy: the duplicate in api/consoles.py is
    deleted outright, so a future reader cannot pick the stale one."""
    from proxploy.api import consoles

    assert not hasattr(consoles, "_proxmox_client_for_host")
    assert consoles.client_for_host is client_for_host
```

- [ ] **Step 2: Run to verify the failure**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_proxmox_infra_reads.py -q`
Expected: FAIL at collection, `ModuleNotFoundError: No module named 'proxploy.services.hostclient'` (the import at the top of the test file). Nothing runs yet.

- [ ] **Step 3: Create `proxploy/services/hostclient.py`**

```python
# backend/proxploy/services/hostclient.py
"""The one decrypt-then-construct helper: a Host row -> a ProxmoxClient.

api/consoles.py and services/lifecycle.py each carried their own copy of these
five lines; consoles.py's copy even carried a comment naming a 4th call site as
the tip-over point for extracting it. Phase 6 adds three routers and twelve job
handlers that all need it, so it is one function now and the copies are gone.

It raises ProxmoxError, never HTTPException, never JobFailed; because both
kinds of caller live here: a route turns it into a 409, a job handler into a
JobFailed. That translation is one line at each call site and keeps this module
free of both FastAPI and the job engine.

Not used by api/hosts.py::test_host, deliberately: that route also needs the
HostCredential row itself (to stamp `last_used_at`), which this helper does not
return, so folding it in would mean widening the return type for one caller.
"""
from __future__ import annotations

import json as jsonlib

from proxploy.models import Host, HostCredential
from proxploy.services.proxmox import ProxmoxClient, ProxmoxError


def client_for_host(app, db, host: Host) -> ProxmoxClient:
    cred = (db.query(HostCredential)
            .filter_by(host_id=host.id, kind="api_token").one_or_none())
    if cred is None:
        raise ProxmoxError(f"host {host.name} has no API token credential")
    tok = jsonlib.loads(app.state.secretstore.decrypt(cred.encrypted_blob))
    return ProxmoxClient(host.address, tok["token_id"], tok["token_secret"],
                         verify_tls=host.verify_tls,
                         tls_fingerprint=host.tls_fingerprint,
                         factory=app.state.proxmox_factory)
```

- [ ] **Step 4: Add the FakePVE read leaves**

In `backend/tests/fakes/pve.py`, add these classes after `_KwLeaf` (they follow
the file's existing one-small-class-per-leaf style, no lambdas, each leaf
checks `owner.fail` itself):

```python
class _AttrLeaf:
    """A .get() that reads a FakePVE attribute lazily, so a test can assign the
    attribute after construction (unlike _Leaf, which captures its value)."""

    def __init__(self, owner, attr, cast=None):
        self._owner, self._attr, self._cast = owner, attr, cast

    def get(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        value = getattr(self._owner, self._attr)
        return self._cast(value) if self._cast else value


class _StorageStatusLeaf:
    def __init__(self, owner, node, storage):
        self._owner, self._node, self._storage = owner, node, storage

    def get(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.last_storage_status_call = (self._node, self._storage)
        return self._owner.storage_status_response


class _StorageContentLeaf:
    def __init__(self, owner, node, storage):
        self._owner, self._node, self._storage = owner, node, storage

    def get(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.last_content_call = (self._node, self._storage,
                                         kwargs.get("content"))
        return self._owner.content_by_storage.get(self._storage, [])


class _StorageNS:
    """nodes(n).storage(name), the per-datastore subtree."""

    def __init__(self, owner, node, storage):
        self.status = _StorageStatusLeaf(owner, node, storage)
        self.content = _StorageContentLeaf(owner, node, storage)


class _NodeStorageNS:
    """nodes(n).storage is BOTH gettable and callable, exactly like proxmoxer:
    `.storage.get()` lists every datastore on the node, `.storage(name)`
    descends into one. ProxmoxClient.storages and .storage_status use one shape
    each, so a leaf that only did .get() would break the second."""

    def __init__(self, owner, node):
        self._owner, self._node = owner, node

    def get(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        return self._owner.storages_by_node.get(self._node, [])

    def __call__(self, storage):
        return _StorageNS(self._owner, self._node, storage)


class _NetIfaceNS:
    """nodes(n).network(iface), the staging subtree Task 7 hangs put/delete
    off. Present now only so `.network` has proxmoxer's full dual shape."""

    def __init__(self, owner, node, iface):
        self._owner, self._node, self._iface = owner, node, iface


class _NodeNetworkNS:
    """Same dual shape as _NodeStorageNS: `.get()` lists, `(iface)` descends."""

    def __init__(self, owner, node):
        self._owner, self._node = owner, node

    def get(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        rows = self._owner.networks_by_node.get(self._node, [])
        want = kwargs.get("type")  # read out of kwargs, never a `type=` param
        return [r for r in rows if r.get("type") == want] if want else rows

    def __call__(self, iface):
        return _NetIfaceNS(self._owner, self._node, iface)


class _GuestConfigLeaf:
    def __init__(self, owner, kind, vmid):
        self._owner, self._kind, self._vmid = owner, kind, vmid

    def get(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        return self._owner.guest_configs.get((self._kind, self._vmid), {})


class _SnapshotLeaf:
    def __init__(self, owner, kind, vmid):
        self._owner, self._kind, self._vmid = owner, kind, vmid

    def get(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        return self._owner.snapshots_by_guest.get((self._kind, self._vmid), [])
```

Then wire them into the three existing namespaces. Replace `_ClusterNS`:

```python
class _ClusterNS:
    def __init__(self, owner, resources, fail):
        self.resources = _KwLeaf(resources, fail)
        self.nextid = _AttrLeaf(owner, "nextid", str)  # PVE returns a string
```

extend `_GuestNS.__init__` (keep the existing three lines, add two):

```python
class _GuestNS:
    def __init__(self, owner, kind, node, vmid):
        self.status = _GuestStatusNS(owner, kind, vmid)
        self.termproxy = _TermproxyLeaf(owner, kind, node, vmid)
        self.config = _GuestConfigLeaf(owner, kind, vmid)
        self.snapshot = _SnapshotLeaf(owner, kind, vmid)
        if kind == "qemu":
            self.vncproxy = _VncproxyLeaf(owner, node, vmid)
```

and extend `_NodeNS.__init__` (keep the existing five lines, add two):

```python
class _NodeNS:
    def __init__(self, owner, name):
        self.rrddata = _KwLeaf(owner.rrd_by_node.get(name, []),
                                owner.fail or owner.rrd_fail)
        self.tasks = _TaskFactory(owner)
        self.lxc = _GuestFactory(owner, "lxc", name)
        self.qemu = _GuestFactory(owner, "qemu", name)
        self.termproxy = _TermproxyLeaf(owner, None, name, None)
        self.storage = _NodeStorageNS(owner, name)
        self.network = _NodeNetworkNS(owner, name)
```

Finally, in `FakePVE.__init__`, add the Phase 6 attribute block **before** the
namespaces are constructed and change the `_ClusterNS` call to pass `self`
(everything else in `__init__` is unchanged; the constructor signature is NOT
touched, tests assign these attributes after construction):

```python
        # infra reads (Phase 6): set before the namespaces below, which read
        # them lazily so a test can reassign any of these post-construction
        self.storages_by_node: dict[str, list[dict]] = {}
        self.storage_status_response: dict = {}
        self.content_by_storage: dict[str, list[dict]] = {}
        self.cluster_storage_rows: list[dict] = []
        self.networks_by_node: dict[str, list[dict]] = {}
        self.guest_configs: dict[tuple[str, int], dict] = {}
        self.snapshots_by_guest: dict[tuple[str, int], list[dict]] = {}
        self.nextid = "100"
        self.last_storage_status_call = None
        self.last_content_call = None
        self.storage = _AttrLeaf(self, "cluster_storage_rows")  # root /storage
        self.cluster = _ClusterNS(self, resources or [], fail)
```

(the existing `self.cluster = _ClusterNS(resources or [], fail)` line is
replaced by the two-line pair above, root `.storage` is the cluster-level
storage config, distinct from `nodes(n).storage`.)

- [ ] **Step 5: Add the eight infra reads to `ProxmoxClient`**

In `backend/proxploy/services/proxmox.py`, append to `class ProxmoxClient`
after `vncproxy`:

```python
    # --- infra reads (Phase 6) ----------------------------------------------
    # All read-only, all on-demand: nothing here is called from the poll loop,
    # so doc 02 §3's O(nodes) budget is untouched.

    def storages(self, node: str) -> list[dict]:
        """GET /nodes/{node}/storage -> [{storage, type, content, active,
        enabled, shared, used, avail, total}]."""
        try:
            return self._connect().nodes(node).storage.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"storage list failed on {node}", e) from e

    def storage_status(self, node: str, storage: str) -> dict:
        """GET /nodes/{node}/storage/{storage}/status -> per-datastore detail."""
        try:
            return self._connect().nodes(node).storage(storage).status.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"storage status failed for {storage!r} on {node}", e) from e

    def storage_content(self, node: str, storage: str,
                        content: str | None = None) -> list[dict]:
        """GET /nodes/{node}/storage/{storage}/content -> volume listing.

        `content=` is a FILTER, so it is omitted rather than sent as None; 
        PVE would otherwise filter on the literal string and return nothing.
        """
        try:
            leaf = self._connect().nodes(node).storage(storage).content
            return leaf.get(content=content) if content else leaf.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"storage content failed for {storage!r} on {node}", e) from e

    def cluster_storage(self) -> list[dict]:
        """GET /storage, the cluster-level storage.cfg, not a node's view."""
        try:
            return self._connect().storage.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap("cluster storage config read failed", e) from e

    def node_networks(self, node: str, iface_type: str | None = None) -> list[dict]:
        """GET /nodes/{node}/network -> [{iface, type, method, cidr, gateway,
        bridge_ports, active, autostart, ...}]. `iface_type` is PVE's `type`
        filter (bridge/bond/eth/vlan), omitted when None for the same reason
        storage_content omits `content`."""
        try:
            net = self._connect().nodes(node).network
            return net.get(type=iface_type) if iface_type else net.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"network list failed on {node}", e) from e

    def guest_config(self, kind: str, node: str, vmid: int) -> dict:
        """GET /nodes/{node}/{lxc|qemu}/{vmid}/config, the full config dict,
        including every netN= line the network page round-trips."""
        try:
            return getattr(self._connect().nodes(node), kind)(vmid).config.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"config read failed for {kind}/{vmid} on {node}", e) from e

    def snapshots(self, kind: str, node: str, vmid: int) -> list[dict]:
        """GET /nodes/{node}/{lxc|qemu}/{vmid}/snapshot -> [{name, description,
        snaptime, vmstate, parent}]. Includes PVE's synthetic `current` row, 
        callers decide whether to show it, this layer does not filter."""
        try:
            return getattr(self._connect().nodes(node), kind)(vmid).snapshot.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"snapshot list failed for {kind}/{vmid} on {node}", e) from e

    def cluster_nextid(self) -> int:
        """GET /cluster/nextid, PVE answers with a JSON string; cast once here
        so no caller has to remember to."""
        try:
            return int(self._connect().cluster.nextid.get())
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap("cluster nextid read failed", e) from e
```

- [ ] **Step 6: Delete `_proxmox_client_for_host` and move `api/consoles.py` onto the shared helper**

In `backend/proxploy/api/consoles.py`, delete the whole
`_proxmox_client_for_host` function (lines 26-37) and change the imports:

```python
from proxploy.api.deps import get_db, require_entitlement, require_role
from proxploy.models import App, Host, User, Vm
from proxploy.services import ptybridge
from proxploy.services.audit import write_audit
from proxploy.services.consoleproxy import ConsoleProxyError, bridge_binary, connect_upstream_vnc
from proxploy.services.consoletickets import mint_ticket, redeem_ticket
from proxploy.services.hostclient import client_for_host
from proxploy.services.ptybridge import PtyBridgeError, bridge_pty
from proxploy.services.proxmox import ProxmoxError
```

(`HostCredential` and `ProxmoxClient` are no longer referenced in this file;
`import json as jsonlib` stays, the VNC/PTY exit frame still uses it.)

Then replace each of the three call sites. In `app_console_ticket`:

```python
    try:
        client = client_for_host(request.app, db, host)
    except ProxmoxError as e:
        raise HTTPException(409, str(e)) from e
```

in `node_shell_ticket` (immediately after the `node_shell_enabled` check):

```python
    try:
        client = client_for_host(request.app, db, host)
    except ProxmoxError as e:
        raise HTTPException(409, str(e)) from e
```

and in `vm_console_ticket`:

```python
    try:
        client = client_for_host(request.app, db, host)
    except ProxmoxError as e:
        raise HTTPException(409, str(e)) from e
```

The 409 and its exact message are unchanged from the deleted helper, only the
raise site moved out of the shared code, because a job handler needs the same
lookup and must not raise HTTPException.

- [ ] **Step 7: Move `services/lifecycle.py::_resolve` onto the shared helper**

In `backend/proxploy/services/lifecycle.py`, change the imports:

```python
from proxploy.jobs import HANDLERS, JobContext, JobFailed
from proxploy.models import App, Host, Vm
from proxploy.services.hostclient import client_for_host
from proxploy.services.proxmox import ProxmoxError
```

(`import json as jsonlib`, `HostCredential` and `ProxmoxClient` all become
unused here, delete them.) Then replace the body of `_resolve`:

```python
def _resolve(app, target_type: str, target_id: int):
    """Blocking: target -> (ProxmoxClient, kind, node, vmid, name). Runs in a thread."""
    with app.state.sessionmaker() as db:
        model = App if target_type == "app" else Vm
        row = db.get(model, target_id)
        if row is None:
            raise JobFailed(f"{target_type} {target_id} not found")
        host = db.get(Host, row.host_id)
        if host is None:
            raise JobFailed(f"host for {target_type} {target_id} not found")
        try:
            client = client_for_host(app, db, host)
        except ProxmoxError as e:
            # Same sentence as before the extraction: a job reports a missing
            # credential as a failed job, never as a 502.
            raise JobFailed(str(e)) from e
        kind = "lxc" if target_type == "app" else "qemu"
        vmid = row.ctid if target_type == "app" else row.vmid
        node = host.node_name or ""
        return client, kind, node, int(vmid), row.name
```

- [ ] **Step 8: Run the new tests**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_proxmox_infra_reads.py -q`
Expected: PASS, 14 passed.

- [ ] **Step 9: Run the full backend suite (the refactor must move nothing)**

Run: `cd backend && ./.venv/bin/python -m pytest tests/ -q -m "not pve_integration and not e2e"`
Expected: 354 passed, 2 skipped, 3 deselected (340 baseline + 14 new). In
particular `tests/test_consoles_api.py`, `tests/test_lifecycle_jobs.py`
(including `test_missing_credential_fails_the_job`, which still asserts
`"no API token credential" in job.error`) and `tests/test_route_auth_invariant.py`
pass unchanged.

- [ ] **Step 10: Commit**

```bash
git add backend/proxploy/services/hostclient.py backend/proxploy/services/proxmox.py \
        backend/proxploy/api/consoles.py backend/proxploy/services/lifecycle.py \
        backend/tests/fakes/pve.py backend/tests/test_proxmox_infra_reads.py
git commit -m "refactor(proxmox): one client_for_host helper + storage/network/config/snapshot reads"
```

---

## Task 2: shared `await_task` + `enqueue_and_audit`, `lifecycle.py` refactored onto them

**Files:**
- Create: `backend/proxploy/services/pvetask.py`
- Modify: `backend/proxploy/services/lifecycle.py`, `backend/proxploy/api/jobs.py`, `backend/proxploy/config.py`
- Test: `backend/tests/test_pvetask.py` (plus the unchanged `backend/tests/test_lifecycle_jobs.py` and `backend/tests/test_lifecycle_api.py` as the no-behaviour-change proof)

**Interfaces:**
- Consumes: `JobContext.log(message, stream="stdout")` / `.progress(pct)` and `JobFailed` (existing, `proxploy/jobs/backend.py`, imported via `proxploy.jobs`); `ProxmoxClient.task_status(node, upid) -> dict` and `ProxmoxClient.task_log(node, upid, start=0, limit=500) -> list[dict]` (existing, `proxploy/services/proxmox.py:283`/`:292`); `JobBackend.enqueue(db, *, kind, target_type=None, target_id=None, params=None, requested_by=None, schedule_id=None) -> Job`; `write_audit(db, *, actor_type, action, actor_id=None, target_type=None, target_id=None, params=None, result="ok", ip=None, request_id=None, job_id=None)`; `job_out(j) -> dict` (existing, `proxploy/api/jobs.py:25`).
- Produces:
  - `proxploy/services/pvetask.py::await_task(ctx: JobContext, client: ProxmoxClient, node: str, upid: str, *, timeout_s: float = TASK_TIMEOUT_S, poll_s: float = TASK_POLL_S, start_pct: int = 10, end_pct: int = 100) -> dict`
  - `proxploy/services/pvetask.py::TASK_POLL_S = 1.0`, `TASK_TIMEOUT_S = 300.0`
  - `proxploy/api/jobs.py::enqueue_and_audit(request, db, user, *, kind: str, target_type: str | None, target_id: int | None, params: dict, action: str | None = None) -> dict`
  - `proxploy/config.py::Settings.pve_task_timeout_s: float = 300.0`

> **Contract note.** The spine's signature is extended by exactly one
> keyword-only parameter, `poll_s`, defaulting to `TASK_POLL_S`. It is required,
> not cosmetic: `tests/test_lifecycle_jobs.py` monkeypatches
> `lifecycle.TASK_POLL_S = 0.01` in three tests, and without a way to pass the
> patched value through, those tests would silently fall back to the real 1.0 s
> sleep. Every other Phase 6 caller can ignore it.

- [ ] **Step 1: Write the failing tests for `await_task`, the config knob and `enqueue_and_audit`**

```python
# backend/tests/test_pvetask.py
"""Phase 6 Task 2: the shared UPID poll-and-drain loop, extracted out of
services/lifecycle.py so twelve new job handlers don't each re-derive it."""
import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient

from proxploy.jobs import HANDLERS, JobBackend
from proxploy.models import AuditEvent, Job, JobEvent, User
from proxploy.services.proxmox import ProxmoxClient
from proxploy.services.pvetask import await_task
from tests.fakes.pve import FakePVE, make_fake_factory
from tests.support import make_app, make_job_app


def _client(fake):
    return ProxmoxClient("https://10.0.0.7:8006", "proxploy@pve!task", "s3cret",
                         verify_tls=False, factory=make_fake_factory(fake))


def _run_probe(tmp_path, fake, *, body, kind="test.await"):
    """Register a throwaway handler that drives await_task, run it, return the
    settled Job row plus its ordered job_events messages."""
    async def go():
        app = make_job_app(tmp_path, fake=fake)
        backend = JobBackend(app)

        async def probe(ctx, params):
            client = _client(fake)
            upid = client.guest_action("lxc", "pve1", 150, "start")
            return await body(ctx, client, upid)

        HANDLERS[kind] = probe
        try:
            with app.state.sessionmaker() as db:
                job_id = backend.enqueue(db, kind=kind, params={}).id
            await backend.wait(job_id, timeout=15)
        finally:
            HANDLERS.pop(kind, None)
        with app.state.sessionmaker() as db:
            job = db.get(Job, job_id)
            events = [(e.message, e.stream) for e in db.query(JobEvent)
                      .filter_by(job_id=job_id).order_by(JobEvent.seq)]
            return SimpleNamespace(status=job.status, error=job.error,
                                   result=job.result, progress=job.progress_pct,
                                   events=events)

    return asyncio.run(go())


def test_await_task_logs_the_upid_drains_the_log_and_returns_the_status(tmp_path):
    fake = FakePVE(running_ticks=2)

    async def body(ctx, client, upid):
        status = await await_task(ctx, client, "pve1", upid, poll_s=0.01)
        assert status["exitstatus"] == "OK"
        return {"upid": upid}

    out = _run_probe(tmp_path, fake, body=body)
    assert out.status == "succeeded"
    [upid] = fake.task_lines.keys()
    messages = [m for m, _ in out.events]
    assert messages[0] == f"proxmox task {upid}"
    assert "start lxc 150" in messages  # the task log was drained into job_events
    assert messages.count("start lxc 150") == 1  # exactly once, cursor advanced
    assert out.progress == 100


def test_await_task_fails_closed_on_a_missing_exitstatus(tmp_path):
    """A stopped task with no exitstatus is an UNKNOWN outcome, not a success."""
    fake = FakePVE(task_exit=None)

    async def body(ctx, client, upid):
        return await await_task(ctx, client, "pve1", upid, poll_s=0.01)

    out = _run_probe(tmp_path, fake, body=body)
    assert out.status == "failed"
    assert "no exitstatus reported" in out.error


def test_await_task_fails_on_a_nonzero_exitstatus(tmp_path):
    fake = FakePVE(task_exit="CT 150 is locked (snapshot)")

    async def body(ctx, client, upid):
        return await await_task(ctx, client, "pve1", upid, poll_s=0.01)

    out = _run_probe(tmp_path, fake, body=body)
    assert out.status == "failed"
    assert "locked" in out.error


def test_await_task_times_out_and_says_the_node_task_is_untouched(tmp_path):
    fake = FakePVE(running_ticks=10_000)

    async def body(ctx, client, upid):
        return await await_task(ctx, client, "pve1", upid, timeout_s=0.0, poll_s=0.01)

    out = _run_probe(tmp_path, fake, body=body)
    assert out.status == "failed"
    assert "still running" in out.error and "untouched" in out.error


def test_cancel_mid_poll_leaves_the_still_running_breadcrumb(tmp_path):
    """Verbatim from run_lifecycle: a locally cancelled job must never imply
    the proxmox-side task was undone."""
    fake = FakePVE(running_ticks=10_000)

    async def go():
        app = make_job_app(tmp_path, fake=fake)
        backend = JobBackend(app)

        async def probe(ctx, params):
            client = _client(fake)
            upid = client.guest_action("lxc", "pve1", 150, "start")
            return await await_task(ctx, client, "pve1", upid, poll_s=0.02)

        HANDLERS["test.cancel"] = probe
        try:
            with app.state.sessionmaker() as db:
                job_id = backend.enqueue(db, kind="test.cancel", params={}).id
            await asyncio.sleep(0.05)
            assert backend.cancel(job_id)
            await backend.wait(job_id, timeout=15)
        finally:
            HANDLERS.pop("test.cancel", None)
        with app.state.sessionmaker() as db:
            job = db.get(Job, job_id)
            events = [(e.message, e.stream) for e in db.query(JobEvent)
                      .filter_by(job_id=job_id).order_by(JobEvent.seq)]
        assert job.status == "canceled"
        assert any("keeps running" in m and s == "stderr" for m, s in events)

    asyncio.run(go())


def test_lifecycle_uses_the_shared_helper_rather_than_its_own_copy():
    """Root-cause DRY proof: run_lifecycle must reference the one await_task,
    not a re-pasted loop."""
    import inspect

    from proxploy.services import lifecycle, pvetask

    assert lifecycle.await_task is pvetask.await_task
    src = inspect.getsource(lifecycle.run_lifecycle)
    assert "await_task(" in src
    assert "task_status" not in src  # the poll loop lives in pvetask only


def test_pve_task_timeout_is_configurable(tmp_path, monkeypatch):
    from proxploy.config import Settings

    assert Settings(data_dir=tmp_path).pve_task_timeout_s == 300.0
    monkeypatch.setenv("PROXPLOY_PVE_TASK_TIMEOUT_S", "45")
    assert Settings(data_dir=tmp_path).pve_task_timeout_s == 45.0


def test_enqueue_and_audit_writes_the_job_the_audit_row_and_the_202_body(tmp_path):
    from proxploy.api.jobs import enqueue_and_audit

    async def noop(ctx, params):
        return {}

    HANDLERS["test.enqueue"] = noop
    app = make_app(tmp_path, fake=FakePVE())
    try:
        with TestClient(app):
            with app.state.sessionmaker() as db:
                u = User(email="op@example.com", display_name="Op")
                db.add(u)
                db.commit()
                req = SimpleNamespace(app=app,
                                      client=SimpleNamespace(host="10.9.9.9"))
                out = enqueue_and_audit(req, db, SimpleNamespace(id=u.id),
                                        kind="test.enqueue", target_type="storage",
                                        target_id=7, params={"volid": "local:iso/x.iso"},
                                        action="storage.upload")
                job_id = out["job"]["id"]
                assert out["job"]["kind"] == "test.enqueue"
                assert db.get(Job, job_id).requested_by == u.id
                row = db.query(AuditEvent).filter_by(action="storage.upload").one()
                assert row.job_id == job_id
                assert row.target_type == "storage" and row.target_id == 7
                assert row.ip == "10.9.9.9" and row.actor_id == u.id
    finally:
        HANDLERS.pop("test.enqueue", None)
```

- [ ] **Step 2: Run to verify the failure**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_pvetask.py -q`
Expected: FAIL at collection, `ModuleNotFoundError: No module named 'proxploy.services.pvetask'`.

- [ ] **Step 3: Create `proxploy/services/pvetask.py` (the loop moved out of `run_lifecycle`, unedited)**

```python
# backend/proxploy/services/pvetask.py
"""The shared UPID poll-and-drain loop (doc 02 §3, doc 03).

Every mutating Proxmox call returns a UPID and then has to be watched: poll
/nodes/{node}/tasks/{upid}/status, drain /log into job_events, fail closed on
anything that is not exitstatus "OK". services/lifecycle.py proved that shape
in Phase 3; Phase 6 adds twelve more handlers that need exactly it, so it lives
here once instead of thirteen times.

Both the cancellation breadcrumb and the fail-closed exitstatus check are
carried over verbatim; they are the two pieces a re-derivation gets wrong:
a cancelled job must never imply the proxmox-side task was undone, and a
stopped task with a missing exitstatus is an unknown outcome, not a success.
"""
from __future__ import annotations

import asyncio

from proxploy.jobs import JobContext, JobFailed
from proxploy.services.proxmox import ProxmoxClient

TASK_POLL_S = 1.0
# ponytail: flat wall-clock ceiling per task. A slow shutdown or a 40 GB
# restore that genuinely needs longer belongs to a per-kind timeout table,
# which is worth building when a real workload proves one operation needs it.
# Callers that already know they are slow pass their own timeout_s (Phase 6's
# handlers pass settings.pve_task_timeout_s).
TASK_TIMEOUT_S = 300.0


async def await_task(ctx: JobContext, client: ProxmoxClient, node: str, upid: str, *,
                     timeout_s: float = TASK_TIMEOUT_S, poll_s: float = TASK_POLL_S,
                     start_pct: int = 10, end_pct: int = 100) -> dict:
    """Log the UPID, poll it to completion, stream its task log into the job.

    Returns the final task-status dict (`{status, exitstatus, ...}`). Raises
    JobFailed on timeout or on any exitstatus other than "OK".
    """
    ctx.log(f"proxmox task {upid}")
    ctx.progress(start_pct)

    seen = 0
    deadline = asyncio.get_running_loop().time() + timeout_s
    try:
        while True:
            status = await asyncio.to_thread(client.task_status, node, upid)
            rows = await asyncio.to_thread(client.task_log, node, upid, seen)
            for r in rows:
                ctx.log(str(r.get("t", "")))
                seen = max(seen, int(r.get("n", seen)))
            if status.get("status") != "running":
                break
            if asyncio.get_running_loop().time() > deadline:
                raise JobFailed(f"proxmox task {upid} still running after "
                                f"{timeout_s:.0f}s, giving up on the log, the "
                                f"task itself is untouched on the node")
            await asyncio.sleep(poll_s)
    except asyncio.CancelledError:
        # The POST already reached proxmox and is unaffected by a local cancel, 
        # telling the user it was "canceled" without this line would read as
        # "nothing happened", which is false.
        ctx.log(f"canceled locally; proxmox task {upid} keeps running on {node}",
                stream="stderr")
        raise

    exitstatus = status.get("exitstatus")
    if exitstatus != "OK":
        # Fail closed: a stopped task with a missing/None exitstatus is an
        # unknown outcome, not a success, contra proxmox.py's own contract.
        reason = exitstatus if exitstatus else "no exitstatus reported"
        raise JobFailed(f"proxmox task {upid} failed: {reason}")

    ctx.progress(end_pct)
    return status
```

- [ ] **Step 4: Add `pve_task_timeout_s` to `config.py`**

In `backend/proxploy/config.py`, add one line to `Settings`, after
`console_idle_timeout_s`:

```python
    console_idle_timeout_s: float = 1800.0
    # Wall-clock ceiling every Phase 6 job handler passes to
    # services/pvetask.py::await_task. services/lifecycle.py keeps its own
    # module constant instead: a start/stop that needs five minutes is a
    # different animal from a restore that needs fifty, and lifecycle's
    # timeout is already exercised by tests that monkeypatch it.
    pve_task_timeout_s: float = 300.0
```

- [ ] **Step 5: Add `enqueue_and_audit` to `api/jobs.py`**

In `backend/proxploy/api/jobs.py`, add after `backlog` (every import it needs; 
`Request`, `User`, `write_audit`, `job_out`; is already in the file):

```python
def enqueue_and_audit(request: Request, db, user: User, *, kind: str,
                      target_type: str | None, target_id: int | None,
                      params: dict, action: str | None = None) -> dict:
    """Enqueue a job, write the audit row that points at it, return the 202 body.

    api/apps.py::enqueue_lifecycle is this same shape plus the self-guard and
    the fixed `{target_type}.{action}` kind; this is the plain version every
    Phase 6 mutation route uses. `action` overrides the audit action when the
    job kind is not the right name for the audit trail (a `backup.run` job
    fired from the restore route, say); it defaults to `kind`.

    Both `params` copies are redacted at their own sink: JobBackend.enqueue
    redacts before writing `jobs.params`, write_audit before `audit_events.params`.
    """
    job = request.app.state.jobs.enqueue(
        db, kind=kind, target_type=target_type, target_id=target_id,
        params=params, requested_by=user.id)
    write_audit(db, actor_type="user", actor_id=user.id, action=action or kind,
                target_type=target_type, target_id=target_id, params=params,
                job_id=job.id, ip=request.client.host if request.client else None)
    return {"job": job_out(job)}
```

- [ ] **Step 6: Refactor `run_lifecycle` onto `await_task`**

In `backend/proxploy/services/lifecycle.py`, delete the two module constants
and import them from `pvetask` instead, so the names existing tests
monkeypatch (`lc.TASK_POLL_S`, `lc.TASK_TIMEOUT_S`) still exist and still take
effect, `run_lifecycle` reads both as module globals at call time:

```python
from proxploy.jobs import HANDLERS, JobContext, JobFailed
from proxploy.models import App, Host, Vm
from proxploy.services.hostclient import client_for_host
from proxploy.services.proxmox import ProxmoxError
from proxploy.services.pvetask import TASK_POLL_S, TASK_TIMEOUT_S, await_task
```

(the `TASK_POLL_S = 1.0` / `TASK_TIMEOUT_S = 300.0` block and its ponytail
comment are deleted here, the comment moved to `pvetask.py` in Step 3.)

Then replace everything in `run_lifecycle` from `ctx.log(f"proxmox task {upid}")`
down to the `return`:

```python
    ctx.log(f"{action} {name} ({kind} {vmid}) on node {node}")
    try:
        upid = await asyncio.to_thread(client.guest_action, kind, node, vmid,
                                       PVE_VERB[action])
    except asyncio.CancelledError:
        # to_thread cannot interrupt the thread once it has started: the POST
        # may already have reached proxmox, but the UPID it would return is
        # discarded here, so there is no task to point at. Leave a breadcrumb
        # even without one, rather than pretending the job vanished cleanly.
        ctx.log(f"canceled while issuing {action} on {kind} {vmid} at {node}, "
                f"the request may have already reached proxmox; no task id was "
                f"captured to track it", stream="stderr")
        raise

    status = await await_task(ctx, client, node, upid,
                              timeout_s=TASK_TIMEOUT_S, poll_s=TASK_POLL_S)

    # Nudge every open tab to refetch rather than assert a status we have not
    # polled yet: the poller owns cached state (doc 04: Proxmox is the truth).
    app.state.bus.publish("resource", {"type": target_type, "id": target_id,
                                       "change": "lifecycle"})
    return {"upid": upid, "exitstatus": status.get("exitstatus"),
            "node": node, "vmid": vmid}
```

Two deliberate, asserted-nowhere deltas, both noted here rather than hidden:
the redundant mid-loop `ctx.progress(50)` is gone (the 10 and 100 ticks still
bracket the same window), and the exitstatus failure message is now
`"proxmox task {upid} failed: {reason}"` instead of `"{action} failed: {reason}"`
the shared helper does not know the caller's verb, and `jobs.kind` already
records it. `tests/test_lifecycle_jobs.py::test_nonzero_exitstatus_fails_the_job`
asserts on the proxmox-supplied `reason` substring, which is unchanged.

- [ ] **Step 7: Run the new tests**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_pvetask.py -q`
Expected: PASS, 8 passed.

- [ ] **Step 8: Run the two existing lifecycle files UNCHANGED; this is the no-behaviour-change proof**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_lifecycle_jobs.py tests/test_lifecycle_api.py -q`
Expected: PASS, 20 passed, in roughly the same wall-clock time as before the
refactor (if it suddenly takes ~6 s longer, `poll_s=TASK_POLL_S` was dropped
from the `await_task` call in Step 6 and the monkeypatched 0.01 s poll interval
is being ignored). The four tests that matter most here:
`test_task_log_lines_are_not_dropped_or_duplicated_across_polls`,
`test_cancel_mid_poll_reports_the_proxmox_task_is_still_running`,
`test_task_timeout_fails_the_job`, `test_nonzero_exitstatus_fails_the_job`.

- [ ] **Step 9: Run the full backend suite**

Run: `cd backend && ./.venv/bin/python -m pytest tests/ -q -m "not pve_integration and not e2e"`
Expected: 362 passed, 2 skipped, 3 deselected (354 after Task 1 + 8 new).

- [ ] **Step 10: Commit**

```bash
git add backend/proxploy/services/pvetask.py backend/proxploy/services/lifecycle.py \
        backend/proxploy/api/jobs.py backend/proxploy/config.py \
        backend/tests/test_pvetask.py
git commit -m "refactor(jobs): extract await_task + enqueue_and_audit, move lifecycle onto them"
```

---

---

## Task 3: Storage reads: poller enrichment + `GET /storage`, `/storage/{host_id}/{name}`, `/storage/{host_id}/{name}/content`

**Files:**
- Create: `backend/proxploy/api/storage.py`
- Modify: `backend/proxploy/pollers/__init__.py`, `backend/proxploy/api/cluster.py`, `backend/proxploy/api/__init__.py`, `backend/tests/fixtures/pve/cluster_resources_basic.json`
- Test: `backend/tests/test_storage_api.py` (new), `backend/tests/test_poller_ingest.py` (extend)

**Interfaces:**
- Consumes: `proxploy.services.hostclient::client_for_host(app, db, host) -> ProxmoxClient` (Task 1), `ProxmoxClient.storage_status(node, storage) -> dict` (Task 1), `ProxmoxClient.storage_content(node, storage, content=None) -> list[dict]` (Task 1), `FakePVE.storage_status_response` / `FakePVE.content_by_storage` (Task 1), `proxploy.api.deps::{get_db, require_role, require_entitlement}`, `tests.support::seed_snapshot`.
- Produces:
  - `HostSnapshot.storage` dicts gain `type` (from `/cluster/resources`' `plugintype`), `content: list[str]`, `shared: bool`, `status: str`, **no new PVE call**, these four fields already ride on every `type=="storage"` row of the one bulk `cluster_resources()` the poller already makes (doc 02 §3's O(nodes) budget is untouched).
  - `proxploy/api/storage.py::router = APIRouter(prefix="/storage", tags=["storage"])` with
    `GET /api/v1/storage -> [{host_id, host_name, node, storage, type, content: list[str], shared: bool, status: str, used_bytes, total_bytes, used_pct}]`,
    `GET /api/v1/storage/{host_id}/{name}?node= -> {…same…, avail_bytes, nodes: [str]}`,
    `GET /api/v1/storage/{host_id}/{name}/content?node=&content= -> [{volid, format, size, used, vmid, ctime, content, notes, verification}]`
  - module helpers `_pct(used, total) -> float`, `_content_list(v) -> list[str]`, `_row(host, st) -> dict`, `_host_or_404(db, host_id) -> Host`, `_nodes_with(request, host_id, name) -> list[str]`, `_resolve_node(request, host, name, node) -> str`; Tasks 4 and 5 import `_host_or_404` and `_resolve_node` from this module rather than re-deriving the node.

- [ ] **Step 1: Add the four already-returned fields to the poller fixture**

`/cluster/resources` returns `plugintype`, `content`, `shared` on every storage row; the recorded fixture predates anything caring about them. Additive only, every existing assertion (`len(snap.storage) == 2`) still holds.

```json
[
  {"type": "node", "node": "pve1", "status": "online", "cpu": 0.42, "maxcpu": 8,
   "mem": 13743895347, "maxmem": 33822867456, "uptime": 864000, "id": "node/pve1", "level": ""},
  {"type": "lxc", "vmid": 150, "name": "immich", "node": "pve1", "status": "running",
   "cpu": 0.12, "maxcpu": 4, "mem": 2147483648, "maxmem": 4294967296,
   "disk": 5368709120, "maxdisk": 17179869184, "uptime": 86400, "id": "lxc/150"},
  {"type": "lxc", "vmid": 200, "name": "plex", "node": "pve1", "status": "running",
   "cpu": 0.05, "maxcpu": 2, "mem": 1073741824, "maxmem": 2147483648,
   "disk": 3221225472, "maxdisk": 8589934592, "uptime": 43200, "id": "lxc/200"},
  {"type": "qemu", "vmid": 100, "name": "win11", "node": "pve1", "status": "running",
   "cpu": 0.31, "maxcpu": 4, "mem": 6442450944, "maxmem": 8589934592,
   "disk": 0, "maxdisk": 68719476736, "uptime": 172800, "id": "qemu/100"},
  {"type": "storage", "storage": "local", "node": "pve1", "status": "available",
   "disk": 107374182400, "maxdisk": 471859200000, "plugintype": "dir",
   "content": "iso,vztmpl,backup", "shared": 0, "id": "storage/pve1/local"},
  {"type": "storage", "storage": "pbs-datastore", "node": "pve1", "status": "available",
   "disk": 214748364800, "maxdisk": 1099511627776, "plugintype": "pbs",
   "content": "backup", "shared": 1, "id": "storage/pve1/pbs-datastore"}
]
```

Write that to `backend/tests/fixtures/pve/cluster_resources_basic.json`.

- [ ] **Step 2: Write the failing poller-enrichment test**

Append to `backend/tests/test_poller_ingest.py`:

```python
def test_snapshot_storage_carries_type_content_shared_status(tmp_path):
    """/cluster/resources already returns plugintype/content/shared/status on
    every storage row; the poller used to drop all four. Keeping them costs
    zero extra PVE calls, which is the only reason the Storage page can be
    served from the snapshot at all (doc 02 §3's O(nodes) poll budget)."""
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db)
    snap = _ingest(db, host).snapshot

    by_name = {s["storage"]: s for s in snap.storage}
    assert by_name["local"] == {
        "storage": "local", "node": "pve1",
        "used_bytes": 107374182400, "total_bytes": 471859200000,
        "type": "dir", "content": ["iso", "vztmpl", "backup"],
        "shared": False, "status": "available"}
    assert by_name["pbs-datastore"]["type"] == "pbs"
    assert by_name["pbs-datastore"]["content"] == ["backup"]
    assert by_name["pbs-datastore"]["shared"] is True
```

- [ ] **Step 3: Run to verify the failure**

Run: `cd backend && pytest tests/test_poller_ingest.py -v`
Expected: FAIL, `test_snapshot_storage_carries_type_content_shared_status` fails with an `AssertionError` showing the snapshot dict is still the four-key `{'storage', 'node', 'used_bytes', 'total_bytes'}` form. The other four tests in the file PASS (the fixture change is additive).

- [ ] **Step 4: Enrich `snap_storage` in the poller**

In `backend/proxploy/pollers/__init__.py`, replace the `snap_storage = [...]` block (lines 183-188):

```python
    snap_storage = [
        {"storage": r.get("storage"), "node": r.get("node"),
         "used_bytes": int(r.get("disk") or 0),
         "total_bytes": int(r.get("maxdisk") or 0),
         # These four ride on the SAME /cluster/resources row the two above come
         # from: the poller used to discard them. Reading them here is what
         # lets GET /storage answer from the snapshot instead of adding a
         # per-datastore PVE call, which doc 02 §3's O(nodes) budget forbids.
         "type": r.get("plugintype"),
         "content": [c for c in str(r.get("content") or "").split(",") if c],
         "shared": bool(r.get("shared")),
         "status": r.get("status") or "unknown"}
        for r in storage_rows
    ]
```

- [ ] **Step 5: Run the poller tests to verify they pass**

Run: `cd backend && pytest tests/test_poller_ingest.py tests/test_poller_loop.py tests/test_cluster_api.py -v`
Expected: PASS. In particular `test_cluster_api.py::test_summary_aggregates_and_dedupes_storage` still passes untouched, `cluster_summary` only reads `st["storage"]`, `st["used_bytes"]` and `st["total_bytes"]`, so four extra keys are invisible to it, and its `storage.setdefault(st["storage"], st)` dedupe is unchanged.

- [ ] **Step 6: Update the `# ponytail:` comment in `api/cluster.py` that points at this phase**

cluster.py:33-36 currently promises "per-datastore truth arrives with the Phase 6 Storage page". It has arrived; the comment must now say where it lives and name the ceiling this aggregate keeps. Replace lines 33-36:

```python
        for st in snap.storage:
            # ponytail: name-keyed dedupe, which is exact for a shared datastore
            # (one datastore reported once per node) and undercounts a LOCAL
            # storage that happens to share a name across nodes (`local` on pve1
            # and pve2 is 2x the capacity, counted once). This is the cluster
            # RING: a single number, and the snapshot dict now carries
            # `shared`, so the fix is one line (`key = st["storage"] if
            # st["shared"] else (st["node"], st["storage"])`) if the ring is ever
            # shown to disagree with the page. Per-datastore truth, which does
            # key on `shared`, is GET /storage (api/storage.py::list_storage).
            storage.setdefault(st["storage"], st)
```

- [ ] **Step 7: Write the failing storage-API tests**

```python
# backend/tests/test_storage_api.py
"""GET /storage reads: list from the poller snapshot, detail + content live."""
import json


def _seed(tmp_path, fake=None):
    from fastapi.testclient import TestClient
    from proxploy.models import HostCredential
    from tests.support import make_app, seed_host_row

    app = make_app(tmp_path, fake=fake)
    with app.state.sessionmaker() as db:
        host = seed_host_row(db)
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!store", "token_secret": "s3cret"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token",
                              encrypted_blob=blob, key_version=ver,
                              public_meta="proxploy@pve!store"))
        db.commit()
        hid = host.id
    return app, TestClient(app), hid


LOCAL_PVE1 = {"storage": "local", "node": "pve1", "used_bytes": 100,
              "total_bytes": 400, "type": "dir",
              "content": ["iso", "vztmpl"], "shared": False, "status": "available"}
LOCAL_PVE2 = {**LOCAL_PVE1, "node": "pve2", "used_bytes": 50}
PBS_PVE1 = {"storage": "pbs-main", "node": "pve1", "used_bytes": 10,
            "total_bytes": 1000, "type": "pbs", "content": ["backup"],
            "shared": True, "status": "available"}
PBS_PVE2 = {**PBS_PVE1, "node": "pve2"}


def test_list_serves_the_enriched_snapshot_fields(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import seed_snapshot

    app, c, hid = _seed(tmp_path)
    with c:
        bootstrap_admin(c)
        seed_snapshot(app, hid, storage=[LOCAL_PVE1])
        rows = c.get("/api/v1/storage").json()
        assert rows == [{"host_id": hid, "host_name": "host-01", "node": "pve1",
                         "storage": "local", "type": "dir",
                         "content": ["iso", "vztmpl"], "shared": False,
                         "status": "available", "used_bytes": 100,
                         "total_bytes": 400, "used_pct": 25.0}]


def test_list_dedupes_shared_storage_but_keeps_local_per_node(tmp_path, csrf_header,
                                                              bootstrap_admin):
    """A shared datastore is reported once per node and is ONE datastore; a
    local one with the same name on two nodes is two. `shared` came off the
    same poll row, so this is exact rather than a heuristic."""
    from tests.support import seed_snapshot

    app, c, hid = _seed(tmp_path)
    with c:
        bootstrap_admin(c)
        seed_snapshot(app, hid,
                      storage=[LOCAL_PVE1, LOCAL_PVE2, PBS_PVE1, PBS_PVE2])
        rows = c.get("/api/v1/storage").json()
        assert [(r["storage"], r["node"]) for r in rows] == [
            ("local", "pve1"), ("local", "pve2"), ("pbs-main", "pve1")]


def test_detail_is_a_live_passthrough_and_lists_every_serving_node(tmp_path, csrf_header,
                                                                   bootstrap_admin):
    from tests.fakes.pve import FakePVE
    from tests.support import seed_snapshot

    fake = FakePVE()
    fake.storage_status_response = {"type": "pbs", "content": "backup",
                                    "active": 1, "enabled": 1, "shared": 1,
                                    "used": 10, "avail": 990, "total": 1000}
    app, c, hid = _seed(tmp_path, fake=fake)
    with c:
        bootstrap_admin(c)
        seed_snapshot(app, hid, storage=[PBS_PVE1, PBS_PVE2])
        d = c.get(f"/api/v1/storage/{hid}/pbs-main").json()
        assert d["type"] == "pbs" and d["content"] == ["backup"]
        assert d["shared"] is True and d["status"] == "available"
        assert d["used_bytes"] == 10 and d["avail_bytes"] == 990
        assert d["total_bytes"] == 1000 and d["used_pct"] == 1.0
        assert d["nodes"] == ["pve1", "pve2"]


def test_detail_404s_an_unknown_host(tmp_path, csrf_header, bootstrap_admin):
    app, c, hid = _seed(tmp_path)
    with c:
        bootstrap_admin(c)
        assert c.get("/api/v1/storage/9999/local").status_code == 404


def test_content_passes_the_filter_through_and_normalises_rows(tmp_path, csrf_header,
                                                               bootstrap_admin):
    from tests.fakes.pve import FakePVE
    from tests.support import seed_snapshot

    fake = FakePVE()
    fake.content_by_storage = {"local": [
        {"volid": "local:iso/ubuntu-24.04.iso", "format": "iso", "size": 6000,
         "content": "iso", "ctime": 1730000000},
        {"volid": "local:backup/vzdump-qemu-100.vma.zst", "format": "vma.zst",
         "size": 900, "content": "backup", "vmid": 100, "ctime": 1730000100,
         "notes": "nightly", "verification": {"state": "ok"}},
    ]}
    app, c, hid = _seed(tmp_path, fake=fake)
    with c:
        bootstrap_admin(c)
        seed_snapshot(app, hid, storage=[LOCAL_PVE1])
        rows = c.get(f"/api/v1/storage/{hid}/local/content?content=iso").json()
        assert rows == [{"volid": "local:iso/ubuntu-24.04.iso", "format": "iso",
                         "size": 6000, "used": 0, "vmid": None,
                         "ctime": 1730000000, "content": "iso", "notes": None,
                         "verification": None}]
        all_rows = c.get(f"/api/v1/storage/{hid}/local/content").json()
        assert len(all_rows) == 2
        assert all_rows[1]["verification"] == {"state": "ok"}


def test_storage_reads_require_a_session(tmp_path):
    app, c, hid = _seed(tmp_path)
    with c:
        assert c.get("/api/v1/storage").status_code == 401
        assert c.get(f"/api/v1/storage/{hid}/local").status_code == 401
        assert c.get(f"/api/v1/storage/{hid}/local/content").status_code == 401
```

- [ ] **Step 8: Run to verify the failure**

Run: `cd backend && pytest tests/test_storage_api.py -v`
Expected: FAIL, all 6 error with `404` bodies (`{"type":"about:blank","title":"Not Found",…}`) because no `/api/v1/storage` route is registered yet; `test_storage_reads_require_a_session` fails on `assert 404 == 401`.

- [ ] **Step 9: Write `api/storage.py`**

```python
# backend/proxploy/api/storage.py
"""Storage routes (doc 05 §Storage, doc 01 §5).

Reads only, in this task. The LIST is served from the poller's in-memory
`HostSnapshot.storage`: doc 05 calls it a "live-refreshed cache", and since the
poll loop's single `cluster_resources()` already carries every field the page
needs, listing costs zero PVE calls. Detail and content are on-demand
passthroughs, one PVE call each, triggered by a human opening a datastore.
There is no storage table and none is added: doc 04 defines no storage entity.

Entitlements: doc 05 leaves the column blank on all three reads. Doc 01 §5
names `storage.view` (datastore overview) and `storage.content` (content
browser) as real features, and doc 07 §3 says a feature without a key does not
merge, so the reads are gated with their doc-01 keys rather than left ungated.
Functionally identical today (every flag defaults ON); recorded as a doc-05
amendment in the phase notes.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from proxploy.api.deps import get_db, require_entitlement, require_role
from proxploy.models import Host, User
from proxploy.services.hostclient import client_for_host
from proxploy.services.proxmox import ProxmoxError

router = APIRouter(prefix="/storage", tags=["storage"])

# Reused as BOTH the route-level dependency and the parameter-level one so
# FastAPI's dependency cache (keyed on the callable) collapses them into a
# single call that runs FIRST. A bare `dependencies=[Depends(require_entitlement(...))]`
# lands at position 0 and runs BEFORE auth, answering an anonymous caller with
# 403 instead of 401: see tests/test_route_auth_invariant.py.
_require_viewer = require_role("viewer")


def _pct(used: float, total: float) -> float:
    return round(used / total * 100, 1) if total else 0.0


def _content_list(v) -> list[str]:
    """Snapshot rows already hold a list; `storage_status()` returns PVE's raw
    comma string ("iso,vztmpl,backup"). Accept either."""
    if isinstance(v, list):
        return v
    return [c for c in str(v or "").split(",") if c]


def _row(host: Host, st: dict) -> dict:
    used, total = int(st.get("used_bytes") or 0), int(st.get("total_bytes") or 0)
    return {"host_id": host.id, "host_name": host.name, "node": st.get("node"),
            "storage": st.get("storage"), "type": st.get("type"),
            "content": _content_list(st.get("content")),
            "shared": bool(st.get("shared")),
            "status": st.get("status") or "unknown",
            "used_bytes": used, "total_bytes": total,
            "used_pct": _pct(used, total)}


def _host_or_404(db, host_id: int) -> Host:
    host = db.get(Host, host_id)
    if host is None:
        raise HTTPException(404, "host not found")
    return host


def _nodes_with(request: Request, host_id: int, name: str) -> list[str]:
    snap = request.app.state.poller.snapshots.get(host_id)
    if snap is None:
        return []
    return sorted({st["node"] for st in snap.storage
                   if st.get("storage") == name and st.get("node")})


def _resolve_node(request: Request, host: Host, name: str, node: str | None) -> str:
    """Every per-datastore PVE path is node-scoped, but the UI addresses a
    datastore by (host, name). Explicit ?node= wins; otherwise take the first
    node the last poll saw serving it, then the host's own node."""
    if node:
        return node
    found = _nodes_with(request, host.id, name)
    if found:
        return found[0]
    if host.node_name:
        return host.node_name
    raise HTTPException(409, f"cannot tell which node serves {name!r} on "
                             f"{host.name}, pass ?node=")


@router.get("", dependencies=[Depends(_require_viewer),
                              Depends(require_entitlement("storage.view"))])
def list_storage(request: Request, db=Depends(get_db),
                 user: User = Depends(_require_viewer)):
    snaps = request.app.state.poller.snapshots
    hosts = {h.id: h for h in db.query(Host).all()}
    seen: dict[tuple, dict] = {}
    for host_id, snap in snaps.items():
        host = hosts.get(host_id)
        if host is None:
            continue  # host deleted between poll and request
        for st in snap.storage:
            # A shared datastore is reported once per node and is ONE
            # datastore; a local one with the same name on two nodes is two.
            key = ((host_id, st.get("storage")) if st.get("shared")
                   else (host_id, st.get("node"), st.get("storage")))
            seen.setdefault(key, _row(host, st))
    return sorted(seen.values(),
                  key=lambda r: (r["host_id"], r["storage"] or "", r["node"] or ""))


@router.get("/{host_id}/{name}",
            dependencies=[Depends(_require_viewer),
                          Depends(require_entitlement("storage.view"))])
def storage_detail(request: Request, host_id: int, name: str,
                   node: str | None = None, db=Depends(get_db),
                   user: User = Depends(_require_viewer)):
    host = _host_or_404(db, host_id)
    node = _resolve_node(request, host, name, node)
    try:
        st = client_for_host(request.app, db, host).storage_status(node, name)
    except ProxmoxError as e:
        raise HTTPException(502, str(e))
    used, total = int(st.get("used") or 0), int(st.get("total") or 0)
    return {"host_id": host.id, "host_name": host.name, "node": node,
            "storage": name, "type": st.get("type"),
            "content": _content_list(st.get("content")),
            "shared": bool(st.get("shared")),
            "status": "available" if st.get("active") else "inactive",
            "used_bytes": used, "total_bytes": total,
            "avail_bytes": int(st.get("avail") or 0),
            "used_pct": _pct(used, total),
            "nodes": _nodes_with(request, host_id, name) or [node]}


@router.get("/{host_id}/{name}/content",
            dependencies=[Depends(_require_viewer),
                          Depends(require_entitlement("storage.content"))])
def storage_content(request: Request, host_id: int, name: str,
                    node: str | None = None, content: str | None = None,
                    db=Depends(get_db), user: User = Depends(_require_viewer)):
    host = _host_or_404(db, host_id)
    node = _resolve_node(request, host, name, node)
    try:
        rows = client_for_host(request.app, db, host).storage_content(node, name, content)
    except ProxmoxError as e:
        raise HTTPException(502, str(e))
    return [{"volid": r.get("volid"), "format": r.get("format"),
             "size": int(r.get("size") or 0), "used": int(r.get("used") or 0),
             "vmid": r.get("vmid"), "ctime": r.get("ctime"),
             "content": r.get("content"), "notes": r.get("notes"),
             "verification": r.get("verification")} for r in rows]
```

- [ ] **Step 10: Register the router**

In `backend/proxploy/api/__init__.py`, add `storage` to the import tuple (alphabetical, between `settings` and `vms`) and include it after `cluster`; a two-segment `/{host_id}/{name}` sibling never collides with the one-segment `""` route, so order within this router is free, but keeping the include next to `cluster` groups the two snapshot-backed routers:

```python
from fastapi import APIRouter

from proxploy.api import (apps, audit, auth, catalog, cluster, consoles, entitlements,
                          events, hosts, jobs, meta, metrics, notifications, settings,
                          storage, vms)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(meta.router)
api_router.include_router(auth.router)
api_router.include_router(auth.users_router)
api_router.include_router(audit.router)
api_router.include_router(entitlements.router)
api_router.include_router(hosts.router)
api_router.include_router(settings.router)
api_router.include_router(events.router)
api_router.include_router(cluster.router)
api_router.include_router(storage.router)
api_router.include_router(apps.router)
api_router.include_router(catalog.router)
api_router.include_router(vms.router)
api_router.include_router(consoles.router)
api_router.include_router(jobs.router)
api_router.include_router(notifications.router)
api_router.include_router(metrics.router)
```

- [ ] **Step 11: Run the storage tests to verify they pass**

Run: `cd backend && pytest tests/test_storage_api.py tests/test_poller_ingest.py -v`
Expected: PASS (6 + 5 = 11 tests).

- [ ] **Step 12: Run the full backend suite (three routes joined the invariant walk)**

Run: `cd backend && pytest tests/ -q -m "not pve_integration and not e2e"`
Expected: PASS, up by exactly 7 tests versus the Task 2 baseline; `2 skipped, 3 deselected` unchanged. `test_route_auth_invariant.py` now walks `/api/v1/storage`, `/api/v1/storage/{host_id}/{name}` and `…/content` and must still report 401 for each; a 403 there means `require_entitlement` was listed before `_require_viewer`.

- [ ] **Step 13: Commit**

```bash
git add backend/proxploy/pollers/__init__.py backend/proxploy/api/storage.py \
        backend/proxploy/api/cluster.py backend/proxploy/api/__init__.py \
        backend/tests/fixtures/pve/cluster_resources_basic.json \
        backend/tests/test_storage_api.py backend/tests/test_poller_ingest.py
git commit -m "feat(storage): keep plugintype/content/shared/status in the poll snapshot and serve GET /storage reads"
```

---

## Task 4: Storage content mutations: upload + delete volume

> **Dependency correction, verified not assumed.** This plan's header originally
> claimed Phase 6 adds no backend dependency because `UploadFile` is "already
> available". It is not: `python-multipart` is absent from this venv
> (`./.venv/bin/python -c "import multipart"` → `ModuleNotFoundError`) and
> FastAPI refuses to even *define* a `File(...)` route without it, printing
> `pip install python-multipart`. Phase 6 therefore adds exactly one backend
> dependency, in Step 0 below. It is Apache-2.0, already inside the doc-03
> allowlist the CI license audit enforces (`--allow-only "…Apache;Apache
> Software License…"`), so the audit leg passes without an allowlist edit; 
> but Step 0 runs the audit anyway, per doc 03's protocol of verifying the
> license of every new dependency at the moment it is added rather than
> trusting a remembered value.

- [ ] **Step 0: Add `python-multipart` and re-run the license audit**

In `backend/pyproject.toml`, add to `dependencies` (after `websockets>=14`):

```toml
  "python-multipart>=0.0.9",
```

Then install and audit:

Run: `cd backend && ./.venv/bin/python -m pip install "python-multipart>=0.0.9"`
Expected: `Successfully installed python-multipart-<version>`

Run: `cd backend && ./.venv/bin/python -m pip install pip-licenses && ./.venv/bin/pip-licenses --partial-match --ignore-packages proxploy --allow-only "MIT;MIT License;BSD;BSD License;Apache;Apache Software License;ISC;Python Software Foundation;PSF-2.0;PostgreSQL;Public Domain;Mozilla Public License 2.0;Eclipse Public License v2.0;EPL-2.0;The Unlicense;CMU License (MIT-CMU)"`
Expected: exits 0, `python-multipart` reports Apache-2.0 and is inside the allowlist. If it exits non-zero, stop and report; do not widen the allowlist.

Run: `cd backend && ./.venv/bin/python -c "from fastapi import FastAPI, UploadFile, File; a=FastAPI(); a.post('/x')(lambda f=File(...): 1); print('UploadFile routes definable')"`
Expected: `UploadFile routes definable` (before Step 0 this printed `pip install python-multipart`).

**Files:**
- Create: `backend/proxploy/services/storagejobs.py`
- Modify: `backend/proxploy/services/proxmox.py`, `backend/proxploy/api/storage.py`, `backend/proxploy/config.py`, `backend/proxploy/main.py`, `backend/tests/fakes/pve.py`
- Test: `backend/tests/test_storage_content.py`

**Interfaces:**
- Consumes: `proxploy.services.pvetask::await_task(ctx, client, node, upid, *, timeout_s=300.0, start_pct=10, end_pct=100) -> dict` (Task 2), `proxploy.api.jobs::enqueue_and_audit(request, db, user, *, kind, target_type, target_id, params, action=None) -> dict` (Task 2), `proxploy.services.hostclient::client_for_host` (Task 1), `proxploy.api.storage::{_host_or_404, _resolve_node}` (Task 3), `proxploy.jobs::{HANDLERS, JobContext, JobFailed}`.
- Produces:
  - `ProxmoxClient.storage_upload(node: str, storage: str, content: str, filename: str, path: str) -> str` (UPID)
  - `ProxmoxClient.storage_delete_volume(node: str, storage: str, volid: str) -> str | None` (UPID, or `None` when PVE deletes synchronously)
  - `proxploy/services/storagejobs.py::run_upload(ctx, params) -> dict`, `run_delete_volume(ctx, params) -> dict`, registered as job kinds `storage.upload` and `storage.delete_volume`
  - routes `POST /api/v1/storage/{host_id}/{name}/content` (202, multipart, admin + `storage.content`) and `DELETE /api/v1/storage/{host_id}/{name}/content/{volid:path}` (202, admin + `storage.content`)
  - `Settings.storage_upload_max_bytes: int`
  - FakePVE: `uploads: list[dict]`, `deleted_volumes: list[tuple]`, callable `nodes(n).storage(s).content(volid)` + `nodes(n).storage(s).upload`

> **Plan note, the upload path double-transfers the ISO, on purpose.**
> Proxmox's `/nodes/{node}/storage/{s}/upload` takes a multipart body; there is
> no "tell PVE to fetch this URL" variant that Proxploy could use instead
> (`download-url` exists but needs the file already published somewhere, which
> is a different feature). So a 5 GB ISO travels **browser → Proxploy → PVE**:
> it is written once to a temp file on the Proxploy host and read back once
> while POSTing upstream. Consequences, stated plainly rather than discovered in
> production: (1) the Proxploy host needs **transient free disk equal to the
> file size** for the life of the job, in `settings.data_dir/uploads`;
> (2) the upload takes roughly twice as long as a direct PVE upload;
> (3) `storage_upload_max_bytes` is the hard cap on both, defaulting to 16 GiB.
> What is NOT acceptable and is the whole reason the route is shaped this way:
> `await file.read()` would materialise the entire ISO in the Proxploy process's
> RAM before a single byte reached disk. The route reads in 1 MiB chunks and the
> job deletes the temp file in a `finally` on every exit path, success, PVE
> failure, cancellation, timeout.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_storage_content.py
"""Storage content mutations: streamed ISO upload + volume delete, both jobs."""
import asyncio
import json
import os
from pathlib import Path


def _seed(app):
    from proxploy.models import Host, HostCredential

    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.9:8006", node_name="pve1",
                    status="connected", pve_version="8.4.1")
        db.add(host)
        db.commit()
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!store", "token_secret": "s3cret"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token",
                              encrypted_blob=blob, key_version=ver,
                              public_meta="proxploy@pve!store"))
        db.commit()
        return host.id


def _api(tmp_path, fake=None, **overrides):
    from fastapi.testclient import TestClient
    from tests.support import make_app

    app = make_app(tmp_path, fake=fake, **overrides)
    return app, TestClient(app), _seed(app)


def test_upload_spools_to_disk_and_enqueues_a_job(tmp_path, csrf_header, bootstrap_admin):
    from proxploy.models import Job
    from tests.fakes.pve import FakePVE

    app, c, hid = _api(tmp_path, fake=FakePVE())
    with c:
        bootstrap_admin(c)
        payload = b"\x00" * (3 * 1024 * 1024)  # 3 MiB, larger than one chunk
        r = c.post(f"/api/v1/storage/{hid}/local/content",
                   files={"file": ("ubuntu.iso", payload, "application/octet-stream")},
                   data={"content": "iso", "node": "pve1"},
                   headers=csrf_header(c))
        assert r.status_code == 202
        job = r.json()["job"]
        assert job["kind"] == "storage.upload"
        assert job["target_type"] == "storage" and job["target_id"] == hid
        with app.state.sessionmaker() as db:
            row = db.get(Job, job["id"])
            assert row.params["filename"] == "ubuntu.iso"
            assert row.params["size_bytes"] == len(payload)
            spooled = Path(row.params["path"])
            assert spooled.parent == app.state.settings.data_dir / "uploads"
            # the bytes really are on disk, not in the request object
            assert spooled.stat().st_size == len(payload)


def test_upload_over_the_cap_is_413_and_leaves_no_temp_file(tmp_path, csrf_header,
                                                            bootstrap_admin):
    from tests.fakes.pve import FakePVE

    app, c, hid = _api(tmp_path, fake=FakePVE(), storage_upload_max_bytes=1024)
    with c:
        bootstrap_admin(c)
        r = c.post(f"/api/v1/storage/{hid}/local/content",
                   files={"file": ("big.iso", b"x" * 5000)},
                   data={"content": "iso", "node": "pve1"},
                   headers=csrf_header(c))
        assert r.status_code == 413
        assert "1024" in r.text
        uploads = app.state.settings.data_dir / "uploads"
        assert not uploads.exists() or list(uploads.iterdir()) == []


def test_the_upload_route_never_buffers_the_whole_body_in_memory(tmp_path):
    """A one-line `await file.read()` turns a 5 GB ISO into 5 GB of RSS. The
    streaming loop is the point of this route, so guard it like a lint rather
    than trusting review (tests/test_isolation_lint.py precedent)."""
    import proxploy.api.storage as mod

    src = Path(mod.__file__).read_text()
    assert "file.read()" not in src
    assert "await file.read" not in src
    assert "file.file.read(" in src  # the chunked loop


def test_upload_job_posts_to_proxmox_and_always_deletes_the_temp_file(tmp_path):
    from proxploy.jobs import JobBackend
    from proxploy.models import Job
    from tests.fakes.pve import FakePVE
    from tests.support import make_job_app

    async def run():
        fake = FakePVE()
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.storagejobs  # noqa: F401, registers handlers
        backend = JobBackend(app)
        hid = _seed(app)
        spool = tmp_path / "ubuntu.iso"
        spool.write_bytes(b"ISO-BYTES")
        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(db, kind="storage.upload", target_type="storage",
                                     target_id=hid,
                                     params={"host_id": hid, "node": "pve1",
                                             "storage": "local", "content": "iso",
                                             "filename": "ubuntu.iso",
                                             "path": str(spool), "size_bytes": 9}).id
        await backend.wait(job_id, timeout=10)
        assert fake.uploads == [{"node": "pve1", "storage": "local", "content": "iso",
                                 "filename": "ubuntu.iso", "bytes": b"ISO-BYTES"}]
        with app.state.sessionmaker() as db:
            job = db.get(Job, job_id)
            assert job.status == "succeeded"
            assert job.result["volid"] == "local:iso/ubuntu.iso"
            assert job.result["exitstatus"] == "OK"
        assert not spool.exists()  # deleted in the finally

    asyncio.run(run())


def test_upload_job_deletes_the_temp_file_even_when_proxmox_fails(tmp_path):
    from proxploy.jobs import JobBackend
    from proxploy.models import Job
    from tests.fakes.pve import FakePVE
    from tests.support import make_job_app

    async def run():
        fake = FakePVE(task_exit="upload failed: no space left on device")
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.storagejobs  # noqa: F401
        backend = JobBackend(app)
        hid = _seed(app)
        spool = tmp_path / "doomed.iso"
        spool.write_bytes(b"x")
        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(db, kind="storage.upload", target_type="storage",
                                     target_id=hid,
                                     params={"host_id": hid, "node": "pve1",
                                             "storage": "local", "content": "iso",
                                             "filename": "doomed.iso",
                                             "path": str(spool), "size_bytes": 1}).id
        await backend.wait(job_id, timeout=10)
        with app.state.sessionmaker() as db:
            assert db.get(Job, job_id).status == "failed"
        assert not spool.exists()

    asyncio.run(run())


def test_delete_volume_route_enqueues_and_audits_the_volid(tmp_path, csrf_header,
                                                           bootstrap_admin):
    from proxploy.models import AuditEvent
    from tests.fakes.pve import FakePVE

    app, c, hid = _api(tmp_path, fake=FakePVE())
    with c:
        bootstrap_admin(c)
        volid = "local:iso/ubuntu-24.04.iso"
        r = c.delete(f"/api/v1/storage/{hid}/local/content/{volid}?node=pve1",
                     headers=csrf_header(c))
        assert r.status_code == 202
        job = r.json()["job"]
        assert job["kind"] == "storage.delete_volume"
        assert job["params"]["volid"] == volid
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="storage.delete_volume").one()
            assert row.target_type == "storage" and row.target_id == hid
            assert row.params["volid"] == volid
            assert row.job_id == job["id"]


def test_delete_volume_job_calls_delete_and_awaits_the_task(tmp_path):
    from proxploy.jobs import JobBackend
    from proxploy.models import Job
    from tests.fakes.pve import FakePVE
    from tests.support import make_job_app

    async def run():
        fake = FakePVE()
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.storagejobs  # noqa: F401
        backend = JobBackend(app)
        hid = _seed(app)
        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(
                db, kind="storage.delete_volume", target_type="storage", target_id=hid,
                params={"host_id": hid, "node": "pve1", "storage": "local",
                        "volid": "local:iso/old.iso"}).id
        await backend.wait(job_id, timeout=10)
        assert fake.deleted_volumes == [("pve1", "local", "local:iso/old.iso")]
        with app.state.sessionmaker() as db:
            job = db.get(Job, job_id)
            assert job.status == "succeeded"
            assert job.result["volid"] == "local:iso/old.iso"

    asyncio.run(run())
```

- [ ] **Step 2: Run to verify the failures**

Run: `cd backend && pytest tests/test_storage_content.py -v`
Expected: FAIL, the four job tests raise `KeyError: "no handler registered for job kind 'storage.upload'"` / `'storage.delete_volume'` from `JobBackend.enqueue`; the three route tests get 405/404 (no POST or DELETE registered under `/api/v1/storage/{host_id}/{name}/content`); `test_the_upload_route_never_buffers_the_whole_body_in_memory` fails on `assert "file.file.read(" in src`.

- [ ] **Step 3: Add the two `ProxmoxClient` methods**

Append to `class ProxmoxClient` in `backend/proxploy/services/proxmox.py`:

```python
    # --- storage content mutations (Phase 6) --------------------------------

    def storage_upload(self, node: str, storage: str, content: str,
                       filename: str, path: str) -> str:
        """POST /nodes/{node}/storage/{storage}/upload -> UPID.

        `path` is a spooled temp file on the Proxploy host, opened here and
        streamed by proxmoxer as the multipart part, the bytes are never held
        in memory by us (see api/storage.py's upload route for the other half).
        """
        try:
            with open(path, "rb") as fh:
                fh.name = filename  # proxmoxer names the multipart part from this
                return self._connect().nodes(node).storage(storage).upload.post(
                    content=content, filename=fh)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"upload of {filename!r} to {storage} on {node} failed",
                             e) from e

    def storage_delete_volume(self, node: str, storage: str, volid: str) -> str | None:
        """DELETE /nodes/{node}/storage/{storage}/content/{volid}.

        Returns a UPID for the plugins that delete asynchronously (PBS, ZFS) and
        None for the ones that do it inline (dir), the caller must handle both.
        """
        try:
            return self._connect().nodes(node).storage(storage).content(volid).delete()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"deleting {volid!r} from {storage} on {node} failed",
                             e) from e
```

- [ ] **Step 4: Make the FakePVE storage namespace callable and add the upload/delete leaves**

Task 1 added a per-node storage namespace serving `storages_by_node` / `storage_status_response` / `content_by_storage`. Replace that namespace and its `content` leaf with the versions below, same attributes, plus a callable `content(volid)` and an `upload` leaf. In `backend/tests/fakes/pve.py`:

```python
class _VolumeLeaf:
    """nodes(n).storage(s).content(volid).delete() records and mints a UPID."""

    def __init__(self, owner, node, storage, volid):
        self._owner, self._node = owner, node
        self._storage, self._volid = storage, volid

    def delete(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.deleted_volumes.append((self._node, self._storage, self._volid))
        return self._owner._record_action("storage", 0, "delvolume")


class _StorageContentNS:
    """.get() lists volumes; calling it drills into one volid."""

    def __init__(self, owner, node, storage):
        self._owner, self._node, self._storage = owner, node, storage

    def get(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        rows = self._owner.content_by_storage.get(self._storage, [])
        want = kwargs.get("content")
        return [r for r in rows if not want or r.get("content") == want]

    def __call__(self, volid):
        return _VolumeLeaf(self._owner, self._node, self._storage, volid)


class _UploadLeaf:
    def __init__(self, owner, node, storage):
        self._owner, self._node, self._storage = owner, node, storage

    def post(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        fh = kwargs.get("filename")
        self._owner.uploads.append({
            "node": self._node, "storage": self._storage,
            "content": kwargs.get("content"),
            "filename": getattr(fh, "name", ""),
            "bytes": fh.read() if hasattr(fh, "read") else b""})
        return self._owner._record_action("storage", 0, "upload")


class _NodeStorageNS:
    def __init__(self, owner, node, storage):
        self.status = _KwLeaf(owner.storage_status_response, owner.fail)
        self.content = _StorageContentNS(owner, node, storage)
        self.upload = _UploadLeaf(owner, node, storage)


class _NodeStorageFactory:
    """nodes(n).storage.get() lists the node's storages.storage(s) drills in."""

    def __init__(self, owner, node):
        self._owner, self._node = owner, node

    def get(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        return self._owner.storages_by_node.get(self._node, [])

    def __call__(self, storage):
        return _NodeStorageNS(self._owner, self._node, storage)
```

In `_NodeNS.__init__`, the storage attribute must be the factory (replace whatever Task 1 wired there):

```python
        self.storage = _NodeStorageFactory(owner, name)
```

And in `FakePVE.__init__`, after the Phase-5 console block, add the two new recorders:

```python
        # storage content mutations (Phase 6)
        self.uploads: list[dict] = []
        self.deleted_volumes: list[tuple] = []
```

- [ ] **Step 5: Add the upload cap to `config.py`**

In `backend/proxploy/config.py`, after `console_idle_timeout_s`:

```python
    # An ISO is spooled to `data_dir/uploads` on its way to PVE (api/storage.py),
    # so this caps BOTH the request body and the transient free disk the
    # Proxploy host must have. 16 GiB covers a Windows Server ISO with room.
    storage_upload_max_bytes: int = 16 * 1024 ** 3
```

- [ ] **Step 6: Write `services/storagejobs.py`**

```python
# backend/proxploy/services/storagejobs.py
"""Storage content job handlers (doc 05 §Storage, doc 01 §5 "Content browser").

Both handlers are the shape services/lifecycle.py established and Task 2
extracted: resolve in a thread, POST to Proxmox, hand the UPID to `await_task`.

The upload one carries one extra obligation. Proxmox's upload endpoint takes a
multipart body; there is no "fetch this URL yourself" variant, so an ISO is
transferred TWICE: browser -> Proxploy (spooled to `data_dir/uploads` by the
route, never buffered in RAM) and Proxploy -> PVE (read back here). The Proxploy
host therefore needs transient free disk equal to the file size for the life of
the job, and the upload takes about twice as long as a direct PVE upload. That
is the accepted cost of proxying it; what is not acceptable is holding the file
in memory, which is why the route streams and this handler takes a path rather
than bytes. The spool file is deleted in a `finally` on EVERY exit, success,
PVE failure, timeout, cancellation; because nothing else ever will.
"""
from __future__ import annotations

import asyncio
import contextlib
import os

from proxploy.jobs import HANDLERS, JobContext, JobFailed
from proxploy.models import Host
from proxploy.services.hostclient import client_for_host
from proxploy.services.pvetask import await_task


def _resolve(app, host_id: int, node: str | None):
    """Blocking: host_id -> (ProxmoxClient, node). Runs in a thread."""
    with app.state.sessionmaker() as db:
        host = db.get(Host, host_id)
        if host is None:
            raise JobFailed(f"host {host_id} not found")
        return client_for_host(app, db, host), (node or host.node_name or "")


async def run_upload(ctx: JobContext, params: dict) -> dict:
    app = ctx.backend.app
    host_id = int(params["host_id"])
    storage, content = params["storage"], params["content"]
    filename, path = params["filename"], params["path"]
    try:
        client, node = await asyncio.to_thread(_resolve, app, host_id, params.get("node"))
        ctx.log(f"uploading {filename} ({params.get('size_bytes', 0)} bytes) "
                f"to {storage} on {node}")
        upid = await asyncio.to_thread(client.storage_upload, node, storage,
                                       content, filename, path)
        status = await await_task(ctx, client, node, upid)
        app.state.bus.publish("resource", {"type": "storage", "id": host_id,
                                           "change": "content"})
        return {"upid": upid, "exitstatus": status.get("exitstatus"), "node": node,
                "storage": storage, "volid": f"{storage}:{content}/{filename}"}
    finally:
        # The ONLY place this file is ever removed. Suppressed because a failure
        # to unlink must not turn a succeeded upload into a failed job: the
        # bytes are already on PVE by then.
        with contextlib.suppress(OSError):
            os.unlink(path)


async def run_delete_volume(ctx: JobContext, params: dict) -> dict:
    app = ctx.backend.app
    host_id = int(params["host_id"])
    storage, volid = params["storage"], params["volid"]
    client, node = await asyncio.to_thread(_resolve, app, host_id, params.get("node"))
    ctx.log(f"deleting {volid} from {storage} on {node}")
    upid = await asyncio.to_thread(client.storage_delete_volume, node, storage, volid)
    exitstatus = "OK"
    if upid:
        exitstatus = (await await_task(ctx, client, node, upid)).get("exitstatus")
    else:
        # dir/lvm plugins delete inline and return no UPID: there is no task to
        # poll, and treating a missing UPID as a failure would fail every
        # successful ISO delete on local storage.
        ctx.log("deleted synchronously (no task id)")
        ctx.progress(100)
    app.state.bus.publish("resource", {"type": "storage", "id": host_id,
                                       "change": "content"})
    return {"upid": upid, "exitstatus": exitstatus, "node": node,
            "storage": storage, "volid": volid}


HANDLERS["storage.upload"] = run_upload
HANDLERS["storage.delete_volume"] = run_delete_volume
```

- [ ] **Step 7: Register the handler module in `main.py`'s lifespan**

Registration is by import side-effect only. In `backend/proxploy/main.py`, inside the lifespan import block (lines 83-85), add the fourth line:

```python
        from proxploy.services import appstore as _appstore  # noqa: F401, registers app.install
        from proxploy.services import catalog as _catalog  # noqa: F401, registers catalog.refresh
        from proxploy.services import lifecycle  # noqa: F401, registers job handlers
        from proxploy.services import storagejobs as _storagejobs  # noqa: F401, registers storage.upload/delete_volume
```

- [ ] **Step 8: Add the two routes to `api/storage.py`**

Extend the imports at the top of `backend/proxploy/api/storage.py`:

```python
import os
import tempfile

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Request,
                     UploadFile)

from proxploy.api.deps import get_db, require_entitlement, require_role
from proxploy.api.jobs import enqueue_and_audit
from proxploy.models import Host, User
from proxploy.services.hostclient import client_for_host
from proxploy.services.proxmox import ProxmoxError
```

Add the admin singleton next to `_require_viewer`:

```python
_require_admin = require_role("admin")

UPLOAD_CHUNK = 1024 * 1024
```

And append the two routes:

```python
@router.post("/{host_id}/{name}/content", status_code=202,
             dependencies=[Depends(_require_admin),
                           Depends(require_entitlement("storage.content"))])
def upload_content(request: Request, host_id: int, name: str,
                   file: UploadFile = File(...), content: str = Form("iso"),
                   node: str | None = Form(None), db=Depends(get_db),
                   user: User = Depends(_require_admin)):
    """Spool the body to disk, then hand the PATH to a job (doc 05 §Storage).

    NEVER `await file.read()`: FastAPI's UploadFile already spools to a
    SpooledTemporaryFile, and reading it whole would materialise a multi-GB ISO
    in this process's RAM. The 1 MiB loop below keeps peak memory flat
    regardless of file size. The cost, stated in services/storagejobs.py's
    docstring too: the ISO crosses the wire twice (browser -> here -> PVE) and
    the Proxploy host needs transient free disk equal to the file size.
    """
    host = _host_or_404(db, host_id)
    node = _resolve_node(request, host, name, node)
    max_bytes = request.app.state.settings.storage_upload_max_bytes
    updir = request.app.state.settings.data_dir / "uploads"
    updir.mkdir(parents=True, exist_ok=True)
    fd, spool = tempfile.mkstemp(dir=updir, suffix=".upload")
    written = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = file.file.read(UPLOAD_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(413, f"upload exceeds the "
                                             f"{max_bytes} byte limit")
                out.write(chunk)
    except BaseException:
        # Anything at all: cap exceeded, disconnect, cancellation; must not
        # leave a partial multi-GB file behind on the Proxploy host.
        with contextlib.suppress(OSError):
            os.unlink(spool)
        raise
    return enqueue_and_audit(
        request, db, user, kind="storage.upload", target_type="storage",
        target_id=host.id,
        params={"host_id": host.id, "node": node, "storage": name,
                "content": content, "filename": file.filename or "upload",
                "path": spool, "size_bytes": written})


@router.delete("/{host_id}/{name}/content/{volid:path}", status_code=202,
               dependencies=[Depends(_require_admin),
                             Depends(require_entitlement("storage.content"))])
def delete_content(request: Request, host_id: int, name: str, volid: str,
                   node: str | None = None, db=Depends(get_db),
                   user: User = Depends(_require_admin)):
    """`:path` because a volid is `local:iso/ubuntu.iso`, it carries a slash,
    which a plain `{volid}` converter would refuse to match."""
    host = _host_or_404(db, host_id)
    node = _resolve_node(request, host, name, node)
    return enqueue_and_audit(
        request, db, user, kind="storage.delete_volume", target_type="storage",
        target_id=host.id,
        params={"host_id": host.id, "node": node, "storage": name, "volid": volid})
```

Add `import contextlib` to the module's import block (used by the `except BaseException` cleanup above).

- [ ] **Step 9: Run the content tests to verify they pass**

Run: `cd backend && pytest tests/test_storage_content.py -v`
Expected: PASS (7 tests).

- [ ] **Step 10: Run the full backend suite**

Run: `cd backend && pytest tests/ -q -m "not pve_integration and not e2e"`
Expected: PASS, up by exactly 7 tests versus the Task 3 total; `2 skipped, 3 deselected` unchanged. `test_route_auth_invariant.py` walks the two new routes with an empty `_features` dict and must see 401 on both.

- [ ] **Step 11: Commit**

```bash
git add backend/proxploy/services/proxmox.py backend/proxploy/services/storagejobs.py \
        backend/proxploy/api/storage.py backend/proxploy/config.py \
        backend/proxploy/main.py backend/tests/fakes/pve.py \
        backend/tests/test_storage_content.py
git commit -m "feat(storage): streamed ISO upload + volume delete as tracked jobs"
```

---

## Task 5: Storage manage: attach / edit / detach

**Files:**
- Modify: `backend/proxploy/services/proxmox.py`, `backend/proxploy/api/storage.py`, `backend/tests/fakes/pve.py`
- Test: `backend/tests/test_storage_manage.py`

**Interfaces:**
- Consumes: `proxploy.services.hostclient::client_for_host` (Task 1), `proxploy.api.storage::_host_or_404` (Task 3), `proxploy.services.audit::write_audit` and its `redact`/`REDACT_SUBSTRINGS`, `proxploy.api.deps::require_role`.
- Produces:
  - `ProxmoxClient.storage_create(config: dict) -> None`, `storage_update(storage: str, config: dict) -> None`, `storage_remove(storage: str) -> None`, the **cluster-level** `/storage` endpoints, which are **synchronous and return no UPID**, so none of them goes through `await_task` or the job engine.
  - routes `POST /api/v1/storage` (201, admin + `storage.manage`), `PATCH /api/v1/storage/{host_id}/{name}` (admin + `storage.manage`), `DELETE /api/v1/storage/{host_id}/{name}` (**owner** + `storage.manage`, per doc 05).
  - FakePVE: root `.storage` becomes callable, `storage_creates: list[dict]`, `storage_updates: list[tuple[str, dict]]`, `storage_removes: list[str]`.

> **Plan note, attaching PBS/CIFS/NFS storage carries live credentials.**
> `POST /storage` with `type: "pbs"` takes a `password` and a `fingerprint`;
> CIFS takes `username` + `password`; NFS none. Those values pass **straight
> through to Proxmox and are never persisted by Proxploy**; there is no storage
> table (doc 04 defines none), these routes are synchronous so there is no
> `jobs.params` row, and the only thing that touches durable storage is the
> audit row, whose `params` go through `services/audit.py::redact`.
> `REDACT_SUBSTRINGS` already contains `"password"`, and `redact` recurses into
> nested dicts, so a nested `config.password` becomes `"[redacted]"` with no new
> redaction code. What still needs writing is the **proof**, Step 1's
> `test_pbs_attach_never_persists_or_echoes_the_password` asserts the secret is
> absent from the response body, absent from every `audit_events.params`,
> absent from `jobs`, and yet arrived at Proxmox verbatim. It is the
> storage-shaped sibling of `tests/test_no_secret_echo.py`'s repo-wide
> invariant. The routes also never echo `config` back, the responses return
> identifiers and, for PATCH, the *names* of the keys changed, mirroring the
> `settings.update` convention that audits key names but never values.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_storage_manage.py
"""Attach/edit/detach storage. Credentials pass through, never persist."""
import json

PBS_PASSWORD = "pbs-sup3r-s3cret-do-not-leak"


def _seed(app):
    from proxploy.models import Host, HostCredential

    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.9:8006", node_name="pve1",
                    status="connected", pve_version="8.4.1")
        db.add(host)
        db.commit()
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!store", "token_secret": "s3cret"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token",
                              encrypted_blob=blob, key_version=ver,
                              public_meta="proxploy@pve!store"))
        db.commit()
        return host.id


def _api(tmp_path, fake=None):
    from fastapi.testclient import TestClient
    from tests.support import make_app

    app = make_app(tmp_path, fake=fake)
    return app, TestClient(app), _seed(app)


def test_attach_creates_the_storage_upstream_and_audits(tmp_path, csrf_header,
                                                        bootstrap_admin):
    from proxploy.models import AuditEvent
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    app, c, hid = _api(tmp_path, fake=fake)
    with c:
        bootstrap_admin(c)
        r = c.post("/api/v1/storage",
                   json={"host_id": hid, "storage": "nfs-media", "type": "nfs",
                         "config": {"server": "10.0.0.30", "export": "/media",
                                    "content": "iso,vztmpl"}},
                   headers=csrf_header(c))
        assert r.status_code == 201
        assert r.json() == {"host_id": hid, "storage": "nfs-media", "type": "nfs"}
        assert fake.storage_creates == [{"storage": "nfs-media", "type": "nfs",
                                         "server": "10.0.0.30", "export": "/media",
                                         "content": "iso,vztmpl"}]
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="storage.create").one()
            assert row.target_type == "storage" and row.target_id == hid
            assert row.params["storage"] == "nfs-media"


def test_pbs_attach_never_persists_or_echoes_the_password(tmp_path, csrf_header,
                                                          bootstrap_admin):
    """The storage-shaped sibling of tests/test_no_secret_echo.py. A PBS attach
    is the one Phase 6 request body carrying a live credential; it must reach
    Proxmox verbatim and reach durable storage nowhere."""
    from proxploy.models import AuditEvent, Job
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    app, c, hid = _api(tmp_path, fake=fake)
    with c:
        bootstrap_admin(c)
        r = c.post("/api/v1/storage",
                   json={"host_id": hid, "storage": "pbs-main", "type": "pbs",
                         "config": {"server": "10.0.0.20", "datastore": "backups",
                                    "username": "proxploy@pbs",
                                    "password": PBS_PASSWORD,
                                    "fingerprint": "AA:BB:CC:DD"}},
                   headers=csrf_header(c))
        assert r.status_code == 201
        # 1. it reached Proxmox unmodified
        assert fake.storage_creates[0]["password"] == PBS_PASSWORD
        # 2. it is not in the response body (which echoes no config at all)
        assert PBS_PASSWORD not in r.text
        assert "config" not in r.json()
        with app.state.sessionmaker() as db:
            rows = db.query(AuditEvent).all()
            # 3. not in ANY audit row's params, and the nested key is masked
            assert PBS_PASSWORD not in json.dumps([x.params for x in rows])
            attach = next(x for x in rows if x.action == "storage.create")
            assert attach.params["config"]["password"] == "[redacted]"
            assert attach.params["config"]["server"] == "10.0.0.20"  # not over-redacted
            # 4. these routes are synchronous: no job row, so no jobs.params copy
            assert db.query(Job).count() == 0
        # 5. and it does not come back out of GET /audit either
        assert PBS_PASSWORD not in c.get("/api/v1/audit").text


def test_edit_sends_only_the_given_keys_and_audits_key_names(tmp_path, csrf_header,
                                                             bootstrap_admin):
    from proxploy.models import AuditEvent
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    app, c, hid = _api(tmp_path, fake=fake)
    with c:
        bootstrap_admin(c)
        r = c.patch(f"/api/v1/storage/{hid}/nfs-media",
                    json={"config": {"content": "iso,backup", "password": PBS_PASSWORD}},
                    headers=csrf_header(c))
        assert r.status_code == 200
        assert r.json() == {"host_id": hid, "storage": "nfs-media",
                            "updated": ["content", "password"]}
        assert PBS_PASSWORD not in r.text
        assert fake.storage_updates == [("nfs-media", {"content": "iso,backup",
                                                       "password": PBS_PASSWORD})]
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="storage.update").one()
            assert row.params["keys"] == ["content", "password"]
            assert PBS_PASSWORD not in json.dumps(row.params)


def test_detach_removes_upstream_and_audits(tmp_path, csrf_header, bootstrap_admin):
    from proxploy.models import AuditEvent
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    app, c, hid = _api(tmp_path, fake=fake)
    with c:
        bootstrap_admin(c)  # the bootstrap user is an OWNER
        r = c.delete(f"/api/v1/storage/{hid}/nfs-media", headers=csrf_header(c))
        assert r.status_code == 200
        assert r.json() == {"host_id": hid, "storage": "nfs-media", "detached": True}
        assert fake.storage_removes == ["nfs-media"]
        with app.state.sessionmaker() as db:
            assert db.query(AuditEvent).filter_by(action="storage.remove").count() == 1


def test_detach_is_owner_only_while_attach_is_admin(tmp_path, csrf_header,
                                                    bootstrap_admin):
    """Doc 05: POST/PATCH are admin, DELETE is owner; detaching is the one that
    can strand a guest's disks behind a removed definition."""
    from fastapi.testclient import TestClient
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    app, c, hid = _api(tmp_path, fake=fake)
    with c:
        bootstrap_admin(c)
        c.post("/api/v1/users",
               json={"email": "admin2@example.com", "password": "correct-horse-battery",
                     "display_name": "Admin Two", "role": "admin"},
               headers=csrf_header(c))
        c2 = TestClient(app)
        c2.post("/api/v1/auth/login",
                json={"email": "admin2@example.com", "password": "correct-horse-battery"},
                headers=csrf_header(c2))
        ok = c2.post("/api/v1/storage",
                     json={"host_id": hid, "storage": "dir-scratch", "type": "dir",
                           "config": {"path": "/mnt/scratch"}},
                     headers=csrf_header(c2))
        assert ok.status_code == 201
        denied = c2.delete(f"/api/v1/storage/{hid}/dir-scratch", headers=csrf_header(c2))
        assert denied.status_code == 403
        assert fake.storage_removes == []


def test_upstream_failure_is_a_502_that_leaks_no_secret(tmp_path, csrf_header,
                                                        bootstrap_admin):
    from tests.fakes.pve import FakePVE

    fake = FakePVE(fail=True)
    app, c, hid = _api(tmp_path, fake=fake)
    with c:
        bootstrap_admin(c)
        r = c.post("/api/v1/storage",
                   json={"host_id": hid, "storage": "pbs-main", "type": "pbs",
                         "config": {"server": "10.0.0.20", "datastore": "backups",
                                    "password": PBS_PASSWORD}},
                   headers=csrf_header(c))
        assert r.status_code == 502
        assert PBS_PASSWORD not in r.text
        assert "s3cret" not in r.text  # the host API token, scrubbed by _wrap
```

- [ ] **Step 2: Run to verify the failures**

Run: `cd backend && pytest tests/test_storage_manage.py -v`
Expected: FAIL, `POST /api/v1/storage` returns 405 (`""` is registered GET-only) and `PATCH`/`DELETE /api/v1/storage/{host_id}/{name}` return 405 too, so every assertion on `status_code == 201`/`200`/`403` fails.

- [ ] **Step 3: Add the three cluster-level `ProxmoxClient` methods**

Append to `class ProxmoxClient` in `backend/proxploy/services/proxmox.py`:

```python
    # --- storage definition management (Phase 6) ----------------------------
    # These three hit the CLUSTER-level /storage endpoints, not /nodes/{n}/…:
    # a storage definition lives in /etc/pve/storage.cfg and is cluster-wide.
    # They are SYNCHRONOUS: Proxmox returns no UPID, so there is nothing to
    # poll and these are plain route calls rather than jobs.
    #
    # `config` may carry a live credential (PBS `password`, CIFS `username`/
    # `password`). It is forwarded and forgotten: nothing here logs, stores or
    # returns it, and _wrap below scrubs only OUR token: the caller's secret
    # never enters an exception message because it is a request body, not a
    # header, and proxmoxer does not echo request bodies in its errors.

    def storage_create(self, config: dict) -> None:
        """POST /storage, `config` must include `storage` and `type`."""
        try:
            self._connect().storage.post(**config)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"attaching storage {config.get('storage')!r} failed",
                             e) from e

    def storage_update(self, storage: str, config: dict) -> None:
        """PUT /storage/{storage}, only the keys given are changed."""
        try:
            self._connect().storage(storage).put(**config)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"updating storage {storage!r} failed", e) from e

    def storage_remove(self, storage: str) -> None:
        """DELETE /storage/{storage}, drops the definition; upstream data stays."""
        try:
            self._connect().storage(storage).delete()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"detaching storage {storage!r} failed", e) from e
```

- [ ] **Step 4: Make FakePVE's root `.storage` callable and record the three mutations**

Task 1 wired a root `.storage` leaf serving `cluster_storage_rows` via `.get()`. Replace it with the factory below, which keeps `.get()` and adds `.post()` plus a callable drill-in. In `backend/tests/fakes/pve.py`:

```python
class _ClusterStorageLeaf:
    """root .storage(name), the cluster-level storage definition."""

    def __init__(self, owner, name):
        self._owner, self._name = owner, name

    def put(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.storage_updates.append((self._name, kwargs))
        return None

    def delete(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.storage_removes.append(self._name)
        return None


class _ClusterStorageFactory:
    """root .storage.get() lists definitions.post() creates one,
    calling it drills into a named definition. All three are synchronous in
    Proxmox and return no UPID, so none of them mints one here either."""

    def __init__(self, owner):
        self._owner = owner

    def get(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        return self._owner.cluster_storage_rows

    def post(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.storage_creates.append(kwargs)
        self._owner.cluster_storage_rows.append(dict(kwargs))
        return None

    def __call__(self, name):
        return _ClusterStorageLeaf(self._owner, name)
```

In `FakePVE.__init__`, the root storage attribute becomes the factory (replace whatever Task 1 wired) and the three recorders are added next to the Task 4 ones:

```python
        self.storage = _ClusterStorageFactory(self)
        # storage definition management (Phase 6)
        self.storage_creates: list[dict] = []
        self.storage_updates: list[tuple] = []
        self.storage_removes: list[str] = []
```

(`cluster_storage_rows` is Task 1's attribute and must be assigned **before** this line, since the factory reads it lazily but `post()` appends to it.)

- [ ] **Step 5: Add the three manage routes to `api/storage.py`**

Extend the import block of `backend/proxploy/api/storage.py` with pydantic and the audit writer, and add the owner singleton:

```python
from pydantic import BaseModel

from proxploy.services.audit import write_audit
```

```python
_require_owner = require_role("owner")


class StorageAttachIn(BaseModel):
    """`config` is a free-form passthrough because the key set is per-plugin
    (dir wants `path`, nfs wants `server`+`export`, pbs wants `server`+
    `datastore`+`username`+`password`+`fingerprint`) and Proxmox is the
    authority on what is valid, mirroring it here would be a second schema to
    keep in sync and a new way to reject a storage type Proxmox supports.
    It may carry a live credential; see the module note on where it does NOT go."""
    host_id: int
    storage: str
    type: str
    config: dict = {}


class StorageEditIn(BaseModel):
    config: dict
```

Append the three routes:

```python
@router.post("", status_code=201,
             dependencies=[Depends(_require_admin),
                           Depends(require_entitlement("storage.manage"))])
def attach_storage(request: Request, body: StorageAttachIn, db=Depends(get_db),
                   user: User = Depends(_require_admin)):
    """Attach a storage definition (doc 05 §Storage, doc 01 §5 "Add/edit storage").

    Synchronous: Proxmox returns no UPID for /storage, so there is no job and
    therefore no `jobs.params` row holding `body.config`. The audit row is the
    only durable trace, and write_audit runs it through redact(); nested
    `config.password` included.

    The response deliberately echoes NO config: a credential the caller just
    sent must not come back out of a GET the browser might cache or a screenshot
    someone pastes into a ticket.
    """
    host = _host_or_404(db, body.host_id)
    ip = request.client.host if request.client else None
    try:
        client_for_host(request.app, db, host).storage_create(
            {"storage": body.storage, "type": body.type, **body.config})
    except ProxmoxError as e:
        write_audit(db, actor_type="user", actor_id=user.id, action="storage.create",
                    target_type="storage", target_id=host.id,
                    params=body.model_dump(), result="error", ip=ip)
        raise HTTPException(502, str(e))
    write_audit(db, actor_type="user", actor_id=user.id, action="storage.create",
                target_type="storage", target_id=host.id,
                params=body.model_dump(), ip=ip)
    request.app.state.bus.publish("resource", {"type": "storage", "id": host.id,
                                               "change": "list"})
    return {"host_id": host.id, "storage": body.storage, "type": body.type}


@router.patch("/{host_id}/{name}",
              dependencies=[Depends(_require_admin),
                            Depends(require_entitlement("storage.manage"))])
def edit_storage(request: Request, host_id: int, name: str, body: StorageEditIn,
                 db=Depends(get_db), user: User = Depends(_require_admin)):
    """Audits the NAMES of the keys changed, never their values; the same rule
    settings.py::patch_settings follows, and the reason a rotated PBS password
    leaves a legible audit trail without leaving the password in it."""
    host = _host_or_404(db, host_id)
    keys = sorted(body.config)
    ip = request.client.host if request.client else None
    try:
        client_for_host(request.app, db, host).storage_update(name, body.config)
    except ProxmoxError as e:
        write_audit(db, actor_type="user", actor_id=user.id, action="storage.update",
                    target_type="storage", target_id=host.id,
                    params={"storage": name, "keys": keys}, result="error", ip=ip)
        raise HTTPException(502, str(e))
    write_audit(db, actor_type="user", actor_id=user.id, action="storage.update",
                target_type="storage", target_id=host.id,
                params={"storage": name, "keys": keys}, ip=ip)
    request.app.state.bus.publish("resource", {"type": "storage", "id": host.id,
                                               "change": "list"})
    return {"host_id": host.id, "storage": name, "updated": keys}


@router.delete("/{host_id}/{name}",
               dependencies=[Depends(_require_owner),
                             Depends(require_entitlement("storage.manage"))])
def detach_storage(request: Request, host_id: int, name: str, db=Depends(get_db),
                   user: User = Depends(_require_owner)):
    """Owner, not admin (doc 05): detaching drops the definition while guest
    disks keep pointing at it, which is the one action here that can strand
    running guests. Upstream data is left in place; this is not a wipe."""
    host = _host_or_404(db, host_id)
    ip = request.client.host if request.client else None
    try:
        client_for_host(request.app, db, host).storage_remove(name)
    except ProxmoxError as e:
        write_audit(db, actor_type="user", actor_id=user.id, action="storage.remove",
                    target_type="storage", target_id=host.id,
                    params={"storage": name}, result="error", ip=ip)
        raise HTTPException(502, str(e))
    write_audit(db, actor_type="user", actor_id=user.id, action="storage.remove",
                target_type="storage", target_id=host.id,
                params={"storage": name}, ip=ip)
    request.app.state.bus.publish("resource", {"type": "storage", "id": host.id,
                                               "change": "list"})
    return {"host_id": host.id, "storage": name, "detached": True}
```

Route ordering inside this router is safe as written: `POST ""` is one segment and `PATCH`/`DELETE /{host_id}/{name}` are two, so nothing shadows anything, and the three-segment `…/content` routes from Task 4 are longer still. (`{name}` never matches a `/`, which is exactly why Task 4's volid parameter needed `:path`.)

- [ ] **Step 6: Run the manage tests to verify they pass**

Run: `cd backend && pytest tests/test_storage_manage.py -v`
Expected: PASS (6 tests).

- [ ] **Step 7: Re-run the repo-wide secret and auth invariants explicitly**

Run: `cd backend && pytest tests/test_no_secret_echo.py tests/test_route_auth_invariant.py tests/test_audit.py tests/test_audit_api.py -v`
Expected: PASS. `test_route_auth_invariant` now probes `POST /api/v1/storage`, `PATCH` and `DELETE /api/v1/storage/{host_id}/{name}` anonymously with `_features = {}` and must get 401 on all three; a 403 means the `require_entitlement("storage.manage")` was listed before the role singleton.

- [ ] **Step 8: Run the full backend suite**

Run: `cd backend && pytest tests/ -q -m "not pve_integration and not e2e"`
Expected: PASS, up by exactly 6 tests versus the Task 4 total; `2 skipped, 3 deselected` unchanged.

- [ ] **Step 9: Commit**

```bash
git add backend/proxploy/services/proxmox.py backend/proxploy/api/storage.py \
        backend/tests/fakes/pve.py backend/tests/test_storage_manage.py
git commit -m "feat(storage): attach/edit/detach storage definitions with credential-safe audit"
```

---

## Task 6: Network reads + guest NIC read/edit

**Files:**
- Create: `backend/proxploy/services/netconfig.py`, `backend/proxploy/api/network.py`
- Modify: `backend/proxploy/services/proxmox.py`, `backend/proxploy/api/__init__.py`, `backend/proxploy/api/vms.py`, `backend/proxploy/api/apps.py`, `backend/tests/fakes/pve.py`
- Test: `backend/tests/test_netconfig.py`, `backend/tests/test_network_api.py`

**Interfaces:**
- Consumes: Task 1's `proxploy/services/hostclient.py::client_for_host(app, db, host) -> ProxmoxClient`, `ProxmoxClient.node_networks(node, iface_type=None) -> list[dict]`, `ProxmoxClient.guest_config(kind, node, vmid) -> dict`, and Task 1's `FakePVE.networks_by_node: dict[node, list[dict]]` / `FakePVE.guest_configs: dict[tuple[kind, vmid], dict]`. Also `proxploy.services.metrics::pick_resolution/query_series` (the exact pair `api/metrics.py::metrics_query` already uses; there is no second metrics reader in this codebase and this task does not add one), `api/deps.py::get_db/require_role/require_entitlement`, `services/audit.py::write_audit`.
- Produces:
  - `proxploy/services/netconfig.py::parse_net(value: str) -> dict`, `build_net(parts: dict) -> str`, `nic_identity(parts: dict) -> dict`
  - `ProxmoxClient.guest_config_update(kind: str, node: str, vmid: int, config: dict) -> str | None`
  - `proxploy/api/network.py` → `router = APIRouter(prefix="/network", tags=["network"])` with `GET /api/v1/network/bridges?host=` and `GET /api/v1/network/throughput?hours=`, plus the two shared helpers `guest_nics(request, db, host, kind, vmid) -> list[dict]` and `set_guest_nic(request, db, user, *, target_type, target_id, host, kind, vmid, iface, body: NicIn) -> dict` and the `NicIn` pydantic model, all three imported by `api/apps.py` and `api/vms.py`
  - `GET /api/v1/apps/{app_id}/network`, `PUT /api/v1/apps/{app_id}/network/{iface}`, `GET /api/v1/vms/{vm_id}/network`, `PUT /api/v1/vms/{vm_id}/network/{iface}`; declared in `apps.py`/`vms.py` **above** their `/{id}/{action}` wildcards

- [ ] **Step 1: Write the failing round-trip test for `netconfig`**

The whole correctness burden of this task is here. A guest's MAC address lives
inside the `netN=` head token (`virtio=AA:BB:CC:DD:EE:FF`), not in a separate
key. Any parser that models a NIC as "model + bridge + tag + firewall" and
rebuilds the string from those four fields silently drops the MAC; Proxmox then
mints a fresh random one on the next start, and every DHCP reservation, static
lease and MAC-bound software licence pointed at that guest breaks. The test
below is the guard: unknown keys and the head token survive byte-for-byte.

```python
# backend/tests/test_netconfig.py
"""netN= round-tripping (doc 01 §6 guest network config).

The MAC lives in the head token, `virtio=AA:BB:CC:DD:EE:FF`, so a parser
that keeps only the keys it understands and rebuilds from those loses it.
These are the strings PVE actually emits; every one must survive
build_net(parse_net(s)) == s exactly.
"""
import pytest

from proxploy.services.netconfig import build_net, nic_identity, parse_net

REAL_WORLD = [
    # plain qemu virtio NIC
    "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0",
    # VLAN-tagged + firewalled
    "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0,tag=10,firewall=1",
    # intel model, rate limited, jumbo frames
    "e1000=DE:AD:BE:EF:00:01,bridge=vmbr1,rate=12.5,mtu=9000",
    # multiqueue + admin-down link
    "virtio=52:54:00:12:34:56,bridge=vmbr0,queues=8,link_down=1",
    # every awkward key at once, in PVE's own order
    "vmxnet3=00:0C:29:AB:CD:EF,bridge=vmbr2,tag=4094,firewall=0,"
    "mtu=1400,rate=1,queues=4,link_down=0",
    # lxc shape: no model=MAC head token at all
    "name=eth0,bridge=vmbr0,firewall=1,hwaddr=BC:24:11:00:11:22,ip=dhcp,type=veth",
    # lxc with a static v4 + v6 and a gateway (colons and slashes in values)
    "name=eth0,bridge=vmbr0,hwaddr=BC:24:11:AA:BB:CC,ip=10.0.0.9/24,"
    "gw=10.0.0.1,ip6=fd00::9/64,type=veth",
]


@pytest.mark.parametrize("s", REAL_WORLD)
def test_round_trip_is_byte_for_byte(s):
    assert build_net(parse_net(s)) == s


@pytest.mark.parametrize("s", REAL_WORLD)
def test_round_trip_is_idempotent(s):
    once = build_net(parse_net(s))
    assert build_net(parse_net(once)) == once


def test_head_token_carries_the_mac_and_is_never_regenerated():
    parts = parse_net("virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0,tag=10")
    assert parts["virtio"] == "AA:BB:CC:DD:EE:FF"
    # editing an unrelated key must not disturb it
    parts["tag"] = "20"
    assert build_net(parts) == "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0,tag=20"


def test_unknown_keys_survive_an_edit():
    """A future PVE release adding `foo=bar` must not lose it on a bridge change."""
    parts = parse_net("virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0,foo=bar,queues=4")
    parts["bridge"] = "vmbr9"
    assert build_net(parts) == "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr9,foo=bar,queues=4"


def test_key_order_is_preserved_not_sorted():
    s = "virtio=AA:BB:CC:DD:EE:FF,tag=10,bridge=vmbr0"
    assert build_net(parse_net(s)) == s  # would fail if the dict were sorted


def test_valueless_token_survives():
    """PVE has emitted bare flags before; a bare token must not become `k=`."""
    assert build_net(parse_net("virtio=AA:BB:CC:DD:EE:FF,trunks")) == \
        "virtio=AA:BB:CC:DD:EE:FF,trunks"


def test_nic_identity_reads_qemu_and_lxc_shapes():
    q = nic_identity(parse_net("virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0"))
    assert q == {"model": "virtio", "macaddr": "AA:BB:CC:DD:EE:FF"}
    c = nic_identity(parse_net("name=eth0,bridge=vmbr0,hwaddr=BC:24:11:00:11:22,type=veth"))
    assert c == {"model": "veth", "macaddr": "BC:24:11:00:11:22"}
```

- [ ] **Step 2: Run to verify the failure**

Run: `cd backend && python -m pytest tests/test_netconfig.py -q`
Expected: FAIL at collection, `ModuleNotFoundError: No module named 'proxploy.services.netconfig'`.

- [ ] **Step 3: Write `services/netconfig.py`**

```python
# backend/proxploy/services/netconfig.py
"""The `netN=` string round-tripper (doc 01 §6 "Guest network config").

Proxmox stores a guest NIC as one comma-joined `k=v` string, and the NIC model
and its MAC address share a single head token: `virtio=AA:BB:CC:DD:EE:FF`.
That is the whole reason this module exists. Editing a NIC means read the
string, change one key, write the string back; never rebuild it from a typed
struct, because anything the struct does not model (the MAC, `queues`, an
option a future PVE adds) would be dropped, and a dropped MAC means Proxmox
mints a new random one at next start, breaking every DHCP reservation and
MAC-bound licence pointed at that guest.

So: parse to an ORDER-PRESERVING dict of raw strings, mutate that dict, join it
back. No key is interpreted, no value is normalised, nothing is sorted.
`build_net(parse_net(s)) == s` for every string PVE emits (tests/test_netconfig.py).
"""
from __future__ import annotations

# The qemu NIC models PVE accepts. Used ONLY to recognise which token is the
# model=MAC head token when reporting a NIC's identity to the UI: never to
# validate or rewrite it.
QEMU_MODELS = frozenset({
    "virtio", "e1000", "e1000-82540em", "e1000-82544gc", "e1000-82545em",
    "e1000e", "i82551", "i82557b", "i82559er", "ne2k_isa", "ne2k_pci",
    "pcnet", "rtl8139", "vmxnet3",
})


def parse_net(value: str) -> dict:
    """`"virtio=AA:BB,bridge=vmbr0"` -> `{"virtio": "AA:BB", "bridge": "vmbr0"}`.

    Insertion order is the file order. A token with no `=` maps to None so
    build_net can emit it bare again rather than as `token=`.
    """
    parts: dict[str, str | None] = {}
    for token in value.split(","):
        if not token:
            continue
        key, sep, val = token.partition("=")
        parts[key] = val if sep else None
    return parts


def build_net(parts: dict) -> str:
    """The exact inverse of parse_net, in dict order."""
    return ",".join(k if v is None else f"{k}={v}" for k, v in parts.items())


def nic_identity(parts: dict) -> dict:
    """-> {"model", "macaddr"} for both flavours.

    qemu puts them in one head token (`virtio=AA:BB:...`); lxc splits them
    across `type=veth` and `hwaddr=`. Read-only, neither value is ever
    written back by this module's callers.
    """
    for key, val in parts.items():
        if key in QEMU_MODELS:
            return {"model": key, "macaddr": val}
    return {"model": parts.get("type") or "veth", "macaddr": parts.get("hwaddr")}
```

- [ ] **Step 4: Run to verify the round-trip passes**

Run: `cd backend && python -m pytest tests/test_netconfig.py -q`
Expected: PASS, 21 passed (7 parametrised × 2 + 7 unparametrised).

- [ ] **Step 5: Add `ProxmoxClient.guest_config_update`**

In `backend/proxploy/services/proxmox.py`, directly below `guest_action` (it
belongs with the other per-guest, user-triggered calls, above `task_status`):

```python
    def guest_config_update(self, kind: str, node: str, vmid: int,
                            config: dict) -> str | None:
        """PUT /nodes/{node}/{lxc|qemu}/{vmid}/config -> UPID or None.

        NOT long-running: PVE writes the config file synchronously. A RUNNING
        qemu guest is the one case that returns a UPID, the change lands in
        the guest's pending-config section and PVE spawns a tiny task to record
        it; the guest itself only picks it up at next boot. A stopped guest or
        an lxc guest returns None and the write is already effective. Callers
        surface that difference rather than pretending it is a job.
        """
        try:
            return getattr(self._connect().nodes(node), kind)(vmid).config.put(**config)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"config update failed for {kind}/{vmid} on {node}", e) from e
```

- [ ] **Step 6: Teach FakePVE's guest-config leaf to accept a `.put()`**

Task 1 added a `_ConfigLeaf` with a `.get()` served from
`FakePVE.guest_configs` (keyed `(kind, vmid)`). Replace that class in
`backend/tests/fakes/pve.py` with the version below and add the two new
attributes to `FakePVE.__init__`:

```python
class _ConfigLeaf:
    """nodes(n).lxc(vmid).config / .qemu(vmid).config.get() reads.put() records."""

    def __init__(self, owner, kind, node, vmid):
        self._owner, self._kind, self._node, self._vmid = owner, kind, node, vmid

    def get(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        return dict(self._owner.guest_configs.get((self._kind, self._vmid), {}))

    def put(self, **cfg):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.config_updates.append((self._kind, self._vmid, dict(cfg)))
        self._owner.guest_configs.setdefault((self._kind, self._vmid), {}).update(cfg)
        return self._owner.config_update_upid
```

In `FakePVE.__init__`, next to the Task-1 `self.guest_configs = ...` line:

```python
        # guest config writes (Phase 6 Task 6)
        self.config_updates: list[tuple[str, int, dict]] = []
        self.config_update_upid: str | None = None
```

- [ ] **Step 7: Write the failing network-API tests**

```python
# backend/tests/test_network_api.py
"""Network reads + guest NIC read/edit (doc 05 §Network, doc 01 §6)."""
import json

from fastapi.testclient import TestClient

from proxploy.models import App, AuditEvent, Host, HostCredential, Job, MetricSample, Vm

NETWORKS = {
    "pve1": [
        {"iface": "vmbr0", "type": "bridge", "method": "static",
         "address": "10.0.0.9", "netmask": "255.255.255.0", "cidr": "10.0.0.9/24",
         "gateway": "10.0.0.1", "bridge_ports": "bond0", "bridge_vlan_aware": 1,
         "active": 1, "autostart": 1, "comments": "management"},
        {"iface": "bond0", "type": "bond", "method": "manual",
         "slaves": "enp1s0 enp2s0", "active": 1, "autostart": 1},
        {"iface": "enp1s0", "type": "eth", "method": "manual", "active": 1},
        {"iface": "vmbr0.10", "type": "vlan", "method": "manual",
         "vlan-id": 10, "vlan-raw-device": "vmbr0", "active": 1},
    ],
}


def _seed(app, *, ct_net="virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0,tag=10,firewall=1"):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.9:8006", node_name="pve1",
                    status="connected", pve_version="8.4.1")
        db.add(host)
        db.commit()
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!net", "token_secret": "s3cret"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token",
                              encrypted_blob=blob, key_version=ver))
        a = App(host_id=host.id, ctid=150, name="Immich", slug="immich")
        v = Vm(host_id=host.id, vmid=201, name="win11", status="running")
        db.add_all([a, v])
        db.commit()
        return host.id, a.id, v.id


def _fake():
    from tests.fakes.pve import FakePVE

    f = FakePVE()
    f.networks_by_node = dict(NETWORKS)
    f.guest_configs = {
        ("lxc", 150): {"hostname": "immich",
                       "net0": "name=eth0,bridge=vmbr0,hwaddr=BC:24:11:00:11:22,"
                               "ip=dhcp,type=veth"},
        ("qemu", 201): {"name": "win11",
                        "net0": "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0,tag=10,firewall=1",
                        "net1": "e1000=DE:AD:BE:EF:00:01,bridge=vmbr1,mtu=9000"},
    }
    return f


def test_bridges_is_a_live_passthrough_with_an_attachment_map(tmp_path, csrf_header,
                                                              bootstrap_admin):
    from tests.support import make_app, seed_snapshot

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id, app_id, vm_id = _seed(app)
        seed_snapshot(app, host_id, nodes=[{"node": "pve1", "status": "online"}])
        r = c.get("/api/v1/network/bridges")
        assert r.status_code == 200
        body = r.json()
        node = body["nodes"][0]
        assert node["node"] == "pve1" and node["host_id"] == host_id
        kinds = {i["iface"]: i["type"] for i in node["interfaces"]}
        assert kinds == {"vmbr0": "bridge", "bond0": "bond",
                         "enp1s0": "eth", "vmbr0.10": "vlan"}
        br = next(i for i in node["interfaces"] if i["iface"] == "vmbr0")
        assert br["cidr"] == "10.0.0.9/24" and br["bridge_ports"] == "bond0"
        assert br["vlan_aware"] is True and br["active"] is True
        # guest attachment map, from per-guest config reads
        att = {(x["guest_type"], x["iface"]): x for x in body["attachments"]}
        assert att[("app", "net0")]["bridge"] == "vmbr0"
        assert att[("app", "net0")]["macaddr"] == "BC:24:11:00:11:22"
        assert att[("vm", "net0")]["tag"] == 10
        assert att[("vm", "net1")]["bridge"] == "vmbr1"


def test_bridges_filters_by_host(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app, seed_snapshot

    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id, _, _ = _seed(app)
        seed_snapshot(app, host_id, nodes=[{"node": "pve1", "status": "online"}])
        assert c.get(f"/api/v1/network/bridges?host={host_id}").json()["nodes"]
        assert c.get(f"/api/v1/network/bridges?host={host_id + 99}").json()["nodes"] == []


def test_throughput_reads_the_existing_host_metric_series(tmp_path, csrf_header,
                                                          bootstrap_admin):
    """Same MetricsStore rows /metrics/query serves, no second reader."""
    from proxploy.models import utcnow
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id, _, _ = _seed(app)
        now = utcnow()
        with app.state.sessionmaker() as db:
            for i in range(3):
                db.add(MetricSample(target_type="host", target_id=host_id,
                                    metric="net_in_bps", value=100.0 + i, ts=now))
                db.add(MetricSample(target_type="host", target_id=host_id,
                                    metric="net_out_bps", value=10.0 + i, ts=now))
            db.commit()
        r = c.get("/api/v1/network/throughput?hours=1")
        assert r.status_code == 200
        body = r.json()
        assert body["resolution"] == "raw"
        h = body["hosts"][0]
        assert h["host_id"] == host_id and h["host_name"] == "host-01"
        assert h["in"]["value"] == [100.0, 101.0, 102.0]
        assert h["out"]["value"] == [10.0, 11.0, 12.0]


def test_guest_network_read_lists_every_nic(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, app_id, vm_id = _seed(app)
        nics = c.get(f"/api/v1/vms/{vm_id}/network").json()
        assert [n["iface"] for n in nics] == ["net0", "net1"]
        assert nics[0]["model"] == "virtio"
        assert nics[0]["macaddr"] == "AA:BB:CC:DD:EE:FF"
        assert nics[0]["tag"] == 10 and nics[0]["firewall"] is True
        assert nics[1]["mtu"] == "9000"
        ct = c.get(f"/api/v1/apps/{app_id}/network").json()
        assert ct[0]["macaddr"] == "BC:24:11:00:11:22" and ct[0]["model"] == "veth"


def test_guest_nic_edit_preserves_the_mac_and_unknown_keys(tmp_path, csrf_header,
                                                           bootstrap_admin):
    """The regression this whole task exists to prevent."""
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, _, vm_id = _seed(app)
        r = c.put(f"/api/v1/vms/{vm_id}/network/net1",
                  json={"bridge": "vmbr7", "tag": 42}, headers=csrf_header(c))
        assert r.status_code == 200, r.text
        assert r.json()["value"] == \
            "e1000=DE:AD:BE:EF:00:01,bridge=vmbr7,mtu=9000,tag=42"
        assert fake.config_updates == [
            ("qemu", 201, {"net1": "e1000=DE:AD:BE:EF:00:01,bridge=vmbr7,mtu=9000,tag=42"})]


def test_guest_nic_edit_can_clear_a_key_with_an_explicit_null(tmp_path, csrf_header,
                                                              bootstrap_admin):
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, _, vm_id = _seed(app)
        r = c.put(f"/api/v1/vms/{vm_id}/network/net0", json={"tag": None},
                  headers=csrf_header(c))
        assert r.json()["value"] == "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0,firewall=1"


def test_guest_nic_edit_is_not_a_job_and_reports_pending(tmp_path, csrf_header,
                                                         bootstrap_admin):
    """A config PUT is not long-running. It returns directly, with the UPID PVE
    handed back for a running qemu guest and an honest pending-until-reboot flag."""
    from tests.support import make_app

    fake = _fake()
    fake.config_update_upid = "UPID:pve1:00001234:...:qmconfig:201:proxploy@pve:"
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, _, vm_id = _seed(app)
        r = c.put(f"/api/v1/vms/{vm_id}/network/net0", json={"bridge": "vmbr3"},
                  headers=csrf_header(c))
        assert r.status_code == 200
        body = r.json()
        assert body["upid"] == fake.config_update_upid
        assert body["pending_reboot"] is True
        assert "reboot" in body["detail"].lower()
        with app.state.sessionmaker() as db:
            assert db.query(Job).count() == 0  # NOT a job


def test_guest_nic_edit_audits_without_a_job_id(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, app_id, _ = _seed(app)
        c.put(f"/api/v1/apps/{app_id}/network/net0", json={"bridge": "vmbr5"},
              headers=csrf_header(c))
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="network.guest_config").one()
            assert row.target_type == "app" and row.target_id == app_id
            assert row.job_id is None
            assert row.params["iface"] == "net0" and row.params["bridge"] == "vmbr5"


def test_unknown_iface_is_404_not_a_new_nic(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, _, vm_id = _seed(app)
        r = c.put(f"/api/v1/vms/{vm_id}/network/net9", json={"bridge": "vmbr0"},
                  headers=csrf_header(c))
        assert r.status_code == 404


def test_network_routes_are_registered_above_the_lifecycle_wildcards(tmp_path):
    """Starlette matches in registration order (apps.py:266-271). If
    /{id}/network lands after /{id}/{action}, the wildcard eats it and the
    action string arrives as "network"."""
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())
    paths = [r.path for r in app.routes if hasattr(r, "path")]
    assert paths.index("/api/v1/vms/{vm_id}/network") < \
        paths.index("/api/v1/vms/{vm_id}/{action}")
    assert paths.index("/api/v1/vms/{vm_id}/network/{iface}") < \
        paths.index("/api/v1/vms/{vm_id}/{action}")
    assert paths.index("/api/v1/apps/{app_id}/network") < \
        paths.index("/api/v1/apps/{app_id}/{action}")
    assert paths.index("/api/v1/apps/{app_id}/network/{iface}") < \
        paths.index("/api/v1/apps/{app_id}/{action}")


def test_put_network_does_not_enqueue_a_lifecycle_job(tmp_path, csrf_header,
                                                      bootstrap_admin):
    """The behavioural half of the ordering assertion above: if the wildcard
    swallowed this, we would get a 422 "action must be one of ..." or a queued
    lifecycle job instead of a config write."""
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, _, vm_id = _seed(app)
        r = c.put(f"/api/v1/vms/{vm_id}/network/net0", json={"bridge": "vmbr4"},
                  headers=csrf_header(c))
        assert r.status_code == 200
        assert "action must be one of" not in r.text
        with app.state.sessionmaker() as db:
            assert db.query(Job).count() == 0
        assert fake.actions == []  # no guest_action ever reached PVE


def test_missing_session_is_401_not_403(tmp_path, csrf_header):
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        _, _, vm_id = _seed(app)
        assert c.get("/api/v1/network/bridges").status_code == 401
        assert c.put(f"/api/v1/vms/{vm_id}/network/net0", json={"bridge": "vmbr0"},
                     headers=csrf_header(c)).status_code == 401
```

- [ ] **Step 8: Run to verify the failures**

Run: `cd backend && python -m pytest tests/test_network_api.py -q`
Expected: FAIL, every test errors with `404 Not Found` on
`/api/v1/network/bridges` and `/api/v1/vms/{id}/network`, and
`test_network_routes_are_registered_above_the_lifecycle_wildcards` fails with
`ValueError: '/api/v1/vms/{vm_id}/network' is not in list`.

- [ ] **Step 9: Write `api/network.py` (the read half)**

```python
# backend/proxploy/api/network.py
"""Network reads + guest NIC edit (doc 05 §Network, doc 01 §6).

Doc 05 calls /network/bridges a "live passthrough" and this is exactly that:
no model, no cache, no migration; one GET /nodes/{node}/network per node of
the requested host(s), served straight back. Throughput is the opposite: it is
NOT a passthrough, it comes from the `host` target's existing `net_in_bps` /
`net_out_bps` MetricSample rows the poller has been writing since Phase 2,
read through services/metrics.py::query_series, the same reader
api/metrics.py::metrics_query uses. There is deliberately no second metrics
path in this codebase.

Deviation from doc 05 recorded in the phase notes: doc 05 leaves the
entitlement column blank on both GETs. Doc 01 §6 defines `network.view` as a
real feature with a real key and doc 07 §3 says a feature without a key does
not merge, so both reads are gated on it. Functionally identical today (the
key defaults ON).
"""
from __future__ import annotations

import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from proxploy.api.deps import get_db, require_entitlement, require_role
from proxploy.models import App, Host, User, Vm, utcnow
from proxploy.services.audit import write_audit
from proxploy.services.hostclient import client_for_host
from proxploy.services.metrics import pick_resolution, query_series
from proxploy.services.netconfig import build_net, nic_identity, parse_net

router = APIRouter(prefix="/network", tags=["network"])

# Singletons first in dependencies=[...] and reused as the parameter dep, so
# auth/role runs before the entitlement gate and FastAPI collapses the two
# (deps.py idiom; test_route_auth_invariant.py enforces it).
_require_viewer = require_role("viewer")
_require_operator = require_role("operator")

NET_KEY = re.compile(r"^net\d+$")

# Keys a NIC edit may touch. The head token (model=MAC) and everything else in
# the string is passed through untouched by netconfig: see that module.
EDITABLE = ("bridge", "tag", "firewall", "rate", "mtu", "link_down")


class NicIn(BaseModel):
    """Every field optional; only fields PRESENT in the request body are
    applied, and an explicit null removes the key (that is how a VLAN tag or a
    rate limit is cleared). Absent != null here, hence exclude_unset below."""
    bridge: str | None = None
    tag: int | None = None
    firewall: bool | None = None
    rate: float | None = None
    mtu: int | None = None
    link_down: bool | None = None


def _nic_out(iface: str, raw: str) -> dict:
    parts = parse_net(raw)
    return {
        "iface": iface, "raw": raw, **nic_identity(parts),
        "bridge": parts.get("bridge"),
        "tag": int(parts["tag"]) if parts.get("tag") else None,
        "firewall": parts.get("firewall") == "1",
        "rate": parts.get("rate"), "mtu": parts.get("mtu"),
        "link_down": parts.get("link_down") == "1",
    }


def guest_nics(request: Request, db, host: Host, kind: str, vmid: int) -> list[dict]:
    """Every netN on one guest, newest PVE config read (no cache)."""
    cfg = client_for_host(request.app, db, host).guest_config(kind, host.node_name or "", vmid)
    return [_nic_out(k, str(cfg[k])) for k in sorted(cfg) if NET_KEY.match(k)]


def set_guest_nic(request: Request, db, user: User, *, target_type: str,
                  target_id: int, host: Host, kind: str, vmid: int,
                  iface: str, body: NicIn) -> dict:
    """Read-modify-write one netN. NOT a job, see ProxmoxClient.guest_config_update."""
    if not NET_KEY.match(iface):
        raise HTTPException(422, "iface must look like net0")
    node = host.node_name or ""
    client = client_for_host(request.app, db, host)
    cfg = client.guest_config(kind, node, vmid)
    if iface not in cfg:
        raise HTTPException(404, f"{iface} is not configured on this guest")
    parts = parse_net(str(cfg[iface]))
    changes = body.model_dump(exclude_unset=True)
    for key, val in changes.items():
        if val is None:
            parts.pop(key, None)
        elif isinstance(val, bool):
            parts[key] = "1" if val else "0"
        else:
            parts[key] = str(val)
    value = build_net(parts)
    upid = client.guest_config_update(kind, node, vmid, {iface: value})
    write_audit(db, actor_type="user", actor_id=user.id, action="network.guest_config",
                target_type=target_type, target_id=target_id,
                params={"iface": iface, **changes},
                ip=request.client.host if request.client else None)
    return {
        "iface": iface, "value": value, "upid": upid,
        "pending_reboot": upid is not None,
        # Honest, not reassuring: PVE handed back a UPID, which for a config
        # write means it filed the change under the guest's PENDING section.
        # The running guest still has the old NIC.
        "detail": ("Proxmox recorded this as a pending change, the guest keeps its "
                   "current NIC until it is rebooted (a shutdown/start, not a reset)."
                   if upid is not None else
                   "Applied immediately; no reboot needed."),
    }


def _nodes_of(request: Request, host: Host) -> list[str]:
    snap = request.app.state.poller.snapshots.get(host.id)
    names = [n["node"] for n in (snap.nodes if snap else []) if n.get("node")]
    return names or ([host.node_name] if host.node_name else [])


def _iface_out(row: dict) -> dict:
    return {
        "iface": row.get("iface"), "type": row.get("type"),
        "method": row.get("method"), "address": row.get("address"),
        "netmask": row.get("netmask"), "cidr": row.get("cidr"),
        "gateway": row.get("gateway"), "bridge_ports": row.get("bridge_ports"),
        "slaves": row.get("slaves"),
        "vlan_aware": bool(row.get("bridge_vlan_aware")),
        "vlan_id": row.get("vlan-id"), "vlan_raw_device": row.get("vlan-raw-device"),
        "active": bool(row.get("active")), "autostart": bool(row.get("autostart")),
        "comments": row.get("comments"),
    }


@router.get("/bridges", dependencies=[Depends(_require_viewer),
                                      Depends(require_entitlement("network.view"))])
def list_bridges(request: Request, host: int | None = None, db=Depends(get_db),
                 user: User = Depends(_require_viewer)):
    """Bridges/bonds/VLANs/physical NICs per node + the guest attachment map.

    # ponytail: the attachment map costs one guest_config read per adopted app
    # and VM on the host: fine for a homelab, linear in guest count for a
    # 200-guest fleet. This is a human-triggered route, explicitly outside the
    # poller's O(nodes) budget (proxmox.py's "per-guest, user-triggered calls"
    # section). If it ever gets slow, cache netN in the poller's cluster_resources
    # pass; do not add per-guest calls to the poll loop to get it.
    """
    hosts = [h for h in db.query(Host).order_by(Host.name).all()
             if host is None or h.id == host]
    nodes, attachments = [], []
    for h in hosts:
        client = client_for_host(request.app, db, h)
        for node in _nodes_of(request, h):
            nodes.append({"host_id": h.id, "host_name": h.name, "node": node,
                          "interfaces": [_iface_out(r) for r in client.node_networks(node)]})
        node = h.node_name or ""
        guests = ([("app", a.id, a.name, "lxc", a.ctid)
                   for a in db.query(App).filter_by(host_id=h.id).order_by(App.name)]
                  + [("vm", v.id, v.name, "qemu", v.vmid)
                     for v in db.query(Vm).filter_by(host_id=h.id).order_by(Vm.name)])
        for gtype, gid, gname, kind, vmid in guests:
            cfg = client.guest_config(kind, node, vmid)
            for key in sorted(k for k in cfg if NET_KEY.match(k)):
                attachments.append({"host_id": h.id, "node": node,
                                    "guest_type": gtype, "guest_id": gid,
                                    "name": gname, "vmid": vmid,
                                    **_nic_out(key, str(cfg[key]))})
    return {"nodes": nodes, "attachments": attachments}


@router.get("/throughput", dependencies=[Depends(_require_viewer),
                                         Depends(require_entitlement("network.view"))])
def throughput(request: Request, hours: int = 1, db=Depends(get_db),
               user: User = Depends(_require_viewer)):
    """Per-host in/out series from the MetricsStore rows the poller already writes.

    Same reader as /metrics/query (services/metrics.py::query_series); this
    endpoint only exists so the Network page can ask for both metrics across
    every host in one round trip instead of 2N.
    """
    if not 1 <= hours <= 48:
        raise HTTPException(422, "hours must be between 1 and 48")
    to_dt = utcnow()
    frm_dt = to_dt - timedelta(hours=hours)
    res = pick_resolution(frm_dt, to_dt)
    out = []
    for h in db.query(Host).order_by(Host.name).all():
        out.append({
            "host_id": h.id, "host_name": h.name,
            "in": query_series(db, "host", h.id, "net_in_bps", frm_dt, to_dt, res),
            "out": query_series(db, "host", h.id, "net_out_bps", frm_dt, to_dt, res),
        })
    return {"hours": hours, "resolution": res, "hosts": out}
```

- [ ] **Step 10: Register the router**

In `backend/proxploy/api/__init__.py`, add `network` to the import tuple
(alphabetical, between `metrics` and `notifications`) and add the include below
`metrics`:

```python
from proxploy.api import (apps, audit, auth, catalog, cluster, consoles, entitlements,
                          events, hosts, jobs, meta, metrics, network, notifications,
                          settings, vms)
...
api_router.include_router(metrics.router)
api_router.include_router(network.router)
```

- [ ] **Step 11: Add the guest NIC routes to `api/vms.py`, ABOVE the wildcard**

In `backend/proxploy/api/vms.py`, add the imports and insert these two routes
**between `vm_detail` and the `_require_operator = require_role("operator")`
line that precedes `vm_lifecycle`**, i.e. above `POST /{vm_id}/{action}`:

```python
from proxploy.api.network import NicIn, guest_nics, set_guest_nic
```

```python
_require_viewer = require_role("viewer")
_require_operator = require_role("operator")


def _vm_and_host(db, vm_id: int):
    v = db.get(Vm, vm_id)
    if v is None:
        raise HTTPException(404, "vm not found")
    host = db.get(Host, v.host_id)
    if host is None:
        raise HTTPException(404, "host not found")
    return v, host


# Registered ABOVE the /{vm_id}/{action} wildcard below: Starlette matches in
# registration order, and although that wildcard is POST-only today, doc 05's
# future two-segment siblings are not. Same WARNING as apps.py:266-271.
# test_network_api.py asserts this ordering by route index.
@router.get("/{vm_id}/network",
            dependencies=[Depends(_require_viewer),
                          Depends(require_entitlement("network.guest_config"))])
def vm_network(request: Request, vm_id: int, db=Depends(get_db),
               user: User = Depends(_require_viewer)):
    v, host = _vm_and_host(db, vm_id)
    return guest_nics(request, db, host, "qemu", v.vmid)


@router.put("/{vm_id}/network/{iface}",
            dependencies=[Depends(_require_operator),
                          Depends(require_entitlement("network.guest_config"))])
def vm_network_update(request: Request, vm_id: int, iface: str, body: NicIn,
                      db=Depends(get_db), user: User = Depends(_require_operator)):
    v, host = _vm_and_host(db, vm_id)
    return set_guest_nic(request, db, user, target_type="vm", target_id=v.id,
                         host=host, kind="qemu", vmid=v.vmid, iface=iface, body=body)
```

Delete the now-duplicated `_require_operator = require_role("operator")` line
that sat just above `vm_lifecycle` (its comment stays with the block above).

- [ ] **Step 12: Add the same two routes to `api/apps.py`, above ITS wildcard**

In `backend/proxploy/api/apps.py`, add the import and insert the block
**immediately after `list_app_script_versions` and before `class LifecycleIn`**
(so it is above the `POST /{app_id}/{action}` WARNING block):

```python
from proxploy.api.network import NicIn, guest_nics, set_guest_nic
```

```python
_require_viewer = require_role("viewer")


def _app_and_host(db, app_id: int):
    a = db.get(App, app_id)
    if a is None:
        raise HTTPException(404, "app not found")
    host = db.get(Host, a.host_id)
    if host is None:
        raise HTTPException(404, "host not found")
    return a, host


# Above the lifecycle wildcard, per that route's own WARNING further down.
@router.get("/{app_id}/network",
            dependencies=[Depends(_require_viewer),
                          Depends(require_entitlement("network.guest_config"))])
def app_network(request: Request, app_id: int, db=Depends(get_db),
                user: User = Depends(_require_viewer)):
    a, host = _app_and_host(db, app_id)
    return guest_nics(request, db, host, "lxc", a.ctid)


@router.put("/{app_id}/network/{iface}",
            dependencies=[Depends(_require_operator),
                          Depends(require_entitlement("network.guest_config"))])
def app_network_update(request: Request, app_id: int, iface: str, body: NicIn,
                       db=Depends(get_db), user: User = Depends(_require_operator)):
    a, host = _app_and_host(db, app_id)
    return set_guest_nic(request, db, user, target_type="app", target_id=a.id,
                         host=host, kind="lxc", vmid=a.ctid, iface=iface, body=body)
```

(`api/network.py` imports nothing from `apps.py` or `vms.py`, so this direction
of import introduces no cycle.)

- [ ] **Step 13: Run the network tests**

Run: `cd backend && python -m pytest tests/test_network_api.py tests/test_netconfig.py -q`
Expected: PASS, 34 passed (21 netconfig + 13 network API).

- [ ] **Step 14: Run the full backend suite**

Run: `cd backend && python -m pytest tests/ -q -m "not pve_integration and not e2e"`
Expected: PASS, Task 5's total + 34. `test_route_auth_invariant.py` and
`test_no_secret_echo.py` must both still pass; a 403-instead-of-401 on any new
route means the `dependencies=[...]` ordering in Step 9/11/12 was transposed.

- [ ] **Step 15: Commit**

```bash
git add backend/proxploy/services/netconfig.py backend/proxploy/api/network.py \
        backend/proxploy/services/proxmox.py backend/proxploy/api/__init__.py \
        backend/proxploy/api/vms.py backend/proxploy/api/apps.py \
        backend/tests/fakes/pve.py backend/tests/test_netconfig.py \
        backend/tests/test_network_api.py
git commit -m "feat(network): live bridge/throughput reads and MAC-preserving guest NIC edit"
```

---

## Task 7: Host network staging + apply/revert

**Files:**
- Create: `backend/proxploy/services/guestjobs.py`
- Modify: `backend/proxploy/services/proxmox.py`, `backend/proxploy/api/network.py`, `backend/proxploy/main.py`, `backend/tests/fakes/pve.py`
- Test: `backend/tests/test_network_hostconfig.py`

**Interfaces:**
- Consumes: Task 1's `services/hostclient.py::client_for_host(app, db, host)`, Task 2's `services/pvetask.py::await_task(ctx, client, node, upid, *, timeout_s=300.0, start_pct=10, end_pct=100) -> dict` and `api/jobs.py::enqueue_and_audit(request, db, user, *, kind, target_type, target_id, params, action=None) -> dict`, Task 6's `api/network.py` router and `_require_viewer` singleton, `proxploy.jobs::HANDLERS/JobContext/JobFailed`.
- Produces:
  - `ProxmoxClient.network_create(node: str, config: dict) -> None`, `network_update(node: str, iface: str, config: dict) -> None`, `network_delete(node: str, iface: str) -> None`, `network_apply(node: str) -> str`, `network_revert(node: str) -> None`
  - `proxploy/services/guestjobs.py::run_network_apply(ctx: JobContext, params: dict) -> dict` registered as `HANDLERS["network.apply"]`. **This module is the shared home for Tasks 10 and 11's snapshot/create/clone/delete handlers**: they append to it, they do not create a second module.
  - `POST /api/v1/network/bridges`, `PUT /api/v1/network/bridges/{host_id}/{node}/{iface}`, `DELETE /api/v1/network/bridges/{host_id}/{node}/{iface}`, `POST /api/v1/network/{host_id}/{node}/apply`, `POST /api/v1/network/{host_id}/{node}/revert`, all admin + `network.host_config`
  - Apply's 409 contract: `{"error": "confirm_required", "confirm_phrase": "<node>", "detail": "..."}`, deliberately the same shape as `services/selfguard.py`'s `{"error": "self_target", "confirm_phrase": name, "detail": ...}` so the frontend reuses one dialog vocabulary.

- [ ] **Step 1: Write the failing host-config tests**

```python
# backend/tests/test_network_hostconfig.py
"""Host network staging + apply/revert (doc 01 §6 "Host network edit", Pro).

PVE stages every network edit into /etc/network/interfaces.new and does
nothing to the live config until PUT /nodes/{node}/network is called. A bad
bridge applied to a node takes that node off the network until someone walks
to it with a keyboard, the single most dangerous call in this phase, so
apply requires the node name typed back, mirroring selfguard's confirm shape.
"""
import asyncio
import json

from fastapi.testclient import TestClient

from proxploy.models import AuditEvent, Host, HostCredential, Job, JobEvent


def _seed(app):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.9:8006", node_name="pve1",
                    status="connected", pve_version="8.4.1")
        db.add(host)
        db.commit()
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!net", "token_secret": "s3cret"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token",
                              encrypted_blob=blob, key_version=ver))
        db.commit()
        return host.id


def _fake():
    from tests.fakes.pve import FakePVE

    f = FakePVE()
    f.networks_by_node = {"pve1": [{"iface": "vmbr0", "type": "bridge", "active": 1}]}
    return f


def test_create_bridge_stages_and_audits_without_a_job(tmp_path, csrf_header,
                                                       bootstrap_admin):
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app)
        r = c.post("/api/v1/network/bridges", headers=csrf_header(c),
                   json={"host_id": host_id, "node": "pve1", "iface": "vmbr9",
                         "type": "bridge",
                         "config": {"bridge_ports": "enp3s0", "autostart": 1,
                                    "cidr": "10.9.0.1/24"}})
        assert r.status_code == 201, r.text
        assert r.json()["staged"] is True
        assert fake.network_calls == [
            ("create", "pve1", None,
             {"iface": "vmbr9", "type": "bridge", "bridge_ports": "enp3s0",
              "autostart": 1, "cidr": "10.9.0.1/24"})]
        with app.state.sessionmaker() as db:
            assert db.query(Job).count() == 0
            row = db.query(AuditEvent).filter_by(action="network.host_config").one()
            assert row.target_type == "host" and row.target_id == host_id
            assert row.params["iface"] == "vmbr9" and row.params["op"] == "create"


def test_update_and_delete_stage_through_to_the_iface_path(tmp_path, csrf_header,
                                                           bootstrap_admin):
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app)
        assert c.put(f"/api/v1/network/bridges/{host_id}/pve1/vmbr0",
                     headers=csrf_header(c),
                     json={"config": {"bridge_ports": "enp1s0 enp2s0"}}
                     ).status_code == 200
        assert c.delete(f"/api/v1/network/bridges/{host_id}/pve1/vmbr9",
                        headers=csrf_header(c)).status_code == 200
        assert fake.network_calls == [
            ("update", "pve1", "vmbr0", {"bridge_ports": "enp1s0 enp2s0"}),
            ("delete", "pve1", "vmbr9", {})]


def test_config_keys_are_validated_before_reaching_proxmox(tmp_path, csrf_header,
                                                           bootstrap_admin):
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app)
        r = c.post("/api/v1/network/bridges", headers=csrf_header(c),
                   json={"host_id": host_id, "node": "pve1", "iface": "vmbr9",
                         "config": {"__class__": "boom"}})
        assert r.status_code == 422
        assert fake.network_calls == []


def test_apply_without_confirm_is_409_with_the_node_as_the_phrase(tmp_path, csrf_header,
                                                                  bootstrap_admin):
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app)
        r = c.post(f"/api/v1/network/{host_id}/pve1/apply", headers=csrf_header(c),
                   json={})
        assert r.status_code == 409
        detail = r.json()["detail"]
        assert detail["error"] == "confirm_required"
        assert detail["confirm_phrase"] == "pve1"
        assert "network" in detail["detail"].lower()
        with app.state.sessionmaker() as db:
            assert db.query(Job).count() == 0
            assert (db.query(AuditEvent).filter_by(action="network.apply").one()
                    .result == "denied")
        assert fake.network_calls == []


def test_apply_with_the_wrong_phrase_is_also_409(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app)
        r = c.post(f"/api/v1/network/{host_id}/pve1/apply", headers=csrf_header(c),
                   json={"confirm": "pve2"})
        assert r.status_code == 409
        assert fake.network_calls == []


def test_apply_with_confirm_enqueues_the_job_and_audits_with_job_id(tmp_path, csrf_header,
                                                                    bootstrap_admin):
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app)
        r = c.post(f"/api/v1/network/{host_id}/pve1/apply", headers=csrf_header(c),
                   json={"confirm": "pve1"})
        assert r.status_code == 202, r.text
        job = r.json()["job"]
        assert job["kind"] == "network.apply"
        assert job["target_type"] == "host" and job["target_id"] == host_id
        with app.state.sessionmaker() as db:
            row = (db.query(AuditEvent).filter_by(action="network.apply")
                   .filter(AuditEvent.result == "ok").one())
            assert row.job_id == job["id"]


def test_revert_needs_no_confirm_and_is_not_a_job(tmp_path, csrf_header, bootstrap_admin):
    """Reverting only discards /etc/network/interfaces.new, it cannot strand a node."""
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app)
        r = c.post(f"/api/v1/network/{host_id}/pve1/revert", headers=csrf_header(c))
        assert r.status_code == 200 and r.json()["reverted"] is True
        assert fake.network_calls == [("revert", "pve1", None, {})]
        with app.state.sessionmaker() as db:
            assert db.query(Job).count() == 0
            assert db.query(AuditEvent).filter_by(action="network.revert").one()


def test_operator_role_is_refused_host_config_is_admin(tmp_path, csrf_header,
                                                       bootstrap_admin):
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id = _seed(app)
        c.post("/api/v1/users", json={"email": "viewer@example.com",
                                      "password": "correct-horse-battery",
                                      "display_name": "Viewer"},
               headers=csrf_header(c))
        c.post("/api/v1/auth/login", json={"email": "viewer@example.com",
                                           "password": "correct-horse-battery"},
               headers=csrf_header(c))
        r = c.post(f"/api/v1/network/{host_id}/pve1/apply", headers=csrf_header(c),
                   json={"confirm": "pve1"})
        assert r.status_code == 403 and r.json()["detail"] == "insufficient role"


def test_missing_session_is_401_not_403(tmp_path, csrf_header):
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        host_id = _seed(app)
        assert c.post(f"/api/v1/network/{host_id}/pve1/apply", json={"confirm": "pve1"},
                      headers=csrf_header(c)).status_code == 401


def test_network_apply_handler_polls_the_upid_to_completion(tmp_path):
    from proxploy.jobs import JobBackend
    from tests.support import make_job_app

    async def run():
        fake = _fake()
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.guestjobs  # noqa: F401, registers network.apply
        backend = JobBackend(app)
        host_id = _seed(app)
        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(db, kind="network.apply", target_type="host",
                                     target_id=host_id,
                                     params={"host_id": host_id, "node": "pve1"}).id
        await backend.wait(job_id, timeout=10)
        with app.state.sessionmaker() as db:
            job = db.get(Job, job_id)
            assert job.status == "succeeded", job.error
            assert job.result["exitstatus"] == "OK" and job.result["node"] == "pve1"
            messages = [e.message for e in db.query(JobEvent)
                        .filter_by(job_id=job_id).order_by(JobEvent.seq)]
            assert any("pve1" in m for m in messages)
        assert [k for k, *_ in fake.network_calls] == ["apply"]

    asyncio.run(run())


def test_network_apply_fails_the_job_when_proxmox_reports_a_bad_exit(tmp_path):
    from proxploy.jobs import JobBackend
    from tests.support import make_job_app

    async def run():
        fake = _fake()
        fake.task_exit = "command 'ifreload -a' failed: exit code 1"
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.guestjobs  # noqa: F401
        backend = JobBackend(app)
        host_id = _seed(app)
        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(db, kind="network.apply", target_type="host",
                                     target_id=host_id,
                                     params={"host_id": host_id, "node": "pve1"}).id
        await backend.wait(job_id, timeout=10)
        with app.state.sessionmaker() as db:
            assert db.get(Job, job_id).status == "failed"

    asyncio.run(run())
```

- [ ] **Step 2: Run to verify the failures**

Run: `cd backend && python -m pytest tests/test_network_hostconfig.py -q`
Expected: FAIL, the route tests return `404 Not Found` (assertion errors on
status codes), and both handler tests fail with
`KeyError: "no handler registered for job kind 'network.apply'"`.

- [ ] **Step 3: Add the five `ProxmoxClient` network methods**

In `backend/proxploy/services/proxmox.py`, after `guest_config_update` (Task 6):

```python
    # --- host network staging (Phase 6 Task 7) -------------------------------
    # PVE writes every one of the three staging calls below into
    # /etc/network/interfaces.new and touches NOTHING live. Only network_apply
    # promotes that file. network_revert deletes it.

    def network_create(self, node: str, config: dict) -> None:
        """POST /nodes/{node}/network, stages a new iface. `config` carries
        `iface` and `type` plus the PVE options (bridge_ports, cidr, ...)."""
        try:
            self._connect().nodes(node).network.post(**config)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"staging network interface failed on {node}", e) from e

    def network_update(self, node: str, iface: str, config: dict) -> None:
        """PUT /nodes/{node}/network/{iface}, stages an edit."""
        try:
            self._connect().nodes(node).network(iface).put(**config)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"staging {iface} failed on {node}", e) from e

    def network_delete(self, node: str, iface: str) -> None:
        """DELETE /nodes/{node}/network/{iface}, stages a removal."""
        try:
            self._connect().nodes(node).network(iface).delete()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"staging removal of {iface} failed on {node}", e) from e

    def network_apply(self, node: str) -> str:
        """PUT /nodes/{node}/network -> UPID.

        This is the one that can cut a node off the network. `ifreload -a` runs
        on the node itself; if the new config is wrong the API connection this
        very call arrived on may be what dies, so the UPID may become
        unpollable. Callers confirm before reaching here.
        """
        try:
            return self._connect().nodes(node).network.put()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"applying network config failed on {node}", e) from e

    def network_revert(self, node: str) -> None:
        """DELETE /nodes/{node}/network, discards /etc/network/interfaces.new."""
        try:
            self._connect().nodes(node).network.delete()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"reverting staged network config failed on {node}", e) from e
```

- [ ] **Step 4: Make FakePVE's network namespace callable and writable**

In `backend/tests/fakes/pve.py`, replace Task 1's read-only network leaf with
the class below (it keeps the same `.get()` contract), and wire it in
`_NodeNS.__init__` as `self.network = _NetworkNS(owner, name)`:

```python
class _NetworkNS:
    """nodes(n).network.get() lists.post/.put/.delete stage.put() with no
    iface applies (returns a UPID), .delete() with no iface reverts. Callable
    for nodes(n).network(iface)."""

    def __init__(self, owner, node, iface=None):
        self._owner, self._node, self._iface = owner, node, iface

    def __call__(self, iface):
        return _NetworkNS(self._owner, self._node, str(iface))

    def _check(self):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")

    def get(self, **kwargs):
        self._check()
        rows = self._owner.networks_by_node.get(self._node, [])
        want = kwargs.get("type")
        return [r for r in rows if want is None or r.get("type") == want]

    def post(self, **cfg):
        self._check()
        self._owner.network_calls.append(("create", self._node, None, dict(cfg)))

    def put(self, **cfg):
        self._check()
        if self._iface is None:
            self._owner.network_calls.append(("apply", self._node, None, dict(cfg)))
            return self._owner._record_action("network", 0, "apply")
        self._owner.network_calls.append(("update", self._node, self._iface, dict(cfg)))

    def delete(self, **kwargs):
        self._check()
        op = "revert" if self._iface is None else "delete"
        self._owner.network_calls.append((op, self._node, self._iface, dict(kwargs)))
```

And in `FakePVE.__init__`, next to the Task-1 `self.networks_by_node = ...` line:

```python
        # host network staging (Phase 6 Task 7): (op, node, iface|None, config)
        self.network_calls: list[tuple[str, str, str | None, dict]] = []
```

- [ ] **Step 5: Write `services/guestjobs.py` with the `network.apply` handler**

```python
# backend/proxploy/services/guestjobs.py
"""Guest- and node-shaped job handlers (doc 10 Phase 6).

Shared home for every Phase 6 handler that is not storage or backups:
`network.apply` lands here first; Tasks 10 and 11 append `vm.snapshot_*`,
`vm.create`, `vm.clone` and `vm.delete` to this same module rather than
starting new ones. Shape is services/lifecycle.py's: a blocking `_resolve` in
a thread, ctx.log/ctx.progress narration, the shared await_task poll loop,
module-bottom HANDLERS registration.

Registration is by import side effect, main.py's lifespan imports this module
with a `# noqa: F401`, and without that import none of these kinds exist.
"""
from __future__ import annotations

import asyncio

from proxploy.jobs import HANDLERS, JobContext, JobFailed
from proxploy.models import Host
from proxploy.services.hostclient import client_for_host
from proxploy.services.pvetask import await_task


def _resolve_host(app, host_id: int):
    """Blocking: host_id -> (ProxmoxClient, host name). Runs in a thread."""
    with app.state.sessionmaker() as db:
        host = db.get(Host, host_id)
        if host is None:
            raise JobFailed(f"host {host_id} not found")
        return client_for_host(app, db, host), host.name


async def run_network_apply(ctx: JobContext, params: dict) -> dict:
    """Promote /etc/network/interfaces.new on one node (PUT /nodes/{node}/network).

    The confirmation gate lives at the API layer (api/network.py::apply_network);
    by the time this runs the operator has already typed the node name back.
    A failure here can mean the node is unreachable rather than that the apply
    failed, await_task raising on a lost connection is the honest outcome
    either way, and the transcript keeps the UPID so an operator at the console
    can look the task up locally.
    """
    app = ctx.backend.app
    host_id = int(params["host_id"])
    node = str(params["node"])
    client, host_name = await asyncio.to_thread(_resolve_host, app, host_id)
    ctx.log(f"applying staged network config on node {node} ({host_name})")
    ctx.progress(5)
    upid = await asyncio.to_thread(client.network_apply, node)
    status = await await_task(ctx, client, node, upid, start_pct=10, end_pct=100)
    app.state.bus.publish("resource", {"type": "network", "id": host_id,
                                       "change": "applied"})
    return {"upid": upid, "exitstatus": status.get("exitstatus"),
            "node": node, "host_id": host_id}


HANDLERS["network.apply"] = run_network_apply
```

- [ ] **Step 6: Import the module in `main.py`'s lifespan**

In `backend/proxploy/main.py`, in the `# noqa: F401` import block inside
`lifespan` (alongside `_appstore` / `_catalog` / `lifecycle`):

```python
        from proxploy.services import guestjobs as _guestjobs  # noqa: F401, registers network.apply
```

Without this line `HANDLERS["network.apply"]` never exists and every apply
returns `KeyError` from `JobBackend.enqueue`.

- [ ] **Step 7: Add the host-config routes to `api/network.py`**

Append to `backend/proxploy/api/network.py` (after `throughput`), and add
`from proxploy.api.jobs import enqueue_and_audit` plus `from pydantic import
BaseModel, Field` to its imports:

```python
_require_admin = require_role("admin")

# PVE option names are lowercase words with dashes/underscores and digits.
# The config dict is unpacked straight into a proxmoxer kwargs call, so the
# key space is a trust boundary even though the values are PVE's problem.
_SAFE_KEY = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def _check_config(config: dict) -> dict:
    bad = [k for k in config if not _SAFE_KEY.match(str(k))]
    if bad:
        raise HTTPException(422, f"unsupported network option(s): {', '.join(map(str, bad))}")
    return config


def _host_or_404(db, host_id: int) -> Host:
    host = db.get(Host, host_id)
    if host is None:
        raise HTTPException(404, "host not found")
    return host


class BridgeIn(BaseModel):
    host_id: int
    node: str
    iface: str
    type: str = "bridge"
    config: dict = Field(default_factory=dict)


class BridgePatchIn(BaseModel):
    config: dict = Field(default_factory=dict)


class ApplyIn(BaseModel):
    confirm: str | None = None


# Every route below stages or promotes /etc/network/interfaces.new.
#
# ponytail: Proxploy does not detect whether staged changes exist, so Apply and
# Revert are always offered rather than enabled-when-dirty. PVE reports pending
# state as a `changes` property SIBLING to `data` on GET /nodes/{node}/network,
# and proxmoxer's .get() unwraps `data` and throws the rest away: reading it
# would mean bypassing the client layer, which proxmox.py's module docstring
# forbids outright. A no-op apply is handled gracefully by PVE (it reloads the
# unchanged config), so the cost of not knowing is one wasted ifreload.
# Upgrade path: a raw-response accessor on ProxmoxClient if the UI ever needs a
# "you have unsaved changes" badge.


@router.post("/bridges", status_code=201,
             dependencies=[Depends(_require_admin),
                           Depends(require_entitlement("network.host_config"))])
def create_bridge(request: Request, body: BridgeIn, db=Depends(get_db),
                  user: User = Depends(_require_admin)):
    host = _host_or_404(db, body.host_id)
    cfg = {"iface": body.iface, "type": body.type, **_check_config(body.config)}
    client_for_host(request.app, db, host).network_create(body.node, cfg)
    write_audit(db, actor_type="user", actor_id=user.id, action="network.host_config",
                target_type="host", target_id=host.id,
                params={"op": "create", "node": body.node, "iface": body.iface,
                        "config": body.config},
                ip=request.client.host if request.client else None)
    return {"staged": True, "node": body.node, "iface": body.iface}


@router.put("/bridges/{host_id}/{node}/{iface}",
            dependencies=[Depends(_require_admin),
                          Depends(require_entitlement("network.host_config"))])
def update_bridge(request: Request, host_id: int, node: str, iface: str,
                  body: BridgePatchIn, db=Depends(get_db),
                  user: User = Depends(_require_admin)):
    host = _host_or_404(db, host_id)
    client_for_host(request.app, db, host).network_update(
        node, iface, _check_config(body.config))
    write_audit(db, actor_type="user", actor_id=user.id, action="network.host_config",
                target_type="host", target_id=host.id,
                params={"op": "update", "node": node, "iface": iface,
                        "config": body.config},
                ip=request.client.host if request.client else None)
    return {"staged": True, "node": node, "iface": iface}


@router.delete("/bridges/{host_id}/{node}/{iface}",
               dependencies=[Depends(_require_admin),
                             Depends(require_entitlement("network.host_config"))])
def delete_bridge(request: Request, host_id: int, node: str, iface: str,
                  db=Depends(get_db), user: User = Depends(_require_admin)):
    host = _host_or_404(db, host_id)
    client_for_host(request.app, db, host).network_delete(node, iface)
    write_audit(db, actor_type="user", actor_id=user.id, action="network.host_config",
                target_type="host", target_id=host.id,
                params={"op": "delete", "node": node, "iface": iface},
                ip=request.client.host if request.client else None)
    return {"staged": True, "node": node, "iface": iface}


@router.post("/{host_id}/{node}/apply", status_code=202,
             dependencies=[Depends(_require_admin),
                           Depends(require_entitlement("network.host_config"))])
def apply_network(request: Request, host_id: int, node: str, body: ApplyIn,
                  db=Depends(get_db), user: User = Depends(_require_admin)):
    """Promote the staged config. Typed confirmation required.

    Doc 08 §1's typed-name guardrail, reused verbatim from selfguard's
    self_target shape so the frontend has one confirm dialog, not two. The
    phrase is the NODE NAME because the node is what is at risk: `ifreload -a`
    with a broken bridge takes the node off the network until someone reaches
    its physical console. Unlike a stopped CT this has no in-band undo.
    """
    host = _host_or_404(db, host_id)
    ip = request.client.host if request.client else None
    if (body.confirm or "") != node:
        write_audit(db, actor_type="user", actor_id=user.id, action="network.apply",
                    target_type="host", target_id=host.id,
                    params={"node": node}, result="denied", ip=ip)
        raise HTTPException(409, {
            "error": "confirm_required", "confirm_phrase": node,
            "detail": (f"Applying the staged network config reloads {node}'s "
                       f"interfaces. If the staged bridge is wrong, {node} loses "
                       f"its network and can only be recovered from its physical "
                       f"console. Type the node name to confirm."),
        })
    return enqueue_and_audit(request, db, user, kind="network.apply",
                             target_type="host", target_id=host.id,
                             params={"host_id": host.id, "node": node},
                             action="network.apply")


@router.post("/{host_id}/{node}/revert",
             dependencies=[Depends(_require_admin),
                           Depends(require_entitlement("network.host_config"))])
def revert_network(request: Request, host_id: int, node: str, db=Depends(get_db),
                   user: User = Depends(_require_admin)):
    """Discard /etc/network/interfaces.new. No confirmation and no job: this
    deletes a staged file and cannot disturb the running config."""
    host = _host_or_404(db, host_id)
    client_for_host(request.app, db, host).network_revert(node)
    write_audit(db, actor_type="user", actor_id=user.id, action="network.revert",
                target_type="host", target_id=host.id, params={"node": node},
                ip=request.client.host if request.client else None)
    return {"reverted": True, "node": node}
```

Registration order inside this router matters as much as it does in `apps.py`:
`/bridges` and `/bridges/{host_id}/{node}/{iface}` are declared before
`/{host_id}/{node}/apply`, so the literal `bridges` segment always wins. Keep
them in this order.

- [ ] **Step 8: Run the host-config tests**

Run: `cd backend && python -m pytest tests/test_network_hostconfig.py -q`
Expected: PASS, 11 passed.

- [ ] **Step 9: Run the full backend suite**

Run: `cd backend && python -m pytest tests/ -q -m "not pve_integration and not e2e"`
Expected: PASS, Task 6's total + 11. `test_route_auth_invariant.py` must still
pass on all five new routes (`_require_admin` first in every
`dependencies=[...]`), and `test_job_backend.py` must still pass; `guestjobs`
adds a key to `HANDLERS`, it does not change the registry's shape.

- [ ] **Step 10: Commit**

```bash
git add backend/proxploy/services/guestjobs.py backend/proxploy/services/proxmox.py \
        backend/proxploy/api/network.py backend/proxploy/main.py \
        backend/tests/fakes/pve.py backend/tests/test_network_hostconfig.py
git commit -m "feat(network): host bridge/VLAN staging with confirmed apply and revert"
```

---

## Task 8: backups sync + `GET /backups` (cached list + stats)

**Files:**
- Create: `backend/proxploy/services/backupjobs.py`
- Create: `backend/proxploy/api/backups.py`
- Modify: `backend/proxploy/config.py`, `backend/proxploy/main.py`, `backend/proxploy/api/__init__.py`
- Test: `backend/tests/test_backups_sync.py`

**Interfaces:**
- Consumes (Task 1): `proxploy.services.hostclient.client_for_host(app, db, host) -> ProxmoxClient`, `ProxmoxClient.storages(node: str) -> list[dict]`, `ProxmoxClient.storage_content(node: str, storage: str, content: str | None = None) -> list[dict]`, and the FakePVE attributes `storages_by_node: dict[str, list[dict]]` / `content_by_storage: dict[str, list[dict]]` with the namespace classes serving them. Also `proxploy.services.settings.get_setting/set_setting`, `proxploy.jobs.HANDLERS/JobContext`, `proxploy.api.deps.require_role/require_entitlement/get_db`.
- Produces:
  - `proxploy/services/backupjobs.py::parse_volid(volid: str) -> tuple[str | None, int | None]`
  - `proxploy/services/backupjobs.py::sync_host_backups(app, host_id: int) -> dict`: blocking; `{"host_id", "synced", "dropped"}`
  - `proxploy/services/backupjobs.py::sync_in_flight(db) -> bool`
  - `proxploy/services/backupjobs.py::SYNCED_AT_KEY = "backup.synced_at"`
  - job kind `backup.sync` → `sync_backups(ctx: JobContext, params: dict) -> dict`
  - `proxploy/api/backups.py::router` (`APIRouter(prefix="/backups", tags=["backups"])`) with `GET /api/v1/backups -> {backups: [{id, host_id, host_name, storage, volid, guest_type, guest_vmid, guest_name, taken_at, size_bytes, verify_state, notes}], stats: {total, total_bytes, ok_count, failed_count, success_rate_30d, datastores: [{storage, count, size_bytes}]}, synced_at, stale}`
  - `Settings.backup_sync_stale_s: float = 900.0`

**No migration.** `Backup(id, host_id, storage, volid, guest_type, guest_vmid, guest_name, taken_at, size_bytes, verify_state, notes, synced_at)` plus `ux_backups(host_id, volid)` and `ix_backups_guest` already exist from migration 0001 (`models/__init__.py:397-414`) and nothing has ever written them. This task is the first writer.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_backups_sync.py
"""backup.sync: PVE storage content -> the `backups` cache table (doc 04
§backups, a droppable mirror), plus the cached GET /api/v1/backups the page
reads. Nothing wrote this table before this task."""
import asyncio
import json
import time

from proxploy.models import App, Backup, Host, HostCredential, Job, Vm

VOLID_CT = "local:backup/vzdump-lxc-150-2026_07_30-02_00_00.tar.zst"
VOLID_VM = "local:backup/vzdump-qemu-201-2026_07_30-03_00_00.vma.zst"


def _fake_with_backups(items=None):
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    fake.storages_by_node = {"pve1": [
        {"storage": "local", "type": "dir", "content": "backup,iso,vztmpl"},
        {"storage": "local-lvm", "type": "lvmthin", "content": "images,rootdir"},
    ]}
    fake.content_by_storage = {"local": items if items is not None else [
        {"volid": VOLID_CT, "ctime": 1753840800, "size": 1073741824,
         "format": "tar.zst", "verification": {"state": "ok"}, "notes": "nightly"},
        {"volid": VOLID_VM, "ctime": 1753844400, "size": 5368709120,
         "format": "vma.zst", "verification": {"state": "failed"}, "notes": None},
    ]}
    return fake


def _seed_host(app):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.7:8006", node_name="pve1",
                    status="connected", pve_version="8.4.1")
        db.add(host)
        db.commit()
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!bk", "token_secret": "s3cret"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token", encrypted_blob=blob,
                              key_version=ver, public_meta="proxploy@pve!bk"))
        db.add(App(host_id=host.id, ctid=150, name="Immich", slug="immich"))
        db.add(Vm(host_id=host.id, vmid=201, name="win11", status="running"))
        db.commit()
        return host.id


def test_parse_volid_reads_guest_type_and_vmid():
    from proxploy.services.backupjobs import parse_volid

    assert parse_volid(VOLID_CT) == ("ct", 150)
    assert parse_volid(VOLID_VM) == ("vm", 201)
    assert parse_volid("pbs-ds:backup/ct/150/2026-07-30T02:00:00Z") == ("ct", 150)
    assert parse_volid("pbs-ds:backup/vm/201/2026-07-30T03:00:00Z") == ("vm", 201)
    assert parse_volid("local:iso/debian-12.iso") == (None, None)


def test_sync_mirrors_backup_storages_only_and_resolves_guest_names(tmp_path):
    from proxploy.services.backupjobs import sync_host_backups
    from tests.support import make_job_app

    async def run():
        fake = _fake_with_backups()
        app = make_job_app(tmp_path, fake=fake)
        hid = _seed_host(app)
        result = sync_host_backups(app, hid)
        assert result["synced"] == 2 and result["dropped"] == 0
        with app.state.sessionmaker() as db:
            rows = {b.volid: b for b in db.query(Backup).all()}
            assert set(rows) == {VOLID_CT, VOLID_VM}  # local-lvm has no `backup` content
            ct = rows[VOLID_CT]
            assert ct.storage == "local" and ct.guest_type == "ct" and ct.guest_vmid == 150
            assert ct.guest_name == "Immich"
            assert ct.size_bytes == 1073741824 and ct.verify_state == "ok"
            assert ct.notes == "nightly" and ct.taken_at is not None
            assert ct.synced_at is not None
            assert rows[VOLID_VM].guest_name == "win11"
            assert rows[VOLID_VM].verify_state == "failed"

    asyncio.run(run())


def test_sync_is_idempotent_and_drops_vanished_volids(tmp_path):
    from proxploy.services.backupjobs import sync_host_backups
    from tests.support import make_job_app

    async def run():
        fake = _fake_with_backups()
        app = make_job_app(tmp_path, fake=fake)
        hid = _seed_host(app)
        sync_host_backups(app, hid)
        assert sync_host_backups(app, hid)["synced"] == 2  # no duplicate rows
        with app.state.sessionmaker() as db:
            assert db.query(Backup).count() == 2
        fake.content_by_storage["local"] = [
            {"volid": VOLID_CT, "ctime": 1753840800, "size": 1073741824,
             "verification": {"state": "ok"}, "notes": "nightly"}]
        assert sync_host_backups(app, hid)["dropped"] == 1
        with app.state.sessionmaker() as db:
            assert [b.volid for b in db.query(Backup).all()] == [VOLID_CT]

    asyncio.run(run())


def test_backup_sync_job_runs_end_to_end(tmp_path):
    from proxploy.jobs import HANDLERS, JobBackend
    from tests.support import make_job_app

    async def run():
        fake = _fake_with_backups()
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.backupjobs  # noqa: F401, registers backup.sync

        assert "backup.sync" in HANDLERS
        backend = JobBackend(app)
        _seed_host(app)
        with app.state.sessionmaker() as db:
            jid = backend.enqueue(db, kind="backup.sync", target_type="system",
                                  params={}).id
        await backend.wait(jid, timeout=10)
        with app.state.sessionmaker() as db:
            job = db.get(Job, jid)
            assert job.status == "succeeded", job.error
            assert job.result["synced"] == 2 and job.result["failed"] == []
            assert db.query(Backup).count() == 2

    asyncio.run(run())


def test_a_broken_host_does_not_abort_the_batch(tmp_path):
    from proxploy.jobs import JobBackend
    from tests.support import make_job_app

    async def run():
        fake = _fake_with_backups()
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.backupjobs  # noqa: F401

        backend = JobBackend(app)
        _seed_host(app)
        with app.state.sessionmaker() as db:  # second host, no api_token credential
            db.add(Host(name="host-02", address="https://10.0.0.8:8006",
                        node_name="pve2", status="connected"))
            db.commit()
            jid = backend.enqueue(db, kind="backup.sync", target_type="system",
                                  params={}).id
        await backend.wait(jid, timeout=10)
        with app.state.sessionmaker() as db:
            job = db.get(Job, jid)
            assert job.status == "succeeded", job.error
            assert job.result["synced"] == 2 and len(job.result["failed"]) == 1

    asyncio.run(run())


def _seed_two_backups(app):
    from datetime import timedelta

    from proxploy.models import utcnow
    from tests.support import seed_host_row

    with app.state.sessionmaker() as db:
        h = seed_host_row(db)
        now = utcnow()
        db.add(Backup(host_id=h.id, storage="local", volid=VOLID_VM, guest_type="vm",
                      guest_vmid=201, guest_name="win11", taken_at=now - timedelta(hours=1),
                      size_bytes=30, verify_state="failed", synced_at=now))
        db.add(Backup(host_id=h.id, storage="local", volid=VOLID_CT, guest_type="ct",
                      guest_vmid=150, guest_name="Immich", taken_at=now,
                      size_bytes=10, verify_state="ok", synced_at=now))
        db.commit()


def test_backups_list_returns_cached_rows_and_stats(tmp_path, bootstrap_admin):
    from fastapi.testclient import TestClient
    from proxploy.services.backupjobs import SYNCED_AT_KEY
    from proxploy.services.settings import set_setting
    from proxploy.models import utcnow
    from tests.support import make_app

    app = make_app(tmp_path)
    c = TestClient(app)
    with c:
        bootstrap_admin(c)
        _seed_two_backups(app)
        with app.state.sessionmaker() as db:
            set_setting(db, SYNCED_AT_KEY, utcnow().isoformat())
        body = c.get("/api/v1/backups").json()
        assert [b["volid"] for b in body["backups"]] == [VOLID_CT, VOLID_VM]  # newest first
        assert body["backups"][0]["host_name"] == "host-01"
        assert body["backups"][0]["guest_name"] == "Immich"
        st = body["stats"]
        assert st["total"] == 2 and st["total_bytes"] == 40
        assert st["ok_count"] == 1 and st["failed_count"] == 1
        assert st["success_rate_30d"] == 50.0
        assert st["datastores"] == [{"storage": "local", "count": 2, "size_bytes": 40}]
        assert body["stale"] is False and body["synced_at"] is not None


def test_unverified_backups_report_no_success_rate(tmp_path, bootstrap_admin):
    from fastapi.testclient import TestClient
    from proxploy.models import utcnow
    from tests.support import make_app, seed_host_row

    app = make_app(tmp_path)
    c = TestClient(app)
    with c:
        bootstrap_admin(c)
        with app.state.sessionmaker() as db:
            h = seed_host_row(db)
            db.add(Backup(host_id=h.id, storage="local", volid=VOLID_CT,
                          guest_type="ct", guest_vmid=150, taken_at=utcnow(),
                          size_bytes=1, verify_state="none", synced_at=utcnow()))
            db.commit()
        st = c.get("/api/v1/backups").json()["stats"]
        assert st["total"] == 1
        assert st["success_rate_30d"] is None  # never a fake 100%


def test_empty_cache_auto_enqueues_exactly_one_sync(tmp_path, bootstrap_admin):
    from fastapi.testclient import TestClient
    from tests.support import make_app

    app = make_app(tmp_path)
    c = TestClient(app)
    with c:
        bootstrap_admin(c)
        body = c.get("/api/v1/backups").json()
        assert body["backups"] == [] and body["stale"] is True
        for _ in range(100):  # let the auto-enqueued sync finish (no hosts -> instant)
            with app.state.sessionmaker() as db:
                j = db.query(Job).filter_by(kind="backup.sync").one()  # .one() = never twice
                if j.status in ("succeeded", "failed", "canceled", "interrupted"):
                    break
            time.sleep(0.05)
        assert j.status == "succeeded", j.error
        body = c.get("/api/v1/backups").json()
        assert body["stale"] is False  # a completed sync over an empty cluster is fresh
        with app.state.sessionmaker() as db:
            assert db.query(Job).filter_by(kind="backup.sync").count() == 1


def test_backups_list_requires_auth(tmp_path):
    from fastapi.testclient import TestClient
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        assert c.get("/api/v1/backups").status_code == 401
```

- [ ] **Step 2: Run to verify failures**

Run: `cd backend && pytest tests/test_backups_sync.py -q`
Expected: FAIL, every test errors with `ModuleNotFoundError: No module named 'proxploy.services.backupjobs'` (the two route tests fail on the same import; the last one fails with `assert 404 == 401`).

- [ ] **Step 3: Add the staleness setting**

In `backend/proxploy/config.py`, after `console_idle_timeout_s`:

```python
    backup_sync_stale_s: float = 900.0
```

- [ ] **Step 4: Write `services/backupjobs.py`, volid parsing + the per-host mirror**

```python
# backend/proxploy/services/backupjobs.py
"""Backup cache sync + backup mutation job handlers (doc 01 §7, doc 04 §backups).

`backups` is a droppable mirror, exactly like the poller's `vms` handling: each
sync writes what Proxmox currently reports and deletes rows whose volid vanished
upstream. Proxmox is the source of truth; this table only feeds the Backups page.

Unlike `vms`, this is NOT on the 30 s poll cycle; listing storage content is a
per-storage call, not part of the `/cluster/resources` bulk read the doc-02 §3
budget allows. It runs as a job: on demand from the page (when the cache is
stale) and after every backup mutation.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

from proxploy.jobs import HANDLERS, JobContext
from proxploy.models import App, Backup, Host, Job, Vm, utcnow
from proxploy.services.hostclient import client_for_host
from proxploy.services.settings import set_setting

SYNCED_AT_KEY = "backup.synced_at"

# vzdump archives:  local:backup/vzdump-lxc-150-2026_07_30-02_00_00.tar.zst
# PBS snapshots:    pbs-ds:backup/ct/150/2026-07-30T02:00:00Z
VZDUMP_RE = re.compile(r"vzdump-(lxc|openvz|qemu)-(\d+)-")
PBS_RE = re.compile(r":backup/(ct|vm)/(\d+)/")
_GUEST_KIND = {"lxc": "ct", "openvz": "ct", "ct": "ct", "qemu": "vm", "vm": "vm"}


def parse_volid(volid: str) -> tuple[str | None, int | None]:
    """-> ("ct"|"vm", vmid), or (None, None) for anything that isn't a backup.

    The volid is the identifier upstream (doc 04) and carries the guest it came
    from in both storage layouts; the content row's own `vmid` field is absent
    on some PBS shapes, so the name is parsed rather than trusted.
    """
    m = VZDUMP_RE.search(volid) or PBS_RE.search(volid)
    if not m:
        return None, None
    return _GUEST_KIND[m.group(1)], int(m.group(2))


def _has_backup_content(entry: dict) -> bool:
    """PVE reports `content` as a comma string ("backup,iso") in most shapes and
    as a list in a few; both mean the same thing."""
    content = entry.get("content") or ""
    parts = content if isinstance(content, list) else content.split(",")
    return "backup" in [str(p).strip() for p in parts]


def _taken_at(ctime) -> datetime | None:
    if ctime in (None, ""):
        return None
    # naive UTC, matching models.utcnow(): every other datetime column is naive
    return datetime.fromtimestamp(int(ctime), timezone.utc).replace(tzinfo=None)


def sync_host_backups(app, host_id: int) -> dict:
    """Blocking. Mirror one host's backup archives into `backups`.

    Returns {"host_id", "synced", "dropped"}.
    """
    with app.state.sessionmaker() as db:
        host = db.get(Host, host_id)
        if host is None:
            raise RuntimeError(f"host {host_id} not found")
        client = client_for_host(app, db, host)
        node = host.node_name or ""
        # ponytail: one node per Host row. Shared datastores (PBS, NFS, CephFS)
        # report identically from any node, so this is complete for them;
        # node-local vzdump archives on a sibling node of a cluster are missed
        # until Host models its nodes. Upgrade path: iterate the poller's
        # snapshot node list instead of this single name.
        rows: list[dict] = []
        for st in client.storages(node):
            if not _has_backup_content(st):
                continue
            name = st.get("storage")
            for item in client.storage_content(node, name, content="backup"):
                rows.append({"_storage": name, **item})

        ct_names = {a.ctid: a.name for a in db.query(App).filter_by(host_id=host_id)}
        vm_names = {v.vmid: v.name for v in db.query(Vm).filter_by(host_id=host_id)}
        existing = {b.volid: b for b in db.query(Backup).filter_by(host_id=host_id)}
        now = utcnow()
        seen: set[str] = set()
        for item in rows:
            volid = item.get("volid")
            if not volid or volid in seen:
                continue
            seen.add(volid)
            b = existing.get(volid)
            if b is None:
                b = Backup(host_id=host_id, volid=volid)  # ux_backups(host_id, volid)
                db.add(b)
            gtype, gvmid = parse_volid(volid)
            b.storage = item.get("_storage")
            b.guest_type, b.guest_vmid = gtype, gvmid
            b.guest_name = ct_names.get(gvmid) if gtype == "ct" else vm_names.get(gvmid)
            b.taken_at = _taken_at(item.get("ctime"))
            b.size_bytes = int(item["size"]) if item.get("size") is not None else None
            b.verify_state = (item.get("verification") or {}).get("state") or "none"
            b.notes = item.get("notes")
            b.synced_at = now
        dropped = 0
        for volid, b in existing.items():
            if volid not in seen:
                db.delete(b)  # gone upstream = gone here; the mirror is droppable
                dropped += 1
        db.commit()
        return {"host_id": host_id, "synced": len(seen), "dropped": dropped}
```

- [ ] **Step 5: Add the `backup.sync` handler and the in-flight guard**

Append to `backend/proxploy/services/backupjobs.py`:

```python
async def sync_backups(ctx: JobContext, params: dict) -> dict:
    """`backup.sync`, every connected host, or one when `host_id` is given.

    One bad host is recorded and skipped: a host missing its API token must not
    stop the other three from syncing (services/catalog.py::run_ingest's rule).
    """
    app = ctx.backend.app
    if params.get("host_id"):
        host_ids = [int(params["host_id"])]
    else:
        with app.state.sessionmaker() as db:
            host_ids = [h.id for h in db.query(Host).filter_by(status="connected").all()]
    ctx.log(f"syncing backups from {len(host_ids)} host(s)")
    synced = dropped = 0
    failed: list[dict] = []
    for i, hid in enumerate(host_ids):
        try:
            r = await asyncio.to_thread(sync_host_backups, app, hid)
        except Exception as e:  # noqa: BLE001, one bad host can't kill the batch
            failed.append({"host_id": hid, "reason": str(e)})
            ctx.log(f"host {hid}: {e}", stream="stderr")
            continue
        synced += r["synced"]
        dropped += r["dropped"]
        ctx.progress(int((i + 1) / len(host_ids) * 100))
    with app.state.sessionmaker() as db:
        # Recorded even when zero backups were found: "the cache is empty" and
        # "the cache was never filled" are different, and only this key can tell
        # the GET route apart: otherwise a cluster with no backups re-enqueues
        # a sync on every page load.
        set_setting(db, SYNCED_AT_KEY, utcnow().isoformat())
    ctx.log(f"{synced} backups cached, {dropped} dropped, {len(failed)} host(s) failed")
    ctx.progress(100)
    app.state.bus.publish("resource", {"type": "backup", "change": "list"})
    return {"synced": synced, "dropped": dropped, "failed": failed}


def sync_in_flight(db) -> bool:
    """A page that refetches while a sync is queued must not pile up a second."""
    return (db.query(Job)
            .filter(Job.kind == "backup.sync", Job.status.in_(("queued", "running")))
            .first() is not None)


HANDLERS["backup.sync"] = sync_backups
```

- [ ] **Step 6: Register the module in `main.py`'s lifespan**

In `backend/proxploy/main.py`, in the lifespan's `# noqa: F401` import block (next to `_appstore` and `_catalog`), add:

```python
        from proxploy.services import backupjobs as _backupjobs  # noqa: F401, registers backup.*
```

Without this line `HANDLERS["backup.sync"]` never registers and `enqueue` raises `KeyError`.

- [ ] **Step 7: Write `api/backups.py`**

```python
# backend/proxploy/api/backups.py
"""Backups page endpoints (doc 05 §Backups, doc 01 §7).

The list is served from the `backups` cache table, never live from Proxmox; 
listing storage content is a per-storage call and this page is polled. The
`backup.sync` job is what fills it, and the GET below fires one when the cache
has gone stale so a fresh install is never permanently blank.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request

from proxploy.api.deps import get_db, require_entitlement, require_role
from proxploy.models import Backup, Host, User, utcnow
from proxploy.services.backupjobs import SYNCED_AT_KEY, sync_in_flight
from proxploy.services.settings import get_setting

router = APIRouter(prefix="/backups", tags=["backups"])

# Singleton first in dependencies=[...] and reused as the parameter dep so
# FastAPI collapses them and auth runs before the entitlement check
# (test_route_auth_invariant.py).
_require_viewer = require_role("viewer")


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def _backup_out(b: Backup, host_name: str | None) -> dict:
    return {
        "id": b.id, "host_id": b.host_id, "host_name": host_name,
        "storage": b.storage, "volid": b.volid,
        "guest_type": b.guest_type, "guest_vmid": b.guest_vmid,
        "guest_name": b.guest_name, "taken_at": _iso(b.taken_at),
        "size_bytes": b.size_bytes, "verify_state": b.verify_state,
        "notes": b.notes,
    }


def _last_sync(db) -> datetime | None:
    raw = get_setting(db, SYNCED_AT_KEY)
    if raw:
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            pass
    return None


@router.get("", dependencies=[Depends(_require_viewer),
                              Depends(require_entitlement("backups.pbs"))])
def list_backups(request: Request, db=Depends(get_db),
                 user: User = Depends(_require_viewer)):
    hosts = {h.id: h.name for h in db.query(Host).all()}
    rows = db.query(Backup).order_by(Backup.taken_at.desc()).all()
    synced_at = _last_sync(db) or max((b.synced_at for b in rows if b.synced_at),
                                      default=None)
    stale_s = request.app.state.settings.backup_sync_stale_s
    stale = synced_at is None or (utcnow() - synced_at).total_seconds() > stale_s
    if stale and not sync_in_flight(db):
        request.app.state.jobs.enqueue(db, kind="backup.sync", target_type="system",
                                       params={}, requested_by=user.id)

    cutoff = utcnow() - timedelta(days=30)
    recent = [b for b in rows if b.taken_at and b.taken_at >= cutoff]
    ok_30d = sum(1 for b in recent if b.verify_state == "ok")
    bad_30d = sum(1 for b in recent if b.verify_state == "failed")
    datastores: dict[str, dict] = {}
    for b in rows:
        d = datastores.setdefault(b.storage or "-", {"storage": b.storage or "-",
                                                     "count": 0, "size_bytes": 0})
        d["count"] += 1
        d["size_bytes"] += b.size_bytes or 0
    return {
        "backups": [_backup_out(b, hosts.get(b.host_id)) for b in rows],
        "stats": {
            "total": len(rows),
            "total_bytes": sum(b.size_bytes or 0 for b in rows),
            "ok_count": sum(1 for b in rows if b.verify_state == "ok"),
            "failed_count": sum(1 for b in rows if b.verify_state == "failed"),
            # verify_state is the only per-archive success signal Proxmox
            # exposes. Unverified archives are excluded from the denominator
            # rather than counted as either outcome, so a datastore with
            # verification switched off reports None instead of a fake 100%.
            "success_rate_30d": (round(ok_30d / (ok_30d + bad_30d) * 100, 1)
                                 if (ok_30d + bad_30d) else None),
            "datastores": sorted(datastores.values(), key=lambda d: -d["size_bytes"]),
        },
        "synced_at": _iso(synced_at),
        "stale": stale,
    }
```

- [ ] **Step 8: Register the router**

In `backend/proxploy/api/__init__.py`, add `backups` to the import tuple and one include:

```python
from proxploy.api import (apps, audit, auth, backups, catalog, cluster, consoles,
                          entitlements, events, hosts, jobs, meta, metrics,
                          notifications, settings, vms)
```

and after `api_router.include_router(metrics.router)`:

```python
api_router.include_router(backups.router)
```

- [ ] **Step 9: Run the task's tests**

Run: `cd backend && pytest tests/test_backups_sync.py -q`
Expected: PASS, 9 passed.

- [ ] **Step 10: Run the full backend suite**

Run: `cd backend && pytest tests/ -q -m "not pve_integration and not e2e"`
Expected: Task 7's total + 9 passed, 0 failed, 0 errors. `test_route_auth_invariant.py` and `test_no_secret_echo.py` must still pass, the new route is automatically in their sweep.

- [ ] **Step 11: Commit**

```bash
git add backend/proxploy/services/backupjobs.py backend/proxploy/api/backups.py backend/proxploy/config.py backend/proxploy/main.py backend/proxploy/api/__init__.py backend/tests/test_backups_sync.py
git commit -m "feat(backups): backup.sync cache job + cached GET /backups with stats"
```

---

## Task 9: backups run / restore / delete / prune

**Files:**
- Modify: `backend/proxploy/services/proxmox.py`, `backend/proxploy/services/backupjobs.py`, `backend/proxploy/api/backups.py`, `backend/tests/fakes/pve.py`
- Test: `backend/tests/test_backups_api.py`

**Interfaces:**
- Consumes: Task 1 `client_for_host`, `ProxmoxClient.cluster_nextid() -> int`; Task 2 `proxploy.services.pvetask.await_task(ctx, client, node, upid, *, timeout_s=300.0, start_pct=10, end_pct=100) -> dict` and `proxploy.api.jobs.enqueue_and_audit(request, db, user, *, kind, target_type, target_id, params, action=None) -> dict`; Task 4 `ProxmoxClient.storage_delete_volume(node, storage, volid) -> str | None`; Task 8 `sync_host_backups`, `parse_volid`; `proxploy.services.selfguard.is_self`.
- Produces:
  - `ProxmoxClient.vzdump(node: str, params: dict) -> str`
  - `ProxmoxClient.restore_guest(kind: str, node: str, vmid: int, params: dict) -> str`
  - `ProxmoxClient.prune_preview(node: str, storage: str, params: dict) -> list[dict]`
  - `ProxmoxClient.prune_backups(node: str, storage: str, params: dict) -> str`
  - job kinds `backup.run`, `backup.restore`, `backup.delete`, `backup.prune`
  - routes `POST /api/v1/backups/run` (operator, `backups.run`), `POST /api/v1/backups/{backup_id}/restore` (admin, `backups.restore`), `DELETE /api/v1/backups/{backup_id}` (admin, `backups.pbs`), `GET /api/v1/backups/prune-preview` (admin, `backups.retention`), `POST /api/v1/backups/prune` (admin, `backups.retention`)
  - FakePVE: `.nodes(n).vzdump.post(**kw)`, `.nodes(n).<lxc|qemu>.post(**kw)` (the guest-factory create/restore leaf **Task 11's `vm_create` reuses**), `.nodes(n).storage(s).prunebackups.{get,delete}(**kw)`; recorders `fake.vzdumps`, `fake.creates`, `fake.prune_gets`, `fake.prune_deletes`, `fake.nextid`

**`selfguard.DESTRUCTIVE` is deliberately NOT extended.** It is a set of *guest
lifecycle verbs* consumed by exactly one caller, `api/apps.py::enqueue_lifecycle`,
via `if action in DESTRUCTIVE`, and `enqueue_lifecycle` is never reached with
`"restore"` or `"delete"`, because backups have their own routes with their own
bodies. Adding the two strings would change no behaviour and would falsely imply
the lifecycle wildcard accepts them. `DELETE /backups/{id}` deletes an *archive*,
never a guest, so it can never target the running CT at all. Only the in-place
restore route needs the guard, and it calls `is_self(db, "app", …)` directly.
`services/selfguard.py` is not edited by this task; a test asserts that.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_backups_api.py
"""Backup mutations: run, restore (in place / as new), delete, prune.

Two safety properties are load-bearing here and each has its own test:
  1. an in-place restore over the CT Proxploy runs in is refused outright;
  2. prune-preview is a dry run and can never delete (different HTTP verb).
"""
import asyncio
import json

from fastapi.testclient import TestClient

from proxploy.models import App, Backup, Host, HostCredential, Job, Vm

VOLID_CT = "local:backup/vzdump-lxc-150-2026_07_30-02_00_00.tar.zst"
VOLID_VM = "local:backup/vzdump-qemu-201-2026_07_30-03_00_00.vma.zst"


def _fake():
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    fake.storages_by_node = {"pve1": [{"storage": "local", "type": "dir",
                                       "content": "backup"}]}
    fake.content_by_storage = {"local": [
        {"volid": VOLID_CT, "ctime": 1753840800, "size": 1,
         "verification": {"state": "ok"}}]}
    fake.nextid = 999
    return fake


def _seed(app, ct_status="stopped"):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.7:8006", node_name="pve1",
                    status="connected", pve_version="8.4.1")
        db.add(host)
        db.commit()
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!bk", "token_secret": "s3cret"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token", encrypted_blob=blob,
                              key_version=ver, public_meta="proxploy@pve!bk"))
        a = App(host_id=host.id, ctid=150, name="Immich", slug="immich",
                status_cached=ct_status)
        v = Vm(host_id=host.id, vmid=201, name="win11", status="stopped")
        db.add_all([a, v])
        db.commit()
        b_ct = Backup(host_id=host.id, storage="local", volid=VOLID_CT,
                      guest_type="ct", guest_vmid=150, guest_name="Immich")
        b_vm = Backup(host_id=host.id, storage="local", volid=VOLID_VM,
                      guest_type="vm", guest_vmid=201, guest_name="win11")
        db.add_all([b_ct, b_vm])
        db.commit()
        return {"host_id": host.id, "app_id": a.id, "vm_id": v.id,
                "ct_backup": b_ct.id, "vm_backup": b_vm.id}


def _authed(tmp_path, bootstrap_admin, ct_status="stopped"):
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    c = TestClient(app)
    c.__enter__()
    bootstrap_admin(c)
    return app, c, fake, _seed(app, ct_status=ct_status)


# --- ProxmoxClient level ---------------------------------------------------

def test_prune_preview_and_prune_use_different_verbs(tmp_path):
    """The whole point of the preview: it must be structurally incapable of
    deleting anything."""
    from proxploy.services.proxmox import ProxmoxClient
    from tests.fakes.pve import make_fake_factory

    fake = _fake()
    client = ProxmoxClient("https://10.0.0.7:8006", "proxploy@pve!bk", "s3cret",
                           factory=make_fake_factory(fake))
    spec = {"prune-backups": "keep-last=3,keep-daily=7"}
    client.prune_preview("pve1", "local", spec)
    assert fake.prune_gets == [("pve1", "local", spec)]
    assert fake.prune_deletes == []
    client.prune_backups("pve1", "local", spec)
    assert fake.prune_deletes == [("pve1", "local", spec)]
    assert len(fake.prune_gets) == 1  # the preview did not re-run


def test_restore_guest_posts_to_the_guest_create_endpoint(tmp_path):
    from proxploy.services.proxmox import ProxmoxClient
    from tests.fakes.pve import make_fake_factory

    fake = _fake()
    client = ProxmoxClient("https://10.0.0.7:8006", "proxploy@pve!bk", "s3cret",
                           factory=make_fake_factory(fake))
    client.restore_guest("lxc", "pve1", 150, {"ostemplate": VOLID_CT, "restore": 1})
    kind, node, kwargs = fake.creates[0]
    assert (kind, node) == ("lxc", "pve1")
    assert kwargs == {"vmid": 150, "ostemplate": VOLID_CT, "restore": 1}


# --- job handlers ----------------------------------------------------------

def _run_job(tmp_path, kind, params, seed_status="stopped"):
    from proxploy.jobs import JobBackend
    from tests.support import make_job_app

    async def go():
        fake = _fake()
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.backupjobs  # noqa: F401, registers backup.*

        backend = JobBackend(app)
        ids = _seed(app, ct_status=seed_status)
        with app.state.sessionmaker() as db:
            jid = backend.enqueue(db, kind=kind, params={k: (ids[v] if isinstance(v, str)
                                                             and v in ids else v)
                                                         for k, v in params.items()}).id
        await backend.wait(jid, timeout=10)
        with app.state.sessionmaker() as db:
            return fake, db.get(Job, jid).status, db.get(Job, jid).result, \
                db.get(Job, jid).error

    return asyncio.run(go())


def test_backup_run_calls_vzdump_with_the_selected_vmids(tmp_path):
    fake, status, result, error = _run_job(
        tmp_path, "backup.run",
        {"host_id": "host_id", "vmids": [150, 201], "storage": "local"})
    assert status == "succeeded", error
    node, kwargs = fake.vzdumps[0]
    assert node == "pve1"
    assert kwargs["vmid"] == "150,201" and kwargs["storage"] == "local"
    assert kwargs["mode"] == "snapshot" and "all" not in kwargs
    assert result["exitstatus"] == "OK"


def test_backup_run_with_no_vmids_backs_up_all_guests(tmp_path):
    fake, status, _, error = _run_job(tmp_path, "backup.run",
                                      {"host_id": "host_id", "vmids": []})
    assert status == "succeeded", error
    _node, kwargs = fake.vzdumps[0]
    assert kwargs["all"] == 1 and "vmid" not in kwargs


def test_restore_as_new_takes_a_fresh_vmid_and_never_forces(tmp_path):
    fake, status, result, error = _run_job(tmp_path, "backup.restore",
                                           {"backup_id": "ct_backup", "mode": "new"})
    assert status == "succeeded", error
    kind, _node, kwargs = fake.creates[0]
    assert kind == "lxc"
    assert kwargs["vmid"] == 999  # cluster_nextid(), not the guest's own 150
    assert kwargs["ostemplate"] == VOLID_CT and kwargs["restore"] == 1
    assert "force" not in kwargs
    assert result["vmid"] == 999 and result["mode"] == "new"


def test_restore_in_place_reuses_the_vmid_and_forces(tmp_path):
    fake, status, result, error = _run_job(tmp_path, "backup.restore",
                                           {"backup_id": "ct_backup", "mode": "in_place"})
    assert status == "succeeded", error
    _kind, _node, kwargs = fake.creates[0]
    assert kwargs["vmid"] == 150 and kwargs["force"] == 1
    assert result["mode"] == "in_place"


def test_restore_of_a_vm_backup_uses_archive_not_ostemplate(tmp_path):
    fake, status, _, error = _run_job(tmp_path, "backup.restore",
                                      {"backup_id": "vm_backup", "mode": "new"})
    assert status == "succeeded", error
    kind, _node, kwargs = fake.creates[0]
    assert kind == "qemu" and kwargs["archive"] == VOLID_VM
    assert "ostemplate" not in kwargs and "restore" not in kwargs


def test_delete_removes_the_volume_and_resyncs_the_cache(tmp_path):
    from proxploy.jobs import JobBackend
    from tests.support import make_job_app

    async def go():
        fake = _fake()
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.backupjobs  # noqa: F401

        backend = JobBackend(app)
        ids = _seed(app)
        fake.content_by_storage["local"] = []  # upstream now has nothing
        with app.state.sessionmaker() as db:
            jid = backend.enqueue(db, kind="backup.delete",
                                  params={"backup_id": ids["ct_backup"]}).id
        await backend.wait(jid, timeout=10)
        with app.state.sessionmaker() as db:
            assert db.get(Job, jid).status == "succeeded", db.get(Job, jid).error
            # the resync ran: the cache no longer lists what was deleted
            assert db.query(Backup).count() == 0
        assert fake.deleted_volumes == [("pve1", "local", VOLID_CT)]

    asyncio.run(go())


def test_prune_job_uses_the_hyphenated_param(tmp_path):
    fake, status, result, error = _run_job(
        tmp_path, "backup.prune",
        {"host_id": "host_id", "storage": "local",
         "spec": "keep-last=3,keep-daily=7", "guest_type": "ct"})
    assert status == "succeeded", error
    _node, _storage, kwargs = fake.prune_deletes[0]
    assert kwargs["prune-backups"] == "keep-last=3,keep-daily=7"
    assert kwargs["type"] == "ct"
    assert result["spec"] == "keep-last=3,keep-daily=7"


# --- routes ----------------------------------------------------------------

def test_run_route_enqueues_a_job_and_audits(tmp_path, csrf_header, bootstrap_admin):
    from proxploy.models import AuditEvent

    app, c, _fake_, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        r = c.post("/api/v1/backups/run",
                   json={"guests": [{"type": "app", "id": ids["app_id"]}]},
                   headers=csrf_header(c))
        assert r.status_code == 202, r.text
        assert r.json()["job"]["kind"] == "backup.run"
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="backup.run").one()
            assert row.job_id is not None and row.target_id == ids["host_id"]


def test_run_route_rejects_guests_spread_across_hosts(tmp_path, csrf_header,
                                                      bootstrap_admin):
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        with app.state.sessionmaker() as db:
            h2 = Host(name="host-02", address="https://10.0.0.8:8006",
                      node_name="pve2", status="connected")
            db.add(h2)
            db.commit()
            v2 = Vm(host_id=h2.id, vmid=300, name="other", status="stopped")
            db.add(v2)
            db.commit()
            other_vm = v2.id
        r = c.post("/api/v1/backups/run",
                   json={"guests": [{"type": "app", "id": ids["app_id"]},
                                    {"type": "vm", "id": other_vm}]},
                   headers=csrf_header(c))
        assert r.status_code == 422


def test_in_place_restore_requires_the_typed_name(tmp_path, csrf_header,
                                                  bootstrap_admin):
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        r = c.post(f"/api/v1/backups/{ids['ct_backup']}/restore",
                   json={"mode": "in_place"}, headers=csrf_header(c))
        assert r.status_code == 409
        # main.py::problem_handler does `body.update(exc.detail)` for a dict
        # detail, so a dict HTTPException body serialises FLAT, not nested
        # under "detail": same shape test_lifecycle_api.py already asserts.
        assert r.json()["error"] == "confirm_required"
        assert r.json()["confirm_phrase"] == "Immich"
        r = c.post(f"/api/v1/backups/{ids['ct_backup']}/restore",
                   json={"mode": "in_place", "confirm": "Immich"},
                   headers=csrf_header(c))
        assert r.status_code == 202, r.text


def test_in_place_restore_refuses_a_running_guest(tmp_path, csrf_header,
                                                  bootstrap_admin):
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin, ct_status="running")
    with c:
        r = c.post(f"/api/v1/backups/{ids['ct_backup']}/restore",
                   json={"mode": "in_place", "confirm": "Immich"},
                   headers=csrf_header(c))
        assert r.status_code == 409
        assert r.json()["error"] == "guest_running"


def test_in_place_restore_over_proxploy_itself_is_refused_even_with_confirm(
        tmp_path, csrf_header, bootstrap_admin):
    from proxploy.services.settings import set_setting

    app, c, _f, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        with app.state.sessionmaker() as db:
            set_setting(db, "self.ctid", "150")
            set_setting(db, "self.host_id", str(ids["host_id"]))
        r = c.post(f"/api/v1/backups/{ids['ct_backup']}/restore",
                   json={"mode": "in_place", "confirm": "Immich"},
                   headers=csrf_header(c))
        assert r.status_code == 409
        body = r.json()["detail"]
        assert body["error"] == "self_target" and body["confirm_phrase"] == "Immich"
        with app.state.sessionmaker() as db:
            assert db.query(Job).filter_by(kind="backup.restore").count() == 0
        # restore-as-new over the same backup is fine: it takes a fresh vmid
        r = c.post(f"/api/v1/backups/{ids['ct_backup']}/restore",
                   json={"mode": "new"}, headers=csrf_header(c))
        assert r.status_code == 202, r.text


def test_restore_as_new_needs_no_confirmation(tmp_path, csrf_header, bootstrap_admin):
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin, ct_status="running")
    with c:
        r = c.post(f"/api/v1/backups/{ids['ct_backup']}/restore", json={},
                   headers=csrf_header(c))
        assert r.status_code == 202, r.text  # default mode is "new"


def test_prune_preview_route_reads_and_prune_route_deletes(tmp_path, csrf_header,
                                                           bootstrap_admin):
    app, c, fake, ids = _authed(tmp_path, bootstrap_admin)
    fake.prune_preview_rows = [{"volid": VOLID_CT, "type": "ct", "vmid": 150,
                                "ctime": 1753840800, "mark": "remove"}]
    with c:
        r = c.get(f"/api/v1/backups/prune-preview?host_id={ids['host_id']}"
                  f"&storage=local&keep_last=3&keep_daily=7")
        assert r.status_code == 200
        assert r.json()[0]["mark"] == "remove"
        assert fake.prune_gets[0][2]["prune-backups"] == "keep-last=3,keep-daily=7"
        assert fake.prune_deletes == []  # the preview deleted nothing
        r = c.post("/api/v1/backups/prune",
                   json={"host_id": ids["host_id"], "storage": "local",
                         "keep_last": 3}, headers=csrf_header(c))
        assert r.status_code == 202, r.text


def test_prune_without_any_keep_value_is_rejected(tmp_path, csrf_header,
                                                  bootstrap_admin):
    app, c, fake, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        r = c.get(f"/api/v1/backups/prune-preview?host_id={ids['host_id']}"
                  f"&storage=local")
        assert r.status_code == 422  # an empty spec would mark everything `remove`
        r = c.post("/api/v1/backups/prune",
                   json={"host_id": ids["host_id"], "storage": "local"},
                   headers=csrf_header(c))
        assert r.status_code == 422
        assert fake.prune_deletes == []


def test_delete_route_enqueues(tmp_path, csrf_header, bootstrap_admin):
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        r = c.request("DELETE", f"/api/v1/backups/{ids['ct_backup']}",
                      headers=csrf_header(c))
        assert r.status_code == 202, r.text
        assert r.json()["job"]["kind"] == "backup.delete"


def test_every_mutation_is_authenticated(tmp_path):
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        assert c.post("/api/v1/backups/run", json={}).status_code == 401
        assert c.post("/api/v1/backups/1/restore", json={}).status_code == 401
        assert c.request("DELETE", "/api/v1/backups/1").status_code == 401
        assert c.get("/api/v1/backups/prune-preview").status_code == 401
        assert c.post("/api/v1/backups/prune", json={}).status_code == 401


def test_literal_routes_are_registered_above_the_id_routes(tmp_path):
    from tests.support import make_app

    paths = [r.path for r in make_app(tmp_path).routes if hasattr(r, "path")]
    assert paths.index("/api/v1/backups/run") < paths.index(
        "/api/v1/backups/{backup_id}/restore")
    assert paths.index("/api/v1/backups/prune-preview") < paths.index(
        "/api/v1/backups/{backup_id}")


def test_selfguard_destructive_set_is_unchanged():
    """Backup restore/delete are NOT lifecycle verbs, see this task's note."""
    from proxploy.services.selfguard import DESTRUCTIVE

    assert DESTRUCTIVE == frozenset({"stop", "shutdown", "restart", "pause"})
```

- [ ] **Step 2: Run to verify failures**

Run: `cd backend && pytest tests/test_backups_api.py -q`
Expected: FAIL, the client-level tests fail with `AttributeError: 'ProxmoxClient' object has no attribute 'prune_preview'`, the job tests with `KeyError: "no handler registered for job kind 'backup.run'"`, and the route tests with `assert 404 == 202`.

- [ ] **Step 3: Add the four `ProxmoxClient` methods**

In `backend/proxploy/services/proxmox.py`, after `task_log`:

```python
    def vzdump(self, node: str, params: dict) -> str:
        """POST /nodes/{node}/vzdump -> UPID. `params` carries `vmid` (a comma
        string) or `all=1`, plus storage/mode/compress."""
        try:
            return self._connect().nodes(node).vzdump.post(**params)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"vzdump failed on {node}", e) from e

    def restore_guest(self, kind: str, node: str, vmid: int, params: dict) -> str:
        """Restore is a create-with-archive, not its own endpoint.

        A CT restore POSTs /nodes/{node}/lxc with `ostemplate=<volid>` +
        `restore=1`; a VM restore POSTs /nodes/{node}/qemu with
        `archive=<volid>`. `vmid` is the TARGET id: the guest's own for an
        in-place restore (which also needs `force=1` and a stopped guest), a
        fresh `cluster_nextid()` for a restore-as-new. Building that decision
        is the caller's; this method only posts it.
        """
        if kind not in ("lxc", "qemu"):
            raise ProxmoxError(f"{kind!r} is not a restorable guest kind")
        try:
            return getattr(self._connect().nodes(node), kind).post(vmid=int(vmid),
                                                                   **params)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"restore of {kind}/{vmid} failed on {node}", e) from e

    def prune_preview(self, node: str, storage: str, params: dict) -> list[dict]:
        """GET /nodes/{node}/storage/{storage}/prunebackups, a DRY RUN.

        Marks each volume keep|remove|protected and deletes nothing. The real
        deletion is the DELETE verb in prune_backups() below; the two must stay
        separate methods so no caller can reach the destructive one by accident.
        `params` is a dict because `prune-backups` is hyphenated and cannot be a
        Python kwarg.
        """
        try:
            return self._connect().nodes(node).storage(storage).prunebackups.get(**params)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"prune preview failed for {storage} on {node}", e) from e

    def prune_backups(self, node: str, storage: str, params: dict) -> str:
        """DELETE /nodes/{node}/storage/{storage}/prunebackups -> UPID. This one
        really deletes; run prune_preview() with the same `params` first."""
        try:
            return self._connect().nodes(node).storage(storage).prunebackups.delete(**params)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"prune failed for {storage} on {node}", e) from e
```

- [ ] **Step 4: Add the FakePVE leaves**

In `backend/tests/fakes/pve.py`, add these classes next to the existing leaves:

```python
class _VzdumpLeaf:
    def __init__(self, owner, node):
        self._owner, self._node = owner, node

    def post(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.vzdumps.append((self._node, kwargs))
        return self._owner._record_action("vzdump", int(kwargs.get("vmid", 0) or 0),
                                          "vzdump")


class _PruneLeaf:
    """nodes(n).storage(s).prunebackups.get() previews.delete() deletes.
    Recorded separately so a test can prove the preview never deletes."""

    def __init__(self, owner, node, storage):
        self._owner, self._node, self._storage = owner, node, storage

    def get(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.prune_gets.append((self._node, self._storage, kwargs))
        return self._owner.prune_preview_rows

    def delete(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.prune_deletes.append((self._node, self._storage, kwargs))
        return self._owner._record_action("prune", 0, "prune")
```

Wire `_VzdumpLeaf` into `_NodeNS.__init__`:

```python
        self.vzdump = _VzdumpLeaf(owner, name)
```

Wire `_PruneLeaf` into the storage namespace class Task 1 added (`_StorageNS`, the
object `.nodes(n).storage(name)` returns), one line in its `__init__`, alongside
its existing `.status` / `.content` attributes:

```python
        self.prunebackups = _PruneLeaf(owner, node, name)
```

Give `_GuestFactory` a `.post()` so `.nodes(n).lxc.post(...)` works (the guest
*create* endpoint, restore here, `vm.create` in Task 11):

```python
    def post(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.creates.append((self._kind, self._node, kwargs))
        return self._owner._record_action(self._kind, int(kwargs.get("vmid", 0)),
                                          "create")
```

And in `FakePVE.__init__`, after the console-call block:

```python
        # backup / restore / prune recording (Phase 6)
        self.vzdumps: list[tuple[str, dict]] = []
        self.creates: list[tuple[str, str, dict]] = []
        self.prune_gets: list[tuple[str, str, dict]] = []
        self.prune_deletes: list[tuple[str, str, dict]] = []
        self.prune_preview_rows: list[dict] = []
```

- [ ] **Step 5: Add the shared resolve + resync helpers**

Append to `backend/proxploy/services/backupjobs.py`:

```python
from proxploy.jobs import JobFailed  # add to the existing proxploy.jobs import
from proxploy.services.pvetask import await_task


def _host_target(app, host_id: int):
    """Blocking: host id -> (client, node, host name)."""
    with app.state.sessionmaker() as db:
        host = db.get(Host, host_id)
        if host is None:
            raise JobFailed(f"host {host_id} not found")
        return client_for_host(app, db, host), host.node_name or "", host.name


def _backup_target(app, backup_id: int):
    """Blocking: backup id -> (client, node, plain dict of the row's fields).

    The row itself is not returned: the resync at the end of every mutation may
    delete it, and a detached ORM object would then be unreadable.
    """
    with app.state.sessionmaker() as db:
        b = db.get(Backup, backup_id)
        if b is None:
            raise JobFailed(f"backup {backup_id} not found")
        host = db.get(Host, b.host_id)
        if host is None:
            raise JobFailed(f"host {b.host_id} not found")
        info = {"host_id": b.host_id, "volid": b.volid, "storage": b.storage,
                "guest_type": b.guest_type, "guest_vmid": b.guest_vmid,
                "guest_name": b.guest_name}
        return client_for_host(app, db, host), host.node_name or "", info


async def _resync(ctx: JobContext, host_id: int) -> None:
    """Every backup mutation ends here. Without it the cache still lists a
    volume that was just deleted, or misses one that was just created.

    A failed resync is logged, not raised: the mutation upstream already
    succeeded, and failing the job over a stale cache would misreport it.
    """
    app = ctx.backend.app
    try:
        r = await asyncio.to_thread(sync_host_backups, app, host_id)
    except Exception as e:  # noqa: BLE001
        ctx.log(f"backup cache resync failed: {e}", stream="stderr")
        return
    ctx.log(f"backup cache resynced: {r['synced']} cached, {r['dropped']} dropped")
    app.state.bus.publish("resource", {"type": "backup", "change": "list"})
```

- [ ] **Step 6: Add the `backup.run` handler**

Append to `backend/proxploy/services/backupjobs.py`:

```python
async def run_backup(ctx: JobContext, params: dict) -> dict:
    """`backup.run`, one vzdump task over the selected guests, or all of them."""
    app = ctx.backend.app
    host_id = int(params["host_id"])
    client, node, host_name = await asyncio.to_thread(_host_target, app, host_id)
    vmids = [int(v) for v in (params.get("vmids") or [])]
    call = {"mode": params.get("mode") or "snapshot",
            "compress": params.get("compress") or "zstd"}
    if params.get("storage"):
        call["storage"] = params["storage"]
    if vmids:
        call["vmid"] = ",".join(str(v) for v in vmids)
    else:
        call["all"] = 1  # empty selection means every guest on the node
    ctx.log(f"vzdump on {host_name}/{node}: "
            f"{'all guests' if not vmids else ', '.join(str(v) for v in vmids)}")
    upid = await asyncio.to_thread(client.vzdump, node, call)
    status = await await_task(ctx, client, node, upid)
    await _resync(ctx, host_id)
    return {"upid": upid, "exitstatus": status.get("exitstatus"), "vmids": vmids}


HANDLERS["backup.run"] = run_backup
```

- [ ] **Step 7: Add the `backup.restore` handler**

Append to `backend/proxploy/services/backupjobs.py`:

```python
async def restore_backup(ctx: JobContext, params: dict) -> dict:
    """`backup.restore`, in place (same vmid, force=1) or as new (fresh vmid).

    The route already refused an in-place restore over a running guest or over
    Proxploy itself; this handler assumes that gate was passed.
    """
    app = ctx.backend.app
    in_place = params.get("mode") == "in_place"
    client, node, info = await asyncio.to_thread(
        _backup_target, app, int(params["backup_id"]))
    kind = "lxc" if info["guest_type"] == "ct" else "qemu"
    if in_place:
        if not info["guest_vmid"]:
            raise JobFailed(f"{info['volid']} carries no guest id to restore over")
        vmid = int(info["guest_vmid"])
    else:
        vmid = await asyncio.to_thread(client.cluster_nextid)
    call = ({"ostemplate": info["volid"], "restore": 1} if kind == "lxc"
            else {"archive": info["volid"]})
    if params.get("storage"):
        call["storage"] = params["storage"]
    if in_place:
        call["force"] = 1  # overwrite the existing guest; PVE requires it stopped
    ctx.log(f"restoring {info['volid']} to {kind} {vmid} on {node} "
            f"({'in place' if in_place else 'as new'})")
    upid = await asyncio.to_thread(client.restore_guest, kind, node, vmid, call)
    status = await await_task(ctx, client, node, upid)
    await _resync(ctx, info["host_id"])
    return {"upid": upid, "exitstatus": status.get("exitstatus"), "vmid": vmid,
            "mode": "in_place" if in_place else "new"}


HANDLERS["backup.restore"] = restore_backup
```

- [ ] **Step 8: Add the `backup.delete` and `backup.prune` handlers**

Append to `backend/proxploy/services/backupjobs.py`:

```python
async def delete_backup(ctx: JobContext, params: dict) -> dict:
    """`backup.delete`, remove one archive upstream, then re-mirror."""
    app = ctx.backend.app
    client, node, info = await asyncio.to_thread(
        _backup_target, app, int(params["backup_id"]))
    ctx.log(f"deleting {info['volid']} from {info['storage']} on {node}")
    upid = await asyncio.to_thread(client.storage_delete_volume, node,
                                   info["storage"], info["volid"])
    if upid:
        await await_task(ctx, client, node, upid)
    else:
        # Some storage plugins delete synchronously and return no task id.
        ctx.log("storage deleted the volume synchronously (no task id)")
        ctx.progress(100)
    await _resync(ctx, info["host_id"])
    return {"upid": upid, "volid": info["volid"]}


async def prune_backups_job(ctx: JobContext, params: dict) -> dict:
    """`backup.prune`, apply a retention spec for real. `spec` was built and
    validated by the route; an empty one would mark every archive `remove`."""
    app = ctx.backend.app
    host_id = int(params["host_id"])
    client, node, host_name = await asyncio.to_thread(_host_target, app, host_id)
    node = params.get("node") or node
    storage = params["storage"]
    # `prune-backups` is hyphenated: a dict that gets unpacked at the proxmoxer
    # call, never a Python kwarg.
    call = {"prune-backups": params["spec"]}
    if params.get("guest_type"):
        call["type"] = params["guest_type"]
    if params.get("vmid"):
        call["vmid"] = int(params["vmid"])
    ctx.log(f"pruning {storage} on {host_name}/{node} with {params['spec']}")
    upid = await asyncio.to_thread(client.prune_backups, node, storage, call)
    status = await await_task(ctx, client, node, upid)
    await _resync(ctx, host_id)
    return {"upid": upid, "exitstatus": status.get("exitstatus"),
            "spec": params["spec"], "storage": storage}


HANDLERS["backup.delete"] = delete_backup
HANDLERS["backup.prune"] = prune_backups_job
```

- [ ] **Step 9: Add the run + restore routes**

In `backend/proxploy/api/backups.py`, extend the imports and add the two role
singletons under `_require_viewer`:

```python
from typing import Literal

from fastapi import Body, HTTPException
from pydantic import BaseModel

from proxploy.api.jobs import enqueue_and_audit
from proxploy.models import App, Backup, Host, User, Vm, utcnow
from proxploy.services.audit import write_audit
from proxploy.services.selfguard import is_self

_require_operator = require_role("operator")
_require_admin = require_role("admin")
```

Then append (these literal-segment routes are declared **before** any
`/{backup_id}` route, Starlette matches in registration order):

```python
class GuestRef(BaseModel):
    type: str  # "app" | "vm", Proxploy row ids, never raw vmids
    id: int


class RunIn(BaseModel):
    guests: list[GuestRef] | Literal["all"] = "all"
    host_id: int | None = None
    storage: str | None = None
    mode: str = "snapshot"
    compress: str = "zstd"


def _resolve_guests(db, body: RunIn) -> tuple[int, list[int]]:
    """-> (host_id, vmids). One vzdump call runs on one node, so a selection
    spanning hosts is a client error, not a silent partial backup."""
    if body.guests == "all":
        hosts = db.query(Host).all()
        if body.host_id is None:
            if len(hosts) != 1:
                raise HTTPException(422, "host_id is required when more than one "
                                         "host is registered")
            return hosts[0].id, []
        if db.get(Host, body.host_id) is None:
            raise HTTPException(404, "host not found")
        return body.host_id, []
    vmids: list[int] = []
    host_ids: set[int] = set()
    for g in body.guests:
        if g.type == "app":
            row = db.get(App, g.id)
            vmid = row.ctid if row else None
        elif g.type == "vm":
            row = db.get(Vm, g.id)
            vmid = row.vmid if row else None
        else:
            raise HTTPException(422, "guest type must be 'app' or 'vm'")
        if row is None:
            raise HTTPException(404, f"{g.type} {g.id} not found")
        vmids.append(int(vmid))
        host_ids.add(row.host_id)
    if not vmids:
        raise HTTPException(422, "select at least one guest, or pass guests='all'")
    if len(host_ids) != 1:
        raise HTTPException(422, "every guest in one backup run must live on the "
                                 "same host")
    return host_ids.pop(), vmids


@router.post("/run", status_code=202,
             dependencies=[Depends(_require_operator),
                           Depends(require_entitlement("backups.run"))])
def run_backup_route(request: Request, body: RunIn = Body(default=RunIn()),
                     db=Depends(get_db), user: User = Depends(_require_operator)):
    host_id, vmids = _resolve_guests(db, body)
    return enqueue_and_audit(request, db, user, kind="backup.run",
                             target_type="host", target_id=host_id,
                             params={"host_id": host_id, "vmids": vmids,
                                     "storage": body.storage, "mode": body.mode,
                                     "compress": body.compress})


class RestoreIn(BaseModel):
    mode: str = "new"  # "new" | "in_place"
    storage: str | None = None
    confirm: str | None = None


def _guest_for(db, b: Backup):
    """The live guest a backup came from, if it still exists -> (row, name)."""
    if b.guest_type == "ct":
        row = db.query(App).filter_by(host_id=b.host_id, ctid=b.guest_vmid).one_or_none()
    else:
        row = db.query(Vm).filter_by(host_id=b.host_id, vmid=b.guest_vmid).one_or_none()
    if row is None:
        return None, ""
    return row, row.name or f"{b.guest_type}-{b.guest_vmid}"


@router.post("/{backup_id}/restore", status_code=202,
             dependencies=[Depends(_require_admin),
                           Depends(require_entitlement("backups.restore"))])
def restore_backup_route(request: Request, backup_id: int,
                         body: RestoreIn = Body(default=RestoreIn()),
                         db=Depends(get_db), user: User = Depends(_require_admin)):
    b = db.get(Backup, backup_id)
    if b is None:
        raise HTTPException(404, "backup not found")
    if body.mode not in ("new", "in_place"):
        raise HTTPException(422, "mode must be 'new' or 'in_place'")
    ip = request.client.host if request.client else None
    if body.mode == "in_place":
        # In place means force=1 over the guest's own vmid: the existing disk is
        # replaced. Restore-as-new takes a fresh id from cluster_nextid() and
        # touches nothing live, which is why it needs none of this.
        guest, name = _guest_for(db, b)
        if guest is None:
            raise HTTPException(409, {
                "error": "guest_missing",
                "detail": (f"{b.guest_type} {b.guest_vmid} no longer exists on this "
                           f"host, restore as new instead.")})
        if isinstance(guest, App) and is_self(db, "app", guest.id):
            # Unlike enqueue_lifecycle's confirmable stop, this one is refused
            # outright: an in-place restore over Proxploy's own CT destroys the
            # container running the job that is performing the restore, so there
            # is no phrase that makes it survivable. The response keeps the
            # familiar self_target shape so the UI can name the target; the
            # front end shows `detail`, not a confirm box, for this case.
            write_audit(db, actor_type="user", actor_id=user.id,
                        action="backup.restore", target_type="backup",
                        target_id=b.id, result="denied", ip=ip)
            raise HTTPException(409, {
                "error": "self_target", "confirm_phrase": name,
                "detail": (f"{name} is the container Proxploy itself runs in. An "
                           f"in-place restore would overwrite Proxploy mid-restore "
                           f"and strand the job doing it. Restore as new instead.")})
        if (body.confirm or "") != name:
            raise HTTPException(409, {
                "error": "confirm_required", "confirm_phrase": name,
                "detail": (f"An in-place restore overwrites {name} with the contents "
                           f"of this backup. Type the name to confirm.")})
        status = getattr(guest, "status_cached", None) or getattr(guest, "status", None)
        if status == "running":
            raise HTTPException(409, {
                "error": "guest_running",
                "detail": f"stop {name} before restoring over it"})
    return enqueue_and_audit(request, db, user, kind="backup.restore",
                             target_type="backup", target_id=b.id,
                             params={"backup_id": b.id, "mode": body.mode,
                                     "storage": body.storage})
```

**Note for the reviewer:** `services/selfguard.py` is deliberately untouched, 
`DESTRUCTIVE` holds guest *lifecycle verbs* and its only consumer is
`enqueue_lifecycle`, which backup routes never call. See this task's header note;
`test_selfguard_destructive_set_is_unchanged` locks it.

- [ ] **Step 10: Add the delete, prune-preview and prune routes**

Append to `backend/proxploy/api/backups.py`. Register `/prune-preview` and
`/prune` **above** `DELETE /{backup_id}` for the same registration-order reason:

```python
KEEP_FIELDS = ("keep_last", "keep_daily", "keep_weekly", "keep_monthly", "keep_yearly")


def _prune_spec(values: dict) -> str:
    """`{"keep_last": 3, "keep_daily": 7}` -> `"keep-last=3,keep-daily=7"`.

    Refuses an empty spec: PVE reads no keep-* rules as "keep nothing", so a
    dropped form field would mark every archive `remove`.
    """
    parts = [f"{k.replace('_', '-')}={int(v)}" for k in KEEP_FIELDS
             if (v := values.get(k))]
    if not parts:
        raise HTTPException(422, "at least one keep-* retention value is required")
    return ",".join(parts)


def _prune_call(spec: str, guest_type: str | None, vmid: int | None) -> dict:
    call = {"prune-backups": spec}  # hyphenated -> dict unpack, never a kwarg
    if guest_type:
        call["type"] = guest_type
    if vmid:
        call["vmid"] = int(vmid)
    return call


@router.get("/prune-preview",
            dependencies=[Depends(_require_admin),
                          Depends(require_entitlement("backups.retention"))])
def prune_preview_route(request: Request, host_id: int, storage: str,
                        node: str | None = None, keep_last: int | None = None,
                        keep_daily: int | None = None, keep_weekly: int | None = None,
                        keep_monthly: int | None = None, keep_yearly: int | None = None,
                        guest_type: str | None = None, vmid: int | None = None,
                        db=Depends(get_db), user: User = Depends(_require_admin)):
    """Dry run. Calls the GET verb only, this endpoint cannot delete anything;
    POST /backups/prune is the one that does."""
    host = db.get(Host, host_id)
    if host is None:
        raise HTTPException(404, "host not found")
    spec = _prune_spec({"keep_last": keep_last, "keep_daily": keep_daily,
                        "keep_weekly": keep_weekly, "keep_monthly": keep_monthly,
                        "keep_yearly": keep_yearly})
    client = client_for_host(request.app, db, host)
    rows = client.prune_preview(node or host.node_name or "", storage,
                                _prune_call(spec, guest_type, vmid))
    return [{"volid": r.get("volid"), "type": r.get("type"), "vmid": r.get("vmid"),
             "ctime": r.get("ctime"), "mark": r.get("mark")} for r in rows]


class PruneIn(BaseModel):
    host_id: int
    storage: str
    node: str | None = None
    keep_last: int | None = None
    keep_daily: int | None = None
    keep_weekly: int | None = None
    keep_monthly: int | None = None
    keep_yearly: int | None = None
    guest_type: str | None = None
    vmid: int | None = None


@router.post("/prune", status_code=202,
             dependencies=[Depends(_require_admin),
                           Depends(require_entitlement("backups.retention"))])
def prune_route(request: Request, body: PruneIn, db=Depends(get_db),
                user: User = Depends(_require_admin)):
    if db.get(Host, body.host_id) is None:
        raise HTTPException(404, "host not found")
    spec = _prune_spec(body.model_dump())
    return enqueue_and_audit(request, db, user, kind="backup.prune",
                             target_type="host", target_id=body.host_id,
                             params={"host_id": body.host_id, "node": body.node,
                                     "storage": body.storage, "spec": spec,
                                     "guest_type": body.guest_type,
                                     "vmid": body.vmid})


@router.delete("/{backup_id}", status_code=202,
               dependencies=[Depends(_require_admin),
                             Depends(require_entitlement("backups.pbs"))])
def delete_backup_route(request: Request, backup_id: int, db=Depends(get_db),
                        user: User = Depends(_require_admin)):
    b = db.get(Backup, backup_id)
    if b is None:
        raise HTTPException(404, "backup not found")
    return enqueue_and_audit(request, db, user, kind="backup.delete",
                             target_type="backup", target_id=b.id,
                             params={"backup_id": b.id, "volid": b.volid})
```

Add the one import `prune_preview_route` needs to the top of the file:

```python
from proxploy.services.hostclient import client_for_host
```

- [ ] **Step 11: Run the task's tests**

Run: `cd backend && pytest tests/test_backups_api.py -q`
Expected: PASS, 20 passed.

- [ ] **Step 12: Run the full backend suite**

Run: `cd backend && pytest tests/ -q -m "not pve_integration and not e2e"`
Expected: Task 8's total + 20 passed, 0 failed, 0 errors. `test_route_auth_invariant.py` must still pass, all five new routes put the role singleton at position 0 in `dependencies=[...]`.

- [ ] **Step 13: Commit**

```bash
git add backend/proxploy/services/proxmox.py backend/proxploy/services/backupjobs.py backend/proxploy/api/backups.py backend/tests/fakes/pve.py backend/tests/test_backups_api.py
git commit -m "feat(backups): run, restore (in place/as new), delete and prune jobs + routes"
```

---

## Task 10: VM snapshots: list / create / rollback / delete

**Files:**
- Modify: `backend/proxploy/services/proxmox.py`, `backend/proxploy/services/guestjobs.py`, `backend/proxploy/api/vms.py`, `backend/tests/fakes/pve.py`
- Test: `backend/tests/test_snapshots_api.py`

**Interfaces:**
- Consumes (Task 1): `proxploy.services.hostclient.client_for_host(app, db, host) -> ProxmoxClient`, `ProxmoxClient.snapshots(kind: str, node: str, vmid: int) -> list[dict]`, FakePVE's `snapshots_by_guest: dict[tuple[str, int], list[dict]]` and its `_SnapshotNS` read class.
- Consumes (Task 2): `proxploy.services.pvetask.await_task(ctx, client, node, upid, *, timeout_s=300.0, start_pct=10, end_pct=100) -> dict`; `proxploy.api.jobs.enqueue_and_audit(request, db, user, *, kind, target_type, target_id, params, action=None) -> dict`.
- Consumes (Task 7): `proxploy/services/guestjobs.py` (created there, already imported in `main.py`'s lifespan `# noqa: F401` block, this task only appends to it).
- Consumes (existing): `proxploy.api.deps.{get_db, require_role, require_entitlement}`, `proxploy.jobs.{HANDLERS, JobContext, JobFailed}`, `proxploy.services.audit.write_audit`, `proxploy.api.jobs.job_out`.
- Produces:
  - `ProxmoxClient.snapshot_create(kind: str, node: str, vmid: int, name: str, description: str | None = None, vmstate: bool = False) -> str` (UPID)
  - `ProxmoxClient.snapshot_rollback(kind: str, node: str, vmid: int, name: str) -> str` (UPID)
  - `ProxmoxClient.snapshot_delete(kind: str, node: str, vmid: int, name: str) -> str` (UPID)
  - `proxploy/services/guestjobs.py::_vm_target(app, vm_id: int) -> tuple[ProxmoxClient, str, int, str, int]`: blocking; `(client, node, vmid, name, host_id)`
  - job kinds `vm.snapshot_create`, `vm.snapshot_rollback`, `vm.snapshot_delete`
  - `proxploy/api/vms.py`: `SNAP_NAME_RE`, `_snapshot_out(s: dict) -> dict`, routes
    `GET /api/v1/vms/{vm_id}/snapshots` (viewer, `vms.snapshots`),
    `POST /api/v1/vms/{vm_id}/snapshots` (operator, `vms.snapshots`),
    `POST /api/v1/vms/{vm_id}/snapshots/{name}/rollback` (admin, `vms.snapshots`),
    `DELETE /api/v1/vms/{vm_id}/snapshots/{name}` (operator, `vms.snapshots`)
    **all four registered above the `POST /{vm_id}/{action}` wildcard**
  - FakePVE: `_SnapshotNS` gains `.post()` and `__call__`; new `_SnapshotItemNS`, `_RollbackLeaf`; recorders `fake.snapshot_creates`, `fake.snapshot_rollbacks`, `fake.snapshot_deletes`

**No migration.** Snapshots are never persisted, doc 05 says "List snapshots (live from Proxmox)" and there is no snapshot model anywhere in `models/__init__.py`. The GET below reads Proxmox on every request.

**The headline risk of this task is route ordering.** `api/vms.py` ends with the
catch-all `POST /{vm_id}/{action}` and Starlette matches in registration order.
Registered after it, `POST /api/v1/vms/3/snapshots` would be dispatched into
`vm_lifecycle` with `action="snapshots"` and 422 with "action must be one of
start, stop, …". Step 1 writes a test that fails on exactly that, and the
route-order assertion is separate from the behavioural one so a future
re-ordering is caught by both.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_snapshots_api.py
"""VM snapshots (doc 05 §VMs, doc 01 §4 "with-RAM option surfaced").

Two properties here are load-bearing and each gets its own test:
  1. all four routes sit ABOVE api/vms.py's POST /{vm_id}/{action} wildcard, 
     otherwise POST /vms/3/snapshots is dispatched as the lifecycle action
     "snapshots" and 422s;
  2. PVE's snapshot list carries a synthetic `current` pseudo-snapshot for the
     running state. It is not a real snapshot and rolling back "to current" is
     meaningless, so the GET filters it out.
"""
import asyncio
import json

from fastapi.testclient import TestClient

from proxploy.models import App, AuditEvent, Host, HostCredential, Job, Vm

SNAPS = [
    {"name": "current", "description": "You are here!", "digest": "abc"},
    {"name": "base", "description": "fresh install", "snaptime": 1753840800,
     "vmstate": 0},
    {"name": "pre-update", "description": "before 2.4", "snaptime": 1753844400,
     "vmstate": 1, "parent": "base"},
]


def _fake():
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    fake.snapshots_by_guest = {("qemu", 201): list(SNAPS)}
    return fake


def _seed(app, vm_status="running"):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.7:8006", node_name="pve1",
                    status="connected", pve_version="8.4.1")
        db.add(host)
        db.commit()
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!snap", "token_secret": "s3cret"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token", encrypted_blob=blob,
                              key_version=ver, public_meta="proxploy@pve!snap"))
        db.add(App(host_id=host.id, ctid=150, name="Immich", slug="immich"))
        v = Vm(host_id=host.id, vmid=201, name="win11", status=vm_status)
        db.add(v)
        db.commit()
        return {"host_id": host.id, "vm_id": v.id}


def _authed(tmp_path, bootstrap_admin, vm_status="running"):
    from tests.support import make_app

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    c = TestClient(app)
    c.__enter__()
    bootstrap_admin(c)
    return app, c, fake, _seed(app, vm_status=vm_status)


# --- ProxmoxClient level ---------------------------------------------------

def test_snapshot_client_calls_hit_the_right_pve_paths(tmp_path):
    from proxploy.services.proxmox import ProxmoxClient
    from tests.fakes.pve import make_fake_factory

    fake = _fake()
    client = ProxmoxClient("https://10.0.0.7:8006", "proxploy@pve!snap", "s3cret",
                           factory=make_fake_factory(fake))
    upid = client.snapshot_create("qemu", "pve1", 201, "pre-update",
                                  description="before 2.4", vmstate=True)
    assert upid.startswith("UPID:")
    kind, node, vmid, kwargs = fake.snapshot_creates[0]
    assert (kind, node, vmid) == ("qemu", "pve1", 201)
    assert kwargs == {"snapname": "pre-update", "description": "before 2.4",
                      "vmstate": 1}
    client.snapshot_rollback("qemu", "pve1", 201, "base")
    assert fake.snapshot_rollbacks == [("qemu", "pve1", 201, "base")]
    client.snapshot_delete("qemu", "pve1", 201, "base")
    assert fake.snapshot_deletes == [("qemu", "pve1", 201, "base")]
    # a snapshot without a description must not send description=None
    client.snapshot_create("qemu", "pve1", 201, "plain")
    assert fake.snapshot_creates[1][3] == {"snapname": "plain"}


def test_with_ram_snapshot_is_refused_for_containers(tmp_path):
    """doc 01 §4's with-RAM option is a qemu feature; PVE's lxc snapshot
    endpoint has no vmstate parameter at all."""
    import pytest

    from proxploy.services.proxmox import ProxmoxClient, ProxmoxError
    from tests.fakes.pve import make_fake_factory

    fake = _fake()
    client = ProxmoxClient("https://10.0.0.7:8006", "proxploy@pve!snap", "s3cret",
                           factory=make_fake_factory(fake))
    with pytest.raises(ProxmoxError, match="vmstate"):
        client.snapshot_create("lxc", "pve1", 150, "nope", vmstate=True)
    assert fake.snapshot_creates == []  # refused before the POST


# --- routes ----------------------------------------------------------------

def test_list_snapshots_drops_the_synthetic_current_entry(tmp_path, bootstrap_admin):
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        rows = c.get(f"/api/v1/vms/{ids['vm_id']}/snapshots").json()
        assert [r["name"] for r in rows] == ["base", "pre-update"]
        assert rows[0]["vmstate"] is False and rows[1]["vmstate"] is True
        assert rows[1]["parent"] == "base" and rows[1]["snaptime"] == 1753844400
        assert rows[0]["description"] == "fresh install"


def test_snapshot_routes_are_registered_above_the_lifecycle_wildcard(tmp_path):
    from tests.support import make_app

    paths = [r.path for r in make_app(tmp_path).routes if hasattr(r, "path")]
    wildcard = paths.index("/api/v1/vms/{vm_id}/{action}")
    for p in ("/api/v1/vms/{vm_id}/snapshots",
              "/api/v1/vms/{vm_id}/snapshots/{name}/rollback",
              "/api/v1/vms/{vm_id}/snapshots/{name}"):
        assert paths.index(p) < wildcard, p


def test_post_snapshots_is_not_swallowed_by_the_lifecycle_wildcard(
        tmp_path, csrf_header, bootstrap_admin):
    """The behavioural half of the ordering guarantee: if the wildcard matched
    first this would 422 with 'action must be one of start, stop, …', and if it
    somehow enqueued it would enqueue the kind `vm.snapshots`."""
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        r = c.post(f"/api/v1/vms/{ids['vm_id']}/snapshots",
                   json={"name": "pre-update"}, headers=csrf_header(c))
        assert r.status_code == 202, r.text
        assert r.json()["job"]["kind"] == "vm.snapshot_create"
        with app.state.sessionmaker() as db:
            kinds = {j.kind for j in db.query(Job).all()}
            assert kinds == {"vm.snapshot_create"}
            assert "vm.snapshots" not in kinds


def test_snapshot_name_is_validated(tmp_path, csrf_header, bootstrap_admin):
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin)
    vid = ids["vm_id"]
    with c:
        for bad in ("current", "1bad", "has space", "semi;colon", "../escape", ""):
            r = c.post(f"/api/v1/vms/{vid}/snapshots", json={"name": bad},
                       headers=csrf_header(c))
            assert r.status_code == 422, bad
        # the same rule guards the path parameter on rollback/delete
        assert c.post(f"/api/v1/vms/{vid}/snapshots/..%2Fescape/rollback",
                      json={"confirm": "win11"},
                      headers=csrf_header(c)).status_code in (404, 422)
        with app.state.sessionmaker() as db:
            assert db.query(Job).count() == 0


def test_rollback_requires_the_typed_vm_name(tmp_path, csrf_header, bootstrap_admin):
    """Rollback discards everything written since the snapshot. It reuses the
    same 409 vocabulary as the self-target stop guard so the frontend's existing
    ConfirmSelfDialog renders it unchanged."""
    app, c, fake, ids = _authed(tmp_path, bootstrap_admin)
    vid = ids["vm_id"]
    with c:
        r = c.post(f"/api/v1/vms/{vid}/snapshots/base/rollback", json={},
                   headers=csrf_header(c))
        assert r.status_code == 409
        assert r.json()["error"] == "confirm_required"
        assert r.json()["confirm_phrase"] == "win11"
        with app.state.sessionmaker() as db:
            assert db.query(AuditEvent).filter_by(
                action="vm.snapshot_rollback", result="denied").count() == 1
            assert db.query(Job).count() == 0
        assert c.post(f"/api/v1/vms/{vid}/snapshots/base/rollback",
                      json={"confirm": "nope"},
                      headers=csrf_header(c)).status_code == 409
        ok = c.post(f"/api/v1/vms/{vid}/snapshots/base/rollback",
                    json={"confirm": "win11"}, headers=csrf_header(c))
        assert ok.status_code == 202, ok.text
        assert ok.json()["job"]["kind"] == "vm.snapshot_rollback"


def test_rollback_requires_admin(tmp_path, csrf_header, bootstrap_admin):
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin)
    vid = ids["vm_id"]
    with c:
        c.post("/api/v1/users", json={"email": "op@example.com",
                                      "password": "correct-horse-battery",
                                      "display_name": "Op", "role": "operator"},
               headers=csrf_header(c))
        c.post("/api/v1/auth/login", json={"email": "op@example.com",
                                           "password": "correct-horse-battery"},
               headers=csrf_header(c))
        # an operator may take and delete snapshots …
        assert c.post(f"/api/v1/vms/{vid}/snapshots", json={"name": "opsnap"},
                      headers=csrf_header(c)).status_code == 202
        assert c.request("DELETE", f"/api/v1/vms/{vid}/snapshots/base",
                         headers=csrf_header(c)).status_code == 202
        # … but not roll one back
        r = c.post(f"/api/v1/vms/{vid}/snapshots/base/rollback",
                   json={"confirm": "win11"}, headers=csrf_header(c))
        assert r.status_code == 403 and r.json()["detail"] == "insufficient role"


def test_delete_snapshot_enqueues_and_audits(tmp_path, csrf_header, bootstrap_admin):
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        r = c.request("DELETE", f"/api/v1/vms/{ids['vm_id']}/snapshots/base",
                      headers=csrf_header(c))
        assert r.status_code == 202, r.text
        assert r.json()["job"]["kind"] == "vm.snapshot_delete"
        assert r.json()["job"]["params"]["name"] == "base"
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="vm.snapshot_delete").one()
            assert row.target_type == "vm" and row.target_id == ids["vm_id"]
            assert row.job_id is not None


def test_snapshot_routes_require_auth(tmp_path, csrf_header):
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        ids = _seed(app)
        vid = ids["vm_id"]
        h = csrf_header(c)
        assert c.get(f"/api/v1/vms/{vid}/snapshots").status_code == 401
        assert c.post(f"/api/v1/vms/{vid}/snapshots", json={"name": "x1"},
                      headers=h).status_code == 401
        assert c.post(f"/api/v1/vms/{vid}/snapshots/base/rollback", json={},
                      headers=h).status_code == 401
        assert c.request("DELETE", f"/api/v1/vms/{vid}/snapshots/base",
                         headers=h).status_code == 401


# --- job handlers ----------------------------------------------------------

def _run_job(tmp_path, kind, params_from_ids):
    from proxploy.jobs import JobBackend
    from tests.support import make_job_app

    async def go():
        fake = _fake()
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.guestjobs  # noqa: F401, registers vm.snapshot_*

        backend = JobBackend(app)
        ids = _seed(app)
        with app.state.sessionmaker() as db:
            jid = backend.enqueue(db, kind=kind, target_type="vm",
                                  target_id=ids["vm_id"],
                                  params=params_from_ids(ids)).id
        await backend.wait(jid, timeout=10)
        with app.state.sessionmaker() as db:
            job = db.get(Job, jid)
            return fake, job.status, job.result, job.error

    return asyncio.run(go())


def test_snapshot_jobs_run_end_to_end(tmp_path):
    from proxploy.jobs import HANDLERS

    import proxploy.services.guestjobs  # noqa: F401

    for k in ("vm.snapshot_create", "vm.snapshot_rollback", "vm.snapshot_delete"):
        assert k in HANDLERS

    fake, status, result, error = _run_job(
        tmp_path, "vm.snapshot_create",
        lambda ids: {"vm_id": ids["vm_id"], "name": "pre-update",
                     "description": "before 2.4", "vmstate": True})
    assert status == "succeeded", error
    assert fake.snapshot_creates[0][3] == {"snapname": "pre-update",
                                           "description": "before 2.4", "vmstate": 1}
    assert result["exitstatus"] == "OK" and result["name"] == "pre-update"

    fake, status, result, error = _run_job(
        tmp_path, "vm.snapshot_rollback",
        lambda ids: {"vm_id": ids["vm_id"], "name": "base"})
    assert status == "succeeded", error
    assert fake.snapshot_rollbacks == [("qemu", "pve1", 201, "base")]

    fake, status, result, error = _run_job(
        tmp_path, "vm.snapshot_delete",
        lambda ids: {"vm_id": ids["vm_id"], "name": "base"})
    assert status == "succeeded", error
    assert fake.snapshot_deletes == [("qemu", "pve1", 201, "base")]


def test_a_failing_pve_task_fails_the_snapshot_job(tmp_path):
    from proxploy.jobs import JobBackend
    from tests.support import make_job_app

    async def go():
        fake = _fake()
        fake.task_exit = "snapshot feature is not available"
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.guestjobs  # noqa: F401

        backend = JobBackend(app)
        ids = _seed(app)
        with app.state.sessionmaker() as db:
            jid = backend.enqueue(db, kind="vm.snapshot_create", target_type="vm",
                                  target_id=ids["vm_id"],
                                  params={"vm_id": ids["vm_id"], "name": "x1"}).id
        await backend.wait(jid, timeout=10)
        with app.state.sessionmaker() as db:
            job = db.get(Job, jid)
            assert job.status == "failed"
            assert "snapshot feature is not available" in (job.error or "")

    asyncio.run(go())
```

- [ ] **Step 2: Run to verify failures**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_snapshots_api.py -q`
Expected: FAIL, 12 failed. The two client-level tests fail with
`AttributeError: 'ProxmoxClient' object has no attribute 'snapshot_create'`; the
route tests fail with `assert 404 == 200` / `assert 422 == 202`
(`test_post_snapshots_is_not_swallowed_by_the_lifecycle_wildcard` is the
diagnostic one: it 422s with `"action must be one of start, stop, restart,
shutdown, pause, resume"`, which is exactly the wildcard swallowing the path);
`test_snapshot_routes_are_registered_above_the_lifecycle_wildcard` fails with
`ValueError: '/api/v1/vms/{vm_id}/snapshots' is not in list`; the two job tests
fail with `KeyError: "no handler registered for job kind 'vm.snapshot_create'"`.

- [ ] **Step 3: Add the three `ProxmoxClient` snapshot mutation methods**

In `backend/proxploy/services/proxmox.py`, after `task_log` (and after Task 1's
`snapshots()` read method), add:

```python
    # --- snapshots (Phase 6) ------------------------------------------------

    def snapshot_create(self, kind: str, node: str, vmid: int, name: str,
                        description: str | None = None,
                        vmstate: bool = False) -> str:
        """POST /nodes/{node}/{kind}/{vmid}/snapshot -> UPID.

        `vmstate` is doc 01 §4's "with-RAM option": PVE dumps the guest's memory
        into the snapshot so a rollback resumes mid-execution. It exists only on
        the qemu endpoint, PVE's lxc snapshot API has no such parameter, so a
        container request for it is refused here rather than silently dropped,
        which would produce a snapshot the caller believes has RAM in it.
        """
        if vmstate and kind != "qemu":
            raise ProxmoxError("vmstate (snapshot with RAM) is a VM-only feature; "
                               f"{kind} snapshots cannot include memory")
        call: dict = {"snapname": name}
        if description:
            call["description"] = description
        if vmstate:
            call["vmstate"] = 1
        try:
            guest = getattr(self._connect().nodes(node), kind)(vmid)
            return guest.snapshot.post(**call)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001, one wrap point, like version()
            raise self._wrap(f"snapshot {name!r} of {kind}/{vmid} failed on {node}",
                             e) from e

    def snapshot_rollback(self, kind: str, node: str, vmid: int, name: str) -> str:
        """POST /nodes/{node}/{kind}/{vmid}/snapshot/{name}/rollback -> UPID.

        Destructive: everything written since the snapshot is discarded. The
        typed-name confirmation lives in the route (api/vms.py), not here.
        """
        try:
            guest = getattr(self._connect().nodes(node), kind)(vmid)
            return guest.snapshot(name).rollback.post()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"rollback of {kind}/{vmid} to {name!r} failed on "
                             f"{node}", e) from e

    def snapshot_delete(self, kind: str, node: str, vmid: int, name: str) -> str:
        """DELETE /nodes/{node}/{kind}/{vmid}/snapshot/{name} -> UPID."""
        try:
            guest = getattr(self._connect().nodes(node), kind)(vmid)
            return guest.snapshot(name).delete()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"deleting snapshot {name!r} of {kind}/{vmid} failed "
                             f"on {node}", e) from e
```

- [ ] **Step 4: Extend the FakePVE snapshot namespace**

In `backend/tests/fakes/pve.py`, **replace** the read-only `_SnapshotNS` Task 1
added with the version below and add the two new leaf classes above it. The
`snapshots_by_guest` attribute and the `_GuestNS.__init__` wiring line Task 1
wrote are unchanged, `.get()` keeps the same behaviour, so Task 1's tests are
unaffected.

```python
class _RollbackLeaf:
    def __init__(self, owner, kind, node, vmid, name):
        self._owner, self._kind = owner, kind
        self._node, self._vmid, self._name = node, vmid, name

    def post(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.snapshot_rollbacks.append(
            (self._kind, self._node, self._vmid, self._name))
        return self._owner._record_action(self._kind, self._vmid, "rollback")


class _SnapshotItemNS:
    """nodes(n).<kind>(vmid).snapshot(name).rollback.post() and .delete()."""

    def __init__(self, owner, kind, node, vmid, name):
        self._owner, self._kind = owner, kind
        self._node, self._vmid, self._name = node, vmid, name
        self.rollback = _RollbackLeaf(owner, kind, node, vmid, name)

    def delete(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.snapshot_deletes.append(
            (self._kind, self._node, self._vmid, self._name))
        return self._owner._record_action(self._kind, self._vmid, "snapdelete")


class _SnapshotNS:
    """nodes(n).<kind>(vmid).snapshot.get() lists.post() creates, and the
    object itself is callable with a snapshot name (proxmoxer's own shape)."""

    def __init__(self, owner, kind, node, vmid):
        self._owner, self._kind, self._node, self._vmid = owner, kind, node, vmid

    def get(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        return self._owner.snapshots_by_guest.get((self._kind, self._vmid), [])

    def post(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.snapshot_creates.append(
            (self._kind, self._node, self._vmid, kwargs))
        return self._owner._record_action(self._kind, self._vmid, "snapshot")

    def __call__(self, name):
        return _SnapshotItemNS(self._owner, self._kind, self._node, self._vmid,
                               name)
```

And in `FakePVE.__init__`, after the backup/restore/prune recording block Task 9
added:

```python
        # snapshot recording (Phase 6, Task 10)
        self.snapshot_creates: list[tuple[str, str, int, dict]] = []
        self.snapshot_rollbacks: list[tuple[str, str, int, str]] = []
        self.snapshot_deletes: list[tuple[str, str, int, str]] = []
```

- [ ] **Step 5: Add the VM resolver and the three handlers to `services/guestjobs.py`**

Append to `backend/proxploy/services/guestjobs.py` (Task 7 created this module
and its `main.py` lifespan import; only the imports it does not already have need
adding to the top of the file):

```python
import asyncio

from proxploy.jobs import HANDLERS, JobContext, JobFailed
from proxploy.models import Host, Vm
from proxploy.services.hostclient import client_for_host
from proxploy.services.pvetask import await_task


def _vm_target(app, vm_id: int):
    """Blocking: vms.id -> (client, node, vmid, name, host_id). Runs in a thread.

    Same shape as services/lifecycle.py::_resolve, minus the app/CT branch; 
    everything in this module is qemu-only (doc 05 puts snapshots, create and
    clone under /vms).
    """
    with app.state.sessionmaker() as db:
        v = db.get(Vm, vm_id)
        if v is None:
            raise JobFailed(f"vm {vm_id} not found")
        host = db.get(Host, v.host_id)
        if host is None:
            raise JobFailed(f"host {v.host_id} not found")
        return (client_for_host(app, db, host), host.node_name or "",
                int(v.vmid), v.name or f"VM {v.vmid}", host.id)


async def snapshot_create_job(ctx: JobContext, params: dict) -> dict:
    """`vm.snapshot_create`, take a snapshot, optionally with RAM."""
    app = ctx.backend.app
    vm_id = int(params["vm_id"])
    name = params["name"]
    client, node, vmid, vm_name, _host_id = await asyncio.to_thread(
        _vm_target, app, vm_id)
    vmstate = bool(params.get("vmstate"))
    ctx.log(f"snapshot {name!r} of {vm_name} (qemu {vmid}) on {node}"
            f"{' including RAM' if vmstate else ''}")
    upid = await asyncio.to_thread(client.snapshot_create, "qemu", node, vmid,
                                   name, params.get("description"), vmstate)
    status = await await_task(ctx, client, node, upid)
    app.state.bus.publish("resource", {"type": "vm", "id": vm_id,
                                       "change": "snapshot"})
    return {"upid": upid, "exitstatus": status.get("exitstatus"), "name": name,
            "vmid": vmid, "vmstate": vmstate}


async def snapshot_rollback_job(ctx: JobContext, params: dict) -> dict:
    """`vm.snapshot_rollback`, discard everything since the snapshot.

    The route already took the typed confirmation. PVE refuses a rollback of a
    running VM unless the snapshot carries vmstate, and that refusal is surfaced
    verbatim rather than pre-checked here: the guest's cached status can be up
    to one poll cycle stale, so a local check would produce a second, less
    accurate answer than the one Proxmox gives.
    """
    app = ctx.backend.app
    vm_id = int(params["vm_id"])
    name = params["name"]
    client, node, vmid, vm_name, _host_id = await asyncio.to_thread(
        _vm_target, app, vm_id)
    ctx.log(f"rolling {vm_name} (qemu {vmid}) back to snapshot {name!r} on {node}")
    upid = await asyncio.to_thread(client.snapshot_rollback, "qemu", node, vmid,
                                   name)
    status = await await_task(ctx, client, node, upid)
    app.state.bus.publish("resource", {"type": "vm", "id": vm_id,
                                       "change": "rollback"})
    return {"upid": upid, "exitstatus": status.get("exitstatus"), "name": name,
            "vmid": vmid}


async def snapshot_delete_job(ctx: JobContext, params: dict) -> dict:
    """`vm.snapshot_delete`, remove one snapshot; the guest is untouched."""
    app = ctx.backend.app
    vm_id = int(params["vm_id"])
    name = params["name"]
    client, node, vmid, vm_name, _host_id = await asyncio.to_thread(
        _vm_target, app, vm_id)
    ctx.log(f"deleting snapshot {name!r} of {vm_name} (qemu {vmid}) on {node}")
    upid = await asyncio.to_thread(client.snapshot_delete, "qemu", node, vmid,
                                   name)
    status = await await_task(ctx, client, node, upid)
    app.state.bus.publish("resource", {"type": "vm", "id": vm_id,
                                       "change": "snapshot"})
    return {"upid": upid, "exitstatus": status.get("exitstatus"), "name": name,
            "vmid": vmid}


HANDLERS["vm.snapshot_create"] = snapshot_create_job
HANDLERS["vm.snapshot_rollback"] = snapshot_rollback_job
HANDLERS["vm.snapshot_delete"] = snapshot_delete_job
```

- [ ] **Step 6: Hoist the role singletons in `api/vms.py`**

The four snapshot routes must be registered **above** `vm_lifecycle`, and they
need the role singletons, but `_require_operator` is currently assigned at
vms.py:54, *below* where the new routes go, so referencing it there would raise
`NameError` at import. Move the block to the top of the file, exactly as
`api/apps.py:26-31` does.

Delete these lines from `backend/proxploy/api/vms.py` (currently lines 51-54,
immediately above `@router.post("/{vm_id}/{action}"…)`):

```python
# Same ordering fix as apps.py::app_lifecycle: see the comment there. Reusing
# this one callable as both the route-level dependency and the parameter
# dependency makes auth/role run first and collapses the two into one call.
_require_operator = require_role("operator")
```

and insert this block immediately after `router = APIRouter(prefix="/vms", tags=["vms"])`:

```python
# Same ordering fix as apps.py::app_lifecycle: see the comment there. Reusing
# one callable as both the route-level dependency and the parameter dependency
# makes auth/role run first and collapses the two into one call. Declared up
# here rather than beside the lifecycle wildcard because every route between
# this line and that wildcard needs one of them.
_require_viewer = require_role("viewer")
_require_operator = require_role("operator")
_require_admin = require_role("admin")
```

- [ ] **Step 7: Add the four snapshot routes to `api/vms.py`**

Insert into `backend/proxploy/api/vms.py` **above** the `# WARNING`-commented
`@router.post("/{vm_id}/{action}"…)` block (i.e. after `vm_detail`). Extend the
imports first:

```python
import re

from pydantic import BaseModel

from proxploy.api.jobs import enqueue_and_audit, job_out
from proxploy.services.audit import write_audit
from proxploy.services.hostclient import client_for_host
from proxploy.services.proxmox import ProxmoxError
```

```python
# Registered ABOVE the /{vm_id}/{action} wildcard: see the WARNING on that
# route. Out of order, `POST /vms/3/snapshots` lands in vm_lifecycle with
# action="snapshots" and 422s (test_post_snapshots_is_not_swallowed_by_the_
# lifecycle_wildcard proves it stays this way).

# PVE's own pve-configid shape, plus its 40-char ceiling. Enforced here because
# the value is interpolated into a Proxmox path segment, and because "current"
# is PVE's synthetic pseudo-snapshot name and must never be creatable.
SNAP_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,39}$")


def _valid_snap_name(name: str) -> str:
    if not SNAP_NAME_RE.match(name or "") or name == "current":
        raise HTTPException(422, "snapshot name must start with a letter and use "
                                 "only letters, digits, '-' and '_' (2-40 chars), "
                                 "and cannot be 'current'")
    return name


def _snapshot_out(s: dict) -> dict:
    return {
        "name": s.get("name"),
        "description": s.get("description"),
        "snaptime": s.get("snaptime"),
        # PVE returns 0/1 (and omits it entirely on containers)
        "vmstate": bool(int(s.get("vmstate") or 0)),
        "parent": s.get("parent"),
    }


def _vm_and_host(db, vm_id: int):
    v = db.get(Vm, vm_id)
    if v is None:
        raise HTTPException(404, "vm not found")
    host = db.get(Host, v.host_id)
    if host is None:
        raise HTTPException(404, "host not found")
    return v, host


@router.get("/{vm_id}/snapshots",
            dependencies=[Depends(_require_viewer),
                          Depends(require_entitlement("vms.snapshots"))])
def list_vm_snapshots(request: Request, vm_id: int, db=Depends(get_db),
                      user: User = Depends(_require_viewer)):
    """Live read on every request (doc 05: "List snapshots (live from
    Proxmox)"); there is no snapshot table and this phase adds none.

    PVE always includes a synthetic `current` entry describing the running
    state. It is not a snapshot, has no snaptime, and cannot be rolled back to
    or deleted, so it is dropped here rather than in the UI; otherwise every
    consumer of this endpoint has to know the same trivia.
    """
    v, host = _vm_and_host(db, vm_id)
    client = client_for_host(request.app, db, host)
    try:
        rows = client.snapshots("qemu", host.node_name or "", v.vmid)
    except ProxmoxError as e:
        raise HTTPException(502, str(e)) from e
    return [_snapshot_out(s) for s in rows if s.get("name") != "current"]


class SnapshotIn(BaseModel):
    name: str
    description: str | None = None
    vmstate: bool = False


@router.post("/{vm_id}/snapshots", status_code=202,
             dependencies=[Depends(_require_operator),
                           Depends(require_entitlement("vms.snapshots"))])
def create_vm_snapshot(request: Request, vm_id: int, body: SnapshotIn,
                       db=Depends(get_db),
                       user: User = Depends(_require_operator)):
    v, _host = _vm_and_host(db, vm_id)
    name = _valid_snap_name(body.name)
    return enqueue_and_audit(request, db, user, kind="vm.snapshot_create",
                             target_type="vm", target_id=v.id,
                             params={"vm_id": v.id, "name": name,
                                     "description": body.description,
                                     "vmstate": body.vmstate})


class RollbackIn(BaseModel):
    confirm: str | None = None


@router.post("/{vm_id}/snapshots/{name}/rollback", status_code=202,
             dependencies=[Depends(_require_admin),
                           Depends(require_entitlement("vms.snapshots"))])
def rollback_vm_snapshot(request: Request, vm_id: int, name: str,
                         body: RollbackIn = Body(default=RollbackIn()),
                         db=Depends(get_db),
                         user: User = Depends(_require_admin)):
    """Rollback throws away every write since the snapshot was taken; there is
    no undo and no second copy. It therefore reuses the exact 409 body
    `enqueue_lifecycle` uses for a self-targeted stop, so the frontend's
    existing ConfirmSelfDialog renders it with no new component.
    """
    v, _host = _vm_and_host(db, vm_id)
    _valid_snap_name(name)
    vm_name = v.name or f"VM {v.vmid}"
    ip = request.client.host if request.client else None
    if (body.confirm or "") != vm_name:
        write_audit(db, actor_type="user", actor_id=user.id,
                    action="vm.snapshot_rollback", target_type="vm",
                    target_id=v.id, params={"name": name}, result="denied", ip=ip)
        raise HTTPException(409, {
            "error": "confirm_required", "confirm_phrase": vm_name,
            "detail": (f"Rolling {vm_name} back to {name!r} discards everything "
                       f"written since that snapshot was taken. Type the VM name "
                       f"to confirm."),
        })
    return enqueue_and_audit(request, db, user, kind="vm.snapshot_rollback",
                             target_type="vm", target_id=v.id,
                             params={"vm_id": v.id, "name": name})


@router.delete("/{vm_id}/snapshots/{name}", status_code=202,
               dependencies=[Depends(_require_operator),
                             Depends(require_entitlement("vms.snapshots"))])
def delete_vm_snapshot(request: Request, vm_id: int, name: str, db=Depends(get_db),
                       user: User = Depends(_require_operator)):
    """No typed confirmation: deleting a snapshot leaves the guest and its disk
    exactly as they are. Only the rollback above destroys live state.
    """
    v, _host = _vm_and_host(db, vm_id)
    _valid_snap_name(name)
    return enqueue_and_audit(request, db, user, kind="vm.snapshot_delete",
                             target_type="vm", target_id=v.id,
                             params={"vm_id": v.id, "name": name})
```

- [ ] **Step 8: Run the task's tests**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_snapshots_api.py -q`
Expected: PASS, 12 passed.

- [ ] **Step 9: Run the VM and lifecycle regressions**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_apps_vms_api.py tests/test_lifecycle_api.py tests/test_route_auth_invariant.py -q`
Expected: PASS, unchanged counts. This is the proof that hoisting the
`_require_operator` singleton in Step 6 changed nothing: `vm_lifecycle` still
resolves the same callable object, so FastAPI still collapses the route-level
and parameter-level dependencies into one call.

- [ ] **Step 10: Run the full backend suite**

Run: `cd backend && ./.venv/bin/python -m pytest tests/ -q -m "not pve_integration and not e2e"`
Expected: Task 9's total + 12 passed, 0 failed, 0 errors.

- [ ] **Step 11: Commit**

```bash
git add backend/proxploy/services/proxmox.py backend/proxploy/services/guestjobs.py backend/proxploy/api/vms.py backend/tests/fakes/pve.py backend/tests/test_snapshots_api.py
git commit -m "feat(vms): snapshot list/create/rollback/delete routes and jobs"
```

---

## Task 11: VM create / clone / delete

**Files:**
- Modify: `backend/proxploy/services/proxmox.py`, `backend/proxploy/services/guestjobs.py`, `backend/proxploy/api/vms.py`, `backend/tests/fakes/pve.py`
- Test: `backend/tests/test_vm_create_clone.py`

**Interfaces:**
- Consumes (Task 1): `client_for_host(app, db, host)`, `ProxmoxClient.cluster_nextid() -> int` and FakePVE's `nextid` attribute + its `.cluster.nextid` leaf.
- Consumes (Task 2): `await_task(...)`, `enqueue_and_audit(...)`.
- Consumes (Task 9): `_GuestFactory.post()` on FakePVE, recording into `fake.creates` as `(kind, node, kwargs)`; **reused verbatim** by `vm_create`; this task only adds the `create_error` hook to it.
- Consumes (Task 10): `proxploy/services/guestjobs.py::_vm_target`, and `api/vms.py`'s hoisted `_require_viewer`/`_require_operator`/`_require_admin` singletons.
- Consumes (existing): `proxploy.services.selfguard.is_self`, `proxploy.services.audit.write_audit`.
- Produces:
  - `ProxmoxClient.vm_create(node: str, params: dict) -> str` (UPID)
  - `ProxmoxClient.vm_clone(node: str, vmid: int, params: dict) -> str` (UPID)
  - `ProxmoxClient.guest_delete(kind: str, node: str, vmid: int) -> str` (UPID)
  - `proxploy/services/guestjobs.py::_host_client(app, host_id: int) -> tuple[ProxmoxClient, str, str]`
  - job kinds `vm.create`, `vm.clone`, `vm.delete`
  - `proxploy/api/vms.py`: `_require_owner = require_role("owner")`, `VM_NAME_RE`, `_pick_node(request, host, node)`, routes
    `POST /api/v1/vms` (admin, `vms.create`),
    `POST /api/v1/vms/{vm_id}/clone` (admin, `vms.clone`),
    `DELETE /api/v1/vms/{vm_id}` (owner, `vms.create` per doc 05)
    **clone and delete registered above the `POST /{vm_id}/{action}` wildcard**
  - FakePVE: `_CloneLeaf`, `_GuestNS.delete()`, recorders `fake.clones`, `fake.guest_deletes`, injectors `fake.create_error`, `fake.clone_error`

**No migration, and no `Vm` row is written.** The `vms` table is the poller's
droppable mirror (doc 04: Proxmox is the truth). A created VM appears when the
30 s poll cycle discovers it, a deleted one disappears the same way; exactly
how `run_lifecycle` handles a status change. The handlers end with the same
`app.state.bus.publish("resource", …)` nudge `run_lifecycle` uses, so an open
tab refetches rather than waiting out the interval.

**Linked-clone honesty.** PVE only permits `full=0` (a linked clone) when the
source is a template. Proxploy does not know which VMs are templates: the `vms`
table has no `template` column, the poller does not read `/cluster/resources`'s
`template` field, and this phase adds no migration. So the clone route passes
`full` straight through and surfaces PVE's own rejection verbatim instead of
pre-validating against knowledge it does not have. A `ponytail:` comment in the
route names the upgrade path.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_vm_create_clone.py
"""VM create / clone / delete (doc 05 §VMs, doc 01 §4).

Same registration-order hazard as Task 10: POST /vms/{id}/clone and
DELETE /vms/{id} live above api/vms.py's POST /{vm_id}/{action} wildcard, and
both an ordering assertion and a behavioural one lock that in.

DELETE is the most destructive route in this phase, it removes a guest and its
disks, so it carries three separate gates: owner role, the selfguard, and a
typed confirmation, plus a refusal to touch a running guest.
"""
import asyncio
import json

from fastapi.testclient import TestClient

from proxploy.models import AuditEvent, Host, HostCredential, Job, Vm


def _fake():
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    fake.nextid = 999
    return fake


def _seed(app, vm_status="stopped"):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.7:8006", node_name="pve1",
                    status="connected", pve_version="8.4.1")
        db.add(host)
        db.commit()
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!vm", "token_secret": "s3cret"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token", encrypted_blob=blob,
                              key_version=ver, public_meta="proxploy@pve!vm"))
        v = Vm(host_id=host.id, vmid=201, name="win11", status=vm_status)
        db.add(v)
        db.commit()
        return {"host_id": host.id, "vm_id": v.id}


def _authed(tmp_path, bootstrap_admin, vm_status="stopped"):
    from tests.support import make_app, seed_snapshot

    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    c = TestClient(app)
    c.__enter__()
    bootstrap_admin(c)
    ids = _seed(app, vm_status=vm_status)
    seed_snapshot(app, ids["host_id"], nodes=[{"node": "pve1"}, {"node": "pve2"}])
    return app, c, fake, ids


def _spec(ids, **over):
    body = {"host_id": ids["host_id"], "name": "web-01", "node": "pve1",
            "cores": 2, "memory_mb": 2048, "disk_gb": 32, "storage": "local-lvm"}
    body.update(over)
    return body


# --- ProxmoxClient level ---------------------------------------------------

def test_create_clone_and_delete_client_calls(tmp_path):
    from proxploy.services.proxmox import ProxmoxClient
    from tests.fakes.pve import make_fake_factory

    fake = _fake()
    client = ProxmoxClient("https://10.0.0.7:8006", "proxploy@pve!vm", "s3cret",
                           factory=make_fake_factory(fake))
    upid = client.vm_create("pve1", {"vmid": 999, "name": "web-01", "cores": 2})
    assert upid.startswith("UPID:")
    # the guest-create leaf Task 9 added for restores: reused, not duplicated
    assert fake.creates == [("qemu", "pve1", {"vmid": 999, "name": "web-01",
                                              "cores": 2})]
    client.vm_clone("pve1", 201, {"newid": 999, "name": "web-02", "full": 1})
    assert fake.clones == [("pve1", 201, {"newid": 999, "name": "web-02",
                                          "full": 1})]
    client.guest_delete("qemu", "pve1", 201)
    assert fake.guest_deletes == [("qemu", "pve1", 201)]


def test_create_error_is_wrapped_and_scrubbed(tmp_path):
    import pytest

    from proxploy.services.proxmox import ProxmoxClient, ProxmoxError
    from tests.fakes.pve import make_fake_factory

    fake = _fake()
    fake.create_error = "500 VM 100 already exists (secret s3cret leaked)"
    client = ProxmoxClient("https://10.0.0.7:8006", "proxploy@pve!vm", "s3cret",
                           factory=make_fake_factory(fake))
    with pytest.raises(ProxmoxError) as exc:
        client.vm_create("pve1", {"vmid": 100})
    assert "already exists" in str(exc.value)
    assert "s3cret" not in str(exc.value)  # _wrap is the one scrubbing point


# --- route ordering --------------------------------------------------------

def test_create_routes_are_registered_above_the_lifecycle_wildcard(tmp_path):
    from tests.support import make_app

    routes = [r for r in make_app(tmp_path).routes if hasattr(r, "path")]
    paths = [r.path for r in routes]
    wildcard = paths.index("/api/v1/vms/{vm_id}/{action}")
    assert paths.index("/api/v1/vms/{vm_id}/clone") < wildcard
    assert "/api/v1/vms" in paths


def test_post_clone_is_not_swallowed_by_the_lifecycle_wildcard(
        tmp_path, csrf_header, bootstrap_admin):
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        r = c.post(f"/api/v1/vms/{ids['vm_id']}/clone", json={"name": "web-02"},
                   headers=csrf_header(c))
        assert r.status_code == 202, r.text
        assert r.json()["job"]["kind"] == "vm.clone"
        with app.state.sessionmaker() as db:
            assert {j.kind for j in db.query(Job).all()} == {"vm.clone"}


# --- create route ----------------------------------------------------------

def test_create_validates_the_spec(tmp_path, csrf_header, bootstrap_admin):
    app, c, fake, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        h = csrf_header(c)
        for over in ({"cores": 0}, {"memory_mb": 0}, {"disk_gb": 0},
                     {"cores": -4}, {"name": "bad name"}, {"node": "pve9"}):
            r = c.post("/api/v1/vms", json=_spec(ids, **over), headers=h)
            assert r.status_code == 422, over
        r = c.post("/api/v1/vms", json=_spec(ids, host_id=9999), headers=h)
        assert r.status_code == 404
        with app.state.sessionmaker() as db:
            assert db.query(Job).count() == 0


def test_create_mints_a_vmid_from_cluster_nextid(tmp_path, csrf_header,
                                                 bootstrap_admin):
    app, c, fake, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        r = c.post("/api/v1/vms", json=_spec(ids), headers=csrf_header(c))
        assert r.status_code == 202, r.text
        assert r.json()["vmid"] == 999
        job = r.json()["job"]
        assert job["kind"] == "vm.create" and job["params"]["vmid"] == 999
        assert job["target_type"] == "host" and job["target_id"] == ids["host_id"]
        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="vm.create").one()
            assert row.job_id is not None
            # no Vm row is written by Proxploy: the poller discovers it
            assert db.query(Vm).count() == 1


def test_create_accepts_an_explicit_vmid(tmp_path, csrf_header, bootstrap_admin):
    app, c, fake, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        r = c.post("/api/v1/vms", json=_spec(ids, vmid=310),
                   headers=csrf_header(c))
        assert r.status_code == 202, r.text
        assert r.json()["vmid"] == 310
        assert fake.nextid_calls == 0  # never asked PVE for one


def test_create_requires_admin(tmp_path, csrf_header, bootstrap_admin):
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        c.post("/api/v1/users", json={"email": "op@example.com",
                                      "password": "correct-horse-battery",
                                      "display_name": "Op", "role": "operator"},
               headers=csrf_header(c))
        c.post("/api/v1/auth/login", json={"email": "op@example.com",
                                           "password": "correct-horse-battery"},
               headers=csrf_header(c))
        r = c.post("/api/v1/vms", json=_spec(ids), headers=csrf_header(c))
        assert r.status_code == 403 and r.json()["detail"] == "insufficient role"


# --- job handlers ----------------------------------------------------------

def _run_job(tmp_path, kind, params_from_ids, tweak=None):
    from proxploy.jobs import JobBackend
    from tests.support import make_job_app

    async def go():
        fake = _fake()
        if tweak:
            tweak(fake)
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.guestjobs  # noqa: F401, registers vm.create etc.

        backend = JobBackend(app)
        ids = _seed(app)
        q = app.state.bus.subscribe()
        with app.state.sessionmaker() as db:
            jid = backend.enqueue(db, kind=kind, params=params_from_ids(ids)).id
        await backend.wait(jid, timeout=10)
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        with app.state.sessionmaker() as db:
            job = db.get(Job, jid)
            return fake, job.status, job.result, job.error, events

    return asyncio.run(go())


def test_create_job_builds_the_qemu_params_and_publishes(tmp_path):
    fake, status, result, error, events = _run_job(
        tmp_path, "vm.create",
        lambda ids: {"host_id": ids["host_id"], "node": "pve1", "vmid": 999,
                     "name": "web-01", "cores": 2, "memory_mb": 2048,
                     "disk_gb": 32, "storage": "local-lvm",
                     "iso": "local:iso/debian-12.iso", "bridge": "vmbr0",
                     "ostype": "l26", "start": True})
    assert status == "succeeded", error
    kind, node, kwargs = fake.creates[0]
    assert (kind, node) == ("qemu", "pve1")
    assert kwargs["vmid"] == 999 and kwargs["name"] == "web-01"
    assert kwargs["cores"] == 2 and kwargs["memory"] == 2048
    assert kwargs["scsi0"] == "local-lvm:32"
    assert kwargs["ide2"] == "local:iso/debian-12.iso,media=cdrom"
    assert kwargs["net0"] == "virtio,bridge=vmbr0"
    assert kwargs["boot"] == "order=scsi0;ide2" and kwargs["start"] == 1
    assert result["vmid"] == 999 and result["exitstatus"] == "OK"
    assert ("resource", {"type": "vm", "id": None, "change": "created"}) in events


def test_create_threads_the_wizards_vlan_tag_into_net0(tmp_path):
    """Task 17's Network step offers a VLAN. Pydantic drops unknown keys
    silently rather than 422-ing, so a missing `vlan_tag` on VmCreateIn would
    build an untagged NIC and report success, a wrong result wearing a green
    tick. Both halves are pinned here."""
    fake, status, _r, error, _e = _run_job(
        tmp_path, "vm.create",
        lambda ids: {"host_id": ids["host_id"], "node": "pve1", "vmid": 999,
                     "name": "web-01", "cores": 1, "memory_mb": 512,
                     "disk_gb": 8, "storage": "local-lvm", "iso": None,
                     "bridge": "vmbr1", "vlan_tag": 42, "ostype": "l26"})
    assert status == "succeeded", error
    assert fake.creates[0][2]["net0"] == "virtio,bridge=vmbr1,tag=42"


def test_create_omits_the_tag_entirely_when_untagged(tmp_path):
    for tag in (None, 0):
        fake, status, _r, error, _e = _run_job(
            tmp_path / f"t{tag}", "vm.create",
            lambda ids: {"host_id": ids["host_id"], "node": "pve1", "vmid": 999,
                         "name": "web-01", "cores": 1, "memory_mb": 512,
                         "disk_gb": 8, "storage": "local-lvm", "iso": None,
                         "bridge": "vmbr0", "vlan_tag": tag, "ostype": "l26"})
        assert status == "succeeded", error
        # never `tag=` with an empty value: PVE rejects that outright
        assert fake.creates[0][2]["net0"] == "virtio,bridge=vmbr0"


def test_create_route_accepts_and_forwards_vlan_tag(tmp_path):
    app = make_app(tmp_path, fake=FakePVE())
    with TestClient(app) as c:
        csrf = _login(c)
        host_id = _seed_host(app)
        r = c.post("/api/v1/vms", headers=csrf, json={
            "host_id": host_id, "node": "pve1", "name": "web-01",
            "cores": 2, "memory_mb": 2048, "disk_gb": 32,
            "storage": "local-lvm", "bridge": "vmbr1", "vlan_tag": 42})
        assert r.status_code == 202, r.text
        with app.state.sessionmaker() as db:
            job = db.query(Job).filter_by(kind="vm.create").one()
            assert job.params["vlan_tag"] == 42


def test_create_without_an_iso_boots_from_disk_only(tmp_path):
    fake, status, _r, error, _e = _run_job(
        tmp_path, "vm.create",
        lambda ids: {"host_id": ids["host_id"], "node": "pve1", "vmid": 999,
                     "name": "web-01", "cores": 1, "memory_mb": 512,
                     "disk_gb": 8, "storage": "local-lvm"})
    assert status == "succeeded", error
    _k, _n, kwargs = fake.creates[0]
    assert "ide2" not in kwargs and kwargs["boot"] == "order=scsi0"
    assert "start" not in kwargs


def test_a_taken_vmid_fails_the_job_once_without_retrying(tmp_path):
    """PVE is the authority on vmid uniqueness. A retry loop here would race a
    second orchestrator forever and hide a real collision, so the error is
    surfaced and the job ends."""
    fake, status, _r, error, _e = _run_job(
        tmp_path, "vm.create",
        lambda ids: {"host_id": ids["host_id"], "node": "pve1", "vmid": 100,
                     "name": "web-01", "cores": 1, "memory_mb": 512,
                     "disk_gb": 8, "storage": "local-lvm"},
        tweak=lambda f: setattr(f, "create_error", "500 VM 100 already exists"))
    assert status == "failed"
    assert "already exists" in (error or "")
    assert len(fake.creates) == 1  # exactly one attempt


def test_clone_job_passes_full_through_and_surfaces_pve_rejection(tmp_path):
    fake, status, result, error, _e = _run_job(
        tmp_path, "vm.clone",
        lambda ids: {"vm_id": ids["vm_id"], "newid": 999, "name": "web-02",
                     "full": True, "target": "pve2", "storage": "local-lvm"})
    assert status == "succeeded", error
    node, vmid, kwargs = fake.clones[0]
    assert (node, vmid) == ("pve1", 201)
    assert kwargs == {"newid": 999, "name": "web-02", "full": 1,
                      "target": "pve2", "storage": "local-lvm"}
    assert result["newid"] == 999

    # A linked clone of a non-template is refused by PVE, not by Proxploy; 
    # Proxploy does not track template-ness (see the route's ponytail comment).
    fake, status, _r, error, _e = _run_job(
        tmp_path, "vm.clone",
        lambda ids: {"vm_id": ids["vm_id"], "newid": 999, "full": False},
        tweak=lambda f: setattr(f, "clone_error",
                                "400 Parameter verification failed. full: "
                                "linked clone feasible only for template"))
    assert status == "failed"
    assert "linked clone feasible only for template" in (error or "")
    assert fake.clones[0][2]["full"] == 0  # full=False went through untouched


def test_delete_job_destroys_the_guest(tmp_path):
    fake, status, result, error, events = _run_job(
        tmp_path, "vm.delete", lambda ids: {"vm_id": ids["vm_id"]})
    assert status == "succeeded", error
    assert fake.guest_deletes == [("qemu", "pve1", 201)]
    assert result["vmid"] == 201
    assert ("resource", {"type": "vm", "id": None, "change": "deleted"}) in events


# --- delete route ----------------------------------------------------------

def test_delete_requires_the_typed_name(tmp_path, csrf_header, bootstrap_admin):
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin)
    vid = ids["vm_id"]
    with c:
        r = c.request("DELETE", f"/api/v1/vms/{vid}", json={},
                      headers=csrf_header(c))
        assert r.status_code == 409
        assert r.json()["error"] == "confirm_required"
        assert r.json()["confirm_phrase"] == "win11"
        with app.state.sessionmaker() as db:
            assert db.query(AuditEvent).filter_by(
                action="vm.delete", result="denied").count() == 1
            assert db.query(Job).count() == 0
        ok = c.request("DELETE", f"/api/v1/vms/{vid}", json={"confirm": "win11"},
                       headers=csrf_header(c))
        assert ok.status_code == 202, ok.text
        assert ok.json()["job"]["kind"] == "vm.delete"


def test_delete_refuses_a_running_vm(tmp_path, csrf_header, bootstrap_admin):
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin, vm_status="running")
    with c:
        r = c.request("DELETE", f"/api/v1/vms/{ids['vm_id']}",
                      json={"confirm": "win11"}, headers=csrf_header(c))
        assert r.status_code == 409
        assert r.json()["error"] == "guest_running"
        with app.state.sessionmaker() as db:
            assert db.query(Job).count() == 0


def test_delete_requires_owner_role(tmp_path, csrf_header, bootstrap_admin):
    """doc 05 puts DELETE /vms/{id} at owner, one rung above every other VM
    route, an admin who may create and clone still may not destroy."""
    app, c, _f, ids = _authed(tmp_path, bootstrap_admin)
    with c:
        c.post("/api/v1/users", json={"email": "adm@example.com",
                                      "password": "correct-horse-battery",
                                      "display_name": "Adm", "role": "admin"},
               headers=csrf_header(c))
        c.post("/api/v1/auth/login", json={"email": "adm@example.com",
                                           "password": "correct-horse-battery"},
               headers=csrf_header(c))
        assert c.post(f"/api/v1/vms/{ids['vm_id']}/clone", json={},
                      headers=csrf_header(c)).status_code == 202
        r = c.request("DELETE", f"/api/v1/vms/{ids['vm_id']}",
                      json={"confirm": "win11"}, headers=csrf_header(c))
        assert r.status_code == 403 and r.json()["detail"] == "insufficient role"


def test_vm_mutations_require_auth(tmp_path, csrf_header):
    from tests.support import make_app

    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        ids = _seed(app)
        h = csrf_header(c)
        assert c.post("/api/v1/vms", json=_spec(ids), headers=h).status_code == 401
        assert c.post(f"/api/v1/vms/{ids['vm_id']}/clone", json={},
                      headers=h).status_code == 401
        assert c.request("DELETE", f"/api/v1/vms/{ids['vm_id']}", json={},
                         headers=h).status_code == 401
```

- [ ] **Step 2: Run to verify failures**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_vm_create_clone.py -q`
Expected: FAIL, 20 failed. The client tests fail with
`AttributeError: 'ProxmoxClient' object has no attribute 'vm_create'`;
`test_create_routes_are_registered_above_the_lifecycle_wildcard` fails with
`ValueError: '/api/v1/vms/{vm_id}/clone' is not in list`;
`test_post_clone_is_not_swallowed_by_the_lifecycle_wildcard` fails with
`assert 422 == 202` (the wildcard matched and rejected `action="clone"`); the
route tests fail with `assert 404 == 202`; the handler tests fail with
`KeyError: "no handler registered for job kind 'vm.create'"`.

- [ ] **Step 3: Add the three `ProxmoxClient` guest-lifecycle methods**

In `backend/proxploy/services/proxmox.py`, after the snapshot block from Task 10:

```python
    # --- guest create / clone / destroy (Phase 6) ---------------------------

    def vm_create(self, node: str, params: dict) -> str:
        """POST /nodes/{node}/qemu -> UPID.

        The same endpoint restore_guest() posts an `archive` to; here it carries
        a full spec (vmid, name, cores, memory, scsi0, net0, …). Building that
        spec is the caller's job, this method only posts it, so every PVE
        parameter name lives in exactly one place (services/guestjobs.py).
        """
        try:
            return self._connect().nodes(node).qemu.post(**params)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001, one wrap point, like version()
            raise self._wrap(f"vm create failed on {node}", e) from e

    def vm_clone(self, node: str, vmid: int, params: dict) -> str:
        """POST /nodes/{node}/qemu/{vmid}/clone -> UPID.

        `params` carries newid/name/full/target/storage. `full=0` (a linked
        clone) is only legal when the source is a template; PVE enforces that
        and its refusal is what the caller reports.
        """
        try:
            return self._connect().nodes(node).qemu(vmid).clone.post(**params)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"clone of qemu/{vmid} failed on {node}", e) from e

    def guest_delete(self, kind: str, node: str, vmid: int) -> str:
        """DELETE /nodes/{node}/{lxc|qemu}/{vmid} -> UPID. Destroys the guest
        and its disks; PVE refuses while it is running."""
        if kind not in ("lxc", "qemu"):
            raise ProxmoxError(f"{kind!r} is not a destroyable guest kind")
        try:
            return getattr(self._connect().nodes(node), kind)(vmid).delete()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"destroying {kind}/{vmid} failed on {node}", e) from e
```

- [ ] **Step 4: Extend FakePVE with clone/delete leaves and the error hooks**

In `backend/tests/fakes/pve.py`, add the clone leaf next to the other guest leaves:

```python
class _CloneLeaf:
    def __init__(self, owner, node, vmid):
        self._owner, self._node, self._vmid = owner, node, vmid

    def post(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        # recorded BEFORE the injected failure so a test can prove exactly one
        # attempt was made and nothing retried
        self._owner.clones.append((self._node, self._vmid, kwargs))
        if self._owner.clone_error:
            raise RuntimeError(self._owner.clone_error)
        return self._owner._record_action("qemu", int(kwargs.get("newid", 0)),
                                          "clone")
```

Replace `_GuestNS` with the version below, it keeps every existing attribute
and adds `.clone` (qemu only, like `.vncproxy`) plus `.delete()`:

```python
class _GuestNS:
    def __init__(self, owner, kind, node, vmid):
        self._owner, self._kind, self._node, self._vmid = owner, kind, node, vmid
        self.status = _GuestStatusNS(owner, kind, vmid)
        self.termproxy = _TermproxyLeaf(owner, kind, node, vmid)
        self.snapshot = _SnapshotNS(owner, kind, node, vmid)
        if kind == "qemu":
            self.vncproxy = _VncproxyLeaf(owner, node, vmid)
            self.clone = _CloneLeaf(owner, node, vmid)

    def delete(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.guest_deletes.append((self._kind, self._node, self._vmid))
        return self._owner._record_action(self._kind, self._vmid, "destroy")
```

Add the `create_error` hook to the `_GuestFactory.post()` Task 9 added (two new
lines; the `fake.creates` recorder itself is unchanged and shared with the
restore path):

```python
    def post(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.creates.append((self._kind, self._node, kwargs))
        if self._owner.create_error:
            raise RuntimeError(self._owner.create_error)
        return self._owner._record_action(self._kind, int(kwargs.get("vmid", 0)),
                                          "create")
```

And in `FakePVE.__init__`, after the snapshot recording block from Task 10:

```python
        # guest create/clone/destroy (Phase 6, Task 11): `creates` and `nextid`
        # already exist from Tasks 9 and 1
        self.clones: list[tuple[str, int, dict]] = []
        self.guest_deletes: list[tuple[str, str, int]] = []
        self.create_error: str | None = None
        self.clone_error: str | None = None
```

Finally, `test_create_accepts_an_explicit_vmid` asserts the route did *not* ask
PVE for an id, so the `.cluster.nextid` leaf Task 1 added needs a counter.
Add `self.nextid_calls = 0` beside `self.nextid` in `FakePVE.__init__`, and make
Task 1's nextid leaf's `get()` increment it before returning:

```python
    def get(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.nextid_calls += 1
        return str(self._owner.nextid)
```

- [ ] **Step 5: Add the host resolver and the `vm.create` handler**

Append to `backend/proxploy/services/guestjobs.py`:

```python
def _host_client(app, host_id: int):
    """Blocking: hosts.id -> (client, node, host name). Create has no guest row
    to resolve from yet, so it resolves the host directly."""
    with app.state.sessionmaker() as db:
        host = db.get(Host, host_id)
        if host is None:
            raise JobFailed(f"host {host_id} not found")
        return client_for_host(app, db, host), host.node_name or "", host.name


def _create_params(params: dict) -> dict:
    """The one place Proxploy's create spec becomes PVE's qemu parameters.

    Deliberately opinionated defaults rather than a passthrough of arbitrary
    PVE keys: virtio-scsi-single + a virtio NIC is what the Proxmox UI's own
    defaults produce, and a create wizard that lets a caller post raw qemu
    config would be an unvalidated write to the hypervisor.
    """
    iso = params.get("iso")

    def _net0(p: dict) -> str:
        # PVE spells a VLAN on a guest NIC as `,tag=N` inside the netN string
        # (same grammar services/netconfig.py round-trips for edits). Absent or
        # falsy tag means untagged: never emit `tag=` with an empty value.
        spec = f"virtio,bridge={p.get('bridge') or 'vmbr0'}"
        tag = p.get("vlan_tag")
        return f"{spec},tag={int(tag)}" if tag else spec

    call = {
        "vmid": int(params["vmid"]),
        "name": params["name"],
        "cores": int(params["cores"]),
        "sockets": 1,
        "memory": int(params["memory_mb"]),
        "ostype": params.get("ostype") or "l26",
        "scsihw": "virtio-scsi-single",
        "scsi0": f"{params['storage']}:{int(params['disk_gb'])}",
        "net0": _net0(params),
        "boot": "order=scsi0;ide2" if iso else "order=scsi0",
    }
    if iso:
        call["ide2"] = f"{iso},media=cdrom"
    if params.get("start"):
        call["start"] = 1
    return call


async def create_vm(ctx: JobContext, params: dict) -> dict:
    """`vm.create`, post the spec, poll the task, nudge the UI.

    No `Vm` row is written here. `vms` is the poller's droppable mirror (doc 04:
    Proxmox is the truth) and writing one from this side would create a row the
    next poll cycle either confirms or deletes, a second, worse source of
    truth. The resource publish below is the same nudge run_lifecycle emits, so
    an open tab refetches instead of waiting out the 30 s interval.
    """
    app = ctx.backend.app
    host_id = int(params["host_id"])
    client, host_node, host_name = await asyncio.to_thread(_host_client, app,
                                                           host_id)
    node = params.get("node") or host_node
    call = _create_params(params)
    ctx.log(f"creating VM {call['vmid']} ({call['name']}) on {host_name}/{node}: "
            f"{call['cores']} cores, {call['memory']} MiB, {call['scsi0']}")
    # ponytail: no retry on a taken vmid. PVE is the authority on uniqueness and
    # rejects a duplicate outright; retrying with the next free id would race a
    # second orchestrator indefinitely and silently create a guest under an id
    # the caller never asked for. The error is surfaced verbatim instead.
    upid = await asyncio.to_thread(client.vm_create, node, call)
    status = await await_task(ctx, client, node, upid)
    app.state.bus.publish("resource", {"type": "vm", "id": None,
                                       "change": "created"})
    return {"upid": upid, "exitstatus": status.get("exitstatus"),
            "vmid": call["vmid"], "name": call["name"], "node": node}


HANDLERS["vm.create"] = create_vm
```

- [ ] **Step 6: Add the `vm.clone` and `vm.delete` handlers**

Append to `backend/proxploy/services/guestjobs.py`:

```python
async def clone_vm(ctx: JobContext, params: dict) -> dict:
    """`vm.clone`, full or linked, per the caller's `full` flag.

    `full` is passed through untouched. PVE allows `full=0` (a linked clone)
    only from a template, and Proxploy has no way to know which VMs are
    templates, the `vms` table has no `template` column and the poller does not
    read `/cluster/resources`'s `template` field, so PVE's own rejection is the
    answer the caller gets, verbatim, instead of a guess made here.
    """
    app = ctx.backend.app
    vm_id = int(params["vm_id"])
    client, node, vmid, vm_name, _host_id = await asyncio.to_thread(
        _vm_target, app, vm_id)
    call: dict = {"newid": int(params["newid"]), "full": 1 if params.get("full") else 0}
    for key in ("name", "target", "storage"):
        if params.get(key):
            call[key] = params[key]
    ctx.log(f"{'full' if call['full'] else 'linked'} clone of {vm_name} "
            f"(qemu {vmid}) on {node} -> {call['newid']}")
    upid = await asyncio.to_thread(client.vm_clone, node, vmid, call)
    status = await await_task(ctx, client, node, upid)
    app.state.bus.publish("resource", {"type": "vm", "id": None,
                                       "change": "created"})
    return {"upid": upid, "exitstatus": status.get("exitstatus"),
            "newid": call["newid"], "source_vmid": vmid, "full": bool(call["full"])}


async def delete_vm(ctx: JobContext, params: dict) -> dict:
    """`vm.delete`, destroy the guest and its disks.

    The route already required owner role, a typed name, a non-running guest and
    a selfguard pass. As with create, the `vms` row is left to the poller to
    drop: deleting it here would beat the poller to a state Proxmox has not
    confirmed yet.
    """
    app = ctx.backend.app
    vm_id = int(params["vm_id"])
    client, node, vmid, vm_name, _host_id = await asyncio.to_thread(
        _vm_target, app, vm_id)
    ctx.log(f"destroying {vm_name} (qemu {vmid}) on {node}")
    upid = await asyncio.to_thread(client.guest_delete, "qemu", node, vmid)
    status = await await_task(ctx, client, node, upid)
    app.state.bus.publish("resource", {"type": "vm", "id": None,
                                       "change": "deleted"})
    return {"upid": upid, "exitstatus": status.get("exitstatus"), "vmid": vmid,
            "name": vm_name}


HANDLERS["vm.clone"] = clone_vm
HANDLERS["vm.delete"] = delete_vm
```

- [ ] **Step 7: Add `POST /vms` to `api/vms.py`**

In `backend/proxploy/api/vms.py`, add the owner singleton next to the three from
Task 10:

```python
_require_owner = require_role("owner")
```

Then add this block **above** the snapshot routes from Task 10 (any position
above the `/{vm_id}/{action}` wildcard works; `POST /vms` has no template
segment so it cannot collide, but it is grouped with its siblings):

```python
# PVE's own name rule for a guest: a DNS-ish label, since it becomes the
# hostname the guest advertises.
VM_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,62}$")


def _pick_node(request: Request, host: Host, node: str | None) -> str:
    """Resolve and validate the target node for a create.

    The known-node list comes from the poller's snapshot for this host (its
    `nodes` entries are `{"node": name, …}`), falling back to `Host.node_name`
    for a host that has not been polled yet. A caller-supplied node is checked
    against that list; an unknown one is a 422 rather than a job that fails
    thirty seconds later inside Proxmox.
    """
    snap = request.app.state.poller.snapshots.get(host.id)
    known = [n["node"] for n in (snap.nodes if snap else []) if n.get("node")]
    if not known and host.node_name:
        known = [host.node_name]
    if node:
        if known and node not in known:
            raise HTTPException(422, f"node {node!r} is not on host {host.name} "
                                     f"(known: {', '.join(known)})")
        return node
    if not known:
        raise HTTPException(422, "this host has no known node yet; wait for the "
                                 "first poll or name a node explicitly")
    return known[0]


class VmCreateIn(BaseModel):
    host_id: int
    name: str
    node: str | None = None
    vmid: int | None = None
    cores: int = 2
    memory_mb: int = 2048
    disk_gb: int = 32
    storage: str = "local-lvm"
    iso: str | None = None
    bridge: str = "vmbr0"
    # Task 17's wizard has a VLAN field on its Network step. Pydantic ignores
    # unknown keys rather than rejecting them, so omitting this here would
    # silently drop the operator's tag and build an untagged NIC: a wrong
    # result that looks like a success. Declared, validated, and threaded
    # through to net0 below.
    vlan_tag: int | None = None
    ostype: str = "l26"
    start: bool = False


@router.post("", status_code=202,
             dependencies=[Depends(_require_admin),
                           Depends(require_entitlement("vms.create"))])
def create_vm_route(request: Request, body: VmCreateIn, db=Depends(get_db),
                    user: User = Depends(_require_admin)):
    """Validate the spec here, not in the job: a bad spec should be a 422 the
    operator sees while the form is still open, not a failed job in the history.
    """
    host = db.get(Host, body.host_id)
    if host is None:
        raise HTTPException(404, "host not found")
    if not VM_NAME_RE.match(body.name or ""):
        raise HTTPException(422, "name must be a hostname-shaped label: letters, "
                                 "digits, '.' and '-', starting with a letter or "
                                 "digit")
    for field, value in (("cores", body.cores), ("memory_mb", body.memory_mb),
                         ("disk_gb", body.disk_gb)):
        if value <= 0:
            raise HTTPException(422, f"{field} must be greater than zero")
    node = _pick_node(request, host, body.node)
    vmid = body.vmid
    if vmid is None:
        # Minted here so the 202 can name the id and the audit row records it.
        # cluster_nextid is advisory, not a reservation: between this call and
        # the job's POST another orchestrator can take the id, and PVE then
        # rejects the create. See create_vm()'s ponytail comment: no retry.
        client = client_for_host(request.app, db, host)
        try:
            vmid = int(client.cluster_nextid())
        except ProxmoxError as e:
            raise HTTPException(502, str(e)) from e
    params = {"host_id": host.id, "node": node, "vmid": int(vmid),
              "name": body.name, "cores": body.cores, "memory_mb": body.memory_mb,
              "disk_gb": body.disk_gb, "storage": body.storage, "iso": body.iso,
              "bridge": body.bridge, "vlan_tag": body.vlan_tag,
              "ostype": body.ostype, "start": body.start}
    out = enqueue_and_audit(request, db, user, kind="vm.create",
                            target_type="host", target_id=host.id, params=params)
    return {**out, "vmid": int(vmid)}
```

- [ ] **Step 8: Add the clone and delete routes to `api/vms.py`**

Append immediately after the snapshot routes from Task 10, still **above** the
`/{vm_id}/{action}` wildcard:

```python
class VmCloneIn(BaseModel):
    name: str | None = None
    newid: int | None = None
    full: bool = True
    target: str | None = None
    storage: str | None = None


@router.post("/{vm_id}/clone", status_code=202,
             dependencies=[Depends(_require_admin),
                           Depends(require_entitlement("vms.clone"))])
def clone_vm_route(request: Request, vm_id: int,
                   body: VmCloneIn = Body(default=VmCloneIn()), db=Depends(get_db),
                   user: User = Depends(_require_admin)):
    """`full` is passed through to PVE unvalidated.

    ponytail: PVE permits a linked clone (`full=false`) only from a template,
    and Proxploy cannot tell templates apart, the `vms` table has no `template`
    column and this phase adds no migration. Pre-validating would mean guessing.
    Upgrade path if PVE's rejection proves confusing in practice: have the
    poller mirror `/cluster/resources`'s `template` flag onto `Vm`, then refuse
    a linked clone of a non-template here with a message naming the reason.
    """
    v, host = _vm_and_host(db, vm_id)
    if body.name is not None and not VM_NAME_RE.match(body.name):
        raise HTTPException(422, "name must be a hostname-shaped label")
    newid = body.newid
    if newid is None:
        client = client_for_host(request.app, db, host)
        try:
            newid = int(client.cluster_nextid())
        except ProxmoxError as e:
            raise HTTPException(502, str(e)) from e
    out = enqueue_and_audit(request, db, user, kind="vm.clone", target_type="vm",
                            target_id=v.id,
                            params={"vm_id": v.id, "newid": int(newid),
                                    "name": body.name, "full": body.full,
                                    "target": body.target,
                                    "storage": body.storage})
    return {**out, "vmid": int(newid)}


class VmDeleteIn(BaseModel):
    confirm: str | None = None


@router.delete("/{vm_id}", status_code=202,
               dependencies=[Depends(_require_owner),
                             Depends(require_entitlement("vms.create"))])
def delete_vm_route(request: Request, vm_id: int,
                    body: VmDeleteIn = Body(default=VmDeleteIn()),
                    db=Depends(get_db), user: User = Depends(_require_owner)):
    """The most destructive route in this phase: the guest and its disks are
    gone, and nothing here backs them up first. Doc 05 puts it at owner, one
    rung above every other VM route; on top of that it takes the same
    typed-confirmation path as a self-targeted stop, and refuses a running
    guest outright rather than forcing it down first.
    """
    v, _host = _vm_and_host(db, vm_id)
    name = v.name or f"VM {v.vmid}"
    ip = request.client.host if request.client else None

    def _deny(payload: dict):
        write_audit(db, actor_type="user", actor_id=user.id, action="vm.delete",
                    target_type="vm", target_id=v.id, result="denied", ip=ip)
        raise HTTPException(409, payload)

    # One guard point for "is this Proxploy itself". is_self() answers False for
    # every VM today (selfguard.py:21: Proxploy ships as an LXC CT), so this is
    # currently always a pass. It is called anyway rather than reasoned around:
    # the day a VM-hosted install exists, the guard is already wired, and the
    # alternative is a comment asserting an invariant no code enforces.
    if is_self(db, "vm", v.id):
        _deny({"error": "self_target", "confirm_phrase": name,
               "detail": f"{name} is the guest Proxploy itself runs in, "
                         f"destroying it would destroy this process."})
    if (v.status or "") == "running":
        _deny({"error": "guest_running",
               "detail": f"stop {name} before destroying it"})
    if (body.confirm or "") != name:
        _deny({"error": "confirm_required", "confirm_phrase": name,
               "detail": (f"Destroying {name} deletes the VM and every disk "
                          f"attached to it. There is no undo and no automatic "
                          f"backup. Type the VM name to confirm.")})
    return enqueue_and_audit(request, db, user, kind="vm.delete", target_type="vm",
                             target_id=v.id, params={"vm_id": v.id, "vmid": v.vmid})
```

Add the one import this block needs to the top of `api/vms.py`:

```python
from proxploy.services.selfguard import is_self
```

- [ ] **Step 9: Run the task's tests**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_vm_create_clone.py -q`
Expected: PASS, 20 passed.

- [ ] **Step 10: Run the VM, snapshot and invariant regressions**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_snapshots_api.py tests/test_apps_vms_api.py tests/test_lifecycle_api.py tests/test_backups_api.py tests/test_route_auth_invariant.py tests/test_no_secret_echo.py -q`
Expected: PASS, unchanged counts. `test_backups_api.py` is in this list on
purpose: Step 4 edited the `_GuestFactory.post()` leaf Task 9's restore path
depends on, and `test_restore_guest_posts_to_the_guest_create_endpoint` is the
proof the shared recorder still behaves identically.

- [ ] **Step 11: Run the full backend suite**

Run: `cd backend && ./.venv/bin/python -m pytest tests/ -q -m "not pve_integration and not e2e"`
Expected: Task 10's total + 20 passed, 0 failed, 0 errors.

- [ ] **Step 12: Commit**

```bash
git add backend/proxploy/services/proxmox.py backend/proxploy/services/guestjobs.py backend/proxploy/api/vms.py backend/tests/fakes/pve.py backend/tests/test_vm_create_clone.py
git commit -m "feat(vms): create, clone and destroy routes and jobs"
```

---

## Task 12: Frontend: Storage page, `api/storage.ts` read hooks, and the `live.ts` resource/job routing fix

**Files:**
- Create: `frontend/src/api/storage.ts`, `frontend/src/components/StorageCard.tsx`, `frontend/src/routes/storage.tsx`
- Modify: `frontend/src/router.tsx`, `frontend/src/api/live.ts`
- Test: `frontend/src/tests/storage.test.tsx` (new), `frontend/src/tests/live.test.ts` (extend)

**Interfaces:**
- Consumes (Task 3's backend, exact shapes; do not re-derive):
  `GET /api/v1/storage -> [{host_id, host_name, node, storage, type, content: string[], shared, status, used_bytes, total_bytes, used_pct}]`,
  `GET /api/v1/storage/{host_id}/{name} -> {…same…, avail_bytes, nodes: string[]}`,
  `GET /api/v1/storage/{host_id}/{name}/content?node=&content= -> [{volid, format, size, used, vmid, ctime, content, notes, verification}]`.
  Also `UsageBar` + `STORAGE_GRADIENT`/`DANGER_GRADIENT`, `EmptyState`, `KVGrid`, `Button`, `lib/format::{fmtBytes, fmtPct}`, `shellRoute` from `./shell`.
- Produces:
  - `api/storage.ts::useStorage() -> UseQueryResult<StorageRow[]>`: key `['storage']`, `refetchInterval: 60_000` (doc 06 §d)
  - `api/storage.ts::useStorageDetail(hostId: number | null, name: string | null) -> UseQueryResult<StorageDetail>`: key `['storage', hostId, name]`
  - `api/storage.ts::useStorageContent(hostId: number | null, name: string | null, contentType?: string) -> UseQueryResult<VolumeRow[]>`: key `['storage', hostId, name, 'content', contentType]`
  - types `StorageRow`, `StorageDetail`, `VolumeRow`
  - `components/StorageCard.tsx::StorageCard({ row: StorageRow; onOpen: (row: StorageRow) => void })`
  - `routes/storage.tsx::StoragePage` (component, imported by tests) and `routes/storage.tsx::storageRoute` (`createRoute`, `getParentRoute: () => shellRoute`, `path: '/storage'`)
  - `api/live.ts::RESOURCE_KEY: Record<string, string>`: the single `d.type` / `d.target_type` → query-key-root map both `applyResource` and `applyJob` route through

> **Plan note, why `live.ts` is in this task and not a later one.**
> `applyResource`'s `const key = d.type === 'app' ? 'apps' : 'vms'` is an
> *else-is-vms* fallthrough: the very first `{"type": "storage"}` event Task 4's
> upload job publishes invalidates `['vms']` and leaves `['storage']` stale, so
> the Storage page would sit on dead data while the VM list refetched for no
> reason. `applyJob` has the same shape one level up, it invalidates a resource
> cache only for `target_type` of `app`/`vm`, and every Phase 6 job carries
> `storage`, `backup` or `network`. Both are one-line-per-type fixes, and both
> have to land with the first page that depends on them. `['vms']` stays a
> prefix match, so a `vm.snapshot_create` job still invalidates
> `['vms', id, 'snapshots']` for free (Task 16).

> **Plan note, no "Add storage" button in this task.**
> Doc 06 §(a) row 43 puts one in the header and Task 13 adds it, wired to the
> `StorageForm` dialog it opens, in this same file. A button that renders now
> and does nothing for two commits is worse than no button: it is untestable,
> it invites a placeholder `onClick`, and the header line it sits on is
> re-touched by Task 13 anyway. The count subtitle, the normative part of that
> row, ships here.

- [ ] **Step 1: Write the failing `live.ts` routing tests**

Append to `frontend/src/tests/live.test.ts` (the file already imports `QueryClient`, `describe/expect/it`; add `vi` to the vitest import and `applyJob` to the live import):

```ts
import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import { applyJob, applyMetrics, applyResource } from '../api/live'
```

```ts
describe('applyResource, Phase 6 resource types', () => {
  it('routes storage/backup/network events to their own keys, never to vms', () => {
    const qc = client()
    const spy = vi.spyOn(qc, 'invalidateQueries')
    applyResource(qc, { type: 'storage', id: 1, change: 'content' })
    applyResource(qc, { type: 'backup', id: 1, change: 'list' })
    applyResource(qc, { type: 'network', id: 1, change: 'list' })
    expect(spy).toHaveBeenCalledWith({ queryKey: ['storage'] })
    expect(spy).toHaveBeenCalledWith({ queryKey: ['backups'] })
    expect(spy).toHaveBeenCalledWith({ queryKey: ['network'] })
    // the whole point: the old else-branch sent all three here
    expect(spy).not.toHaveBeenCalledWith({ queryKey: ['vms'] })
  })

  it('ignores an unknown type instead of guessing a cache to invalidate', () => {
    const qc = client()
    const spy = vi.spyOn(qc, 'invalidateQueries')
    applyResource(qc, { type: 'wormhole', id: 1, change: 'list' })
    expect(spy).not.toHaveBeenCalled()
  })

  it('never runs the id-keyed status patch for a non-guest type', () => {
    // A storage event's `id` is a HOST id, and ['storage'] rows have no `id`
    // at all, patching by id there would silently corrupt whichever row
    // happened to collide.
    const qc = client()
    qc.setQueryData(['storage'], [{ host_id: 7, storage: 'local', status: 'available' }])
    applyResource(qc, { type: 'storage', id: 7, change: 'status', status: 'inactive' })
    expect((qc.getQueryData(['storage']) as any)[0].status).toBe('available')
  })
})

describe('applyJob, Phase 6 target types', () => {
  const terminal = (target_type: string) =>
    ({ id: 1, kind: `${target_type}.thing`, status: 'succeeded', target_type })

  it('invalidates the matching resource cache for storage/backup/network jobs', () => {
    for (const [target, key] of [['storage', 'storage'], ['backup', 'backups'],
                                 ['network', 'network']] as const) {
      const qc = new QueryClient()
      const spy = vi.spyOn(qc, 'invalidateQueries')
      applyJob(qc, terminal(target))
      expect(spy).toHaveBeenCalledWith({ queryKey: [key] })
      expect(spy).toHaveBeenCalledWith({ queryKey: ['jobs'] })
    }
  })

  it('still invalidates vms for a vm job, which prefix-covers the snapshots key', () => {
    const qc = new QueryClient()
    const spy = vi.spyOn(qc, 'invalidateQueries')
    applyJob(qc, terminal('vm'))
    expect(spy).toHaveBeenCalledWith({ queryKey: ['vms'] })
  })
})
```

- [ ] **Step 2: Run to verify the failure**

Run: `cd frontend && npx vitest run src/tests/live.test.ts`
Expected: FAIL, 3 of the 5 new tests fail. "routes storage/backup/network events" fails on `expect(spy).not.toHaveBeenCalledWith({queryKey:['vms']})` (all three landed in `['vms']` via the else-branch). "ignores an unknown type" fails the same way. "invalidates the matching resource cache for storage/backup/network jobs" fails on `expect(spy).toHaveBeenCalledWith({queryKey:['storage']})`, `applyJob` only knows `app`/`vm`. The two pre-existing `applyResource` tests and both remaining new ones PASS.

- [ ] **Step 3: Extend `api/live.ts`**

In `frontend/src/api/live.ts`, insert the map above `applyResource` and rewrite that function's routing:

```ts
/**
 * `d.type` (resource events) and `d.target_type` (job events) → the root of the
 * query key that owns that resource. One map, both functions, because they
 * used to disagree: applyResource fell through to 'vms' for anything it did
 * not recognise and applyJob invalidated nothing at all, so Phase 6's storage /
 * backup / network events refreshed the VM list while their own pages went
 * stale. An unlisted type now routes NOWHERE, which is the honest answer; 
 * a guess here is a wrong cache read somewhere else.
 */
const RESOURCE_KEY: Record<string, string> = {
  app: 'apps',
  vm: 'vms',
  storage: 'storage',
  backup: 'backups',
  network: 'network',
}

/** SSE `resource` event → patch status, invalidate everything else (doc 06 §d). */
export function applyResource(qc: QueryClient, d: ResourceEvent) {
  if (d.type === 'host') {
    qc.invalidateQueries({ queryKey: ['cluster'] })
    qc.invalidateQueries({ queryKey: ['hosts'] })
    return
  }
  const key = RESOURCE_KEY[d.type]
  if (!key) return
  // Guests only. A storage/backup/network event's `id` is a HOST id and those
  // caches hold no `id` column, running the row patch there would edit
  // whichever unrelated row happened to collide.
  if (d.change === 'status' && d.id != null && (d.type === 'app' || d.type === 'vm')) {
    qc.setQueriesData({ queryKey: [key] }, (v: unknown) => {
      if (Array.isArray(v)) {
        return v.map((r: any) => (r.id === d.id ? { ...r, status: d.status } : r))
      }
      const row = v as { id?: number } | undefined
      return row && row.id === d.id ? { ...row, status: d.status } : v
    })
    return
  }
  if (d.change === 'discovered') {
    qc.invalidateQueries({ queryKey: ['apps', 'discovered'] })
    return
  }
  qc.invalidateQueries({ queryKey: [key] })
}
```

Then, in `applyJob`, replace the two hard-coded target lines:

```ts
  if (d.target_type === 'app') qc.invalidateQueries({ queryKey: ['apps'] })
  if (d.target_type === 'vm') qc.invalidateQueries({ queryKey: ['vms'] })
```

with:

```ts
  // ['vms'] is a prefix match, so a vm.snapshot_* job invalidates
  // ['vms', id, 'snapshots'] here for free; Task 16 adds no wiring.
  const resourceKey = d.target_type ? RESOURCE_KEY[d.target_type] : undefined
  if (resourceKey) qc.invalidateQueries({ queryKey: [resourceKey] })
```

- [ ] **Step 4: Run to verify the live tests pass**

Run: `cd frontend && npx vitest run src/tests/live.test.ts`
Expected: PASS (3 pre-existing + 5 new = 8 tests).

- [ ] **Step 5: Write the failing Storage page tests**

```tsx
// frontend/src/tests/storage.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const LOCAL = {
  host_id: 1, host_name: 'host-01', node: 'pve1', storage: 'local', type: 'dir',
  content: ['iso', 'vztmpl', 'backup'], shared: false, status: 'available',
  used_bytes: 107374182400, total_bytes: 429496729600, used_pct: 25.0,
}
const PBS = {
  host_id: 1, host_name: 'host-01', node: 'pve1', storage: 'pbs-main', type: 'pbs',
  content: ['backup'], shared: true, status: 'available',
  used_bytes: 924000000000, total_bytes: 1000000000000, used_pct: 92.4,
}
const ISO = {
  volid: 'local:iso/ubuntu-24.04.iso', format: 'iso', size: 6000000000, used: 0,
  vmid: null, ctime: 1730000000, content: 'iso', notes: null, verification: null,
}
const DUMP = {
  volid: 'local:backup/vzdump-qemu-100.vma.zst', format: 'vma.zst', size: 900000,
  used: 0, vmid: 100, ctime: 1730000100, content: 'backup', notes: 'nightly',
  verification: { state: 'ok' },
}

const calls: string[] = []
vi.mock('../api/client', () => ({
  api: vi.fn((path: string) => {
    calls.push(path)
    if (path.includes('/content')) {
      return Promise.resolve(path.includes('content=backup') ? [DUMP] : [ISO])
    }
    if (path === '/storage/1/local') {
      return Promise.resolve({ ...LOCAL, avail_bytes: 322122547200, nodes: ['pve1'] })
    }
    if (path === '/storage') return Promise.resolve([LOCAL, PBS])
    return Promise.resolve(null)
  }),
  ApiError: class extends Error {},
}))

vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ children }: { children?: unknown }) => <a>{children as never}</a>,
  useNavigate: () => () => {},
  useSearch: () => ({}),
}))

import { StoragePage } from '../routes/storage'

const withQuery = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('StoragePage', () => {
  it('counts the datastores in the header (doc 06 §a row 43)', async () => {
    withQuery(<StoragePage />)
    expect(await screen.findByText('2 datastores across the cluster')).toBeInTheDocument()
  })

  it('renders a card per datastore with the node · type subline and a % badge', async () => {
    withQuery(<StoragePage />)
    expect(await screen.findByText('local')).toBeInTheDocument()
    expect(screen.getByText('pve1 · dir')).toBeInTheDocument()
    expect(screen.getByText('pve1 · pbs')).toBeInTheDocument()
    expect(screen.getByText('25%')).toBeInTheDocument()
    expect(screen.getByText('92%')).toBeInTheDocument()
    expect(screen.getByText('100.0 GiB / 400.0 GiB')).toBeInTheDocument()
  })

  it('turns the usage bar red past 80% and leaves the rest violet', async () => {
    const { container } = withQuery(<StoragePage />)
    await screen.findByText('local')
    // UsageBar paints its fill with an inline `background: <gradient>`; the
    // codebase has no test ids, so read the style the same way a human would.
    const bars = [...container.querySelectorAll('div[style*="linear-gradient"]')]
      .map((el) => el.getAttribute('style') ?? '')
    expect(bars[0]).toContain('#A78BFA')  // local, 25% → STORAGE_GRADIENT
    expect(bars[1]).toContain('#F26D6D')  // pbs-main, 92% → DANGER_GRADIENT
  })

  it('opens the content browser on a card click and lists the volumes', async () => {
    withQuery(<StoragePage />)
    fireEvent.click(await screen.findByRole('button', { name: /local/ }))
    expect(await screen.findByText('local:iso/ubuntu-24.04.iso')).toBeInTheDocument()
    expect(screen.getByText('5.6 GiB')).toBeInTheDocument()
    // detail hook supplies the free-space line the list row cannot
    await waitFor(() => expect(screen.getByText('300.0 GiB')).toBeInTheDocument())
  })

  it('refetches through the content endpoint when the content filter changes', async () => {
    withQuery(<StoragePage />)
    fireEvent.click(await screen.findByRole('button', { name: /local/ }))
    await screen.findByText('local:iso/ubuntu-24.04.iso')
    fireEvent.click(screen.getByRole('button', { name: 'Backups' }))
    expect(await screen.findByText('local:backup/vzdump-qemu-100.vma.zst')).toBeInTheDocument()
    expect(calls).toContain('/storage/1/local/content?content=backup')
  })
})
```

- [ ] **Step 6: Run to verify the failure**

Run: `cd frontend && npx vitest run src/tests/storage.test.tsx`
Expected: FAIL, the whole file errors before any test runs with `Failed to resolve import "../routes/storage" from "src/tests/storage.test.tsx"`.

- [ ] **Step 7: Write `src/api/storage.ts`**

```ts
// api/storage.ts, read hooks for the Storage page (doc 05 §Storage, doc 06 §d).
// Same shape as api/catalog.ts: plain useQuery wrappers, no client-side state.
import { useQuery } from '@tanstack/react-query'
import { api } from './client'

export type StorageRow = {
  host_id: number
  host_name: string
  node: string
  storage: string
  type: string | null
  content: string[]
  shared: boolean
  status: string
  used_bytes: number
  total_bytes: number
  used_pct: number
}

export type StorageDetail = StorageRow & { avail_bytes: number; nodes: string[] }

export type VolumeRow = {
  volid: string
  format: string | null
  size: number
  used: number
  vmid: number | null
  ctime: number | null
  content: string | null
  notes: string | null
  verification: { state?: string } | null
}

/** Whole-cluster datastore list. Served from the poll snapshot, so it is cheap
 *  and 60 s is the doc 06 §d interval for it. */
export function useStorage() {
  return useQuery({
    queryKey: ['storage'],
    refetchInterval: 60_000,
    queryFn: () => api<StorageRow[]>('/storage'),
  })
}

/** One datastore, live from Proxmox; the only source of `avail_bytes` and the
 *  full `nodes` list.
 *
 *  ponytail: keyed on (host, name) with no node, matching the interface
 *  contract. The backend resolves the node itself (first node the last poll saw
 *  serving that name), so two same-named LOCAL datastores on different nodes
 *  share this entry and both show the first node's free space. Every number on
 *  the CARD comes from the clicked row and stays exact; only this panel's
 *  free-space line is affected. Add `node` to the key and the query string if a
 *  real fleet ever hits it. */
export function useStorageDetail(hostId: number | null, name: string | null) {
  return useQuery({
    queryKey: ['storage', hostId, name],
    enabled: hostId != null && name != null,
    queryFn: () => api<StorageDetail>(`/storage/${hostId}/${name}`),
  })
}

export function useStorageContent(hostId: number | null, name: string | null,
                                  contentType?: string) {
  return useQuery({
    queryKey: ['storage', hostId, name, 'content', contentType],
    enabled: hostId != null && name != null,
    queryFn: () => {
      const p = new URLSearchParams()
      if (contentType) p.set('content', contentType)
      const qs = p.toString()
      return api<VolumeRow[]>(`/storage/${hostId}/${name}/content${qs ? `?${qs}` : ''}`)
    },
  })
}
```

- [ ] **Step 8: Write `src/components/StorageCard.tsx`**

```tsx
import type { StorageRow } from '../api/storage'
import { fmtBytes, fmtPct } from '../lib/format'
import { DANGER_GRADIENT, STORAGE_GRADIENT, UsageBar } from './UsageBar'

// doc 06 §a row 43 / §c: violet is storage's reserved accent, red takes over
// past 80%, the one place on this page the palette is a warning and not a
// decoration.
const DANGER_PCT = 80

export function StorageCard({ row, onOpen }:
  { row: StorageRow; onOpen: (row: StorageRow) => void }) {
  const hot = row.used_pct > DANGER_PCT
  return (
    <button
      type="button"
      onClick={() => onOpen(row)}
      className="rounded-card border border-line-soft bg-panel p-5 text-left transition hover:bg-panel-2 motion-reduce:transition-none"
    >
      <div className="flex items-center gap-3">
        <div
          className="grid h-9 w-9 shrink-0 place-items-center rounded-tile font-mono text-[11px] font-semibold text-[#1b1230]"
          style={{ background: STORAGE_GRADIENT }}
        >
          {(row.type ?? '??').slice(0, 2).toUpperCase()}
        </div>
        <div className="min-w-0">
          <div className="truncate font-mono text-[14px] text-text">{row.storage}</div>
          <div className="truncate font-mono text-[11px] text-text-3">
            {row.node} · {row.type ?? 'unknown'}
          </div>
        </div>
        <span className={`ml-auto shrink-0 rounded-full px-2 py-0.5 font-mono text-[10.5px] ${
          hot ? 'bg-red-dim text-red' : 'bg-panel-2 text-text-2'}`}>
          {fmtPct(row.used_pct)}
        </span>
      </div>
      <div className="mt-3">
        <UsageBar pct={row.used_pct} gradient={hot ? DANGER_GRADIENT : STORAGE_GRADIENT} />
        <div className="mt-1.5 font-mono text-[11px] text-text-3">
          {fmtBytes(row.used_bytes)} / {fmtBytes(row.total_bytes)}
        </div>
      </div>
    </button>
  )
}
```

- [ ] **Step 9: Write `src/routes/storage.tsx`**

```tsx
import { useState } from 'react'
import { createRoute } from '@tanstack/react-router'
import { useStorage, useStorageContent, useStorageDetail } from '../api/storage'
import type { StorageRow, VolumeRow } from '../api/storage'
import { EmptyState } from '../components/EmptyState'
import { KVGrid } from '../components/KVGrid'
import { StorageCard } from '../components/StorageCard'
import { Button } from '../components/ui/button'
import { fmtBytes } from '../lib/format'
// shellRoute comes from ./shell, never ../router; importing router.tsx here
// would force its eager createRouter() to run mid-cycle (cluster.tsx carries
// the same note).
import { shellRoute } from './shell'

const card = 'rounded-card border border-line-soft bg-panel p-5'

// PVE's content classes, in the order the browser shows them. The tab strip is
// filtered against the datastore's own advertised `content` list, so a PBS
// datastore offers Backups only and a dir storage offers all four.
const CONTENT_TABS = [
  { key: 'iso', label: 'ISOs' },
  { key: 'vztmpl', label: 'Templates' },
  { key: 'backup', label: 'Backups' },
  { key: 'images', label: 'Disk images' },
] as const

function fmtCtime(ctime: number | null) {
  return ctime == null ? ', ' : new Date(ctime * 1000).toLocaleString()
}

function VolumeTable({ volumes }: { volumes: VolumeRow[] }) {
  if (volumes.length === 0) {
    return <EmptyState title="Nothing stored here yet" note="Volumes of this content type appear here." />
  }
  return (
    <table className="w-full text-left text-[13px]">
      <thead>
        <tr className="text-[11px] uppercase text-text-3">
          <th scope="col" className="pb-2 font-medium">Volume</th>
          <th scope="col" className="pb-2 font-medium">Format</th>
          <th scope="col" className="pb-2 font-medium">Size</th>
          <th scope="col" className="pb-2 font-medium">Guest</th>
          <th scope="col" className="pb-2 font-medium">Created</th>
        </tr>
      </thead>
      <tbody>
        {volumes.map((v) => (
          <tr key={v.volid} className="border-t border-line-soft hover:bg-panel-2">
            <td className="py-2.5 font-mono">{v.volid}</td>
            <td className="py-2.5 font-mono text-text-2">{v.format ?? ', '}</td>
            <td className="py-2.5 font-mono text-text-2">{fmtBytes(v.size)}</td>
            <td className="py-2.5 font-mono text-text-2">{v.vmid ?? ', '}</td>
            <td className="py-2.5 font-mono text-text-2">{fmtCtime(v.ctime)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function ContentBrowser({ row, onClose }:
  { row: StorageRow; onClose: () => void }) {
  const tabs = CONTENT_TABS.filter((t) => row.content.includes(t.key))
  const [active, setActive] = useState<string>(tabs[0]?.key ?? 'iso')
  const detail = useStorageDetail(row.host_id, row.storage)
  const { data: volumes, isError } = useStorageContent(row.host_id, row.storage, active)

  return (
    <div className={`${card} mt-5`}>
      <div className="mb-4 flex items-start justify-between">
        <div>
          <h2 className="font-mono text-[16px] font-semibold">{row.storage}</h2>
          <div className="font-mono text-[11px] text-text-3">
            {row.host_name} · {row.node} · {row.type ?? 'unknown'}
            {row.shared ? ' · shared' : ''}
          </div>
        </div>
        <Button variant="ghost" className="px-2 py-1 text-[11px]" onClick={onClose}>Close</Button>
      </div>

      <KVGrid items={[
        ['Status', row.status],
        ['Used', fmtBytes(row.used_bytes)],
        ['Free', fmtBytes(detail.data?.avail_bytes)],
        ['Total', fmtBytes(row.total_bytes)],
        ['Nodes', (detail.data?.nodes ?? [row.node]).join(', ')],
        ['Content', row.content.join(', ') || '; '],
      ]} />

      <div className="mb-4 mt-5 flex gap-1 border-b border-line-soft">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setActive(t.key)}
            className={`px-3 py-2 text-[13px] ${
              active === t.key
                ? 'border-b-2 border-amber text-text'
                : 'text-text-2 hover:text-text'}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {isError ? (
        <EmptyState title="Content listing unavailable"
          note="Proxploy could not reach this datastore; it may be offline or the node may be down." />
      ) : (
        <VolumeTable volumes={volumes ?? []} />
      )}
    </div>
  )
}

export function StoragePage() {
  const { data: rows } = useStorage()
  const [open, setOpen] = useState<StorageRow | null>(null)

  return (
    <div>
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h1 className="font-display text-[22px] font-semibold">Storage</h1>
          <div className="text-[12px] text-text-3">
            {rows ? `${rows.length} datastores across the cluster` : '…'}
          </div>
        </div>
      </div>

      {rows && rows.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {rows.map((r) => (
            <StorageCard key={`${r.host_id}:${r.node}:${r.storage}`} row={r} onOpen={setOpen} />
          ))}
        </div>
      ) : (
        <EmptyState title="No datastores yet"
          note="Datastores on connected Proxmox hosts appear here after the first poll." />
      )}

      {open && (
        // Keyed so switching datastores resets the content tab and the two
        // queries, rather than showing the previous datastore's volumes for a
        // frame while the new ones load.
        <ContentBrowser key={`${open.host_id}:${open.storage}`} row={open}
          onClose={() => setOpen(null)} />
      )}
    </div>
  )
}

export const storageRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/storage',
  component: StoragePage,
})
```

- [ ] **Step 10: Run to verify the storage tests pass**

Run: `cd frontend && npx vitest run src/tests/storage.test.tsx`
Expected: PASS (5 tests).

- [ ] **Step 11: Point `router.tsx` at the real route**

In `frontend/src/router.tsx`, delete the placeholder const (lines 20-21):

```tsx
export const storageRoute = page('/storage', 'Storage', 'Phase 6 (Infra pages)',
  'Datastore cards and the content browser arrive in Phase 6.')
```

and add the import alongside the other route-file imports (the `page()` helper and `PlaceholderPage` import stay, `networkRoute` and `backupsRoute` still use them until Tasks 14-15 delete them):

```tsx
import { storeRoute } from './routes/store'
import { storageRoute } from './routes/storage'
```

`routeTree` already lists `storageRoute` in `shellRoute.addChildren([...])` and needs no edit.

- [ ] **Step 12: Run the full frontend suite, build and lint**

Run: `cd frontend && npx vitest run && npm run build && npm run lint`
Expected: 71 + 5 + 5 = **81 passed across 21 files**; clean `tsc -b && vite build`; oxlint clean. (The 5 new `live.test.ts` tests land in the existing file, so the file count rises by one; `storage.test.tsx`, not two.)

- [ ] **Step 13: Commit**

```bash
git add frontend/src/api/storage.ts frontend/src/api/live.ts \
        frontend/src/components/StorageCard.tsx frontend/src/routes/storage.tsx \
        frontend/src/router.tsx frontend/src/tests/storage.test.tsx \
        frontend/src/tests/live.test.ts
git commit -m "feat(storage): datastore cards + content browser, and route SSE storage/backup/network events to their own caches"
```

---

## Task 13: Frontend: storage mutations: multipart upload + attach / edit / detach

**Files:**
- Create: `frontend/src/components/UploadDialog.tsx`, `frontend/src/components/StorageForm.tsx`
- Modify: `frontend/src/api/storage.ts`, `frontend/src/routes/storage.tsx`
- Test: `frontend/src/tests/storage-mutations.test.tsx`

**Interfaces:**
- Consumes (Tasks 4-5's backend, exact shapes):
  `POST /api/v1/storage/{host_id}/{name}/content`: **multipart**, parts `file`, `content`, `node` → 202 `{job: {id, kind, …}}`;
  `POST /api/v1/storage`: `{host_id, storage, type, config}` → 201 `{host_id, storage, type}` (echoes no config, by design);
  `PATCH /api/v1/storage/{host_id}/{name}`: `{config}` → 200 `{host_id, storage, updated: string[]}`;
  `DELETE /api/v1/storage/{host_id}/{name}` → 200 `{host_id, storage, detached: true}` (**owner**-only server-side).
  Also `LockVeil` (first consumer in the codebase), `useEntitlements` from `api/hooks`, `inputCls` from `components/LoginForm`, `JobLog`, `Button`, `toast` from `sonner`, Task 12's `StorageRow` / `StoragePage` / `ContentBrowser`.
- Produces:
  - `api/storage.ts::useUploadContent()`: `mutate({hostId, storage, node, content, file})`, returns `{job: {id: number; kind: string}}`
  - `api/storage.ts::useAttachStorage()`: `mutate({host_id, storage, type, config})`
  - `api/storage.ts::useEditStorage()`: `mutate({host_id, storage, config})`
  - `api/storage.ts::useDetachStorage()`: `mutate({host_id, storage})`
  - `components/UploadDialog.tsx::UploadDialog({ hostId, storage, node, contentTypes, onClose })`
  - `components/StorageForm.tsx::StorageForm({ existing, onClose })` where `existing: StorageRow | null` (null = attach, row = edit + detach)

> **Plan note, the one `api()` exemption in the codebase, and why it must stay one.**
> `src/api/client.ts` does `if (opts.body != null) headers['Content-Type'] = 'application/json'`.
> With a `FormData` body that overwrite is fatal: the browser generates
> `multipart/form-data; boundary=…` itself and forcing `application/json` over
> it strips the boundary, so FastAPI's `UploadFile` parse fails with 422 before
> a byte of the ISO is read. `postForm()` below therefore calls `fetch`
> directly, and reproduces **everything else** `api()` does (the `/api/v1`
> prefix, `credentials: 'include'`, the `X-CSRF-Token` header read from the
> `pp_csrf` cookie, `ApiError(status, body)` on non-ok) so the exemption stays
> exactly one header wide. The comment in the source says so in as many words;
> a test in Step 1 asserts the header set, so "tidying" it back to `api()`
> fails CI rather than shipping a broken upload.

> **Plan note, upload progress is indeterminate, and that is a named ceiling.**
> `fetch` fires no upload-progress events; `XMLHttpRequest.upload.onprogress`
> does. This dialog uses `fetch` (per the plan spine) and shows an honest
> "Uploading…" state, because switching to XHR means re-implementing the whole
> response/CSRF/error path a second time in a second style for a progress bar
> that covers only the browser→Proxploy half, the Proxploy→PVE half is already
> a real `JobLog` with real percentages the moment the POST returns. The
> `ponytail:` comment in the source names XHR as the upgrade, and the honest
> ceiling on a multi-GB ISO is: the bar you get is the job's, not the browser's.

- [ ] **Step 1: Write the failing mutation tests**

```tsx
// frontend/src/tests/storage-mutations.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const LOCAL = {
  host_id: 1, host_name: 'host-01', node: 'pve1', storage: 'local', type: 'dir',
  content: ['iso', 'vztmpl', 'backup'], shared: false, status: 'available',
  used_bytes: 100, total_bytes: 400, used_pct: 25.0,
}

let features: Record<string, boolean> = { 'storage.manage': true }
const calls: { path: string; opts?: any }[] = []

vi.mock('../api/client', () => ({
  api: vi.fn((path: string, opts?: any) => {
    calls.push({ path, opts })
    if (path === '/entitlements') {
      return Promise.resolve({ tier: 'pro', features, grace: null })
    }
    if (path === '/hosts') return Promise.resolve([{ id: 1, name: 'host-01' }])
    if (path.endsWith('/events')) return Promise.resolve([])
    if (path === '/storage') return Promise.resolve([LOCAL])
    if (path.includes('/content')) return Promise.resolve([])
    if (path === '/storage/1/local') {
      return Promise.resolve({ ...LOCAL, avail_bytes: 300, nodes: ['pve1'] })
    }
    return Promise.resolve({ host_id: 1, storage: 'local' })
  }),
  ApiError: class extends Error {},
}))

vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ children }: { children?: unknown }) => <a>{children as never}</a>,
  useNavigate: () => () => {},
  useSearch: () => ({}),
}))

import { StorageForm } from '../components/StorageForm'
import { UploadDialog } from '../components/UploadDialog'

const withQuery = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  calls.length = 0
  features = { 'storage.manage': true }
  document.cookie = 'pp_csrf=csrf-token-abc'
})
afterEach(() => { vi.restoreAllMocks() })

describe('UploadDialog', () => {
  it('POSTs multipart with credentials + CSRF and no Content-Type override', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 202, json: () => Promise.resolve({ job: { id: 9, kind: 'storage.upload' } }),
    })
    vi.stubGlobal('fetch', fetchMock)

    withQuery(<UploadDialog hostId={1} storage="local" node="pve1"
      contentTypes={['iso', 'vztmpl', 'backup']} onClose={vi.fn()} />)

    const input = screen.getByLabelText('File') as HTMLInputElement
    const file = new File(['iso-bytes'], 'ubuntu.iso', { type: 'application/octet-stream' })
    fireEvent.change(input, { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: 'Upload' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/storage/1/local/content')
    expect(opts.method).toBe('POST')
    expect(opts.credentials).toBe('include')
    expect(opts.headers['X-CSRF-Token']).toBe('csrf-token-abc')
    // the whole reason this is not api(): a Content-Type here kills the boundary
    expect(opts.headers['Content-Type']).toBeUndefined()
    expect(opts.body).toBeInstanceOf(FormData)
    expect((opts.body as FormData).get('content')).toBe('iso')
    expect((opts.body as FormData).get('node')).toBe('pve1')
    expect((opts.body as FormData).get('file')).toBe(file)
  })

  it('swaps the body for the job log once the upload returns a job', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, status: 202, json: () => Promise.resolve({ job: { id: 9, kind: 'storage.upload' } }),
    }))
    withQuery(<UploadDialog hostId={1} storage="local" node="pve1"
      contentTypes={['iso']} onClose={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('File'),
      { target: { files: [new File(['x'], 'a.iso')] } })
    fireEvent.click(screen.getByRole('button', { name: 'Upload' }))
    expect(await screen.findByRole('button', { name: 'Close' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Upload' })).toBeNull()
  })
})

describe('StorageForm', () => {
  it('attaches with the plugin fields for the chosen type', async () => {
    withQuery(<StorageForm existing={null} onClose={vi.fn()} />)
    await screen.findByRole('option', { name: 'host-01' })
    fireEvent.change(screen.getByLabelText('Host'), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'nfs-media' } })
    fireEvent.change(screen.getByLabelText('Type'), { target: { value: 'nfs' } })
    fireEvent.change(screen.getByLabelText('Server'), { target: { value: '10.0.0.30' } })
    fireEvent.change(screen.getByLabelText('Export'), { target: { value: '/media' } })
    fireEvent.change(screen.getByLabelText('Content'), { target: { value: 'iso,vztmpl' } })
    fireEvent.click(screen.getByRole('button', { name: 'Attach' }))

    await waitFor(() => expect(calls.some((c) => c.path === '/storage' && c.opts?.method === 'POST')).toBe(true))
    const post = calls.find((c) => c.path === '/storage' && c.opts?.method === 'POST')!
    expect(JSON.parse(post.opts.body)).toEqual({
      host_id: 1, storage: 'nfs-media', type: 'nfs',
      config: { server: '10.0.0.30', export: '/media', content: 'iso,vztmpl' },
    })
  })

  it('veils the form when storage.manage is off, and never before entitlements resolve', async () => {
    features = {}
    withQuery(<StorageForm existing={null} onClose={vi.fn()} />)
    // has() is false until the first fetch resolves, gating on !has() alone
    // would veil this for every plan during load.
    expect(screen.queryByText('Unlock Pro')).toBeNull()
    expect(await screen.findByText('Unlock Pro')).toBeInTheDocument()
  })

  it('PATCHes only the fields the operator filled in edit mode', async () => {
    withQuery(<StorageForm existing={LOCAL} onClose={vi.fn()} />)
    fireEvent.change(await screen.findByLabelText('Content'), { target: { value: 'iso,backup' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(calls.some((c) => c.opts?.method === 'PATCH')).toBe(true))
    const patch = calls.find((c) => c.opts?.method === 'PATCH')!
    expect(patch.path).toBe('/storage/1/local')
    expect(JSON.parse(patch.opts.body)).toEqual({ config: { content: 'iso,backup' } })
  })

  it('confirms before detaching and does nothing when the operator cancels', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    withQuery(<StorageForm existing={LOCAL} onClose={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Detach' }))
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('local'))
    expect(calls.some((c) => c.opts?.method === 'DELETE')).toBe(false)

    confirm.mockReturnValue(true)
    fireEvent.click(screen.getByRole('button', { name: 'Detach' }))
    await waitFor(() => expect(calls.some((c) => c.opts?.method === 'DELETE')).toBe(true))
    expect(calls.find((c) => c.opts?.method === 'DELETE')!.path).toBe('/storage/1/local')
  })
})
```

- [ ] **Step 2: Run to verify the failure**

Run: `cd frontend && npx vitest run src/tests/storage-mutations.test.tsx`
Expected: FAIL, the file errors before any test runs with `Failed to resolve import "../components/StorageForm" from "src/tests/storage-mutations.test.tsx"`.

- [ ] **Step 3: Add the four mutations to `src/api/storage.ts`**

Extend the import line at the top of `frontend/src/api/storage.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, api } from './client'
```

and append to the file:

```ts
export type JobResponse = { job: { id: number; kind: string } }

/**
 * The ONE place in this codebase that must NOT go through `api()`.
 *
 * api/client.ts sets `Content-Type: application/json` whenever `opts.body` is
 * non-null. A FormData body needs the BROWSER to set
 * `multipart/form-data; boundary=…` itself; overwriting it strips the boundary
 * and FastAPI's UploadFile parse 422s before a byte of the ISO is read.
 *
 * Everything else `api()` does is reproduced here verbatim, the /api/v1
 * prefix, credentials: 'include', the X-CSRF-Token header read from the
 * pp_csrf cookie, ApiError(status, body) on non-ok; so this stays an
 * exemption exactly one header wide. DO NOT "fix" it back to api().
 *
 * ponytail: fetch fires no upload-progress events, so the dialog shows an
 * indeterminate "Uploading…" for the browser→Proxploy leg; the
 * Proxploy→PVE leg is a real JobLog with real percentages the moment this
 * resolves. Swap to XMLHttpRequest + upload.onprogress if a multi-GB ISO ever
 * makes that first leg feel dead.
 */
async function postForm<T>(path: string, form: FormData): Promise<T> {
  const csrf = document.cookie.split('; ')
    .find((c) => c.startsWith('pp_csrf='))?.split('=')[1] ?? ''
  const r = await fetch('/api/v1' + path, {
    method: 'POST',
    credentials: 'include',
    headers: { 'X-CSRF-Token': csrf },
    body: form,
  })
  const body = r.status === 204 ? null : await r.json().catch(() => null)
  if (!r.ok) throw new ApiError(r.status, body)
  return body as T
}

export type UploadVars = {
  hostId: number; storage: string; node: string; content: string; file: File
}

export function useUploadContent() {
  const qc = useQueryClient()
  return useMutation<JobResponse, ApiError, UploadVars>({
    mutationFn: (v) => {
      const form = new FormData()
      form.append('file', v.file)
      form.append('content', v.content)
      form.append('node', v.node)
      return postForm<JobResponse>(`/storage/${v.hostId}/${v.storage}/content`, form)
    },
    // Same rule as api/jobs.ts::useLifecycle, the resource key is NOT
    // invalidated here. The volume does not exist until the job succeeds, and
    // the SSE `resource` event applyResource now routes to ['storage'] is what
    // refreshes the browser at exactly the right moment (Task 12).
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['cluster', 'activity'] })
    },
  })
}

export type AttachVars = {
  host_id: number; storage: string; type: string; config: Record<string, string>
}

export function useAttachStorage() {
  const qc = useQueryClient()
  return useMutation<{ host_id: number; storage: string; type: string }, ApiError, AttachVars>({
    mutationFn: (v) => api('/storage', { method: 'POST', body: JSON.stringify(v) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['storage'] }),
  })
}

export type EditVars = { host_id: number; storage: string; config: Record<string, string> }

export function useEditStorage() {
  const qc = useQueryClient()
  return useMutation<{ host_id: number; storage: string; updated: string[] }, ApiError, EditVars>({
    mutationFn: (v) => api(`/storage/${v.host_id}/${v.storage}`, {
      method: 'PATCH', body: JSON.stringify({ config: v.config }),
    }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['storage'] }),
  })
}

export function useDetachStorage() {
  const qc = useQueryClient()
  return useMutation<{ host_id: number; storage: string; detached: boolean }, ApiError,
                     { host_id: number; storage: string }>({
    mutationFn: (v) => api(`/storage/${v.host_id}/${v.storage}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['storage'] }),
  })
}
```

- [ ] **Step 4: Write `src/components/UploadDialog.tsx`**

```tsx
import { useState } from 'react'
import { toast } from 'sonner'
import { ApiError } from '../api/client'
import { useUploadContent } from '../api/storage'
import { JobLog } from './JobLog'
import { Button } from './ui/button'

const LABEL: Record<string, string> = { iso: 'ISO image', vztmpl: 'CT template' }

export function UploadDialog({ hostId, storage, node, contentTypes, onClose }: {
  hostId: number; storage: string; node: string; contentTypes: string[]; onClose: () => void
}) {
  const upload = useUploadContent()
  // Proxmox's upload endpoint accepts iso and vztmpl only, backups and disk
  // images get there by being written, not posted. Offering the other two would
  // be a 400 dressed up as a feature.
  const uploadable = contentTypes.filter((c) => c === 'iso' || c === 'vztmpl')
  const [content, setContent] = useState(uploadable[0] ?? 'iso')
  const [file, setFile] = useState<File | null>(null)
  const [jobId, setJobId] = useState<number | null>(null)

  const submit = () => {
    if (!file) return
    upload.mutate({ hostId, storage, node, content, file }, {
      onSuccess: (r) => setJobId(r.job.id),
      onError: (e) => toast.error(
        e instanceof ApiError ? String((e.body as any)?.detail ?? 'Upload rejected') : 'Upload failed'),
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-[520px] rounded-card border border-line bg-panel p-5">
        <h2 className="text-[16px] font-semibold text-text">Upload to {storage}</h2>
        <div className="font-mono text-[11px] text-text-3">{node}</div>

        {jobId ? (
          // Exactly InstallDialog's pattern: the mutation returned {job:{id}},
          // so the dialog becomes the job's live transcript.
          <div className="mt-4">
            <JobLog jobId={jobId} />
            <Button className="mt-3" variant="ghost" onClick={onClose}>Close</Button>
          </div>
        ) : (
          <>
            <div className="mt-4 space-y-3">
              <div>
                <label htmlFor="upload-content"
                  className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">Content type</label>
                <select id="upload-content" value={content}
                  onChange={(e) => setContent(e.target.value)}
                  className="w-full rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px]">
                  {uploadable.map((c) => <option key={c} value={c}>{LABEL[c] ?? c}</option>)}
                </select>
              </div>
              <div>
                <label htmlFor="upload-file"
                  className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">File</label>
                <input id="upload-file" type="file"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  className="w-full rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px] text-text-2" />
              </div>
              <div className="text-[12px] text-text-2">
                The file is streamed through Proxploy to the node, it crosses the
                wire twice and needs that much free space on the Proxploy host
                while the job runs.
              </div>
            </div>
            <div className="mt-4 flex items-center justify-end gap-2">
              {upload.isPending && (
                <span className="mr-auto font-mono text-[11px] text-text-3">Uploading…</span>
              )}
              <Button variant="ghost" onClick={onClose}>Cancel</Button>
              <Button variant="primary" disabled={!file || upload.isPending} onClick={submit}>
                Upload
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Write `src/components/StorageForm.tsx`**

```tsx
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ApiError, api } from '../api/client'
import { useEntitlements } from '../api/hooks'
import { useAttachStorage, useDetachStorage, useEditStorage } from '../api/storage'
import type { StorageRow } from '../api/storage'
import { LockVeil } from './LockVeil'
import { inputCls } from './LoginForm'
import { Button } from './ui/button'

type HostRow = { id: number; name: string }

const TYPES = ['dir', 'nfs', 'cifs', 'pbs'] as const

// Per-plugin field lists. The backend forwards `config` to Proxmox unvalidated
// on purpose (Proxmox is the authority on what a plugin accepts), so this map
// is a CONVENIENCE, not a schema: an unlisted key is a missing input here, not
// a rejected request there.
const FIELDS: Record<string, [string, string, string][]> = {
  dir: [['path', 'Path', 'text']],
  nfs: [['server', 'Server', 'text'], ['export', 'Export', 'text']],
  cifs: [['server', 'Server', 'text'], ['share', 'Share', 'text'],
         ['username', 'Username', 'text'], ['password', 'Password', 'password']],
  pbs: [['server', 'Server', 'text'], ['datastore', 'Datastore', 'text'],
        ['username', 'Username', 'text'], ['password', 'Password', 'password'],
        ['fingerprint', 'Fingerprint', 'text']],
}

const errText = (e: unknown) =>
  e instanceof ApiError
    ? String((e.body as any)?.detail ?? (e.body as any)?.title ?? e.message)
    : 'Request failed'

export function StorageForm({ existing, onClose, defaultType = 'dir' }:
  { existing: StorageRow | null; onClose: () => void; defaultType?: string }) {
  const editing = existing != null
  const ent = useEntitlements()
  // ent.has() returns false until the first fetch resolves, so gating on
  // !has() alone veils this for every plan during load (LifecycleActions and
  // settings.tsx carry the same guard).
  const locked = ent.data != null && !ent.has('storage.manage')

  const { data: hosts } = useQuery({
    queryKey: ['hosts'], queryFn: () => api<HostRow[]>('/hosts'), enabled: !editing,
  })
  const attach = useAttachStorage()
  const edit = useEditStorage()
  const detach = useDetachStorage()

  const [hostId, setHostId] = useState<number | null>(existing?.host_id ?? null)
  const [name, setName] = useState(existing?.storage ?? '')
  // `defaultType` lets the Backups page open this same form pre-set to `pbs`
  // for its "Connect PBS datastore" affordance (doc 10's Phase 6 Backups
  // deliverable), connecting PBS *is* attaching a storage of type pbs, so it
  // reuses this form rather than growing a second, near-identical one.
  const [type, setType] = useState<string>(existing?.type ?? defaultType)
  const [cfg, setCfg] = useState<Record<string, string>>({
    content: existing?.content.join(',') ?? '',
  })
  const set = (k: string, v: string) => setCfg((s) => ({ ...s, [k]: v }))

  const fields: [string, string, string][] = [
    ...(FIELDS[type] ?? []), ['content', 'Content', 'text'],
  ]
  // Blank means "not supplied", on edit that is how a password stays
  // unchanged, and on attach it is how an optional plugin key is omitted.
  const filled = Object.fromEntries(
    fields.map(([k]) => [k, (cfg[k] ?? '').trim()]).filter(([, v]) => v !== ''),
  ) as Record<string, string>

  const canAttach = hostId != null && name.trim() !== '' && Object.keys(filled).length > 0
  const busy = attach.isPending || edit.isPending || detach.isPending

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (editing && existing) {
      edit.mutate({ host_id: existing.host_id, storage: existing.storage, config: filled }, {
        onSuccess: (r) => { toast.success(`Updated ${r.updated.join(', ')}`); onClose() },
        onError: (err) => toast.error(errText(err)),
      })
      return
    }
    if (!canAttach || hostId == null) return
    attach.mutate({ host_id: hostId, storage: name.trim(), type, config: filled }, {
      onSuccess: () => { toast.success(`Attached ${name.trim()}`); onClose() },
      onError: (err) => toast.error(errText(err)),
    })
  }

  const remove = () => {
    if (!existing) return
    // window.confirm is this codebase's destructive-but-not-self precedent
    // (routes/settings.tsx). Detaching strands guest disks behind a removed
    // definition, which is exactly the class of misclick that needs a stop.
    if (!window.confirm(
      `Detach storage "${existing.storage}" from ${existing.host_name}? ` +
      'Guests still pointing at it will lose their disks. The data upstream is not deleted.')) return
    detach.mutate({ host_id: existing.host_id, storage: existing.storage }, {
      onSuccess: () => { toast.success(`Detached ${existing.storage}`); onClose() },
      onError: (err) => toast.error(errText(err)),
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-[520px] rounded-card border border-line bg-panel p-5">
        <h2 className="mb-4 text-[16px] font-semibold text-text">
          {editing ? `Edit ${existing?.storage}` : 'Add storage'}
        </h2>

        {/* doc 06 §e rule 1: never hide a gated feature, veil it. The Close
            button below sits OUTSIDE the veil, because LockVeil sets
            pointer-events:none on its children and a dialog you cannot dismiss
            is a worse bug than the one being gated. */}
        <LockVeil locked={locked}
          title="Storage management is a Pro feature"
          subtitle="Attach, edit and detach datastores without leaving Proxploy.">
          <form onSubmit={submit} className="space-y-3">
            {!editing && (
              <div>
                <label htmlFor="sf-host"
                  className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">Host</label>
                <select id="sf-host" className={inputCls} value={hostId ?? ''}
                  onChange={(e) => setHostId(Number(e.target.value) || null)}>
                  <option value="">Select a host…</option>
                  {(hosts ?? []).map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
                </select>
              </div>
            )}
            <div>
              <label htmlFor="sf-name"
                className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">Name</label>
              <input id="sf-name" className={inputCls} value={name} disabled={editing}
                placeholder="nfs-media" onChange={(e) => setName(e.target.value)} />
            </div>
            <div>
              <label htmlFor="sf-type"
                className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">Type</label>
              <select id="sf-type" className={inputCls} value={type} disabled={editing}
                onChange={(e) => setType(e.target.value)}>
                {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            {fields.map(([k, label, inputType]) => (
              <div key={k}>
                <label htmlFor={`sf-${k}`}
                  className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">{label}</label>
                <input id={`sf-${k}`} className={inputCls} type={inputType}
                  value={cfg[k] ?? ''} onChange={(e) => set(k, e.target.value)}
                  placeholder={k === 'content' ? 'iso,vztmpl,backup' : ''} />
              </div>
            ))}
            <div className="flex items-center gap-2 pt-1">
              <Button type="submit" variant="primary" disabled={busy || (!editing && !canAttach)}>
                {editing ? 'Save' : 'Attach'}
              </Button>
              {editing && (
                <Button type="button" variant="danger" disabled={busy} onClick={remove}>
                  Detach
                </Button>
              )}
            </div>
          </form>
        </LockVeil>

        <div className="mt-4 flex justify-end">
          <Button variant="ghost" onClick={onClose}>Close</Button>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 6: Run the mutation tests to verify they pass**

Run: `cd frontend && npx vitest run src/tests/storage-mutations.test.tsx`
Expected: PASS (6 tests).

- [ ] **Step 7: Wire both dialogs into the Storage page**

In `frontend/src/routes/storage.tsx`, extend the imports:

```tsx
import { StorageForm } from '../components/StorageForm'
import { UploadDialog } from '../components/UploadDialog'
```

Give `ContentBrowser` the two actions. Replace its signature and header block, 

find:

```tsx
export function ContentBrowser({ row, onClose }:
  { row: StorageRow; onClose: () => void }) {
```

replace with:

```tsx
export function ContentBrowser({ row, onClose, onManage }:
  { row: StorageRow; onClose: () => void; onManage: (row: StorageRow) => void }) {
  const [uploading, setUploading] = useState(false)
```

find:

```tsx
        <Button variant="ghost" className="px-2 py-1 text-[11px]" onClick={onClose}>Close</Button>
      </div>
```

replace with:

```tsx
        <div className="flex gap-2">
          <Button variant="ghost" className="px-2 py-1 text-[11px]"
            onClick={() => setUploading(true)}>Upload</Button>
          <Button variant="ghost" className="px-2 py-1 text-[11px]"
            onClick={() => onManage(row)}>Manage</Button>
          <Button variant="ghost" className="px-2 py-1 text-[11px]" onClick={onClose}>Close</Button>
        </div>
      </div>

      {uploading && (
        <UploadDialog hostId={row.host_id} storage={row.storage} node={row.node}
          contentTypes={row.content} onClose={() => setUploading(false)} />
      )}
```

Then give `StoragePage` the header button and the form. Replace the whole `StoragePage` function with:

```tsx
export function StoragePage() {
  const { data: rows } = useStorage()
  const [open, setOpen] = useState<StorageRow | null>(null)
  // 'new' = attach, a row = edit + detach. One dialog, two modes; a second
  // component would be the same form with two fields locked.
  const [form, setForm] = useState<'new' | StorageRow | null>(null)

  return (
    <div>
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h1 className="font-display text-[22px] font-semibold">Storage</h1>
          <div className="text-[12px] text-text-3">
            {rows ? `${rows.length} datastores across the cluster` : '…'}
          </div>
        </div>
        <Button variant="primary" onClick={() => setForm('new')}>Add storage</Button>
      </div>

      {rows && rows.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {rows.map((r) => (
            <StorageCard key={`${r.host_id}:${r.node}:${r.storage}`} row={r} onOpen={setOpen} />
          ))}
        </div>
      ) : (
        <EmptyState title="No datastores yet"
          note="Datastores on connected Proxmox hosts appear here after the first poll." />
      )}

      {open && (
        // Keyed so switching datastores resets the content tab and the two
        // queries, rather than showing the previous datastore's volumes for a
        // frame while the new ones load.
        <ContentBrowser key={`${open.host_id}:${open.storage}`} row={open}
          onClose={() => setOpen(null)} onManage={setForm} />
      )}

      {form && (
        <StorageForm existing={form === 'new' ? null : form}
          onClose={() => setForm(null)} />
      )}
    </div>
  )
}
```

- [ ] **Step 8: Assert the page wiring in the page test**

Append to `frontend/src/tests/storage.test.tsx`:

```tsx
  it('opens the attach form from the header button', async () => {
    withQuery(<StoragePage />)
    fireEvent.click(await screen.findByRole('button', { name: 'Add storage' }))
    expect(await screen.findByRole('button', { name: 'Attach' })).toBeInTheDocument()
  })

  it('offers Upload and Manage inside the content browser', async () => {
    withQuery(<StoragePage />)
    fireEvent.click(await screen.findByRole('button', { name: /local/ }))
    expect(await screen.findByRole('button', { name: 'Upload' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Manage' })).toBeInTheDocument()
  })
```

`StorageForm` fetches `/hosts` and `/entitlements`; add both to that file's `api` mock, above its `return Promise.resolve(null)` fallthrough:

```tsx
    if (path === '/hosts') return Promise.resolve([{ id: 1, name: 'host-01' }])
    if (path === '/entitlements') {
      return Promise.resolve({ tier: 'pro', features: { 'storage.manage': true }, grace: null })
    }
```

- [ ] **Step 8b: Add the delete-volume row action to the content browser**

Task 4 ships `DELETE /api/v1/storage/{host_id}/{name}/content/{volid:path}` and doc 01 §5 defines the `storage.content` feature as "Browse ISOs, templates, backups, disk images per datastore; upload ISOs/templates; **delete content**", a content browser that can only add is half the feature, and an endpoint with no caller is dead weight. Deleting a volume is destructive and irreversible, so it uses the `window.confirm` precedent from `routes/settings.tsx`, and the volid goes through `encodeURIComponent` because volids contain `/` (`local:iso/debian-12.iso`) and the route is declared `{volid:path}`.

In `src/api/storage.ts`, add:

```ts
export function useDeleteVolume() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { hostId: number; storage: string; node: string; volid: string }) =>
      api<{ job: { id: number; kind: string } }>(
        `/storage/${v.hostId}/${v.storage}/content/${encodeURIComponent(v.volid)}?node=${encodeURIComponent(v.node)}`,
        { method: 'DELETE' },
      ),
    onSettled: (_d, _e, v) => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['cluster', 'activity'] })
      // The content listing is a live passthrough, not a poll-stomped resource
      // cache, so re-reading it after the job is enqueued is correct here; 
      // the opposite of useLifecycle's rule for ['vms'].
      qc.invalidateQueries({ queryKey: ['storage', v.hostId, v.storage, 'content'] })
    },
  })
}
```

In `src/routes/storage.tsx`, give `VolumeTable` a `Delete` column. Add to its props `{ hostId, node }`, import `useDeleteVolume`, and add the header cell plus this row cell after the ctime cell:

```tsx
            <td className="py-2.5" onClick={(e) => e.stopPropagation()}>
              <Button
                variant="danger"
                className="px-2 py-1 text-[11px]"
                disabled={del.isPending}
                onClick={() => {
                  if (window.confirm(`Delete ${v.volid}? This removes the volume from ${storage} and cannot be undone.`)) {
                    del.mutate({ hostId, storage, node, volid: v.volid })
                  }
                }}
              >
                Delete
              </Button>
            </td>
```

with `const del = useDeleteVolume()` at the top of the component and `<th scope="col" className="pb-2 font-medium">Delete</th>` added to the header row.

Add to `src/tests/storage-mutations.test.tsx`:

```tsx
  it('deletes a volume only after the confirm, and encodes the volid', async () => {
    const spy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={qc}><StoragePage /></QueryClientProvider>)
    fireEvent.click(await screen.findByText('local-lvm'))
    fireEvent.click((await screen.findAllByRole('button', { name: 'Delete' }))[0])
    await waitFor(() =>
      expect(calls.some(c =>
        c.path.startsWith('/storage/1/local-lvm/content/local%3Aiso%2Fdebian-12.iso') &&
        c.opts?.method === 'DELETE')).toBe(true))
    spy.mockRestore()
  })

  it('does not delete when the confirm is dismissed', async () => {
    const spy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={qc}><StoragePage /></QueryClientProvider>)
    fireEvent.click(await screen.findByText('local-lvm'))
    fireEvent.click((await screen.findAllByRole('button', { name: 'Delete' }))[0])
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'Delete' }).length).toBeGreaterThan(0))
    expect(calls.some(c => c.opts?.method === 'DELETE')).toBe(false)
    spy.mockRestore()
  })
```

- [ ] **Step 9: Run both storage test files**

Run: `cd frontend && npx vitest run src/tests/storage.test.tsx src/tests/storage-mutations.test.tsx`
Expected: PASS (7 + 8 = 15 tests).

- [ ] **Step 10: Run the full frontend suite, build and lint**

Run: `cd frontend && npx vitest run && npm run build && npm run lint`
Expected: 81 + 8 (storage-mutations) + 2 (storage.test.tsx additions) = **91 passed across 22 files**; clean `tsc -b && vite build`; oxlint clean.

- [ ] **Step 11: Commit**

```bash
git add frontend/src/api/storage.ts frontend/src/components/UploadDialog.tsx \
        frontend/src/components/StorageForm.tsx frontend/src/routes/storage.tsx \
        frontend/src/tests/storage-mutations.test.tsx frontend/src/tests/storage.test.tsx
git commit -m "feat(storage): multipart ISO upload + attach/edit/detach behind LockVeil"
```

---

## Task 14: Frontend: Network page (bridges, throughput, guest NICs, host config)

**Files:**
- Create: `frontend/src/api/network.ts`, `frontend/src/components/NicForm.tsx`, `frontend/src/components/BridgeForm.tsx`, `frontend/src/routes/network.tsx`
- Modify: `frontend/src/router.tsx`, `frontend/src/components/ConfirmSelfDialog.tsx`
- Test: `frontend/src/tests/network.test.tsx`

**Interfaces:**

- Consumes (Task 6): `GET /api/v1/network/bridges?host=` → `{nodes: [{host_id, host_name, node, interfaces: [{iface, type, method, address, netmask, cidr, gateway, bridge_ports, slaves, vlan_aware, vlan_id, vlan_raw_device, active, autostart, comments}]}], attachments: [{host_id, node, guest_type, guest_id, name, vmid, iface, raw, model, macaddr, bridge, tag, firewall, rate, mtu, link_down}]}`; `GET /api/v1/network/throughput?hours=` → `{hours, resolution, hosts: [{host_id, host_name, in: {resolution, ts, value}, out: {…}}]}`; `PUT /api/v1/{apps|vms}/{id}/network/{iface}` with a body of **only the fields being changed** (the backend does `model_dump(exclude_unset=True)`; an explicit `null` clears a key) → `{iface, value, upid, pending_reboot, detail}`.
- Consumes (Task 7): `POST /api/v1/network/bridges` `{host_id, node, iface, type, config}` → `201 {staged, node, iface}`; `PUT|DELETE /api/v1/network/bridges/{host_id}/{node}/{iface}`; `POST /api/v1/network/{host_id}/{node}/apply` `{confirm}` → `202 {job}` or `409 {"detail": {"error": "confirm_required", "confirm_phrase": "<node>", "detail": "…"}}`; `POST /api/v1/network/{host_id}/{node}/revert` → `{reverted, node}`.
- Consumes (existing): `useEntitlements()`, `LockVeil`, `ConfirmSelfDialog`, `JobLog`, `Sparkline`, `Button`, `EmptyState`, `inputCls`, `lib/format.ts::fmtBps`, `toast` from `sonner`, `shellRoute` from `./shell`.
- Produces:
  - `src/api/network.ts` → types `Iface`, `NodeIfaces`, `Attachment`, `Bridges`, `NetSeries`, `HostThroughput`, `Throughput`, `NicPatch`, `BridgeConfig`; `errBody(e: unknown) -> Record<string, unknown> | null`; hooks `useBridges(hostId?: number)`, `useThroughput(hours?: number)`, `useSetNic()`, `useStageBridge()`, `useUpdateBridge()`, `useDeleteBridge()`, `useApplyNetwork()`, `useRevertNetwork()`
  - `src/components/NicForm.tsx` → `NicForm({ nic: Attachment; bridges: string[]; onClose: () => void })`
  - `src/components/BridgeForm.tsx` → `BridgeForm({ hostId: number; node: string; iface: Iface | null; onClose: () => void })`
  - `src/routes/network.tsx` → `NetworkPage()` and `networkRoute`
  - `ConfirmSelfDialog` gains an optional `title?: string` prop (default unchanged)

**Two deliberate deviations, both recorded here rather than silently:**

1. **`ConfirmSelfDialog` gets a `title` prop.** Its `<h2>` is the hard-coded string "This is Proxploy's own container". Reusing it verbatim for the network apply would put a false sentence above the most dangerous control in the product. One optional prop with the current string as its default keeps `LifecycleActions` and `src/tests/lifecycle.test.tsx` byte-identical (that test asserts on `detail`, not the heading) and is smaller than a second dialog component.
2. **One 409 envelope, verified flat; not two.** An earlier draft of this task assumed `HTTPException(409, {...})` serialises nested under `detail`. It does not: `main.py::problem_handler` does `body.update(exc.detail)` for a dict detail, so *every* dict-bodied error in this app; `selfguard`'s `self_target` and every Phase 6 route alike, arrives flat as `{type, title, status, error, confirm_phrase, detail}`, with `detail` a human-readable string. That is exactly why `LifecycleActions` reads `e.body.error` today. `errBody()` is kept as the single accessor so no call site re-derives the shape, but it is a thin reader, not an unwrapper; its `detail`-is-an-object branch never fires on the routes we ship. Task 15 imports the same helper.

- [ ] **Step 1: Write the failing read-half tests**

`uPlot` cannot render in jsdom, it calls `canvas.getContext('2d')` and jsdom returns `null`, so `_commit` throws `TypeError: Cannot read properties of null (reading 'clearRect')` the moment `Sparkline` is handed a non-empty series (`cluster.test.tsx` sidesteps this by feeding it empty arrays). This page's whole point is non-empty series, so mock the leaf component; the same treatment `vncconsole.test.tsx` already gives `@novnc/novnc`.

```tsx
// frontend/src/tests/network.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const BRIDGES = {
  nodes: [{
    host_id: 1, host_name: 'host-01', node: 'pve1',
    interfaces: [
      { iface: 'vmbr0', type: 'bridge', method: 'static', address: '10.0.0.9',
        netmask: '255.255.255.0', cidr: '10.0.0.9/24', gateway: '10.0.0.1',
        bridge_ports: 'bond0', slaves: null, vlan_aware: true, vlan_id: null,
        vlan_raw_device: null, active: true, autostart: true, comments: 'management' },
      { iface: 'vmbr1', type: 'bridge', method: 'manual', address: null, netmask: null,
        cidr: null, gateway: null, bridge_ports: 'enp3s0', slaves: null,
        vlan_aware: false, vlan_id: null, vlan_raw_device: null, active: false,
        autostart: true, comments: null },
      { iface: 'bond0', type: 'bond', method: 'manual', address: null, netmask: null,
        cidr: null, gateway: null, bridge_ports: null, slaves: 'enp1s0 enp2s0',
        vlan_aware: false, vlan_id: null, vlan_raw_device: null, active: true,
        autostart: true, comments: null },
    ],
  }],
  attachments: [
    { host_id: 1, node: 'pve1', guest_type: 'vm', guest_id: 9, name: 'win11', vmid: 201,
      iface: 'net0', raw: 'virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0,tag=10,firewall=1',
      model: 'virtio', macaddr: 'AA:BB:CC:DD:EE:FF', bridge: 'vmbr0', tag: 10,
      firewall: true, rate: null, mtu: null, link_down: false },
    { host_id: 1, node: 'pve1', guest_type: 'app', guest_id: 5, name: 'Immich', vmid: 150,
      iface: 'net0', raw: 'name=eth0,bridge=vmbr0,hwaddr=BC:24:11:00:11:22,ip=dhcp,type=veth',
      model: 'veth', macaddr: 'BC:24:11:00:11:22', bridge: 'vmbr0', tag: null,
      firewall: false, rate: null, mtu: null, link_down: false },
  ],
}

const THROUGHPUT = {
  hours: 1, resolution: 'raw',
  hosts: [{
    host_id: 1, host_name: 'host-01',
    in: { resolution: 'raw', ts: [1, 2, 3], value: [1_000_000, 1_100_000, 1_250_000] },
    out: { resolution: 'raw', ts: [1, 2, 3], value: [200_000, 210_000, 250_000] },
  }],
}

const calls: { path: string; method: string; body: any }[] = []
let features: Record<string, boolean> = {
  'network.view': true, 'network.guest_config': true, 'network.host_config': true,
}

vi.mock('../api/client', () => {
  class ApiError extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) {
      super(`API ${status}`); this.status = status; this.body = body
    }
  }
  return {
    ApiError,
    api: vi.fn((path: string, opts?: RequestInit) => {
      const method = (opts?.method ?? 'GET').toUpperCase()
      const body = opts?.body ? JSON.parse(String(opts.body)) : {}
      if (path === '/entitlements') {
        return Promise.resolve({ tier: 'builtin', features, grace: null })
      }
      if (method !== 'GET') calls.push({ path, method, body })
      if (path.startsWith('/network/bridges') && method === 'GET') {
        return Promise.resolve(BRIDGES)
      }
      if (path.startsWith('/network/throughput')) return Promise.resolve(THROUGHPUT)
      if (path.endsWith('/apply')) {
        if (!body.confirm) {
          // FastAPI wraps HTTPException(409, {...}) bodies in `detail`; the
          // exact envelope api/network.py::apply_network produces.
          return Promise.reject(new ApiError(409, {
            detail: {
              error: 'confirm_required', confirm_phrase: 'pve1',
              detail: 'Applying the staged network config reloads pve1’s interfaces.',
            },
          }))
        }
        return Promise.resolve({ job: { id: 7, kind: 'network.apply', status: 'queued' } })
      }
      if (path.includes('/network/net')) {
        return Promise.resolve({ iface: 'net0', value: 'virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr1,tag=10,firewall=1',
          upid: null, pending_reboot: false, detail: 'Applied immediately; no reboot needed.' })
      }
      return Promise.resolve(null)
    }),
  }
})

vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ children }: { children?: unknown }) => <a>{children as never}</a>,
  useNavigate: () => () => {},
  useSearch: () => ({}),
}))

// uPlot needs a real canvas 2D context; jsdom hands it null and uPlot's _commit
// throws on the first paint with non-empty data. Same treatment vncconsole.test
// gives @novnc/novnc, the chart is a leaf with nothing this page asserts on.
vi.mock('../components/charts/Sparkline', () => ({
  Sparkline: ({ values }: { values: (number | null)[] }) =>
    <div data-testid="sparkline">{values.length}</div>,
}))

import { NetworkPage } from '../routes/network'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}><NetworkPage /></QueryClientProvider>)
}

// Interface names legitimately appear in three places at once (bridges table,
// attachment map, host-config table), so every query is scoped to the table it
// is about. Each table carries an aria-label for exactly this reason.
const table = (name: string | RegExp) => within(screen.getByRole('table', { name }))

describe('NetworkPage reads', () => {
  it('renders the bridges table with subnet, zone and ports', async () => {
    calls.length = 0
    wrap()
    await screen.findByRole('table', { name: 'Bridges' })
    const t = table('Bridges')
    expect(t.getByText('vmbr0')).toBeInTheDocument()
    expect(t.getByText('10.0.0.9/24')).toBeInTheDocument()
    expect(t.getByText('VLAN-aware')).toBeInTheDocument()
    expect(t.getByText('bond0')).toBeInTheDocument()          // vmbr0's port
    // bonds and physical NICs are not bridges, doc 06's table is bridges only.
    // They belong to the host-config section, which asserts them below.
    expect(t.queryByText('enp1s0 enp2s0')).toBeNull()
  })

  it('renders the throughput figures in Mbps from the newest sample', async () => {
    calls.length = 0
    wrap()
    expect(await screen.findByText(/10\.0 Mbps/)).toBeInTheDocument()   // 1_250_000 B/s in
    expect(screen.getByText(/2\.0 Mbps/)).toBeInTheDocument()           // 250_000 B/s out
    expect(screen.getAllByTestId('sparkline')).toHaveLength(2)
  })

  it('lists the guest attachment map with each NIC bridge and MAC', async () => {
    calls.length = 0
    wrap()
    await screen.findByRole('table', { name: 'Guest attachments' })
    const t = table('Guest attachments')
    expect(t.getByText('win11')).toBeInTheDocument()
    expect(t.getByText('Immich')).toBeInTheDocument()
    expect(t.getByText('AA:BB:CC:DD:EE:FF')).toBeInTheDocument()
    expect(t.getByText('BC:24:11:00:11:22')).toBeInTheDocument()
  })

  it('sends only the fields the NIC form edited, never the model or MAC', async () => {
    calls.length = 0
    wrap()
    await screen.findByRole('table', { name: 'Guest attachments' })
    fireEvent.click(table('Guest attachments').getAllByRole('button', { name: 'Edit' })[0])
    expect(await screen.findByText(/preserved exactly as Proxmox stores/i)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Bridge'), { target: { value: 'vmbr1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save NIC' }))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0].path).toBe('/vms/9/network/net0')
    expect(calls[0].method).toBe('PUT')
    // the whole point: an untouched tag/firewall are absent (exclude_unset),
    // and model/macaddr are never in the body at all
    expect(calls[0].body).toEqual({ bridge: 'vmbr1' })
  })
})
```

- [ ] **Step 2: Run to verify the failure**

Run: `cd frontend && npx vitest run src/tests/network.test.tsx`
Expected: FAIL, `Failed to resolve import "../routes/network" from "src/tests/network.test.tsx"`, so all 4 tests fail at collection.

- [ ] **Step 3: Write `src/api/network.ts`**

```ts
// api/network.ts, Network page server state (doc 05 §Network, doc 06 §a row 44).
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from './client'
import type { JobRow } from './jobs'

export type Iface = {
  iface: string
  type: string | null
  method: string | null
  address: string | null
  netmask: string | null
  cidr: string | null
  gateway: string | null
  bridge_ports: string | null
  slaves: string | null
  vlan_aware: boolean
  vlan_id: number | null
  vlan_raw_device: string | null
  active: boolean
  autostart: boolean
  comments: string | null
}

export type NodeIfaces = {
  host_id: number; host_name: string; node: string; interfaces: Iface[]
}

/** One netN on one guest, as GET /network/bridges reports it. */
export type Attachment = {
  host_id: number; node: string
  guest_type: 'app' | 'vm'; guest_id: number; name: string | null; vmid: number
  iface: string; raw: string
  model: string | null; macaddr: string | null
  bridge: string | null; tag: number | null; firewall: boolean
  rate: string | null; mtu: string | null; link_down: boolean
}

export type Bridges = { nodes: NodeIfaces[]; attachments: Attachment[] }

export type NetSeries = { resolution: string; ts: number[]; value: (number | null)[] }
export type HostThroughput = {
  host_id: number; host_name: string; in: NetSeries; out: NetSeries
}
export type Throughput = { hours: number; resolution: string; hosts: HostThroughput[] }

/**
 * Read a 4xx body.
 *
 * Every dict-bodied `HTTPException` in this app arrives FLAT: `main.py`'s
 * `problem_handler` does `body.update(exc.detail)`, so `HTTPException(409,
 * {"error": "confirm_required", ...})` serialises as
 * `{type, title, status, error, confirm_phrase, detail}`: `detail` is the
 * human-readable string, not a nested object. That is why `LifecycleActions`
 * reads `e.body.error` directly and why it works for Phase 6's routes too.
 * The `detail`-is-an-object branch below is belt-and-braces for a plain
 * string-detail `HTTPException`; it never fires on the routes we ship.
 */
export function errBody(e: unknown): Record<string, unknown> | null {
  if (!(e instanceof ApiError)) return null
  const body = e.body as Record<string, unknown> | null
  if (!body) return null
  const inner = body.detail
  return inner && typeof inner === 'object' ? (inner as Record<string, unknown>) : body
}

export function useBridges(hostId?: number) {
  return useQuery({
    queryKey: ['network', 'bridges', hostId ?? null],
    refetchInterval: 30_000,
    queryFn: () =>
      api<Bridges>(hostId ? `/network/bridges?host=${hostId}` : '/network/bridges'),
  })
}

export function useThroughput(hours = 1) {
  return useQuery({
    queryKey: ['network', 'throughput', hours],
    refetchInterval: false, // SSE-invalidated, like every other metrics read (doc 06 §d)
    queryFn: () => api<Throughput>(`/network/throughput?hours=${hours}`),
  })
}

/**
 * Only the keys the form actually changed. The backend applies
 * `model_dump(exclude_unset=True)`, so an ABSENT key is left alone and an
 * explicit `null` deletes it. `model` and `macaddr` are deliberately not
 * expressible here: they live inside the netN head token
 * (`virtio=AA:BB:CC:DD:EE:FF`) which `services/netconfig.py` round-trips
 * byte-for-byte, and a regenerated MAC breaks every DHCP reservation and
 * MAC-bound licence pointed at that guest.
 */
export type NicPatch = { bridge?: string; tag?: number | null; firewall?: boolean }

export type NicResult = {
  iface: string; value: string; upid: string | null
  pending_reboot: boolean; detail: string
}

export function useSetNic() {
  const qc = useQueryClient()
  return useMutation<NicResult, ApiError,
    { guestType: 'app' | 'vm'; guestId: number; iface: string; patch: NicPatch }>({
    mutationFn: (v) =>
      api<NicResult>(`/${v.guestType === 'app' ? 'apps' : 'vms'}/${v.guestId}/network/${v.iface}`,
        { method: 'PUT', body: JSON.stringify(v.patch) }),
    // A config PUT is not a job (api/network.py::set_guest_nic writes the file
    // synchronously), so useLifecycle's "never invalidate the resource key"
    // rule does not apply; there is no optimistic patch to stomp and the
    // attachment map is exactly what changed.
    onSettled: () => { qc.invalidateQueries({ queryKey: ['network'] }) },
  })
}

/** PVE option names, unpacked straight into the proxmoxer call server-side. */
export type BridgeConfig = Record<string, string | number>

export function useStageBridge() {
  const qc = useQueryClient()
  return useMutation<{ staged: boolean; node: string; iface: string }, ApiError,
    { hostId: number; node: string; iface: string; config: BridgeConfig }>({
    mutationFn: (v) =>
      api('/network/bridges', {
        method: 'POST',
        body: JSON.stringify({ host_id: v.hostId, node: v.node, iface: v.iface,
                               type: 'bridge', config: v.config }),
      }),
    onSettled: () => { qc.invalidateQueries({ queryKey: ['network'] }) },
  })
}

export function useUpdateBridge() {
  const qc = useQueryClient()
  return useMutation<{ staged: boolean; node: string; iface: string }, ApiError,
    { hostId: number; node: string; iface: string; config: BridgeConfig }>({
    mutationFn: (v) =>
      api(`/network/bridges/${v.hostId}/${v.node}/${v.iface}`, {
        method: 'PUT', body: JSON.stringify({ config: v.config }),
      }),
    onSettled: () => { qc.invalidateQueries({ queryKey: ['network'] }) },
  })
}

export function useDeleteBridge() {
  const qc = useQueryClient()
  return useMutation<{ staged: boolean }, ApiError,
    { hostId: number; node: string; iface: string }>({
    mutationFn: (v) =>
      api(`/network/bridges/${v.hostId}/${v.node}/${v.iface}`, { method: 'DELETE' }),
    onSettled: () => { qc.invalidateQueries({ queryKey: ['network'] }) },
  })
}

export function useApplyNetwork() {
  const qc = useQueryClient()
  return useMutation<{ job: JobRow }, ApiError,
    { hostId: number; node: string; confirm?: string }>({
    mutationFn: (v) =>
      api<{ job: JobRow }>(`/network/${v.hostId}/${v.node}/apply`, {
        method: 'POST',
        body: JSON.stringify(v.confirm ? { confirm: v.confirm } : {}),
      }),
    // Job-firing mutation: jobs + activity only, never ['network'] on success
    // (api/jobs.ts::useLifecycle's documented rule). The apply's own terminal
    // `resource` delta is what refreshes the interface list.
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['cluster', 'activity'] })
    },
  })
}

export function useRevertNetwork() {
  const qc = useQueryClient()
  return useMutation<{ reverted: boolean; node: string }, ApiError,
    { hostId: number; node: string }>({
    mutationFn: (v) =>
      api(`/network/${v.hostId}/${v.node}/revert`, { method: 'POST' }),
    onSettled: () => { qc.invalidateQueries({ queryKey: ['network'] }) },
  })
}
```

- [ ] **Step 4: Write `src/components/NicForm.tsx`**

```tsx
import { useState } from 'react'
import { toast } from 'sonner'
import type { Attachment, NicPatch } from '../api/network'
import { errBody, useSetNic } from '../api/network'
import { inputCls } from './LoginForm'
import { Button } from './ui/button'

/**
 * Edit one guest NIC: bridge, VLAN tag, firewall. Nothing else.
 *
 * The NIC's model and MAC are shown but never submitted. Proxmox stores them in
 * the netN head token (`virtio=AA:BB:CC:DD:EE:FF`), and the backend edits the
 * string it read rather than rebuilding one, so this form sends only the keys
 * the operator touched and the head token survives untouched.
 */
export function NicForm({ nic, bridges, onClose }: {
  nic: Attachment; bridges: string[]; onClose: () => void
}) {
  const set = useSetNic()
  const [bridge, setBridge] = useState(nic.bridge ?? '')
  const [tag, setTag] = useState(nic.tag == null ? '' : String(nic.tag))
  const [firewall, setFirewall] = useState(nic.firewall)
  const [error, setError] = useState('')

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    const patch: NicPatch = {}
    if (bridge && bridge !== nic.bridge) patch.bridge = bridge
    const nextTag = tag.trim() === '' ? null : Number(tag)
    if (nextTag !== nic.tag) patch.tag = nextTag   // explicit null clears the key
    if (firewall !== nic.firewall) patch.firewall = firewall
    if (Object.keys(patch).length === 0) { onClose(); return }
    set.mutate({ guestType: nic.guest_type, guestId: nic.guest_id, iface: nic.iface, patch }, {
      onSuccess: (r) => {
        // pending_reboot means PVE filed the change under the guest's PENDING
        // section, say so plainly instead of a green "saved".
        if (r.pending_reboot) toast(r.detail)
        else toast.success(`${nic.iface} updated`)
        onClose()
      },
      onError: (err) =>
        setError(String(errBody(err)?.detail ?? 'Could not update this NIC, try again.')),
    })
  }

  const label = 'mb-1 block text-[11px] uppercase tracking-wide text-text-3'

  return (
    <div role="dialog" aria-label="Edit guest NIC"
         className="fixed inset-0 z-30 grid place-items-center bg-[rgba(11,15,22,.72)] backdrop-blur-[3px]">
      <div className="w-[420px] max-w-[92vw] rounded-card border border-line bg-panel p-5">
        <h2 className="font-display text-[16px] font-semibold">
          {nic.name ?? `guest ${nic.vmid}`} · <span className="font-mono">{nic.iface}</span>
        </h2>
        <div className="mt-2 rounded-ctl border border-line-soft bg-elev p-2 font-mono text-[11px] text-text-3">
          <div>{nic.model ?? ', '} · {nic.macaddr ?? ', '}</div>
          <div className="mt-1 break-all">{nic.raw}</div>
        </div>
        <p className="mt-2 text-[12px] text-text-3">
          The adapter model and MAC address are preserved exactly as Proxmox stores
          them, this form only changes the three fields below.
        </p>

        <form onSubmit={submit} className="mt-4 space-y-3">
          <div>
            <label className={label} htmlFor="nic-bridge">Bridge</label>
            <select id="nic-bridge" className={inputCls} value={bridge}
                    onChange={(e) => setBridge(e.target.value)}>
              {bridge === '' && <option value="">Select a bridge…</option>}
              {bridges.map((b) => <option key={b} value={b}>{b}</option>)}
              {bridge !== '' && !bridges.includes(bridge) &&
                <option value={bridge}>{bridge}</option>}
            </select>
          </div>
          <div>
            <label className={label} htmlFor="nic-tag">VLAN tag (blank = untagged)</label>
            <input id="nic-tag" type="number" min={1} max={4094} className={inputCls}
                   value={tag} onChange={(e) => setTag(e.target.value)} />
          </div>
          <label className="flex items-center gap-2 text-[13px] text-text-2">
            <input type="checkbox" checked={firewall}
                   onChange={(e) => setFirewall(e.target.checked)} />
            Firewall enabled on this NIC
          </label>
          {error && <p className="text-[12.5px] text-red">{error}</p>}
          <div className="flex justify-end gap-2 pt-1">
            <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={set.isPending}>
              {set.isPending ? 'Saving…' : 'Save NIC'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Write `src/routes/network.tsx`, the read half**

The gated host-config section lands in Step 10; this is everything doc 06 §(a) row 44 calls for plus the attachment map.

```tsx
import { useState } from 'react'
import { createRoute } from '@tanstack/react-router'
import { shellRoute } from './shell'
import { useEntitlements } from '../api/hooks'
import { useBridges, useThroughput } from '../api/network'
import type { Attachment, HostThroughput, Iface, NetSeries, NodeIfaces } from '../api/network'
import { EmptyState } from '../components/EmptyState'
import { NicForm } from '../components/NicForm'
import { Sparkline } from '../components/charts/Sparkline'
import { Button } from '../components/ui/button'
import { fmtBps } from '../lib/format'

const card = 'rounded-card border border-line-soft bg-panel p-5'
const th = 'pb-2 font-medium'

/** Newest non-null sample, or null for an empty window. */
function lastValue(s?: NetSeries): number | null {
  const v = s?.value ?? []
  for (let i = v.length - 1; i >= 0; i--) if (v[i] != null) return v[i] as number
  return null
}

// ponytail: doc 06's "Zone badge" renders the VLAN posture that
// GET /nodes/{node}/network actually reports. PVE SDN zones live behind a
// separate /cluster/sdn/zones API this phase does not read; wire that in when a
// real SDN deployment asks for it.
function zoneLabel(i: Iface): string {
  if (i.vlan_id != null) return `VLAN ${i.vlan_id}`
  if (i.vlan_aware) return 'VLAN-aware'
  return i.type ?? ', '
}

function BridgesCard({ nodes }: { nodes: NodeIfaces[] }) {
  const rows = nodes.flatMap((n) =>
    n.interfaces.filter((i) => i.type === 'bridge').map((i) => ({ node: n, iface: i })))
  return (
    <div className={`${card} lg:col-span-2`}>
      <h2 className="mb-3 font-display text-[16px] font-semibold">Bridges</h2>
      {rows.length === 0 ? (
        <p className="text-[12.5px] text-text-3">
          No bridges reported yet, Proxploy reads them live from each node on every load.
        </p>
      ) : (
        <table aria-label="Bridges" className="w-full text-left text-[13px]">
          <thead>
            <tr className="text-[11px] uppercase text-text-3">
              <th scope="col" className={th}>Bridge</th>
              <th scope="col" className={th}>Node</th>
              <th scope="col" className={th}>Subnet</th>
              <th scope="col" className={th}>Zone</th>
              <th scope="col" className={th}>Ports</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ node, iface }) => (
              <tr key={`${node.host_id}:${node.node}:${iface.iface}`}
                  className="border-t border-line-soft hover:bg-panel-2">
                <td className="py-2.5 font-mono">
                  {iface.iface}
                  {!iface.active && <span className="ml-2 text-[11px] text-text-3">down</span>}
                </td>
                <td className="py-2.5 text-text-2">{node.node}</td>
                <td className="py-2.5 font-mono text-text-2">
                  {iface.cidr ?? iface.address ?? ', '}
                </td>
                <td className="py-2.5">
                  <span className="rounded-full border border-blue/30 bg-blue-dim px-2 py-0.5 text-[11px] text-blue">
                    {zoneLabel(iface)}
                  </span>
                </td>
                <td className="py-2.5 font-mono text-text-2">{iface.bridge_ports || ', '}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function ThroughputCard() {
  // 1h window, matching the cluster page's network card.
  const { data } = useThroughput(1)
  const hosts = data?.hosts ?? []
  const total = (pick: (h: HostThroughput) => NetSeries) =>
    hosts.length ? hosts.reduce((a, h) => a + (lastValue(pick(h)) ?? 0), 0) : null
  // ponytail: the two sparklines chart the first host's series, the same
  // simplification cluster.tsx made for its network card, the ↓/↑ figures above
  // them are already fleet-wide. Summed series when a real fleet shows it matters.
  const first = hosts[0]
  return (
    <div className={card}>
      <h2 className="mb-1 font-display text-[16px] font-semibold">Throughput</h2>
      <div className="mb-3 font-mono text-[13px] text-text-2">
        ↓ {fmtBps(total((h) => h.in))} · ↑ {fmtBps(total((h) => h.out))}
      </div>
      <div className="text-[11px] uppercase tracking-wide text-text-3">In</div>
      <Sparkline ts={first?.in.ts ?? []} values={first?.in.value ?? []} color="#5B9DF9" />
      <div className="mt-3 text-[11px] uppercase tracking-wide text-text-3">Out</div>
      <Sparkline ts={first?.out.ts ?? []} values={first?.out.value ?? []} color="#34D3C6" />
      {hosts.length > 1 && (
        <p className="mt-3 text-[11.5px] text-text-3">
          Figures are fleet-wide; the charts show {first?.host_name}.
        </p>
      )}
    </div>
  )
}

function AttachmentMap({ attachments, nodes }: {
  attachments: Attachment[]; nodes: NodeIfaces[]
}) {
  const ent = useEntitlements()
  // has() is false until the first fetch resolves, gating on !has() alone
  // greys the button out for every plan during load.
  const denied = ent.data != null && !ent.has('network.guest_config')
  const [editing, setEditing] = useState<Attachment | null>(null)
  const bridgesOn = (node: string) =>
    nodes.filter((n) => n.node === node)
      .flatMap((n) => n.interfaces.filter((i) => i.type === 'bridge').map((i) => i.iface))

  return (
    <div className={`${card} mt-4`}>
      <h2 className="mb-1 font-display text-[16px] font-semibold">Guest attachments</h2>
      <p className="mb-3 text-[12.5px] text-text-3">Which guest sits on which bridge.</p>
      {attachments.length === 0 ? (
        <p className="text-[12.5px] text-text-3">No guest NICs found on this host.</p>
      ) : (
        <table aria-label="Guest attachments" className="w-full text-left text-[13px]">
          <thead>
            <tr className="text-[11px] uppercase text-text-3">
              <th scope="col" className={th}>Guest</th>
              <th scope="col" className={th}>NIC</th>
              <th scope="col" className={th}>Bridge</th>
              <th scope="col" className={th}>VLAN</th>
              <th scope="col" className={th}>Firewall</th>
              <th scope="col" className={th}>MAC</th>
              <th scope="col" className={th}></th>
            </tr>
          </thead>
          <tbody>
            {attachments.map((a) => (
              <tr key={`${a.guest_type}:${a.guest_id}:${a.iface}`}
                  className="border-t border-line-soft hover:bg-panel-2">
                <td className="py-2.5 font-mono">
                  {a.name ?? `guest ${a.vmid}`}
                  <span className="ml-2 text-[11px] text-text-3">
                    {a.guest_type === 'app' ? 'CT' : 'VM'} {a.vmid}
                  </span>
                </td>
                <td className="py-2.5 font-mono text-text-2">{a.iface}</td>
                <td className="py-2.5 font-mono text-text-2">{a.bridge ?? ', '}</td>
                <td className="py-2.5 font-mono text-text-2">{a.tag ?? ', '}</td>
                <td className={`py-2.5 text-[12px] ${a.firewall ? 'text-green' : 'text-text-3'}`}>
                  {a.firewall ? 'on' : 'off'}
                </td>
                <td className="py-2.5 font-mono text-[12px] text-text-3">{a.macaddr ?? ', '}</td>
                <td className="py-2.5 text-right">
                  <Button variant="ghost" className="px-2 py-1 text-[11px]"
                          disabled={denied}
                          title={denied ? 'Not included in your plan' : undefined}
                          onClick={() => setEditing(a)}>
                    Edit
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {editing && (
        <NicForm nic={editing} bridges={bridgesOn(editing.node)}
                 onClose={() => setEditing(null)} />
      )}
    </div>
  )
}

export function NetworkPage() {
  const { data, isError } = useBridges()
  const nodes = data?.nodes ?? []
  const bridgeCount = nodes.reduce(
    (a, n) => a + n.interfaces.filter((i) => i.type === 'bridge').length, 0)

  return (
    <div>
      <div className="mb-5">
        <h1 className="font-display text-[22px] font-semibold">Network</h1>
        <div className="text-[12px] text-text-3">
          {data ? `${bridgeCount} bridges across ${nodes.length} nodes` : '…'}
        </div>
      </div>

      {isError ? (
        <EmptyState title="Network not readable"
          note="Proxploy reads bridges live from each node, check that the host is connected." />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <BridgesCard nodes={nodes} />
            <ThroughputCard />
          </div>
          <AttachmentMap attachments={data?.attachments ?? []} nodes={nodes} />
        </>
      )}
    </div>
  )
}

// shellRoute comes from ./shell, never ../router; importing router.tsx here
// would force its eager createRouter() to run mid-cycle (cluster.tsx:273-277).
export const networkRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/network',
  component: NetworkPage,
})
```

- [ ] **Step 6: Run to verify the read half passes**

Run: `cd frontend && npx vitest run src/tests/network.test.tsx`
Expected: PASS, 4 passed.

- [ ] **Step 7: Append the gated host-config tests**

```tsx
// frontend/src/tests/network.test.tsx (append)

describe('NetworkPage host config', () => {
  it('veils the host bridge editor when network.host_config is not entitled', async () => {
    calls.length = 0
    features = { 'network.view': true, 'network.guest_config': true }
    wrap()
    expect(await screen.findByText(/Host network editing is a Pro feature/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Unlock Pro/i })).toBeInTheDocument()
    features = { 'network.view': true, 'network.guest_config': true, 'network.host_config': true }
  })

  it('lists every interface type in the host section, not just bridges', async () => {
    calls.length = 0
    wrap()
    await screen.findByRole('table', { name: 'Interfaces on pve1' })
    const t = table('Interfaces on pve1')
    expect(t.getByText('enp1s0 enp2s0')).toBeInTheDocument()   // bond0's slaves
    expect(t.getByText('vmbr1')).toBeInTheDocument()
  })

  it('routes the apply 409 through the typed confirmation and retries with the phrase', async () => {
    calls.length = 0
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: /Apply staged config/i }))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0].path).toBe('/network/1/pve1/apply')
    expect(calls[0].body).toEqual({})

    // the backend's own sentence, not a generic one
    expect(await screen.findByText(/reloads pve1/)).toBeInTheDocument()
    const input = screen.getByLabelText(/type/i)
    fireEvent.change(input, { target: { value: 'pve2' } })
    expect(screen.getByRole('button', { name: /^Confirm$/ })).toBeDisabled()
    fireEvent.change(input, { target: { value: 'pve1' } })
    fireEvent.click(screen.getByRole('button', { name: /^Confirm$/ }))
    await waitFor(() => expect(calls.length).toBe(2))
    expect(calls[1].body).toEqual({ confirm: 'pve1' })
  })
})
```

- [ ] **Step 8: Run to verify the new failures**

Run: `cd frontend && npx vitest run src/tests/network.test.tsx`
Expected: FAIL, 4 passed, 3 failed: `Unable to find an element with the text: /Host network editing is a Pro feature/i`, `Unable to find an accessible element with the role "table" and name "Interfaces on pve1"`, and `Unable to find a button with the name /Apply staged config/i`.

- [ ] **Step 9: Add the `title` prop to `ConfirmSelfDialog`**

In `frontend/src/components/ConfirmSelfDialog.tsx`, replace the props type and the `<h2>` (everything else in the file is unchanged):

```tsx
export function ConfirmSelfDialog({ phrase, detail, title, onConfirm, onCancel }: {
  phrase: string
  detail: string
  /** Defaults to the self-CT heading. Phase 6's network apply and in-place
   *  restore reuse the same typed-confirmation control for a different danger,
   *  and a false heading above the most destructive button in the product is
   *  worse than a prop. */
  title?: string
  onConfirm: (typed: string) => void
  onCancel: () => void
}) {
  const [typed, setTyped] = useState('')
  return (
    <div role="dialog" aria-label="Confirm destructive action"
         className="fixed inset-0 z-30 grid place-items-center bg-[rgba(11,15,22,.72)] backdrop-blur-[3px]">
      <div className="w-[420px] max-w-[92vw] rounded-card border border-line bg-panel p-5">
        <h2 className="font-display text-[16px] font-semibold text-amber">
          {title ?? 'This is Proxploy’s own container'}
        </h2>
```

- [ ] **Step 10: Write `src/components/BridgeForm.tsx`**

```tsx
import { useState } from 'react'
import { toast } from 'sonner'
import type { BridgeConfig, Iface } from '../api/network'
import { errBody, useStageBridge, useUpdateBridge } from '../api/network'
import { inputCls } from './LoginForm'
import { Button } from './ui/button'

/**
 * Create or edit one host bridge. Everything this form does is STAGED: Proxmox
 * writes it to /etc/network/interfaces.new and the live config is untouched
 * until someone presses Apply on the page behind this dialog.
 */
export function BridgeForm({ hostId, node, iface, onClose }: {
  hostId: number; node: string; iface: Iface | null; onClose: () => void
}) {
  const create = useStageBridge()
  const update = useUpdateBridge()
  const editing = iface != null
  const [name, setName] = useState(iface?.iface ?? '')
  const [ports, setPorts] = useState(iface?.bridge_ports ?? '')
  const [cidr, setCidr] = useState(iface?.cidr ?? '')
  const [gateway, setGateway] = useState(iface?.gateway ?? '')
  const [comments, setComments] = useState(iface?.comments ?? '')
  const [vlanAware, setVlanAware] = useState(iface?.vlan_aware ?? false)
  const [autostart, setAutostart] = useState(iface?.autostart ?? true)
  const [error, setError] = useState('')

  const busy = create.isPending || update.isPending

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    const config: BridgeConfig = {
      bridge_vlan_aware: vlanAware ? 1 : 0,
      autostart: autostart ? 1 : 0,
    }
    if (ports.trim()) config.bridge_ports = ports.trim()
    if (cidr.trim()) config.cidr = cidr.trim()
    if (gateway.trim()) config.gateway = gateway.trim()
    if (comments.trim()) config.comments = comments.trim()
    const done = {
      onSuccess: () => {
        toast(`${name} staged on ${node}, nothing changes until you Apply.`)
        onClose()
      },
      onError: (err: unknown) =>
        setError(String(errBody(err)?.detail ?? 'Proxmox rejected that interface config.')),
    }
    if (editing) update.mutate({ hostId, node, iface: name, config }, done)
    else create.mutate({ hostId, node, iface: name, config }, done)
  }

  const label = 'mb-1 block text-[11px] uppercase tracking-wide text-text-3'

  return (
    <div role="dialog" aria-label="Edit host bridge"
         className="fixed inset-0 z-30 grid place-items-center bg-[rgba(11,15,22,.72)] backdrop-blur-[3px]">
      <div className="w-[460px] max-w-[92vw] rounded-card border border-line bg-panel p-5">
        <h2 className="font-display text-[16px] font-semibold">
          {editing ? `Edit ${name} on ${node}` : `New bridge on ${node}`}
        </h2>
        <p className="mt-1 text-[12.5px] text-text-3">
          Staged only. Proxmox writes this to{' '}
          <span className="font-mono">/etc/network/interfaces.new</span>; {node} keeps its
          current network until you apply it.
        </p>

        <form onSubmit={submit} className="mt-4 space-y-3">
          <div>
            <label className={label} htmlFor="br-name">Interface</label>
            <input id="br-name" required disabled={editing} className={inputCls}
                   placeholder="vmbr1" value={name}
                   onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label className={label} htmlFor="br-ports">Bridge ports</label>
            <input id="br-ports" className={inputCls} placeholder="enp3s0 enp4s0"
                   value={ports} onChange={(e) => setPorts(e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={label} htmlFor="br-cidr">CIDR</label>
              <input id="br-cidr" className={inputCls} placeholder="10.9.0.1/24"
                     value={cidr} onChange={(e) => setCidr(e.target.value)} />
            </div>
            <div>
              <label className={label} htmlFor="br-gw">Gateway</label>
              <input id="br-gw" className={inputCls} placeholder="10.9.0.254"
                     value={gateway} onChange={(e) => setGateway(e.target.value)} />
            </div>
          </div>
          <div>
            <label className={label} htmlFor="br-comment">Comment</label>
            <input id="br-comment" className={inputCls} placeholder="lab network"
                   value={comments} onChange={(e) => setComments(e.target.value)} />
          </div>
          <label className="flex items-center gap-2 text-[13px] text-text-2">
            <input type="checkbox" checked={vlanAware}
                   onChange={(e) => setVlanAware(e.target.checked)} /> VLAN aware
          </label>
          <label className="flex items-center gap-2 text-[13px] text-text-2">
            <input type="checkbox" checked={autostart}
                   onChange={(e) => setAutostart(e.target.checked)} /> Start on boot
          </label>
          {error && <p className="text-[12.5px] text-red">{error}</p>}
          <div className="flex justify-end gap-2 pt-1">
            <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={busy || !name.trim()}>
              {busy ? 'Staging…' : 'Stage change'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
```

- [ ] **Step 11: Add the gated host-config section to `src/routes/network.tsx`**

Extend the imports at the top of the file:

```tsx
import { toast } from 'sonner'
import { errBody, useApplyNetwork, useBridges, useDeleteBridge, useRevertNetwork, useThroughput } from '../api/network'
import { BridgeForm } from '../components/BridgeForm'
import { ConfirmSelfDialog } from '../components/ConfirmSelfDialog'
import { JobLog } from '../components/JobLog'
import { LockVeil } from '../components/LockVeil'
```

Add the section component above `NetworkPage`:

```tsx
function HostNetworkSection({ nodes }: { nodes: NodeIfaces[] }) {
  const ent = useEntitlements()
  const locked = ent.data != null && !ent.has('network.host_config')
  const [editing, setEditing] = useState<{ hostId: number; node: string; iface: Iface | null } | null>(null)
  const [guard, setGuard] = useState<{ hostId: number; node: string; phrase: string; detail: string } | null>(null)
  const [jobId, setJobId] = useState<number | null>(null)
  const apply = useApplyNetwork()
  const revert = useRevertNetwork()
  const remove = useDeleteBridge()

  const fire = (hostId: number, node: string, confirm?: string) =>
    apply.mutate({ hostId, node, confirm }, {
      onSuccess: (r) => { setGuard(null); setJobId(r.job.id) },
      onError: (e) => {
        const b = errBody(e)
        // The backend refuses an unconfirmed apply with the node name as the
        // phrase, deliberately the same envelope selfguard uses; escalate to
        // the typed-confirmation dialog and re-fire with what was typed.
        if (b?.error === 'confirm_required') {
          setGuard({ hostId, node, phrase: String(b.confirm_phrase ?? node),
                     detail: String(b.detail ?? '') })
          return
        }
        toast.error('Could not apply the staged config, the node was not changed.')
      },
    })

  const drop = (hostId: number, node: string, iface: string) => {
    if (!window.confirm(
      `Stage removal of ${iface} on ${node}? It disappears from the live config only when you apply.`)) return
    remove.mutate({ hostId, node, iface }, {
      onSuccess: () => toast(`${iface} removal staged on ${node}`),
      onError: () => toast.error(`Could not stage the removal of ${iface}.`),
    })
  }

  return (
    <div className="mt-4">
      <LockVeil locked={locked}
        title="Host network editing is a Pro feature"
        subtitle="Create bridges and VLANs on the node itself, then apply them.">
        <section className={card}>
          <h2 className="font-display text-[16px] font-semibold">Host bridges &amp; VLANs</h2>
          <p className="mt-1 text-[12.5px] text-text-3">
            Edits here are <span className="text-text-2">staged</span>. Proxmox writes them to{' '}
            <span className="font-mono">/etc/network/interfaces.new</span> and changes nothing
            until you apply.
          </p>
          <p className="mt-2 rounded-ctl border border-red/30 bg-red-dim p-2 text-[12.5px] text-text-2">
            <span className="text-red">Applying reloads the node&apos;s interfaces.</span> If the
            staged config is wrong the node loses its network, and the only way back is its
            physical console; there is no undo from here.
          </p>

          {jobId != null && (
            <div className="mt-4">
              <JobLog jobId={jobId} />
              <Button className="mt-3" variant="ghost" onClick={() => setJobId(null)}>Close</Button>
            </div>
          )}

          {nodes.map((n) => (
            <div key={`${n.host_id}:${n.node}`} className="mt-4 border-t border-line-soft pt-4">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <h3 className="font-mono text-[13px]">{n.node}</h3>
                <span className="text-[11.5px] text-text-3">{n.host_name}</span>
                <div className="ml-auto flex gap-2">
                  <Button variant="ghost" className="px-2 py-1 text-[11px]"
                          onClick={() => setEditing({ hostId: n.host_id, node: n.node, iface: null })}>
                    Add bridge
                  </Button>
                  <Button variant="ghost" className="px-2 py-1 text-[11px]"
                          disabled={revert.isPending}
                          onClick={() => revert.mutate({ hostId: n.host_id, node: n.node }, {
                            onSuccess: () => toast(`Staged changes discarded on ${n.node}`),
                            onError: () => toast.error('Could not discard the staged config.'),
                          })}>
                    Discard staged
                  </Button>
                  <Button variant="danger" className="px-2 py-1 text-[11px]"
                          disabled={apply.isPending}
                          onClick={() => fire(n.host_id, n.node)}>
                    Apply staged config
                  </Button>
                </div>
              </div>
              <table aria-label={`Interfaces on ${n.node}`} className="w-full text-left text-[13px]">
                <thead>
                  <tr className="text-[11px] uppercase text-text-3">
                    <th scope="col" className={th}>Interface</th>
                    <th scope="col" className={th}>Type</th>
                    <th scope="col" className={th}>Subnet</th>
                    <th scope="col" className={th}>Ports</th>
                    <th scope="col" className={th}>State</th>
                    <th scope="col" className={th}></th>
                  </tr>
                </thead>
                <tbody>
                  {n.interfaces.map((i) => (
                    <tr key={i.iface} className="border-t border-line-soft hover:bg-panel-2">
                      <td className="py-2.5 font-mono">{i.iface}</td>
                      <td className="py-2.5 text-text-2">{i.type ?? ', '}</td>
                      <td className="py-2.5 font-mono text-text-2">
                        {i.cidr ?? i.address ?? ', '}
                      </td>
                      <td className="py-2.5 font-mono text-text-2">
                        {i.bridge_ports || i.slaves || ', '}
                      </td>
                      <td className={`py-2.5 text-[12px] ${i.active ? 'text-green' : 'text-text-3'}`}>
                        {i.active ? 'up' : 'down'}
                      </td>
                      <td className="py-2.5 text-right">
                        <Button variant="ghost" className="px-2 py-1 text-[11px]"
                                onClick={() => setEditing({ hostId: n.host_id, node: n.node, iface: i })}>
                          Edit
                        </Button>
                        <Button variant="danger" className="ml-2 px-2 py-1 text-[11px]"
                                onClick={() => drop(n.host_id, n.node, i.iface)}>
                          Remove
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </section>
      </LockVeil>

      {editing && (
        <BridgeForm hostId={editing.hostId} node={editing.node} iface={editing.iface}
                    onClose={() => setEditing(null)} />
      )}
      {guard && (
        <ConfirmSelfDialog
          title={`Apply network config on ${guard.node}`}
          phrase={guard.phrase}
          detail={guard.detail}
          onConfirm={(typed) => fire(guard.hostId, guard.node, typed)}
          onCancel={() => setGuard(null)} />
      )}
    </div>
  )
}
```

And render it at the bottom of `NetworkPage`'s success branch, directly after `<AttachmentMap …/>`:

```tsx
          <AttachmentMap attachments={data?.attachments ?? []} nodes={nodes} />
          <HostNetworkSection nodes={nodes} />
```

- [ ] **Step 12: Run the network tests**

Run: `cd frontend && npx vitest run src/tests/network.test.tsx`
Expected: PASS, 7 passed.

- [ ] **Step 13: Point `router.tsx` at the real network route**

In `frontend/src/router.tsx`, delete the placeholder const:

```tsx
export const networkRoute = page('/network', 'Network', 'Phase 6 (Infra pages)',
  'Bridges, VLANs and throughput arrive in Phase 6.')
```

and add the import to the route-import block below `indexRoute` (next to the storage import Task 12 added):

```tsx
import { networkRoute } from './routes/network'
```

`routeTree` already lists `networkRoute` and needs no change. The `page()` helper stays for now, `backupsRoute` is its last consumer and Task 15 deletes both.

- [ ] **Step 14: Run the full frontend suite, build and lint**

Run: `cd frontend && npx vitest run && npm run build && npm run lint`
Expected: Task 13's total **+ 7 passed** across **+1 file**; `tsc -b && vite build` clean; oxlint clean. A `tsc` error naming `networkRoute` means Step 13's placeholder const was left behind alongside the import.

- [ ] **Step 15: Commit**

```bash
git add frontend/src/api/network.ts frontend/src/components/NicForm.tsx \
        frontend/src/components/BridgeForm.tsx frontend/src/routes/network.tsx \
        frontend/src/components/ConfirmSelfDialog.tsx frontend/src/router.tsx \
        frontend/src/tests/network.test.tsx
git commit -m "feat(network): live bridges, throughput, guest NIC editor and confirmed host apply"
```

---

## Task 15: Frontend: Backups page (+ the last placeholder is deleted)

**Files:**
- Create: `frontend/src/api/backups.ts`, `frontend/src/components/RestoreDialog.tsx`, `frontend/src/routes/backups.tsx`
- Modify: `frontend/src/router.tsx`
- Delete: `frontend/src/routes/placeholder.tsx`
- Test: `frontend/src/tests/backups.test.tsx`

**Interfaces:**

- Consumes (Task 8): `GET /api/v1/backups` → `{backups: [{id, host_id, host_name, storage, volid, guest_type, guest_vmid, guest_name, taken_at, size_bytes, verify_state, notes}], stats: {total, total_bytes, ok_count, failed_count, success_rate_30d: number|null, datastores: [{storage, count, size_bytes}]}, synced_at, stale}`.
- Consumes (Task 9): `POST /api/v1/backups/run` `{guests: "all", host_id?}` → `202 {job}`; `POST /api/v1/backups/{id}/restore` `{mode: "new"|"in_place", confirm?}` → `202 {job}` or `409 {"detail": {...}}` with `error` of `confirm_required` / `self_target` / `guest_running` / `guest_missing`; `DELETE /api/v1/backups/{id}` → `202 {job}`; `GET /api/v1/backups/prune-preview?host_id=&storage=&keep_last=&keep_daily=` → `[{volid, type, vmid, ctime, mark: "keep"|"remove"|"protected"}]`.
- Consumes (Task 14): `errBody(e)` from `../api/network`, the same `{"detail": {...}}` unwrapper; one helper, not two.
- Consumes (existing): `useEntitlements`, `LockVeil`, `ConfirmSelfDialog` (with Task 14's `title` prop), `JobLog`, `UsageBar` + `STORAGE_GRADIENT`, `EmptyState`, `Button`, `inputCls`, `fmtBytes`/`fmtPct`, `toast`, `window.confirm` (the `routes/settings.tsx` precedent), `shellRoute` from `./shell`.
- Produces:
  - `src/api/backups.ts` → types `BackupRow`, `Datastore`, `BackupStats`, `BackupsResponse`, `PruneRow`, `PruneParams`; hooks `useBackups()`, `useRunBackup()`, `useRestoreBackup()`, `useDeleteBackup()`, `usePrunePreview(params)`
  - `src/components/RestoreDialog.tsx` → `RestoreDialog({ backup: BackupRow; onClose: () => void })`
  - `src/routes/backups.tsx` → `BackupsPage()` and `backupsRoute`
  - `src/routes/placeholder.tsx` deleted; `router.tsx`'s `page()` helper deleted

**Three things worth stating before the steps:**

1. **The `self_target` 409 is a refusal, not a confirmation.** Every other `self_target` in the product (`LifecycleActions`' stop) re-POSTs with the typed phrase and succeeds. `api/backups.py::restore_backup_route` raises it *unconditionally* for an in-place restore over Proxploy's own CT, `confirm` cannot bypass it, and re-POSTing gets the identical 409. So this page renders the backend's `detail` sentence and stops. `confirm_required` (an in-place restore over any *other* guest) is the one that opens `ConfirmSelfDialog`.
2. **The doc-06 "Node" column shows the host.** `api/backups.py::_backup_out` returns `host_name`; the `backups` table carries no node column and Task 8's sync is single-node-per-host by design. The column is labelled **Host** rather than mislabelling a host as a node.
3. **The retention section is preview-only.** `POST /backups/prune` exists and is not wired. A one-shot "prune now" button is a worse product than the retention *policy* the Phase 7 scheduler owns, and shipping a destructive button whose rules cannot be saved is the wrong half to build first. Recorded as a `ponytail:` comment naming the upgrade path.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/tests/backups.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const BACKUPS = {
  backups: [
    { id: 11, host_id: 1, host_name: 'host-01', storage: 'pbs-ds',
      volid: 'pbs-ds:backup/ct/150/2026-07-30T02:00:00Z', guest_type: 'ct',
      guest_vmid: 150, guest_name: 'Immich', taken_at: '2026-07-30T02:00:00Z',
      size_bytes: 1073741824, verify_state: 'ok', notes: 'nightly' },
    { id: 12, host_id: 1, host_name: 'host-01', storage: 'pbs-ds',
      volid: 'pbs-ds:backup/vm/201/2026-07-30T03:00:00Z', guest_type: 'vm',
      guest_vmid: 201, guest_name: 'win11', taken_at: '2026-07-30T03:00:00Z',
      size_bytes: 5368709120, verify_state: 'failed', notes: null },
  ],
  stats: {
    total: 2, total_bytes: 6442450944, ok_count: 1, failed_count: 1,
    success_rate_30d: 50.0,
    datastores: [{ storage: 'pbs-ds', count: 2, size_bytes: 6442450944 }],
  },
  synced_at: '2026-07-31T09:00:00Z',
  stale: false,
}

const PRUNE = [
  { volid: 'pbs-ds:backup/ct/150/2026-07-30T02:00:00Z', type: 'ct', vmid: 150,
    ctime: 1753840800, mark: 'keep' },
  { volid: 'pbs-ds:backup/ct/150/2026-06-01T02:00:00Z', type: 'ct', vmid: 150,
    ctime: 1748743200, mark: 'remove' },
  { volid: 'pbs-ds:backup/vm/201/2026-05-01T02:00:00Z', type: 'vm', vmid: 201,
    ctime: 1746064800, mark: 'protected' },
]

const calls: { path: string; method: string; body: any }[] = []
let features: Record<string, boolean> = {
  'backups.pbs': true, 'backups.run': true, 'backups.restore': true,
  'backups.retention': true,
}
/** which 409 the next in-place restore should hit, if any */
let restoreGuard: 'confirm' | 'self' | null = null

vi.mock('../api/client', () => {
  class ApiError extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) {
      super(`API ${status}`); this.status = status; this.body = body
    }
  }
  return {
    ApiError,
    api: vi.fn((path: string, opts?: RequestInit) => {
      const method = (opts?.method ?? 'GET').toUpperCase()
      const body = opts?.body ? JSON.parse(String(opts.body)) : {}
      if (path === '/entitlements') {
        return Promise.resolve({ tier: 'builtin', features, grace: null })
      }
      if (method !== 'GET') calls.push({ path, method, body })
      if (path === '/backups') return Promise.resolve(BACKUPS)
      if (path === '/hosts') return Promise.resolve([{ id: 1, name: 'host-01' }])
      if (path.startsWith('/backups/prune-preview')) return Promise.resolve(PRUNE)
      if (path === '/backups/run') {
        return Promise.resolve({ job: { id: 31, kind: 'backup.run', status: 'queued' } })
      }
      if (path.endsWith('/restore')) {
        if (body.mode === 'in_place' && restoreGuard === 'self') {
          // Unconditional refusal, `confirm` does not bypass it.
          return Promise.reject(new ApiError(409, { detail: {
            error: 'self_target', confirm_phrase: 'Immich',
            detail: 'Immich is the container Proxploy itself runs in. An in-place ' +
                    'restore would overwrite Proxploy mid-restore. Restore as new instead.',
          } }))
        }
        if (body.mode === 'in_place' && restoreGuard === 'confirm' && !body.confirm) {
          return Promise.reject(new ApiError(409, { detail: {
            error: 'confirm_required', confirm_phrase: 'win11',
            detail: 'An in-place restore overwrites win11 with the contents of this backup.',
          } }))
        }
        return Promise.resolve({ job: { id: 32, kind: 'backup.restore', status: 'queued' } })
      }
      if (method === 'DELETE') {
        return Promise.resolve({ job: { id: 33, kind: 'backup.delete', status: 'queued' } })
      }
      return Promise.resolve(null)
    }),
  }
})

vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ children }: { children?: unknown }) => <a>{children as never}</a>,
  useNavigate: () => () => {},
  useSearch: () => ({}),
}))

import { BackupsPage } from '../routes/backups'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}><BackupsPage /></QueryClientProvider>)
}

describe('BackupsPage', () => {
  it('renders the datastore header, the three stat cards and the recent-backups table', async () => {
    calls.length = 0; restoreGuard = null
    wrap()
    expect(await screen.findByText(/Proxmox Backup Server · pbs-ds/)).toBeInTheDocument()
    expect(screen.getByText('Next scheduled')).toBeInTheDocument()
    expect(screen.getByText('Datastore used')).toBeInTheDocument()
    expect(screen.getByText('Success rate · 30d')).toBeInTheDocument()
    expect(screen.getByText('50%')).toBeInTheDocument()
    expect(screen.getByText('Immich')).toBeInTheDocument()
    expect(screen.getByText('win11')).toBeInTheDocument()
    expect(screen.getByText('5.0 GiB')).toBeInTheDocument()
  })

  it('renders "New job" as a disabled control that says why', async () => {
    calls.length = 0
    wrap()
    const btn = await screen.findByRole('button', { name: 'New job' })
    expect(btn).toBeDisabled()
    expect(btn.getAttribute('title')).toMatch(/Phase 7/i)
  })

  it('runs a backup and swaps the dialog body for the job log', async () => {
    calls.length = 0
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Run now' }))
    // the single registered host is auto-selected once /hosts resolves; the
    // button is disabled until then, and a click on a disabled button is a no-op
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Start backup' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Start backup' }))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0].path).toBe('/backups/run')
    expect(calls[0].body).toEqual({ guests: 'all', host_id: 1 })
    expect(await screen.findByRole('button', { name: 'Close' })).toBeInTheDocument()
  })

  it('asks for confirmation before deleting an archive, then fires the job', async () => {
    calls.length = 0
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    wrap()
    await screen.findByText('Immich')
    fireEvent.click(screen.getAllByRole('button', { name: 'Delete' })[0])
    expect(confirmSpy).toHaveBeenCalled()
    expect(calls.length).toBe(0)          // declining deletes nothing
    confirmSpy.mockReturnValue(true)
    fireEvent.click(screen.getAllByRole('button', { name: 'Delete' })[0])
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0].method).toBe('DELETE')
    expect(calls[0].path).toBe('/backups/11')
    confirmSpy.mockRestore()
  })

  it('takes a typed confirmation for an in-place restore over another guest', async () => {
    calls.length = 0; restoreGuard = 'confirm'
    wrap()
    await screen.findByText('win11')
    fireEvent.click(screen.getAllByRole('button', { name: 'Restore' })[1])
    fireEvent.click(await screen.findByLabelText(/In place/i))
    fireEvent.click(screen.getByRole('button', { name: 'Start restore' }))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0].body).toEqual({ mode: 'in_place' })

    expect(await screen.findByText(/An in-place restore overwrites win11/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText(/type/i), { target: { value: 'win11' } })
    fireEvent.click(screen.getByRole('button', { name: /^Confirm$/ }))
    await waitFor(() => expect(calls.length).toBe(2))
    expect(calls[1].body).toEqual({ mode: 'in_place', confirm: 'win11' })
    restoreGuard = null
  })

  it('refuses an in-place restore over Proxploy itself instead of offering a confirm box', async () => {
    calls.length = 0; restoreGuard = 'self'
    wrap()
    await screen.findByText('Immich')
    fireEvent.click(screen.getAllByRole('button', { name: 'Restore' })[0])
    fireEvent.click(await screen.findByLabelText(/In place/i))
    fireEvent.click(screen.getByRole('button', { name: 'Start restore' }))
    await waitFor(() => expect(calls.length).toBe(1))
    // the backend's own sentence, and NO typed-confirmation control: re-POSTing
    // with the phrase gets the same 409, so offering one would be a lie
    expect(await screen.findByText(/Restore as new instead/)).toBeInTheDocument()
    expect(screen.queryByLabelText(/type/i)).toBeNull()
    expect(screen.queryByRole('button', { name: /^Confirm$/ })).toBeNull()
    expect(calls.length).toBe(1)
    restoreGuard = null
  })

  it('veils the retention preview without backups.retention, and marks volumes when entitled', async () => {
    calls.length = 0
    features = { 'backups.pbs': true, 'backups.run': true, 'backups.restore': true }
    const veiled = wrap()
    expect(await screen.findByText(/Retention preview is a Pro feature/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Unlock Pro/i })).toBeInTheDocument()
    veiled.unmount()

    features = { 'backups.pbs': true, 'backups.run': true, 'backups.restore': true,
                 'backups.retention': true }
    wrap()
    // enabled only once /backups resolves, the datastore and its host come from it
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Preview retention' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Preview retention' }))
    expect(await screen.findByText('remove')).toBeInTheDocument()
    expect(screen.getByText('protected')).toBeInTheDocument()
    expect(screen.getAllByText('keep').length).toBeGreaterThan(0)
    expect(screen.getByText(/deletes nothing/i)).toBeInTheDocument()
  })

  it('offers PBS datastore connect, reusing StorageForm pre-set to type pbs', async () => {
    // doc 10 lists "PBS datastore connect" as a Phase 6 Backups deliverable.
    // Connecting PBS *is* attaching a storage of type pbs, so this asserts the
    // affordance exists and opens Task 13's form in the right mode, not that
    // a second, parallel PBS form was built.
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Connect PBS' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByLabelText(/Type/i)).toHaveValue('pbs')
  })
})
```

- [ ] **Step 2: Run to verify the failure**

Run: `cd frontend && npx vitest run src/tests/backups.test.tsx`
Expected: FAIL, `Failed to resolve import "../routes/backups" from "src/tests/backups.test.tsx"`; all 8 tests fail at collection.

- [ ] **Step 3: Write `src/api/backups.ts`**

```ts
// api/backups.ts, Backups page server state (doc 05 §Backups, doc 06 §a row 45).
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from './client'
import type { JobRow } from './jobs'

export type BackupRow = {
  id: number
  host_id: number
  host_name: string | null
  storage: string | null
  volid: string
  guest_type: string | null
  guest_vmid: number | null
  guest_name: string | null
  taken_at: string | null
  size_bytes: number | null
  verify_state: string | null
  notes: string | null
}

export type Datastore = { storage: string; count: number; size_bytes: number }

export type BackupStats = {
  total: number
  total_bytes: number
  ok_count: number
  failed_count: number
  /** null when nothing in the window was verified, never a fake 100%. */
  success_rate_30d: number | null
  datastores: Datastore[]
}

export type BackupsResponse = {
  backups: BackupRow[]
  stats: BackupStats
  synced_at: string | null
  stale: boolean
}

export type PruneRow = {
  volid: string
  type: string | null
  vmid: number | null
  ctime: number | null
  mark: 'keep' | 'remove' | 'protected'
}

/**
 * The list is served from the `backups` cache table; GET /backups enqueues its
 * own `backup.sync` when that cache is stale, so this hook never has to.
 */
export function useBackups() {
  return useQuery({
    queryKey: ['backups'],
    queryFn: () => api<BackupsResponse>('/backups'),
    refetchInterval: 30_000,
  })
}

// Every mutation below fires a job. Per api/jobs.ts::useLifecycle's documented
// rule they invalidate ['jobs'] and ['cluster','activity'] only, never
// ['backups'] on success. The handler's own `_resync` + the `resource`
// {type:'backup'} SSE delta are what refresh the list, once the archive
// actually exists upstream rather than while the job is still queued.
const jobSettled = (qc: ReturnType<typeof useQueryClient>) => () => {
  qc.invalidateQueries({ queryKey: ['jobs'] })
  qc.invalidateQueries({ queryKey: ['cluster', 'activity'] })
}

export function useRunBackup() {
  const qc = useQueryClient()
  return useMutation<{ job: JobRow }, ApiError, { hostId: number | null }>({
    mutationFn: (v) =>
      api<{ job: JobRow }>('/backups/run', {
        method: 'POST',
        body: JSON.stringify({ guests: 'all', ...(v.hostId ? { host_id: v.hostId } : {}) }),
      }),
    onSettled: jobSettled(qc),
  })
}

export type RestoreVars = { id: number; mode: 'new' | 'in_place'; confirm?: string }

export function useRestoreBackup() {
  const qc = useQueryClient()
  return useMutation<{ job: JobRow }, ApiError, RestoreVars>({
    mutationFn: (v) =>
      api<{ job: JobRow }>(`/backups/${v.id}/restore`, {
        method: 'POST',
        body: JSON.stringify(v.confirm ? { mode: v.mode, confirm: v.confirm } : { mode: v.mode }),
      }),
    onSettled: jobSettled(qc),
  })
}

export function useDeleteBackup() {
  const qc = useQueryClient()
  return useMutation<{ job: JobRow }, ApiError, number>({
    mutationFn: (id) => api<{ job: JobRow }>(`/backups/${id}`, { method: 'DELETE' }),
    onSettled: jobSettled(qc),
  })
}

export type PruneParams = {
  hostId: number
  storage: string
  keepLast: number
  keepDaily: number
}

/** Dry run. GET only, the destructive verb lives on POST /backups/prune. */
export function usePrunePreview(p: PruneParams | null) {
  return useQuery({
    queryKey: ['backups', 'prune-preview', p],
    enabled: p != null,
    retry: false,
    staleTime: 0,
    queryFn: () =>
      api<PruneRow[]>(`/backups/prune-preview?host_id=${p!.hostId}` +
        `&storage=${encodeURIComponent(p!.storage)}` +
        `&keep_last=${p!.keepLast}&keep_daily=${p!.keepDaily}`),
  })
}
```

- [ ] **Step 4: Write `src/components/RestoreDialog.tsx`**

```tsx
import { useState } from 'react'
import type { BackupRow } from '../api/backups'
import { useRestoreBackup } from '../api/backups'
// One 409 unwrapper for the whole phase; it landed with the network page.
import { errBody } from '../api/network'
import { ConfirmSelfDialog } from './ConfirmSelfDialog'
import { JobLog } from './JobLog'
import { Button } from './ui/button'
import { fmtBytes } from '../lib/format'

/**
 * Restore one archive, in place or as a new guest (doc 01 §7).
 *
 * Three 409 shapes reach this dialog and they are NOT interchangeable:
 *  - `confirm_required`: an in-place restore over another guest. Confirmable:
 *    re-POST with the typed name.
 *  - `self_target`: an in-place restore over the CT Proxploy itself runs in.
 *    Refused unconditionally by api/backups.py; `confirm` does not bypass it and
 *    re-POSTing returns the identical 409. Show the reason, offer nothing.
 *  - `guest_running` / `guest_missing`, same treatment: state the reason.
 */
export function RestoreDialog({ backup, onClose }: {
  backup: BackupRow; onClose: () => void
}) {
  const restore = useRestoreBackup()
  const [mode, setMode] = useState<'new' | 'in_place'>('new')
  const [guard, setGuard] = useState<{ phrase: string; detail: string } | null>(null)
  const [refusal, setRefusal] = useState('')
  const [jobId, setJobId] = useState<number | null>(null)
  const name = backup.guest_name ?? `${backup.guest_type ?? 'guest'} ${backup.guest_vmid ?? ''}`

  const fire = (confirm?: string) => {
    setRefusal('')
    restore.mutate({ id: backup.id, mode, confirm }, {
      onSuccess: (r) => { setGuard(null); setJobId(r.job.id) },
      onError: (e) => {
        const b = errBody(e)
        if (b?.error === 'confirm_required') {
          setGuard({ phrase: String(b.confirm_phrase ?? name), detail: String(b.detail ?? '') })
          return
        }
        setGuard(null)
        setRefusal(String(b?.detail ?? 'Could not start the restore, try again.'))
      },
    })
  }

  return (
    <>
      <div role="dialog" aria-label="Restore backup"
           className="fixed inset-0 z-30 grid place-items-center bg-[rgba(11,15,22,.72)] backdrop-blur-[3px]">
        <div className="w-[480px] max-w-[92vw] rounded-card border border-line bg-panel p-5">
          <h2 className="font-display text-[16px] font-semibold">Restore {name}</h2>
          <div className="mt-2 rounded-ctl border border-line-soft bg-elev p-2 font-mono text-[11px] text-text-3">
            <div className="break-all">{backup.volid}</div>
            <div className="mt-1">
              {fmtBytes(backup.size_bytes)} · {backup.verify_state ?? 'unverified'}
            </div>
          </div>

          {jobId != null ? (
            <div className="mt-4">
              <JobLog jobId={jobId} />
              <Button className="mt-3" variant="ghost" onClick={onClose}>Close</Button>
            </div>
          ) : (
            <>
              <div className="mt-4 space-y-3">
                <label className="flex gap-2 text-[13px] text-text-2">
                  <input type="radio" name="restore-mode" checked={mode === 'new'}
                         onChange={() => setMode('new')} />
                  <span>
                    <span className="text-text">As a new guest</span>
                    <span className="block text-[12px] text-text-3">
                      Proxmox takes the next free CTID/VMID. Nothing existing is touched.
                    </span>
                  </span>
                </label>
                <label className="flex gap-2 text-[13px] text-text-2">
                  <input type="radio" name="restore-mode" checked={mode === 'in_place'}
                         onChange={() => setMode('in_place')} />
                  <span>
                    <span className="text-text">In place</span>
                    <span className="block text-[12px] text-text-3">
                      Overwrites {name} ({backup.guest_vmid}) with this archive. The guest must
                      be stopped, and its current disk is replaced.
                    </span>
                  </span>
                </label>
              </div>

              {refusal && (
                <p className="mt-3 rounded-ctl border border-red/30 bg-red-dim p-2 text-[12.5px] text-text-2">
                  {refusal}
                </p>
              )}

              <div className="mt-4 flex justify-end gap-2">
                <Button variant="ghost" onClick={onClose}>Cancel</Button>
                <Button variant={mode === 'in_place' ? 'danger' : 'primary'}
                        disabled={restore.isPending} onClick={() => fire()}>
                  {restore.isPending ? 'Starting…' : 'Start restore'}
                </Button>
              </div>
            </>
          )}
        </div>
      </div>

      {guard && (
        <ConfirmSelfDialog
          title={`Overwrite ${guard.phrase}`}
          phrase={guard.phrase}
          detail={guard.detail}
          onConfirm={(typed) => fire(typed)}
          onCancel={() => setGuard(null)} />
      )}
    </>
  )
}
```

Note the radio labels: `In place` is what the test's `findByLabelText(/In place/i)` matches, and the `<input>` sits inside its `<label>`, so no `htmlFor` is needed.

- [ ] **Step 5: Write `src/routes/backups.tsx`**

```tsx
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { createRoute } from '@tanstack/react-router'
import { toast } from 'sonner'
import { shellRoute } from './shell'
import { api } from '../api/client'
import { useEntitlements } from '../api/hooks'
import { useBackups, useDeleteBackup, usePrunePreview, useRunBackup } from '../api/backups'
import type { BackupRow, BackupsResponse, PruneParams } from '../api/backups'
import { EmptyState } from '../components/EmptyState'
import { JobLog } from '../components/JobLog'
import { LockVeil } from '../components/LockVeil'
import { RestoreDialog } from '../components/RestoreDialog'
import { StorageForm } from '../components/StorageForm'
import { UsageBar, STORAGE_GRADIENT } from '../components/UsageBar'
import { Button } from '../components/ui/button'
import { inputCls } from '../components/LoginForm'
import { fmtBytes, fmtPct } from '../lib/format'

const card = 'rounded-card border border-line-soft bg-panel p-5'
const th = 'pb-2 font-medium'

function fmtWhen(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : ', '
}

function StatCard({ label, value, note }: { label: string; value: string; note: React.ReactNode }) {
  return (
    <div className={card}>
      <div className="text-[11px] uppercase tracking-wide text-text-3">{label}</div>
      <div className="mt-1 font-mono text-[20px] text-text">{value}</div>
      <div className="mt-2 text-[12px] text-text-3">{note}</div>
    </div>
  )
}

/** Run now → one vzdump job over every guest on the chosen host, then the log. */
function RunDialog({ onClose }: { onClose: () => void }) {
  const { data: hosts } = useQuery({
    queryKey: ['hosts'], queryFn: () => api<{ id: number; name: string }[]>('/hosts'),
  })
  const run = useRunBackup()
  const [picked, setPicked] = useState<number | null>(null)
  const [jobId, setJobId] = useState<number | null>(null)
  // One vzdump task runs on one node, so the backend requires host_id whenever
  // more than one host is registered; with exactly one there is nothing to ask.
  const hostId = picked ?? (hosts?.length === 1 ? hosts[0].id : null)

  return (
    <div role="dialog" aria-label="Run backup"
         className="fixed inset-0 z-30 grid place-items-center bg-[rgba(11,15,22,.72)] backdrop-blur-[3px]">
      <div className="w-[480px] max-w-[92vw] rounded-card border border-line bg-panel p-5">
        <h2 className="font-display text-[16px] font-semibold">Run a backup now</h2>
        {jobId != null ? (
          <div className="mt-4">
            <JobLog jobId={jobId} />
            <Button className="mt-3" variant="ghost" onClick={onClose}>Close</Button>
          </div>
        ) : (
          <>
            <p className="mt-2 text-[12.5px] text-text-3">
              Backs up every guest on the selected host in snapshot mode, to that host&apos;s
              default backup datastore.
            </p>
            <select className={`${inputCls} mt-4`} value={hostId ?? ''}
                    aria-label="Host"
                    onChange={(e) => setPicked(Number(e.target.value) || null)}>
              <option value="">Select a host…</option>
              {(hosts ?? []).map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
            </select>
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="ghost" onClick={onClose}>Cancel</Button>
              <Button disabled={hostId == null || run.isPending}
                      onClick={() => run.mutate({ hostId }, {
                        onSuccess: (r) => setJobId(r.job.id),
                        onError: () => toast.error('Could not start the backup, try again.'),
                      })}>
                {run.isPending ? 'Starting…' : 'Start backup'}
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

const MARK_CLS: Record<string, string> = {
  keep: 'border-green/30 bg-green-dim text-green',
  remove: 'border-red/30 bg-red-dim text-red',
  protected: 'border-blue/30 bg-blue-dim text-blue',
}

/**
 * Retention preview (Pro). A dry run and nothing else.
 *
 * ponytail: POST /backups/prune is deliberately not wired. A one-shot "prune
 * now" button whose keep-* rules cannot be saved anywhere is the wrong half of
 * retention to ship first; the rules belong to the Phase 7 scheduler, and this
 * view is what proves the spec does what the operator meant before that lands.
 */
function RetentionSection({ data }: { data: BackupsResponse | undefined }) {
  const ent = useEntitlements()
  const locked = ent.data != null && !ent.has('backups.retention')
  const stores = data?.stats.datastores ?? []
  const [storage, setStorage] = useState('')
  const [keepLast, setKeepLast] = useState('3')
  const [keepDaily, setKeepDaily] = useState('7')
  const [params, setParams] = useState<PruneParams | null>(null)
  const preview = usePrunePreview(params)

  const chosen = storage || stores[0]?.storage || ''
  const hostId = data?.backups.find((b) => b.storage === chosen)?.host_id ?? null
  const rows = preview.data ?? []
  const count = (m: string) => rows.filter((r) => r.mark === m).length

  return (
    <div className="mt-4">
      <LockVeil locked={locked}
        title="Retention preview is a Pro feature"
        subtitle="See exactly which archives a keep-rule would drop, before anything is deleted.">
        <section className={card}>
          <h2 className="font-display text-[16px] font-semibold">Retention preview</h2>
          <p className="mt-1 rounded-ctl border border-amber/30 bg-amber-dim p-2 text-[12.5px] text-text-2">
            <span className="text-amber">Dry run.</span> This preview only asks Proxmox what a
            retention rule <em>would</em> do, it deletes nothing, and there is no button here
            that does.
          </p>

          <div className="mt-4 flex flex-wrap items-end gap-3">
            <div>
              <label className="mb-1 block text-[11px] uppercase tracking-wide text-text-3"
                     htmlFor="rt-store">Datastore</label>
              <select id="rt-store" className={inputCls} value={chosen}
                      onChange={(e) => setStorage(e.target.value)}>
                {stores.map((s) => <option key={s.storage} value={s.storage}>{s.storage}</option>)}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-[11px] uppercase tracking-wide text-text-3"
                     htmlFor="rt-last">Keep last</label>
              <input id="rt-last" type="number" min={0} className={inputCls}
                     value={keepLast} onChange={(e) => setKeepLast(e.target.value)} />
            </div>
            <div>
              <label className="mb-1 block text-[11px] uppercase tracking-wide text-text-3"
                     htmlFor="rt-daily">Keep daily</label>
              <input id="rt-daily" type="number" min={0} className={inputCls}
                     value={keepDaily} onChange={(e) => setKeepDaily(e.target.value)} />
            </div>
            <Button variant="ghost"
                    disabled={hostId == null || !chosen}
                    onClick={() => setParams({
                      hostId: hostId as number, storage: chosen,
                      keepLast: Number(keepLast) || 0, keepDaily: Number(keepDaily) || 0,
                    })}>
              Preview retention
            </Button>
          </div>

          {preview.isError && (
            <p className="mt-3 text-[12.5px] text-red">
              Proxmox refused that rule, at least one keep value must be above zero.
            </p>
          )}

          {rows.length > 0 && (
            <>
              <div className="mt-4 font-mono text-[12px] text-text-3">
                {count('keep')} keep · {count('remove')} remove · {count('protected')} protected
              </div>
              <table className="mt-2 w-full text-left text-[13px]">
                <thead>
                  <tr className="text-[11px] uppercase text-text-3">
                    <th scope="col" className={th}>Volume</th>
                    <th scope="col" className={th}>Guest</th>
                    <th scope="col" className={th}>Created</th>
                    <th scope="col" className={th}>Mark</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.volid} className="border-t border-line-soft hover:bg-panel-2">
                      <td className="py-2.5 font-mono text-[11.5px] text-text-2 break-all">{r.volid}</td>
                      <td className="py-2.5 font-mono text-text-2">
                        {r.type ?? ', '} {r.vmid ?? ''}
                      </td>
                      <td className="py-2.5 text-text-2">
                        {r.ctime ? new Date(r.ctime * 1000).toLocaleDateString() : ', '}
                      </td>
                      <td className="py-2.5">
                        <span className={`rounded-full border px-2 py-0.5 text-[11px] ${MARK_CLS[r.mark] ?? ''}`}>
                          {r.mark}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </section>
      </LockVeil>
    </div>
  )
}

export function BackupsPage() {
  const ent = useEntitlements()
  const { data, isError } = useBackups()
  const [running, setRunning] = useState(false)
  const [restoring, setRestoring] = useState<BackupRow | null>(null)
  const [connecting, setConnecting] = useState(false)
  const del = useDeleteBackup()

  const stats = data?.stats
  const stores = stats?.datastores ?? []
  const biggest = stores[0]
  const runDenied = ent.data != null && !ent.has('backups.run')
  const restoreDenied = ent.data != null && !ent.has('backups.restore')

  const drop = (b: BackupRow) => {
    if (!window.confirm(
      `Delete ${b.volid}? The archive is removed from ${b.storage} and cannot be recovered.`)) return
    del.mutate(b.id, {
      onError: () => toast.error('Could not delete that archive, try again.'),
    })
  }

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-[22px] font-semibold">Backups</h1>
          <div className="text-[12px] text-text-3">
            {data
              ? (biggest
                  ? `Proxmox Backup Server · ${biggest.storage}`
                  : 'No backup datastore found yet')
              : '…'}
            {data?.stale && <span className="ml-2 text-amber">· refreshing from Proxmox…</span>}
          </div>
        </div>
        <div className="flex gap-2">
          {/* doc 10's "PBS datastore connect". Connecting PBS is exactly
              attaching a storage of type `pbs`, so this opens Task 13's
              StorageForm pre-set rather than duplicating it. Shown always,
              not only when empty, a second datastore is a normal thing to
              add. Server enforces `storage.manage`; the form carries its own
              LockVeil, so no gate is needed on the trigger. */}
          <Button variant="ghost" onClick={() => setConnecting(true)}>
            Connect PBS
          </Button>
          <Button variant="ghost" disabled
                  title="Scheduled backup jobs arrive with the Phase 7 scheduler.">
            New job
          </Button>
          <Button disabled={runDenied}
                  title={runDenied ? 'Not included in your plan' : undefined}
                  onClick={() => setRunning(true)}>
            Run now
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <StatCard label="Next scheduled" value=", "
          note="Scheduled backups arrive with the Phase 7 scheduler; every run today is one you started." />
        <StatCard label="Datastore used" value={fmtBytes(stats?.total_bytes)}
          note={
            <>
              <UsageBar gradient={STORAGE_GRADIENT}
                pct={stats?.total_bytes && biggest ? (biggest.size_bytes / stats.total_bytes) * 100 : 0} />
              <span className="mt-2 block">
                {biggest ? `${biggest.storage} holds ${fmtBytes(biggest.size_bytes)} of it` : 'No archives yet'}
                {' '}· datastore capacity lives on the Storage page.
              </span>
            </>
          } />
        <StatCard label="Success rate · 30d"
          value={stats?.success_rate_30d == null ? ', ' : fmtPct(stats.success_rate_30d)}
          note={stats?.success_rate_30d == null
            ? 'Nothing verified in the last 30 days, unverified archives are left out rather than counted as passes.'
            : `${stats.ok_count} verified · ${stats.failed_count} failed`} />
      </div>

      <div className={`${card} mt-4`}>
        <h2 className="mb-3 font-display text-[16px] font-semibold">Recent backups</h2>
        {isError ? (
          <EmptyState title="Backups not readable"
            note="Proxploy mirrors archives from each host's backup datastores, check that the host is connected." />
        ) : (data?.backups.length ?? 0) === 0 ? (
          <EmptyState title="No backups yet"
            note="Archives Proxmox already holds appear here after the first sync." />
        ) : (
          <table className="w-full text-left text-[13px]">
            <thead>
              <tr className="text-[11px] uppercase text-text-3">
                <th scope="col" className={th}>Guest</th>
                {/* GET /backups returns host_name; the `backups` table has no node
                    column, so this is labelled honestly (doc 06 says "Node"). */}
                <th scope="col" className={th}>Host</th>
                <th scope="col" className={th}>When</th>
                <th scope="col" className={th}>Size</th>
                <th scope="col" className={th}>Status</th>
                <th scope="col" className={th}></th>
              </tr>
            </thead>
            <tbody>
              {(data?.backups ?? []).map((b) => (
                <tr key={b.id} className="border-t border-line-soft hover:bg-panel-2">
                  <td className="py-2.5 font-mono">
                    {b.guest_name ?? ', '}
                    <span className="ml-2 text-[11px] text-text-3">
                      {b.guest_type?.toUpperCase()} {b.guest_vmid}
                    </span>
                  </td>
                  <td className="py-2.5 text-text-2">{b.host_name ?? ', '}</td>
                  <td className="py-2.5 text-text-2">{fmtWhen(b.taken_at)}</td>
                  <td className="py-2.5 font-mono text-text-2">{fmtBytes(b.size_bytes)}</td>
                  <td className={`py-2.5 text-[12px] ${
                    b.verify_state === 'ok' ? 'text-green'
                      : b.verify_state === 'failed' ? 'text-red' : 'text-text-3'}`}>
                    {b.verify_state === 'ok' ? 'verified'
                      : b.verify_state === 'failed' ? 'failed' : 'unverified'}
                  </td>
                  <td className="py-2.5 text-right">
                    <Button variant="ghost" className="px-2 py-1 text-[11px]"
                            disabled={restoreDenied}
                            title={restoreDenied ? 'Not included in your plan' : undefined}
                            onClick={() => setRestoring(b)}>
                      Restore
                    </Button>
                    <Button variant="danger" className="ml-2 px-2 py-1 text-[11px]"
                            onClick={() => drop(b)}>
                      Delete
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <RetentionSection data={data} />

      {running && <RunDialog onClose={() => setRunning(false)} />}
      {restoring && <RestoreDialog backup={restoring} onClose={() => setRestoring(null)} />}
      {connecting && (
        <StorageForm existing={null} defaultType="pbs" onClose={() => setConnecting(false)} />
      )}
    </div>
  )
}

// shellRoute from ./shell, never ../router (cluster.tsx:273-277).
export const backupsRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/backups',
  component: BackupsPage,
})
```

- [ ] **Step 6: Run the backups tests**

Run: `cd frontend && npx vitest run src/tests/backups.test.tsx`
Expected: PASS, 8 passed.

- [ ] **Step 7: Point `router.tsx` at the real backups route and delete the `page()` helper**

All three placeholder pages are now real, so `page()` and its `PlaceholderPage`
import are dead. Replace the whole of `frontend/src/router.tsx` with:

```tsx
import { createRoute, createRouter, redirect } from '@tanstack/react-router'
import { rootRoute, shellRoute } from './routes/shell'

export { rootRoute, shellRoute }

export const indexRoute = createRoute({
  getParentRoute: () => rootRoute, path: '/',
  // cast: indexRoute's own `to` type can't see the tree it's still being built into
  beforeLoad: () => { throw redirect({ to: '/cluster' as never }) },
})

import { loginRoute } from './routes/login'
import { onboardingRoute } from './routes/onboarding'
import { settingsRoute } from './routes/settings'
import { clusterRoute, nodeDetailRoute } from './routes/cluster'
import { appsRoute, appDetailRoute, appOverviewRoute, appLogsRoute, appConsoleRoute, appConfigRoute } from './routes/apps'
import { vmsRoute, vmDetailRoute, vmOverviewRoute, vmConsoleRoute, vmSnapshotsRoute } from './routes/vms'
import { storeRoute } from './routes/store'
import { storageRoute } from './routes/storage'
import { networkRoute } from './routes/network'
import { backupsRoute } from './routes/backups'

const appDetailTree = appDetailRoute.addChildren([appOverviewRoute, appLogsRoute, appConsoleRoute, appConfigRoute])
const vmDetailTree = vmDetailRoute.addChildren([vmOverviewRoute, vmConsoleRoute, vmSnapshotsRoute])

export const routeTree = rootRoute.addChildren([
  indexRoute, loginRoute, onboardingRoute,
  shellRoute.addChildren([clusterRoute, nodeDetailRoute, appsRoute, appDetailTree, storeRoute, vmsRoute, vmDetailTree,
                          storageRoute, networkRoute, backupsRoute, settingsRoute]),
])
export const router = createRouter({ routeTree })

declare module '@tanstack/react-router' {
  interface Register { router: typeof router }
}
```

- [ ] **Step 8: Delete `src/routes/placeholder.tsx`**

```bash
cd frontend && rm src/routes/placeholder.tsx && grep -rn "placeholder\|PlaceholderPage" src/ || echo "no references left"
```

Expected: `no references left`. A hit here means a route file still imports it and Step 7's rewrite missed something.

- [ ] **Step 9: Run the full frontend suite, build and lint**

Run: `cd frontend && npx vitest run && npm run build && npm run lint`
Expected: Task 14's total **+ 8 passed** across **+1 file**; `tsc -b && vite build` clean; oxlint clean. A `TS2307: Cannot find module './routes/placeholder'` means Step 7's rewrite was applied after the delete in a stale editor buffer, re-apply Step 7.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/api/backups.ts frontend/src/components/RestoreDialog.tsx \
        frontend/src/routes/backups.tsx frontend/src/router.tsx \
        frontend/src/tests/backups.test.tsx
git rm frontend/src/routes/placeholder.tsx
git commit -m "feat(backups): PBS page with run, restore, delete and retention preview; drop the last placeholder"
```

---

## Task 16: Frontend: VM snapshots tab (list / take / roll back / delete)

**Files:**
- Create: `frontend/src/api/snapshots.ts`
- Create: `frontend/src/components/SnapshotPanel.tsx`
- Modify: `frontend/src/routes/vms.tsx`
- Test: `frontend/src/tests/snapshots.test.tsx`

**Interfaces:**
- Consumes (Task 10): `GET /api/v1/vms/{id}/snapshots -> [{name, description, snaptime, vmstate, parent}]` (PVE's own shape, including the synthetic `current` row), `POST /api/v1/vms/{id}/snapshots` body `{name, description, vmstate}` → `202 {"job": {...}}`, `POST /api/v1/vms/{id}/snapshots/{name}/rollback` body `{}` or `{"confirm": "<vm name>"}` → `202 {"job": {...}}` / `409 {"error": "confirm_required"|"self_target", "confirm_phrase": "<vm name>", "detail": "..."}`, `DELETE /api/v1/vms/{id}/snapshots/{name}` → `202 {"job": {...}}`. Entitlement key `vms.snapshots`.
- Consumes (existing): `api/client::api`/`ApiError`, `api/jobs::JobRow`, `api/hooks::useEntitlements`/`VmRow`, `components/ConfirmSelfDialog`, `components/EmptyState`, `components/LoginForm::inputCls`, `components/ui/button::Button`, `lib/format::fmtBytes`, `sonner::toast`.
- Produces:
  - `src/api/snapshots.ts::SnapshotRow`, `SnapshotVars`, `useSnapshots(vmId: number)` (query key `['vms', vmId, 'snapshots']`), `useSnapshotAction(): UseMutationResult<{job: JobRow}, ApiError, SnapshotVars>`
  - `src/components/SnapshotPanel.tsx::SnapshotPanel({ vmId, vmName }: { vmId: number; vmName: string })`
  - `src/routes/vms.tsx::vmSnapshotsRoute` becomes a real `createRoute({ getParentRoute: () => vmDetailRoute, path: 'snapshots', component: VmSnapshots })`; the local `phaseTab` helper is **deleted**.

**Layout is doc 06 §(a) row 48, quoted, not reinvented:** *"Snapshots: table (Name/Created/Size) with Rollback + Delete row actions and 'Take snapshot'"*. The with-RAM (`vmstate`) toggle on the take form is doc 01 §4's *"with-RAM option surfaced"* line.

- [ ] **Step 1: Write the failing test file**

```tsx
// frontend/src/tests/snapshots.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const calls: { path: string; method: string; body: any }[] = []
let features: Record<string, boolean> = { 'vms.snapshots': true }
let rollbackGuard = false

const SNAPS = [
  // PVE's snapshot list always carries a synthetic `current` row for the live
  // state; it is not a snapshot and must never be offered Rollback/Delete.
  { name: 'current', description: 'You are here!', snaptime: null, vmstate: false, parent: 'pre-upgrade' },
  { name: 'pre-upgrade', description: 'before the 24.04 jump', snaptime: 1785369600,
    vmstate: true, parent: null, size_bytes: 2147483648 },
]

vi.mock('../api/client', () => {
  class ApiError extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) {
      super(`API ${status}`); this.status = status; this.body = body
    }
  }
  return {
    ApiError,
    api: vi.fn((path: string, opts?: RequestInit) => {
      if (path === '/entitlements') return Promise.resolve({ tier: 'builtin', features, grace: null })
      const method = (opts?.method ?? 'GET').toUpperCase()
      const body = opts?.body ? JSON.parse(String(opts.body)) : {}
      if (method === 'GET' && path === '/vms/9/snapshots') return Promise.resolve(SNAPS)
      calls.push({ path, method, body })
      if (rollbackGuard && path.endsWith('/rollback') && !body.confirm) {
        return Promise.reject(new ApiError(409, {
          error: 'confirm_required', confirm_phrase: 'win11',
          detail: 'Rolling back discards every change made since the snapshot.',
        }))
      }
      return Promise.resolve({ job: { id: 7, kind: 'vm.snapshot_create', status: 'queued' } })
    }),
  }
})

import { SnapshotPanel } from '../components/SnapshotPanel'

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return { qc, ...render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>) }
}

describe('SnapshotPanel', () => {
  beforeEach(() => {
    calls.length = 0
    rollbackGuard = false
    features = { 'vms.snapshots': true }
  })

  it('renders Name/Created/Size rows and hides the synthetic current row', async () => {
    wrap(<SnapshotPanel vmId={9} vmName="win11" />)
    expect(await screen.findByText('pre-upgrade')).toBeInTheDocument()
    expect(screen.queryByText('current')).toBeNull()
    expect(screen.getByText('2026-07-30 00:00')).toBeInTheDocument()
    // fmtBytes is binary-unit with one decimal: 2147483648 -> "2.0 GiB"
    expect(screen.getByText('2.0 GiB')).toBeInTheDocument()
    expect(screen.getByText('RAM')).toBeInTheDocument()
  })

  it('takes a snapshot with name, description and the with-RAM flag', async () => {
    wrap(<SnapshotPanel vmId={9} vmName="win11" />)
    fireEvent.change(await screen.findByLabelText(/snapshot name/i), { target: { value: 'clean-install' } })
    fireEvent.change(screen.getByLabelText(/description/i), { target: { value: 'fresh' } })
    fireEvent.click(screen.getByLabelText(/include ram/i))
    fireEvent.click(screen.getByRole('button', { name: /take snapshot/i }))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0]).toMatchObject({
      path: '/vms/9/snapshots', method: 'POST',
      body: { name: 'clean-install', description: 'fresh', vmstate: true },
    })
  })

  it('escalates a 409 confirm_required on rollback into the typed-confirmation dialog and retries', async () => {
    rollbackGuard = true
    wrap(<SnapshotPanel vmId={9} vmName="win11" />)
    fireEvent.click(await screen.findByRole('button', { name: /rollback/i }))
    expect(await screen.findByText(/discards every change made since the snapshot/i)).toBeInTheDocument()

    const input = screen.getByLabelText(/type/i)
    fireEvent.change(input, { target: { value: 'nope' } })
    expect(screen.getByRole('button', { name: /confirm/i })).toBeDisabled()

    fireEvent.change(input, { target: { value: 'win11' } })
    fireEvent.click(screen.getByRole('button', { name: /confirm/i }))
    await waitFor(() => expect(calls.length).toBe(2))
    expect(calls[1].path).toBe('/vms/9/snapshots/pre-upgrade/rollback')
    expect(calls[1].body).toEqual({ confirm: 'win11' })
  })

  it('deletes through window.confirm and invalidates the snapshot list', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { qc } = wrap(<SnapshotPanel vmId={9} vmName="win11" />)
    const spy = vi.spyOn(qc, 'invalidateQueries')
    fireEvent.click(await screen.findByRole('button', { name: /delete/i }))
    expect(confirmSpy).toHaveBeenCalled()
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0]).toMatchObject({ path: '/vms/9/snapshots/pre-upgrade', method: 'DELETE' })
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ['vms', 9, 'snapshots'] }))
    confirmSpy.mockRestore()
  })

  it('disables every mutating control with a plan tooltip when vms.snapshots is off', async () => {
    features = { 'vms.snapshots': false }
    wrap(<SnapshotPanel vmId={9} vmName="win11" />)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /take snapshot/i })).toBeDisabled())
    expect(screen.getByRole('button', { name: /rollback/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /delete/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /rollback/i }))
      .toHaveAttribute('title', 'Not included in your plan')
  })
})
```

- [ ] **Step 2: Run to verify the failure**

Run: `cd frontend && npx vitest run src/tests/snapshots.test.tsx`
Expected: FAIL, `Error: Failed to resolve import "../components/SnapshotPanel" from "src/tests/snapshots.test.tsx". Does the file exist?` (all 5 tests fail at collection; the file is never executed).

- [ ] **Step 3: Write `src/api/snapshots.ts`**

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { ApiError } from './client'
import type { JobRow } from './jobs'

/** PVE's own snapshot shape (doc 05: "List snapshots (live from Proxmox)"). */
export type SnapshotRow = {
  name: string
  description: string | null
  /** Unix seconds. Null on the synthetic `current` row. */
  snaptime: number | null
  /** true = the RAM state was captured alongside the disk (qemu only). */
  vmstate: boolean
  parent: string | null
  // PVE does not report a per-snapshot size for every storage plugin (LVM-thin
  // and ZFS internal snapshots have no standalone size), so this is optional on
  // purpose: doc 06 row 48's Size column renders ", " rather than a fake number.
  size_bytes?: number | null
}

export type SnapshotVars = {
  vmId: number
  op: 'create' | 'rollback' | 'delete'
  name: string
  description?: string
  vmstate?: boolean
  confirm?: string
}

export function useSnapshots(vmId: number) {
  return useQuery({
    queryKey: ['vms', vmId, 'snapshots'],
    queryFn: () => api<SnapshotRow[]>(`/vms/${vmId}/snapshots`),
  })
}

function request(v: SnapshotVars) {
  const base = `/vms/${v.vmId}/snapshots`
  if (v.op === 'create') {
    return api<{ job: JobRow }>(base, {
      method: 'POST',
      body: JSON.stringify({ name: v.name, description: v.description ?? '', vmstate: !!v.vmstate }),
    })
  }
  const one = `${base}/${encodeURIComponent(v.name)}`
  if (v.op === 'rollback') {
    return api<{ job: JobRow }>(`${one}/rollback`, {
      method: 'POST',
      body: JSON.stringify(v.confirm ? { confirm: v.confirm } : {}),
    })
  }
  return api<{ job: JobRow }>(one, { method: 'DELETE' })
}

/**
 * All three snapshot operations fire jobs, so they follow useLifecycle's
 * onSettled rule: invalidate ['jobs'] and ['cluster','activity'].
 *
 * They ALSO invalidate ['vms', id, 'snapshots'], which useLifecycle deliberately
 * does not do for ['vms'], and the difference is real, not an inconsistency.
 * ['vms'] is the poller's 30s resource cache holding an optimistic `pending`
 * patch that a refetch would stomp with stale data. ['vms', id, 'snapshots'] is
 * a live read straight off Proxmox with no optimistic patch to protect, so a
 * refetch can only move it closer to the truth. It is best-effort at enqueue
 * time (the job has only been accepted); the terminal `job` SSE delta
 * invalidates the ['vms'] prefix, which matches this key too, and is the
 * backstop that actually shows the finished result.
 */
export function useSnapshotAction() {
  const qc = useQueryClient()
  return useMutation<{ job: JobRow }, ApiError, SnapshotVars>({
    mutationFn: request,
    onSettled: (_data, _err, v) => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['cluster', 'activity'] })
      qc.invalidateQueries({ queryKey: ['vms', v.vmId, 'snapshots'] })
    },
  })
}
```

- [ ] **Step 4: Write `src/components/SnapshotPanel.tsx`**

```tsx
import { useState } from 'react'
import { toast } from 'sonner'
import { ApiError } from '../api/client'
import { useEntitlements } from '../api/hooks'
import { useSnapshotAction, useSnapshots } from '../api/snapshots'
import type { SnapshotRow } from '../api/snapshots'
import { ConfirmSelfDialog } from './ConfirmSelfDialog'
import { EmptyState } from './EmptyState'
import { inputCls } from './LoginForm'
import { Button } from './ui/button'
import { fmtBytes } from '../lib/format'

const card = 'rounded-card border border-line-soft bg-panel p-5'

type Guard = { phrase: string; detail: string; name: string }

const ROLLBACK_DETAIL =
  'Rolling back discards every change made since the snapshot was taken.'

/** Unix seconds → "YYYY-MM-DD HH:MM" in UTC. Deterministic, unlike toLocaleString. */
function fmtWhen(t: number | null | undefined): string {
  if (!t) return ', '
  return new Date(t * 1000).toISOString().replace('T', ' ').slice(0, 16)
}

/**
 * Doc 06 §(a) row 48: "Snapshots: table (Name/Created/Size) with Rollback +
 * Delete row actions and 'Take snapshot'". The with-RAM (vmstate) checkbox is
 * doc 01 §4's "with-RAM option surfaced".
 *
 * This panel only ever mounts under /vms/$vmId, i.e. qemu guests, which is why
 * the vmstate checkbox is unconditional, PVE rejects vmstate for LXC, so an
 * LXC consumer would have to hide it before reusing this component.
 */
export function SnapshotPanel({ vmId, vmName }: { vmId: number; vmName: string }) {
  const ent = useEntitlements()
  const { data, isError } = useSnapshots(vmId)
  const run = useSnapshotAction()
  const [guard, setGuard] = useState<Guard | null>(null)
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')
  const [withRam, setWithRam] = useState(false)

  // useEntitlements().has() is false until /entitlements resolves, gate on
  // ent.data != null too or every plan sees a dead panel during the first fetch.
  const denied = ent.data != null && !ent.has('vms.snapshots')
  const planTitle = denied ? 'Not included in your plan' : undefined

  // PVE's list carries a synthetic `current` row describing the live state; it
  // is not a snapshot and cannot be rolled back to or deleted.
  const rows: SnapshotRow[] = (data ?? []).filter((s) => s.name !== 'current')

  const fire = (op: 'create' | 'rollback' | 'delete', target: string, confirm?: string) =>
    run.mutate(
      { vmId, op, name: target, description: desc, vmstate: withRam, confirm },
      {
        onError: (e) => {
          const body = e instanceof ApiError ? (e.body as Record<string, unknown>) : null
          if (body?.error === 'confirm_required' || body?.error === 'self_target') {
            setGuard({
              phrase: String(body.confirm_phrase ?? vmName),
              detail: String(body.detail ?? ROLLBACK_DETAIL),
              name: target,
            })
            return
          }
          toast.error(`Could not ${op} snapshot "${target}"`)
        },
        onSuccess: () => {
          setGuard(null)
          if (op === 'create') { setName(''); setDesc(''); setWithRam(false) }
          toast.success(`Snapshot ${op} queued`)
        },
      },
    )

  const removeSnapshot = (s: SnapshotRow) => {
    // Destructive but not self-targeted, so the settings.tsx precedent applies:
    // native window.confirm, not a second bespoke typed-confirmation dialog.
    if (window.confirm(`Delete snapshot "${s.name}"? This cannot be undone.`)) {
      fire('delete', s.name)
    }
  }

  if (isError) {
    return <EmptyState title="Snapshots not available"
      note="Proxploy could not read this VM's snapshot list from Proxmox. Check the host connection." />
  }

  return (
    <>
      <div className={card}>
        <h2 className="mb-3 text-[13px] uppercase text-text-3">Take snapshot</h2>
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => { e.preventDefault(); fire('create', name.trim()) }}
        >
          <div className="w-[200px]">
            <label htmlFor="snap-name" className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
              Snapshot name
            </label>
            <input id="snap-name" className={inputCls} value={name} placeholder="pre-upgrade"
              onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="w-[260px]">
            <label htmlFor="snap-desc" className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
              Description (optional)
            </label>
            <input id="snap-desc" className={inputCls} value={desc}
              onChange={(e) => setDesc(e.target.value)} />
          </div>
          <label htmlFor="snap-ram" className="flex items-center gap-2 pb-2 text-[13px] text-text-2">
            <input id="snap-ram" type="checkbox" checked={withRam}
              onChange={(e) => setWithRam(e.target.checked)} />
            Include RAM (vmstate)
          </label>
          <Button type="submit" className="mb-0.5" disabled={denied || run.isPending || name.trim() === ''}
            title={planTitle}>
            Take snapshot
          </Button>
        </form>
        <p className="mt-2 text-[12px] text-text-3">
          Including RAM captures the running state so a rollback resumes mid-boot,
          but writes the whole memory allocation to disk and briefly pauses the guest.
        </p>
      </div>

      <div className={`${card} mt-4`}>
        {rows.length === 0 ? (
          <EmptyState title="No snapshots" note="Snapshots taken here and in Proxmox both show up in this list." />
        ) : (
          <table className="w-full text-left text-[13px]">
            <thead>
              <tr className="text-[11px] uppercase text-text-3">
                <th scope="col" className="pb-2 font-medium">Name</th>
                <th scope="col" className="pb-2 font-medium">Created</th>
                <th scope="col" className="pb-2 font-medium">Size</th>
                <th scope="col" className="pb-2 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.name} className="border-t border-line-soft hover:bg-panel-2">
                  <td className="py-2.5 font-mono">
                    {s.name}
                    {s.vmstate && (
                      <span className="ml-2 rounded-full border border-amber/30 bg-amber-dim px-1.5 py-0.5 font-mono text-[9.5px] text-amber">
                        RAM
                      </span>
                    )}
                    {s.description && (
                      <div className="font-ui text-[11.5px] text-text-3">{s.description}</div>
                    )}
                  </td>
                  <td className="py-2.5 font-mono text-text-2">{fmtWhen(s.snaptime)}</td>
                  <td className="py-2.5 font-mono text-text-2"
                    title={s.size_bytes == null ? 'Proxmox does not report a size for this storage plugin' : undefined}>
                    {s.size_bytes == null ? ', ' : fmtBytes(s.size_bytes)}
                  </td>
                  <td className="flex items-center gap-2 py-2.5">
                    <Button variant="go" className="px-2 py-1 text-[11px]"
                      disabled={denied || run.isPending} title={planTitle}
                      onClick={() => fire('rollback', s.name)}>
                      Rollback
                    </Button>
                    <Button variant="danger" className="px-2 py-1 text-[11px]"
                      disabled={denied || run.isPending} title={planTitle}
                      onClick={() => removeSnapshot(s)}>
                      Delete
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {guard && (
        <ConfirmSelfDialog
          phrase={guard.phrase}
          detail={guard.detail}
          onCancel={() => setGuard(null)}
          onConfirm={(typed) => fire('rollback', guard.name, typed)}
        />
      )}
    </>
  )
}
```

- [ ] **Step 5: Run the new test file to verify it passes**

Run: `cd frontend && npx vitest run src/tests/snapshots.test.tsx`
Expected: PASS, `Test Files 1 passed (1)`, `Tests 5 passed (5)`.

- [ ] **Step 6: Replace `vmSnapshotsRoute` and delete the dead `phaseTab` helper in `routes/vms.tsx`**

Delete this block outright (`frontend/src/routes/vms.tsx`, between `vmDetailRoute` and `vmOverviewRoute`):

```tsx
const phaseTab = (path: string, phase: string, note: string) =>
  createRoute({
    getParentRoute: () => vmDetailRoute,
    path,
    component: () => <EmptyState title={`This tab lands in ${phase}`} note={note} />,
  })
```

Replace the last two lines of the file:

```tsx
export const vmSnapshotsRoute = phaseTab('snapshots', 'Phase 6 (Infra pages)',
  'List, create, roll back and delete snapshots.')
```

with:

```tsx
function VmSnapshots() {
  const { vmId } = useParams({ strict: false }) as { vmId: string }
  const id = Number(vmId)
  const { data: vm } = useQuery({ queryKey: ['vms', id], queryFn: () => api<VmRow>(`/vms/${id}`) })
  // The tab renders inside VmDetail's Outlet, so the ['vms', id] row is already
  // warm; this read is a cache hit, not a second round trip.
  if (!vm) return null
  return <SnapshotPanel vmId={id} vmName={vm.name} />
}

export const vmSnapshotsRoute = createRoute({
  getParentRoute: () => vmDetailRoute, path: 'snapshots', component: VmSnapshots,
})
```

Add one import near the other component imports at the top of `vms.tsx`:

```tsx
import { SnapshotPanel } from '../components/SnapshotPanel'
```

`EmptyState` stays imported, `VmsPage`, `VmDetail` and `VmConsole` all still use it. `createRoute`, `useParams`, `useQuery`, `api` and `VmRow` are already imported.

- [ ] **Step 7: Run the full frontend suite, build and lint**

Run: `cd frontend && npx vitest run && npm run build && npm run lint`
Expected: PASS, Task 15's total **+5 tests across +1 file** (`snapshots.test.tsx`, 5 passed). `tsc -b && vite build` clean; oxlint reports 0 warnings, 0 errors. Nothing in Tasks 12-15 touches `routes/vms.tsx`, so no pre-existing test changes count.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api/snapshots.ts frontend/src/components/SnapshotPanel.tsx \
        frontend/src/routes/vms.tsx frontend/src/tests/snapshots.test.tsx
git commit -m "feat(vms): real snapshots tab, list, take (with-RAM), roll back and delete"
```

---

## Task 17: Frontend: VM create wizard + clone dialog

**Files:**
- Create: `frontend/src/components/VmCreateWizard.tsx`
- Create: `frontend/src/components/CloneDialog.tsx`
- Modify: `frontend/src/routes/vms.tsx`
- Test: `frontend/src/tests/vmcreate.test.tsx`

**Interfaces:**
- Consumes (Task 11): `POST /api/v1/vms` body `{host_id, node, name, ostype, iso, cores, memory_mb, disk_gb, storage, bridge, vlan_tag}` → `202 {"job": {...}}`; `POST /api/v1/vms/{id}/clone` body `{name, full, storage}` → `202 {"job": {...}}`. Entitlement keys `vms.create` (admin) and `vms.clone` (admin, the Pro flag).
- Consumes (Task 3): `GET /api/v1/storage -> [{host_id, host_name, node, storage, type, content: string[], shared, status, used_bytes, total_bytes, used_pct}]`; `GET /api/v1/storage/{host_id}/{name}/content?node=&content=iso -> [{volid, format, size, used, vmid, ctime, content, notes, verification}]`.
- Consumes (Task 6): `GET /api/v1/network/bridges?host= -> {nodes: [{host_id, host_name, node, interfaces: [{iface, type, ...}]}], attachments: [...]}`.
- Consumes (existing): `GET /api/v1/hosts -> [{id, name, ...}]`, `GET /api/v1/cluster/nodes -> [{host_id, node, ...}]`, `components/JobLog`, `components/KVGrid`, `components/LoginForm::inputCls`, `components/ui/button::Button`, `api/hooks::useEntitlements`/`VmRow`, `api/jobs::JobRow`, `api/client::api`/`ApiError`.
- Produces: `src/components/VmCreateWizard.tsx::VmCreateWizard({ onClose }: { onClose: () => void })`, `src/components/CloneDialog.tsx::CloneDialog({ vm, onClose }: { vm: VmRow; onClose: () => void })`, and the doc 06 §(a) row 42 **"New VM"** header button plus a **Clone** row action in `VmsPage`.

**This task adds zero backend calls.** Every list the wizard offers already has an endpoint: hosts and nodes from Phase 2, storages and ISO content from Task 3, bridges from Task 6, and the two mutations from Task 11.

- [ ] **Step 1: Write the failing test file**

```tsx
// frontend/src/tests/vmcreate.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const calls: { path: string; method: string; body: any }[] = []
let features: Record<string, boolean> = { 'vms.create': true, 'vms.clone': true }
let cloneRejects = false

const VM = {
  id: 9, host_id: 1, host_name: 'host-01', vmid: 201, name: 'win11',
  status: 'running', os_type: 'win11', cpu_cores: 4, cpu_pct: 3,
  mem_bytes: 8589934592, disk_bytes: 68719476736, uptime_s: 3600, synced_at: null,
}

vi.mock('../api/client', () => {
  class ApiError extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) {
      super(`API ${status}`); this.status = status; this.body = body
    }
  }
  return {
    ApiError,
    api: vi.fn((path: string, opts?: RequestInit) => {
      const method = (opts?.method ?? 'GET').toUpperCase()
      if (method === 'GET') {
        if (path === '/entitlements') return Promise.resolve({ tier: 'builtin', features, grace: null })
        if (path === '/vms') return Promise.resolve([VM])
        if (path === '/hosts') return Promise.resolve([{ id: 1, name: 'host-01' }])
        if (path === '/cluster/nodes') return Promise.resolve([{ host_id: 1, node: 'pve1' }])
        if (path === '/storage') return Promise.resolve([
          { host_id: 1, node: 'pve1', storage: 'local', content: ['iso', 'vztmpl'] },
          { host_id: 1, node: 'pve1', storage: 'local-lvm', content: ['images', 'rootdir'] },
        ])
        if (path.startsWith('/storage/1/local/content')) {
          return Promise.resolve([{ volid: 'local:iso/ubuntu-24.04.iso', size: 6000000000 }])
        }
        if (path.startsWith('/network/bridges')) {
          return Promise.resolve({ nodes: [{ host_id: 1, node: 'pve1', interfaces: [
            { iface: 'vmbr0', type: 'bridge' }, { iface: 'enp1s0', type: 'eth' },
          ] }], attachments: [] })
        }
        if (path.startsWith('/jobs/')) return Promise.resolve([])
        return Promise.resolve(null)
      }
      const body = opts?.body ? JSON.parse(String(opts.body)) : {}
      calls.push({ path, method, body })
      if (cloneRejects && path.endsWith('/clone')) {
        return Promise.reject(new ApiError(502, {
          detail: "proxmox: 400 Parameter verification failed. full: linked clone feature is not supported for drive 'scsi0'",
        }))
      }
      return Promise.resolve({ job: { id: 11, kind: 'vm.create', status: 'queued' } })
    }),
  }
})

vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ children }: { children?: unknown }) => <a>{children as never}</a>,
  useNavigate: () => () => {},
  useSearch: () => ({}),
}))

import { CloneDialog } from '../components/CloneDialog'
import { VmCreateWizard } from '../components/VmCreateWizard'
import { VmsPage } from '../routes/vms'

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return { qc, ...render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>) }
}
const next = () => fireEvent.click(screen.getByRole('button', { name: 'Next' }))

describe('VmCreateWizard', () => {
  beforeEach(() => {
    calls.length = 0
    cloneRejects = false
    features = { 'vms.create': true, 'vms.clone': true }
  })

  it('walks Target → OS → Resources → Network → Confirm and posts the assembled spec', async () => {
    wrap(<VmCreateWizard onClose={() => {}} />)

    // Every <select> renders empty and fills in when its query resolves, so each
    // pick waits for its own <option>, changing to a value with no matching
    // option is a silent no-op in jsdom.
    await screen.findByRole('option', { name: 'host-01' })
    fireEvent.change(screen.getByLabelText(/^host$/i), { target: { value: '1' } })
    await screen.findByRole('option', { name: 'pve1' })
    fireEvent.change(screen.getByLabelText(/^node$/i), { target: { value: 'pve1' } })
    fireEvent.change(screen.getByLabelText(/vm name/i), { target: { value: 'ubuntu-lab' } })
    next()

    fireEvent.change(await screen.findByLabelText(/iso storage/i), { target: { value: 'local' } })
    // The ISO list only loads once a datastore is picked; wait for the <option>
    // itself, or fireEvent.change sets a value that has no matching option.
    await screen.findByRole('option', { name: 'local:iso/ubuntu-24.04.iso' })
    fireEvent.change(screen.getByLabelText(/iso image/i),
      { target: { value: 'local:iso/ubuntu-24.04.iso' } })
    fireEvent.change(screen.getByLabelText(/os type/i), { target: { value: 'l26' } })
    next()

    fireEvent.change(screen.getByLabelText(/cores/i), { target: { value: '4' } })
    fireEvent.change(screen.getByLabelText(/memory/i), { target: { value: '4096' } })
    fireEvent.change(screen.getByLabelText(/disk size/i), { target: { value: '64' } })
    await screen.findByRole('option', { name: 'local-lvm' })
    fireEvent.change(screen.getByLabelText(/target storage/i), { target: { value: 'local-lvm' } })
    next()

    await screen.findByRole('option', { name: 'vmbr0' })
    fireEvent.change(screen.getByLabelText(/bridge/i), { target: { value: 'vmbr0' } })
    fireEvent.change(screen.getByLabelText(/vlan tag/i), { target: { value: '20' } })
    next()

    expect(screen.getByText('ubuntu-lab')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Create' }))

    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0]).toMatchObject({
      path: '/vms', method: 'POST',
      body: {
        host_id: 1, node: 'pve1', name: 'ubuntu-lab', ostype: 'l26',
        iso: 'local:iso/ubuntu-24.04.iso', cores: 4, memory_mb: 4096,
        disk_gb: 64, storage: 'local-lvm', bridge: 'vmbr0', vlan_tag: 20,
      },
    })
    // InstallDialog pattern: the body swaps for the job log once the job lands.
    expect(await screen.findByText('No output yet.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Close' })).toBeInTheDocument()
  })

  it('asks the storage content endpoint for ISOs only', async () => {
    const { api } = await import('../api/client')
    wrap(<VmCreateWizard onClose={() => {}} />)
    await screen.findByRole('option', { name: 'host-01' })
    fireEvent.change(screen.getByLabelText(/^host$/i), { target: { value: '1' } })
    await screen.findByRole('option', { name: 'pve1' })
    fireEvent.change(screen.getByLabelText(/^node$/i), { target: { value: 'pve1' } })
    fireEvent.change(screen.getByLabelText(/vm name/i), { target: { value: 'x' } })
    next()
    await screen.findByRole('option', { name: 'local' })
    fireEvent.change(screen.getByLabelText(/iso storage/i), { target: { value: 'local' } })
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith('/storage/1/local/content?node=pve1&content=iso'))
  })
})

describe('VmsPage create/clone affordances', () => {
  beforeEach(() => {
    calls.length = 0
    cloneRejects = false
    features = { 'vms.create': true, 'vms.clone': true }
  })

  it('renders the New VM button and disables it with a tooltip when vms.create is off', async () => {
    features = { 'vms.create': false, 'vms.clone': true }
    wrap(<VmsPage />)
    const btn = await screen.findByRole('button', { name: 'New VM' })
    await waitFor(() => expect(btn).toBeDisabled())
    expect(btn).toHaveAttribute('title', 'Not included in your plan')
  })

  it('disables the Clone row action with a Pro tooltip when vms.clone is off', async () => {
    features = { 'vms.create': true, 'vms.clone': false }
    wrap(<VmsPage />)
    const btn = await screen.findByRole('button', { name: 'Clone' })
    await waitFor(() => expect(btn).toBeDisabled())
    expect(btn).toHaveAttribute('title', 'Cloning is a Pro feature')
  })
})

describe('CloneDialog', () => {
  beforeEach(() => { calls.length = 0; cloneRejects = false })

  it('posts the new name, clone mode and target storage', async () => {
    wrap(<CloneDialog vm={VM as never} onClose={() => {}} />)
    fireEvent.change(await screen.findByLabelText(/new name/i), { target: { value: 'win11-copy' } })
    await screen.findByRole('option', { name: 'local-lvm' })
    fireEvent.change(screen.getByLabelText(/target storage/i), { target: { value: 'local-lvm' } })
    fireEvent.click(screen.getByRole('button', { name: 'Clone' }))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0]).toMatchObject({
      path: '/vms/9/clone', method: 'POST',
      body: { name: 'win11-copy', full: true, storage: 'local-lvm' },
    })
    expect(await screen.findByText('No output yet.')).toBeInTheDocument()
  })

  it("renders PVE's linked-clone rejection verbatim instead of pre-validating template-ness", async () => {
    cloneRejects = true
    wrap(<CloneDialog vm={VM as never} onClose={() => {}} />)
    fireEvent.change(await screen.findByLabelText(/new name/i), { target: { value: 'win11-linked' } })
    fireEvent.click(screen.getByLabelText(/linked/i))
    fireEvent.click(screen.getByRole('button', { name: 'Clone' }))
    expect(await screen.findByText(/linked clone feature is not supported for drive 'scsi0'/))
      .toBeInTheDocument()
    expect(calls[0].body).toMatchObject({ full: false })
  })
})
```

- [ ] **Step 2: Run to verify the failure**

Run: `cd frontend && npx vitest run src/tests/vmcreate.test.tsx`
Expected: FAIL, `Error: Failed to resolve import "../components/CloneDialog" from "src/tests/vmcreate.test.tsx". Does the file exist?` (collection error; none of the 5 tests run).

- [ ] **Step 3: Write `src/components/VmCreateWizard.tsx`**

```tsx
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, ApiError } from '../api/client'
import type { JobRow } from '../api/jobs'
import { JobLog } from './JobLog'
import { KVGrid } from './KVGrid'
import { inputCls } from './LoginForm'
import { Button } from './ui/button'

// Deliberately local, deliberately narrow row types: the wizard reads the
// endpoints Tasks 3, 6 and 11 built, not Tasks 12/14's page hooks, so the
// Storage and Network pages stay free to reshape their own hook signatures.
type HostRow = { id: number; name: string }
type NodeRow = { host_id: number; node: string }
type StorageRow = { host_id: number; node: string; storage: string; content: string[] }
type ContentRow = { volid: string; size: number }
type BridgesOut = { nodes: { host_id: number; node: string; interfaces: { iface: string; type: string }[] }[] }

const STEPS = ['Target', 'OS', 'Resources', 'Network', 'Confirm'] as const

// PVE `ostype` values for qemu. The full list is longer; these four cover
// everything Proxploy's own install paths produce plus an honest escape hatch.
const OS_TYPES = [
  ['l26', 'Linux (kernel 2.6 – 6.x)'],
  ['win11', 'Windows 11 / Server 2022'],
  ['win10', 'Windows 10 / Server 2016-2019'],
  ['other', 'Other / unspecified'],
] as const

const lbl = 'mb-1 block text-[11px] uppercase tracking-wide text-text-3'

function Field({ id, label, children }: { id: string; label: string; children: React.ReactNode }) {
  return (
    <div>
      <label htmlFor={id} className={lbl}>{label}</label>
      {children}
    </div>
  )
}

/**
 * Doc 06 §(a) row 42's "New VM". Mirrors routes/onboarding.tsx's wizard shape
 * on purpose, a step index, a STEPS chip row, `{step === N && (…)}` blocks; 
 * rather than becoming a reusable <Wizard/>: there are exactly two multi-step
 * flows in this app and they share no fields.
 *
 * On submit it follows InstallDialog: fire the mutation, keep the job id, swap
 * the body for <JobLog/> + Close.
 */
export function VmCreateWizard({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const [step, setStep] = useState(0)
  const [jobId, setJobId] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [f, setF] = useState({
    host_id: '', node: '', name: '',
    iso_storage: '', iso: '', ostype: 'l26',
    cores: '2', memory_mb: '2048', disk_gb: '32', storage: '',
    bridge: '', vlan_tag: '',
  })
  const set = (k: keyof typeof f, v: string) => setF((s) => ({ ...s, [k]: v }))
  const hostId = Number(f.host_id) || 0

  const hosts = useQuery({ queryKey: ['hosts'], queryFn: () => api<HostRow[]>('/hosts') })
  const nodes = useQuery({ queryKey: ['cluster', 'nodes'], queryFn: () => api<NodeRow[]>('/cluster/nodes') })
  const storages = useQuery({ queryKey: ['storage'], queryFn: () => api<StorageRow[]>('/storage') })
  const isos = useQuery({
    queryKey: ['storage', hostId, f.iso_storage, f.node, 'iso'],
    enabled: hostId > 0 && f.iso_storage !== '' && f.node !== '',
    queryFn: () => api<ContentRow[]>(
      `/storage/${hostId}/${f.iso_storage}/content?node=${encodeURIComponent(f.node)}&content=iso`),
  })
  const bridges = useQuery({
    queryKey: ['network', 'bridges', hostId],
    enabled: hostId > 0,
    queryFn: () => api<BridgesOut>(`/network/bridges?host=${hostId}`),
  })

  const nodeOpts = (nodes.data ?? []).filter((n) => n.host_id === hostId)
  const storeOpts = (kind: string) => (storages.data ?? [])
    .filter((s) => s.host_id === hostId && s.node === f.node && (s.content ?? []).includes(kind))
  const bridgeOpts = (bridges.data?.nodes ?? [])
    .filter((n) => n.node === f.node)
    .flatMap((n) => n.interfaces)
    .filter((i) => i.type === 'bridge')

  const create = useMutation<{ job: JobRow }, ApiError, void>({
    mutationFn: () => api<{ job: JobRow }>('/vms', {
      method: 'POST',
      body: JSON.stringify({
        host_id: hostId, node: f.node, name: f.name.trim(), ostype: f.ostype,
        iso: f.iso, cores: Number(f.cores), memory_mb: Number(f.memory_mb),
        disk_gb: Number(f.disk_gb), storage: f.storage, bridge: f.bridge,
        vlan_tag: f.vlan_tag ? Number(f.vlan_tag) : null,
      }),
    }),
    // useLifecycle's rule: the job is only *accepted* here, so refetching ['vms']
    // would show nothing new. ['jobs'] + activity are what actually moved.
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['cluster', 'activity'] })
    },
  })

  const ok = [
    hostId > 0 && f.node !== '' && f.name.trim() !== '',
    f.iso_storage !== '' && f.iso !== '',
    Number(f.cores) > 0 && Number(f.memory_mb) > 0 && Number(f.disk_gb) > 0 && f.storage !== '',
    f.bridge !== '',
    true,
  ]

  const submit = () => {
    setError('')
    create.mutate(undefined, {
      onSuccess: (r) => setJobId(r.job.id),
      onError: (e) => setError(
        e instanceof ApiError
          ? String((e.body as any)?.detail ?? (e.body as any)?.error ?? e.message)
          : 'Request failed'),
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-[560px] max-w-[92vw] rounded-card border border-line bg-panel p-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-display text-[16px] font-semibold text-text">New VM</h2>
          <div className="flex gap-1.5">
            {STEPS.map((s, i) => (
              <span key={s}
                className={`rounded-full border px-2 py-0.5 font-mono text-[9.5px] ${i === step ? 'border-amber text-amber' : 'border-line text-text-3'}`}>
                {i + 1} {s}
              </span>
            ))}
          </div>
        </div>

        {jobId ? (
          <div>
            <JobLog jobId={jobId} />
            <Button className="mt-3" variant="ghost" onClick={onClose}>Close</Button>
          </div>
        ) : (
          <>
            {step === 0 && (
              <div className="space-y-3">
                <Field id="vm-host" label="Host">
                  <select id="vm-host" className={inputCls} value={f.host_id}
                    onChange={(e) => { set('host_id', e.target.value); set('node', ''); set('iso_storage', ''); set('iso', ''); set('storage', ''); set('bridge', '') }}>
                    <option value="">Select a host…</option>
                    {(hosts.data ?? []).map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
                  </select>
                </Field>
                <Field id="vm-node" label="Node">
                  <select id="vm-node" className={inputCls} value={f.node}
                    onChange={(e) => set('node', e.target.value)}>
                    <option value="">Select a node…</option>
                    {nodeOpts.map((n) => <option key={n.node} value={n.node}>{n.node}</option>)}
                  </select>
                </Field>
                <Field id="vm-name" label="VM name">
                  <input id="vm-name" className={inputCls} placeholder="ubuntu-lab"
                    value={f.name} onChange={(e) => set('name', e.target.value)} />
                </Field>
              </div>
            )}

            {step === 1 && (
              <div className="space-y-3">
                <Field id="vm-isostore" label="ISO storage">
                  <select id="vm-isostore" className={inputCls} value={f.iso_storage}
                    onChange={(e) => { set('iso_storage', e.target.value); set('iso', '') }}>
                    <option value="">Select a datastore…</option>
                    {storeOpts('iso').map((s) => <option key={s.storage} value={s.storage}>{s.storage}</option>)}
                  </select>
                </Field>
                <Field id="vm-iso" label="ISO image">
                  <select id="vm-iso" className={inputCls} value={f.iso}
                    onChange={(e) => set('iso', e.target.value)}>
                    <option value="">Select an ISO…</option>
                    {(isos.data ?? []).map((v) => <option key={v.volid} value={v.volid}>{v.volid}</option>)}
                  </select>
                </Field>
                <Field id="vm-ostype" label="OS type">
                  <select id="vm-ostype" className={inputCls} value={f.ostype}
                    onChange={(e) => set('ostype', e.target.value)}>
                    {OS_TYPES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                  </select>
                </Field>
                <p className="text-[12px] text-text-3">
                  No ISOs listed? Upload one on the Storage page, this list is the
                  datastore's own <span className="font-mono">content=iso</span> listing.
                </p>
              </div>
            )}

            {step === 2 && (
              <div className="grid grid-cols-2 gap-3">
                <Field id="vm-cores" label="Cores">
                  <input id="vm-cores" type="number" min="1" className={inputCls}
                    value={f.cores} onChange={(e) => set('cores', e.target.value)} />
                </Field>
                <Field id="vm-mem" label="Memory (MB)">
                  <input id="vm-mem" type="number" min="128" step="128" className={inputCls}
                    value={f.memory_mb} onChange={(e) => set('memory_mb', e.target.value)} />
                </Field>
                <Field id="vm-disk" label="Disk size (GB)">
                  <input id="vm-disk" type="number" min="1" className={inputCls}
                    value={f.disk_gb} onChange={(e) => set('disk_gb', e.target.value)} />
                </Field>
                <Field id="vm-storage" label="Target storage">
                  <select id="vm-storage" className={inputCls} value={f.storage}
                    onChange={(e) => set('storage', e.target.value)}>
                    <option value="">Select a datastore…</option>
                    {storeOpts('images').map((s) => <option key={s.storage} value={s.storage}>{s.storage}</option>)}
                  </select>
                </Field>
              </div>
            )}

            {step === 3 && (
              <div className="space-y-3">
                <Field id="vm-bridge" label="Bridge">
                  <select id="vm-bridge" className={inputCls} value={f.bridge}
                    onChange={(e) => set('bridge', e.target.value)}>
                    <option value="">Select a bridge…</option>
                    {bridgeOpts.map((i) => <option key={i.iface} value={i.iface}>{i.iface}</option>)}
                  </select>
                </Field>
                <Field id="vm-vlan" label="VLAN tag (optional)">
                  <input id="vm-vlan" type="number" min="1" max="4094" className={inputCls}
                    placeholder="untagged" value={f.vlan_tag}
                    onChange={(e) => set('vlan_tag', e.target.value)} />
                </Field>
              </div>
            )}

            {step === 4 && (
              <div className="rounded-ctl border border-line-soft bg-elev p-3">
                <KVGrid items={[
                  ['Name', f.name],
                  ['Host / node', `${(hosts.data ?? []).find((h) => h.id === hostId)?.name ?? ', '} / ${f.node}`],
                  ['OS type', f.ostype],
                  ['ISO', f.iso],
                  ['Cores', f.cores],
                  ['Memory', `${f.memory_mb} MB`],
                  ['Disk', `${f.disk_gb} GB on ${f.storage}`],
                  ['Network', f.vlan_tag ? `${f.bridge} tag ${f.vlan_tag}` : f.bridge],
                ]} />
              </div>
            )}

            {error && <p className="mt-3 text-[12.5px] text-red">{error}</p>}

            <div className="mt-4 flex justify-end gap-2">
              <Button variant="ghost" onClick={onClose}>Cancel</Button>
              {step > 0 && (
                <Button variant="ghost" onClick={() => setStep(step - 1)}>Back</Button>
              )}
              {step < STEPS.length - 1 ? (
                <Button disabled={!ok[step]} onClick={() => setStep(step + 1)}>Next</Button>
              ) : (
                <Button disabled={create.isPending} onClick={submit}>Create</Button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Write `src/components/CloneDialog.tsx`**

```tsx
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, ApiError } from '../api/client'
import type { VmRow } from '../api/hooks'
import type { JobRow } from '../api/jobs'
import { JobLog } from './JobLog'
import { inputCls } from './LoginForm'
import { Button } from './ui/button'

type StorageRow = { host_id: number; node: string; storage: string; content: string[] }

/**
 * Clone a VM: new name, full vs linked, target storage. Same InstallDialog
 * pattern, fire, keep the job id, swap the body for the job log.
 */
export function CloneDialog({ vm, onClose }: { vm: VmRow; onClose: () => void }) {
  const qc = useQueryClient()
  const [name, setName] = useState(`${vm.name}-clone`)
  const [full, setFull] = useState(true)
  const [storage, setStorage] = useState('')
  const [jobId, setJobId] = useState<number | null>(null)
  const [error, setError] = useState('')

  const storages = useQuery({ queryKey: ['storage'], queryFn: () => api<StorageRow[]>('/storage') })
  const storeOpts = (storages.data ?? [])
    .filter((s) => s.host_id === vm.host_id && (s.content ?? []).includes('images'))

  const clone = useMutation<{ job: JobRow }, ApiError, void>({
    mutationFn: () => api<{ job: JobRow }>(`/vms/${vm.id}/clone`, {
      method: 'POST',
      body: JSON.stringify({ name: name.trim(), full, storage: storage || null }),
    }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['cluster', 'activity'] })
    },
  })

  const submit = () => {
    setError('')
    clone.mutate(undefined, {
      onSuccess: (r) => setJobId(r.job.id),
      // Linked clone is only valid from a template and Proxploy does not track
      // template-ness, so the option is offered unconditionally and PVE's own
      // rejection is shown verbatim rather than guessed at up front.
      onError: (e) => setError(
        e instanceof ApiError
          ? String((e.body as any)?.detail ?? (e.body as any)?.error ?? e.message)
          : 'Request failed'),
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-[520px] max-w-[92vw] rounded-card border border-line bg-panel p-5">
        <h2 className="font-display text-[16px] font-semibold text-text">
          Clone <span className="font-mono">{vm.name}</span>
        </h2>

        {jobId ? (
          <div className="mt-4">
            <JobLog jobId={jobId} />
            <Button className="mt-3" variant="ghost" onClick={onClose}>Close</Button>
          </div>
        ) : (
          <>
            <div className="mt-4 space-y-3">
              <div>
                <label htmlFor="clone-name" className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
                  New name
                </label>
                <input id="clone-name" className={inputCls} value={name}
                  onChange={(e) => setName(e.target.value)} />
              </div>
              <fieldset className="space-y-1.5">
                <legend className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">Mode</legend>
                <label htmlFor="clone-full" className="flex items-center gap-2 text-[13px] text-text-2">
                  <input id="clone-full" type="radio" name="clone-mode" checked={full}
                    onChange={() => setFull(true)} />
                  Full clone, an independent copy of every disk
                </label>
                <label htmlFor="clone-linked" className="flex items-center gap-2 text-[13px] text-text-2">
                  <input id="clone-linked" type="radio" name="clone-mode" checked={!full}
                    onChange={() => setFull(false)} />
                  Linked clone, shares the base disk, template sources only
                </label>
              </fieldset>
              <div>
                <label htmlFor="clone-storage" className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
                  Target storage
                </label>
                <select id="clone-storage" className={inputCls} value={storage}
                  onChange={(e) => setStorage(e.target.value)}>
                  <option value="">Same as source</option>
                  {storeOpts.map((s) => <option key={s.storage} value={s.storage}>{s.storage}</option>)}
                </select>
              </div>
              {!full && (
                <p className="text-[12px] text-text-3">
                  Proxmox only accepts a linked clone when the source is a template.
                  Proxploy does not track template-ness, so if this VM is not one,
                  Proxmox&apos;s own error is shown here unchanged.
                </p>
              )}
              {error && <p className="text-[12.5px] text-red">{error}</p>}
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="ghost" onClick={onClose}>Cancel</Button>
              <Button disabled={clone.isPending || name.trim() === ''} onClick={submit}>Clone</Button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Wire "New VM" and the Clone row action into `VmsPage`**

In `frontend/src/routes/vms.tsx`, add the imports:

```tsx
import { useState } from 'react'
import { useEntitlements } from '../api/hooks'
import { CloneDialog } from '../components/CloneDialog'
import { VmCreateWizard } from '../components/VmCreateWizard'
```

(`import { useEffect } from 'react'` already exists, merge it into `import { useEffect, useState } from 'react'`; `useMetrics` is already imported from `../api/hooks`, so add `useEntitlements` to that import list.)

Replace the `VmsPage` header block and the row-action cell. The whole updated function:

```tsx
export function VmsPage() {
  const navigate = useNavigate()
  const ent = useEntitlements()
  const [creating, setCreating] = useState(false)
  const [cloning, setCloning] = useState<VmRow | null>(null)
  const { data: vms } = useQuery({
    queryKey: ['vms', {}],
    queryFn: () => api<VmRow[]>('/vms'),
    refetchInterval: 30_000,
  })
  const running = vms?.filter((v) => v.status === 'running').length ?? 0
  // ent.has() is false until /entitlements resolves, gate on ent.data != null
  // too, or every plan sees a dead "New VM" button for the whole first fetch.
  const createDenied = ent.data != null && !ent.has('vms.create')
  const cloneDenied = ent.data != null && !ent.has('vms.clone')
  return (
    <div>
      <div className="mb-5 flex items-center">
        <div>
          <h1 className="font-display text-[22px] font-semibold">Virtual Machines</h1>
          <div className="text-[12px] text-text-3">
            {vms ? `${vms.length} VMs · ${running} running` : '…'}
          </div>
        </div>
        <Button className="ml-auto" disabled={createDenied}
          title={createDenied ? 'Not included in your plan' : undefined}
          onClick={() => setCreating(true)}>
          New VM
        </Button>
      </div>
      {vms && vms.length > 0 ? (
        <div className={card}>
          <table className="w-full text-left text-[13px]">
            <thead>
              <tr className="text-[11px] uppercase text-text-3">
                <th scope="col" className="pb-2 font-medium">Name</th>
                <th scope="col" className="pb-2 font-medium">Node</th>
                <th scope="col" className="pb-2 font-medium">vCPU / RAM</th>
                <th scope="col" className="pb-2 font-medium">CPU</th>
                <th scope="col" className="pb-2 font-medium">Status</th>
                <th scope="col" className="pb-2 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {vms.map((v) => (
                <tr
                  key={v.id}
                  className="cursor-pointer border-t border-line-soft hover:bg-panel-2"
                  onClick={() => navigate({ to: '/vms/$vmId' as never, params: { vmId: String(v.id) } as never })}
                >
                  <td className="py-2.5 font-mono">{v.name}</td>
                  <td className="py-2.5 text-text-2">{v.host_name}</td>
                  <td className="py-2.5 font-mono text-text-2">
                    {v.cpu_cores ?? ', '} / {fmtBytes(v.mem_bytes)}
                  </td>
                  <td className="py-2.5 font-mono text-text-2">{fmtPct(v.cpu_pct)}</td>
                  <td className="py-2.5"><StatusPill status={v.status} /></td>
                  <td className="py-2.5 flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                    <LifecycleActions target="vm" id={v.id} name={v.name} status={v.status} size="sm" />
                    <Button variant="ghost" className="px-2 py-1 text-[11px]"
                      onClick={() => navigate({ to: '/vms/$vmId/console' as never, params: { vmId: String(v.id) } as never })}>
                      Console
                    </Button>
                    {/* doc 06 §e rule 2: a table-cell button is a "small inline
                        action", so the Pro treatment here is disabled+tooltip,
                        not LockVeil, veiling a 60px cell blurs nothing legible,
                        and a disabled trigger makes a veil inside the dialog
                        unreachable dead code. */}
                    <Button variant="ghost" className="px-2 py-1 text-[11px]"
                      disabled={cloneDenied}
                      title={cloneDenied ? 'Cloning is a Pro feature' : undefined}
                      onClick={() => setCloning(v)}>
                      Clone
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="No VMs discovered"
          note="QEMU guests on connected hosts are mirrored here by the poller." />
      )}
      {creating && <VmCreateWizard onClose={() => setCreating(false)} />}
      {cloning && <CloneDialog vm={cloning} onClose={() => setCloning(null)} />}
    </div>
  )
}
```

- [ ] **Step 6: Run the new test file to verify it passes**

Run: `cd frontend && npx vitest run src/tests/vmcreate.test.tsx`
Expected: PASS, `Test Files 1 passed (1)`, `Tests 5 passed (5)`.

- [ ] **Step 7: Run the full frontend suite, build and lint**

Run: `cd frontend && npx vitest run && npm run build && npm run lint`
Expected: PASS, Task 16's total **+5 tests across +1 file** (`vmcreate.test.tsx`, 5 passed). `tsc -b && vite build` clean; oxlint 0 warnings, 0 errors. `src/tests/nav.test.tsx` is untouched and still passes, this task adds page controls, never a nav entry.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/VmCreateWizard.tsx frontend/src/components/CloneDialog.tsx \
        frontend/src/routes/vms.tsx frontend/src/tests/vmcreate.test.tsx
git commit -m "feat(vms): New VM wizard (target/OS/resources/network/confirm) + clone dialog"
```

---

## Task 18: DoD verification, doc-05 amendment, notes doc, buildlog

**Files:**
- Create: `backend/dod_verify_phase6.py` (throwaway, **not committed**; same as `dod_verify_phase5.py`), `docs/notes/phase-6-infra.md`
- Modify: `docs/05-api-surface.md`, `buildlog.md`
- Test: `backend/tests/test_infra_pve_integration.py` (new, `pve_integration`-marked)

**Interfaces:**
- Consumes: everything Tasks 1-17 produced.
- Produces: nothing further tasks depend on. This task closes the phase.

Doc 10's Phase 6 definition of done has four clauses, and this task proves each
one against a named artifact:

| Clause | Proving artifact |
|---|---|
| "every nav page now renders real content" | `src/tests/{storage,network,backups}.test.tsx` render each page against mocked endpoints and assert real rows; `routes/placeholder.tsx` no longer exists |
| "a VM can be created, snapshotted, rolled back, and cloned from the UI" | `dod_verify_phase6.py` §2 drives all four backend routes end-to-end; `src/tests/{snapshots,vmcreate}.test.tsx` drive the UI halves |
| "a CT backs up to PBS and restores as a new CTID" | `dod_verify_phase6.py` §3 |
| "an ISO uploads through Proxploy" | `dod_verify_phase6.py` §4 |

- [ ] **Step 1: Add the live-PVE-gated integration test**

The same standing limitation every prior phase has stated applies: there is no
live Proxmox host on this box, so the real-PVE proof is written, marked, and
skipped until a disposable PVE exists, exactly the pattern
`tests/test_console_pve_integration.py` and `tests/test_pve_integration.py`
already use.

```python
# backend/tests/test_infra_pve_integration.py
"""Phase 6 against a real, disposable PVE (doc 11 §7 matrix).

Skipped without the PROXPLOY_TEST_PVE_* env triple, like every other
live-PVE test in this repo. What only a real host can prove, and what the
fakes in tests/fakes/pve.py deliberately do not:

- that `/nodes/{node}/storage/{storage}/upload` accepts proxmoxer's
  multipart shape for a real multi-hundred-MB ISO rather than just the
  few-byte payload the fake accepts, and that the UPID it returns
  actually completes;
- that a vzdump of a real CT to a real PBS datastore, and a restore of
  that archive as a NEW ctid, both succeed; the one DoD clause with the
  most moving upstream parts;
- that `/nodes/{node}/network` PUT (apply) behaves as documented on both
  PVE 8.x and 9.x, the single most dangerous call in the phase;
- that prunebackups' dry-run GET really deletes nothing.
"""
import os

import pytest

pytestmark = pytest.mark.pve_integration

_ENV = ("PROXPLOY_TEST_PVE_URL", "PROXPLOY_TEST_PVE_TOKEN_ID",
        "PROXPLOY_TEST_PVE_TOKEN_SECRET")


@pytest.mark.skipif(not all(os.environ.get(k) for k in _ENV),
                    reason="needs a disposable live PVE (PROXPLOY_TEST_PVE_*)")
def test_phase6_against_live_pve():
    pytest.skip("fill in against the disposable PVE fixture once one is "
                "available (doc 11 §7), no live PVE on this box, the "
                "standing limitation every phase has stated")
```

- [ ] **Step 2: Write the DoD verification script**

```python
# backend/dod_verify_phase6.py: run once from backend/, NOT committed
"""Phase 6 DoD verification, doc 10. Uses tests.support.make_app + FakePVE, 
no live PVE, no browser on this box, matching every prior phase's stated
limitation. Proves the three job-shaped DoD clauses end to end through the
real routes, the real JobBackend, and the real audit path."""
import io
import json as jsonlib
import time
from pathlib import Path

from fastapi.testclient import TestClient

from proxploy.models import App, AuditEvent, Backup, HostCredential, Job
from tests.fakes.pve import FakePVE
from tests.support import make_app, seed_host_row, seed_snapshot


def _login(client):
    client.get("/api/v1/meta/health")
    csrf = {"X-CSRF-Token": client.cookies.get("pp_csrf")}
    client.post("/api/v1/users", headers=csrf, json={
        "email": "owner@example.com", "password": "correct-horse-battery",
        "display_name": "Owner"})
    client.post("/api/v1/auth/login", headers=csrf, json={
        "email": "owner@example.com", "password": "correct-horse-battery"})
    return {"X-CSRF-Token": client.cookies.get("pp_csrf")}


def _await(app, job_id, timeout=10.0):
    """Poll the DB until the job leaves a non-terminal state."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with app.state.sessionmaker() as db:
            j = db.get(Job, job_id)
            if j.status in ("succeeded", "failed", "canceled", "interrupted"):
                return j.status, j.error
        time.sleep(0.05)
    return "TIMEOUT", None


def main():
    tmp = Path("/tmp/phase6_dod")
    tmp.mkdir(exist_ok=True)

    fake = FakePVE()
    fake.storages_by_node = {"pve1": [
        {"storage": "local", "type": "dir", "content": "iso,vztmpl,backup",
         "active": 1, "enabled": 1, "shared": 0,
         "used": 5 * 2**30, "avail": 45 * 2**30, "total": 50 * 2**30},
        {"storage": "pbs-datastore", "type": "pbs", "content": "backup",
         "active": 1, "enabled": 1, "shared": 1,
         "used": 80 * 2**30, "avail": 20 * 2**30, "total": 100 * 2**30},
    ]}
    fake.content_by_storage = {
        ("pve1", "local"): [{"volid": "local:iso/debian-12.iso", "format": "iso",
                             "size": 700 * 2**20, "content": "iso", "ctime": 1753800000}],
        ("pve1", "pbs-datastore"): [],
    }
    fake.nextid = 999
    fake.snapshots_by_guest = {("qemu", 200): [
        {"name": "current", "description": "You are here!"},
    ]}

    app = make_app(tmp, fake=fake)

    with app.state.sessionmaker() as db:
        host = seed_host_row(db, name="host-01", node="pve1")
        blob, ver = app.state.secretstore.encrypt(jsonlib.dumps(
            {"token_id": "proxploy@pve!infra", "token_secret": "s3cret"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token",
                              encrypted_blob=blob, key_version=ver))
        ct = App(host_id=host.id, ctid=150, name="immich", slug="immich-1",
                 status_cached="stopped")
        db.add(ct)
        db.commit()
        host_id, app_id = host.id, ct.id

    seed_snapshot(app, host_id, storage=[
        {"storage": "local", "node": "pve1", "type": "dir",
         "content": ["iso", "vztmpl", "backup"], "shared": False, "status": "available",
         "used_bytes": 5 * 2**30, "total_bytes": 50 * 2**30},
        {"storage": "pbs-datastore", "node": "pve1", "type": "pbs",
         "content": ["backup"], "shared": True, "status": "available",
         "used_bytes": 80 * 2**30, "total_bytes": 100 * 2**30},
    ])

    with TestClient(app) as client:
        csrf = _login(client)

        print("\n=== 1. every nav page has a real backing endpoint ===")
        for path in ("/api/v1/storage", "/api/v1/network/bridges",
                     "/api/v1/network/throughput", "/api/v1/backups"):
            r = client.get(path)
            print(f"  GET {path:34s} -> {r.status_code}")
            assert r.status_code == 200, r.text
        rows = client.get("/api/v1/storage").json()
        assert len(rows) == 2 and rows[0]["type"] == "dir", rows
        print(f"  storage rows carry type/content/shared: {rows[0]}")

        print("\n=== 2. VM created, snapshotted, rolled back, cloned ===")
        r = client.post("/api/v1/vms", headers=csrf, json={
            "host_id": host_id, "node": "pve1", "name": "web-01",
            "cores": 2, "memory_mb": 2048, "disk_gb": 32,
            "storage": "local-lvm", "iso": "local:iso/debian-12.iso",
            "bridge": "vmbr0", "ostype": "l26"})
        print("  POST /vms                ->", r.status_code, r.json())
        assert r.status_code == 202, r.text
        vmid = r.json()["vmid"]
        print("  create job:", _await(app, r.json()["job"]["id"]))
        assert vmid == 999, "vmid must come from cluster/nextid"

        # A Vm row for the snapshot/clone routes to address. Proxploy never
        # writes these itself: the poller discovers them, so seed it the way
        # a poll cycle would.
        from proxploy.models import Vm
        with app.state.sessionmaker() as db:
            v = Vm(host_id=host_id, vmid=200, name="win11", status="stopped")
            db.add(v)
            db.commit()
            vm_row_id = v.id

        r = client.post(f"/api/v1/vms/{vm_row_id}/snapshots", headers=csrf,
                        json={"name": "pre-update", "description": "", "vmstate": False})
        print("  POST …/snapshots         ->", r.status_code, r.json().get("job", {}).get("kind"))
        assert r.status_code == 202 and r.json()["job"]["kind"] == "vm.snapshot_create", r.text
        print("  snapshot job:", _await(app, r.json()["job"]["id"]))

        r = client.get(f"/api/v1/vms/{vm_row_id}/snapshots")
        print("  GET  …/snapshots         ->", r.status_code, r.json())
        assert all(s["name"] != "current" for s in r.json()), \
            "PVE's synthetic 'current' pseudo-snapshot must be filtered out"

        r = client.post(f"/api/v1/vms/{vm_row_id}/snapshots/pre-update/rollback",
                        headers=csrf, json={})
        print("  rollback without confirm ->", r.status_code, r.json().get("error"))
        assert r.status_code == 409 and r.json()["error"] == "confirm_required", r.text
        r = client.post(f"/api/v1/vms/{vm_row_id}/snapshots/pre-update/rollback",
                        headers=csrf, json={"confirm": "win11"})
        print("  rollback with confirm    ->", r.status_code)
        assert r.status_code == 202, r.text
        print("  rollback job:", _await(app, r.json()["job"]["id"]))

        r = client.post(f"/api/v1/vms/{vm_row_id}/clone", headers=csrf,
                        json={"name": "win11-copy", "full": True})
        print("  POST …/clone             ->", r.status_code)
        assert r.status_code == 202, r.text
        print("  clone job:", _await(app, r.json()["job"]["id"]))

        print("\n=== 3. CT backs up to PBS and restores as a NEW ctid ===")
        r = client.post("/api/v1/backups/run", headers=csrf, json={
            "guests": [{"type": "ct", "id": app_id}], "storage": "pbs-datastore"})
        print("  POST /backups/run        ->", r.status_code)
        assert r.status_code == 202, r.text
        print("  backup job:", _await(app, r.json()["job"]["id"]))

        # The archive the backup produced, as the next sync would see it.
        volid = "pbs-datastore:backup/vzdump-lxc-150-2026_07_31-02_00_00.tar.zst"
        fake.content_by_storage[("pve1", "pbs-datastore")] = [
            {"volid": volid, "format": "tar.zst", "size": 2 * 2**30,
             "content": "backup", "ctime": 1753920000,
             "verification": {"state": "ok"}}]
        r = client.get("/api/v1/backups")
        print("  GET  /backups            ->", r.status_code, "stale:", r.json()["stale"])
        for _ in range(100):
            with app.state.sessionmaker() as db:
                if db.query(Backup).count():
                    break
            time.sleep(0.05)
        with app.state.sessionmaker() as db:
            b = db.query(Backup).one()
            backup_id, parsed = b.id, (b.guest_type, b.guest_vmid, b.verify_state)
        print("  synced backup row:", parsed)
        assert parsed == ("ct", 150, "ok"), parsed

        r = client.post(f"/api/v1/backups/{backup_id}/restore", headers=csrf,
                        json={"mode": "new"})
        print("  POST …/restore (as new)  ->", r.status_code, r.json())
        assert r.status_code == 202, r.text
        print("  restore job:", _await(app, r.json()["job"]["id"]))
        assert any(c.get("vmid") == 999 for c in fake.creates), \
            f"restore-as-new must mint a fresh vmid from cluster/nextid: {fake.creates}"
        print("  restored to a NEW ctid, source CT 150 untouched")

        print("\n=== 4. an ISO uploads through Proxploy ===")
        payload = b"\x00" * (3 * 1024 * 1024)  # 3 MiB, spills past the spool threshold
        r = client.post(f"/api/v1/storage/{host_id}/local/content", headers=csrf,
                        data={"content": "iso", "node": "pve1"},
                        files={"file": ("debian-12.iso", io.BytesIO(payload),
                                        "application/octet-stream")})
        print("  POST …/content (3 MiB)   ->", r.status_code, r.json())
        assert r.status_code == 202, r.text
        print("  upload job:", _await(app, r.json()["job"]["id"]))
        assert fake.uploads and fake.uploads[-1]["content"] == "iso", fake.uploads
        leftovers = list((Path(app.state.settings.data_dir) / "uploads").glob("*")) \
            if (Path(app.state.settings.data_dir) / "uploads").exists() else []
        print("  temp spool files left behind:", leftovers)
        assert not leftovers, "the upload job must delete its temp file in finally"

        print("\n=== 5. every mutation wrote an audit row ===")
        with app.state.sessionmaker() as db:
            actions = sorted({a.action for a in db.query(AuditEvent).all()})
        print("  audit actions:", actions)
        for expected in ("vm.create", "vm.snapshot_create", "vm.snapshot_rollback",
                         "vm.clone", "backup.run", "backup.restore", "storage.upload"):
            assert expected in actions, f"{expected} missing from {actions}"

    print("\nPROVED: all four doc-10 Phase 6 DoD clauses, through the real "
          "routes, the real JobBackend and the real audit path.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run it and keep the real output**

Run: `cd backend && ./.venv/bin/python dod_verify_phase6.py`
Expected: every assertion passes and the script ends with the `PROVED:` line. Paste the **actual** output into the notes doc in Step 5, not a reconstruction of it. If a clause fails, fix the code, not the script.

- [ ] **Step 4: Run every suite and gate**

Run: `cd backend && ./.venv/bin/python -m pytest tests/ -q -m "not pve_integration and not e2e"`
Expected: Phase 5's 340 passed plus every test this plan added, zero failures. The new `pve_integration` test raises the deselected count from 3 to 4.

Run: `cd backend && ./.venv/bin/python scripts/check_executor_isolation.py`
Expected: `executor isolation: OK`, unaffected by this phase, which never touches SSH.

Run: `cd backend && ./.venv/bin/pip-licenses --partial-match --ignore-packages proxploy --allow-only "MIT;MIT License;BSD;BSD License;Apache;Apache Software License;ISC;Python Software Foundation;PSF-2.0;PostgreSQL;Public Domain;Mozilla Public License 2.0;Eclipse Public License v2.0;EPL-2.0;The Unlicense;CMU License (MIT-CMU)"`
Expected: exits 0 with `python-multipart` (Apache-2.0) now in the tree.

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_migrations.py -q`
Expected: PASS, and **head is still `2330a95b98d2`**; this phase adds no migration. Confirm with `./.venv/bin/python -m alembic -c alembic.ini heads`.

Run: `cd frontend && npx vitest run && npm run build && npm run lint`
Expected: Phase 5's 71 passed plus this plan's frontend tests, a clean `tsc -b && vite build`, and clean oxlint.

- [ ] **Step 5: Amend doc 05 with the endpoints this phase actually shipped**

`docs/05-api-surface.md` is the API contract and is now out of date in three
ways this phase discovered. Fix it rather than leaving the next phase to trip
over it:

1. **§Network is missing the guest- and host-config endpoints entirely.** It lists only `/network/bridges` and `/network/throughput`, but doc 01 §6 defines `network.guest_config` and `network.host_config` as real features and doc 10 puts both in Phase 6. Add the rows for `GET|PUT /{apps|vms}/{id}/network[/{iface}]`, `POST /network/bridges`, `PUT|DELETE /network/bridges/{hostId}/{node}/{iface}`, and `POST /network/{hostId}/{node}/apply|revert`, with the roles and entitlement keys the routes actually enforce.
2. **The entitlement column is blank on six read endpoints that this phase gates** (`GET /storage`, `/storage/{h}/{n}`, `/storage/{h}/{n}/content`, `/network/bridges`, `/network/throughput`, `/vms/{id}/snapshots`). Fill in `storage.view`, `storage.content`, `network.view` and `vms.snapshots` per doc 01, and add a one-line note under §Conventions recording that a blank entitlement column means "never gated" and that these were blanks-by-omission, corrected in Phase 6.
3. **§Backups is missing `GET /backups/prune-preview` and `POST /backups/prune`**, both of which Phase 6 ships (`backups.retention`).

- [ ] **Step 6: Write `docs/notes/phase-6-infra.md`**

Follow `docs/notes/phase-5-console.md`'s exact structure: "What shipped, per
subsystem", a DoD verification map table (clause | proving artifact | verdict)
covering all four doc-10 clauses, the **real** command output from Steps 3-4,
and a "What was NOT verified" section. That last section must name, at minimum:

- **No live Proxmox host**: every PVE interaction in this phase was proved against `tests/fakes/pve.py`, not a real API. `tests/test_infra_pve_integration.py` is the placeholder for when one exists. This is the standing limitation every phase since Phase 1 has stated, and it bites hardest here: this is the first phase whose operations **write** to storage, network and guest configuration rather than reading them.
- **No browser**: the three new pages and four new dialogs are proved by jsdom render tests, not by a human or a headless browser looking at them. Layout, the 80%-usage red bar, and the LockVeil visuals are unverified visually.
- **The host-network apply path is the highest-risk unverified code in the product.** A wrong bridge config applied to a node can permanently cut that node off the network, and no fake can prove PVE's real apply/revert semantics. Say so plainly.
- **The ISO upload double-transfers** (browser → Proxploy → PVE) and needs transient disk on the Proxploy host equal to the file size; the cap is `storage_upload_max_bytes`. Only a 3 MiB payload was exercised, never a real multi-GB ISO.
- **Two endpoints ship unconsumed by the UI** (`POST /backups/prune`, and the `vmstate` option on non-qemu guests), deliberately, per the plan's cross-task couplings note.
- **`GET /backups` auto-enqueues a sync when the cache is stale**, so the first load of a fresh install returns an empty list and fills in moments later; correct, but a behaviour worth knowing before someone reports it as a bug.

- [ ] **Step 7: Update `buildlog.md`**

Append a `### <ISO timestamp>, Phase 6, execute-plan completed` entry matching
Phases 2/3/4/5's format exactly: plan path, what was built per subsystem,
verification counts (backend passed/skipped/deselected, frontend passed/files),
and a **Deviations** paragraph. The deviations that must appear, because each is
a real departure from what the plan or the docs said at the start:

- Phase 6 shipped **one** new backend dependency (`python-multipart`), not zero; the plan's own header claim was wrong and was corrected in Task 4 Step 0 after verifying FastAPI refuses to define an `UploadFile` route without it.
- Phase 6 shipped **zero Alembic migrations**, as planned; the `backups` table and every column used had existed unused since migration 0001.
- Doc 05 was amended (Step 5) for three omissions this phase surfaced.
- The staged-network-changes indicator was deliberately not built: proxmoxer's `.get()` unwraps only the `data` key and drops the sibling `changes` property, so Apply/Revert are always offered rather than guessing at pending state.
- Linked-clone validity is not pre-checked, Proxploy does not track template-ness, so PVE's rejection is surfaced verbatim.
- Anything the per-task reviews parked, carried forward by name.

- [ ] **Step 8: Commit**

```bash
git add docs/notes/phase-6-infra.md docs/05-api-surface.md buildlog.md \
        backend/tests/test_infra_pve_integration.py
git commit -m "docs(phase-6): DoD verification notes, doc-05 amendment, buildlog entry"
```

`backend/dod_verify_phase6.py` is deliberately **not** added; it is a
throwaway verification script, exactly like `dod_verify_phase5.py`, which is
still sitting untracked in the working tree from the previous phase.

---

