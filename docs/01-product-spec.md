# Proxploy: Product Specification (feature catalogue)

Doc 01. Subordinate to `00-decision-brief.md`; if anything here conflicts with the
brief, the brief wins (and must be changed first).

## 0. Scope rules restated

- **Apps-only model.** The primary workload view is Apps. One app = exactly one
  LXC container, always; Immich is one CT and one tile, regardless of how many
  services run inside it. There is no raw CT list page in the shipped nav.
- **Fixed navigation:** Cluster · Apps · App Store · Virtual Machines · Storage ·
  Network · Backups · Settings. Nothing is added to or removed from this list by
  tier, config, or entitlement; gated features veil or disable, they never
  reshape the nav.
- **This is the whole product.** Every feature below ships. The build sequence
  (doc 10) orders them; it never cuts them.

## 0.1 How to read the tables

Each feature has:

- **Flag key**: the entitlement key (brief §7): dotted, namespaced by domain.
  One flag per feature. Backend enforces via dependency/decorator; frontend
  reads the resolved map from `GET /api/v1/entitlements` and veils, but the server
  always re-enforces.
- **Tier**: a **provisional, INERT** label. Every flag defaults **ON**
  (unarmed) in both the built-in default map and the dormant proxploy-api
  resolver. Nothing in the codebase branches on tier; arming Pro later is a
  config change on proxploy-api only. Values:
  - `Core`: never gated, even after arming. Security and safety surfaces
    (local auth, secrets, audit, the entitlement client itself) are not
    sellable and must not be toggleable.
  - `Free`: provisionally in the free tier when armed.
  - `Pro`: provisionally in the paid tier when armed. A guess to be priced
    later; changing it costs nothing.

---

## 1. Hosts & Cluster

| Feature | Description | Flag key | Tier (inert) |
|---|---|---|---|
| Host onboarding | Add a PVE host: URL, scoped API token (never root@pam password), TLS fingerprint pinning, connectivity check | `hosts.onboard` | Free |
| SSH executor enrolment | Authorize the dedicated ed25519 key on a node during onboarding, with explicit consent UX; required only for store installs/updates/migration | `hosts.ssh_executor` | Free |
| Single-host management | Full platform against one host | `hosts.single` | Free |
| Multi-host management | Any number of hosts under one pane; per-host and fleet-wide views | `hosts.multi` | Pro |
| Host health & removal | Reachability status, credential rotation, safe host removal (apps become orphaned, not deleted) | `hosts.manage` | Free |
| Cluster overview | Landing dashboard: fleet CPU/RAM/storage rings, per-node cards, running counts, live-updated | `cluster.overview` | Free |
| Node detail | Per-node drill-down: load, uptime, PVE version, guests on node, per-node graphs | `cluster.node_detail` | Free |
| Activity feed | Recent jobs/events stream on the dashboard (installs, lifecycle actions, backups, alerts) | `cluster.activity_feed` | Free |
| Global search | Topbar search across apps, VMs, store entries, hosts, settings (`/` shortcut) | `ui.global_search` | Free |

## 2. Apps (installed workloads)

| Feature | Description | Flag key | Tier (inert) |
|---|---|---|---|
| Apps grid | Card grid of installed apps: icon, host, status, CPU/RAM bars, quick actions; filter by host/status, text filter; a discovered-but-unadopted panel above the grid surfaces pre-existing CTs found by the poller with catalog-match suggestions and a bulk Adopt affordance, so a fresh install against existing infra never shows an empty grid | `apps.list` | Free |
| App detail, overview | Resource usage, CT identity (host, CTID, IP), assigned storage, uptime, update badge | `apps.detail` | Free |
| Lifecycle | Start / stop / restart / shutdown an app (its CT) with job tracking | `apps.lifecycle` | Free |
| Open web UI | One-click open of the app's own web interface (detected/declared port) | `apps.open_ui` | Free |
| Logs | Live-following log view (CT console output + service journal), tabbed on app detail | `apps.logs` | Free |
| Console | In-browser terminal into the app's CT (xterm.js over Proxmox `termproxy`) | `apps.console` | Free |
| Install-script view/edit | View the pinned community script for this app; edit and save a local variant, versioned in `app_scripts`, diffed against upstream | `apps.script_edit` | Pro |
| Resource graphs | Per-app CPU/RAM/net/disk history charts (uPlot over MetricsStore rollups) | `apps.graphs` | Free |
| Adopt existing CT | Discover pre-existing LXC containers not yet mapped to an app and adopt them individually or in bulk; catalog-match suggestions offered from CT/script heuristics, manual override always available | `apps.adopt` | Free |
| Reconfigure | Change CT resources (cores, RAM, disk grow) from the app detail page | `apps.reconfigure` | Free |
| Uninstall | Destroy the app's CT with typed-confirmation and optional final backup | `apps.uninstall` | Free |

## 3. App Store

Source: community-scripts/ProxmoxVE, parsed **server-side only** directly
from the public `ct/*.sh` + `install/*.sh` script pairs in that GitHub repo,
cached in DB with ETag-based change detection (brief §5). **Correction to an
earlier assumption in this doc:** there is no public bulk catalog metadata
API to fetch instead, the community-scripts website's catalog is
PocketBase-backed behind its own Next.js frontend with no open read
endpoint (confirmed while grounding the Phase 4 plan in real code; see
`docs/superpowers/plans/2026-07-30-phase-4-store.md`'s header note, and
`docs/notes/phase-4-store.md` once Phase 4 lands). Installs run the script
as root on the node over the SSH executor, stated plainly in the consent
UX (brief §8).

Catalog ingest classifies every entry as **installable** (drivable
non-interactively within the one-CT constraint) or **unsupported**; only
installable entries are ever offered as install targets, unsupported entries
render with an honest note and an upstream link (doc 04 `catalog_entries`,
doc 11 §8). The classifier rule is mechanical, not a guess: single
`build_container` call in the paired `ct/` script, and no unguarded
interactive prompt (`read`/`whiptail`/`dialog` not preceded by an env-var
short-circuit) in the paired `install/` script, every community-scripts
install runs under a `set -e` + ERR-trap wrapper, so an unguarded prompt
hard-aborts rather than defaulting, making "unguarded prompt present" a
reliable unsupported signal (`docs/notes/phase-4-spike.md`). Applied to the
current upstream corpus this rule seats installable ≈ **493/559 (88.2%)**, 
the number Phase 4's definition of done reports (doc 10), replacing any
"300+ scripts" framing with the real figure.

**Known v1 gap, tracked rather than silently absorbed:** `ct/*.sh` reliably
yields `name`, resource defaults (`var_cpu`/`var_ram`/`var_disk`/`var_os`/
`var_version`), and a `website` link (the script's `# Source:` header
comment), but not `category`, `description`, `icon_url`, or `popularity`,
none of which are derivable from script content alone. Phase 4 ships a
small hand-maintained slug→category map (`proxploy/services/catalog_categories.py`)
as a v1 stopgap, defaulting unmapped entries to "Uncategorized";
`description`/`icon_url`/`popularity` stay null until a real source is
found. **Follow-up (not blocking Phase 4):** either find/negotiate a stable
read path into the community-scripts PocketBase content, or accept
hand-curating the map as ongoing catalog-maintenance cost and grow it
incrementally as real gaps surface in the store UI.

| Feature | Description | Flag key | Tier (inert) |
|---|---|---|---|
| Catalog browse | Tile grid of installable scripts with icon, description, resource defaults, upstream link; unsupported entries listed separately with an honest note + upstream link, never an Install control | `store.catalog` | Free |
| Search & categories | Text search plus category chips (media, networking, automation, monitoring, …) from upstream metadata | `store.search` | Free |
| Catalog refresh | Manual + scheduled server-side re-fetch with ETag; staleness indicator in UI | `store.refresh` | Free |
| Install to host | Pick target host, review resources + pinned script content + diff-vs-upstream, explicit root-consent step, then install | `store.install` | Free |
| Live install log | Streamed script output during install (SSE from job_events), archived permanently with the job | `store.install_log` | Free |
| Update detection | Per-app "update available" badges from catalog version metadata | `store.updates` | Free |
| Per-app update | Run the app's update entrypoint with the same pin/diff/consent/stream/archive treatment as install | `store.update` | Free |
| Update all | One action queuing sequential updates for every updatable app, with per-app results | `store.update_all` | Pro |
| Scheduled auto-updates | APScheduler-driven update windows (per app or global), with notification on result | `store.auto_update` | Pro |

## 4. Virtual Machines

| Feature | Description | Flag key | Tier (inert) |
|---|---|---|---|
| VM list | Table of VMs across hosts: name, host, status, specs, uptime; filters | `vms.list` | Free |
| Lifecycle | Start / stop / shutdown / reboot / pause / resume with job tracking | `vms.lifecycle` | Free |
| Console | noVNC console via Proxmox `vncproxy`/`vncwebsocket`, proxied with Proxploy auth | `vms.console` | Free |
| Snapshots | List / create / roll back / delete snapshots (with-RAM option surfaced) | `vms.snapshots` | Free |
| Create VM | Guided create: ISO/template pick, resources, storage, network, boot | `vms.create` | Free |
| Clone VM | Full/linked clone from an existing VM or template | `vms.clone` | Pro |
| VM graphs | Per-VM resource history charts | `vms.graphs` | Free |

## 5. Storage

| Feature | Description | Flag key | Tier (inert) |
|---|---|---|---|
| Datastore overview | All datastores across hosts: type, capacity, usage, content types, health | `storage.view` | Free |
| Content browser | Browse ISOs, templates, backups, disk images per datastore; upload ISOs/templates; delete content | `storage.content` | Free |
| Add/edit storage | Attach supported storage types (dir, NFS, CIFS, PBS, ZFS-over-API) to a host via Proxmox API | `storage.manage` | Pro |

## 6. Network

| Feature | Description | Flag key | Tier (inert) |
|---|---|---|---|
| Network overview | Bridges, bonds, VLANs, physical NICs per node; guest attachment map; live throughput | `network.view` | Free |
| Guest network config | Edit an app/VM's NIC (bridge, VLAN tag, firewall toggle, IP config) | `network.guest_config` | Free |
| Host network edit | Create/edit bridges and VLANs on a node with apply/rollback via Proxmox API | `network.host_config` | Pro |

## 7. Backups (PBS)

| Feature | Description | Flag key | Tier (inert) |
|---|---|---|---|
| PBS integration | Connect Proxmox Backup Server datastores; browse backup groups/snapshots with verify status | `backups.pbs` | Free |
| Run backup now | On-demand vzdump/PBS backup of an app, VM, or all guests, job-tracked | `backups.run` | Free |
| Scheduled backup jobs | Backup jobs with schedule, retention (keep-last/daily/weekly), target datastore, guest selection | `backups.schedule` | Free |
| Restore | Restore a guest from a PBS snapshot or vzdump archive, in place or as new CTID/VMID | `backups.restore` | Free |
| Backup notifications | Success/failure notifications per job via Notifier | `backups.notify` | Free |
| Retention & prune view | Show prune simulation and applied retention per backup group | `backups.retention` | Pro |

## 8. Migration

| Feature | Description | Flag key | Tier (inert) |
|---|---|---|---|
| Cross-host migration | Move an app or VM between managed hosts. Cluster-native `migrate` when hosts share a Proxmox cluster; PBS or vzdump+transfer backup/restore path when they don't, with honest downtime estimates in the UX (doc 11) | `migrate.cross_host` | Pro |
| Migration preflight | Target-capacity check, storage mapping, network mapping, estimated transfer size/time before commit | `migrate.preflight` | Pro |

## 9. Metrics & Alerting

| Feature | Description | Flag key | Tier (inert) |
|---|---|---|---|
| Metrics collection | 30s pollers per host writing `metric_samples`; 5m/1h rollups; retention pruning (brief §5) | `metrics.collect` | Free |
| History charts | uPlot charts on dashboard, node, app, and VM pages, range-selectable | `metrics.history` | Free |
| Alert rules | Threshold/state rules (CPU %, RAM %, disk %, guest down, host unreachable, backup failed) with duration and severity | `alerts.rules` | Pro |
| Alert lifecycle | Firing/resolved states, acknowledgement, alert history | `alerts.manage` | Pro |

## 10. Notifications

| Feature | Description | Flag key | Tier (inert) |
|---|---|---|---|
| Notification channels | Configure Apprise targets: ntfy, gotify, email, Telegram, Slack, generic webhook; test-send | `notify.channels` | Free |
| Event routing | Choose which event classes (jobs, alerts, updates, backups) go to which channels | `notify.routing` | Pro |
| In-app notifications | Bell/toast surface for job results and alerts inside the UI | `notify.inapp` | Free |

## 11. Jobs & Scheduling

| Feature | Description | Flag key | Tier (inert) |
|---|---|---|---|
| Job engine | Custom asyncio JobBackend: enqueue, status, cancel, persisted `jobs` + `job_events`; powers every state-changing action | `jobs.engine` | Core |
| Job log streaming | Live SSE stream of any running job's output; full archive after completion | `jobs.stream` | Free |
| Job history | Filterable history of all jobs with actor, target, result, duration, archived logs | `jobs.history` | Free |
| Scheduling | APScheduler 3.11 cron-like triggers feeding JobBackend: auto-updates, backups, catalog refresh, metric pruning. **Amendment, Phase 7, 2026-08-01, see `docs/notes/phase-7-operate.md`:** this row named "APScheduler 4"; no 4.x release exists, PyPI's maximum stable is 3.11.3 (verified 2026-08-01). | `sched.windows` | Free |

## 12. Consoles & Terminal

| Feature | Description | Flag key | Tier (inert) |
|---|---|---|---|
| CT terminal | xterm.js terminal to any app CT via proxied Proxmox `termproxy` websocket (no SSH needed) | `terminal.ct` | Free |
| Node shell | xterm.js shell on the PVE node itself, same PtyBridge, prominently audit-logged | `terminal.node` | Pro |
| VM console | (See §4) noVNC session, same ConsoleProxy seam | `vms.console` | Free |

## 13. Identity, Access & Teams

| Feature | Description | Flag key | Tier (inert) |
|---|---|---|---|
| Local auth | argon2 password hashing, server-side DB sessions, CSRF, per-IP rate limiting on auth endpoints | `auth.local` | Core |
| TOTP 2FA | pyotp-based TOTP enrolment with recovery codes | `auth.totp` | Free |
| OIDC SSO | Authlib OIDC login against any external IdP (Authelia, Keycloak, …); never bundled | `auth.oidc` | Pro |
| RBAC | pycasbin roles, owner, admin, operator, viewer; enforced on every API route | `rbac.roles` | Free |
| Teams | Casbin domains: group users into teams with scoped access to hosts/apps/VMs | `teams.rbac` | Pro |
| API tokens | Scoped, revocable personal/service tokens for the REST API, hashed at rest | `api.tokens` | Pro |

## 14. Secrets & Audit

| Feature | Description | Flag key | Tier (inert) |
|---|---|---|---|
| Secret store | Fernet/MultiFernet encryption of host credentials and SSH keys; master key in root-only file; rotation support | `secrets.store` | Core |
| Audit log | Append-only `audit_events` for every state-changing action (actor, action, target, params, result, timestamp); filterable viewer; export | `audit.log` | Core |
| Audit retention config | Configurable retention/export policy for audit events (never truncation below a floor) | `audit.retention` | Pro |

## 15. Entitlements & Licensing

| Feature | Description | Flag key | Tier (inert) |
|---|---|---|---|
| Entitlement client | `Entitlements.enabled(key)`; Ed25519-signed JWT from proxploy-api, offline-valid to `grace_until` (~30d), disk-cached; no license → built-in all-on map, zero network calls, forever | `ent.client` | Core |
| License management UI | Settings page: enter/refresh/remove license key, show tier + expiry + grace state | `ent.manage` | Core |

## 16. Platform & Delivery

| Feature | Description | Flag key | Tier (inert) |
|---|---|---|---|
| Onboarding wizard | First-run flow: admin account → add first host (token + optional SSH key) → TLS choice → land on Cluster | `platform.onboarding` | Free |
| Self-update | In-app update check + apply for Proxploy itself, with pre-update DB backup and rollback path (risks in doc 11) | `platform.self_update` | Free |
| Installer artifacts | One-line LXC installer, Docker/Compose, systemd unit, Caddy TLS setup | `platform.install` | Free |
| REST API + OpenAPI | Full REST surface (everything the UI does) with FastAPI-generated OpenAPI docs at `/api/docs` | `api.rest` | Free |
| Theming | Dark (default, prototype tokens) and light themes; per-user preference | `ui.theme` | Free |
| Settings | Hosts, users, teams, notifications, schedules, license, appearance, advanced (DB DSN, bind address, TLS) | `platform.settings` | Core |
| Opt-in error reporting | Off by default; explicit opt-in; never on the entitlement path | `platform.error_report` | Free |

---

## 17. Flag key index (canonical list)

`hosts.onboard` · `hosts.ssh_executor` · `hosts.single` · `hosts.multi` ·
`hosts.manage` · `cluster.overview` · `cluster.node_detail` ·
`cluster.activity_feed` · `ui.global_search` · `apps.list` · `apps.detail` ·
`apps.lifecycle` · `apps.open_ui` · `apps.logs` · `apps.console` ·
`apps.script_edit` · `apps.graphs` · `apps.adopt` · `apps.reconfigure` ·
`apps.uninstall` · `store.catalog` · `store.search` · `store.refresh` ·
`store.install` · `store.install_log` · `store.updates` · `store.update` ·
`store.update_all` · `store.auto_update` · `vms.list` · `vms.lifecycle` ·
`vms.console` · `vms.snapshots` · `vms.create` · `vms.clone` · `vms.graphs` ·
`storage.view` · `storage.content` · `storage.manage` · `network.view` ·
`network.guest_config` · `network.host_config` · `backups.pbs` ·
`backups.run` · `backups.schedule` · `backups.restore` · `backups.notify` ·
`backups.retention` · `migrate.cross_host` · `migrate.preflight` ·
`metrics.collect` · `metrics.history` · `alerts.rules` · `alerts.manage` ·
`notify.channels` · `notify.routing` · `notify.inapp` · `jobs.engine` ·
`jobs.stream` · `jobs.history` · `sched.windows` · `terminal.ct` ·
`terminal.node` · `auth.local` · `auth.totp` · `auth.oidc` · `rbac.roles` ·
`teams.rbac` · `api.tokens` · `secrets.store` · `audit.log` ·
`audit.retention` · `ent.client` · `ent.manage` · `platform.onboarding` ·
`platform.self_update` · `platform.install` · `api.rest` · `ui.theme` ·
`platform.settings` · `platform.error_report`

Provisional Pro set (inert until armed): `hosts.multi`, `apps.script_edit`,
`store.update_all`, `store.auto_update`, `vms.clone`, `storage.manage`,
`network.host_config`, `backups.retention`, `migrate.cross_host`,
`migrate.preflight`, `alerts.rules`, `alerts.manage`, `notify.routing`,
`terminal.node`, `auth.oidc`, `teams.rbac`, `api.tokens`, `audit.retention`.

To repeat the governing rule: **every one of these flags resolves ON today.**
The Free/Pro column is a pricing sketch stored as config on proxploy-api, not
behavior in the app. Arming it later is a config deploy, never a code change.
