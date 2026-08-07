# Phase 9a: Install & Update (design)

**Date:** 2026-08-05
**Status:** approved, ready for implementation planning
**Scope:** installers (LXC one-liner, Docker/Compose, systemd unit, Caddy TLS)
and self-update (check, apply, rollback) for `proxploy-app`.

---

## Why this is 9a and not Phase 9

Doc 10's Phase 9 covers seven workstreams across four repos: installers,
self-update, onboarding polish, `proxploy-api` hardening, a marketing site, a
docs site, and opt-in error reporting. Every prior phase was one plan in one
repo. Phase 9 is decomposed into four sub-phases, each with its own
spec → plan → implement cycle:

| Sub-phase | Scope |
|---|---|
| **9a** (this spec) | Installers; self-update with backup, switch-over and rollback |
| 9b | Onboarding wizard full flow, empty states, error states (closes finding F1), light-theme QA |
| 9c | `proxploy-web` marketing/download site; `proxploy-docs` install, trust model, OpenAPI reference, per-feature guides |
| 9d | `proxploy-api` rate limiting, key rotation runbook, monitoring; opt-in error reporting |

Order is 9a → 9b → 9c → 9d. 9a carries the phase's Definition of Done; 9c
cannot be written honestly until the installer it documents exists.

**Phase 9a's slice of the doc-10 DoD**: *"a stranger installs via the
one-liner on a clean PVE box … and self-updates to the next tagged release, 
without reading source code."* The onboarding, app-install, VM-create and
backup-schedule clauses of that sentence are already shipped (Phases 4–7) or
belong to 9b.

---

## Decisions settled during design

### D1: Release channel: public repo + GitHub Releases

Artifacts live in GitHub Releases on `aspyrelabs/proxploy-app`, which becomes
public (matching the source-available posture stated in doc 11:165). The
one-liner fetches `install.sh`; the installer and updater fetch a tarball plus
`manifest.json` and `manifest.json.sig` from the release.

Channels are expressed with GitHub's existing prerelease flag, `latest` is
**stable**, prereleases are **edge**; which gives doc 11:297's staged rollout
without building a channel service.

**Rejected:** serving artifacts from `proxploy-api` (puts the update path on
licensing infrastructure and makes us a CDN), and a split
artifacts-on-GitHub / channel-resolved-by-api design (two systems must agree
before any user can update).

### D2: Artifact signing: a separate Ed25519 release key

Doc 11:300 leaves the signing scheme explicitly deferred. Resolved: a
**dedicated release keypair, never the entitlement key.** A leaked release key
must not also be able to mint entitlements, and the two rotate on different
cadences.

The release **public** key ships inside the release artifact, so rotating it
requires publishing a release, the same bootstrap constraint doc 09:153–156
already records for the entitlement key. Named here so it is a known property
rather than a discovery.

The private key never touches this repo or CI secrets during 9a; it is
generated offline as part of the publication runbook (D4).

### D3: Self-update applies to LXC and systemd installs only

`install_shape` (`lxc` | `systemd` | `docker`) is detected once at boot and
reported by the API.

- **lxc / systemd**: full in-app apply: pre-update backup, new versioned
  directory, switch-over, health check, automatic rollback.
- **docker**: the update is detected and displayed, with the exact
  `docker compose pull && docker compose up -d` to run on the host and a link
  to the release notes. **The app never rewrites its own image.**

**Rejected:** uniform self-update including Docker via a mounted Docker
socket. Mounting the socket gives the container host-root-equivalent
authority, which contradicts the locked-down-defaults posture doc 10 sets for
this phase. A capability the product declines to have is not a gap.

### D4: 9a builds and proves; publication is a separate gated runbook

9a implements the installer, the manifest format, the signer, the update check
and the apply path, and proves the whole upgrade and rollback cycle against a
**local file-served release channel signed with a throwaway test key.**

Making the repository public, generating the real release keypair, and cutting
`v1.0.0` are a documented runbook the maintainer executes. No outward-facing
action happens as a side effect of implementation.

---

## Architecture

### On-disk layout (lxc and systemd shapes)

```
/opt/proxploy/
  releases/
    1.0.0/{backend/, frontend/dist/, venv/}    immutable once written
    1.0.1/{backend/, frontend/dist/, venv/}
  current -> releases/1.0.1                    the only mutable pointer
  bin/proxploy-update                          the updater (see below)
/var/lib/proxploy/
  proxploy.db, master.key, uploads/            data; never touched by an update
  pre-update/<version>/                        backup taken before each apply
/etc/proxploy/proxploy.env                     settings; survives updates
/etc/systemd/system/proxploy.service           ExecStart points at current/
```

Three properties this layout buys:

1. **Rollback is a pointer swap.** The previous release directory is still
   there, intact, with its own venv.
2. **The venv is per-release** because dependencies change between versions. A
   shared venv would make rollback a reinstall, which is exactly the fragile
   path doc 11:286 warns against.
3. **`main.py:167` already resolves the SPA at `parents[2]/frontend/dist`,**
   so this layout matches the code as written, no path rework.

Data and secrets live outside `releases/` entirely, so "never update in
place" holds structurally rather than by discipline.

### The updater is a standalone script

**The problem it solves:** a process cannot swap its own code, restart itself,
and still be around to observe whether the result is healthy. Anything that
tries becomes a state machine spanning a restart, in the one code path where
being wrong strands the user.

`proxploy-update` is therefore a plain shell script installed at
`/opt/proxploy/bin/proxploy-update`. The API route validates the request and
launches it **detached via `systemd-run`**, outside the app's cgroup, so
restarting the app does not kill the thing performing the restart. The script
owns the entire sequence:

```
preflight   disk space; install_shape is lxc|systemd; no update already running;
            target version > current unless --force
backup      DB copy (SQLite file copy / pg_dump) + master.key copy
              -> /var/lib/proxploy/pre-update/<current-version>/
download    tarball + manifest.json + manifest.json.sig from the channel
verify      Ed25519 signature over the manifest, then sha256 of each artifact
            against that signed manifest  (refuse on any mismatch)
unpack      -> releases/<new>/ ; create venv; install deps
migrate     alembic upgrade head
switch      symlink current -> releases/<new> ; systemctl restart proxploy
healthcheck GET /meta/health until timeout
rollback    on any failure after switch: symlink back, restore DB, restart,
            record the reason
```

The UI observes the outcome by polling `/meta/version` until it changes or the
timeout expires; on timeout it says it lost contact with the server, which is
the truth, rather than reporting success it cannot know.

The manual path, running `proxploy-update --to 1.1.0` by hand, or re-running
the installer, always works and is what the docs (9c) present first, per
doc 11:295.

### Installer

`install.sh` is one script with two halves, because the one-liner does two
separable things.

**PVE-host half** (only when run on a Proxmox node): pick storage and bridge,
`pct create` a Debian container, then run the in-container half inside it.

**In-container half** (also the bare-systemd path): install runtime deps,
create the layout above, fetch and verify the release, write
`/etc/proxploy/proxploy.env`, install and enable the systemd unit, configure
TLS, print the URL and the first-run instruction.

**Locked-down defaults**, per doc 10: the app binds `127.0.0.1`, Caddy fronts
it on `:443`, and TLS is on with no opt-out flag in 9a.

**Caddy stays arm's-length** (doc 00:47): the installer writes a Caddyfile and
runs Caddy as its own service, using `tls internal` for the self-signed
fallback when no public hostname is available. We never link or vendor its
code.

### API surface added

| Route | Purpose |
|---|---|
| `GET /api/v1/meta/update` | current version, latest in channel, `install_shape`, whether in-app apply is available, release notes URL |
| `POST /api/v1/meta/update` | launch the updater (lxc/systemd only; 409 on docker with the compose command in the body) |

Both are `settings`-domain authorized through the existing `authorize()` path
established in Phase 8, this spec adds no new authorization concept. The
update check reuses the existing entitlement-refresh pattern for outbound HTTP.

### Version, single source of truth

`0.1.0` is currently hardcoded in both `backend/proxploy/__init__.py` and
`backend/pyproject.toml`. 9a makes one of them authoritative, has the other
read it, and moves the product to `1.0.0`. The release process reads the same
value, so a tag, a manifest and `/meta/version` cannot disagree.

---

## Verification

No Proxmox host exists on the build machine, and no VM harness is being built.
The proof splits along the same line the installer does: the in-container half
runs **for real**, and the PVE half runs against a fake `pct`.

| Property | How it is proven |
|---|---|
| Install works | `install.sh` runs in a clean Debian container with systemd: unit active, `/meta/health` answers over TLS, a second run is idempotent (no duplicate units, no clobbered data) |
| PVE half | fake `pct` on `PATH`; assert the create arguments, storage and bridge selection |
| Upgrade works | local file-served channel: 1.0.0 → 1.0.1, version changes, DB intact, pre-update backup present |
| Rollback works | poisoned 1.0.2 whose health check fails → automatic revert to 1.0.1, DB restored, failure reason recorded |
| Signature enforcement | bad signature, tampered sha256, unknown signing key, and downgrade attempt each rejected |
| Docker shape | update is detected and the compose command rendered; the apply route 409s |
| Scripts | `shellcheck` clean on every shipped script |

**Stated limitation, to be carried into the phase notes:** no real Proxmox node
and no real GitHub release channel took part. The PVE half is proven against a
fake `pct`, and the update path against a local file-served channel with a test
key. This is the same substitution posture Phases 5–8 recorded, and the
publication runbook (D4) is where it stops being a substitution.

---

## Out of scope for 9a

Onboarding polish, empty and error states, finding F1 (9b); marketing and docs
sites (9c); `proxploy-api` hardening and opt-in error reporting (9d);
multi-node HA; unattended/automatic updates, 9a's apply is always operator-
initiated.
