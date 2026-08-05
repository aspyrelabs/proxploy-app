# Phase 9a — Install & Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A stranger can install Proxploy on a clean Proxmox node with one
command, and update it from the UI with an automatic rollback if the new
version fails to come up.

**Architecture:** Releases are immutable versioned directories under
`/opt/proxploy/releases/<version>/`, each with its own venv; `current` is a
symlink and switching versions is a symlink swap. The updater is a standalone
shell script launched detached via `systemd-run`, because a process cannot swap
its own code, restart itself, and still be present to observe whether that
worked. The app only checks for updates, launches the script, and watches
`/meta/version` change. Artifacts are verified against an Ed25519-signed
manifest using a release key that is deliberately separate from the entitlement
key.

**Tech Stack:** POSIX shell (installer + updater), systemd, Caddy
(arm's-length, `tls internal` fallback), Docker + Compose for the container
shape, `cryptography` (already a dependency) for Ed25519 verification, FastAPI
for the two new routes, React + Vitest for the Settings card, Docker for the
install/upgrade test harnesses.

**Spec:** `docs/superpowers/specs/2026-08-05-phase-9a-install-update-design.md`
— read it before Task 1. Decisions D1–D4 there are settled; do not relitigate
them mid-implementation. If implementation contradicts the spec, the spec wins
unless you record an amendment in `docs/notes/phase-9a-install-update.md` the
way Phase 8 recorded A1–A3.

## Global Constraints

- **No new backend or frontend runtime dependency.** Ed25519 verification uses
  `cryptography>=43`, already in `backend/pyproject.toml`. sha256 uses
  `hashlib`. HTTP fetching uses `httpx>=0.27`, already present. If you believe
  a task needs a new dependency, stop and say so rather than adding one.
- **Every shipped shell script must pass `shellcheck` with no warnings**, and
  must start `#!/usr/bin/env bash` + `set -euo pipefail`.
- **The updater never touches `/var/lib/proxploy/`** except to write a backup
  into `pre-update/` and to restore from it during rollback. Data and secrets
  are outside `releases/` by design.
- **Locked-down defaults:** the app binds `127.0.0.1`, Caddy fronts `:443`,
  TLS is always on. There is no flag in 9a that disables TLS.
- **Caddy is arm's-length** (doc 00:47): we write a Caddyfile and run Caddy as
  its own systemd service. We never vendor, link, or import its code.
- **Nothing outward-facing happens during implementation** (spec D4). No
  `gh repo edit --visibility`, no `gh release create`, no real release
  keypair. Every test uses a local file-served channel and a throwaway test
  key generated inside the test.
- **Authorization uses the existing `authorize()` path** from Phase 8. Both new
  routes are `authorize("settings", "manage")` / `authorize("settings",
  "read")`. Do not invent a new authorization concept, and do not add a route
  to any invariant allowlist — if `test_rbac_invariant.py` fails, the route is
  wrong, not the test.
- **Test floors:** backend ≥ 784 passed, frontend ≥ 199 passed across 36 files.
  Frontend runs must use `npx vitest run --no-file-parallelism` — this box
  flakes unrelated suites under parallel load (see
  `docs/notes/phase-8-scale.md`).
- **Commit to `main` directly**, one commit per task, no branches — the
  convention every prior phase used.

## File Structure

**New — release plumbing (backend)**

| File | Responsibility |
|---|---|
| `backend/proxploy/services/release.py` | Pure functions: parse a manifest, verify its Ed25519 signature, verify an artifact's sha256, compare versions. No I/O. |
| `backend/proxploy/services/updater.py` | I/O around `release.py`: fetch manifest from a channel URL, detect `install_shape`, launch the updater script detached. |
| `backend/proxploy/release_pubkey.pem` | The release **public** key, shipped inside the artifact. A placeholder self-generated key during 9a; the publication runbook replaces it. |

**New — scripts**

| File | Responsibility |
|---|---|
| `install.sh` (repo root) | The one-liner. Detects PVE host vs in-container, runs the right half. |
| `packaging/lib/common.sh` | Shared shell helpers sourced by both scripts: logging, `verify_manifest`, `fetch`, layout constants. |
| `packaging/proxploy-update` | The updater. Backup → download → verify → unpack → migrate → switch → health-check → rollback. |
| `packaging/proxploy.service` | systemd unit template for the app. |
| `packaging/caddy/Caddyfile.tmpl` | TLS front, `tls internal` fallback. |
| `packaging/docker/Dockerfile` | The container shape. |
| `packaging/docker/compose.yml` | Compose file the docs and the UI's copy-button reference. |
| `packaging/build_release.sh` | Builds `proxploy-<version>.tar.gz`, `manifest.json`, `manifest.json.sig`. |

**New — tests**

| File | Responsibility |
|---|---|
| `backend/tests/test_release_verify.py` | Signature, checksum, downgrade, unknown-key rejection. |
| `backend/tests/test_update_api.py` | Both routes, per install shape, authorization. |
| `packaging/tests/channel_fixture.sh` | Builds a two-release local channel + test keypair for the harnesses. |
| `packaging/tests/test_install.sh` | Real Debian container: install, assert unit + TLS health, assert idempotent re-run. |
| `packaging/tests/test_upgrade_rollback.sh` | Real container: 1.0.0 → 1.0.1 upgrade, then a poisoned 1.0.2 → auto-rollback. |
| `packaging/tests/test_pve_half.sh` | Fake `pct` on `PATH`; assert create args, storage and bridge picks. |
| `frontend/src/tests/update.test.tsx` | The Settings card, both shapes. |

**Modified**

| File | Change |
|---|---|
| `backend/proxploy/__init__.py`, `backend/pyproject.toml` | One source of truth for the version; bump to `1.0.0`. |
| `backend/proxploy/api/meta.py` | `GET /meta/update`, `POST /meta/update`. |
| `backend/proxploy/config.py` | `release_channel_url`, `install_shape`, `self_ctid`, `update_script`. |
| `backend/proxploy/main.py` | Boot-time write of the `self.ctid` / `self.host_id` settings from env (closes the hook `services/selfguard.py` documents). |
| `frontend/src/api/account.ts` | `useUpdateStatus()` + the apply mutation. |
| `frontend/src/routes/settings.tsx` | Mount `UpdateCard`. |
| `.github/workflows/ci.yml` | `shellcheck` job; container install/upgrade harness job. |

## Task Order and Dependencies

```
1 ── 2 ── 3 ── 4 ── 5            backend: version, verify, channel, routes
      └── 11                      build_release.sh needs the manifest format
6 ── 7 ── 8 ── 10                 scripts: installer, PVE half, TLS, docker
      └── 9                       updater needs the layout task 6 creates
11 ── 12 ── 13                    harnesses need a real buildable release
5, 13 ── 14                       frontend card needs the routes
14 ── 15 ── 16                    CI, runbook, close-out
```

Tasks 1–5 (backend) and 6–10 (scripts) are independent of each other until
Task 11. Task 9 consumes the layout Task 6 defines. Task 16 is last.

---

## Task 1: One version, and it is 1.0.0

**Files:**
- Modify: `backend/proxploy/__init__.py`, `backend/pyproject.toml`
- Test: `backend/tests/test_version.py` (create)

**Interfaces:**
- Produces: `proxploy.__version__` — the single authoritative version string,
  read by `api/meta.py`, `packaging/build_release.sh`, and every task below.

Today `0.1.0` is written in two places that can drift. `pyproject.toml` becomes
dynamic and reads the package; `__init__.py` is the source of truth.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_version.py
"""The version is stated once. A release tag, a signed manifest and
/meta/version that disagree are a supply-chain bug, not a cosmetic one."""
import re
import tomllib
from pathlib import Path

import proxploy


def test_version_is_semver_and_at_least_1_0_0():
    assert re.fullmatch(r"\d+\.\d+\.\d+", proxploy.__version__)
    major = int(proxploy.__version__.split(".")[0])
    assert major >= 1, "9a ships 1.0.0; 0.x is pre-release"


def test_pyproject_does_not_hardcode_a_second_version():
    raw = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    project = raw["project"]
    assert "version" not in project, (
        "pyproject must declare version dynamic and read it from the package")
    assert "version" in project.get("dynamic", [])


def test_installed_metadata_matches_the_package():
    from importlib.metadata import version as dist_version
    assert dist_version("proxploy") == proxploy.__version__
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/python -m pytest tests/test_version.py -q`
Expected: FAIL — version is `0.1.0`, and `pyproject.toml` hardcodes it.

- [ ] **Step 3: Implement**

`backend/proxploy/__init__.py`:

```python
__version__ = "1.0.0"
```

`backend/pyproject.toml` — replace the `version = "0.1.0"` line in `[project]`
with `dynamic = ["version"]`, and add below the `[build-system]` block:

```toml
[tool.setuptools.dynamic]
version = {attr = "proxploy.__version__"}
```

Check the existing `[build-system]` block first — if the backend uses a
backend other than setuptools, use that backend's equivalent attr-reading
mechanism rather than switching build backends.

- [ ] **Step 4: Reinstall so the metadata refreshes, then run**

Run: `cd backend && .venv/bin/pip install -e '.[dev]' -q && .venv/bin/python -m pytest tests/test_version.py -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Full backend suite** — `cd backend && .venv/bin/python -m pytest tests/ -m "not pve_integration and not e2e" -q`. Expected ≥ 787 passed. If a test asserted the literal string `0.1.0`, fix that test — it was pinning a placeholder.

- [ ] **Step 6: Commit**

```bash
git add backend/proxploy/__init__.py backend/pyproject.toml backend/tests/test_version.py
git commit -m "chore(release): single source of truth for the version; 1.0.0"
```

---

## Task 2: Manifest format and verification

**Files:**
- Create: `backend/proxploy/services/release.py`, `backend/tests/test_release_verify.py`

**Interfaces:**
- Produces, for Tasks 3, 5, 9 and 11:
  - `MANIFEST_SCHEMA_VERSION = 1`
  - `verify_manifest(raw: bytes, sig: bytes, pubkey_pem: bytes) -> dict` — returns the parsed manifest, raises `ReleaseError` on a bad signature or an unparseable/unknown-schema body. **Signature is verified over the exact bytes**, before any parsing, so a tampered body can never reach the parser.
  - `verify_artifact(path: Path, entry: dict) -> None` — raises `ReleaseError` unless the file's sha256 equals `entry["sha256"]` and its size equals `entry["size"]`.
  - `is_upgrade(current: str, candidate: str) -> bool` — semver compare, False for equal or older.
  - `class ReleaseError(Exception)`.

The manifest shape, fixed here and consumed everywhere below:

```json
{
  "schema": 1,
  "version": "1.0.1",
  "channel": "stable",
  "released_at": "2026-08-05T12:00:00Z",
  "notes_url": "https://github.com/aspyrelabs/proxploy-app/releases/tag/v1.0.1",
  "artifacts": {
    "tarball": {
      "name": "proxploy-1.0.1.tar.gz",
      "sha256": "<hex>",
      "size": 12345678
    }
  }
}
```

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_release_verify.py
"""Release verification is the product's supply chain. Every test here is a
way an attacker or a corrupt mirror could hand us bytes we should refuse."""
import hashlib
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from proxploy.services.release import (ReleaseError, is_upgrade, verify_artifact,
                                       verify_manifest)


def _keypair():
    priv = Ed25519PrivateKey.generate()
    pem = priv.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    return priv, pem


def _manifest(version="1.0.1", sha="0" * 64, size=10, schema=1):
    return json.dumps({
        "schema": schema, "version": version, "channel": "stable",
        "released_at": "2026-08-05T12:00:00Z",
        "notes_url": "https://example.invalid/notes",
        "artifacts": {"tarball": {"name": f"proxploy-{version}.tar.gz",
                                  "sha256": sha, "size": size}},
    }).encode()


def test_a_correctly_signed_manifest_parses():
    priv, pem = _keypair()
    raw = _manifest()
    got = verify_manifest(raw, priv.sign(raw), pem)
    assert got["version"] == "1.0.1"
    assert got["artifacts"]["tarball"]["name"] == "proxploy-1.0.1.tar.gz"


def test_a_tampered_body_is_refused():
    priv, pem = _keypair()
    raw = _manifest()
    sig = priv.sign(raw)
    tampered = raw.replace(b"1.0.1", b"9.9.9")
    with pytest.raises(ReleaseError):
        verify_manifest(tampered, sig, pem)


def test_a_signature_from_the_wrong_key_is_refused():
    priv, _ = _keypair()
    _, other_pem = _keypair()
    raw = _manifest()
    with pytest.raises(ReleaseError):
        verify_manifest(raw, priv.sign(raw), other_pem)


def test_an_unknown_schema_version_is_refused():
    """Forward compatibility must fail closed: a manifest we do not
    understand is not a manifest we may act on."""
    priv, pem = _keypair()
    raw = _manifest(schema=99)
    with pytest.raises(ReleaseError):
        verify_manifest(raw, priv.sign(raw), pem)


def test_unparseable_body_is_refused_even_when_correctly_signed():
    priv, pem = _keypair()
    raw = b"this is not json"
    with pytest.raises(ReleaseError):
        verify_manifest(raw, priv.sign(raw), pem)


def test_artifact_checksum_and_size_must_both_match(tmp_path):
    blob = tmp_path / "proxploy-1.0.1.tar.gz"
    blob.write_bytes(b"payload")
    good = {"name": blob.name, "sha256": hashlib.sha256(b"payload").hexdigest(),
            "size": len(b"payload")}
    verify_artifact(blob, good)                      # no raise

    with pytest.raises(ReleaseError):
        verify_artifact(blob, {**good, "sha256": "0" * 64})
    with pytest.raises(ReleaseError):
        verify_artifact(blob, {**good, "size": 999})


def test_upgrade_comparison_rejects_equal_and_older():
    assert is_upgrade("1.0.0", "1.0.1")
    assert is_upgrade("1.0.9", "1.1.0")
    assert is_upgrade("1.9.0", "2.0.0")
    assert not is_upgrade("1.0.1", "1.0.1")
    assert not is_upgrade("1.0.1", "1.0.0")
    assert not is_upgrade("2.0.0", "1.9.9")
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/python -m pytest tests/test_release_verify.py -q`
Expected: FAIL — `ModuleNotFoundError: proxploy.services.release`

- [ ] **Step 3: Implement `backend/proxploy/services/release.py`**

```python
"""Release manifest parsing and verification (Phase 9a, spec D2).

Deliberately pure: no network, no filesystem beyond hashing a file the caller
already has. Everything here is on the path an attacker would need to walk to
make us install their bytes, so it is small enough to read in one sitting.

The signature is checked over the RAW bytes before any parsing, so malformed
or hostile JSON never reaches the parser.
"""
import hashlib
import json
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

MANIFEST_SCHEMA_VERSION = 1
_CHUNK = 1024 * 1024


class ReleaseError(Exception):
    """Any reason we refuse a release. Callers surface the message verbatim."""


def verify_manifest(raw: bytes, sig: bytes, pubkey_pem: bytes) -> dict:
    try:
        key = load_pem_public_key(pubkey_pem)
    except Exception as e:
        raise ReleaseError(f"release public key is unreadable: {e}") from e
    if not isinstance(key, Ed25519PublicKey):
        raise ReleaseError("release public key is not Ed25519")
    try:
        key.verify(sig, raw)
    except InvalidSignature as e:
        raise ReleaseError("manifest signature is not valid for this key") from e

    try:
        manifest = json.loads(raw)
    except ValueError as e:
        raise ReleaseError(f"manifest is not valid JSON: {e}") from e
    if not isinstance(manifest, dict):
        raise ReleaseError("manifest is not an object")
    if manifest.get("schema") != MANIFEST_SCHEMA_VERSION:
        raise ReleaseError(
            f"manifest schema {manifest.get('schema')!r} is not supported "
            f"(this build understands {MANIFEST_SCHEMA_VERSION}) — update "
            f"Proxploy manually, then retry")
    for field in ("version", "artifacts"):
        if field not in manifest:
            raise ReleaseError(f"manifest is missing {field!r}")
    tarball = manifest["artifacts"].get("tarball")
    if not isinstance(tarball, dict) or not {"name", "sha256", "size"} <= tarball.keys():
        raise ReleaseError("manifest has no complete tarball artifact entry")
    return manifest


def verify_artifact(path: Path, entry: dict) -> None:
    actual_size = path.stat().st_size
    if actual_size != entry["size"]:
        raise ReleaseError(
            f"{path.name}: expected {entry['size']} bytes, got {actual_size}")
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != entry["sha256"]:
        raise ReleaseError(f"{path.name}: sha256 mismatch — refusing to install")


def _parts(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in v.split("."))
    except ValueError as e:
        raise ReleaseError(f"unparseable version {v!r}") from e


def is_upgrade(current: str, candidate: str) -> bool:
    """Strictly newer. Downgrades are refused here rather than at the call
    site, so no caller can forget: rolling BACK is the updater's rollback
    path, which restores a known-good directory, not a fresh install of an
    older release over a newer database."""
    return _parts(candidate) > _parts(current)
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_release_verify.py -q`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/proxploy/services/release.py backend/tests/test_release_verify.py
git commit -m "feat(release): Ed25519 manifest verification, checksums, downgrade refusal"
```

---

## Task 3: Channel client and install-shape detection

**Files:**
- Create: `backend/proxploy/services/updater.py`
- Modify: `backend/proxploy/config.py`
- Test: `backend/tests/test_updater_check.py` (create)

**Interfaces:**
- Consumes: `release.verify_manifest`, `release.verify_artifact`, `release.is_upgrade`, `release.ReleaseError` (Task 2).
- Produces, for Tasks 5 and 14:
  - `detect_shape(settings) -> str` — `"lxc"` | `"systemd"` | `"docker"`.
  - `CAN_SELF_APPLY = {"lxc", "systemd"}`
  - `check(settings) -> dict` — `{"current", "latest", "update_available", "notes_url", "channel", "error"}`. **Never raises**: a channel that is unreachable, unsigned, or malformed returns `error` as a human-readable string with `update_available: False`. A broken update channel must not break the Settings page.
  - `launch(settings, version: str) -> None` — Task 5 uses it; implemented there.

New settings, appended to `backend/proxploy/config.py`:

```python
    # Phase 9a. The release channel is a base URL holding manifest.json,
    # manifest.json.sig and the tarball. https:// in production; the test
    # harnesses point it at a file:// directory so no test ever needs the
    # network or a real release.
    release_channel_url: str = "https://github.com/aspyrelabs/proxploy-app/releases/latest/download"
    release_pubkey_file: Path | None = None   # None = the key shipped in the package
    # Set by the installer in /etc/proxploy/proxploy.env. Unset means a dev
    # checkout: check works, apply refuses, because there is no managed
    # layout to switch.
    install_shape: str | None = None
    update_script: Path = Path("/opt/proxploy/bin/proxploy-update")
    update_timeout_s: float = 600.0
    # Written by the installer from inside the CT it creates, so
    # services/selfguard.py can recognise Proxploy's own container.
    self_ctid: int | None = None
```

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_updater_check.py
"""The update check talks to a channel we do not control. Every failure mode
of that channel must degrade to 'no update available, here is why' — never to
an exception that takes the Settings page down with it."""
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import proxploy
from proxploy.config import Settings
from proxploy.services.updater import CAN_SELF_APPLY, check, detect_shape


def _channel(tmp_path, version, schema=1, sign_with=None):
    """Writes a file:// channel and returns (settings, pubkey_path)."""
    priv = sign_with or Ed25519PrivateKey.generate()
    pem = priv.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    ch = tmp_path / "channel"
    ch.mkdir(exist_ok=True)
    raw = json.dumps({
        "schema": schema, "version": version, "channel": "stable",
        "released_at": "2026-08-05T12:00:00Z",
        "notes_url": f"https://example.invalid/v{version}",
        "artifacts": {"tarball": {"name": f"proxploy-{version}.tar.gz",
                                  "sha256": "0" * 64, "size": 1}},
    }).encode()
    (ch / "manifest.json").write_bytes(raw)
    (ch / "manifest.json.sig").write_bytes(priv.sign(raw))
    key_path = tmp_path / "release.pem"
    key_path.write_bytes(pem)
    return Settings(db_url=f"sqlite:///{tmp_path}/t.db", data_dir=tmp_path,
                    master_key_file=tmp_path / "m.key",
                    release_channel_url=ch.as_uri(),
                    release_pubkey_file=key_path)


def test_a_newer_signed_release_is_offered(tmp_path):
    s = _channel(tmp_path, "99.0.0")
    got = check(s)
    assert got["update_available"] is True
    assert got["latest"] == "99.0.0"
    assert got["current"] == proxploy.__version__
    assert got["notes_url"] == "https://example.invalid/v99.0.0"
    assert got["error"] is None


def test_the_running_version_is_not_an_update(tmp_path):
    s = _channel(tmp_path, proxploy.__version__)
    got = check(s)
    assert got["update_available"] is False
    assert got["error"] is None


def test_an_older_release_is_not_an_update(tmp_path):
    s = _channel(tmp_path, "0.0.1")
    assert check(s)["update_available"] is False


def test_a_manifest_signed_by_the_wrong_key_reports_an_error(tmp_path):
    s = _channel(tmp_path, "99.0.0")
    (tmp_path / "release.pem").write_bytes(
        Ed25519PrivateKey.generate().public_key().public_bytes(
            Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
    got = check(s)
    assert got["update_available"] is False
    assert got["error"] and "signature" in got["error"].lower()


def test_an_unreachable_channel_reports_an_error_and_does_not_raise(tmp_path):
    s = Settings(db_url=f"sqlite:///{tmp_path}/t.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "m.key",
                 release_channel_url=(tmp_path / "nope").as_uri())
    got = check(s)
    assert got["update_available"] is False
    assert got["error"]


def test_shape_detection(tmp_path, monkeypatch):
    s = Settings(db_url=f"sqlite:///{tmp_path}/t.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "m.key", install_shape="lxc")
    assert detect_shape(s) == "lxc"

    # Configured shape wins; env is the fallback for a container that was
    # started from the image without the installer's env file.
    s2 = Settings(db_url=f"sqlite:///{tmp_path}/t.db", data_dir=tmp_path,
                  master_key_file=tmp_path / "m.key")
    monkeypatch.setenv("PROXPLOY_IN_DOCKER", "1")
    assert detect_shape(s2) == "docker"


def test_only_lxc_and_systemd_may_self_apply():
    assert CAN_SELF_APPLY == {"lxc", "systemd"}
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/python -m pytest tests/test_updater_check.py -q`
Expected: FAIL — `ModuleNotFoundError: proxploy.services.updater`

- [ ] **Step 3: Implement `backend/proxploy/services/updater.py`** (the `check`/`detect_shape` half; `launch` lands in Task 5)

```python
"""Update check and install-shape detection (Phase 9a).

`check()` never raises. A self-hosted box may sit behind a proxy, on an
air-gapped network, or in front of a mirror serving nonsense; none of that is
a reason for the Settings page to fail. Every failure becomes a string the
operator can act on.
"""
import os
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import url2pathname

import httpx

import proxploy
from proxploy.config import Settings
from proxploy.services.release import ReleaseError, is_upgrade, verify_manifest

CAN_SELF_APPLY = {"lxc", "systemd"}
_TIMEOUT = 15.0


def detect_shape(settings: Settings) -> str:
    if settings.install_shape:
        return settings.install_shape
    if os.environ.get("PROXPLOY_IN_DOCKER") or Path("/.dockerenv").exists():
        return "docker"
    return "systemd"


def _pubkey(settings: Settings) -> bytes:
    if settings.release_pubkey_file:
        return Path(settings.release_pubkey_file).read_bytes()
    return (Path(proxploy.__file__).parent / "release_pubkey.pem").read_bytes()


def _fetch(base: str, name: str) -> bytes:
    """file:// for the test harnesses, https:// in production. Nothing else."""
    url = f"{base.rstrip('/')}/{name}"
    if url.startswith("file://"):
        return Path(url2pathname(url[len("file://"):])).read_bytes()
    r = httpx.get(url, timeout=_TIMEOUT, follow_redirects=True)
    r.raise_for_status()
    return r.content


def check(settings: Settings) -> dict:
    out = {"current": proxploy.__version__, "latest": None,
           "update_available": False, "notes_url": None,
           "channel": None, "error": None}
    try:
        raw = _fetch(settings.release_channel_url, "manifest.json")
        sig = _fetch(settings.release_channel_url, "manifest.json.sig")
        manifest = verify_manifest(raw, sig, _pubkey(settings))
    except ReleaseError as e:
        out["error"] = str(e)
        return out
    except Exception as e:                    # network, DNS, permissions, disk
        out["error"] = f"could not reach the release channel: {e}"
        return out
    out["latest"] = manifest["version"]
    out["notes_url"] = manifest.get("notes_url")
    out["channel"] = manifest.get("channel")
    out["update_available"] = is_upgrade(proxploy.__version__, manifest["version"])
    return out
```

Note `urljoin` is imported but unused in the snippet above — drop the import;
the f-string join is deliberate, because `urljoin` would discard a channel URL
path segment.

- [ ] **Step 4: Run the tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_updater_check.py -q`
Expected: PASS (7 tests)

- [ ] **Step 5: Generate the placeholder release public key**

The package must ship *a* key so `_pubkey()` has a default. Generate a
throwaway one now; the publication runbook (Task 15) replaces it.

```bash
cd backend && .venv/bin/python - <<'PY'
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (Encoding, NoEncryption,
                                                          PrivateFormat, PublicFormat)
priv = Ed25519PrivateKey.generate()
Path("proxploy/release_pubkey.pem").write_bytes(
    priv.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
Path("../packaging/tests/DEV_ONLY_release_key.pem").parent.mkdir(parents=True, exist_ok=True)
Path("../packaging/tests/DEV_ONLY_release_key.pem").write_bytes(
    priv.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
print("wrote placeholder keypair")
PY
```

Add to `.gitignore`: `packaging/tests/DEV_ONLY_release_key.pem`. The **private**
key is never committed, even a throwaway one — a committed private key in a
release-signing path is the kind of thing that gets copy-pasted into
production. Add a header comment in `release_pubkey.pem` marking it a
placeholder.

- [ ] **Step 6: Commit**

```bash
git add backend/proxploy/services/updater.py backend/proxploy/config.py \
        backend/proxploy/release_pubkey.pem backend/tests/test_updater_check.py .gitignore
git commit -m "feat(release): channel client and install-shape detection"
```

---

## Task 4: Boot-time self-identity, closing the selfguard hook

**Files:**
- Modify: `backend/proxploy/main.py`
- Test: `backend/tests/test_self_identity.py` (create)

**Interfaces:**
- Consumes: `settings.self_ctid` (Task 3), `services/settings.set_setting`, `services/selfguard.is_self`.

`services/selfguard.py`'s docstring already says: *"Identity is recorded at
install time as the `self.ctid` / `self.host_id` settings keys (the Phase 9
installer writes them from inside the CT it creates)."* Nothing writes them
yet, so the guard is inert on every install. The installer cannot write DB rows
(no database exists when it runs), so it writes `PROXPLOY_SELF_CTID` into the
env file and the app persists it on boot.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_self_identity.py
"""selfguard.py has been waiting since Phase 4 for the installer to tell it
which container Proxploy is. This is that wire."""
from fastapi.testclient import TestClient

from proxploy.services.settings import get_setting
from tests.support import make_app


def test_self_ctid_from_settings_is_persisted_on_boot(tmp_path):
    app = make_app(tmp_path, self_ctid=150)
    with TestClient(app):
        db = app.state.sessionmaker()
        assert get_setting(db, "self.ctid") == 150
        db.close()


def test_absent_self_ctid_writes_nothing(tmp_path):
    """A dev checkout or a bare-metal install has no CTID. selfguard is
    documented to block NOTHING when identity is unknown — writing a bogus
    value here would be worse than writing none."""
    app = make_app(tmp_path)
    with TestClient(app):
        db = app.state.sessionmaker()
        assert get_setting(db, "self.ctid") is None
        db.close()


def test_an_operator_edit_is_not_overwritten_on_the_next_boot(tmp_path):
    """Proxploy can be migrated to another CT; the operator corrects the
    setting, and a restart must not stamp the installer's stale value back."""
    app = make_app(tmp_path, self_ctid=150)
    with TestClient(app):
        pass
    db = app.state.sessionmaker()
    from proxploy.services.settings import set_setting
    set_setting(db, "self.ctid", 151)
    db.commit()
    db.close()

    app2 = make_app(tmp_path, self_ctid=150)
    with TestClient(app2):
        db2 = app2.state.sessionmaker()
        assert get_setting(db2, "self.ctid") == 151
        db2.close()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/python -m pytest tests/test_self_identity.py -q`
Expected: FAIL — the setting is never written.

- [ ] **Step 3: Implement** — in `backend/proxploy/main.py`'s lifespan, alongside the other boot-time writes (find where `SYSTEM_SCHEDULES` seeding happens and put it near there):

```python
    # Phase 9a: the installer knows which CT it built Proxploy into and puts
    # it in the env file; persist it once so services/selfguard.py can
    # recognise our own container. Write-once: a later operator correction
    # (Proxploy moved) must survive restarts, so an existing value wins.
    if settings.self_ctid is not None:
        db = sessionmaker()
        try:
            if get_setting(db, "self.ctid") is None:
                set_setting(db, "self.ctid", settings.self_ctid)
                db.commit()
        finally:
            db.close()
```

Import `get_setting`/`set_setting` from `proxploy.services.settings` at the
top of the function, matching how the file imports other services lazily.

- [ ] **Step 4: Run the tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_self_identity.py -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/proxploy/main.py backend/tests/test_self_identity.py
git commit -m "feat(install): persist self.ctid at boot so selfguard can see its own CT"
```

---

## Task 5: The two update routes

**Files:**
- Modify: `backend/proxploy/api/meta.py`, `backend/proxploy/services/updater.py`
- Test: `backend/tests/test_update_api.py` (create)

**Interfaces:**
- Consumes: `updater.check`, `updater.detect_shape`, `updater.CAN_SELF_APPLY` (Task 3).
- Produces, for Task 14 (frontend):
  - `GET /api/v1/meta/update` → `{"current", "latest", "update_available", "notes_url", "channel", "error", "install_shape", "can_self_apply": bool, "compose_hint": str | None}`
  - `POST /api/v1/meta/update` body `{"version": "1.0.1"}` → `202 {"ok": true, "version": "1.0.1"}`; `409 {"error": "docker_shape", "compose_hint": "docker compose pull && docker compose up -d"}` on Docker; `409 {"error": "no_such_version"}` when the channel's latest does not match the requested version; `503` when the update script is missing.
  - `updater.launch(settings, version) -> None` — runs `systemd-run --unit=proxploy-update-<version> --collect <update_script> --to <version> --channel <url>`, detached, and returns immediately.

**Why the requested version is echoed back and checked:** the client sends the
version it was *shown*. If the channel moved on between the check and the
click, applying "latest" silently would install something the operator never
saw. Mismatch is a 409, not a silent substitution.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_update_api.py
"""The update routes. Authorization is the Phase 8 authorize() path; what is
new here is refusing to act on a shape that cannot self-apply, and refusing to
install a version the operator was not shown."""
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient

import proxploy
from tests.support import make_app


def _channel(tmp_path, version):
    priv = Ed25519PrivateKey.generate()
    ch = tmp_path / "channel"
    ch.mkdir(exist_ok=True)
    raw = json.dumps({
        "schema": 1, "version": version, "channel": "stable",
        "released_at": "2026-08-05T12:00:00Z",
        "notes_url": f"https://example.invalid/v{version}",
        "artifacts": {"tarball": {"name": f"proxploy-{version}.tar.gz",
                                  "sha256": "0" * 64, "size": 1}},
    }).encode()
    (ch / "manifest.json").write_bytes(raw)
    (ch / "manifest.json.sig").write_bytes(priv.sign(raw))
    key = tmp_path / "release.pem"
    key.write_bytes(priv.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
    return {"release_channel_url": ch.as_uri(), "release_pubkey_file": key}


def test_status_reports_an_available_update(tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path, install_shape="lxc", **_channel(tmp_path, "99.0.0"))
    with TestClient(app) as c:
        bootstrap_admin(c)                       # logs in; auth is the cookie
        r = c.get("/api/v1/meta/update")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["update_available"] is True
        assert body["latest"] == "99.0.0"
        assert body["current"] == proxploy.__version__
        assert body["install_shape"] == "lxc"
        assert body["can_self_apply"] is True
        assert body["compose_hint"] is None


def test_docker_shape_reports_the_compose_command_instead_of_applying(
        tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path, install_shape="docker", **_channel(tmp_path, "99.0.0"))
    with TestClient(app) as c:
        bootstrap_admin(c)
        body = c.get("/api/v1/meta/update").json()
        assert body["update_available"] is True
        assert body["can_self_apply"] is False
        assert body["compose_hint"] == "docker compose pull && docker compose up -d"

        r = c.post("/api/v1/meta/update", json={"version": "99.0.0"},
                   headers=csrf_header(c))
        assert r.status_code == 409
        assert r.json()["error"] == "docker_shape"


def test_apply_launches_the_updater_for_lxc(tmp_path, csrf_header, bootstrap_admin,
                                            monkeypatch):
    launched = []
    monkeypatch.setattr("proxploy.api.meta.updater.launch",
                        lambda s, v: launched.append(v))
    script = tmp_path / "proxploy-update"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    app = make_app(tmp_path, install_shape="lxc", update_script=script,
                   **_channel(tmp_path, "99.0.0"))
    with TestClient(app) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/meta/update", json={"version": "99.0.0"},
                   headers=csrf_header(c))
        assert r.status_code == 202, r.text
        assert launched == ["99.0.0"]


def test_a_version_the_channel_does_not_offer_is_refused(
        tmp_path, csrf_header, bootstrap_admin, monkeypatch):
    monkeypatch.setattr("proxploy.api.meta.updater.launch",
                        lambda s, v: (_ for _ in ()).throw(AssertionError("must not launch")))
    script = tmp_path / "proxploy-update"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    app = make_app(tmp_path, install_shape="lxc", update_script=script,
                   **_channel(tmp_path, "99.0.0"))
    with TestClient(app) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/meta/update", json={"version": "98.0.0"},
                   headers=csrf_header(c))
        assert r.status_code == 409
        assert r.json()["error"] == "no_such_version"


def test_a_missing_update_script_is_503_not_a_crash(tmp_path, csrf_header,
                                                    bootstrap_admin):
    app = make_app(tmp_path, install_shape="systemd",
                   update_script=tmp_path / "absent",
                   **_channel(tmp_path, "99.0.0"))
    with TestClient(app) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/meta/update", json={"version": "99.0.0"},
                   headers=csrf_header(c))
        assert r.status_code == 503


def test_a_viewer_cannot_apply_an_update(tmp_path, csrf_header, bootstrap_admin):
    """Covered generically by test_rbac_invariant.py; asserted explicitly here
    because 'a viewer can restart the product' would be the most embarrassing
    possible hole in the phase that adds the restart."""
    app = make_app(tmp_path, install_shape="lxc", **_channel(tmp_path, "99.0.0"))
    with TestClient(app) as c:
        bootstrap_admin(c)                       # owner, so it can mint a viewer
        h = csrf_header(c)
        c.post("/api/v1/users", json={"email": "v@x.io", "role": "viewer",
               "password": "correct-horse-battery"}, headers=h)
        c.post("/api/v1/auth/logout", headers=h)
        c.post("/api/v1/auth/login", json={"email": "v@x.io",
               "password": "correct-horse-battery"}, headers=h)
        r = c.post("/api/v1/meta/update", json={"version": "99.0.0"},
                   headers=csrf_header(c))
        assert r.status_code == 403
```

**Fixture semantics, verified against `backend/tests/conftest.py`:**
`bootstrap_admin(client)` creates the first user *and logs it in*, returning
the client — authentication is the session cookie, so GETs need no headers.
`csrf_header(client)` returns the `X-CSRF-Token` header dict every mutating
request needs. There is no `viewer_session` fixture; the viewer is built
inline above, the same way `tests/test_rbac_invariant.py` does it.

**Note the monkeypatch target:** `proxploy.api.meta.updater.launch`, not
`proxploy.services.updater.launch` — `api/meta.py` imports the *module*, so
patching the attribute on the module object is what the route actually calls.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/python -m pytest tests/test_update_api.py -q`
Expected: FAIL — 404 on both routes.

- [ ] **Step 3: Implement `launch()` in `services/updater.py`**

```python
import shutil
import subprocess


def launch(settings: Settings, version: str) -> None:
    """Hand off to the updater and return immediately.

    systemd-run puts the script in its OWN transient unit, outside this
    process's cgroup. That is the whole point: the script restarts
    proxploy.service, and anything living inside that cgroup would be killed
    mid-update, leaving the symlink swapped and nothing running.
    """
    script = str(settings.update_script)
    systemd_run = shutil.which("systemd-run") or "/usr/bin/systemd-run"
    subprocess.Popen(
        [systemd_run, f"--unit=proxploy-update-{version}", "--collect",
         script, "--to", version, "--channel", settings.release_channel_url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
```

- [ ] **Step 4: Implement the routes in `backend/proxploy/api/meta.py`**

```python
from pathlib import Path

from pydantic import BaseModel

from proxploy.services import updater

_manage = authorize("settings", "manage")

COMPOSE_HINT = "docker compose pull && docker compose up -d"


class UpdateIn(BaseModel):
    version: str


@router.get("/update")
def update_status(request: Request, user=Depends(_read)):
    settings = request.app.state.settings
    shape = updater.detect_shape(settings)
    body = updater.check(settings)
    can = shape in updater.CAN_SELF_APPLY
    body["install_shape"] = shape
    body["can_self_apply"] = can
    body["compose_hint"] = None if can else COMPOSE_HINT
    return body


@router.post("/update", status_code=202)
def apply_update(request: Request, body: UpdateIn, user=Depends(_manage)):
    settings = request.app.state.settings
    shape = updater.detect_shape(settings)
    if shape not in updater.CAN_SELF_APPLY:
        # Not a failure — a deliberate capability boundary (spec D3). The
        # container never rewrites its own image.
        raise HTTPException(409, {"error": "docker_shape", "compose_hint": COMPOSE_HINT})
    status = updater.check(settings)
    if status["error"]:
        raise HTTPException(502, {"error": "channel_unavailable",
                                  "detail": status["error"]})
    if status["latest"] != body.version:
        # The operator clicked on a version they were shown; the channel has
        # since moved. Installing something they never saw is worse than an
        # error they can re-check.
        raise HTTPException(409, {"error": "no_such_version",
                                  "latest": status["latest"]})
    if not Path(settings.update_script).exists():
        raise HTTPException(503, {"error": "updater_missing",
                                  "detail": f"{settings.update_script} is not installed — "
                                            f"re-run the installer to repair it"})
    write_audit(db_from(request), actor_type="user", actor_id=user.id,
                action="system.update.start", target_type="system",
                ip=request.client.host if request.client else None)
    updater.launch(settings, body.version)
    return {"ok": True, "version": body.version}
```

`write_audit` needs a session — this router does not currently take `db`. Add
`db=Depends(get_db)` to the `apply_update` signature and call
`write_audit(db, ...)`; drop the `db_from` placeholder above. `get_db` is
already imported in this module. Import `HTTPException` from `fastapi`.

- [ ] **Step 5: Run the new tests, then the invariant suites**

Run: `cd backend && .venv/bin/python -m pytest tests/test_update_api.py tests/test_rbac_invariant.py tests/test_route_auth_invariant.py -q`
Expected: PASS. If an invariant test fails, the route's authorization is
wrong — fix the route, never the allowlist.

- [ ] **Step 6: Full backend suite**, then **Commit**

```bash
git add backend/proxploy/api/meta.py backend/proxploy/services/updater.py backend/tests/test_update_api.py
git commit -m "feat(update): status and apply routes, with a hard docker boundary"
```

---

## Task 6: The layout, the systemd unit, and the in-container installer

**Files:**
- Create: `packaging/lib/common.sh`, `packaging/proxploy.service`, `install.sh` (repo root)

**Interfaces:**
- Produces, for Tasks 7, 9, 12, 13:
  - Layout constants in `common.sh`: `PP_ROOT=/opt/proxploy`, `PP_RELEASES=$PP_ROOT/releases`, `PP_CURRENT=$PP_ROOT/current`, `PP_BIN=$PP_ROOT/bin`, `PP_DATA=/var/lib/proxploy`, `PP_ETC=/etc/proxploy`, `PP_ENV=$PP_ETC/proxploy.env`.
  - `log()`, `die()`, `need_root()`, `fetch_to(url, dest)`, `verify_release(dir, pubkey)`, `install_release(tarball, version)` → unpacks to `$PP_RELEASES/$version`, creates its venv, installs deps.
  - `install.sh --shape systemd|lxc --channel <url> --version <v>` — the in-container half, idempotent.

**The layout, fixed here:**

```
/opt/proxploy/releases/<version>/{backend/,frontend/dist/,venv/}
/opt/proxploy/current -> releases/<version>
/opt/proxploy/bin/proxploy-update
/var/lib/proxploy/{proxploy.db,master.key,uploads/,pre-update/}
/etc/proxploy/proxploy.env
/etc/systemd/system/proxploy.service
```

`packaging/proxploy.service`:

```ini
[Unit]
Description=Proxploy
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
# current/ is a symlink; the swap in proxploy-update is what makes rollback
# a pointer move rather than a reinstall.
WorkingDirectory=/opt/proxploy/current/backend
EnvironmentFile=/etc/proxploy/proxploy.env
ExecStart=/opt/proxploy/current/backend/venv/bin/uvicorn --factory proxploy.main:create_app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=3
User=proxploy
Group=proxploy
# Data and secrets live outside the release tree; an update never writes here.
StateDirectory=proxploy
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

**Note on `--factory`:** `backend/proxploy/main.py` exposes `create_app()` and
no module-level `app`. Verify this before writing the unit — if a module-level
`app` has since been added, prefer it and drop `--factory`.

- [ ] **Step 1: Write `packaging/lib/common.sh`**

Required functions, each small enough to read:

```bash
#!/usr/bin/env bash
# Shared helpers for install.sh and proxploy-update. Sourced, never executed.
set -euo pipefail

PP_ROOT="${PP_ROOT:-/opt/proxploy}"
PP_RELEASES="$PP_ROOT/releases"
PP_CURRENT="$PP_ROOT/current"
PP_BIN="$PP_ROOT/bin"
PP_DATA="${PP_DATA:-/var/lib/proxploy}"
PP_ETC="${PP_ETC:-/etc/proxploy}"
PP_ENV="$PP_ETC/proxploy.env"
PP_USER=proxploy

log()  { printf '  %s\n' "$*" >&2; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }
need_root() { [ "$(id -u)" -eq 0 ] || die "run as root"; }

fetch_to() {  # fetch_to <url> <dest>
  local url="$1" dest="$2"
  case "$url" in
    file://*) cp "${url#file://}" "$dest" ;;
    *) curl -fsSL --retry 3 --retry-delay 2 -o "$dest" "$url" ;;
  esac
}

verify_release() {  # verify_release <workdir> <pubkey-pem>
  # openssl verifies the Ed25519 signature over the manifest bytes, then we
  # check the tarball's sha256 against that signed manifest. Same order as
  # services/release.py: signature first, parse second.
  local dir="$1" pub="$2"
  openssl pkeyutl -verify -pubin -inkey "$pub" -rawin \
      -in "$dir/manifest.json" -sigfile "$dir/manifest.json.sig" >/dev/null \
    || die "manifest signature is not valid — refusing to install"
  local want name
  name=$(sed -n 's/.*"name": *"\([^"]*\)".*/\1/p' "$dir/manifest.json" | head -1)
  want=$(sed -n 's/.*"sha256": *"\([^"]*\)".*/\1/p' "$dir/manifest.json" | head -1)
  echo "$want  $dir/$name" | sha256sum -c - >/dev/null \
    || die "$name: sha256 mismatch — refusing to install"
}
```

**Check `openssl pkeyutl -rawin` works on Debian 12's OpenSSL 3** before
relying on it (`openssl pkeyutl -help 2>&1 | grep rawin`). If it is
unavailable, fall back to calling the release release-verification through
Python — but the installer runs *before* any venv exists, so prefer a pure
`openssl` path and only fall back to the system `python3` with `cryptography`
if `openssl` cannot do it. Whichever you pick, say so in a comment.

Also write `install_release()` here: unpack the tarball to
`$PP_RELEASES/$version`, `python3 -m venv` inside it, `pip install -e backend/`
(or `pip install backend/` — read what the tarball actually contains after
Task 11 and match it).

- [ ] **Step 2: Write `install.sh`'s in-container half**

Structure — flags `--shape`, `--channel`, `--version`, `--pubkey`:

1. `need_root`
2. install OS deps: `python3`, `python3-venv`, `curl`, `openssl`, `ca-certificates`, `sqlite3`
3. create the `proxploy` system user if absent (idempotent)
4. `mkdir -p` the layout; `chown` `$PP_DATA` to `proxploy`
5. download manifest + sig + tarball into a temp dir; `verify_release`
6. `install_release` → `$PP_RELEASES/$version`
7. write `$PP_ENV` **only if absent** (an update must never clobber operator
   settings), containing at minimum:
   ```
   PROXPLOY_DB_URL=sqlite:////var/lib/proxploy/proxploy.db
   PROXPLOY_DATA_DIR=/var/lib/proxploy
   PROXPLOY_MASTER_KEY_FILE=/var/lib/proxploy/master.key
   PROXPLOY_INSTALL_SHAPE=<shape>
   PROXPLOY_COOKIE_SECURE=true
   PROXPLOY_UPDATE_SCRIPT=/opt/proxploy/bin/proxploy-update
   ```
8. `alembic upgrade head` using the new release's venv
9. install `packaging/proxploy-update` to `$PP_BIN/` (mode 0755)
10. point `$PP_CURRENT` at the new release (`ln -sfn`, atomic-ish via temp +
    `mv -T`)
11. install and `systemctl enable --now proxploy.service`
12. call the TLS step (Task 8)
13. print the URL and "create the first account at https://<addr>/"

**Idempotency is a hard requirement** (the harness asserts it): a second run
with the same version must not duplicate the user, must not rewrite `$PP_ENV`,
must not wipe the database, and must leave exactly one enabled unit.

- [ ] **Step 3: shellcheck**

Run: `shellcheck install.sh packaging/lib/common.sh`
Expected: no output. If `shellcheck` is not installed, install it
(`apt-get install -y shellcheck`) — it is a required gate, not optional.

- [ ] **Step 4: Commit**

```bash
git add install.sh packaging/lib/common.sh packaging/proxploy.service
git commit -m "feat(install): versioned layout, systemd unit, in-container installer"
```

---

## Task 7: The PVE-host half of the one-liner

**Files:**
- Modify: `install.sh`
- Create: `packaging/tests/test_pve_half.sh`, `packaging/tests/fake-pct`

**Interfaces:**
- Consumes: `common.sh` helpers, the in-container half (Task 6).
- Produces: `install.sh` run with no `--shape` on a node where `pct` exists creates a CT and runs itself inside it with `--shape lxc`.

The one-liner is `curl -fsSL https://proxploy.com/install.sh | bash`. On a
Proxmox node that means: pick storage and bridge, create a Debian CT, push the
installer in, run it, then report the URL. No PVE box exists here, so this half
is proven against a fake `pct`.

**Defaults, all overridable by flag:** CTID = first free ≥ 150 (`pvesh get
/cluster/nextid` when available, else scan `pct list`), 2 cores, 2 GiB RAM,
8 GiB disk, unprivileged, `bridge=vmbr0`, DHCP, `onboot=1`, hostname
`proxploy`.

- [ ] **Step 1: Write the fake `pct` and the failing test**

`packaging/tests/fake-pct` records its arguments so the test can assert on
them:

```bash
#!/usr/bin/env bash
# Test double for pct. Records every invocation; pretends everything worked.
set -euo pipefail
printf '%s\n' "$*" >> "${FAKE_PCT_LOG:?FAKE_PCT_LOG must be set}"
case "${1:-}" in
  list)   printf 'VMID       Status     Name\n' ;;
  create) : ;;
  start)  : ;;
  exec)   : ;;
  push)   : ;;
  *)      : ;;
esac
exit 0
```

`packaging/tests/test_pve_half.sh`:

```bash
#!/usr/bin/env bash
# The PVE half cannot run against real Proxmox on this machine. It CAN be
# held to the exact arguments it would send, which is what actually goes
# wrong: a bad storage pick, a missing bridge, a privileged container.
set -euo pipefail
cd "$(dirname "$0")/../.."

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
export FAKE_PCT_LOG="$tmp/pct.log"
export PATH="$PWD/packaging/tests:$PATH"
: > "$FAKE_PCT_LOG"

# --dry-run stops before running the in-container half, which needs a real CT.
./install.sh --pve-only --dry-run --ctid 150 --storage local-lvm --bridge vmbr0 \
             --channel "file://$PWD/packaging/tests/fixture-channel" --version 1.0.0

grep -q '^create 150' "$FAKE_PCT_LOG"      || { echo "FAIL: no create for 150"; exit 1; }
grep -q 'unprivileged 1' "$FAKE_PCT_LOG"   || { echo "FAIL: CT is not unprivileged"; exit 1; }
grep -q 'storage local-lvm' "$FAKE_PCT_LOG" || { echo "FAIL: storage not honoured"; exit 1; }
grep -q 'net0 .*bridge=vmbr0' "$FAKE_PCT_LOG" || { echo "FAIL: bridge not honoured"; exit 1; }
grep -q 'onboot 1' "$FAKE_PCT_LOG"         || { echo "FAIL: CT will not survive a reboot"; exit 1; }
echo "OK: pve half sends the expected create"
```

- [ ] **Step 2: Run to verify failure**

Run: `bash packaging/tests/test_pve_half.sh`
Expected: FAIL — `install.sh` does not accept `--pve-only`/`--dry-run` yet.

- [ ] **Step 3: Implement the PVE half in `install.sh`**

Add near the top, after flag parsing: if `--shape` was not given, detect —
`command -v pct >/dev/null && [ -d /etc/pve ]` means PVE host. Then:

1. resolve CTID (`--ctid`, else `pvesh get /cluster/nextid`, else scan)
2. resolve storage (`--storage`, else first storage from `pvesm status` that
   supports `rootdir`) and bridge (`--bridge`, else `vmbr0`)
3. download the Debian 12 CT template if absent (`pveam update`,
   `pveam download`)
4. `pct create <ctid> <template> --hostname proxploy --cores 2 --memory 2048
   --rootfs <storage>:8 --unprivileged 1 --features nesting=1 --onboot 1
   --net0 name=eth0,bridge=<bridge>,ip=dhcp`
5. `pct start <ctid>`, wait for network
6. `pct push` the installer in, then `pct exec <ctid> -- bash /root/install.sh
   --shape lxc --channel <url> --version <v>` **with `PROXPLOY_SELF_CTID=<ctid>`
   in the environment**, so the env file records the identity Task 4 persists
7. print the CT's IP and the URL

Under `--dry-run`, stop after step 4's `pct create` (which the fake records)
and skip everything after. Under `--pve-only`, never recurse into the
in-container half.

- [ ] **Step 4: Run the test**

Run: `bash packaging/tests/test_pve_half.sh`
Expected: `OK: pve half sends the expected create`

- [ ] **Step 5: shellcheck and commit**

```bash
shellcheck install.sh packaging/tests/test_pve_half.sh packaging/tests/fake-pct
git add install.sh packaging/tests/
git commit -m "feat(install): PVE-host half — CT create, push, exec, self-ctid"
```

---

## Task 8: TLS — Caddy, arm's-length, self-signed fallback

**Files:**
- Create: `packaging/caddy/Caddyfile.tmpl`
- Modify: `install.sh`

**Interfaces:**
- Consumes: `common.sh` (Task 6).
- Produces: after install, `https://<addr>/` serves the app; `http://` redirects.

Doc 00:47 puts copyleft dependencies at arm's length: Caddy runs as its own
process from its own package. We write config, never code.

`packaging/caddy/Caddyfile.tmpl`:

```
# Proxploy TLS front. The app itself binds 127.0.0.1:8000 and is never
# exposed directly (doc 10 Phase 9: locked-down defaults, LAN bind, TLS on).
{$PROXPLOY_SITE_ADDRESS} {
	# tls internal = Caddy's own CA, no ACME, no public DNS needed. A LAN
	# install with no public hostname still gets TLS; the browser warning is
	# the honest cost, and the docs say so rather than telling people to
	# disable TLS.
	tls {$PROXPLOY_TLS_DIRECTIVE}

	encode zstd gzip
	reverse_proxy 127.0.0.1:8000 {
		# Console and job-log streams are long-lived; the default 
		# flush behaviour would buffer SSE.
		flush_interval -1
	}
}
```

- [ ] **Step 1: Implement the TLS step in `install.sh`**

Add a `configure_tls()` function:
- install `caddy` from the official Debian repo (documented in the docs task
  9c; here just `apt-get install -y caddy` after adding the repo, guarded so a
  re-run is a no-op)
- if `--hostname <fqdn>` was passed, `PROXPLOY_SITE_ADDRESS=<fqdn>` and
  `PROXPLOY_TLS_DIRECTIVE=` (empty → Caddy does ACME)
- otherwise `PROXPLOY_SITE_ADDRESS=https://<primary-ip>` and
  `PROXPLOY_TLS_DIRECTIVE=internal`
- render the template to `/etc/caddy/Caddyfile`, `systemctl enable --now caddy`
- set `PROXPLOY_COOKIE_SECURE=true` in `$PP_ENV` (already in Task 6's env
  block — verify it is there rather than writing it twice)

- [ ] **Step 2: Verify by hand in the Task 12 harness**

There is no separate test here — TLS is asserted by the container harness
(Task 12), which curls `https://localhost/api/v1/meta/health` and requires a
2xx. Do not write a mock-Caddy test; it would prove nothing the harness does
not prove for real.

- [ ] **Step 3: shellcheck and commit**

```bash
shellcheck install.sh
git add packaging/caddy/Caddyfile.tmpl install.sh
git commit -m "feat(install): Caddy TLS front with tls-internal fallback"
```

---

## Task 9: `proxploy-update` — the whole update, in one boring script

**Files:**
- Create: `packaging/proxploy-update`

**Interfaces:**
- Consumes: `common.sh` (Task 6), the layout, the channel format (Task 2).
- Produces, for Tasks 13 and 14: `proxploy-update --to <version> --channel <url>`; exit 0 on success, non-zero on failure **after having rolled back**.

This is the script doc 11:293 calls "the most boring code in the repo". No
functions that do two things, no cleverness, one linear path, and every failure
after the switch goes through exactly one rollback function.

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# Proxploy self-update (Phase 9a).
#
# Runs OUTSIDE the app's cgroup, launched by systemd-run from
# services/updater.py::launch. That is deliberate: this script restarts
# proxploy.service, and anything inside that cgroup would be killed halfway
# through, leaving the symlink swapped and nothing serving.
#
# Order matters and is not negotiable:
#   backup BEFORE download   (a full disk must not cost you the database)
#   verify BEFORE unpack     (never write unverified bytes into releases/)
#   migrate BEFORE switch    (a failed migration leaves the old version running)
#   health  AFTER  switch    (and any failure from here rolls back)
set -euo pipefail
# shellcheck source=lib/common.sh
. "$(dirname "$0")/../lib/common.sh" 2>/dev/null || . /opt/proxploy/lib/common.sh

TO=""; CHANNEL=""; FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --to) TO="$2"; shift 2 ;;
    --channel) CHANNEL="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    *) die "unknown argument: $1" ;;
  esac
done
[ -n "$TO" ] || die "--to <version> is required"
need_root

FROM=$(readlink "$PP_CURRENT" | xargs basename)
BACKUP="$PP_DATA/pre-update/$FROM"

rollback() {
  log "rolling back to $FROM"
  ln -sfn "$PP_RELEASES/$FROM" "$PP_CURRENT.tmp" && mv -T "$PP_CURRENT.tmp" "$PP_CURRENT"
  if [ -f "$BACKUP/proxploy.db" ]; then
    cp -a "$BACKUP/proxploy.db" "$PP_DATA/proxploy.db"
  fi
  systemctl restart proxploy.service || true
  die "update to $TO failed; rolled back to $FROM"
}

# --- preflight -------------------------------------------------------------
[ "$TO" != "$FROM" ] || die "already running $TO"
[ -d "$PP_RELEASES/$TO" ] && [ "$FORCE" -eq 0 ] && die "$TO is already unpacked; use --force"
avail=$(df -Pk "$PP_ROOT" | awk 'NR==2 {print $4}')
[ "$avail" -gt 2097152 ] || die "less than 2 GiB free on $PP_ROOT — refusing to update"

# --- backup ----------------------------------------------------------------
log "backing up $FROM"
mkdir -p "$BACKUP"
if [ -f "$PP_DATA/proxploy.db" ]; then
  # sqlite3 .backup is safe against a live writer; cp is not.
  sqlite3 "$PP_DATA/proxploy.db" ".backup '$BACKUP/proxploy.db'"
fi
cp -a "$PP_DATA/master.key" "$BACKUP/master.key" 2>/dev/null || true
echo "$FROM" > "$BACKUP/version"

# --- download + verify -----------------------------------------------------
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
log "fetching $TO"
fetch_to "$CHANNEL/manifest.json"     "$work/manifest.json"
fetch_to "$CHANNEL/manifest.json.sig" "$work/manifest.json.sig"
tarball=$(sed -n 's/.*"name": *"\([^"]*\)".*/\1/p' "$work/manifest.json" | head -1)
fetch_to "$CHANNEL/$tarball" "$work/$tarball"
verify_release "$work" "$PP_CURRENT/backend/proxploy/release_pubkey.pem"

# --- unpack + migrate ------------------------------------------------------
log "installing $TO"
install_release "$work/$tarball" "$TO"
log "migrating database"
"$PP_RELEASES/$TO/backend/venv/bin/alembic" -c "$PP_RELEASES/$TO/backend/alembic.ini" \
  upgrade head || { log "migration failed; nothing was switched"; exit 1; }

# --- switch + health -------------------------------------------------------
log "switching to $TO"
ln -sfn "$PP_RELEASES/$TO" "$PP_CURRENT.tmp" && mv -T "$PP_CURRENT.tmp" "$PP_CURRENT"
systemctl restart proxploy.service || rollback

deadline=$(( $(date +%s) + 120 ))
until curl -fsS --max-time 5 http://127.0.0.1:8000/api/v1/meta/health >/dev/null 2>&1; do
  [ "$(date +%s)" -lt "$deadline" ] || rollback
  sleep 2
done

log "update to $TO complete"
```

**Note on the migration failure path:** it exits 1 *without* rolling back,
because nothing was switched — the old version is still running and its
database is untouched by a migration that failed to apply. Rolling back here
would restore a backup over a database that was never changed.

- [ ] **Step 2: shellcheck**

Run: `shellcheck packaging/proxploy-update`
Expected: no output. Resolve every warning; `# shellcheck disable` is only
acceptable with a comment saying why.

- [ ] **Step 3: Verify `sqlite3 .backup` exists in the install image**

Task 6's dependency list must include `sqlite3`. Confirm it is there; if not,
add it in this task — the backup step is the one thing that must not fail.

- [ ] **Step 4: Commit**

```bash
git add packaging/proxploy-update
git commit -m "feat(update): the updater — backup, verify, migrate, switch, roll back"
```

---

## Task 10: The Docker shape

**Files:**
- Create: `packaging/docker/Dockerfile`, `packaging/docker/compose.yml`, `packaging/docker/entrypoint.sh`

**Interfaces:**
- Produces: an image that sets `PROXPLOY_IN_DOCKER=1` so `detect_shape` (Task 3) returns `"docker"` and `POST /meta/update` 409s with the compose hint.

- [ ] **Step 1: Write the Dockerfile**

Multi-stage: build the frontend with Node, install the backend into a venv,
copy both into a slim runtime image. The runtime image must place the tree so
`main.py:167`'s `parents[2]/frontend/dist` still resolves — i.e. the same
`backend/` + `frontend/dist/` shape as a release tarball.

```dockerfile
FROM node:22-slim AS web
WORKDIR /src
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
RUN adduser --system --group proxploy \
 && apt-get update && apt-get install -y --no-install-recommends sqlite3 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/proxploy/current
COPY backend/ backend/
COPY --from=web /src/dist/ frontend/dist/
RUN python -m venv backend/venv && backend/venv/bin/pip install --no-cache-dir ./backend
# The app never self-applies an update in this shape (spec D3) — the UI shows
# the compose command instead. This is the flag that makes that true.
ENV PROXPLOY_IN_DOCKER=1 \
    PROXPLOY_DATA_DIR=/var/lib/proxploy \
    PROXPLOY_DB_URL=sqlite:////var/lib/proxploy/proxploy.db \
    PROXPLOY_MASTER_KEY_FILE=/var/lib/proxploy/master.key
VOLUME /var/lib/proxploy
USER proxploy
EXPOSE 8000
COPY packaging/docker/entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
```

`entrypoint.sh` runs `alembic upgrade head` then execs uvicorn
(`--factory proxploy.main:create_app --host 0.0.0.0 --port 8000`). Binding
`0.0.0.0` is correct **inside** a container; the compose file is what maps it.

`compose.yml` — this exact file is what the docs and the UI's copy button
reference, so keep it short and readable:

```yaml
services:
  proxploy:
    image: ghcr.io/aspyrelabs/proxploy:latest
    restart: unless-stopped
    ports: ["8006:8000"]
    volumes: ["proxploy-data:/var/lib/proxploy"]
volumes:
  proxploy-data:
```

- [ ] **Step 2: Build it and prove the shape**

```bash
docker build -f packaging/docker/Dockerfile -t proxploy:dev .
docker run --rm -d --name pp-shape -p 18006:8000 proxploy:dev
sleep 5
curl -fsS http://127.0.0.1:18006/api/v1/meta/health
docker rm -f pp-shape
```

Expected: `{"status":"ok"}`.

- [ ] **Step 3: Commit**

```bash
git add packaging/docker/
git commit -m "feat(install): Docker image and compose file; detect-and-instruct update shape"
```

---

## Task 11: `build_release.sh` and the local channel fixture

**Files:**
- Create: `packaging/build_release.sh`, `packaging/tests/channel_fixture.sh`

**Interfaces:**
- Consumes: the manifest schema (Task 2), `proxploy.__version__` (Task 1).
- Produces, for Tasks 12–13: `build_release.sh --version <v> --key <pem> --out <dir>` → `<dir>/{proxploy-<v>.tar.gz, manifest.json, manifest.json.sig}`; `channel_fixture.sh <dir>` → a two-release channel (1.0.0 and 1.0.1) plus `DEV_ONLY_release_key.pem`.

- [ ] **Step 1: Write `build_release.sh`**

Steps it performs, in order:
1. `npm ci && npm run build` in `frontend/`
2. stage a tree: `backend/` (excluding `.venv`, `__pycache__`, `tests/`,
   `dod_verify_*`) + `frontend/dist/`
3. **override the staged `backend/proxploy/__init__.py` version with
   `--version`** so the artifact, the manifest and the tag cannot disagree
4. `tar czf proxploy-<v>.tar.gz` from the staging root
5. compute sha256 and size, write `manifest.json` in the Task 2 schema
6. `openssl pkeyutl -sign -inkey <key> -rawin -in manifest.json -out manifest.json.sig`
7. print the manifest

- [ ] **Step 2: Write `channel_fixture.sh`**

Generates a throwaway Ed25519 keypair (if absent), then calls
`build_release.sh` twice — once as `1.0.0`, once as `1.0.1` — into
`<dir>/1.0.0/` and `<dir>/1.0.1/`, and writes the matching public key to
`<dir>/release.pem`. Tasks 12 and 13 point `--channel file://<dir>/<version>`
at these.

It must also be able to build a **poisoned** release on request
(`--poison <version>`): identical, except the staged
`backend/proxploy/main.py` gets a line inserted that raises on startup. Task 13
uses this to prove rollback. Insert the failure with a clearly marked
`# POISONED BY channel_fixture.sh` comment so nobody ever mistakes it for real
code.

- [ ] **Step 3: Build the fixture and verify it round-trips**

```bash
bash packaging/tests/channel_fixture.sh /tmp/pp-channel
cd backend && .venv/bin/python - <<'PY'
from pathlib import Path
from proxploy.services.release import verify_manifest, verify_artifact
d = Path("/tmp/pp-channel/1.0.1")
m = verify_manifest((d/"manifest.json").read_bytes(),
                    (d/"manifest.json.sig").read_bytes(),
                    Path("/tmp/pp-channel/release.pem").read_bytes())
verify_artifact(d / m["artifacts"]["tarball"]["name"], m["artifacts"]["tarball"])
print("OK", m["version"])
PY
```

Expected: `OK 1.0.1`. **This is the proof that the shell signer and the Python
verifier agree** — two implementations of the same format, which is exactly
where a format drifts.

- [ ] **Step 4: shellcheck and commit**

```bash
shellcheck packaging/build_release.sh packaging/tests/channel_fixture.sh
git add packaging/build_release.sh packaging/tests/channel_fixture.sh
git commit -m "feat(release): release builder and signed local channel fixture"
```

---

## Task 12: The container install harness

**Files:**
- Create: `packaging/tests/test_install.sh`

**Interfaces:**
- Consumes: `install.sh` (Tasks 6–8), `channel_fixture.sh` (Task 11).

A Proxmox LXC is a Debian userspace with systemd. Docker can give us exactly
that with `systemd` as PID 1, so the in-container half of the installer runs
**for real** — same script, same systemd, same Caddy, same TLS.

- [ ] **Step 1: Write the harness**

```bash
#!/usr/bin/env bash
# Runs the REAL installer in a REAL Debian container with systemd as PID 1.
# What this proves: the unit comes up, TLS serves the app, and a second run
# changes nothing. What it does not prove: `pct create` (test_pve_half.sh) or
# a real release channel (spec D4).
set -euo pipefail
cd "$(dirname "$0")/../.."

CH=${CH:-/tmp/pp-channel}
[ -d "$CH" ] || bash packaging/tests/channel_fixture.sh "$CH"

name=pp-install-$$
cleanup() { docker rm -f "$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$name" --privileged \
  --tmpfs /run --tmpfs /run/lock -v /sys/fs/cgroup:/sys/fs/cgroup:rw \
  --cgroupns=host \
  -v "$PWD:/src:ro" -v "$CH:/channel:ro" \
  debian:12 /sbin/init >/dev/null

# systemd needs a moment to reach a usable state before we install into it.
for _ in $(seq 30); do
  docker exec "$name" systemctl is-system-running --wait >/dev/null 2>&1 && break
  sleep 1
done

docker exec "$name" bash -c "apt-get update -qq && apt-get install -y -qq curl ca-certificates >/dev/null"
docker exec "$name" bash -c \
  "cp -r /src/install.sh /src/packaging /tmp/ && cd /tmp && \
   ./install.sh --shape systemd --channel file:///channel/1.0.0 --version 1.0.0 \
                --pubkey /channel/release.pem"

docker exec "$name" systemctl is-active --quiet proxploy.service \
  || { echo "FAIL: proxploy.service is not active"; docker exec "$name" journalctl -u proxploy --no-pager | tail -40; exit 1; }
echo "OK: unit is active"

docker exec "$name" curl -fsS http://127.0.0.1:8000/api/v1/meta/health | grep -q '"ok"' \
  || { echo "FAIL: app does not answer"; exit 1; }
echo "OK: app answers on the loopback bind"

docker exec "$name" curl -fsSk https://127.0.0.1/api/v1/meta/health | grep -q '"ok"' \
  || { echo "FAIL: TLS front does not serve"; exit 1; }
echo "OK: TLS front serves"

# Idempotency: the second run must change nothing that matters.
docker exec "$name" bash -c "sqlite3 /var/lib/proxploy/proxploy.db \
  \"insert into settings (key, value) values ('harness.canary', '1')\"" || true
before=$(docker exec "$name" md5sum /etc/proxploy/proxploy.env | cut -d' ' -f1)
docker exec "$name" bash -c \
  "cd /tmp && ./install.sh --shape systemd --channel file:///channel/1.0.0 \
                           --version 1.0.0 --pubkey /channel/release.pem"
after=$(docker exec "$name" md5sum /etc/proxploy/proxploy.env | cut -d' ' -f1)
[ "$before" = "$after" ] || { echo "FAIL: re-run rewrote proxploy.env"; exit 1; }
docker exec "$name" bash -c "sqlite3 /var/lib/proxploy/proxploy.db \
  \"select value from settings where key='harness.canary'\"" | grep -q 1 \
  || { echo "FAIL: re-run destroyed the database"; exit 1; }
docker exec "$name" systemctl is-active --quiet proxploy.service \
  || { echo "FAIL: re-run left the unit down"; exit 1; }
echo "OK: re-run is idempotent"
echo "PASS: install harness"
```

**Check the settings table's real column names** (`backend/proxploy/models/`)
before writing the canary insert — if it is not `(key, value)`, use whatever
it is.

- [ ] **Step 2: Run it**

Run: `bash packaging/tests/test_install.sh`
Expected: four `OK:` lines then `PASS: install harness`. Expect to iterate on
`install.sh` here — this is the first time it runs for real. Fix the
installer, never the harness's assertions.

- [ ] **Step 3: Commit**

```bash
git add packaging/tests/test_install.sh
git commit -m "test(install): real Debian+systemd container harness for the installer"
```

---

## Task 13: The upgrade and rollback harness

**Files:**
- Create: `packaging/tests/test_upgrade_rollback.sh`

**Interfaces:**
- Consumes: `test_install.sh`'s container recipe, `proxploy-update` (Task 9), the poisoned release from `channel_fixture.sh` (Task 11).

This proves the two claims the phase actually rests on: an update applies, and
a bad update undoes itself.

- [ ] **Step 1: Write the harness**

Same container setup as Task 12 (extract the `docker run` + systemd-wait block
into `packaging/tests/lib.sh` and source it from both, rather than
copy-pasting — the second copy is where they drift). Then:

```bash
# 1. install 1.0.0 and seed a row we can look for afterwards
install_in_container 1.0.0
docker exec "$name" bash -c "sqlite3 /var/lib/proxploy/proxploy.db \
  \"insert into settings (key, value) values ('harness.canary','keep-me')\""

# 2. upgrade to 1.0.1
docker exec "$name" /opt/proxploy/bin/proxploy-update --to 1.0.1 \
  --channel file:///channel/1.0.1

docker exec "$name" readlink /opt/proxploy/current | grep -q '1\.0\.1' \
  || { echo "FAIL: current does not point at 1.0.1"; exit 1; }
docker exec "$name" curl -fsS http://127.0.0.1:8000/api/v1/meta/health | grep -q ok \
  || { echo "FAIL: app is down after upgrade"; exit 1; }
docker exec "$name" bash -c "sqlite3 /var/lib/proxploy/proxploy.db \
  \"select value from settings where key='harness.canary'\"" | grep -q keep-me \
  || { echo "FAIL: upgrade lost data"; exit 1; }
docker exec "$name" test -f /var/lib/proxploy/pre-update/1.0.0/proxploy.db \
  || { echo "FAIL: no pre-update backup was taken"; exit 1; }
echo "OK: 1.0.0 -> 1.0.1 upgrade, data intact, backup present"

# 3. try the poisoned 1.0.2 — it must fail AND put us back on 1.0.1
if docker exec "$name" /opt/proxploy/bin/proxploy-update --to 1.0.2 \
     --channel file:///channel/1.0.2; then
  echo "FAIL: poisoned release reported success"; exit 1
fi
docker exec "$name" readlink /opt/proxploy/current | grep -q '1\.0\.1' \
  || { echo "FAIL: did not roll back to 1.0.1"; exit 1; }
docker exec "$name" curl -fsS http://127.0.0.1:8000/api/v1/meta/health | grep -q ok \
  || { echo "FAIL: app is down after rollback — the worst outcome"; exit 1; }
docker exec "$name" bash -c "sqlite3 /var/lib/proxploy/proxploy.db \
  \"select value from settings where key='harness.canary'\"" | grep -q keep-me \
  || { echo "FAIL: rollback lost data"; exit 1; }
echo "OK: poisoned 1.0.2 rejected, rolled back to 1.0.1, app healthy"
echo "PASS: upgrade + rollback harness"
```

Build the poisoned 1.0.2 in step 0:
`bash packaging/tests/channel_fixture.sh /tmp/pp-channel --poison 1.0.2`.

- [ ] **Step 2: Run it**

Run: `bash packaging/tests/test_upgrade_rollback.sh`
Expected: both `OK:` lines then `PASS`. The rollback assertion is the one that
matters most — if the app is down at the end, the phase's core promise is
false and the updater needs fixing.

- [ ] **Step 3: Commit**

```bash
git add packaging/tests/test_upgrade_rollback.sh packaging/tests/lib.sh
git commit -m "test(update): upgrade and forced-rollback harness in a real container"
```

---

## Task 14: The Settings update card

**Files:**
- Modify: `frontend/src/api/account.ts`, `frontend/src/routes/settings.tsx`
- Create: `frontend/src/components/UpdateCard.tsx`, `frontend/src/tests/update.test.tsx`

**Interfaces:**
- Consumes: `GET /api/v1/meta/update`, `POST /api/v1/meta/update` (Task 5).

Follow `ApiKeysCard.tsx` for structure and `settings.tsx`'s local `Card`
helper for chrome. Behaviour:

- shows current version always; "up to date" when there is nothing newer
- `error` present → show it as an inline warning, not a toast, and still show
  the current version. A broken channel is not an emergency.
- `update_available && can_self_apply` → "Update to X" button + release-notes
  link. Clicking POSTs `{version: latest}`, then polls `GET /meta/version`
  every 3s. Version changes → success. `update_timeout_s` elapses → "lost
  contact with the server while updating — check the host" (**not** a success
  claim; the client genuinely cannot know).
- `update_available && !can_self_apply` (docker) → render `compose_hint` in a
  monospace block with a copy button and the sentence "Proxploy does not
  update its own container — run this on the Docker host."

- [ ] **Step 1: Write the failing tests**

`frontend/src/tests/update.test.tsx`, mocking `../api/client` per
`apikeys.test.tsx`:

1. up-to-date state renders the version and no button
2. available + `can_self_apply` renders "Update to 1.0.1" and the notes link
3. clicking it POSTs `/meta/update` with `{version: '1.0.1'}`
4. docker shape renders the compose command and **no** apply button
5. a channel `error` renders the message and still shows the current version
6. after applying, a `/meta/version` that changes flips the card to the new
   version

- [ ] **Step 2–4:** verify failure → implement → `cd frontend && npx vitest run --no-file-parallelism` (floor 199 + 6) and `npm run build` clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/UpdateCard.tsx frontend/src/tests/update.test.tsx \
        frontend/src/api/account.ts frontend/src/routes/settings.tsx
git commit -m "feat(ui): update card — apply, poll, and the honest docker boundary"
```

---

## Task 15: CI gates and the publication runbook

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `docs/runbooks/publishing-a-release.md`

- [ ] **Step 1: Add the CI jobs**

```yaml
  scripts:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: sudo apt-get update && sudo apt-get install -y shellcheck
      - run: shellcheck install.sh packaging/proxploy-update packaging/lib/*.sh packaging/tests/*.sh packaging/build_release.sh

  install-harness:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: {node-version: "22"}
      - run: bash packaging/tests/channel_fixture.sh /tmp/pp-channel
      - run: bash packaging/tests/test_install.sh
      - run: bash packaging/tests/test_upgrade_rollback.sh
      - run: bash packaging/tests/test_pve_half.sh
```

- [ ] **Step 2: Write `docs/runbooks/publishing-a-release.md`**

Spec D4 keeps publication out of implementation. This runbook is the thing a
human runs, once, when ready. It must state, in order:

1. **Generate the release keypair offline.** `openssl genpkey -algorithm ed25519`.
   The private key goes in a password manager, never in the repo, never in CI
   secrets during 9a. Replace `backend/proxploy/release_pubkey.pem` with the
   real public key and commit that — **the public key ships in the artifact, so
   rotating it requires publishing a release** (same bootstrap property doc
   09:153 records for the entitlement key).
2. `gh repo edit aspyrelabs/proxploy-app --visibility public` — irreversible in
   practice; the whole history becomes public. Check the history for secrets
   first (`git log -p | grep -iE 'BEGIN .*PRIVATE KEY|password|token'`).
3. `bash packaging/build_release.sh --version 1.0.0 --key <key> --out dist/`
4. `gh release create v1.0.0 dist/* --notes-file <notes>` — prereleases are the
   **edge** channel, `latest` is **stable** (spec D1).
5. Verify from a clean box: `curl -fsSL <raw install.sh URL> | bash`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml docs/runbooks/publishing-a-release.md
git commit -m "ci(9a): shellcheck and install/upgrade harness gates; publication runbook"
```

---

## Task 16: DoD verification, notes, buildlog

**Files:**
- Create: `backend/dod_verify_phase9a.py` (throwaway, gitignored by the existing `dod_verify*` pattern — confirm), `docs/notes/phase-9a-install-update.md`
- Modify: `buildlog.md`

- [ ] **Step 1: Write `dod_verify_phase9a.py`** — four checks, each printing `OK`/`FAIL`, exit non-zero on any failure, following `dod_verify_phase8.py`'s pattern:
  1. **Signed-release verification** — build a channel, verify it, then assert a tampered manifest, a wrong key, and a downgrade are each refused. Print the count of refusals.
  2. **Install** — shell out to `packaging/tests/test_install.sh`, print its `OK:` lines. Output line must read `OK (real Debian container with systemd — no Proxmox node on this machine; the pct half is proven separately against a fake pct)`.
  3. **Upgrade + rollback** — shell out to `test_upgrade_rollback.sh`; print the version transitions.
  4. **Docker boundary** — start the app with `install_shape="docker"` via `tests.support.make_app` and assert `POST /meta/update` 409s with the compose hint, proving the container never self-applies.
  Run it twice; output identical apart from container names and timings.

- [ ] **Step 2: Write `docs/notes/phase-9a-install-update.md`** — same skeleton as `docs/notes/phase-8-scale.md`: what shipped per subsystem; findings that contradicted the docs; residual limitations (**at minimum**: no real Proxmox node — the PVE half is fake-`pct` only; no real GitHub release channel — everything ran against a local file-served channel with a throwaway key; the release private key does not exist yet and the shipped `release_pubkey.pem` is a placeholder that the runbook replaces; Docker installs cannot self-apply **by design**, not by omission); gate numbers table with the real counts; commit range.

- [ ] **Step 3: `buildlog.md`** — the phase entry in the established format (see the Phase 8 entry), including the "Known gaps, stated plainly" section.

- [ ] **Step 4: Run everything and record real numbers** — DoD script ×2, full backend suite, frontend suite (`--no-file-parallelism`) + build + lint, all four shell harnesses, `shellcheck`, `alembic heads`. Never write a projected number.

- [ ] **Step 5: Commit**

```bash
git add docs/notes/phase-9a-install-update.md buildlog.md
git commit -m "docs(phase-9a): DoD verification, notes, buildlog"
```

---

## Self-Review

Checked after writing, against the spec and the shaping constraints:

1. **Spec coverage** — D1 release channel: Tasks 3, 11, 15. D2 separate
   Ed25519 release key: Tasks 2, 3 (placeholder), 15 (real key, runbook). D3
   per-shape update behaviour: Tasks 3, 5, 10, 14. D4 build-and-prove without
   publishing: every test uses a local channel; publication is Task 15's
   runbook only. Layout: Task 6. Standalone updater: Task 9. Installer both
   halves: Tasks 6, 7. Caddy TLS: Task 8. API surface: Task 5. Version single
   source of truth: Task 1. The verification table in the spec maps to Tasks
   12 (install, idempotency, TLS), 7 (PVE half), 13 (upgrade, rollback), 2
   (signature enforcement), 5 + 16 (docker boundary), 15 (shellcheck).
   `self.ctid`, which the spec mentions only in passing via `selfguard.py`,
   has its own task (4) because the hook has been inert since Phase 4.
2. **Placeholder scan** — no "TBD"/"handle errors appropriately". The three
   places an implementer must check a fact before coding say exactly what to
   check and what to do with each answer: `openssl pkeyutl -rawin`
   availability (Task 6), the `settings` table's real column names (Task 12),
   and whether `main.py` still exposes only a factory (Task 6). Task 8 has no
   unit test *by intent*, stated in the task.
3. **Type consistency** — `verify_manifest(raw, sig, pubkey_pem) -> dict`,
   `verify_artifact(path, entry)`, `is_upgrade(current, candidate)`,
   `ReleaseError` are used identically in Tasks 2, 3, 9, 11, 16.
   `detect_shape`/`CAN_SELF_APPLY`/`check`/`launch` identical in 3, 5, 16. The
   manifest JSON shape in Task 2 is what Tasks 3, 9 and 11 read and write. The
   layout constants from Task 6 are used verbatim in 7, 9, 12, 13.
4. **Honesty** — the two things this machine cannot prove (a real Proxmox node,
   a real published release channel) are declared in Global Constraints, in
   the DoD script's own printed output (Task 16 Step 1.2), and in the notes'
   residual-limitations list. The Docker no-self-update boundary is recorded as
   a deliberate capability decision rather than a missing feature.

