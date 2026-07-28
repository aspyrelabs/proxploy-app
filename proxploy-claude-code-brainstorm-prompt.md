# Claude Code kickoff prompt — Proxploy

Paste everything below the line into Claude Code. Have `proxploy-prototype.html` (the clickable mockup) and `proxploy-dashboard.html` in the working directory first, and point Claude Code at them.

---

Use your `/brainstorm` skill to produce a complete, buildable plan for a product called **Proxploy** before writing any application code. Do not scaffold or code yet. The output of this session is a set of planning documents I will review and then greenlight for implementation.

## What Proxploy is

Proxploy is a self-hosted, web-based management platform for Proxmox VE. Think "Unraid's experience, but for Proxmox." It gives a single pane over one or many Proxmox hosts, and it treats LXC containers as **Apps** the way Unraid treats Docker containers as apps: install from a store, launch the web UI, start/stop/restart, view logs, open a console, and edit the underlying install script, all without touching the Proxmox admin UI.

The clickable mockup `proxploy-prototype.html` is the **source of truth for layout, navigation, page set, interactions, and visual design language.** Open it, click through every page, and treat its structure and design tokens (color palette, typography of Space Grotesk / Inter / JetBrains Mono, card styles, dark operator-console aesthetic) as the intended product UX. `proxploy-dashboard.html` is the higher-fidelity overview screen. Your frontend plan must reproduce and extend this, not invent a different look.

## Hard product rules (do not violate)

1. **Apps-only model.** The primary workload view is **Apps**, never a raw "Containers/LXC" list. Anyone who wants CTID-level detail uses Proxmox itself. Each app maps to **exactly one CT**, including multi-service apps: Immich (server + database + machine-learning) lives in one CT and appears as a single "Immich" tile, never as immich-db / immich-server / immich-ml. The nav is: Cluster, Apps, App Store, Virtual Machines, Storage, Network, Backups, Settings.
2. **App Store is powered by Community Scripts.** It sources its catalog from the `community-scripts/ProxmoxVE` project by fetching and caching their JSON metadata, and maps each entry's install command to Proxploy's one-CT deploy flow. Design a fetch-cache-refresh layer (through our own backend, not direct from the user's browser, to avoid CORS and rate limits).
3. **Build the whole product, not an MVP.** Scope is the complete feature set below. Phasing is allowed as a dependency-ordered **build sequence**, but nothing ships as a deliberately feature-stripped release. "Phase 1" means "built first because others depend on it," not "the cut-down version."
4. **Reuse over reinvention (this is a core constraint).** For every subsystem, first find a mature, well-maintained open-source project or library that already solves it, and plan to adopt, port, or integrate it. Only propose writing something from scratch when you have checked and no suitable OSS exists, and you must justify that decision explicitly. This applies especially to security, encryption, auth, secrets, terminals, consoles, and notifications. Do not hand-roll cryptography.
5. **Feature-gate everything from day 0, dormant.** Every feature must be wrapped behind an entitlement check from its first commit, resolved through one central entitlement client in the app that talks to our hosted **proxploy-api** (see Service topology). The licensing API is deliberately **not shipped inside the self-hosted app**, because a locally deployed app cannot be trusted to gate its own Pro features. The default state of every flag is ON (unarmed), so in development and until we sell, everything is unlocked. The free-vs-paid tier mapping is a config artifact on proxploy-api that stays inert until we decide to sell. Turning Pro gating on later is a config change, never a refactor.
6. **Security posture is not optional.** This product holds credentials that are effectively keys to a user's entire virtualization stack and it executes install scripts on their hosts. Non-negotiables: connect to Proxmox with **scoped API tokens, never root**; encrypt all stored credentials at rest; keep an append-only **audit log** of every state-changing action; ship **locked-down by default** (not internet-exposed, real auth on the panel, sane session/CSRF/rate-limit handling); TLS by default. Be explicit and honest about the trust model in the plan.

## Licensing discipline (decide this per dependency, it gates the reuse strategy)

- **Permissive** (MIT, BSD, Apache-2.0, and generally MPL-2.0 at file level): safe to port into or link within our codebase.
- **Copyleft** (GPL, LGPL, and especially **AGPL**): must be used **at arm's length only**, as a separate process/service over network or CLI. **Never copy copyleft source into Proxploy's own code**, because it would force Proxploy itself to adopt those terms and destroy any future proprietary Pro tier. Talking to Proxmox (AGPL) over its HTTP API is fine; porting AGPL code in is not.
- **Not open source** (e.g. BUSL, SSPL, "source-available"): do not use as a linked dependency. Example: HashiCorp Vault is BUSL now, so use the open fork **OpenBao** instead.
- For **every** dependency you propose, record: project, purpose, license, and the reuse mode (port / link / arm's-length service). Verify the *current* license from the source repo; do not assume.

## Stack decisions: lock the spine, keep the leaves provisional

The stack is an output of this brainstorm, not a later step. Decide it here, but treat two layers differently.

- **Lock the foundation now, and defend each choice.** These cascade into everything and are expensive to change later, so commit to them in this session: backend language and framework, ORM and database, frontend framework, and the core Proxmox client. Anchor point: we already own a **proxmoxer** (Python) engine from a prior project, so a Python backend is the sensible spine, which cascades into FastAPI, SQLAlchemy, and so on. State these as decided, with reasons.
- **Propose subsystem components as provisional leading candidates, behind swappable interfaces.** For individual subsystems (notifications, feature-flag provider, console approach, task queue, metrics store, secrets tool, and similar), name the leading candidate and its license now, but design a clean seam so it can be swapped when we actually reach that part of the build, without touching the rest. Do not marry a specific package months before it is integrated.

The failure modes to avoid are both real: do not hand-wave the whole stack as "TBD," and do not prematurely nail down forty packages we have not touched yet. Spine decided, leaves swappable.

## Service topology (four separate properties)

Proxploy is not one deployable. Plan it as four separate repos/properties with clean boundaries:

- **proxploy-app** — the self-hosted product the user installs on or beside their Proxmox host (backend + frontend + optional agent + installer). This is the only piece that ships to users.
- **proxploy-api** — an Aspyre-hosted licensing and entitlement API. It issues and validates licenses and resolves feature entitlements. It is **never bundled into proxploy-app**; the app calls it as a remote dependency. This is what makes Pro enforcement real, since a self-hosted app cannot be trusted to gate itself with local flags alone.
- **proxploy-web** — the marketing site (proxploy.com): landing, pricing, download.
- **proxploy-docs** — the documentation site (install, connect a host, security model, troubleshooting, API reference).

Design rules for the app-to-api relationship:
- The self-hosted app talks to proxploy-api **only for licensing/entitlement**, behind the swappable entitlement interface. Keep this call minimal and separate from any analytics or telemetry.
- **Offline tolerance is mandatory.** Many self-hosters run air-gapped or distrust phone-home. The free tier must work **fully without ever reaching proxploy-api**. Pro entitlement should use **short-lived signed entitlement tokens** (signed by Aspyre's private key, verified locally with a bundled public key) that the app caches and validates offline for a grace window, refreshing periodically rather than calling home on every action. A transient network failure must never lock a paying user out.
- **Dormant default.** Because we are not selling yet, proxploy-api ships resolving "all features entitled" until we arm real tiers. The wiring exists from day 0; enforcement is inert.
- The Community Scripts catalog mirror, if hosted, is a **separate concern** from proxploy-api and must not make the free App Store depend on Aspyre being online; the app can fall back to fetching the catalog directly.

## Full feature set to plan for

Plan all of this. Group into a build sequence, but scope the whole thing.

**Core platform**
- Multi-host / cluster connection management (agentless via per-host API tokens; design an optional lightweight agent as a pluggable component for things the API cannot do, such as PTY and local script execution, but default to agentless).
- Cluster + node overview: CPU, RAM, storage, network, temperatures, uptime, PVE/PBS versions, per-node and aggregated.
- Apps: lifecycle (start/stop/restart/pause), open web UI, live logs, web console, edit the saved Community Script, per-app resource graphs, one-CT-per-app model.
- App Store: Community Scripts catalog (fetch/cache/refresh), search, categories, install-to-any-chosen-host, **live streaming install log**, updates (per-app and update-all), scheduled auto-updates in a maintenance window.
- Virtual machines: list, lifecycle, in-browser console, snapshots, basic create/clone.
- Storage: datastores, usage per node, add/manage.
- Network: bridges, interfaces, live throughput.
- Backups: Proxmox Backup Server integration, jobs, schedules, snapshots, restore, success metrics.
- Cross-host migration of CTs/VMs (the paid moat): both cluster-native migration and a path for non-clustered hosts.

**Cross-cutting systems**
- Metrics + historical time-series with charts, and alerting (high load, disk full, node down, app down).
- Notifications to many targets (ntfy, gotify, email, Telegram, Slack, webhooks) via one abstraction.
- Task/job engine for long-running operations (installs, migrations, backups) with queue, progress, and live log streaming over WebSocket/SSE.
- Web terminal (into CTs and host shell) and VM console (VNC/SPICE in the browser).
- Scheduling (cron-like) for updates, backups, and tasks.
- AuthN (local login + optional OIDC/SSO + TOTP 2FA), AuthZ / RBAC, multi-user and teams (teams matter for the later MSP angle).
- Secrets management: encrypt API tokens and secrets at rest with a proven library or an arm's-length OpenBao, plus key management.
- Central entitlement / feature-flag service (the day-0 dormant gating layer).
- Audit log, structured logging, opt-in error reporting.
- First-run onboarding wizard (connect your first host), self-update of Proxploy itself.
- Full REST API with OpenAPI docs (the product should be automatable).
- Theming (dark/light) built on the mockup's design tokens.

**Delivery**
- Packaged as an easy self-hosted install: a one-line LXC installer in the Community Scripts spirit, plus a Docker/Compose option, systemd, and automatic TLS.
- proxploy.com landing/download site and documentation (install, connect a host, security model, troubleshooting) as a planned workstream.

## Starting candidates to evaluate (not final choices — verify license and fit)

Treat these as leads for the "reuse" mandate. Confirm each is current, maintained, and correctly licensed, and swap freely if you find better.

- Proxmox API: **proxmoxer** (Python, MIT) — we already use this; it is the engine to build on.
- Backend: **FastAPI** + Uvicorn + Pydantic (MIT), **SQLAlchemy** + Alembic (MIT). DB: SQLite default, Postgres option.
- Task queue: **Celery** (BSD) or **RQ** (BSD). Note **Dramatiq** is LGPL — arm's-length or avoid porting.
- Web terminal: **xterm.js** (MIT) + a PTY bridge. VM console: **noVNC** (MPL-2.0), or **Apache Guacamole** (Apache-2.0) for a heavier multi-protocol option.
- RBAC / authz: **Casbin / pycasbin** (Apache-2.0).
- AuthN: **Authlib** (BSD) for OIDC, argon2/passlib for local, **pyotp** for 2FA; or integrate an external IdP (Authelia Apache-2.0, Keycloak Apache-2.0) at arm's length.
- Secrets at rest: **age** (BSD) / **SOPS** (MPL-2.0) / **libsodium via PyNaCl** (ISC); full secrets manager: **OpenBao** (MPL-2.0, the open Vault fork). Do **not** use Vault (BUSL).
- Feature flags / entitlement: **OpenFeature** (Apache-2.0 spec) with a self-hosted provider, or **Unleash** (Apache-2.0) / **Flagsmith** (BSD) / **GrowthBook** (MIT). A lightweight internal flag service implementing OpenFeature may be cleanest for the dormant-gating requirement.
- Notifications: **Apprise** (BSD-2) — one library, dozens of targets. Strong single reuse pick.
- Scheduling: **APScheduler** (MIT).
- Metrics/time-series: store in the DB, or **VictoriaMetrics** / **Prometheus** (Apache-2.0) at arm's length. Charts: **uPlot** (MIT) / **Chart.js** (MIT) / **Recharts** (MIT).
- Reverse proxy + auto-TLS: **Caddy** (Apache-2.0).
- Catalog: **community-scripts/ProxmoxVE** metadata (verify license before porting anything beyond metadata).
- Frontend: **Vue 3** or **React** (MIT) + **Tailwind** (MIT), matching the mockup's tokens; a permissive component layer (Radix/shadcn, PrimeVue — MIT).

## Deliverables from this brainstorm

Produce these as separate markdown documents in a `/docs` (or `/planning`) folder:

1. **Product spec** — the exhaustive feature catalogue, each feature with a one-line description and its intended tier flag (all defaulting to on/unarmed).
2. **System architecture** — components and data flow, the agentless model and the optional-agent boundary, the security and trust model, and how script execution on hosts is isolated and streamed.
3. **Technology + dependency map** — a table: subsystem, chosen project, license, reuse mode (port/link/arm's-length), and a one-line justification. Mark each row as **locked** (foundational spine) or **provisional** (swappable leaf behind an interface). Flag every copyleft or non-OSS item and how you are handling it.
4. **Data model** — entities and schema (hosts, apps, VMs, jobs, users, roles, audit events, flags, catalog cache, notifications, schedules).
5. **API surface** — the REST endpoint list grouped by domain, with the WebSocket/SSE channels for live logs, consoles, and metrics.
6. **Frontend spec** — page map and routes derived from `proxploy-prototype.html`, the component inventory, the design-token system, and how state/streaming binds to the API.
7. **Entitlement / feature-flag architecture** — how every feature is wrapped from day 0; the split between the in-app entitlement client and the hosted **proxploy-api**; offline-tolerant validation via cached signed entitlement tokens with a grace window; the default-on/unarmed behavior; and the (inert) tier-mapping config on proxploy-api that we fill in only when we decide to sell.
8. **Security + secrets design** — token scoping, encryption at rest, audit logging, locked-down defaults, session/auth hardening, all built on the reused components above.
9. **Repository structure** — the layout across the four properties (**proxploy-app**, **proxploy-api**, **proxploy-web**, **proxploy-docs**): what lives in each, how proxploy-app is internally organized (backend / frontend / optional agent / installer), and the shared contract between app and api (the entitlement token format and the endpoints).
10. **Build sequence** — dependency-ordered phases that converge on the complete product, each phase listing what gets built and what it unblocks. Not scope cuts.
11. **Risks + open decisions** — call out the hard ones honestly: script-execution sandboxing, cross-host migration without a Proxmox cluster, agent-vs-agentless trade-offs, and where the reuse strategy has gaps that force custom code.

Ask me any clarifying questions you need before you begin, then run `/brainstorm` and produce the documents. When they are ready, stop and let me review before any implementation.
