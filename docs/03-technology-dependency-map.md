# 03: Technology & Dependency Map

Subordinate to `00-decision-brief.md`. If a row here disagrees with the brief,
the brief wins and this table changes.

**License marking (†).** No network access was available when this table was
written. Every license value marked **†** means: *believed correct as of
Jan 2026, re-verify against the source repo before first install.* No
dependency is installed until its row is re-verified per the protocol below.

Reuse modes (per brief §3):

- **port**: source is copied into our tree and becomes ours to maintain.
- **link**: installed as a package dependency; we import it, we never copy its files in.
- **arm's-length**: separate process or remote service, talked to over network/CLI only.

## Backend

| Subsystem | Project | License | Reuse mode | Status | Justification |
|---|---|---|---|---|---|
| Proxmox client | proxmoxer | MIT † | link | Locked | Already ours in production use; thin, maintained, API-token auth support (brief §4). `backend/proxploy/services/proxmox.py` adapts the existing lab-cluster-deploy proxmoxer module, CT lifecycle, cluster/node/guest reads, migration calls; rather than being written from scratch; all PVE-8-vs-9 version branching is isolated to that one layer (doc 02 §4). |
| Web framework | FastAPI | MIT † | link | Locked | Async-first for polling many hosts and streaming logs; OpenAPI docs for free, the full REST API is a deliverable (brief §4). |
| ASGI server | Uvicorn | BSD-3-Clause † | link | Locked | Default production ASGI server for FastAPI; boring, fast, websocket-capable (needed for terminal/console proxying). |
| Validation / serialization | Pydantic v2 | MIT † | link | Locked | FastAPI's native model layer; one schema language for API, config, and entitlement payloads. |
| ORM | SQLAlchemy 2.x | MIT † | link | Locked | Boring, universal, supports both target DBs in one portable schema subset (brief §4). |
| Migrations | Alembic | MIT † | link | Locked | The SQLAlchemy migration tool; no reason to look elsewhere. |
| Database (default) | SQLite (WAL mode) | Public Domain † | link (stdlib driver) | Locked | Zero-dependency install for self-hosters; WAL mitigates write contention from metrics polling (brief §4, §11). |
| Database (optional) | PostgreSQL | PostgreSQL License † | arm's-length | Locked | Larger installs flip a DSN; server is a separate process the user runs, never bundled. |
| Job engine | **Custom** in-process asyncio runner, DB-persisted | n/a (ours) | n/a | Provisional (seam: `JobBackend`) | **Custom justified per brief §5:** every mature Python queue (Celery, RQ, arq, Huey) requires a broker; our default install is single-process + SQLite. We also need live log streaming per job, which brokers don't give us anyway. Swap to Celery/Redis behind `JobBackend` if multi-worker ever matters. |
| Scheduling | APScheduler 3.11 | MIT **verified** | link | Provisional (seam: `Scheduler`, satisfied by `jobs/scheduler.py`) | **Amendment, Phase 7, 2026-08-01, see `docs/notes/phase-7-operate.md`:** this row named "APScheduler 4"; no 4.x release exists, PyPI's maximum stable is 3.11.3, and 4.0.0 exists only as `a1`–`a6` pre-releases (verified against PyPI 2026-08-01). Shipped on the stable 3.11 line instead. Only `CronTrigger` is used, for cron parsing and DST-correct next-fire arithmetic; `jobs/scheduler.py`'s tick loop reads the `schedules` table directly on every tick and replaces `BaseScheduler`/jobstores entirely, so there is no second in-process registry to reconcile against doc 04's authoritative table; this satisfies the `Scheduler` seam. License confirmed MIT via `pip show APScheduler` against the installed 3.11.3 wheel, replacing the † unverified mark. |
| Scheduling (transitive) | tzlocal | MIT **verified** | link | Provisional | `APScheduler`'s own dependency (`pip show APScheduler` lists it under `Requires`); pulled in automatically, never imported directly; `jobs/scheduler.py::next_fire` always passes an explicit IANA timezone string, never relies on tzlocal's local-timezone detection. Added to this table, Phase 7, so the dependency tree is complete. |
| Notifications | Apprise | BSD-2-Clause † | link | Provisional (seam: `Notifier`) | One dependency covers ntfy, gotify, email, Telegram, Slack, webhooks. Strongest single reuse win in the plan (brief §5). |
| AuthZ / RBAC | pycasbin (`casbin`) | **Apache-2.0, verified 2026-08-05 @ v1.43.0** | link | Provisional (seam: `Authorizer`, satisfied by `services/authz.py`) | Proven RBAC-with-domains model for teams; roles owner/admin/operator/viewer without hand-rolling policy evaluation. **Amendment, Phase 8, 2026-08-05, see `docs/notes/phase-8-scale.md`:** the enforcer is built **in memory** from the static policy matrix in code plus `g`-lines derived from `team_members`, not from the `casbin_rules` table via `casbin-sqlalchemy-adapter` (that dependency is not in the tree). The policy matrix never changes at runtime, doc 05 exposes no policy-editing endpoint, and the only dynamic rules are a pure function of `team_members`, so an adapter would create a mirror to drift rather than a source of truth. Membership writes re-sync through the `Authorizer` seam (`services/authz.py::sync_user`), which is what this row's "Provisional (seam)" status licenses. License confirmed via `pip show casbin` against the installed 1.43.0 wheel, replacing the † unverified mark. |
| AuthZ (transitive) | simpleeval | MIT **verified** | link | Provisional | `casbin`'s own dependency (`pip show casbin` lists it under `Requires`); pulled in automatically, never imported directly; it evaluates the matcher expression inside the enforcer. Added to this table, Phase 8, so the dependency tree is complete (same treatment Phase 7 gave `tzlocal`). |
| OIDC client | Authlib | **BSD-3-Clause, verified 2026-08-05 @ v1.7.2** | link | Provisional (seam: `AuthProvider`) | Standards-correct OIDC so external IdPs (Authelia, Keycloak) are supported *through* the protocol, never bundled. Used for discovery + the PKCE authorization-code flow (`services/oidc.py`); JWT/JWKS validation goes through `joserfc` below, since `authlib.jose` is deprecated in 1.7.x. License confirmed via `pip show Authlib` against the installed 1.7.2 wheel, replacing the † unverified mark. |
| OIDC (transitive) | joserfc | BSD-3-Clause **verified** | link | Provisional | `Authlib`'s own dependency (`pip show Authlib` lists it under `Requires`), and the successor to the deprecated `authlib.jose`. Imported directly by `services/oidc.py` for RS256 ID-token verification against the IdP's JWKS. Added to this table, Phase 8. |
| Password hashing | argon2-cffi | MIT † | link | Provisional (seam: `AuthProvider`) | Argon2id is the current best-practice password hash; never hand-roll crypto (brief §2.4). Phase 8 reuses the same `PasswordHasher` for one-time TOTP recovery codes, no second hash construction. |
| TOTP | pyotp | **MIT, verified 2026-08-05 @ v2.10.0** | link | Provisional (seam: `AuthProvider`) | Tiny, standard RFC 6238 implementation for 2FA. License confirmed via `pip show PyOTP` against the installed 2.10.0 wheel, replacing the † unverified mark. No QR-code dependency was added alongside it: enrollment renders the secret and the `otpauth://` URI as text for manual entry (`components/TotpCard.tsx`). |
| Entitlement tokens | PyJWT (EdDSA/Ed25519) | MIT † | link | Provisional | Verifies Aspyre-signed entitlement JWTs offline against a bundled public key (brief §7). EdDSA: modern, small keys, no RSA footguns. |
| Entitlement client | **Custom** thin client, OpenFeature-shaped API | n/a (ours) | n/a | Provisional (seam: `Entitlements.enabled(key)`) | **Custom justified per brief §5:** Unleash/Flagsmith solve ops-side flag *management*; our problem is offline-verifiable *licensing*, signed tokens, grace windows, air-gapped default map. No OSS project does that; the client is ~a few hundred lines around PyJWT. |
| Secrets at rest | cryptography (Fernet / MultiFernet) | Apache-2.0 OR BSD-3 (dual) † | link | Provisional (seam: `SecretStore`) | Audited primitive with built-in key rotation via MultiFernet; master key in a root-only file. No hand-rolled crypto anywhere (brief §5). |
| SSH executor transport | asyncssh | **EPL-2.0 OR GPL-2.0-or-later, verified 2026-07-28 @ v2.24.0** | link (never port files) | Provisional (seam: executor interface) | Async-native SSH for App Store installs (root on the PVE node, brief §8). Chosen over paramiko explicitly to avoid LGPL. **Verified:** dual-licensed EPL-2.0 OR GPL-2.0-or-later, confirmed against `github.com/ronf/asyncssh` `COPYRIGHT` and `LICENSE` at tag `v2.24.0` (2026-06-27 release) and the PyPI project page, checked 2026-07-28. Ruling: EPL-2.0's weak, file-level copyleft is acceptable as an unmodified linked dependency, never ported; matches the brief §3/§8 posture. If a future major version relicenses, re-run this check per the protocol below. |
| Rate limiting | slowapi | MIT † | link | Provisional | **Decision (the brief offered slowapi *or* Starlette middleware, we pick slowapi):** purpose-built for FastAPI/Starlette on top of `limits`, gives per-IP limits on auth endpoints (brief §8) in a decorator, no custom middleware to maintain. Trivial to replace with hand-written Starlette middleware if it stagnates. |
| HTTP client | httpx | BSD-3-Clause † | link | Provisional | One async client for both catalog fetches (community-scripts, with ETag caching) and the proxploy-api entitlement calls. Already an indirect FastAPI-ecosystem staple. |
| Metrics store | **Custom** tables in the app DB (raw 30s samples + 5m/1h rollups, retention-pruned) | n/a (ours) | n/a | Provisional (seam: `MetricsStore`) | **Custom justified per brief §5:** a TSDB dependency would break the zero-dependency SQLite install for what is, at default scale, a few insert-and-rollup queries. VictoriaMetrics (Apache-2.0) is the arm's-length swap-in behind `MetricsStore` for big fleets. |

## Frontend

| Subsystem | Project | License | Reuse mode | Status | Justification |
|---|---|---|---|---|---|
| UI framework | React 19 | MIT † | link | Locked | Deepest ecosystem for the hard reuse targets: xterm.js wrappers, noVNC integration, TanStack Query (brief §4). |
| Language | TypeScript | Apache-2.0 † | link (toolchain) | Locked | Non-negotiable for an API-heavy dashboard; types generated from the OpenAPI spec keep frontend and backend honest. |
| Build tool | Vite | MIT † | link (toolchain) | Locked | Default modern React toolchain; fast dev server, static production build served by the backend. |
| Styling | Tailwind CSS v4 | MIT † | link (toolchain) | Locked | Utility styling driven entirely by the prototype's design tokens. |
| Overlay primitives | @radix-ui/react-dialog 1.1.23, @radix-ui/react-alert-dialog 1.1.23 | MIT **verified** | link | Locked | **Added 2026-08-11 (see doc 06's amendment).** An audit found 18 hand-rolled dialog surfaces sharing four defects: no Escape, no focus trap, no focus restore, no `aria-modal`. Zero focus traps and one `aria-modal` across the whole app. Focus management is subtly hard and not where this project's value is, so it is bought rather than owned. Versions pinned exact. License read from the installed `package.json`, not assumed; all 29 transitive `@radix-ui/*` packages are MIT. Measured cost +41.9 KB gzipped against a 326 KB bundle. Wrapped once in `src/components/ui/dialog.tsx` and `alert-dialog.tsx` so no call site touches Radix directly. |
| Menu primitive | @radix-ui/react-dropdown-menu 2.1.24 | MIT **verified** | link | Locked | Added 2026-08-11 for `AccountMenu`, which hand-rolled Escape and click-outside but had no roving focus, no focus return and no typeahead. |
| Tab primitive | @radix-ui/react-tabs 1.1.21 | MIT **verified** | link | Locked | Added 2026-08-11 for the one local-state tab strip (`routes/storage.tsx`). The tab strips in `apps.tsx`, `hosts.tsx` and `vms.tsx` are deliberately NOT converted: they are router child-routes so tabs stay deep-linkable, and Radix Tabs would break that. |
| Command palette | cmdk 1.1.1 | MIT **verified** | link | Provisional (rebuild in progress) | Added 2026-08-11. Doc 06 named cmdk originally; the palette was hand-rolled with manual roving focus instead. Rebuilding on cmdk drops that hand-rolled focus handling. |
| Components | shadcn/ui + Radix primitives | MIT † | **port** (shadcn, by design) + link (Radix) | Locked | shadcn is *meant* to be copied into the tree and restyled; exactly right for the prototype's bespoke dark-console look instead of fighting a themed kit (brief §4). Radix stays a linked dependency underneath. |
| Server state | TanStack Query | MIT † | link | Locked | Cache + refetch model maps 1:1 onto live dashboards fed by polling + SSE invalidation (brief §4). |
| Routing | TanStack Router | MIT † | link | Locked | Type-safe routes; pairs with Query; matches the prototype's page set cleanly. |
| Web terminal | xterm.js | MIT † | link | Provisional (seam: `PtyBridge`) | The standard browser terminal; backend bridges Proxmox `termproxy` websockets, no SSH needed for consoles (brief §5). |
| VM console | noVNC (`@novnc/novnc`) | **MPL-2.0 †, see copyleft flags** | **link only, never port** | Provisional (seam: `ConsoleProxy`) | Browser VNC over Proxmox `vncproxy`/`vncwebsocket`. MPL-2.0 is file-level copyleft: fine as an npm dependency, but **no noVNC file is ever copied into our tree** unless we carry full MPL file-level compliance for it; so we don't copy, period. |
| Charts | uPlot | MIT † | link | Provisional | Smallest fast time-series charting lib; fits high-frequency metrics without dragging in a charting framework. |
| Command palette | cmdk | **MIT, verified 2026-07-28 @ v1.1.1** | link | Provisional | ⌘K command palette, `GlobalSearch` (doc 06). Verified via `github.com/pacocoursey/cmdk` `LICENSE.md`. Introduced in doc 06; reconciled into this table per the license audit. |
| Toasts | sonner | **MIT, verified 2026-07-28 @ v2.0.7** | link | Provisional | Toast surface, restyled with our tokens (doc 06 `Toast`). Verified via `github.com/emilkowalski/sonner` `LICENSE.md`. |
| Code/script editor | CodeMirror 6 (`@codemirror/*`) | **MIT, verified 2026-07-28 @ v6.7.1 (`@codemirror/state`)** | link | Provisional (seam: `CodePanel`) | Script editor (Config tab) + read-only script preview (doc 06 `CodePanel`). Verified via `github.com/codemirror/state` `LICENSE`. |
| Data tables | TanStack Table | **MIT, verified 2026-07-28 @ v8.21.3 (`@tanstack/react-table`)** | link | Locked (pairs with TanStack Query/Router, brief §4) | Sorting for `DataTable` (doc 06): VMs, hosts, backups, bridges, snapshots. Verified via `github.com/TanStack/table` `LICENSE`. |

## Delivery

| Subsystem | Project | License | Reuse mode | Status | Justification |
|---|---|---|---|---|---|
| Reverse proxy / TLS | Caddy | Apache-2.0 † | **arm's-length** (separate process, installer-managed) | Provisional | Automatic TLS with near-zero config. Installer artifact only; the app also serves plain HTTP behind it and can self-sign via `cryptography` if Caddy is declined (brief §5). |
| App catalog + installers | community-scripts/ProxmoxVE | MIT † (verify at import) | **arm's-length**: JSON metadata consumed + install entrypoints invoked over SSH; **code never vendored** | Locked as source (product rule §2); fetch/cache mechanics provisional (seam: `CatalogSource`) | The App Store *is* this catalog (brief §2.2). Fetched server-side, cached in DB with ETag refresh. We consume metadata and execute their scripts on the node exactly as a user would; copying their code into our tree would freeze it, fork it, and take on their maintenance; provenance pinning + diff-against-upstream (brief §8) gives safety without vendoring. |
| Proxmox VE itself | Proxmox VE | **AGPL-3.0, see copyleft flags** | **arm's-length: HTTP API only** | Locked | The platform we manage. AGPL means we never import, copy, or link Proxmox code, every interaction is over its HTTP API via proxmoxer (brief §3). |

## Copyleft / weak-copyleft flags (every one, explicit)

| Project | License | Ruling |
|---|---|---|
| Proxmox VE | AGPL-3.0 | **Arm's-length only.** HTTP API via proxmoxer; no Proxmox source ever enters our tree or our process. |
| noVNC | MPL-2.0 | **Link only.** npm dependency, never port files into our tree; porting would require file-level MPL compliance (per-file license retention, source availability for modifications). We avoid the question by never copying. |
| asyncssh | EPL-2.0 OR GPL-2.0-or-later (dual; **verified 2026-07-28 @ v2.24.0**) | **Link only, never port files.** Verified acceptable as an unmodified linked dependency (weak, file-level copyleft) per the protocol below; fallback to invoking system `ssh` arm's-length remains the documented escape hatch if a future relicense changes this ruling. |
| paramiko | LGPL-2.1 | **Rejected.** LGPL as a linked Python library sits on the wrong side of brief §3; asyncssh chosen instead. |
| Dramatiq | LGPL-3.0 | **Rejected.** Same LGPL rule, and it wants a broker anyway (see job engine row). |
| HashiCorp Vault | BUSL-1.1 | **Rejected, non-OSS, never linked** (brief §3). If a full secrets manager is ever needed, **OpenBao (MPL-2.0)** is the arm's-length swap-in behind `SecretStore`. |
| OpenBao | MPL-2.0 | Not adopted now. If adopted: arm's-length process only, which sidesteps MPL entirely. |

## Rejected alternatives

| Candidate | Rejected in favor of | Why |
|---|---|---|
| Celery, RQ, arq, Huey | Custom in-process job engine | All require a broker (Redis/RabbitMQ), breaking the zero-dependency SQLite install; none provide the live per-job log streaming we need anyway (brief §5). Celery remains the named swap-in behind `JobBackend`. |
| Dramatiq | Custom job engine / asyncssh-era stack | LGPL *and* broker-dependent, fails two rules at once. |
| Unleash, Flagsmith | Custom entitlement client | They solve ops-side feature-flag *management*; our problem is offline-verifiable *licensing* with signed tokens and grace windows, which they don't do (brief §5). |
| paramiko | asyncssh | LGPL (brief §3). |
| HashiCorp Vault | Fernet SecretStore now, OpenBao arm's-length if ever needed | BUSL is non-OSS; also a heavyweight external service for what is one encrypted column family at our scale. |
| Apache Guacamole | noVNC | Apache-2.0 and capable, but a full Java gateway service; far heavier than proxying Proxmox's own VNC websocket. Named swap-in behind `ConsoleProxy` if SPICE/RDP demand appears (brief §5). |
| Vue 3 | React 19 | Runner-up on merit; rejected only because the console/VNC/terminal reuse targets and component ecosystem are deeper on React. The prototype's design tokens port identically to either (brief §4). |
| VictoriaMetrics (now) | Custom MetricsStore tables | An external TSDB breaks the zero-dependency install; it stays the named arm's-length swap-in behind `MetricsStore` for large fleets. |
| Starlette hand-rolled rate-limit middleware | slowapi | Both acceptable per the brief; slowapi picked because it exists, is MIT, and is purpose-built; writing middleware to avoid a 200-line dependency is reinvention. |
| requests / aiohttp | httpx | One client, sync-and-async, already idiomatic in the FastAPI ecosystem; no reason to carry two HTTP clients. |

## License verification protocol (required, Phase 1)

Every **†** in this document is a claim, not a fact. Before the first
`pip install` / `npm install` of the build (Phase 1, Foundation, brief §10):

1. For each row, open the dependency's source repository at the exact version
   to be pinned and read its `LICENSE` file (and `pyproject.toml` /
   `package.json` license field). Trust the repo, not PyPI/npm metadata alone.
2. Update this table: replace "†" with "verified 2026-MM-DD @ vX.Y.Z".
3. Any mismatch with the table is escalated before install: re-run the brief
   §3 rules against the *actual* license and either re-approve the row or
   swap the dependency. **asyncssh was the first row resolved**: verified
   2026-07-28 @ v2.24.0, dual EPL-2.0 OR GPL-2.0-or-later against the source
   repo's `COPYRIGHT`/`LICENSE` files, ruling: acceptable as an unmodified
   linked dependency (see the row above and the copyleft flags table).
   cmdk, sonner, CodeMirror 6, and TanStack Table were verified the same way
   the same day, all MIT, after being reconciled into this table from doc 06.
4. Copyleft findings are added to the flags section above; nothing copyleft
   is ever installed under a "link" or "port" mode without a ruling recorded
   here.
5. Repeat the check whenever a dependency's major version is bumped
   (relicensing mid-life is no longer hypothetical, Vault proved it).

CI enforcement (Phase 1 deliverable): a license-audit step (e.g.
`pip-licenses` / `license-checker`) that fails the build on any license
outside the approved set in brief §3, so drift after the initial audit is
caught mechanically rather than by memory.
