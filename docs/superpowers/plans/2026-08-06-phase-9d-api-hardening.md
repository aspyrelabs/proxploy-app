# Phase 9d: proxploy-api production hardening

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the licensing service ready to deploy, Postgres, rate limits, a real license-key format, install binding that survives a reinstall, a health check that checks something, structured logs, and a rotation runbook; without deploying it.

**Architecture:** Postgres replaces SQLite first, because every later task's tests run against whatever `conftest.py` builds. Then a new `licensekey` module owns key generation and validation, applied before any database lookup. Then `install_id` binding on `refresh`/`revoke` plus the rebind path through `activate`. Rate limiting copies `proxploy-app`'s `slowapi` idiom verbatim. Logging, health and rotation are additive.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Alembic, PyJWT (EdDSA), `psycopg[binary]`, `slowapi`, pytest, Postgres 16 via Docker.

**Spec:** `docs/superpowers/specs/2026-08-06-phase-9d-api-hardening-design.md` (in `proxploy-app`)

---

## Global Constraints

Every task's requirements implicitly include this section.

- **The repo is `/home/aasim/workspace/aspyrelabs/proxploy/proxploy-api`** for Tasks 1–7 and 9. **Task 8 touches `proxploy-app`.** Both have remotes; commit directly to `main`, never branch.
- **`proxploy-api` stays private permanently.** It is distributed as a running service, never as source. Do not add public-facing readme copy, and do not assume a reader of this repo is a customer.
- **Nothing deploys.** No Dockerfile for the service, no hosting, no DNS, no monitoring backend. `docker` is used only to run Postgres for tests.
- **`tiers.yaml` keeps `all_entitled: true`.** Do not arm tiers, do not populate the `tiers:` map, do not gate any feature.
- **No shared API secret.** Any credential the app presents lives in `proxploy-app`, which becomes public; it would be extractable. Rate limits, key entropy and install binding are the defence; caller authentication is not.
- **Python floor is 3.12** (`requires-python = ">=3.12"`).
- **Test floor: the suite currently has 4 tests and they all pass.** Never let the count drop; every task adds tests.
- **Secrets are never logged.** License keys, refresh credentials and signing-key material must not appear in logs in full or in part. A SHA-256 prefix is acceptable as a correlation handle.
- **`proxploy-app` keeps SQLite-WAL.** The Postgres rule applies to Aspyre's own services, not to the database a customer runs on their own hardware. Do not touch `proxploy-app`'s database configuration.

---

## Task Order and Dependencies

```
Task 1  Postgres            -> MUST land first; every other task's tests run on it
Task 2  License key format  (needs 1, regenerates fixtures)
Task 3  install_id binding  (needs 1, 2; its tests use generated keys)
Task 4  Rate limiting       (needs 1)
Task 5  Structured logging  (needs 1)
Task 6  Health check        (needs 1)
Task 7  Rotation + runbook  (needs 1)
Task 8  proxploy-app gaps   independent, different repo, can run any time
Task 9  DoD, notes, buildlog (last)
```

Task 1 is a hard barrier. Tasks 4–7 are mutually independent once it lands but all touch `main.py`, so run them sequentially or expect conflicts. Task 8 is in a different repo and can run in parallel with anything.

---

## Task 1: Postgres replaces SQLite

**Files:**
- Modify: `proxploy_api/config.py`, `proxploy_api/db.py`, `pyproject.toml`, `tests/conftest.py`, `.github/workflows/ci.yml`, `scripts/create_license.py`
- Create: `docker-compose.test.yml`

**Interfaces:**
- Produces, for every later task: `conftest.py`'s `client` fixture yields a `TestClient` backed by a **real Postgres**, and `pg_dsn` is a session-scoped fixture returning a `postgresql+psycopg://…` DSN.

`proxploy-app`'s pattern skips Postgres tests when a DSN is unset, because SQLite is its primary. **That is not available here**: Postgres becomes the only database, so a skip means the suite proves nothing. The fixture must guarantee a database exists.

This box has **no Postgres binaries at all** (`pg_isready`, `psql`, `initdb`, `pg_ctl` all absent; nothing listening on 5432) but **Docker 29.1.3 works**. So: use an existing DSN if one is provided, otherwise start a throwaway container.

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, add `"psycopg[binary]>=3.2"` to `dependencies` and `"pytest-asyncio>=0.24"` is **not** needed; do not add it. The dev extra stays `["pytest>=8", "httpx>=0.27"]`.

- [ ] **Step 2: Point settings and engine at Postgres**

`proxploy_api/config.py`: change the default only:

```python
    db_url: str = "postgresql+psycopg://proxploy:proxploy@localhost:5432/proxploy_api"
```

`proxploy_api/db.py`: delete the sqlite branch entirely. `make_engine` becomes:

```python
def make_engine(settings: Settings):
    return create_engine(settings.db_url, pool_pre_ping=True)
```

Drop the now-unused `event` import. `pool_pre_ping=True` matters for a long-lived service against a network database, a stale pooled connection otherwise surfaces as a request failure.

Leave `models/__init__.py`'s `BigPK = BigInteger().with_variant(Integer, "sqlite")` alone. It is harmless on Postgres (the variant simply never applies) and removing it is churn in a file this task has no other reason to touch.

- [ ] **Step 3: Write the conftest fixture**

Replace `tests/conftest.py`'s sqlite wiring. The `pg_dsn` fixture is session-scoped so one container serves the whole run:

```python
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

REPO = Path(__file__).resolve().parents[1]
PG_IMAGE = "postgres:16"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def pg_dsn():
    """A real Postgres for the whole run.

    PROXPLOY_API_TEST_DSN wins when set; that is how CI hands us its
    `services:` container. With nothing set we start a throwaway container,
    because this box has no Postgres binaries at all (no initdb, no pg_ctl,
    nothing on 5432) and Postgres is now the only database this service
    speaks. Skipping when a DSN is absent would mean the suite proves
    nothing, which is exactly the trap to avoid.
    """
    dsn = os.environ.get("PROXPLOY_API_TEST_DSN")
    if dsn:
        yield dsn
        return

    port = _free_port()
    name = f"proxploy-api-test-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", name,
         "-e", "POSTGRES_PASSWORD=proxploy", "-e", "POSTGRES_USER=proxploy",
         "-e", "POSTGRES_DB=proxploy_api",
         "-p", f"127.0.0.1:{port}:5432", PG_IMAGE],
        check=True, capture_output=True)
    try:
        deadline = time.time() + 60
        while True:
            ready = subprocess.run(
                ["docker", "exec", name, "pg_isready", "-U", "proxploy"],
                capture_output=True)
            if ready.returncode == 0:
                break
            if time.time() > deadline:
                raise RuntimeError(f"{PG_IMAGE} did not become ready in 60s")
            time.sleep(1)
        yield f"postgresql+psycopg://proxploy:proxploy@127.0.0.1:{port}/proxploy_api"
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


@pytest.fixture
def clean_db(pg_dsn):
    """Blank schema per test. Tests share one server; they must not share
    state, and dropping the schema is faster than recreating the database."""
    eng = create_engine(pg_dsn)
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    eng.dispose()
    return pg_dsn


@pytest.fixture
def client(clean_db, tmp_path, monkeypatch):
    monkeypatch.setenv("PROXPLOY_API_DB_URL", clean_db)
    key = tmp_path / "sign.key"
    subprocess.run([sys.executable, str(REPO / "scripts/gen_signing_key.py"),
                    "--kid", "test-kid", "--out", str(key)], check=True)
    monkeypatch.setenv("PROXPLOY_API_SIGNING_KEY_FILE", str(key))
    monkeypatch.setenv("PROXPLOY_API_KID", "test-kid")
    from proxploy_api.config import get_settings
    get_settings.cache_clear()
    from proxploy_api.main import create_app
    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()


@pytest.fixture
def license_key(clean_db):
    out = subprocess.run(
        [sys.executable, str(REPO / "scripts/create_license.py"), "--tier", "pro",
         "--db-url", clean_db],
        check=True, capture_output=True, text=True)
    return out.stdout.strip()
```

**Ordering trap to get right:** `license_key` and `client` both depend on `clean_db`, and pytest caches it per test, so the schema is dropped **once** and both see the same database. If you make `clean_db` do its work twice, `create_license.py` writes a row and `client` then wipes it. The existing `test_activate_refresh_revoke_cycle` will catch this immediately with a 404.

- [ ] **Step 4: A compose file for running the suite locally**

`docker-compose.test.yml`:

```yaml
# Optional: `docker compose -f docker-compose.test.yml up -d`, then
# PROXPLOY_API_TEST_DSN=postgresql+psycopg://proxploy:proxploy@127.0.0.1:5432/proxploy_api
# to reuse one server across runs. Without it the suite starts its own
# throwaway container per session, which is slower but needs no setup.
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: proxploy
      POSTGRES_PASSWORD: proxploy
      POSTGRES_DB: proxploy_api
    ports: ["127.0.0.1:5432:5432"]
```

- [ ] **Step 5: CI**

In `.github/workflows/ci.yml`'s `test` job, add a Postgres service and the DSN, copying `proxploy-app`'s working `backend-postgres` job:

```yaml
    services:
      postgres:
        image: postgres:16
        env: {POSTGRES_USER: proxploy, POSTGRES_PASSWORD: proxploy, POSTGRES_DB: proxploy_api}
        ports: ["5432:5432"]
        options: >-
          --health-cmd pg_isready --health-interval 5s
          --health-timeout 5s --health-retries 10
    env:
      PROXPLOY_API_TEST_DSN: postgresql+psycopg://proxploy:proxploy@localhost:5432/proxploy_api
```

With `PROXPLOY_API_TEST_DSN` set, the fixture never invokes Docker; which matters because Docker-in-Docker on a runner is not something to rely on.

- [ ] **Step 6: Run**

```bash
cd /home/aasim/workspace/aspyrelabs/proxploy/proxploy-api
pip install -e '.[dev]'
python -m pytest tests/ -q
```
Expected: **4 passed**. The first run pulls `postgres:16`, so allow time.

Also confirm the migration actually applies on Postgres; it was only ever run against SQLite. If `sa.BigInteger().with_variant(sa.Integer(), 'sqlite')` or anything else errors, fix the migration and say so.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml proxploy_api/config.py proxploy_api/db.py tests/conftest.py \
        docker-compose.test.yml .github/workflows/ci.yml
git commit -m "feat(db): Postgres replaces SQLite, and the suite runs against a real one"
```

---

## Task 2: The license-key format

**Files:**
- Create: `proxploy_api/licensekey.py`, `tests/test_licensekey.py`
- Modify: `scripts/create_license.py`, `proxploy_api/api/licenses.py`, `tests/test_licensing.py`

**Interfaces:**
- Produces, for Task 3: `generate() -> str`, `canonical(raw: str) -> str`, `LicenseKeyError`. `canonical` normalises and validates, raising `LicenseKeyError` on anything malformed; its return value is what gets stored and looked up.

Current keys are `"PPL-" + "-".join(secrets.token_hex(2).upper() for _ in range(4))`, 16 hex chars, **64 bits**. New format: `PPL-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX`, Crockford Base32, **24 payload characters = 120 bits**, plus a mod-37 check symbol.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_licensekey.py`:

```python
import pytest

from proxploy_api.licensekey import LicenseKeyError, canonical, generate


def test_generated_keys_are_the_documented_shape():
    k = generate()
    assert k.startswith("PPL-")
    groups = k[4:].split("-")
    assert len(groups) == 5 and all(len(g) == 5 for g in groups)


def test_generated_keys_round_trip_through_canonical():
    k = generate()
    assert canonical(k) == k


def test_keys_are_distinct():
    assert len({generate() for _ in range(200)}) == 200


def test_lowercase_and_missing_dashes_are_accepted():
    k = generate()
    assert canonical(k.lower()) == k
    assert canonical(k.replace("-", "", 4)) == k


def test_crockford_confusables_are_normalised():
    """O/o -> 0 and I/i/L/l -> 1. This is the property that lets a key
    survive being read aloud or copied off a screen."""
    k = generate()
    body = k[4:].replace("-", "")
    if "0" not in body and "1" not in body:
        pytest.skip("this key has no 0 or 1 to confuse")
    typo = "PPL-" + body.replace("0", "O").replace("1", "I")
    assert canonical(typo) == k


def test_a_single_character_error_is_rejected():
    """The check symbol's entire job. Mutate one payload char and it must
    fail before anything touches a database."""
    k = generate()
    body = list(k[4:].replace("-", ""))
    body[0] = "Z" if body[0] != "Z" else "Y"
    with pytest.raises(LicenseKeyError):
        canonical("PPL-" + "".join(body))


def test_an_adjacent_transposition_is_rejected():
    k = generate()
    body = list(k[4:].replace("-", ""))
    for i in range(len(body) - 1):
        if body[i] != body[i + 1]:
            body[i], body[i + 1] = body[i + 1], body[i]
            break
    else:
        pytest.skip("all characters identical")
    with pytest.raises(LicenseKeyError):
        canonical("PPL-" + "".join(body))


@pytest.mark.parametrize("bad", [
    "", "PPL-", "nope", "XXX-ABCDE-ABCDE-ABCDE-ABCDE-ABCDE",
    "PPL-ABCDE-ABCDE-ABCDE-ABCDE",           # too short
    "PPL-ABCDE-ABCDE-ABCDE-ABCDE-ABCDE-ABCDE",  # too long
])
def test_malformed_keys_raise(bad):
    with pytest.raises(LicenseKeyError):
        canonical(bad)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_licensekey.py -q`
Expected: FAIL, the module does not exist.

- [ ] **Step 3: Implement**

Create `proxploy_api/licensekey.py`:

```python
"""License-key format: PPL-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX.

Crockford Base32, 24 payload characters (120 bits) plus a mod-37 check
symbol. Crockford because it drops I, L, O and U and normalises the
confusable pairs on decode, so a key survives being read down a phone or
retyped out of a support ticket.

The check symbol is a TYPO detector, not a security control; an attacker
computes valid checksums trivially. Its value is that a mistyped key fails
here, locally, instead of consuming a database lookup and a slice of the
rate-limit budget that exists to catch real guessing.
"""
import secrets

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"      # Crockford Base32
CHECK_ALPHABET = ALPHABET + "*~$=U"                # 37 symbols, mod-37 check
PREFIX = "PPL-"
PAYLOAD_LEN = 24                                   # 24 * 5 = 120 bits
BODY_LEN = PAYLOAD_LEN + 1                         # + check symbol
_CONFUSABLE = str.maketrans({"I": "1", "L": "1", "O": "0"})


class LicenseKeyError(ValueError):
    """A key that is malformed, mistyped, or not ours. Never raised for a
    well-formed key that simply is not in the database; that is a lookup
    miss, and the caller distinguishes them."""


def _decode(payload: str) -> int:
    n = 0
    for ch in payload:
        n = n * 32 + ALPHABET.index(ch)
    return n


def _encode(n: int) -> str:
    out = []
    for _ in range(PAYLOAD_LEN):
        out.append(ALPHABET[n % 32])
        n //= 32
    return "".join(reversed(out))


def _grouped(body: str) -> str:
    return PREFIX + "-".join(body[i:i + 5] for i in range(0, BODY_LEN, 5))


def generate() -> str:
    n = secrets.randbits(PAYLOAD_LEN * 5)
    payload = _encode(n)
    return _grouped(payload + CHECK_ALPHABET[_decode(payload) % 37])


def canonical(raw: str) -> str:
    """Normalise and validate, returning the canonical grouped form.

    This is what gets stored and what gets looked up, so a key typed in
    lowercase, without dashes, or with O-for-0 resolves to the same row.
    """
    if not isinstance(raw, str):
        raise LicenseKeyError("license key must be a string")
    s = raw.strip().upper()
    if not s.startswith(PREFIX):
        raise LicenseKeyError("license key does not start with PPL-")
    # Normalise ONLY the body. The prefix contains an L, which the
    # confusable table would rewrite to "PP1-": a trap worth naming.
    body = s[len(PREFIX):].replace("-", "").translate(_CONFUSABLE)
    if len(body) != BODY_LEN:
        raise LicenseKeyError(f"license key body must be {BODY_LEN} characters")
    payload, check = body[:PAYLOAD_LEN], body[PAYLOAD_LEN]
    if any(c not in ALPHABET for c in payload):
        raise LicenseKeyError("license key contains characters outside the alphabet")
    if check not in CHECK_ALPHABET:
        raise LicenseKeyError("license key check symbol is not valid")
    if CHECK_ALPHABET[_decode(payload) % 37] != check:
        raise LicenseKeyError("license key failed its checksum, likely a typo")
    return _grouped(payload + check)
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_licensekey.py -q`
Expected: all pass.

- [ ] **Step 5: Use it in the generator and the route**

`scripts/create_license.py`: replace the key line:

```python
from proxploy_api.licensekey import generate
...
key = generate()
```
Delete the now-unused `import secrets`.

`proxploy_api/api/licenses.py`: validate **before** the query in `activate`:

```python
from proxploy_api.licensekey import LicenseKeyError, canonical
...
@router.post("/activate")
def activate(request: Request, body: ActivateIn, db=Depends(get_db)):
    try:
        key = canonical(body.license_key)
    except LicenseKeyError as e:
        # 422, not 404: this is a malformed request, not a missing resource,
        # and it never reaches the database: which is what keeps the rate
        # limit meaningful for real guessing.
        raise HTTPException(422, str(e))
    lic = db.query(License).filter_by(license_key=key, status="active").one_or_none()
    if not lic:
        raise HTTPException(404, "unknown or revoked license key")
```

- [ ] **Step 6: Fix the two tests this invalidates**

In `tests/test_licensing.py`, `test_unknown_license_404` currently posts `"PPL-NOPE"`. That is now **malformed**, so it gets 422 and no longer exercises the 404 path. Split it:

```python
def test_unknown_license_404(client):
    """A well-formed key that simply is not ours."""
    from proxploy_api.licensekey import generate
    assert client.post("/v1/licenses/activate", json={
        "license_key": generate(), "install_id": "i"}).status_code == 404


def test_malformed_license_422(client):
    """Rejected on format before any lookup, see licensekey.canonical."""
    assert client.post("/v1/licenses/activate", json={
        "license_key": "PPL-NOPE", "install_id": "i"}).status_code == 422
```

**No dual-accept path.** The old 64-bit format is not recognised anywhere. Any other fixture or test hardcoding a `PPL-XXXX-XXXX-XXXX-XXXX` string is rewritten to call `generate()`.

- [ ] **Step 7: Run the full suite and commit**

Run: `python -m pytest tests/ -q`

```bash
git add proxploy_api/licensekey.py tests/test_licensekey.py scripts/create_license.py \
        proxploy_api/api/licenses.py tests/test_licensing.py
git commit -m "feat(licensing): 120-bit Crockford license keys, validated before any lookup"
```

---

## Task 3: `install_id` binding, and the rebind path

**Files:**
- Modify: `proxploy_api/api/licenses.py`, `proxploy_api/api/entitlements.py`, `tests/test_licensing.py`
- Test: `tests/test_install_binding.py` (new)

**Interfaces:**
- Consumes: `canonical`, `generate` from Task 2.
- Produces: `CredentialIn` gains a required `install_id: str`. `refresh` and `revoke` return **403** on mismatch. `activate` with a known key and a new `install_id` returns **200** and a fresh `refresh_credential`.

Two changes, and the second is the one that stops this becoming a support queue.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_install_binding.py`:

```python
"""refresh/revoke bind to the install that owns the credential, and a
reinstall rebinds cleanly instead of being refused."""


def _activate(client, key, install):
    return client.post("/v1/licenses/activate",
                       json={"license_key": key, "install_id": install})


def test_refresh_from_the_bound_install_works(client, license_key):
    cred = _activate(client, license_key, "inst-1").json()["refresh_credential"]
    r = client.post("/v1/entitlements/refresh",
                    json={"refresh_credential": cred, "install_id": "inst-1"})
    assert r.status_code == 200 and "token" in r.json()


def test_refresh_from_another_install_is_rejected(client, license_key):
    cred = _activate(client, license_key, "inst-1").json()["refresh_credential"]
    r = client.post("/v1/entitlements/refresh",
                    json={"refresh_credential": cred, "install_id": "inst-2"})
    assert r.status_code == 403


def test_a_mismatch_does_not_mutate_the_binding(client, license_key):
    """The important one. If a mismatch revoked or rebound the license, a
    stolen credential would become a denial-of-service against the owner."""
    cred = _activate(client, license_key, "inst-1").json()["refresh_credential"]
    client.post("/v1/entitlements/refresh",
                json={"refresh_credential": cred, "install_id": "attacker"})
    r = client.post("/v1/entitlements/refresh",
                    json={"refresh_credential": cred, "install_id": "inst-1"})
    assert r.status_code == 200, "the legitimate install must still work"


def test_revoke_from_another_install_is_rejected(client, license_key):
    cred = _activate(client, license_key, "inst-1").json()["refresh_credential"]
    assert client.post("/v1/licenses/revoke", json={
        "refresh_credential": cred, "install_id": "inst-2"}).status_code == 403
    # and the license is still usable from its real install
    assert client.post("/v1/entitlements/refresh", json={
        "refresh_credential": cred, "install_id": "inst-1"}).status_code == 200


def test_reinstall_rebinds_and_issues_a_fresh_credential(client, license_key):
    """A user who rebuilds their CT gets a new install_id. Re-activating
    must work, this returned 409 before 9d and generated a support ticket
    for every reinstall."""
    first = _activate(client, license_key, "inst-1").json()["refresh_credential"]
    r = _activate(client, license_key, "inst-2")
    assert r.status_code == 200
    second = r.json()["refresh_credential"]
    assert second and second != first

    assert client.post("/v1/entitlements/refresh", json={
        "refresh_credential": second, "install_id": "inst-2"}).status_code == 200


def test_the_old_credential_stops_working_after_a_rebind(client, license_key):
    """It ages out through the app's grace window rather than dying, the
    app honours its cached token to grace_until on a 403. See doc 07 §8."""
    first = _activate(client, license_key, "inst-1").json()["refresh_credential"]
    _activate(client, license_key, "inst-2")
    assert client.post("/v1/entitlements/refresh", json={
        "refresh_credential": first, "install_id": "inst-1"}).status_code == 403


def test_reactivating_the_same_install_is_still_idempotent(client, license_key):
    """Unchanged contract: null credential means 'keep the one you have'."""
    _activate(client, license_key, "inst-1")
    r = _activate(client, license_key, "inst-1")
    assert r.status_code == 200 and r.json()["refresh_credential"] is None
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_install_binding.py -q`
Expected: FAIL, `install_id` is not a field on `CredentialIn`, and the rebind returns 409.

- [ ] **Step 3: Implement**

`proxploy_api/api/licenses.py`:

```python
class CredentialIn(BaseModel):
    refresh_credential: str
    install_id: str


def bound_license(db, body: CredentialIn, *, active_only: bool) -> License:
    """Resolve a credential to its license, enforcing the install binding.

    A mismatch is reported exactly as an unknown credential, same 403,
    same shape, so proxploy-app's existing failure path takes over: it
    honours its cached token to `exp`, then through `grace_until`, then
    falls back to the built-in map (doc 07 §8). The install ages down to
    the floor instead of being cut off.

    This function NEVER mutates the binding. Rejecting is the whole action.
    Revoking or rebinding on mismatch would let anyone holding a stolen
    credential lock the real owner out by deliberately triggering one.
    """
    q = db.query(License).filter_by(refresh_credential_hash=_h(body.refresh_credential))
    if active_only:
        q = q.filter_by(status="active")
    lic = q.one_or_none()
    if not lic or lic.install_id != body.install_id:
        raise HTTPException(403, "unknown or revoked refresh credential")
    return lic
```

`activate`: replace the 409 branch with a rebind:

```python
    rebound_from = None
    if lic.install_id and lic.install_id != body.install_id:
        # A reinstall, a rebuilt CT, or a restore. The license key IS the
        # owner's credential, so anyone presenting it already owns this
        # license: refusing bought nothing and cost a support ticket per
        # reinstall. Rebind, and invalidate the old credential.
        rebound_from = lic.install_id
        lic.refresh_credential_hash = None

    cred = None
    if lic.refresh_credential_hash is None:
        cred = secrets.token_urlsafe(32)
        lic.refresh_credential_hash = _h(cred)
    lic.install_id = body.install_id
    lic.issued_at = lic.issued_at or utcnow()
    db.commit()
```

Keep `rebound_from`, Task 5 logs it. Until then, leave it assigned with a comment saying Task 5 consumes it, rather than deleting and re-adding.

`revoke`: use the helper. Note it previously had **no** status filter, so a revoked license could be revoked again; `active_only=True` fixes that inconsistency with `refresh`:

```python
@router.post("/revoke")
def revoke(body: CredentialIn, db=Depends(get_db)):
    lic = bound_license(db, body, active_only=True)
    lic.status = "revoked"
    lic.revoked_at = utcnow()
    db.commit()
    return {"revoked": True}
```

`proxploy_api/api/entitlements.py`:

```python
from proxploy_api.api.licenses import CredentialIn, bound_license, get_db, mint


@router.post("/refresh")
def refresh(request: Request, body: CredentialIn, db=Depends(get_db)):
    lic = bound_license(db, body, active_only=True)
    return {"token": mint(request, db, lic)}
```

`_h` is no longer imported there, drop it from the import line.

- [ ] **Step 4: Fix the existing cycle test**

`tests/test_licensing.py::test_activate_refresh_revoke_cycle` asserts `409` for `inst-2` and calls refresh/revoke without an `install_id`. Update it: the 409 assertion becomes a rebind, and both credential calls pass `install_id`. Do not delete the test; it is the end-to-end happy path.

- [ ] **Step 5: Run everything and commit**

Run: `python -m pytest tests/ -q`

```bash
git add proxploy_api/api/licenses.py proxploy_api/api/entitlements.py \
        tests/test_install_binding.py tests/test_licensing.py
git commit -m "feat(licensing): bind credentials to their install, and let a reinstall rebind"
```

---

## Task 4: Rate limiting

**Files:**
- Modify: `pyproject.toml`, `proxploy_api/api/licenses.py`, `proxploy_api/api/entitlements.py`, `proxploy_api/main.py`
- Test: `tests/test_rate_limit.py` (new)

Copy `proxploy-app`'s idiom exactly, module-level `Limiter(key_func=get_remote_address)`, `@limiter.limit(...)` decorators, `app.state.limiter` set once. Do not invent a second pattern.

- [ ] **Step 1: Write the failing test**

```python
"""activate is the brute-force surface: a license key is a bearer secret,
and without a limit an attacker gets unlimited guesses."""


def test_activate_is_rate_limited(client):
    from proxploy_api.licensekey import generate

    codes = [client.post("/v1/licenses/activate",
                         json={"license_key": generate(), "install_id": "i"}).status_code
             for _ in range(40)]
    assert 429 in codes, "activate accepted 40 unknown keys without throttling"


def test_health_is_not_rate_limited(client):
    """Throttling health breaks the thing that watches the service."""
    assert all(client.get("/v1/health").status_code == 200 for _ in range(40))
```

- [ ] **Step 2: Run to verify failure**

Expected: FAIL, no 429 appears.

- [ ] **Step 3: Implement**

Add `"slowapi>=0.1.9"` to `pyproject.toml` dependencies (the same floor `proxploy-app` uses).

In `proxploy_api/api/licenses.py`:

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
```

Decorate. `slowapi` requires the route to take `request: Request`, `activate` already does; `revoke` does **not** and must gain one:

```python
@router.post("/activate")
@limiter.limit("10/minute")
def activate(request: Request, body: ActivateIn, db=Depends(get_db)):

@router.post("/revoke")
@limiter.limit("20/minute")
def revoke(request: Request, body: CredentialIn, db=Depends(get_db)):
```

`entitlements.py` imports the same limiter, one limiter for the app, not one per module:

```python
from proxploy_api.api.licenses import CredentialIn, bound_license, get_db, limiter, mint

@router.post("/refresh")
@limiter.limit("20/minute")
def refresh(request: Request, body: CredentialIn, db=Depends(get_db)):
```

`activate` gets the tighter limit because it is the only endpoint where guessing is viable; a 256-bit credential is not brute-forceable, so `refresh`/`revoke` are throttled against hammering rather than guessing. `/v1/health` is deliberately unlimited.

In `main.py`, after creating the app:

```python
    from proxploy_api.api.licenses import limiter
    app.state.limiter = limiter
```

**Check whether a 429 handler is needed here.** `proxploy-app` relies on its own RFC 9457 problem handler and needs none. This service has no such handler, so `RateLimitExceeded` may propagate as a 500 instead of a 429; if the test shows that, add `app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)` from `slowapi`. Report which you found.

- [ ] **Step 4: Run and commit**

Run: `python -m pytest tests/ -q`

```bash
git add pyproject.toml proxploy_api/api/licenses.py proxploy_api/api/entitlements.py \
        proxploy_api/main.py tests/test_rate_limit.py
git commit -m "feat(api): rate-limit the credential endpoints"
```

---

## Task 5: Structured logging

**Files:**
- Create: `proxploy_api/logging.py`, `tests/test_logging.py`
- Modify: `proxploy_api/main.py`, `proxploy_api/api/licenses.py`

The service currently emits **nothing**, no `logging.basicConfig`, no logger anywhere.

- [ ] **Step 1: Write the failing test**

```python
"""Whatever we log, we must never log the secrets themselves."""
import json
import logging


def test_activation_is_logged_without_the_key(client, license_key, caplog):
    with caplog.at_level(logging.INFO):
        client.post("/v1/licenses/activate",
                    json={"license_key": license_key, "install_id": "inst-1"})
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "activate" in text
    assert license_key not in text, "the license key leaked into the logs"


def test_a_rebind_is_logged(client, license_key, caplog):
    client.post("/v1/licenses/activate",
                json={"license_key": license_key, "install_id": "inst-1"})
    with caplog.at_level(logging.INFO):
        client.post("/v1/licenses/activate",
                    json={"license_key": license_key, "install_id": "inst-2"})
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "rebind" in text.lower()


def test_the_refresh_credential_never_appears(client, license_key, caplog):
    cred = client.post("/v1/licenses/activate", json={
        "license_key": license_key, "install_id": "inst-1"}).json()["refresh_credential"]
    with caplog.at_level(logging.DEBUG):
        client.post("/v1/entitlements/refresh",
                    json={"refresh_credential": cred, "install_id": "inst-1"})
    assert cred not in "\n".join(r.getMessage() for r in caplog.records)
```

- [ ] **Step 2: Run to verify failure**

Expected: FAIL, nothing is logged, so `"activate" in text` is false.

- [ ] **Step 3: Implement**

`proxploy_api/logging.py`:

```python
"""Structured logging.

The rule this module exists to enforce: license keys, refresh credentials
and signing-key material NEVER reach a log, in full or in part. Where a
correlation handle is genuinely needed, use `handle()`; a short SHA-256
prefix, which is enough to correlate two events without being enough to
replay anything.
"""
import hashlib
import json
import logging
import sys


def handle(secret: str) -> str:
    """A non-reversible correlation handle for a secret. Not a credential."""
    return hashlib.sha256(secret.encode()).hexdigest()[:12]


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"level": record.levelname, "logger": record.name,
                   "msg": record.getMessage()}
        extra = getattr(record, "fields", None)
        if extra:
            payload |= extra
        return json.dumps(payload, default=str)


def configure() -> None:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(logging.INFO)


def log(logger: logging.Logger, level: int, msg: str, **fields) -> None:
    logger.log(level, msg, extra={"fields": fields})
```

Call `configure()` in `create_app()` before the routers are included.

In `licenses.py`, log the outcomes; never the inputs:

```python
import logging
from proxploy_api.logging import handle, log

_log = logging.getLogger("proxploy_api.licenses")
...
    if rebound_from:
        log(_log, logging.INFO, "license rebind",
            license_id=lic.id, from_install=rebound_from, to_install=body.install_id)
    log(_log, logging.INFO, "activate", license_id=lic.id,
        install_id=body.install_id, key=handle(key), rebound=bool(rebound_from))
```

`license_id` and `install_id` are safe; they are identifiers, not secrets. `key=handle(key)` gives correlation without the key.

- [ ] **Step 4: Run and commit**

Run: `python -m pytest tests/ -q`

```bash
git add proxploy_api/logging.py proxploy_api/main.py proxploy_api/api/licenses.py \
        tests/test_logging.py
git commit -m "feat(obs): structured logging that never logs a credential"
```

---

## Task 6: A health check that checks something

**Files:**
- Modify: `proxploy_api/main.py`
- Test: `tests/test_health.py` (new)

`/v1/health` currently returns `{"status": "ok"}` whenever the process is up, so it can only ever detect "the process died", never "the process is up and cannot do its job".

- [ ] **Step 1: Write the failing test**

```python
def test_health_reports_the_things_it_depends_on(client):
    body = client.get("/v1/health").json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["signing_key"] == "ok"
    assert body["kid"] == "test-kid"
    assert body["version"]


def test_health_reports_unhealthy_when_the_database_is_gone(client):
    """A dropped connection must show up here, not as a 500 on activate."""
    client.app.state.engine.dispose()
    client.app.state.engine.url = client.app.state.engine.url.set(
        database="definitely-not-a-database")
    r = client.get("/v1/health")
    assert r.status_code == 503
    assert r.json()["database"] != "ok"
```

If mutating the engine URL proves awkward against SQLAlchemy 2.0's immutable `URL`, substitute `monkeypatch`ing `app.state.sessionmaker` with one whose connection raises. **The assertion that matters is that an unreachable database yields 503 and a non-`ok` `database` field**, not the mechanism used to break it; adapt and say so.

- [ ] **Step 2: Run to verify failure**

Expected: FAIL, the response has only `status`.

- [ ] **Step 3: Implement**

```python
    @app.get("/v1/health")
    def health(response: Response):
        from sqlalchemy import text
        checks = {"database": "ok", "signing_key": "ok"}
        try:
            with app.state.engine.connect() as c:
                c.execute(text("SELECT 1"))
        except Exception as e:
            checks["database"] = f"error: {type(e).__name__}"
        if not getattr(app.state, "private_pem", None):
            checks["signing_key"] = "error: not loaded"
        ok = all(v == "ok" for v in checks.values())
        if not ok:
            response.status_code = 503
        return {"status": "ok" if ok else "degraded",
                "kid": settings.kid, "version": version("proxploy-api"), **checks}
```

Import `Response` from `fastapi` and `version` from `importlib.metadata`.

**Also fix the startup crash.** `main.py`'s lifespan calls `settings.signing_key_file.read_text()`, which raises an uncaught `FileNotFoundError` and kills the process with a stack trace. Catch it, log a clear message via Task 5's logger, and leave `app.state.private_pem` unset so this health check reports it; a service that starts and reports "I cannot sign" is more debuggable than one that refuses to start with a traceback.

- [ ] **Step 4: Run and commit**

Run: `python -m pytest tests/ -q`

```bash
git add proxploy_api/main.py tests/test_health.py
git commit -m "feat(obs): a health check that checks the database and the signing key"
```

---

## Task 7: Key rotation, code and runbook

**Files:**
- Modify: `proxploy_api/config.py`, `scripts/gen_signing_key.py`
- Create: `docs/runbooks/rotating-the-signing-key.md` (in `proxploy-api`; create `docs/runbooks/`)
- Test: `tests/test_rotation.py` (new)

The API signs with one key; the app verifies against a **set** (`BUNDLED_PUBLIC_KEYS` plus an optional `ent_extra_keys_file` overlay) precisely so rotation is an overlap window. The asymmetry is the design.

- [ ] **Step 1: Write the failing test**

```python
"""Rotation is a config change with a known-good sequence, not a file swap."""


def test_tokens_carry_the_configured_kid(client):
    import jwt
    from proxploy_api.licensekey import generate
    # activate a license and read the header
    ...
    assert jwt.get_unverified_header(token)["kid"] == "test-kid"


def test_a_second_key_can_be_generated_without_disturbing_the_first(tmp_path):
    """gen_signing_key.py must refuse to clobber an existing key file, a
    silent overwrite destroys the only copy of a key that installs still
    trust."""
    import subprocess, sys
    from pathlib import Path
    out = tmp_path / "k.key"
    REPO = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, str(REPO / "scripts/gen_signing_key.py"),
                    "--kid", "k1", "--out", str(out)], check=True)
    first = out.read_bytes()
    r = subprocess.run([sys.executable, str(REPO / "scripts/gen_signing_key.py"),
                        "--kid", "k1", "--out", str(out)], capture_output=True)
    assert r.returncode != 0, "regenerating over an existing key must fail"
    assert out.read_bytes() == first
```

- [ ] **Step 2: Run to verify failure**

Expected: the overwrite test FAILs, the script currently clobbers (and `chmod(0o400)` then `write_bytes` on a second run may even raise a confusing `PermissionError` rather than a clear refusal).

- [ ] **Step 3: Implement**

`scripts/gen_signing_key.py`: refuse to overwrite an existing file with a clear message, unless `--force` is passed. Keep the 0400 mode and the public-PEM-to-stdout behaviour.

`proxploy_api/config.py`: no new fields are strictly required, rotation is `PROXPLOY_API_SIGNING_KEY_FILE` plus `PROXPLOY_API_KID`, but document that pair as the rotation interface in the runbook, and make sure both are read fresh (they are: `get_settings` is `lru_cache`d per process, so a restart picks them up).

- [ ] **Step 4: Write the runbook**

`docs/runbooks/rotating-the-signing-key.md`. It must lead with the bootstrap property, because getting it wrong breaks entitlement refresh for every install that has not updated:

> **The app's trusted key set ships inside the release artifact.** A newly generated signing key is not trusted by any install until an app release carrying its public half has propagated. Rotation is therefore always two-step and cannot be completed in one action.

Sequence:
1. Generate the new key (`gen_signing_key.py --kid <new>`), private key to the password manager, public PEM captured.
2. Add the public key to `proxploy-app`'s `BUNDLED_PUBLIC_KEYS` **alongside** the current one. Both are now trusted.
3. Publish a `proxploy-app` release carrying it, and wait for installs to update. **Do not proceed until they have**: installs still on the old release will reject tokens signed by the new key.
4. Switch the API: `PROXPLOY_API_SIGNING_KEY_FILE` and `PROXPLOY_API_KID` to the new key, restart. Tokens now carry the new `kid`.
5. After the old key's tokens have all expired (`token_ttl_hours`, default 72h) **and** their grace windows closed (`grace_days`, default 30d), remove the old public key from `BUNDLED_PUBLIC_KEYS` in a later release.

State the emergency case separately: if the private key is compromised, steps 3–4 invert; you must switch signing immediately and accept that installs which have not updated will fall back through grace to the built-in map, which is a degradation rather than an outage. Say that plainly so nobody discovers it mid-incident.

Note the runbook should read consistently with `proxploy-app`'s `docs/runbooks/publishing-a-release.md`, which records the identical bootstrap property for the *release-signing* key.

- [ ] **Step 5: Run and commit**

```bash
git add proxploy_api/config.py scripts/gen_signing_key.py \
        docs/runbooks/rotating-the-signing-key.md tests/test_rotation.py
git commit -m "feat(signing): refuse to clobber a live key, and document the two-step rotation"
```

---

## Task 8: Two gaps in proxploy-app

**Repo:** `proxploy-app` (different repo from Tasks 1–7)

**Files:**
- Modify: `backend/proxploy/services/license_client.py`, `proxploy_api/signing.py` (in `proxploy-api`)
- Test: `backend/tests/`, find the existing licence-client test and extend it

- [ ] **Step 1: Add `LicenseClient.revoke()`**

The API exposes `POST /v1/licenses/revoke` and the client cannot call it. Add the method, matching the existing `activate`/`refresh` shape and **including the `install_id`** Task 3 made required:

```python
    def revoke(self, refresh_credential: str, install_id: str) -> dict:
        return self._post("/v1/licenses/revoke",
                          {"refresh_credential": refresh_credential,
                           "install_id": install_id})
```

Task 3 also made `install_id` required on `refresh`, **update `LicenseClient.refresh()` to send it too**, or the app's refresh breaks against the hardened API. Find where the app knows its own install id (grep for `install_id` in `backend/proxploy/`) and thread it through; if the app has no install id concept yet, report that rather than inventing one, because it changes the size of this task considerably.

- [ ] **Step 2: Delete the dead loader**

`proxploy_api/signing.py::load_private_pem` is never imported, `main.py` inlines the same `read_text()`. Two ways to load a signing key is one too many. Either route `main.py` through the helper or delete it; pick one and say which.

- [ ] **Step 3: Run and commit**

Run the backend suite: `cd backend && .venv/bin/python -m pytest tests/ -q -m "not pve_integration and not e2e"`, floor **830 passed, 2 skipped**.

Commit in each repo separately, staging explicit paths.

---

## Task 9: DoD verification, notes, buildlog

**Repo:** `proxploy-app` for the notes and buildlog; the DoD script lives in `proxploy-api`.

**Files:**
- Create: `proxploy-api/dod_verify_phase9d.py` (add `dod_verify_*` to `proxploy-api/.gitignore`), `proxploy-app/docs/notes/phase-9d-api-hardening.md`
- Modify: `proxploy-app/buildlog.md`

- [ ] **Step 1: The DoD script**, four checks, each printing OK/FAIL, exit non-zero on failure, run twice with identical output:
  1. **Key format**: generate 1000 keys, assert all validate, all distinct, and that a single-character mutation and an adjacent transposition are both rejected. Print the bit count.
  2. **Install binding**: drive activate → refresh → mismatch → rebind through the real app, asserting the mismatch does not mutate the binding and the rebind issues a fresh credential.
  3. **Rate limiting**: hammer `activate` and assert a 429 appears; assert `/v1/health` does not throttle.
  4. **Postgres**: assert the suite's database is genuinely Postgres (`SELECT version()`), not SQLite. This is the check that would have caught a silent fallback.

- [ ] **Step 2: Notes**, `docs/notes/phase-9d-api-hardening.md`, same skeleton as `phase-9c-web-and-docs.md`.

**Findings that must appear:** all four endpoints had zero authentication and still do by design (a shared secret would live in the public app); license keys were 64 bits with unlimited guesses; `refresh`/`revoke` had no install binding at all; `revoke` had no status filter so a revoked licence could be revoked again; there was no logging whatsoever; `/v1/health` could only detect a dead process; a missing signing key crashed startup with an uncaught `FileNotFoundError`; re-activating from a new install returned **409**, meaning every reinstall was a support ticket; and `test_unknown_license_404` was testing a malformed key rather than an unknown one, so the 404 path was never actually exercised.

**Residual limitations, at minimum:** the service has still never run outside tests; rotation is proven mechanically but has never been executed against real installs because there are none; everything here protects a system whose protections are moot while `all_entitled: true`; and no deployment, Dockerfile, monitoring backend or error reporting exists.

- [ ] **Step 3: Buildlog**, the phase entry in the established format, including "Known gaps, stated plainly".

- [ ] **Step 4: Real numbers**, the `proxploy-api` suite count, the `proxploy-app` backend count, both DoD runs. **Never write a projected number.**

- [ ] **Step 5: Commit** in both repos.

---

## Self-Review

1. **Spec coverage.** §1 Postgres → Task 1. §2 rate limiting → Task 4. §3.1 key format → Task 2. §3.2 no dual-accept → Task 2 Step 6. §3.3 install binding both directions → Task 3. §4 health → Task 6. §5 logging → Task 5. §6 rotation code and runbook → Task 7. §7 `revoke()` and dead code → Task 8. Verification → Task 9.

2. **Placeholder scan.** No "TBD" or "handle appropriately". Four places direct the implementer to check a fact and state both branches: whether `slowapi` needs an explicit 429 handler here (Task 4), how to break the database in a test if URL mutation is awkward (Task 6), whether to route through or delete the dead loader (Task 8), and whether the app has an install-id concept to thread into `refresh` (Task 8); that last one explicitly says to report rather than invent, because it changes the task's size.

3. **Type consistency.** `generate()`, `canonical()`, `LicenseKeyError` are defined in Task 2 and used by name in Tasks 3, 4 and 9. `bound_license(db, body, *, active_only)` is defined in Task 3 and used in both routers. `CredentialIn` gains `install_id` in Task 3 and Task 8 sends it. `handle()` and `log()` are defined in Task 5 and used in `licenses.py` in the same task. `pg_dsn`/`clean_db`/`client`/`license_key` fixtures are defined in Task 1 and used by every later test.

4. **Honesty.** The three things this phase cannot prove, a running service, rotation against real installs, and any of it mattering while `all_entitled`; are in the spec, in Task 9's residual limitations, and in the DoD script's own output.
