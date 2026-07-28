# Proxploy — Decision Brief (source of truth for all planning docs)

Date: 2026-07-28. Status: brainstorm output, pending review by Aasim.
Every other document in `/docs` must agree with this brief. If a doc needs to
contradict it, the brief changes first. Docs 01–11 refine this brief where it
permits (e.g. doc 01's inert Core tier, doc 07's fail-closed unknown flags,
doc 02's interrupted-not-resumed jobs, doc 05's `/api/v1` prefix); those
refinements live in the topic docs.

## 1. What Proxploy is

A self-hosted, web-based management platform for Proxmox VE — "Unraid's
experience, but for Proxmox." One pane over one or many Proxmox hosts. LXC
containers are presented as **Apps** (install from a store, open web UI,
start/stop/restart, logs, console, edit install script), never as a raw
CT list. `proxploy-prototype.html` is the source of truth for layout, nav,
pages, interactions, and design tokens.

## 2. Hard product rules (from the kickoff — restated, non-negotiable)

1. **Apps-only model.** Primary workload view is Apps. One app = exactly one
   CT, even multi-service apps (Immich = one CT, one tile). Nav: Cluster,
   Apps, App Store, Virtual Machines, Storage, Network, Backups, Settings.
2. **App Store = community-scripts/ProxmoxVE**, fetched and cached through
   our backend (never browser-direct; CORS + rate limits).
3. **Whole product, not an MVP.** Phases are a dependency-ordered build
   sequence, never scope cuts.
4. **Reuse over reinvention.** Every subsystem adopts mature OSS unless we
   can show none fits; custom code must be justified explicitly. Never
   hand-roll cryptography.
5. **Feature-gate everything from day 0, dormant.** One central entitlement
   client; hosted proxploy-api resolves entitlements; default state of every
   flag is ON (unarmed). Arming Pro tiers later is a config change on
   proxploy-api, never a refactor.
6. **Security posture non-negotiable:** scoped API tokens (never root@pam
   password auth), credentials encrypted at rest, append-only audit log,
   locked-down defaults, TLS by default, honest trust model, a
   self-management guardrail (Proxploy refuses, or requires typed
   confirmation with an explicit warning for, destructive actions against
   its own CT/host — doc 02 §9, doc 08), and hard executor isolation: no
   module outside `executor/` may import the SSH client or retrieve the SSH
   key, enforced in CI, not by convention alone (doc 08 §4, doc 09).

## 3. Licensing discipline

- Permissive (MIT/BSD/Apache-2.0/ISC, MPL-2.0 at file level): port or link freely.
- Copyleft (GPL/LGPL/AGPL): arm's-length only (separate process, network/CLI).
  Never copy copyleft source into Proxploy. Proxmox itself (AGPL) is talked to
  over HTTP only.
- Non-OSS (BUSL/SSPL): never linked. Vault is BUSL → use OpenBao if a full
  secrets manager is ever needed.
- Every dependency row in doc 03 records: project, purpose, license, reuse
  mode (port / link / arm's-length), locked vs provisional. Licenses must be
  re-verified against the source repo at implementation time; the table marks
  each license as "verified <date>" or "verify before install."

## 4. Locked spine (decided now, expensive to change, defended)

| Layer | Choice | License | Why |
|---|---|---|---|
| Backend language | Python 3.12+ | — | We already own a proxmoxer-based engine; the whole reuse story (Apprise, APScheduler, pycasbin, Authlib) is Python-native. |
| Web framework | FastAPI + Uvicorn + Pydantic v2 | MIT/BSD | Async-first (polling many hosts, streaming logs), OpenAPI docs for free (deliverable: full REST API), the default modern Python stack. |
| ORM / migrations | SQLAlchemy 2.x + Alembic | MIT | Boring, universal, supports both target DBs. |
| Database | SQLite (WAL) default; Postgres optional via DSN | PD/PostgreSQL | Self-hosters get zero-dependency install; larger installs flip a connection string. Schema stays in the portable subset of both. |
| Proxmox client | proxmoxer | MIT | Already ours in production use; thin, maintained, token-auth support. `backend/proxploy/services/proxmox.py` adapts the existing lab-cluster-deploy proxmoxer module (CT lifecycle, cluster/node/guest reads, migration calls) rather than being written from scratch; all PVE-8-vs-9 branching is isolated to that one layer (doc 02 §4, doc 03). |
| Frontend | React 19 + TypeScript + Vite | MIT | Biggest ecosystem for the hard UI pieces we must reuse: xterm.js wrappers, noVNC integration, TanStack Query for polling/streaming cache. |
| UI layer | Tailwind CSS v4 + shadcn/ui (Radix primitives) | MIT | shadcn components are copied in and styled entirely by our tokens — exactly right for reproducing the prototype's bespoke dark-console look instead of fighting a themed kit. |
| Data/state | TanStack Query (server state) + TanStack Router | MIT | Query's cache + refetch model maps 1:1 onto "live" dashboards fed by polling + SSE invalidation. |

Vue 3 was the runner-up for frontend; rejected only because the console/VNC/
terminal reuse targets and component ecosystem are deeper on React, and the
prototype's design tokens port identically to either.

## 5. Provisional leaves (leading candidate now, swappable seam named)

| Subsystem | Leading candidate | License | Seam (interface to code against) |
|---|---|---|---|
| Task/job engine | Custom in-process asyncio runner, jobs persisted in DB | n/a (ours) | `JobBackend` — enqueue/status/cancel/log-stream. Justification for custom: every mature Python queue (Celery, RQ, arq, Huey-redis) wants a broker; our default install is single-process + SQLite and needs live log streaming, which brokers don't give us anyway. Swap to Celery/Redis behind the seam if multi-worker ever matters. |
| Scheduling | APScheduler 4 | MIT | `Scheduler` — cron-like triggers feeding JobBackend. |
| Notifications | Apprise | BSD-2 | `Notifier` — one `notify(event, targets)` call; Apprise covers ntfy, gotify, email, Telegram, Slack, webhooks in one dependency. Strongest single reuse win in the plan. |
| Web terminal | xterm.js frontend; backend bridges Proxmox `termproxy` websockets (CT + node shell) | MIT | `PtyBridge`. No SSH needed for consoles — Proxmox's own API provides the PTY websocket; we proxy it with auth. |
| VM console | noVNC via Proxmox `vncproxy` + `vncwebsocket` | MPL-2.0 (link, don't port) | Same `ConsoleProxy` seam; Guacamole (Apache-2.0) is the heavier swap-in if SPICE/RDP demand appears. |
| Secrets at rest | `cryptography` Fernet (MultiFernet for rotation), master key in a root-only file created at install | Apache/BSD | `SecretStore` — get/put/rotate. OpenBao (MPL-2.0) is the arm's-length swap-in for teams that want external KMS. No hand-rolled crypto anywhere. |
| AuthN | Local: argon2-cffi + server-side DB sessions. OIDC: Authlib. TOTP: pyotp | MIT/BSD | `AuthProvider`. External IdP (Authelia/Keycloak) supported *through* OIDC, never bundled. |
| AuthZ / RBAC | pycasbin, RBAC model with domains (teams) | Apache-2.0 | `Authorizer.check(user, resource, action)`. Roles: owner, admin, operator, viewer. |
| Entitlements | Custom thin client (OpenFeature-shaped API), tokens verified with PyJWT EdDSA | MIT deps | `Entitlements.enabled(key)` — see §7. Unleash/Flagsmith rejected: they solve ops-side flag *management*; our problem is offline-verifiable *licensing*, which they don't do. |
| Metrics store | Own tables in the app DB: raw samples (30s poll) + 5m/1h rollups, retention-pruned | n/a | `MetricsStore` write/query. VictoriaMetrics (Apache-2.0) arm's-length swap-in for big fleets. Charts: uPlot (MIT). |
| Reverse proxy / TLS | Caddy, arm's-length process managed by the installer | Apache-2.0 | Installer artifact only; app also serves plain HTTP behind it and can do self-signed TLS itself via `cryptography` if Caddy is declined. |
| Catalog source | community-scripts/ProxmoxVE JSON metadata, fetched server-side, cached in DB with ETag refresh | MIT (verify at import; we consume metadata + call their install entrypoints, we do not vendor their code) | `CatalogSource`. Optional Aspyre-hosted mirror is a dumb CDN concern, separate from proxploy-api; app always falls back to fetching upstream directly. |

## 6. Service topology (four properties)

- **proxploy-app** — the only thing users install. Backend + frontend +
  installer; optional agent is a later pluggable add-on, agentless is default.
- **proxploy-api** — Aspyre-hosted licensing/entitlement API (FastAPI too).
  Never bundled. The app calls it only for entitlement refresh — no
  analytics, no telemetry on this path.
- **proxploy-web** — proxploy.com marketing/landing/download.
- **proxploy-docs** — documentation site.

## 7. Entitlement architecture (day-0, dormant)

- App-side: one `Entitlements` service. Every gated feature calls
  `enabled("domain.feature")`; backend enforces via decorator/dependency,
  frontend gets the resolved flag map from `GET /api/v1/entitlements` (UI hides
  or veils, server always re-enforces).
- Flag keys are dotted, namespaced by domain: `hosts.multi`,
  `apps.lifecycle`, `apps.console`, `store.install`, `store.auto_update`,
  `vms.console`, `migrate.cross_host`, `backups.pbs`, `alerts.rules`,
  `auth.oidc`, `teams.rbac`, `api.tokens`, … (full catalogue in doc 01, one
  flag per feature).
- Token format: JWT signed **EdDSA/Ed25519** (PyJWT), Aspyre private key on
  proxploy-api, public key bundled in the app. Claims: `sub` (license id),
  `tier`, `features` (map), `iat`, `exp` (~72 h), `grace_until` (~30 d).
  App refreshes in the background, caches the token on disk, and validates
  **offline** until `grace_until`. Transient network failure never locks a
  paying user out.
- **No license configured → built-in default feature map, zero network
  calls, forever.** The free tier works fully air-gapped. During the dormant
  phase the built-in default map = *everything on*; proxploy-api likewise
  resolves "all entitled." The tier→features mapping is a config artifact on
  proxploy-api, inert until we decide to sell.

## 8. Trust model and script execution (the honest part)

- **Read/lifecycle/console/backup operations:** Proxmox API with a scoped
  API token per host (documented minimal privilege set, e.g. VM.*, 
  Datastore.*, Sys.Audit + Sys.Console as needed). Never root@pam password.
- **App Store installs are different.** Community scripts create CTs by
  running bash *as root on the PVE node*; the Proxmox HTTP API deliberately
  has no "run arbitrary host command." Agentless default: **SSH to the node
  with a dedicated ed25519 key** (asyncssh — **verified EPL-2.0** (dual-licensed
  EPL-2.0 OR GPL-2.0-or-later) 2026-07-28 at v2.24.0, doc 03's license
  table and verification protocol; acceptable as an unmodified linked
  dependency, never ported. If a future relicense makes EPL-2.0 unacceptable
  as a linked dependency, the fallback is invoking the system `ssh` binary at
  arm's length; paramiko is rejected — LGPL) that the user authorizes during
  host onboarding, used *only* by the install/update/migration executor, with
  every invocation audit-logged and its full output streamed + archived.
  Before Phase 4 commits further engineering to this design, a spike checks
  whether current community-scripts tooling exposes a non-interactive or
  API-drivable install path that would reduce or remove the need for root
  SSH — a Phase 4 entry gate, not an afterthought (doc 08 §4, doc 11 §1). The
  plan says this plainly: App Store install = root on your node, exactly
  like running the script yourself; Proxploy adds streaming, logging, and
  provenance (script content pinned + diffed against upstream before each
  run), not magic sandboxing.
- The **optional agent** (later, pluggable, same executor interface) removes
  the SSH requirement for shops that prefer an outbound-only daemon; it is
  not in the default path and nothing else may depend on it.
- Everything state-changing writes an append-only `audit_events` row
  (actor, action, target, params, result, timestamp).
- Ship locked down: binds to LAN by default, real session auth, CSRF,
  per-IP rate limiting on auth endpoints (slowapi or starlette middleware),
  TLS on by default (Caddy or self-signed), no telemetry.

## 9. Data model — entity list (doc 04 owns the full schema)

users, sessions, api_keys, teams, team_members, casbin_rules,
hosts, host_credentials (encrypted blobs), apps, app_scripts (saved/edited
community script per app, versioned), vms (cache), catalog_entries (cache),
jobs, job_events (log lines/progress), schedules, notification_channels,
alert_rules, alerts, metric_samples, metric_rollups, backups (cache),
audit_events, entitlement_cache, settings.

Conventions: integer PKs, `created_at/updated_at` UTC, soft caches of
Proxmox state are clearly named as caches (Proxmox stays the source of truth
for infra state; Proxploy owns app identity: app ↔ (host, ctid) mapping,
script, metadata).

## 10. Build sequence (doc 10 owns detail; dependency order, not scope cuts)

1. **Foundation** — repo scaffolds (all four properties), auth + sessions,
   SecretStore, Entitlements client + dormant proxploy-api, host onboarding
   (token + SSH key), audit log, settings. Unblocks everything.
2. **Observe** — pollers, MetricsStore, Cluster/node overview, Apps + VMs
   read-only views, dashboard.
3. **Act** — JobBackend, lifecycle actions (start/stop/restart/pause),
   activity feed, notifications (Apprise).
4. **Store** — catalog fetch/cache, App Store UI, install executor with live
   streamed logs, app↔CT adoption of existing CTs.
5. **Console** — xterm.js terminals (CT + node), noVNC for VMs, logs tabs.
6. **Infra pages** — Storage, Network, Backups (PBS), VM snapshots/create/clone.
7. **Operate** — updates (per-app / update-all), APScheduler windows,
   alert rules, scheduled backups.
8. **Scale** — OIDC + TOTP, RBAC/teams, full REST API keys, cross-host
   migration (cluster-native + non-clustered backup/restore path).
9. **Deliver** — one-line LXC installer, Docker/Compose, systemd, Caddy TLS,
   self-update, onboarding wizard polish, proxploy-web + proxploy-docs
   content, opt-in error reporting.

## 11. Open risks (doc 11 owns detail)

Script execution requires node root (mitigations, not sandboxing theater) ·
cross-host migration without a cluster (backup/restore via PBS or
vzdump+rsync; slower, needs honest UX) · SSH-vs-agent trade-off ·
SQLite write contention under heavy metrics (rollups + WAL mitigate; seam to
Postgres/VictoriaMetrics) · community-scripts upstream drift/licensing ·
free-rider risk on entitlements (self-hosted apps can be patched; we accept
this, the moat is hosted-signed tokens + honesty, not DRM).

## 12. Documentation set

00 this brief · 01 product spec · 02 system architecture · 03 technology +
dependency map · 04 data model · 05 API surface · 06 frontend spec ·
07 entitlement architecture · 08 security + secrets design · 09 repository
structure · 10 build sequence · 11 risks + open decisions.
