# Proxploy: Build Sequence

Doc 10. Expands brief §10. Subordinate to `00-decision-brief.md`.

**Governing rule: phases are dependency order, never scope cuts.** Every phase
exists because later work needs it, not because earlier features are "the MVP."
The product is complete only when Phase 9 lands; nothing in Phases 1–8 is a
shippable subset we would stop at. Feature keys referenced below are defined in
doc 01.

Repo placement: all Phases 1–8 work lands in **proxploy-app** (`backend/`,
`frontend/` per doc 09). **proxploy-api** gets its dormant
resolver in Phase 1 and its production hardening in Phase 9. **proxploy-web**
and **proxploy-docs** land in Phase 9, with docs drafted incrementally from
Phase 4 onward (each phase's DoD includes doc notes so Phase 9 is assembly,
not archaeology).

---

## Phase 1: Foundation

**Builds**

- Repo scaffolds for all four properties: proxploy-app (FastAPI + Uvicorn +
  SQLAlchemy 2/Alembic backend; React 19 + Vite + Tailwind v4 + shadcn/ui +
  TanStack Query/Router frontend with the prototype's design tokens ported),
  proxploy-api (FastAPI), proxploy-web and proxploy-docs (empty scaffolds,
  content deferred to Phase 9).
- DB bootstrap: SQLite-WAL default, Postgres via DSN, Alembic migration 0001
  with the full entity list from brief §9 growing per phase.
- AuthN: local accounts (argon2-cffi), server-side DB sessions, CSRF
  middleware, per-IP rate limiting on auth endpoints. Endpoints:
  `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`, `GET /api/v1/auth/me`,
  `POST /api/v1/users` (admin).
- SecretStore: Fernet/MultiFernet, master key file created root-only at
  install, get/put/rotate seam.
- Entitlements client: `Entitlements.enabled(key)`, built-in all-on default
  map, disk token cache, Ed25519 JWT verification (PyJWT), background refresh
  loop; FastAPI dependency + frontend `GET /api/v1/entitlements`. **All 81 flags
  from doc 01 §17 registered now**, all ON.
- proxploy-api dormant resolver: `POST /v1/licenses/activate` +
  `POST /v1/entitlements/refresh` (contract in docs 07/09) returning
  "all entitled" signed tokens; Ed25519 keypair generated, private key held on
  the hosted side only, public key bundled into proxploy-app.
- Host onboarding: `POST /api/v1/hosts` (URL, scoped API token, TLS fingerprint
  pin, connectivity check via proxmoxer), optional SSH ed25519 key enrolment
  with explicit consent copy; credentials stored via SecretStore.
- Audit log: `audit_events` table, append-only write helper wired into every
  state-changing route from day one; `GET /api/v1/audit`.
- Settings service + page skeleton; onboarding wizard v1 (admin account →
  first host); app shell UI: sidebar with the fixed nav, topbar, theme tokens,
  dark/light switch.
- proxploy-api `licenses` + `issued_tokens` tables (Alembic, doc 07); 
  created now even though nothing is sold yet; not deferred.
- **Test infrastructure (Phase 1 deliverable, not deferred to "later"):**
  (a) a proxmoxer fake/fixture layer (recorded fixtures + a lightweight fake
  PVE responder) so unit tests and most day-to-day development run with
  **no live PVE**; (b) an integration test path against a **disposable PVE**
  wired into CI for the PVE 8.latest/9.latest matrix (doc 11 §7); (c) an
  **app-to-api entitlement contract test**, wired into both proxploy-app and
  proxploy-api CI from day one, asserting each repo's token
  (de)serialization matches the shared fixture in doc 09's contract
  section, fails loudly on drift instead of silently at runtime.

**Depends on**: nothing. **Unblocks**: everything.

**Definition of done**

- Fresh install: wizard creates admin, adds a real PVE host with a scoped
  token, connectivity check passes, credentials round-trip encrypted.
- Every subsequent route template already runs through auth, RBAC stub,
  audit, and an entitlement check.
- `Entitlements.enabled()` verifies a token signed by the dormant
  proxploy-api and falls back to the built-in map offline.
- Alembic migrates SQLite and Postgres from empty to current.
- The proxmoxer fake/fixture layer and the app-to-api entitlement contract
  test both run in CI; the disposable-PVE integration path is wired (the
  PVE 9 leg can be added incrementally through Phase 2 if needed).

## Phase 2: Observe

**Builds**

- Poller subsystem: per-host asyncio poll loops (30s) via proxmoxer, 
  nodes, CT/VM status, storage capacity, network counters.
- MetricsStore: `metric_samples` writes, 5m/1h rollup jobs, retention
  pruning; query API for range charts.
- Read-only caches: `apps` identity mapping (host, ctid) with adoption
  heuristics run against discovered CTs, `vms` cache, storage/network
  snapshots.
- Pages (read-only): **Cluster** (rings, node cards, live badge), node
  detail, **Apps** grid, **Virtual Machines** table, app/VM detail overview
  tabs with uPlot graphs. SSE endpoint for cache invalidation feeding
  TanStack Query.
- Endpoints: `GET /api/v1/cluster/summary`, `GET /api/v1/cluster/nodes`,
  `GET /api/v1/apps`, `GET /api/v1/vms`, `GET /api/v1/metrics/query`,
  `GET /api/v1/events/stream` (SSE).

**Depends on**: Phase 1 (hosts, secrets, auth). **Unblocks**: every page
that shows state; alerting; graphs.

**Definition of done**: dashboard reflects a real multi-host lab live
(≤35s staleness); apps and VMs discovered and rendered; charts show 24h of
history from rollups; a killed host degrades to "unreachable" without
breaking the UI.

## Phase 3: Act

**Builds**

- JobBackend: in-process asyncio runner, `jobs` + `job_events` persistence,
  enqueue/status/cancel, SSE log streaming (`GET /api/v1/jobs/{id}/events/stream`),
  job history API/UI.
- Lifecycle actions for apps and VMs: start/stop/shutdown/restart/
  pause/resume via proxmoxer, each as a job, each audit-logged, each behind
  its flag and RBAC check. Endpoints: `POST /api/v1/apps/{id}/start|stop|restart`,
  `POST /api/v1/vms/{id}/start|stop|restart|pause`.
- Activity feed on the dashboard fed from jobs + audit.
- Notifications: Apprise-backed Notifier, `notification_channels` CRUD +
  test-send, in-app toast/bell surface, job-result events routed.

**Depends on**: Phase 2 (caches to act on, SSE plumbing). **Unblocks**, 
installs (Phase 4), backups/schedules (6–7), migration (8): everything
state-changing rides JobBackend.

**Definition of done**: start/stop/restart from Apps and VMs pages works
end-to-end with optimistic UI + reconciliation; a cancelled job stops
cleanly; every action appears in audit and the feed; a Telegram/ntfy channel
receives a job-failure notification.

## Phase 4: Store

**Entry gate**: before install-executor work begins, the non-root/
API-first install spike (doc 08 §4, doc 11 §1) is resolved and its finding
written down: either community-scripts tooling exposes an API-drivable
install path that reduces or removes the need for root SSH, or; the
expected outcome, raw SSH-root is confirmed necessary and `SSHExecutor`
below proceeds as designed. This is a documented finding, not a
research-project blocker, but Phase 4 does not start executor work without it.

**Builds**

- CatalogSource: server-side fetch of community-scripts/ProxmoxVE metadata,
  ETag-cached in `catalog_entries`, manual + scheduled refresh, license
  check recorded at import, install-feasibility classifier setting
  `installable` / `unsupported_reason` per entry (doc 01 §3, doc 04).
- **App Store** page: tile grid of installable entries (unsupported entries
  shown separately with an honest note + upstream link), categories, search,
  detail drawer with script content, resource defaults, upstream link.
- Install executor: asyncssh runner using the enrolled ed25519 key; script
  content pinned into `app_scripts`, diff-vs-upstream shown pre-run;
  explicit root-consent step in the install flow; full output streamed via
  job SSE and archived in `job_events`. `POST /api/v1/catalog/{slug}/install`.
  Highest test-coverage bar in the repo applies here (doc 08 §4, doc 09); 
  unit tests plus integration tests against a throwaway PVE, backed by the
  CI import-graph check that blocks any non-`executor/` module from
  touching the SSH client.
- App ↔ CT adoption for pre-existing containers (`apps.adopt`): the
  discovered-but-unadopted panel on the Apps page (`GET /api/v1/apps/discovered`)
  plus bulk adopt (`POST /api/v1/apps/adopt`) with catalog-match suggestions
  (doc 06).
- Install-script view/edit on app detail (versioned local variants).

**Depends on**: Phase 3 (JobBackend + streaming), Phase 1 (SSH enrolment,
audit). **Unblocks**: updates and auto-updates (Phase 7); app config tab
(Phase 5 polish).

**Definition of done**: a real app (e.g. Immich) installs from the store
onto a chosen host as exactly one CT, with live log, archived log, audit
row, and consent step; catalog survives upstream being unreachable (serves
cache with staleness banner); an edited script shows its diff against
upstream before every run; the store reports the **true installable count**
from the classifier, no "300+ scripts" placeholder, with unsupported
entries counted and shown separately; a host with pre-existing CTs shows
them in the discovered panel and bulk-adopts cleanly.

## Phase 5: Console

**Builds**

- PtyBridge: backend websocket proxy to Proxmox `termproxy` for CT consoles
  and node shells, authenticated by Proxploy session, audit-logged.
- xterm.js terminal component; Console tab on app detail; node shell from
  node detail.
- ConsoleProxy: noVNC via `vncproxy` + `vncwebsocket` for VM consoles;
  Console tab on VM detail.
- Logs tabs finalized: live-follow CT logs and archived job logs share one
  log-viewer component.

**Depends on**: Phase 2 (detail pages), Phase 1 (auth on websockets).
**Unblocks**: nothing hard-blocks on it; sequenced here because install
debugging (Phase 4 output) makes consoles immediately valuable.

**Definition of done**: CT terminal, node shell, and VM noVNC session all
work through the Proxploy origin only (no direct-to-PVE browser
connections), survive reconnect, and write audit rows on open.

## Phase 6: Infra pages

**Builds**

- **Storage** page: datastore cards/usage, content browser (ISOs,
  templates, backups, images), ISO/template upload, add/edit storage.
- **Network** page: bridges/bonds/VLANs/NICs per node, guest attachment
  map, live throughput sparklines, guest NIC editing, host bridge/VLAN
  editing with apply confirmation.
- **Backups** page: PBS datastore connect, backup group/snapshot browser
  with verify status, run-now backup, restore (in place or as new ID),
  retention/prune view.
- VM snapshots (list/create/rollback/delete), VM create wizard, VM clone.

**Depends on**: Phase 3 (jobs for uploads/backups/restores/creates),
Phase 2 (storage/network caches). **Unblocks**: scheduled backups
(Phase 7), non-clustered migration (Phase 8, which is restore + transfer).

**Definition of done**: every nav page now renders real content; a VM can
be created, snapshotted, rolled back, and cloned from the UI; a CT backs up
to PBS and restores as a new CTID; an ISO uploads through Proxploy.

## Phase 7: Operate

**Builds**

- Update pipeline: per-app update, update-all queue with per-app results; 
  same pin/diff/consent/stream/archive path as install.
- Scheduler (APScheduler 3.11) in production: `schedules` CRUD + UI for
  auto-update windows, scheduled backup jobs, catalog refresh, metric/audit
  pruning. **Amendment, Phase 7, 2026-08-01, see `docs/notes/phase-7-operate.md`:**
  this said "APScheduler 4"; no 4.x release exists, PyPI's maximum stable is
  3.11.3 (verified 2026-08-01).
- Alerting: `alert_rules` CRUD + evaluator riding the poll loop, firing/
  resolved/acknowledge lifecycle, alert history, routing through Notifier;
  event-class → channel routing UI.

**Depends on**: Phase 4 (update executor), Phase 6 (backup jobs),
Phase 3 (Notifier), Phase 2 (metrics for rules). **Unblocks**: nothing
downstream; this is the "runs itself" layer.

**Definition of done**: an unattended weekend: scheduled backups and an
auto-update window run, an induced CPU alert fires and resolves with
notifications both ways, and Monday's job history tells the whole story.

## Phase 8: Scale

**Builds**

- OIDC login (Authlib) + TOTP (pyotp) with recovery codes.
- RBAC completed: pycasbin policies on every route (owner/admin/operator/
  viewer), Teams as casbin domains with host/app/VM scoping, team admin UI.
- API tokens: scoped, revocable, hashed at rest; OpenAPI surface audited so
  the full REST API (`/api/docs`) covers everything the UI does.
- Cross-host migration: preflight (capacity, storage/network mapping,
  size/time estimate) → cluster-native `migrate` when hosts share a
  cluster; PBS backup/restore or vzdump+transfer path when they don't, with
  explicit downtime messaging (doc 11 §2).

**Depends on**: Phase 1 (auth seams), Phase 6 (backup/restore machinery
that migration reuses), Phase 3 (jobs). **Unblocks**: Deliver.

**Definition of done**: a viewer cannot mutate anything (verified by
test-suite against every route); OIDC round-trips against a real Authelia;
an app migrates between two *non-clustered* hosts via the backup/restore
path with accurate downtime shown; a CI script drives the product entirely
through token-authed REST.

## Phase 9: Deliver

**Builds**

- Installers: one-line LXC installer, Docker/Compose, systemd unit, Caddy
  TLS (arm's-length) with self-signed fallback; locked-down defaults (LAN
  bind, TLS on).
- Self-update: in-app check + apply with pre-update DB backup, versioned
  migration, rollback path (failure modes in doc 11 §10).
- Onboarding wizard polish to the full flow (admin → host → TLS → land on
  Cluster), empty states, error states, light-theme QA pass.
- proxploy-api production hardening: rate limiting, key rotation runbook,
  monitoring, still resolving "all entitled."
- **proxploy-web**: marketing/landing/download site. **proxploy-docs**:
  install, host onboarding + minimal-privilege token guide, trust model
  (root-on-node stated plainly), API reference from OpenAPI, per-feature
  guides assembled from Phases 4–8 notes.
- Opt-in error reporting (off by default, never on the entitlement path).

**Depends on**: everything. **Unblocks**: launch.

**Definition of done**: a stranger installs via the one-liner on a clean
PVE box, completes onboarding, installs an app, creates a VM, schedules a
backup, and self-updates to the next tagged release; without reading
source code. All four properties are live. Every doc-01 feature is
reachable, flagged, and ON.

---

## Sequence at a glance

| # | Phase | Hard dependencies | Headline deliverable |
|---|---|---|---|
| 1 | Foundation | n/a | Auth, secrets, entitlements (dormant), host onboarding, audit |
| 2 | Observe | 1 | Live read-only Cluster/Apps/VMs + metrics |
| 3 | Act | 2 | JobBackend, lifecycle, notifications |
| 4 | Store | 3 | Catalog + consented root installs with streamed logs |
| 5 | Console | 2 | CT/node terminals, VM noVNC |
| 6 | Infra pages | 3 | Storage, Network, Backups, VM snapshots/create/clone |
| 7 | Operate | 4, 6 | Updates, schedules, alerting |
| 8 | Scale | 1, 3, 6 | OIDC/TOTP, RBAC/teams, API tokens, migration |
| 9 | Deliver | all | Installers, self-update, web + docs, launch |
