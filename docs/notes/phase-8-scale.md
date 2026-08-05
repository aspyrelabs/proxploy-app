# Phase 8 (Scale) — verification notes

> Amendments were recorded here as they were decided, not at the end of the
> phase, so a behavior change is documented rather than rediscovered.

## What shipped, per subsystem

**Authorization (Tasks 1–7).** `services/authz.py` holds a casbin
RBAC-with-domains model, a static `PERMISSIONS` matrix over
(resource, action) → minimum role, and `sync_user`, which rebuilds a user's
`g`-lines from `team_members`. `api/deps.py::authorize(resource, action,
scope_of=…)` is now the **single** authorization path in the product: every
router was converted to it and `require_role` was deleted (`grep -rn
require_role backend/proxploy/` returns nothing). Team scoping resolvers
(`scope_host`, `scope_app`, `scope_vm`, `scope_backup`) turn a path
parameter into the owning team, so a role is evaluated in a domain rather
than globally. Two invariant suites walk every registered route: one asserts
each carries an `authorize()` marker (or sits on a reasoned allowlist), the
other drives a viewer — once by cookie, once by bearer token — at every
mutating route and demands 403.

**Teams (Tasks 6, 20).** `api/teams.py` with teams/members CRUD, `GET
/users` for the member picker, and `hosts.team_id` assignment. Every
membership write calls `sync_user`, so an enforcement change is immediate
rather than pending a restart — pinned by a test that flips a viewer to
admin and PATCHes a host in the same request sequence. Frontend: `TeamsCard`
plus a per-host team select.

**OIDC (Tasks 10–11, 17).** `services/oidc.py` — discovery, S256 PKCE,
RS256 ID-token validation against the IdP's live JWKS, and just-in-time
provisioning under the A2 policy below. Routes in `api/auth.py`; the
frontend's entry point is a plain `<a href>` to the login route, not a fetch,
because the flow is a redirect chain. Proven end to end against a local mock
IdP fixture (`tests/fakes/oidc.py`) that serves a real discovery document
and real signed tokens.

**TOTP and sessions (Tasks 8–9, 18).** Enrollment issues a seed plus ten
one-time recovery codes (their own table — see A3). Login became two-step
for TOTP-enabled users: the password check alone never sets a cookie, it
returns a pending token that is single-use, TTL-bounded, capped at five
wrong codes, and usable at exactly one route. `GET/DELETE /auth/sessions`
give self-service session listing and revocation. Frontend: a TOTP step on
the login page, and a Security card with enrollment (secret + `otpauth://`
URI as selectable text, no QR dependency) and session management.

**API tokens (Tasks 12–13, 19).** `ppk_…` bearer keys, hashed at rest,
optionally scoped (`read`, `<resource>:write`) and optionally expiring;
`get_current_user` resolves them, and `authorize()` folds a key's scopes in
*ahead of* the role check, so a key can only ever narrow its owner's rights.
The whole product was driven once over REST with no cookies to prove the API
surface is complete.

**Cross-host migration (Tasks 14–16, 21).** `services/migrate.py` picks its
strategy from **live** Proxmox state: cluster-native when both hosts are in
one cluster, shared-storage when they share a datastore, otherwise vzdump +
SFTP transfer + restore. Preflight returns the strategy, transfer size, an
estimate, blockers, warnings and a verbatim downtime statement; the job
records the *measured* `downtime_s` so the estimate and the outcome sit side
by side in the UI.

## The browser gap is closed

Phases 5, 6 and 7 each recorded the same limitation: no browser on this box,
so every frontend claim rested on Vitest + jsdom. That is no longer true —
`frontend/e2e/smoke.spec.ts` drives real Chromium against the real backend
(throwaway SQLite DB, pollers off) and asserts all nine nav pages render with
a clean console. `npm run e2e`.

What is still true, and always will be: there is **no live Proxmox host
here**. The harness seeds its admin through the app's own REST endpoints and
skips the onboarding wizard's host step, because `POST /hosts` probes a real
PVE API.

### F1 — no route-level `errorComponent` anywhere in the frontend (deferred)

Found by the harness on its first real run, while a backend fault was making
`/auth/me` return 500: TanStack Router logged *"The following error wasn't
caught by any route! At the very least, consider setting an 'errorComponent'
in your RootRoute!"* and the page rendered nothing. `grep -rn errorComponent
frontend/src` returns no hits, and `routes/shell.tsx`'s `beforeLoad` calls the
API — so any 5xx or unreachable backend during route load white-screens the
app instead of showing an error state.

jsdom could never have surfaced this; it does not run the router's real error
path. Deferred rather than fixed here: doc 10 puts "empty states, error
states" in Phase 9, and this is that work, not Phase 8's. Recorded so it is
scheduled rather than rediscovered.

## Amendments

### A1 — Authorization is fail-closed; a membership-less user is denied everything

**What changed.** Before Phase 8, `api/deps.py::user_role()` computed a
user's role as `max(their memberships, default="viewer")`. The `default=`
meant a user belonging to **no** team was silently treated as a viewer and
could read every resource in the product.

Phase 8's authorizer (`services/authz.py::enforce`) derives every decision
from the g-lines built out of `team_members`. A user with no membership has
no g-line, matches no policy, and is denied — including reads.

**Why this is right.** "Belongs to nothing" is not a statement that someone
should see everything; it is the absence of a statement. Reading the absence
of an authorization record as a grant is precisely the accidental-access
failure mode this phase exists to close, and doc 10's Phase 8 Definition of
Done ("a viewer cannot mutate anything, verified by test-suite against every
route") only means something if the role a user holds is a real record rather
than a fallback constant.

**Why it does not lock a fresh install out of itself.** It never could:
`api/users` `POST` has always forced the **first** user on an empty
`users` table to `role="owner"` (`api/auth.py:70-72`, doc 08 §8) and has
always written that user a real `TeamMember` row in the "default" team
(`api/auth.py:95`). That path predates Phase 8 and is unchanged by it.

What Phase 8 changes is its status: the bootstrap owner's membership used to
be incidental — the fallback would have covered a mistake there — and is now
load-bearing. It is therefore pinned by test rather than left implicit. Two
guarantees, both asserted directly against `enforce`:

- an ordinary user in no team is denied, reads included;
- the first-run bootstrap owner is **not** denied, and holds real owner
  permissions on a fresh database.

**Consequence to watch.** Any code path that mints a `User` without also
minting a `TeamMember` now produces an account that can do nothing. Before
Phase 8 there was exactly one such path (`api/auth.py:95`, which does both).
Phase 8 adds a second — OIDC just-in-time provisioning — which is why A2
exists.

### A2 — OIDC just-in-time provisioning assigns membership at mint time

**The problem.** OIDC first-login creates a user by a different path than
`POST /users`. Under A1, provisioning that user without a membership yields a
silent lockout: authentication succeeds, every subsequent request 403s, and
nothing in the UI explains why.

**The policy.** Two settings, `PROXPLOY_OIDC_DEFAULT_ROLE` (unset by default)
and `PROXPLOY_OIDC_DEFAULT_TEAM_SLUG` (`"default"`):

- **Role configured** — the user row and a `TeamMember` row carrying that
  role are written in one transaction. An unknown role or a missing team slug
  is a loud configuration error, never a silent fallback to no membership.
- **Role not configured (the default)** — the user is provisioned
  `is_active=False`. Login fails with an explicit "awaiting administrator
  approval" error and writes an audit row, so an admin can see who is
  waiting and activate them through the existing users/teams API.

**Why deny-with-an-explanation is the default.** An identity provider's user
population is not automatically the application's authorized population —
pointing Proxploy at a company-wide Authelia should not hand every employee
in the directory a Proxmox console. Requiring the operator to opt in to
auto-provisioning makes the unconfigured case safe. The pending state is what
keeps "safe" from meaning "silent": the account exists, the operator is told,
and the user is told why they cannot get in.

**Why `is_active` rather than a new column.** It already exists on `users`,
is already honored by `services/authn.py:44` and by the password login path
at `api/auth.py:41`, and already means exactly this. No migration, no second
state machine to keep consistent with the first.

**What was explicitly rejected.** Provisioning OIDC users as admins (grants
the IdP the ability to mint privilege in Proxploy); and widening the viewer
default to cover them (re-opens A1 for every user, to paper over one path).

**Also settled while implementing this** — an OIDC identity is never linked to
an existing local account by matching email. If the email claim collides with
a password account, provisioning refuses. Silent linking would let anyone who
can get that email claim out of the IdP take over the local account it names.
Deliberate linking is an admin action, not a side effect of a first login.

**As built** — `services/oidc.py::_create_user`. The user row and its
`TeamMember` are written with one `flush()` and a single `commit()`, so the
crash-between-the-two case cannot produce a permissionless account. Both
misconfiguration paths (`oidc_default_role` not in `ROLE_ORDER`,
`oidc_default_team_slug` naming no existing team) raise before anything is
written — no fallback, no auto-created team.

### A3 — recovery codes got their own table, and with it the phase's one migration

**What changed.** The plan opened with "zero migrations this phase" and, to
hold that line, packed the ten one-time recovery codes as JSON inside the
existing `users.totp_secret_enc` Fernet blob. That was rejected while
implementing Task 8. Migration `6cf6a0722d23` adds `totp_recovery_codes`
(one row per code: `code_hash_enc`, `created_at`, `used_at`).

**Why.** Burning a recovery code in the blob design means
decrypt → mutate → re-encrypt → write, on a column a concurrent TOTP verify
is reading at the same time. Two logins racing to redeem the same code could
both read it unused, and the second write would silently clobber the first —
a one-time code redeemable twice, which is the entire property it exists to
have. With a row per code, burning is an ordinary
`UPDATE … WHERE used_at IS NULL`: exactly one statement matches, the database
arbitrates, and the pattern is already in the codebase
(`services/consoletickets.py`'s atomic redeem). The secondary reason is
plainer: a column named `totp_secret_enc` holding two different kinds of
secret is a name that lies.

**What this cost.** The phase's zero-migration property. Recorded rather
than defended — a constraint the plan set for itself is not worth a race in
a credential path, and the honest gate number below is
`alembic heads` = `6cf6a0722d23`, not the `2330a95b98d2` the plan
predicted.

## Findings that contradicted the docs

1. **`casbin_rules` + sqlalchemy-adapter (docs 04, 08) → in-memory enforcer.**
   Doc 04 describes `casbin_rules` as pycasbin's storage table and
   `team_members.role` as "mirrored into casbin_rules by the service layer" —
   two sources of truth by design. There is no `casbin-sqlalchemy-adapter` in
   the dependency tree, the policy matrix never changes at runtime (doc 05
   exposes no policy-editing endpoint), and the dynamic `g`-lines are a pure
   function of `team_members`. The enforcer is therefore built in memory from
   code + `team_members` at boot and re-synced through the `Authorizer` seam
   on membership writes. `casbin_rules` ships empty and retained. Doc 03's
   AuthZ row and doc 04's `casbin_rules` section are amended.
2. **`users.totp_secret_enc` "Fernet-encrypted TOTP seed" (doc 04) had
   nowhere to put recovery codes,** which doc 08 §5 requires. See A3: new
   table, doc 04 amended in both places.
3. **`hosts.cluster_name` was never populated before this phase.** The column
   existed from migration `0001` and nothing wrote it. Migration strategy
   selection cannot trust it, so `services/migrate.py` decides from a live
   `cluster_status()` call on both hosts and writes the observed name back as
   a side effect. Strategy is derived from what Proxmox says now, never from
   a cached column — stated in the module docstring so a future reader does
   not "optimise" the live call away.
4. **`authlib.jose` is deprecated in Authlib 1.7.x.** ID-token verification
   uses `joserfc` (Authlib's own dependency and its designated successor)
   instead. Doc 03 gains `joserfc` as a named transitive row, the way Phase 7
   added `tzlocal`.
5. **Doc 04's API-key scope example `"apps:write"` is plural; the grammar is
   singular.** Scopes are `read` or `<matrix-resource-name>:write`, and the
   matrix names resources `app`, `vm`, `backup`. `POST /api-keys` 422s
   anything outside the matrix, so the plural string was never accepted by
   the code. Doc 04's example is normalised.

## Residual limitations

- **No real IdP on this box.** Doc 10's DoD says OIDC "round-trips against a
  real Authelia". There is no Authelia and no browser-driven IdP here. The
  substitute is a local mock provider serving a real discovery document, a
  real S256 PKCE authorization-code exchange, and real RS256-signed ID tokens
  verified against a real JWKS endpoint — protocol-complete, but not a
  third-party implementation on the wire. The DoD script prints this
  substitution in its own output rather than burying it here.
- **No live Proxmox host.** Migration is proven against two `FakePVE`
  instances plus a fake SFTP layer driving the real preflight, real handler
  and real route. The measured `downtime_s` is a real measurement of fake
  work.
- **Token-authed audit rows still name the user, not the key.** 84
  `write_audit` call sites exist; exactly one
  (`api/deps.py:158`, the scope-denial path) writes
  `actor_type="api_key"`. Every other row written during a bearer-token
  request attributes the acting *user*, because those call sites predate API
  keys and take the user from the dependency. `request.state.api_key` is
  populated and available — the upgrade path is an `actor_of(request)` helper
  threaded through the call sites, which is a mechanical change across 83
  lines and was not worth bundling into this phase. Per-key forensic evidence
  today is the scope-denial rows plus `last_used_at`.
- **OIDC state and the 2FA pending store are in-memory, single-process.** By
  design — the job backend is in-process too. A restart mid-login costs one
  re-login. Both carry `ponytail:` comments naming the table-backed upgrade
  path if multi-worker ever lands.
- **Migration never deletes the source container.** After a successful
  vzdump/transfer/restore the source CT is left stopped, for the operator to
  remove once satisfied. Deliberate: the alternative is destroying the only
  copy of a workload on the strength of an automated check.
- **F1 (no route-level `errorComponent`) is still open** — see above; it is
  Phase 9 work.
- **The frontend suite is only reliable run sequentially on this box.** Under
  `npx vitest run`'s default file parallelism, unrelated suites
  (`settings`, `schedules`, `backups`, `vmcreate`, `storage`) fail
  intermittently and pass on re-run in isolation — CPU/timer contention in
  this sandbox, reproduced independently by three different agents on files
  none of them had touched. `--no-file-parallelism` passes every time. The
  gate number below is the sequential run; whether the flakiness is
  environmental or a latent fake-timer dependency in those suites is not
  settled here, and it is not claimed to be.

## Gate numbers (real, captured this run)

| Gate | Result |
|---|---|
| `dod_verify_phase8.py` | 4/4 clauses OK, exit 0, run twice — output identical except the measured `downtime_s` (0.043819 s vs 0.040807 s), which is a real wall-clock measurement and was deliberately not rounded into false identity |
| Backend | **784 passed, 2 skipped, 4 deselected** — `pytest tests/ -m "not pve_integration and not e2e"`, run twice, identical (baseline entering the phase: 663) |
| Frontend | **199 passed across 36 files** — `npx vitest run --no-file-parallelism` (Phase 7 closed at 154 across 30; the plan's stated floor was 157) |
| Frontend build | exit 0, clean — only the pre-existing >500 kB chunk-size advisory |
| Frontend lint (oxlint) | exit 0 — pre-existing warning classes only, no errors |
| Frontend e2e | **1 passed** — real Chromium, `login and every nav page renders with a clean console` (3.1 s) |
| Executor isolation (CI gate) | `executor isolation: OK` |
| License audit, backend + frontend (CI gates) | clean, exit 0, against the exact CI allow-list |
| Migrations | `alembic heads` = **`6cf6a0722d23`** — one migration this phase (A3). The plan predicted `2330a95b98d2` unchanged; that prediction did not survive contact with the recovery-code race |

One note on the license audit, because the first run of it was not clean: the
local `.venv` had `psycopg`/`psycopg-binary` (LGPL-3.0-only) left over from an
earlier session testing the Postgres CI leg. `pyproject.toml`'s `dev` extra
does not include them and CI's backend job does not install them, so this was
an artefact of this machine, not of the dependency tree — confirmed by
uninstalling, re-running clean, and reinstalling to leave the venv as found.

## Commit range

Phase 8 runs `5c4382a` ("docs(phase-8): implementation plan for Scale") through
`e76df83` ("feat(ui): security settings — TOTP enrollment with one-time
recovery codes, session management"), 26 commits, plus this documentation
commit. The preceding commit, `e8093d1`, is Phase 7's closing chore. All 22
planned tasks are committed directly to `main`, one commit per task, matching
the convention every prior phase used.
