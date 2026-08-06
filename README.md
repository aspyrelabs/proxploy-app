# Proxploy

Self-hosted web UI for managing Proxmox VE — "Unraid's experience, for
Proxmox." Backend is FastAPI + SQLAlchemy (`backend/`), frontend is React 19
+ Vite + TanStack Router (`frontend/`).

This repository, `proxploy-app`, is **the product**: backend, frontend, and
installer ship together as one versioned release artifact that installs onto
a customer's own Proxmox host (or a plain Debian box, or via Docker). It is
**not** a hosted service and there is nothing here to deploy to Coolify or
any other PaaS — see `docs/09-repository-structure.md` for why the app,
API, web, and docs are four separate repos with four separate deployment
models.

For the product spec, architecture, data model, API surface, and security
design, start at `docs/00-decision-brief.md` and read `docs/01` through
`docs/11` in order. Phase-by-phase build notes live in `docs/notes/`.

## Status, stated plainly

- **The repository is private.** It becomes public when the project is
  ready to publish a release (`docs/11-risks-open-decisions.md` §6).
- **No release has been published yet.** The installer
  (`curl -fsSL https://proxploy.com/install.sh | bash`) is fully built and
  tested, but there is nothing at that URL to fetch: it will 404. The
  compiled-in release public key at `backend/proxploy/release_pubkey.pem` is
  still a **placeholder** and the matching release private key does not
  exist. `docs/runbooks/publishing-a-release.md` is the runbook that
  generates the real keypair and cuts the first real release — do that
  before pointing anyone at the one-liner.
- **The database defaults to SQLite in WAL mode**, with Postgres available
  via `PROXPLOY_DB_URL`. That's deliberate for a self-hosted, single-box
  product, not a gap to close.
- **There is no live Proxmox host in development.** The backend test suite
  runs against `FakePVE` (`backend/tests/`), and the Playwright e2e suite
  runs against a fake PVE/SSH server (`backend/tests/e2e_server.py`).

## Install / deploy

Proxploy has three install shapes, all built in Phase 9a
(`docs/notes/phase-9a-install-update.md`, `install.sh --help`). None of them
apply to *this* repo as a hosted deployment — they're how the product lands
on a customer's own hardware.

### 1. LXC on a Proxmox node (the one-liner)

```bash
curl -fsSL https://proxploy.com/install.sh | bash
```

Run on a Proxmox VE node (detected via `pct` + `/etc/pve`), this creates a
CT and installs Proxploy inside it — OS packages, a dedicated system user, a
versioned release layout under `/opt/proxploy/releases/<version>/`, the
`proxploy.service` systemd unit, and Caddy in front with a real Let's
Encrypt certificate (`--hostname`) or a self-signed `tls internal` cert
otherwise. See "Status" above: this doesn't work until a release is
published.

### 2. systemd on a plain Debian box

```bash
curl -fsSL https://proxploy.com/install.sh | bash -s -- --shape systemd
```

Same install, minus the CT-creation step — for a bare Debian 12 host or VM
that isn't itself a Proxmox node.

### 3. Docker / Compose

```bash
cd packaging/docker
docker compose up -d
```

`packaging/docker/Dockerfile` builds the frontend, then an editable install
of the backend into a slim Python image; `packaging/docker/compose.yml`
maps port 8006 on the host to 8000 in the container and persists
`/var/lib/proxploy` in a named volume. **This shape deliberately cannot
self-update** — a container replacing its own image from inside is how you
lose the container. `POST /meta/update` returns `409` with the fix:

```bash
docker compose pull && docker compose up -d
```

The update card in the UI states this rather than hiding the button.

## Environment variables

All settings are `pydantic-settings`, prefix `PROXPLOY_`, defined in
`backend/proxploy/config.py`. Defaults shown are what a plain dev checkout
gets; the installer and Docker image override the relevant ones.

| Variable | Default | Purpose |
|---|---|---|
| `PROXPLOY_DB_URL` | `sqlite:///./data/proxploy.db` | Database DSN. SQLite (WAL) by default; any SQLAlchemy-supported Postgres DSN also works. |
| `PROXPLOY_DATA_DIR` | `./data` | Root for the SQLite file, uploads, and other on-disk state. |
| `PROXPLOY_MASTER_KEY_FILE` | `./data/master.key` | Root-only Fernet key file backing `SecretStore` (encrypts stored credentials). |
| `PROXPLOY_SESSION_COOKIE` | `pp_session` | Session cookie name. |
| `PROXPLOY_CSRF_COOKIE` | `pp_csrf` | CSRF cookie name. |
| `PROXPLOY_SESSION_TTL_HOURS` | `168` | Session lifetime. |
| `PROXPLOY_COOKIE_SECURE` | `false` | Set by the installer once TLS terminates in front of the app. |
| `PROXPLOY_API_BASE_URL` | `https://api.proxploy.com` | Aspyre entitlements/licensing API base URL. |
| `PROXPLOY_ENT_EXTRA_KEYS_FILE` | unset | Extra entitlement verification keys, if any. |
| `PROXPLOY_CATALOG_SLUGS` | built-in app-store list | App Store catalog slugs. |
| `PROXPLOY_POLL_ENABLED` | `true` | Background Proxmox poller on/off. |
| `PROXPLOY_POLL_INTERVAL_S` | `30.0` | Poller interval. |
| `PROXPLOY_POLL_TIMEOUT_S` | `20.0` | Poller per-call timeout. |
| `PROXPLOY_CONSOLE_TICKET_TTL_S` | `30.0` | VNC/term console ticket lifetime. |
| `PROXPLOY_CONSOLE_IDLE_TIMEOUT_S` | `1800.0` | Console idle disconnect timeout. |
| `PROXPLOY_STORAGE_UPLOAD_MAX_BYTES` | `16 GiB` | Max ISO upload size (also caps transient free disk needed). |
| `PROXPLOY_PVE_TASK_TIMEOUT_S` | `3600.0` | Wall-clock ceiling for disk-copy-bound PVE jobs (clone, backup, restore, upload). |
| `PROXPLOY_BACKUP_SYNC_STALE_S` | `900.0` | How stale a backup-sync snapshot can be before it's refreshed. |
| `PROXPLOY_SCHEDULER_ENABLED` | `true` | Cron-style job scheduler on/off. |
| `PROXPLOY_SCHEDULER_TICK_S` | `30.0` | Scheduler poll tick. |
| `PROXPLOY_ALERTS_ENABLED` | `true` | Alert evaluation on/off (poller still writes samples either way). |
| `PROXPLOY_OIDC_DEFAULT_ROLE` | unset (`None`) | If set, auto-provisions this role for first-time OIDC sign-ins; unset means new OIDC users are inactive until an admin activates them. |
| `PROXPLOY_OIDC_DEFAULT_TEAM_SLUG` | `default` | Team new OIDC users are provisioned into. |
| `PROXPLOY_TOTP_PENDING_TTL_S` | `300.0` | How long a pending-2FA token stays redeemable. |
| `PROXPLOY_MIGRATE_ASSUMED_BPS` | `80e6` | Assumed LAN transfer rate used only for the migration preflight estimate. |
| `PROXPLOY_RELEASE_CHANNEL_URL` | GitHub releases URL | Base URL of the release channel (manifest + signed tarball). |
| `PROXPLOY_RELEASE_PUBKEY_FILE` | unset (uses the key shipped in the package) | Path to a release public key, to verify against a non-default key. |
| `PROXPLOY_INSTALL_SHAPE` | unset | Set by the installer in `/etc/proxploy/proxploy.env`; unset means a dev checkout (self-update `check` works, `apply` refuses). |
| `PROXPLOY_UPDATE_SCRIPT` | `/opt/proxploy/bin/proxploy-update` | Path to the updater script `POST /meta/update` runs via `systemd-run`. |
| `PROXPLOY_UPDATE_TIMEOUT_S` | `600.0` | Timeout for the self-update run. |
| `PROXPLOY_SELF_CTID` | unset | CT id of Proxploy's own container, written by the installer so it can recognise (and refuse to destroy) itself. |

Two more variables exist outside the `Settings` class:

- **`PROXPLOY_IN_DOCKER`** — checked directly (`services/updater.py`), set to
  `1` by `packaging/docker/Dockerfile`. Forces `detect_shape()` to report
  `docker`, which is what makes `POST /meta/update` refuse to self-apply.
- **`PROXPLOY_TEST_PG_DSN`** — test-only, read by
  `backend/tests/test_migrations.py`. Unset, the Postgres half of the
  dual-DB migration tests is skipped; the `backend-postgres` CI leg
  (`.github/workflows/ci.yml`) sets it to a local `postgres:16` service
  container and runs the full suite against both DBs.

The Playwright e2e harness (`frontend/playwright.config.ts`) sets its own
throwaway environment for the backend it spawns: `PROXPLOY_DATA_DIR` and
`PROXPLOY_DB_URL` pointed at a scratch `.e2e-data/` directory,
`PROXPLOY_MASTER_KEY_FILE` alongside it, and
`PROXPLOY_POLL_ENABLED=PROXPLOY_SCHEDULER_ENABLED=PROXPLOY_ALERTS_ENABLED=false`
so the app doesn't try to reach a Proxmox host that isn't there.

## Development

### Backend

```bash
cd backend
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/uvicorn --factory proxploy.main:create_app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev   # vite dev server on :5173, proxies /api to :8000
```

### Tests

Backend (unit + integration, excludes the two suites below):

```bash
cd backend
.venv/bin/python -m pytest tests/ -q -m "not pve_integration and not e2e"
```

`pve_integration` needs a disposable live Proxmox host
(`PROXPLOY_TEST_PVE_*`) that doesn't exist in this environment; pytest's
`e2e` marker is a cross-repo roundtrip against a local `proxploy-api`, not
the Playwright suite below — don't confuse the two.

Frontend unit tests — **the `--no-file-parallelism` flag is required**;
suites flake under vitest's default parallelism on this box:

```bash
cd frontend
npx vitest run --no-file-parallelism
```

End-to-end (real Chromium via Playwright, against
`backend/tests/e2e_server.py`'s fake PVE/SSH — spins up its own backend and
frontend dev server, see `frontend/playwright.config.ts`):

```bash
cd frontend
npx playwright test
```

## Cutting a release

Not part of day-to-day development — see
`docs/runbooks/publishing-a-release.md` for the full procedure (generate
the release keypair, make the repo public, build the signed artifact with
`packaging/build_release.sh`, publish the GitHub release, verify against a
clean box).
