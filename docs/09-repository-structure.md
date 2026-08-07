# 09: Repository Structure

Subordinate to `00-decision-brief.md`. Four properties (brief §6), four
repositories. The boundary rule is simple: **a repo is a deployment unit.**
proxploy-app ships to the user's hardware; proxploy-api runs on Aspyre's;
proxploy-web and proxploy-docs deploy as static sites. Nothing crosses a repo
boundary except the shared contract at the end of this document, and that
crosses as a *specification*, not as code.

## Why four repos, not a monorepo

- **Different trust domains.** proxploy-app is the entire user-installed
  product; proxploy-api holds the Aspyre signing key and must never be
  bundled or even buildable into the app by accident (brief §6). A hard repo
  boundary is the cheapest way to make "never bundled" structural.
- **Different release cadences.** The app versions like a product; the API is
  a tiny service that changes when licensing changes; web/docs are content
  workstreams edited by whoever is writing that week.
- **Backend + frontend of the app stay together** in proxploy-app because
  they version together, deploy together (one installer artifact), and the
  frontend is generated against the backend's OpenAPI spec. Splitting them
  would create exactly the cross-repo coupling we avoid everywhere else.

---

## proxploy-app (the product: the only thing users install)

Backend, frontend, and installer in one repo, one version, one release
artifact. Layout:

```
proxploy-app/
├── docs/                       # this planning set (00–11)
├── proxploy-prototype.html     # design source of truth (brief §1)
├── backend/
│   ├── pyproject.toml
│   ├── proxploy/
│   │   ├── main.py             # FastAPI app factory, lifespan (pollers, scheduler, entitlement refresh)
│   │   ├── config.py           # settings: DSN, bind addr, paths (Pydantic settings)
│   │   ├── api/                # routers, one module per domain; mirrors nav + brief §9 entities
│   │   │   ├── auth.py         #   sessions, login, TOTP, OIDC callbacks
│   │   │   ├── hosts.py        #   host onboarding (token + SSH key), host CRUD
│   │   │   ├── cluster.py      #   cluster/node overview, metrics queries
│   │   │   ├── apps.py         #   Apps: lifecycle, logs, script view/edit
│   │   │   ├── store.py        #   catalog browse, install, updates
│   │   │   ├── vms.py          #   VM list/detail, lifecycle, snapshots
│   │   │   ├── storage.py
│   │   │   ├── network.py
│   │   │   ├── backups.py
│   │   │   ├── consoles.py     #   websocket proxies: termproxy (PtyBridge), vncproxy (ConsoleProxy)
│   │   │   ├── jobs.py         #   job status, cancel, log-stream (SSE/websocket)
│   │   │   ├── entitlements.py #   GET /api/v1/entitlements, resolved flag map for the UI
│   │   │   ├── teams.py        #   teams, members, RBAC admin
│   │   │   ├── settings.py
│   │   │   └── audit.py        #   read-only audit log views
│   │   ├── services/           # domain logic behind the routers; the seams from brief §5 live here
│   │   │   ├── proxmox.py      #   adapts the existing lab-cluster-deploy proxmoxer module (CT lifecycle,
│   │   │   │                   #   cluster/node/guest reads, migration); PVE 8-vs-9 branching isolated here
│   │   │   ├── catalog.py      #   CatalogSource: fetch, ETag cache, pin + diff against upstream
│   │   │   ├── notifier.py     #   Notifier → Apprise
│   │   │   ├── authz.py        #   Authorizer → pycasbin
│   │   │   ├── authn.py        #   AuthProvider: argon2 local, Authlib OIDC, pyotp TOTP
│   │   │   └── metrics.py      #   MetricsStore: samples, rollups, retention pruning
│   │   ├── executor/           # the privileged path (brief §8), isolated on purpose
│   │   │   ├── ssh.py          #   asyncssh transport, dedicated ed25519 key, audit-logged
│   │   │   └── runner.py       #   install/update/migrate runs: stream + archive output
│   │   ├── jobs/               # JobBackend: in-process asyncio runner, DB-persisted
│   │   │   ├── backend.py      #   enqueue / status / cancel / log-stream (the seam)
│   │   │   └── scheduler.py    #   Scheduler → APScheduler 4, triggers feed JobBackend
│   │   ├── pollers/            # background Proxmox polling → caches + MetricsStore
│   │   ├── entitlements/       # custom client (brief §7): PyJWT EdDSA verify, disk cache,
│   │   │   │                   # grace window, built-in default map (air-gapped free tier)
│   │   │   └── client.py       #   Entitlements.enabled(key) + FastAPI dependency/decorator
│   │   ├── secretstore/        # SecretStore: Fernet/MultiFernet, root-only master key file
│   │   ├── models/             # SQLAlchemy models, entity list per brief §9
│   │   └── migrations/         # Alembic
│   └── tests/
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── src/
│   │   ├── routes/             # TanStack Router, one route per prototype page
│   │   │   ├── cluster.tsx
│   │   │   ├── apps.tsx            # + apps.$appId.tsx (detail: overview, logs, console, script)
│   │   │   ├── store.tsx           # + store.$slug.tsx (catalog entry detail / install)
│   │   │   ├── vms.tsx             # + vms.$vmId.tsx (detail incl. noVNC console)
│   │   │   ├── storage.tsx
│   │   │   ├── network.tsx
│   │   │   ├── backups.tsx
│   │   │   └── settings.tsx        # hosts, users/teams, notifications, entitlements, audit
│   │   ├── components/
│   │   │   ├── ui/             # shadcn/ui, ported in and restyled (the one sanctioned "port")
│   │   │   ├── terminal/       # xterm.js wrapper (CT + node shells)
│   │   │   ├── console/        # noVNC wrapper, imports @novnc/novnc, never copies its files (MPL)
│   │   │   └── charts/         # uPlot wrappers
│   │   ├── api/                # typed client generated from backend OpenAPI + TanStack Query hooks
│   │   └── styles/             # Tailwind v4 config + design tokens lifted from the prototype
│   └── tests/
└── installer/
    ├── install.sh              # one-line LXC installer, community-scripts spirit
    ├── docker-compose.yml
    ├── systemd/                # proxploy.service (+ Caddy unit if accepted)
    └── caddy/Caddyfile         # arm's-length TLS; app self-signs if Caddy is declined
```

Notes on the boundaries inside the repo:

- **`executor/` is its own directory, not a service module**, because it is
  the one component that holds root-on-node power (brief §8). Keeping it
  physically small and separate makes the audit surface obvious and keeps
  the future agent swap honest, the agent replaces this directory's
  transport, nothing else. It carries the repo's highest test-coverage bar
  and tightest review bar, and a CI check (an import-graph lint over
  `backend/proxploy/`) fails the build if any module outside `executor/`
  imports the SSH client or the SecretStore accessor for the SSH key, a
  hard structural rule, not a convention (doc 08 §4, doc 10 Phase 1).
- **`agent/` does not exist yet, deliberately.** The optional agent (brief
  §6, §8) is a later pluggable add-on behind the same executor interface.
  Scaffolding it now is YAGNI: agentless SSH is the default path, nothing may
  depend on the agent, and an empty directory would only invite premature
  coupling. It gets created when it gets built.
- The backend serves the built frontend as static files in production; one
  process, one port, one systemd unit.

## proxploy-api (Aspyre-hosted licensing service)

Deliberately tiny, a licensing endpoint, not a platform. No analytics, no
telemetry (brief §6).

```
proxploy-api/
├── pyproject.toml
├── proxploy_api/
│   ├── main.py                 # FastAPI app
│   ├── api/
│   │   ├── licenses.py         # activate (license key → first token + refresh credential) + revoke
│   │   └── entitlements.py     # token refresh (refresh credential → fresh token)
│   ├── signing.py              # Ed25519 signing (PyJWT); private key loaded from
│   │                           # a root-only file / KMS, never in the repo, never in env-committed config
│   ├── tiers.yaml              # tier → features mapping; INERT while dormant: resolves "all entitled"
│   │                           # (brief §7). Arming Pro tiers later = editing this file, never a refactor.
│   └── models/                 # licenses, issued_tokens (schema defined in doc 07; created Phase 1,
│                                # launch-critical even while dormant, not deferred to "when we sell")
├── migrations/
└── tests/
```

Key handling rules: the Ed25519 **private** key lives in a KMS or a
root-only file on proxploy-api infrastructure, with an **offline encrypted
backup** kept outside the serving environment (doc 07 §4), never in the
repo. The **public** key is committed into proxploy-app as part of a
`kid`-keyed **set** (not a single key) and ships inside every install from
**Phase 1**. Key rotation = publish the new public key in an app release,
sign with both `kid`s during the overlap window, retire the old key after
`grace_until` passes, a documented runbook (doc 07 §4) that always survives
an app release, because the app must ship to learn the new key.

## proxploy-web (proxploy.com)

Content workstream, not an engineering one. Static site, suggested stack:
Astro (static output, MD-driven, no server). Page inventory: landing,
features, screenshots/tour, download + install (the one-liner front and
center), pricing (dormant until tiers arm), about/Aspyre Labs, legal
(privacy, terms), blog/changelog. Nothing here talks to proxploy-api.

## proxploy-docs (documentation site)

Also static, also content. Suggested stack: a standard docs generator, 
Starlight or MkDocs Material. Page inventory: quick start (LXC one-liner,
Docker, manual), host onboarding (API token scopes + SSH key authorization,
the honest trust-model page per brief §8), Apps & App Store guide, VMs,
Storage/Network/Backups, alerts & notifications, teams/RBAC/OIDC, REST API
reference (generated from the app's OpenAPI spec), upgrade & self-update,
security model, FAQ/troubleshooting.

---

## SHARED CONTRACT: entitlement token + app↔api interface

Stated once, here. proxploy-app and proxploy-api both implement this section
as written; a change to the contract is a change to this document first, then
both repos.

### Entitlement token (JWT, EdDSA/Ed25519: brief §7)

Signed with Aspyre's private key on proxploy-api; verified offline in
proxploy-app against the bundled public key. The JWT header carries a `kid`;
the app bundles a small **set** of valid public keys so rotation is an
overlap window, not a flag day (doc 07 §8).

| Claim | Type | Meaning |
|---|---|---|
| `sub` | string | License id. |
| `tier` | string | Tier name (informational; features map is authoritative). |
| `features` | object (map of flag key → bool) | Dotted, domain-namespaced keys per brief §7 (`hosts.multi`, `store.install`, `auth.oidc`, …; full catalogue in doc 01). |
| `iat` | int (unix) | Issued at. |
| `exp` | int (unix) | ~72 h after `iat`. App refreshes in the background well before this. |
| `grace_until` | int (unix) | ~30 d after `iat`. Past `exp` but before `grace_until`, the cached token remains valid offline; transient network failure never locks a paying user out. |

App-side behavior (restating brief §7 as contract): token cached on disk;
refresh is background-only; **no license configured → built-in default map,
zero network calls, forever**; during the dormant phase the default map and
proxploy-api both resolve "all entitled."

### app ↔ api endpoints

| Method + path (on proxploy-api) | Request | Response | Notes |
|---|---|---|---|
| `POST /v1/licenses/activate` | `{ "license_key": str, "install_id": str }` | `{ "token": jwt, "refresh_credential": str }` | First contact: exchanges a purchased key for the first entitlement token; binds an install-generated `install_id` to the license and issues a per-install refresh credential (doc 07 §4). |
| `POST /v1/entitlements/refresh` | `{ "refresh_credential": str }` | `{ "token": jwt }` | Background refresh, authenticated by the per-install refresh credential. |
| `POST /v1/licenses/revoke` | `{ "refresh_credential": str }` | `{ "revoked": true }` | Deactivates this install's refresh credential; the app ages through grace to the free-tier floor (doc 07 §8). |
| `GET /v1/health` | n/a | `{ "status": "ok" }` | Operational only; the app never depends on it. |

That is the entire surface. The app calls nothing else on proxploy-api
(brief §6: entitlement refresh only, no analytics, no telemetry).

### Why a spec, not a shared code package

The contract is duplicated as implementation in two repos on purpose:

- It is **six claims and four endpoints**. A shared package would exist to
  deduplicate roughly fifty lines of Pydantic, at the cost of a third
  versioned artifact, a release pipeline, and lockstep upgrades between a
  user-installed product and an Aspyre-hosted service that deliberately
  version independently.
- The coupling we want is **to a document with a review step**, not to a
  dependency that can drift silently via a version bump. JWT itself is the
  wire-level compatibility layer; the signature check is the integration
  test.
- The one safeguard worth having instead of a package: a contract test in
  each repo asserting its serialization of the claims table above matches a
  shared static fixture (a checked-in sample token payload copied from this
  doc). Cheap, no dependency, fails loudly on drift.

If the contract ever grows past a screenful, revisit; at this size a shared
package is machinery without a payload.
