# Proxploy: Security and Secrets Design

Status: planning. Governed by `00-decision-brief.md` §2 rule 6 and §8. Doc 02
summarizes; this doc is the detail. Standing rule restated up front: **no
hand-rolled cryptography anywhere**, every crypto operation below names the
library that performs it.

## 1. Principles

- Least privilege by construction: capabilities the user hasn't enabled get
  no credentials at all, not unused broad ones.
- Two channels to a node, never blurred: scoped Proxmox API token for
  API-shaped work; dedicated SSH key for script execution only (doc 02 §4).
- Encrypt every credential at rest; the database alone must never be enough
  to reach a node.
- Every state change leaves an append-only audit row.
- Locked-down defaults: safe out of the box, opt into exposure, never the
  reverse.
- Honesty over theater: the residual risks in §9 are documented, not hidden.
- Self-preservation: Proxploy refuses, or requires typed confirmation with
  an explicit warning for, destructive actions (stop, delete, migrate)
  against the CT or host it is itself running on, when detectable. A tool
  that can stop its own CT can brick its own recovery path.

## 2. Proxmox API token scoping

Per-host, per-capability API tokens; never root@pam password auth. Tokens
use Proxmox's privilege-separated mode (`--privsep 1`), so each token's
effective permissions are the intersection of its own ACLs, independent of
the backing user. One dedicated PVE user (`proxploy@pve`), one custom role
per capability, one token per enabled capability.

### Capability → PVE role mapping

| Capability | Custom role | PVE privileges | Used for |
|---|---|---|---|
| Read-only monitoring (always required) | `ProxployAudit` | `VM.Audit`, `Datastore.Audit`, `Sys.Audit`, `Pool.Audit`, `SDN.Audit` | Pollers, dashboard, metrics, Apps/VMs read views, storage/network read pages |
| Lifecycle | `ProxployLifecycle` | `VM.PowerMgmt`, `VM.Config.Disk`, `VM.Config.CPU`, `VM.Config.Memory`, `VM.Config.Network`, `VM.Config.Options`, `VM.Allocate`, `VM.Clone`, `VM.Snapshot`, `VM.Snapshot.Rollback`, `VM.Migrate`, `Sys.Modify`, `Datastore.Allocate`, `Datastore.AllocateSpace` | Start/stop/restart/pause, resource edits, snapshots, clone, cluster-native migration, CT/VM create-destroy (installs create CTs via script, but adoption/cleanup and VM creation go through the API); also node-level infrastructure this app edits on the guests' behalf: network bridge staging/apply/revert (`Sys.Modify`), attaching/editing/detaching a storage pool definition (`Datastore.Allocate`), and storage content writes -- ISO upload, stray volume delete (`Datastore.AllocateSpace`) |
| Console | `ProxployConsole` | `VM.Console`; `Sys.Console` only if the user opts into node shells | CT/VM console tickets (termproxy/vncproxy); node shell is a separate opt-in because it reaches the node itself, not a guest. On real hardware a node shell lands on the node's `/bin/login` prompt, not a root shell: `Sys.Console` gates reaching that prompt, it is not root access by itself |
| Backup | `ProxployBackup` | `VM.Backup`, `Datastore.AllocateSpace`, `Datastore.Audit` | vzdump/PBS backup + restore jobs, backup listing |

**Lifecycle is no longer guest-only, and that is a deliberate widening.** It
originally meant "things you do to a CT or VM". It now also carries three
node-level privileges (`Sys.Modify`, `Datastore.Allocate`,
`Datastore.AllocateSpace`) because the app edits node network bridges and
storage pool definitions, and writes storage content (ISO upload, stray volume
delete), on the guests' behalf. Those calls previously 403'd whichever token
was pasted, since no capability granted them.

Folding storage-content actions into lifecycle rather than minting a fifth
capability is a judgement call, recorded here so it is visible rather than
inferred: it keeps the operator-facing choice at four tokens, at the cost of
lifecycle granting more than its name suggests. If storage content ever needs
to be withheld separately from guest operations, this is the seam to split.

This table is implemented in `backend/proxploy/services/pveum.py::CAPABILITIES`,
transcribed from here rather than derived from application code. It is the
single source for both the generated script (step 2 below) and the enrolment
verifier (step 4), which imports its monitoring set from it; keeping them as
one table is what stops the wizard telling an operator to create a token the
wizard then rejects. Change this table and that module together.

**Storage:** `host_credentials.kind` carries the capability directly --
`api_token:monitoring` / `api_token:lifecycle` / `api_token:console` /
`api_token:backup` (`ssh_key` unchanged, it has no capability) -- rather than
a separate column. `UniqueConstraint(host_id, kind)` already gives "one
credential per (host, capability)" for free. `services/hostclient.py::
client_for_host(app, db, host, capability=...)` resolves the row for the
capability a call site actually needs (default `"monitoring"`, the one every
host is guaranteed to have) and raises `CapabilityNotConfigured` -- a typed,
named error, not a raw PVE 403 -- the moment a capability's token is missing,
before any network call. An install that predates this (a single
`kind="api_token"` row) is migrated to `api_token:monitoring` on upgrade;
lifecycle/console/backup are then simply "not configured" until the operator
adds them, the same state a fresh install reaches by ticking only Read-only
monitoring, not a broken one. See `.superpowers/sdd/host-token-privileges-
step-one-report.md` for the full sweep that closed the gap where node-level
operations (bridges, storage pools, storage content) had no capability that
actually granted what they needed.

ACLs are granted at path `/` with propagate by default (Proxploy is a
whole-host manager); users who want to scope Proxploy to a pool grant the
same roles on `/pool/<name>` instead, and the onboarding verifier (below)
reports exactly what it can see. Privilege names must be re-verified against
the target PVE major version at implementation time; PVE occasionally splits
privileges (as it did with `VM.Config.*`).

### Onboarding flow (least privilege, generated, verified)

1. User enters host URL + chooses capabilities (monitoring is mandatory;
   lifecycle/console/backup are checkboxes).
2. The wizard **generates a copy-paste `pveum` script** for exactly the
   chosen capabilities: create `proxploy@pve`, create the custom roles,
   grant ACLs to user *and* token (privsep tokens need their own ACLs),
   create one privsep token per capability. The user runs it in a node shell
   they already own, Proxploy never asks for root credentials, even
   transiently.
3. User pastes the resulting token id(s) + secret(s) into the wizard.
4. **Verification:** the app calls `GET /version` (connectivity + TLS), then
   `GET /access/permissions` per token and diffs the granted privilege set
   against the expected set for each capability, reporting both missing
   privileges (feature will fail) and surplus ones (user granted too much;
   we say so). Verification results are stored and re-checkable from
   Settings.
5. Secrets go straight into the SecretStore (§3); the plaintext never lands
   in a log, an audit row, or an unencrypted column.

Enabling a capability later re-enters the wizard for just that capability's
role + token. Disabling one deletes the stored token and tells the user which
`pveum` commands remove the role/token server-side.

TLS to Proxmox: a per-host self-signed fingerprint can be pinned at
onboarding (stored, compared on every connection) rather than globally
disabling verification. The backend implements the pin
(`HostIn.tls_fingerprint`, honoured on every `ProxmoxClient` call).

**The add-host form ships with certificate verification unchecked**, which
reverses this section's original "on by default". A stock Proxmox node serves
a self-signed certificate, so verifying by default failed the very first
connection for almost every operator, and the only escape hatch the form
offers is that same checkbox: the effective default was "the operator
unticks it", reached via a confusing failure instead of a decision.

This is a real weakening and is recorded rather than dressed up. The fix that
would let verification default back on is the pin above: the form does not
yet collect a fingerprint, so there is nothing for an operator to verify
*against* when the certificate is self-signed. Collecting it at probe time,
where the certificate is already in hand, is what closes this; until then the
unchecked box is the honest default rather than a broken one.

## 3. Encryption at rest

- **Library:** `cryptography`, Fernet (AES-128-CBC + HMAC-SHA256,
  authenticated) via `MultiFernet` for rotation. No other symmetric crypto
  in the codebase.
- **Master key file:** created at install by the installer, 
  `/etc/proxploy/master.key` (or the container-volume equivalent), owner
  `root:root` (or the service user where root isn't available), mode `0400`.
  The key never enters the database, environment variables, or logs. Losing
  it means re-entering credentials; the installer says this out loud and the
  docs recommend including it in host backups.
- **What's encrypted:** every `host_credentials` blob (API token secrets,
  SSH private key, pinned TLS fingerprints move with them), the cached
  entitlement token, SMTP/webhook credentials inside notification channel
  configs, OIDC client secrets. Column-level: ciphertext blobs in otherwise
  normal rows.
- **Key rotation procedure:** generate a new key → prepend to the key file
  (newest first) → app loads all keys into `MultiFernet` (encrypts with the
  first, decrypts with any) → run the built-in `proxploy rotate-secrets`
  job, which re-encrypts every stored blob under the new key → remove the
  old key from the file. Documented, scriptable, no downtime.
- **SecretStore seam:** `get / put / rotate` (brief §5). The Fernet-file
  implementation is the default and only day-one backend. **OpenBao** is the
  arm's-length swap-in (separate process, spoken to over its HTTP API; 
  MPL-2.0 stays outside our process) for teams that want an external KMS;
  nothing outside the SecretStore module may know which backend is active.

## 4. SSH key handling for the executor

**Phase 4 entry-gate spike (doc 10/11 §1) ran and confirmed: raw SSH-root is
structurally necessary, not merely the expected default.** Findings in full
at `docs/notes/phase-4-spike.md`: every community-scripts LXC install
creates its container with the host-local `pct create` CLI, never the
Proxmox REST API, and `root_check()` hard-exits anything that isn't root;
independently, Proxmox's REST API has no LXC equivalent of the QEMU
guest-agent `exec` endpoint at all, `pct exec`/`pct push` are host-CLI-only.
So there is no non-interactive or API-drivable path that removes the need
for a root shell, at either the container-creation step or the
install-script-execution step. The design below ships as originally
planned.

- One **dedicated ed25519 keypair per Proxploy install** (generated with
  `cryptography`'s Ed25519 primitives or `asyncssh.generate_private_key`, 
  library-generated either way, never shelling out to ssh-keygen), created at
  first host onboarding. Private key lives only as a SecretStore-encrypted
  blob; it is never written to disk in plaintext and never leaves the app
  process (asyncssh loads it from memory).
- During host onboarding the wizard displays the **public** key and the
  exact `authorized_keys` line to add for root on the node, ideally
  restricted (`from="<proxploy-ip>"`). The user authorizes it themselves;
  Proxploy never self-installs its key.
- The key is used **only** by the `SSHExecutor` for install/update/migration
  script execution (doc 02 §6). No console path, no ad-hoc command runner,
  no other module imports the SSH client. This is enforced structurally (the
  key is retrievable only through the executor's own SecretStore handle)
  **and mechanically in CI**: an import-graph lint fails the build if any
  module outside `executor/` imports the SSH client or calls the SecretStore
  accessor that returns the SSH key (doc 09), a hard structural rule, not a
  convention. `executor/` also carries the repo's highest test-coverage bar
  and tightest review requirement, unit tests plus integration tests
  against a throwaway PVE (doc 10 Phase 1/4), because it is the one
  component holding root-on-node power.
- **Every use is audit-logged:** one `audit_events` row per SSH invocation
  (actor, host, job id, script hash, result), and the full session output is
  archived in `job_events`.
- Host key verification: the node's SSH host key is recorded on first
  onboarding (trust-on-first-use, shown to the user for confirmation) and
  pinned; a changed host key hard-fails the executor with an explicit
  re-verification flow, never an auto-accept.
- Rotation: regenerate keypair → wizard shows the new public key per host →
  user swaps `authorized_keys` → old key destroyed from the SecretStore.

## 5. Session and auth hardening

| Concern | Design | Library |
|---|---|---|
| Password hashing | argon2id, library defaults for memory/iterations, per-hash salt (built into the format) | `argon2-cffi` |
| Sessions | Server-side sessions in the `sessions` table: random 256-bit id (`secrets.token_urlsafe`), hashed at rest, absolute + idle expiry, listable and revocable per user ("sign out everywhere") | stdlib `secrets` |
| Cookies | `Secure`, `HttpOnly`, `SameSite=Lax`, host-only; session id is the only auth cookie | Starlette |
| CSRF | SameSite=Lax as the base + double-submit token required on all state-changing requests (the SPA sends it as a header); WebSocket upgrades validate `Origin` | Starlette middleware + stdlib `secrets`/`hmac.compare_digest` for comparison |
| Rate limiting | Per-IP on `/api/auth/*` (login, TOTP verify, password reset) | `slowapi` |
| Lockout/backoff | Per-account exponential backoff after repeated failures (temporary lock with honest UI messaging, not silent failure), independent of the per-IP limit so a distributed guess still hits the account wall | app logic over the same counters table |
| TOTP | Standard TOTP enrollment (QR + manual secret), secret stored via SecretStore, recovery codes generated with `secrets` and stored argon2-hashed, one-time use | `pyotp` |
| OIDC | Authorization-code flow with PKCE against any standard IdP (Authelia, Keycloak, Entra, …); supported *through* OIDC, never bundled; JIT user provisioning mappable to roles | `Authlib` |
| Login auditing | Every success/failure/lockout/TOTP event is an `audit_events` row | n/a |

All authenticated randomness comes from `secrets`; all secret comparisons use
`hmac.compare_digest`. Nothing rolls its own.

## 6. RBAC via pycasbin

- Model: RBAC **with domains**, teams are casbin domains, so a user can be
  `admin` of team A and `viewer` of team B.
- Roles (brief §5): **owner** (everything, incl. billing/license, destructive
  host removal, role grants), **admin** (everything operational incl. host
  onboarding, installs, node shells, user management within the team),
  **operator** (lifecycle, installs, consoles, backups; no user/host/
  credential management), **viewer** (read-only, no consoles).
- Enforcement point: one FastAPI dependency, 
  `authorize(resource, action)` → `enforcer.enforce(user, team, resource,
  action)`, stacked with the session and entitlement dependencies on every
  route (doc 07 §2). Resources are typed object references
  (`host:3`, `app:12`), actions are verbs (`read`, `lifecycle`, `console`,
  `install`, `manage`).
- Policies live in the `casbin_rules` table (casbin's SQLAlchemy adapter);
  policy mutations are themselves audited state changes, permitted only to
  owner/admin.
- Console note: node-shell access requires admin+ **and** the opt-in
  `Sys.Console` token from §2, RBAC and token scoping fail independently.

## 7. Append-only audit log

- Table: `audit_events(id, ts, actor_type[user|api_key|system], actor_id,
  action, target_type, target_id, params, result[ok|error|denied], ip,
  request_id, job_id)`; full schema in doc 04. Written for every state-changing operation,
  every auth event, every SSH invocation, every policy change, every denied
  attempt (denials are evidence too).
- **One delete path, and it is itself audited.** `DELETE /audit`
  (`api/audit.py::clear_audit`) is the only endpoint that removes rows.
  Amended from "no delete path in the API or UI": operators asked to be able to
  clear the log, and a product that answers that by telling them to open the
  SQLite file gets a worse outcome than one that puts the capability behind a
  gate and records its use. The gate, in full:
  - **Owner only.** `("audit", "clear")` in `services/authz.py`, the same floor
    as `host.remove`. An admin can read and export the log; erasing it is a
    different question. A refused attempt is recorded as `audit.clear` +
    `denied`, which is why it is its own permission and not a reuse of
    `("audit", "export")`.
  - **Typed confirmation.** The caller must send `confirm: "clear audit log"`,
    the same 409 `confirm_required` shape the app uninstall and the in-place
    restore use, so a single click cannot empty the trail.
  - **The clear is audited, and the row survives it.** One `audit.clear` row is
    written *after* the delete, naming the actor, the count removed and whether
    the scope was `all` or everything `before` a given instant. Written before
    the delete it would sit inside the range it describes and go with it,
    leaving an empty table and no author.
  - **Not wired to the screen's filters.** `before` is the only narrowing the
    route accepts. "Clear what I am looking at" stops being unambiguous the
    moment a filter is a substring match.
  - Retention (clear entries older than a date) is the intended use and is
    strictly less destructive than emptying the table; both are offered, and
    the audit row says which was used.
- `params` is written through a redaction filter so secrets never enter the log
  in the first place (nothing sensitive to purge later).
- Retention **by archival, not deletion** is still the design, and is still
  unbuilt: there is no `audit.retention` setting and no archival job today, and
  the only pruning job that exists ("Usage cleanup", `metrics.maintain`) touches
  metric samples and rollups, never `audit_events`. Until it lands, `DELETE
  /audit` with `before` is the only retention an operator has, and it deletes
  without archiving. Off by default (doc 04:
  operator-initiated `proxploy audit export`). When the operator opts into a
  retention window (`audit.retention`), a scheduled job exports rows older
  than the window to compressed JSONL files in an archive directory, then
  prunes only rows that verifiably made it into a completed archive, never
  below a floor. Archives are kept until the operator removes them at the
  filesystem level, outside the app, deliberately.
- Honest limit: with app-DB-level access an attacker can touch the table;
  the DB file permissions (§8) are the boundary, and shipping archives off-
  box is the recommended hardening for anyone who needs tamper evidence.

## 8. Locked-down defaults

- **Bind:** LAN/private interface by default (installer detects and
  confirms), never `0.0.0.0` silently.
- **TLS by default:** Caddy in front (arm's-length, installer-managed) or,
  if declined, the app serves TLS itself with a self-signed cert generated
  via `cryptography` (x509 builder), plain HTTP only ever behind a
  localhost reverse-proxy hop.
- **No telemetry.** The only outbound calls the app can make: Proxmox nodes,
  the catalog upstream (+optional mirror), Apprise notification targets the
  user configured, and proxploy-api iff a license is configured (doc 07 §6).
  Error reporting is opt-in and off by default (brief §10 phase 9).
- **No internet exposure guidance:** docs state plainly that Proxploy is
  designed for LAN/VPN access (Tailscale/WireGuard recommended), because a
  reachable Proxploy is a credential store for your nodes (§9). Exposing it
  publicly is the operator's explicit choice, made against our advice.
- File permissions: master key `0400`, SQLite DB + secrets dir `0700`
  service-user-owned, archives likewise.
- First-run: forced owner-account creation on first visit (no default
  credentials anywhere), TOTP prominently offered.

## 9. Threat model

| # | Threat | Mitigations | Honest residual risk |
|---|---|---|---|
| 1 | Malicious/compromised community install script runs as root on a node | Server-side catalog cache; script content pinned + diffed against upstream before every run with confirmation on drift; full output archived; per-run audit row with script hash; provenance visible in UI | **Root is root.** A malicious script owns the node. Identical to running it yourself, Proxploy adds provenance and evidence, not sandboxing. Review before you run remains the real control. |
| 2 | Proxploy host itself compromised | Encrypted secrets (DB alone insufficient); root-only key file; LAN-bind + TLS defaults; minimal attack surface (one process); audit trail of what the attacker did with our channels | **A compromised Proxploy host equals compromised credentials to every connected node.** Blast radius limiters: per-capability tokens (a monitoring-only install leaks only read access), SSH key restricted to script exec and revocable per node in `authorized_keys`, OpenBao seam moves keys off-box. It cannot be eliminated, the product's job is holding these credentials. |
| 3 | Stolen DB file / backup | Fernet-encrypted credential blobs (`cryptography`); master key stored outside the DB; session ids hashed at rest | Metadata (hostnames, app inventory, audit history) is readable. Encrypt backups. |
| 4 | Stolen master key file alone | Useless without the DB; root-only 0400 perms | Key + DB together = full credential compromise (= threat 2). |
| 5 | Credential theft in transit to nodes | TLS to Proxmox with verification/pinned fingerprints; SSH host key pinned (TOFU + hard-fail on change) | First-use pinning trusts the first connection; onboarding shows fingerprints for manual verification. |
| 6 | Auth brute force / credential stuffing | argon2id, per-IP rate limit (slowapi), per-account backoff/lockout, TOTP, audit of failures | Password reuse by users; TOTP is offered, not forced. |
| 7 | Session theft / XSS / CSRF | HttpOnly+Secure+SameSite cookies, server-side revocable sessions, CSRF tokens, React's default escaping, no third-party script tags, Origin-checked websockets | A future XSS bug can still act with the victim's session (cookies unreadable, requests forgeable in-page); short idle expiry + audit limit the window. |
| 8 | Privilege escalation inside Proxploy (operator → admin actions) | pycasbin checks on every route; policy changes audited and owner/admin-only; consoles double-gated (RBAC + token scope) | Casbin policy misconfiguration by an owner is possible; the audit log records who changed policy. |
| 9 | Console misuse (a console is a root shell in the CT; a node shell lands on the node's `/bin/login`) | Separate `Sys.Console` opt-in token; admin+ RBAC for node shells; every console open audited; idle timeout; single-use short-TTL bridge handles | Console I/O contents are not recorded (a deliberate privacy call); the audit log shows who had a shell where and when, not what they typed. |
| 10 | Catalog upstream compromise (poisoned metadata/scripts) | Server-side fetch over TLS from the pinned upstream repo; cached copies mean a compromised upstream doesn't instantly propagate; pin+diff surfaces unexpected changes before any run | We do not cryptographically verify upstream authorship (upstream doesn't sign); a compromised upstream repo plus a user clicking through the diff runs attacker code as root, see threat 1. |
| 11 | Entitlement forgery / tampering | Ed25519-signed tokens (PyJWT), public-key-only in the app, offline verification, `kid` rotation | Self-hosted code can be patched to bypass gates entirely. Accepted per brief §11, the moat is signed tokens + honesty, not DRM. |
| 12 | Malicious insider with a legitimate role | Least-privilege roles, append-only audit (denials included), archival off-box recommended; the one clear path is owner-only, typed-confirmed and records its own use (§7) | An owner is trusted by definition and can clear the log, leaving one `audit.clear` row naming them; the log is evidence, not prevention. |
| 13 | Supply chain (our own dependencies) | Pinned + hash-locked dependency versions, small curated set (doc 03), license/provenance review per brief §3, no post-install script execution from deps | Same residual every Python app has; pinning narrows the window, doesn't close it. |
| 14 | Proxploy stops/deletes/migrates its own CT or host | Self-detection recorded at install (CT id + hostname, doc 02 §9); destructive actions against a detected match are refused, or gated behind a typed-confirmation dialog with an explicit warning | Detection can miss edge cases (Proxploy relocated without re-detection, ambiguous hostname); the typed-confirmation prompt is the backstop even when automatic detection fails. |

## 10. Crypto operations index (one library per operation, no exceptions)

| Operation | Library |
|---|---|
| Secrets at rest (encrypt/decrypt/rotate) | `cryptography` Fernet / MultiFernet |
| Password hashing | `argon2-cffi` (argon2id) |
| Entitlement token sign/verify | `PyJWT` (EdDSA/Ed25519; sign on proxploy-api, verify in-app) |
| SSH transport + ed25519 keygen | `asyncssh` (+ `cryptography` primitives) |
| TOTP | `pyotp` |
| OIDC/OAuth flows, JWKS | `Authlib` |
| Self-signed TLS cert generation | `cryptography` x509 |
| TLS termination (default form) | Caddy (arm's-length process) |
| Random tokens (sessions, CSRF, recovery codes) | stdlib `secrets` |
| Constant-time comparison | stdlib `hmac.compare_digest` |
