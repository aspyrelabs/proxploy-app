# Phase 9d (proxploy-api production hardening) — verification notes

> **Goal**, verbatim from the plan: *"Make the licensing service ready to
> deploy — Postgres, rate limits, a real license-key format, install binding
> that survives a reinstall, a health check that checks something,
> structured logs, and a rotation runbook — without deploying it."* Nine
> tasks, eight in `proxploy-api`, one (Task 8) in `proxploy-app`. Plan:
> `docs/superpowers/plans/2026-08-06-phase-9d-api-hardening.md`. Spec:
> `docs/superpowers/specs/2026-08-06-phase-9d-api-hardening-design.md`.

This is also the close of **Phase 9 as a whole** — 9a (install/update),
9b (onboarding polish), 9c (docs + marketing sites), 9d (this). Phase 9's
own closing note is in `buildlog.md` below this phase's entry.

## What shipped, per subsystem

**Task 1 — Postgres replaces SQLite (`proxploy-api`).** `db_url` and
`make_engine` point at Postgres unconditionally; the SQLite branch is gone.
`tests/conftest.py` gained a session-scoped `pg_dsn` fixture that reuses
`PROXPLOY_API_TEST_DSN` when set (CI hands it a `services:` container) or
starts a throwaway `postgres:16` Docker container otherwise — this box has
no Postgres binaries at all, so a skip-when-absent fixture would have
proven nothing. A per-test `clean_db` fixture drops and recreates the
`public` schema rather than the whole database, which is faster and keeps
one server for the whole run.

**Task 2 — the license-key format.** `proxploy_api/licensekey.py`:
`PPL-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX`, Crockford Base32, 24 payload
characters (120 bits) plus a mod-37 check symbol. `canonical()` validates
and normalises (case, missing dashes, `O`/`I`/`L` confusables) before
anything touches the database; `generate()`/`canonical()`/`LicenseKeyError`
are the module's whole public surface. `scripts/create_license.py` and
`proxploy_api/api/licenses.py::activate` both moved onto it; the old
16-hex-char format has no dual-accept path anywhere.

**Task 3 — `install_id` binding, and the rebind path.** `CredentialIn`
gained a required `install_id`. `bound_license()` (in `licenses.py`, shared
by `revoke` and `entitlements.py::refresh`) resolves a credential to its
license and rejects — 403, never mutating anything — the moment the
presented `install_id` doesn't match the bound one. `activate` from a
license's current `install_id` reactivates idempotently (`refresh_credential:
null`, unchanged from before); from a *different* `install_id` it now
**rebinds**: the old credential hash is cleared, a fresh one is minted, and
the response is 200, not the old 409.

**Task 4 — rate limiting.** Copied `proxploy-app`'s `slowapi` idiom exactly
— module-level `Limiter(key_func=get_remote_address)` in `licenses.py`,
`@limiter.limit(...)` decorators, `app.state.limiter` set once in
`main.py`. `activate` is `10/minute` (the only endpoint where guessing is
viable — a 256-bit refresh credential isn't brute-forceable); `refresh`/
`revoke` are `20/minute` against hammering rather than guessing; `/v1/health`
is deliberately unlimited.

**Task 5 — structured logging.** `proxploy_api/logging.py`: a JSON
formatter on a root `StreamHandler`, wired up by `configure()` in
`create_app()`. `handle()` gives a 12-character SHA-256 correlation prefix
for anything that would otherwise be a raw secret in a log line.
`licenses.py` logs `activate` (with `key=handle(key)`, never the raw key)
and, when applicable, a separate `license rebind` line naming the old and
new `install_id`.

**Task 6 — a health check that checks something.** `/v1/health` now runs
`SELECT 1` against the real engine and checks whether `app.state.private_pem`
loaded; either failure flips `status` to `degraded`, sets HTTP 503, and
names which check failed. The lifespan's signing-key load, which previously
let an uncaught `FileNotFoundError` kill the process on startup, now catches
it, logs it, and leaves `private_pem` unset — the service starts and
*reports* "I cannot sign" instead of crashing before it can report anything.

**Task 7 — key rotation, code and runbook.** `scripts/gen_signing_key.py`
now refuses to overwrite an existing key file unless `--force` is passed
(previously it clobbered silently, and could `PermissionError` confusingly
on a 0400 file). `docs/runbooks/rotating-the-signing-key.md` (new, in
`proxploy-api`) documents the two-step rotation the asymmetric trust model
requires: the app's trusted key set ships inside the release artifact, so a
new signing key isn't trusted anywhere until an app release carrying its
public half has propagated. It also states the emergency (key-compromise)
case separately, where the steps invert and installs that haven't updated
degrade through grace rather than erroring outright.

**Task 8 — two gaps in `proxploy-app`.** `LicenseClient.revoke()` was
added, matching `activate`/`refresh`'s shape and sending `install_id`.
`LicenseClient.refresh()` was updated to send `install_id` too, or the
app's own refresh would break against the now-hardened API — this turned
out to be mechanical, not a design decision, because
`api/entitlements.py::set_license` (called from `activate`) already mints a
`uuid4()` and persists it as `AppSetting("license.install_id")`; there was
no missing install-identity concept to invent. `proxploy_api/signing.py`'s
never-imported `load_private_pem` helper was deleted (`main.py` already
inlines the identical `read_text()` — one loader, not two).

**Task 9 — this task.** `proxploy-api/dod_verify_phase9d.py` (gitignored,
`proxploy-api/.gitignore` gained a `dod_verify_*` line — it previously had
none), this notes file, and the `buildlog.md` entry below.

## Findings — the phase's real output

- **All four endpoints had zero authentication when the phase started, and
  still do — by design.** A shared secret would have to live in
  `proxploy-app`, which is the one repo that goes public, so it would be
  extractable with one `grep`. Doc 11 §6 already concedes this class of
  thing; rate limits, key entropy and install binding are the actual
  defence here, not caller authentication.
- **License keys were ~64 bits with unlimited guesses** — `"PPL-" +
  secrets.token_hex(2)` four times over, and no rate limiting anywhere.
  Now 120-bit Crockford Base32 with a mod-37 check symbol, validated in
  `canonical()` before any database lookup, so a typo never consumes
  rate-limit budget that exists to catch real guessing.
- **`refresh` and `revoke` had no install binding at all** — possession of
  a refresh credential was the entire check. Both now resolve through
  `bound_license()`, which 403s on a mismatched `install_id`.
- **`revoke` had no status filter**, so a revoked licence could be revoked
  again and still returned `{"revoked": true}` — inconsistent with
  `refresh`, which did filter on `status="active"`. `bound_license(...,
  active_only=True)` now applies to both.
- **There was no logging whatsoever** — zero hits for `logging` in the
  package before Task 5.
- **`/v1/health` could only ever detect a dead process**, never "up but
  cannot do its job." It now checks the database connection and the
  signing key independently.
- **A missing signing key crashed startup** with an uncaught
  `FileNotFoundError`. Now caught, logged, and surfaced through
  `/v1/health` instead.
- **Re-activating from a new `install_id` returned 409** — every reinstall,
  CT rebuild or restore was a support ticket. Now a clean rebind: 200, a
  fresh credential, the old one invalidated.
- **`test_unknown_license_404` was testing a malformed key** (`"PPL-NOPE"`),
  not an unknown one, so the 404 path was never actually exercised. Split
  into a 404 test using `generate()` and a separate 422 test for the
  malformed case.

**Found during execution, worth recording:**

- **The `slowapi` `Limiter` is a module-level singleton**, so its counters
  leaked across tests — a rate-limit test primed the counter and broke
  three unrelated tests with spurious 429s. Fixed with `limiter.reset()` in
  the `client` fixture, mirroring `proxploy-app`'s own `tests/conftest.py`.
- **`RateLimitExceeded` subclasses Starlette's `HTTPException`**, confirmed
  directly (`slowapi.errors.RateLimitExceeded.__mro__` includes
  `starlette.exceptions.HTTPException`), so FastAPI's default handler
  returns 429 with no custom wiring needed — `proxploy-api/proxploy_api/
  main.py` has no `add_exception_handler` call for it. The house pattern
  from `proxploy-app` transferred here for a simpler reason than it applies
  there.
- **`proxploy-app` already had a real persisted install identity** —
  `backend/proxploy/api/entitlements.py::set_license` mints a `uuid4()` and
  stores it as `AppSetting("license.install_id")`. Threading it through
  `refresh`/`revoke` (Task 8) was mechanical, not the design decision the
  plan flagged it as a risk of being.
- **Two bugs in the plan's own test text, both caught and fixed by
  implementers**: `k.replace("-", "", 4)` in one of the plan's example
  tests stripped the `PPL-` prefix's dash along with the body dashes and
  broke the `startswith` check it was meant to exercise; and the
  confusables test called `pytest.skip()` whenever a randomly generated key
  happened to contain no `0` or `1`, so — as originally drafted — it
  silently didn't run some fraction of the time while still showing green.
  Both were corrected in the committed test files.
- `pip` on this box is externally-managed (PEP 668); every command in this
  phase ran through the repo's `.venv`, never bare `pip`.

## Residual limitations, at minimum

- **The service has still never run outside tests.** No Dockerfile, no
  host, no deployment anywhere. Rate limits, health checks and structured
  logs are verified by tests and by this phase's DoD script driving a real
  in-process app against a real Postgres — not by observing a deployed
  instance under real traffic.
- **Rotation is proven mechanically, never operationally.** The runbook
  describes a two-step sequence — generate, distribute via an app release,
  wait for propagation, then switch signing — that nobody has executed
  against real installs, because there are no real installs yet.
- **Everything here protects a system whose protections are currently
  moot.** `tiers.yaml` still keeps `all_entitled: true`, so a stolen token
  grants exactly what `DEFAULT_FEATURES` already grants unconditionally.
  Every defence built this phase — key entropy, install binding, rate
  limits — becomes live the day tiers arm, not before.
- **No deployment, Dockerfile, monitoring backend, or error reporting** —
  all deliberately out of scope per the plan's global constraints. Docker
  is used only to run Postgres for tests.

## Real numbers — every one run directly in this session

| Gate | Result |
|---|---|
| `proxploy-api` suite | **35 passed, 0 skipped** — `.venv/bin/python -m pytest tests/ -q` (baseline entering the phase: 4) |
| `proxploy-app` backend suite | **831 passed, 2 skipped, 4 deselected**, 0 failed — `.venv/bin/python -m pytest tests/ -q -m "not pve_integration and not e2e"` (9c exited at 829 passed + 1 flake that re-passed in isolation; Task 8's new/extended license-client tests plus a clean run of that same flaky test account for the difference here) |
| `proxploy-api/dod_verify_phase9d.py`, run 1 | exit 0, all four checks OK (key format, install binding, rate limiting, Postgres-not-SQLite) |
| `proxploy-api/dod_verify_phase9d.py`, run 2 | exit 0, byte-identical to run 1 apart from the interpreter's own deprecation-warning line, which is itself identical text both times |

**Commit ranges:**

- `proxploy-api`: `5b933d9..b2253e1` — 8 commits (`f134e77` Task 1,
  `f6d49bb` Task 2, `2cd502a` Task 3, `0519d22` Task 4, `0660f6b` Task 5,
  `a4bd8ac` Task 8's dead-loader deletion, `12a8daf` Task 6, `b2253e1`
  Task 7), plus this task's own `.gitignore` commit following.
- `proxploy-app`: `e574b88..4374251` — 4 commits (`b64b22f` design spec,
  `bdc6ec1` key-format/binding spec addendum, `7d0a636` implementation
  plan, `4374251` Task 8's app-side change), plus this task's own
  notes/buildlog commit following.
