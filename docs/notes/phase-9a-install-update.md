# Phase 9a (Install and update) — verification notes

> Phase 9 in doc 10 was one undifferentiated "Deliver" block. The design spec
> (`docs/superpowers/specs/2026-08-05-phase-9a-install-update-design.md`) split
> it into 9a–9d and this phase is the first: how the product gets onto a box,
> and how it replaces itself once it is there. Publication — a real key, a
> public repo, a real GitHub release — is deliberately *not* in this phase.

## What shipped, per subsystem

**One version, one place (Task 1).** `proxploy.__version__` is the single
source of truth and reads `1.0.0`. The manifest, the release tarball's staged
`__init__.py`, the install directory name and `/meta/version` all derive from
it; `build_release.sh` overwrites the staged copy with `--version` so the
artifact, the manifest and the tag cannot disagree.

**Release format and verification (Task 2).** `services/release.py` —
`verify_manifest(raw, sig, pubkey_pem)` checks an Ed25519 signature over the
**raw manifest bytes before any parsing**, `verify_artifact(path, entry)`
checks sha256 and size, `is_upgrade(current, candidate)` refuses downgrades.
Order is signature-then-checksum-then-unpack, and it is the same order the
shell side uses, because a format with two implementations is exactly where a
format drifts.

**Channel client and shape detection (Task 3).** `services/updater.py::check`
fetches a channel's manifest and reports what is available;
`detect_shape()` returns `systemd` | `docker` | `dev`, and `CAN_SELF_APPLY`
encodes which of those may replace themselves. A Docker install never does —
see the boundary note below.

**Boot-time self-identity (Task 4).** The lifespan now persists `self.ctid`,
which closes a hook `selfguard.py` has carried since Phase 4 and which had
been inert ever since: the app could not previously recognise its own
container, so "don't let the user destroy the CT they are talking to" was a
rule with no subject.

**Update routes (Task 5).** `GET /meta/update` reports current version,
available version and whether this shape can self-apply. `POST /meta/update`
launches the updater through `systemd-run` — **outside** the app's own cgroup,
because the script restarts `proxploy.service` and anything inside that cgroup
gets killed halfway through, leaving the symlink swapped and nothing serving.
On a Docker install the same route `409`s with the `docker compose pull`
instruction instead.

**Layout, unit, installer (Tasks 6–8).** Immutable versioned directories under
`/opt/proxploy/releases/<version>/`, each with its own venv, and
`/opt/proxploy/current` as the symlink that a switch or a rollback moves.
Data and secrets live outside the release tree in `/var/lib/proxploy/`, so an
update is only ever a code swap. `install.sh` is both halves of the one-liner:
on a PVE host it creates the CT and pushes itself inside; in the container it
installs Debian packages, creates the service user, unpacks a verified
release, writes the unit, and puts Caddy in front with a real certificate
where possible and `tls internal` where not.

**The updater (Task 9).** `packaging/proxploy-update` — backup, download,
verify, unpack, migrate, switch, health-check, and roll back on any failure
from the switch onward. The ordering is the whole design and none of it is
negotiable: backup *before* download (a full disk must not cost you the
database), verify *before* unpack (never write unverified bytes into
`releases/`), migrate *before* switch (a failed migration leaves the old
version running), health *after* switch.

**The Docker shape (Task 10).** `packaging/docker/` — image and compose file.
It detects that it is a container and instructs rather than self-applying.

**Release builder and channel fixture (Task 11).** `build_release.sh` produces
the signed artifact set; `channel_fixture.sh` produces a throwaway two-release
channel plus, on request, a **poisoned** release whose `main.py` raises on
startup. The poison is what makes rollback testable rather than asserted.

**Harnesses (Tasks 12–13) and the update card (Task 14).** See below.

## The installer had never run before Task 12

Every installer bug in this phase was found by executing the thing, not by
reading it. `test_install.sh` runs the **real** `install.sh` in a real Debian
12 container with systemd as PID 1 — same script, same systemd, same Caddy,
same TLS — and its first run found seven bugs, each fixed at the shared root
rather than in the caller that happened to surface it:

- `pip install` without `-e` moved `proxploy/` into site-packages, so
  `main.py`'s `parents[2]/frontend/dist` resolved *inside the venv* and `/`
  served nothing while `/meta/health` answered fine. The API being up is not
  the same claim as the app being usable, and only one of those was tested.
- alembic's relative `script_location` resolves against the cwd, not against
  the ini file — `install.sh` and `proxploy-update` had the identical bug, so
  it was fixed once in `migrate_release()`.
- The manual alembic call had no `PROXPLOY_*` in its environment and silently
  fell back to a relative sqlite path.
- Pre-migrating before first boot created the database before the master key,
  which `SecretStore` correctly refuses as key loss.
- Caddy matched only the primary IP, so anything arriving on 127.0.0.1 got a
  TLS internal error with no matching site.
- `requires-python` claimed `>=3.12` while Debian 12 — which *is* the PVE 8 CT
  template, i.e. the actual install target — ships 3.11, and pip refused
  outright. Lowered to 3.11; CI grew a 3.11 leg (`backend-py311`) in Task 15,
  because a supported-version claim that nothing tests is not a claim.

## The rollback bug, which is the one that mattered

`test_upgrade_rollback.sh` upgrades 1.0.0 → 1.0.1, then feeds the box a
poisoned 1.0.2 and demands that it end up back on 1.0.1, healthy, with data
intact. It failed on the last clause, and the failure was worth the harness on
its own: `rollback()` restored the pre-update database with `cp -a` from a
backup written by `sqlite3 .backup` **running as root**, so the live database
came back owned `root:root` while the unit runs as `User=proxploy`. The app
then crash-looped on `attempt to write a readonly database`.

The data was restored perfectly and the box was still down — which is the
exact outcome the rollback path exists to prevent, arrived at by way of a
rollback that "worked". Three things were wrong and all three are fixed:

1. The restore ran under a live unit that was crash-looping on `RestartSec=3`,
   racing a starting process for the same file. It now stops the unit first.
2. That crash loop trips systemd's start-limit (5 starts / 10 s) and leaves
   the unit failed, where a bare `start` will not revive it. `reset-failed`
   now runs unconditionally — it is a no-op otherwise.
3. `cp -a` preserved the backup's root ownership. Plain `cp` plus an explicit
   `chown` to the service user, and the stale `-wal`/`-shm` belonging to the
   database being *replaced* are removed rather than left for sqlite to replay
   over a different file.

It also now waits for the same health signal the forward path waits for,
because `Type=exec` reports "active" the moment the process execs, not once
uvicorn has opened the port.

## Residual limitations, stated plainly

- **No real Proxmox node here.** The PVE-host half of the installer is proven
  against a fake `pct` (`packaging/tests/fake-pct`) that asserts the expected
  create call. `pct create` against real hardware is unproven, and this is the
  same gap every phase since 4 has recorded.
- **No real release channel.** Everything ran against a local `file://`
  channel signed with a throwaway key. Spec D4 keeps publication out of
  implementation on purpose.
- **The release private key does not exist yet**, and
  `backend/proxploy/release_pubkey.pem` ships a **placeholder**. Replacing it
  is Step 1 of `docs/runbooks/publishing-a-release.md`. Note the bootstrap
  property: the public key ships *inside* the artifact, so rotating it
  requires publishing a release — the same property doc 09 records for the
  entitlement key.
- **Docker installs cannot self-apply, by design, not by omission.** A
  container replacing its own image from inside is a way to lose the
  container; `POST /meta/update` returns 409 with the `docker compose pull`
  instruction, and the UI card says so rather than hiding the button.
- **Task 8 (Caddy TLS) has no unit test**, by intent — it is verified by the
  container harness serving real HTTPS, which is the only assertion that
  means anything about a TLS front.

## Gate numbers

| Gate | Result |
|---|---|
| Backend suite | **810 passed, 2 skipped, 4 deselected** (baseline entering the phase: 784) |
| Frontend suite | **205 passed across 37 files** (baseline 199 across 36), `--no-file-parallelism` |
| Frontend build | clean |
| Frontend lint | exit 0 — 30 warnings, 0 errors, pre-existing warning classes only |
| Migrations | `alembic heads` = **`6cf6a0722d23`**, unchanged — **zero migrations this phase**, as planned |
| shellcheck | clean, exit 0 — `-x -P SCRIPTDIR` over `install.sh`, `proxploy-update`, `packaging/lib/*.sh`, `packaging/tests/*.sh`, `build_release.sh` |
| `test_install.sh` | PASS — unit active, app answers, TLS front serves, second run idempotent |
| `test_upgrade_rollback.sh` | PASS — 1.0.0 → 1.0.1 with data intact and a backup taken; poisoned 1.0.2 refused and rolled back to 1.0.1, healthy, SPA serving |
| `test_pve_half.sh` | PASS — the PVE half sends the expected `pct create` |
| `dod_verify_phase9a.py` | all four checks OK, **exit 0**, run three times (twice by the implementer, once independently) — byte-identical output every time |

The DoD script surfaces only the harnesses' `OK:`-prefixed lines, so no
container name or timing reaches its own stdout and the runs are identical
outright rather than "identical modulo timings". It is throwaway and not
committed — `backend/.gitignore` carries `dod_verify_phase*.py` (the repo-root
`.gitignore` does not; the pattern is backend-local).

Three shell harnesses exist, not the four the plan's Step 4 counts:
`test_install.sh`, `test_upgrade_rollback.sh`, `test_pve_half.sh`.
`channel_fixture.sh` is a fixture builder they all consume, not a harness.

Commit range: `01b3a92`..`HEAD` (design spec through this note).
