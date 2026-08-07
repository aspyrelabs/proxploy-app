# Phase 8 (Scale) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Multi-user Proxploy, OIDC and TOTP logins, pycasbin RBAC with teams as domains enforced on every route, scoped hashed API tokens driving the full REST surface, and cross-host app migration (cluster-native or backup/restore) with honest downtime numbers.

**Architecture:** Four subsystems land on the Phase 1 auth seams with **zero Alembic migrations** (`users` already carries `totp_secret_enc`/`totp_enabled`/`oidc_issuer`/`oidc_sub` + `ux_users_oidc`; `api_keys`, `teams`, `team_members`, `casbin_rules` and `hosts.team_id` have existed since migration 0001). (1) **AuthZ**: an in-memory pycasbin RBAC-with-domains enforcer built at boot from a static `(resource, action) → min_role` matrix plus `g`-lines derived from `team_members`; the `require_role` stub in `api/deps.py` (its own docstring: "the seam pycasbin replaces in Phase 8") is replaced route-by-route with `authorize(resource, action)`. (2) **AuthN**: pyotp TOTP with argon2-hashed recovery codes packed inside the existing Fernet blob, and an Authlib/joserfc OIDC authorization-code+PKCE flow with JIT provisioning onto `ux_users_oidc`. (3) **API tokens**: `Authorization: Bearer ppk_…` resolution inside `get_current_user` (SHA-256 at rest, scope checks folded into `authorize`), then a CI-runnable test drives the product end-to-end through token-authed REST only. (4) **Migration**: a preflight that picks cluster-native `migrate` / shared-storage backup-restore / vzdump+SFTP-transfer, and a `migrate.app` job handler that reuses the Phase 6 vzdump/restore machinery (`services/backupjobs.py` patterns) and reports **measured** downtime.

**Tech Stack:** Python 3.12+ / FastAPI / SQLAlchemy 2.x / SQLite (WAL) / **casbin 1.43** / **Authlib 1.7** (+ its own dependency **joserfc** for ID-token verification, `authlib.jose` is deprecated in 1.7) / **pyotp 2.10** / argon2-cffi / asyncssh (SFTP transfer, executor-only) / pytest; React 19 / Vite / TanStack Router + Query / Tailwind v4 / Vitest.

---

## Global Constraints

Every task's requirements implicitly include this section. Values are copied verbatim from the specs and from verification runs performed while writing this plan (2026-08-05, repo at `e8093d1`).

**Repository / process**

- All work lands on `main` directly. Never create a branch (standing project rule; every prior phase did the same).
- Working directory for backend commands is `backend/`; for frontend commands, `frontend/`.
- Backend tests: `./.venv/bin/python -m pytest tests/ -m "not pve_integration and not e2e"`. Frontend tests: `npm test`.
- **Phase 8 floor, measured 2026-08-05 at `e8093d1`:** backend **663 passed / 2 skipped / 4 deselected** (~5 min wall clock), frontend **157 passed across 30 files**. Any task that leaves either suite below its starting count has broken something.
- Commit after every task, message prefix `feat(...)` / `fix(...)` / `test(...)` / `docs(...)` matching the touched area.

**Schema**

- **Zero Alembic migrations this phase.** Alembic head stays at `2330a95b98d2` (verified: `alembic heads` → `2330a95b98d2 (head)`). Column-by-column check performed against `proxploy/models/__init__.py` and migration `9f3cd187d023`:
  - `users`: `totp_secret_enc` (LargeBinary), `totp_enabled`, `oidc_issuer`, `oidc_sub` + unique index `ux_users_oidc(oidc_issuer, oidc_sub)`; OIDC subject and TOTP secret both already have homes.
  - `api_keys`: `user_id`, `name`, `prefix`, `key_hash` (unique), `scopes` (JSON), `expires_at`, `last_used_at`, `revoked_at`; complete for scoped/revocable/hashed tokens.
  - `teams`, `team_members(team_id, user_id, role)` + `ux_team_members`, `hosts.team_id`; complete for team domains.
  - **Recovery codes have no column anywhere.** Rather than migrate, they are stored **inside the existing `users.totp_secret_enc` Fernet blob** as JSON `{"secret": "<base32>", "recovery": ["<argon2 hash>", …]}`; argon2-hashed first (doc 08 §5: "stored argon2-hashed, one-time use"), then encrypted with everything else. Burning a code rewrites the blob. Task 23 amends doc 04's `totp_secret_enc` cell ("Fernet-encrypted TOTP seed" → seed + hashed recovery codes) the same way Phase 7 amended the `schedules` section.
  - If any task appears to need a migration beyond this, stop and re-read the model; it does not.
- `utcnow()` returns a **naive** UTC datetime. Every `DateTime` column is naive UTC.
- **`casbin_rules` stays empty, deliberate amendment, Phase 7's APScheduler precedent.** Doc 04/08 say policies live in `casbin_rules` via "casbin's SQLAlchemy adapter", and doc 04 itself says `team_members.role` is "mirrored into casbin_rules by the service layer"; an explicit two-sources-of-truth design. There is no `casbin-sqlalchemy-adapter` dependency in the tree, the static policy matrix never changes at runtime (no policy-editing endpoint exists anywhere in doc 05), and the only dynamic rules (`g` user→role-in-team lines) are a pure function of `team_members`. So the enforcer is built **in memory** from code + `team_members` on boot and updated through the `Authorizer` seam on membership writes, one source of truth, no mirror to drift. Doc 03 marks AuthZ "Provisional (seam: `Authorizer`)", which is exactly the licence for this call; Task 23 records the amendment in docs 03/04.

**Dependencies, all three verified against PyPI in a clean venv, 2026-08-05**

- **casbin 1.43.0**: `pip show` license: `Apache 2.0`, pip-licenses classifier: `Apache Software License`. Pulls one transitive dependency: **simpleeval 1.0.7 (MIT License)**. Pin: `"casbin>=1.43,<2"`.
- **Authlib 1.7.2**: `pip show` license: `BSD-3-Clause`, pip-licenses classifier: `BSD License`. Requires `cryptography` (already present) plus one new transitive: **joserfc 1.7.4 (BSD License)**, same author, and the library Authlib itself now delegates JOSE to. Pin: `"Authlib>=1.7,<2"`.
- **pyotp 2.10.0**: MIT, zero dependencies. Pin: `"pyotp>=2.10,<3"`.
- All five names (casbin, simpleeval, Authlib, joserfc, pyotp) were run through the **exact** allow-only string from `.github/workflows/ci.yml:19` (`pip-licenses --partial-match --allow-only "MIT;MIT License;BSD;BSD License;Apache;Apache Software License;ISC;Python Software Foundation;PSF-2.0;PostgreSQL;Public Domain;Mozilla Public License 2.0;Eclipse Public License v2.0;EPL-2.0;The Unlicense;CMU License (MIT-CMU)"`); **exit 0, all pass**. No other new backend or frontend dependency this phase (deliberately: no QR-code library, TOTP enrollment shows the secret + otpauth URI for manual entry, see Task 19).

**Verified library behaviour** (all confirmed by running it, not assumed):

```
casbin 1.43:  Enforcer(model) with NO adapter is a pure in-memory enforcer.
  model.load_model_from_text(...) + e.add_policy(...) / e.add_grouping_policy(...)
  / e.remove_grouping_policy(...) all work; enforce() returns False for unknown
  subjects, unknown objects, wrong domains; fail-closed by construction.
pyotp 2.10:   pyotp.random_base32(); TOTP(s).provisioning_uri(name=email,
  issuer_name="Proxploy") -> otpauth://totp/Proxploy:...; TOTP(s).verify(code,
  valid_window=1) tolerates ±1 30s step.
Authlib 1.7:  OAuth2Client(cid, sec, redirect_uri=..., code_challenge_method="S256")
  .create_authorization_url(url, nonce=..., code_verifier=v)
  TRAP: code_challenge/code_challenge_method appear in the URL ONLY when
  code_verifier= is passed to create_authorization_url. Without it, PKCE is
  silently absent. AsyncOAuth2Client.fetch_token(url, code=..., code_verifier=...,
  state=...) does the exchange over httpx.
  `authlib.jose` imports but emits AuthlibDeprecationWarning ("use joserfc
  instead"), do NOT use it.
joserfc 1.7:  from joserfc import jwt; from joserfc.jwk import KeySet;
  from joserfc.jwt import JWTClaimsRegistry.
  jwt.decode(token, KeySet.import_key_set(jwks_dict)).claims verifies the
  signature against a real JWKS document; JWTClaimsRegistry(iss={"essential":
  True, "value": issuer}, aud={"essential": True, "value": client_id},
  exp={"essential": True}, sub={"essential": True}).validate(claims) raises
  InvalidClaimError on a wrong issuer. Both verified with a generated RSA key.
```

**Error shape / route ordering / auth invariants**

- `main.py::problem_handler` serialises a dict-bodied `HTTPException` **flat**, not nested under `detail`. Tests assert `r.json()["error"]`; frontend reads `e.body.error`.
- On every gated route the auth/role dependency must run **before** the entitlement dependency, or an anonymous caller gets a leaky 403 instead of 401. `tests/test_route_auth_invariant.py` walks every registered route and enforces this; every new Phase 8 router must keep it green. The new `authorize()` dependency resolves `get_current_user` as a sub-dependency, so `dependencies=[Depends(authorize(...)), Depends(require_entitlement(...))]` in that order is correct.
- Literal-segment paths register **before** `/{app_id}/{action}` wildcards. `api/apps.py:522` carries a WARNING comment naming `/apps/{id}/migrate` explicitly, both migrate routes go above that wildcard.
- CSRF: `proxploy/middleware.py` already exempts requests carrying an `Authorization` header (line 20), bearer-token auth needs **no** CSRF change. Cookie-authed tests keep using the `csrf_header` fixture.
- Fail-closed is non-negotiable this phase: an unregistered `(resource, action)` pair must crash at route-registration time (import), an unknown API-key scope string grants nothing, an unknown casbin subject/object/domain denies. No task may soften these.

**Secrets**

- A raw API key appears in exactly one place ever: the `POST /api-keys` response body. Only `prefix` + SHA-256 `key_hash` persist (doc 04). Same hashing pattern as `services/authn.py::_th`.
- Recovery codes appear in exactly one place ever: the `POST /auth/totp/enroll` response. Only argon2 hashes persist (inside the Fernet blob).
- The OIDC client secret is Fernet-encrypted under settings key `oidc.client_secret.enc`, `GET /settings` already excludes `.enc` keys and `PATCH /settings` already refuses them ("managed by their own flows"), so the dedicated `PUT /auth/oidc/config` route in Task 10 is that flow.
- `write_audit` redacts by key-name substring (`services/audit.py::REDACT_SUBSTRINGS`, includes `token`, `secret`, `credential`). Never hand it a raw token under any key.

**Job conventions** (unchanged from Phases 6–7)

- A handler is `async def h(ctx: JobContext, params: dict) -> dict`, registered via `HANDLERS["kind"] = h`, imported for its side effect in `main.py`'s lifespan with `# noqa: F401`.
- Blocking work (SQLAlchemy, proxmoxer) goes in `asyncio.to_thread`. `ctx.log` / `ctx.progress` from the event loop only.
- Expected failures raise `JobFailed`; a `ProxmoxError` escaping a handler is translated to `JobFailed`.
- Long PVE tasks pass `timeout_s=app.state.settings.pve_task_timeout_s` to `await_task`.
- `JobBackend.enqueue(db, *, kind, target_type=None, target_id=None, params=None, requested_by=None) -> Job`; routes use `api/jobs.py::enqueue_and_audit(request, db, user, *, kind, target_type, target_id, params, action=None) -> dict` for the 202 body.

**Entitlement keys**: all already in `proxploy/entitlements/registry.py`; no key is added this phase:
`auth.local`, `auth.totp`, `auth.oidc`, `rbac.roles`, `teams.rbac`, `api.tokens`, `migrate.cross_host`, `migrate.preflight`.

**Frontend**

- `api<T>(path, opts)` from `src/api/client.ts` prefixes `/api/v1`, sets `X-CSRF-Token` on mutating verbs, throws `ApiError { status, body }`.
- Tests mock `../api/client` with `vi.mock` and render inside a `QueryClientProvider`, copy the shape from `src/tests/channels.test.tsx`.
- Entitlement-gated UI waits for the first entitlements fetch (`ent.data != null && ent.has(key)`) before deciding.

**Honesty rules (brief §8, established practice)**

- **What cannot be proven on this machine, said plainly:** doc 10's DoD clause "OIDC round-trips against a real Authelia" is not provable here; no browser, no Authelia, no live IdP. The closest honest substitute is a **local mock OIDC provider fixture** (Task 11): a real discovery document, real PKCE authorization-code flow, real RS256-signed ID tokens verified against a real JWKS endpoint; everything except a third-party implementation on the wire. The DoD verification (Task 23) states this substitution explicitly, as Phases 5–7 stated their no-browser/no-PVE gaps. Likewise "an app migrates between two non-clustered hosts" is proven against two `FakePVE` instances plus a fake SFTP layer driving the **real** preflight, handler, and route code; not against real hardware.
- Mark deliberate simplifications that cut a real corner with a `ponytail:` comment naming the ceiling and the upgrade path.

---

## File Structure

**Backend, new files**

| File | Responsibility |
|---|---|
| `backend/proxploy/services/authz.py` | Casbin model text, the `PERMISSIONS` matrix, `build_enforcer(db)`, `sync_user(enforcer, db, user_id)`, `enforce(...)`. The only module that imports casbin. |
| `backend/proxploy/services/totp.py` | TOTP blob pack/unpack (Fernet), enrollment, code + recovery-code verification, one-time burn. |
| `backend/proxploy/services/oidc.py` | OIDC config from settings, discovery, PKCE begin/complete, joserfc ID-token validation, JIT provisioning. |
| `backend/proxploy/services/migrate.py` | Preflight (strategy pick, capacity, size/downtime estimate) + the `migrate.app` job handler. |
| `backend/proxploy/executor/transfer.py` | SFTP archive streaming between two hosts via asyncssh (executor package = the only asyncssh zone). |
| `backend/proxploy/api/teams.py` | `/teams` CRUD + members + `GET /users` list. |
| `backend/proxploy/api/apikeys.py` | `/api-keys` list/create/revoke. |
| `backend/tests/fakes/oidc.py` | In-process mock OIDC IdP (discovery, authorize, token, jwks) with a real RSA key. |
| `backend/tests/test_authz_core.py`, `test_authorize_dep.py`, `test_rbac_invariant.py`, `test_teams_api.py`, `test_totp.py`, `test_auth_totp_login.py`, `test_sessions_api.py`, `test_oidc.py`, `test_apikeys.py`, `test_rest_token_drive.py`, `test_openapi_surface.py`, `test_migrate_preflight.py`, `test_migrate_job.py`, `test_migrate_transfer.py`, `test_migrate_api.py` | Coverage for the above. |

**Backend, modified files**

| File | Change |
|---|---|
| `backend/pyproject.toml` | Add `casbin>=1.43,<2`, `Authlib>=1.7,<2`, `pyotp>=2.10,<3`. |
| `backend/proxploy/api/deps.py` | `authorize(resource, action, scope_of=None)` dependency factory + team-scope resolvers + API-key bearer resolution in `get_current_user` (Task 12). `require_role` is deleted once the last router converts (Task 5). |
| `backend/proxploy/main.py` | Build `app.state.authz` enforcer in lifespan; import `services/migrate` for handler registration; `app.state.pending_totp` / `app.state.oidc_states` dicts. |
| `backend/proxploy/config.py` | `migrate_assumed_bps` (downtime estimator), `totp_pending_ttl_s`. |
| `backend/proxploy/api/auth.py` | TOTP login step, enroll/confirm/disable, sessions list/revoke, OIDC login/callback/config routes; `create_user` role check goes through the enforcer. |
| `backend/proxploy/api/hosts.py` | `HostPatchIn` gains `team_id`; router converts to `authorize`. |
| Every other router (`apps`, `catalog`, `vms`, `consoles`, `storage`, `network`, `backups`, `jobs`, `schedules`, `notifications`, `alerts`, `metrics`, `audit`, `settings`, `entitlements`, `cluster`, `meta`) | `require_role(X)` → `authorize(resource, action)` per the matrix (Tasks 2–5); migrate + preflight routes in `apps.py` (Tasks 14, 15). |
| `backend/proxploy/api/__init__.py` | Register `teams.router`, `apikeys.router`. |
| `backend/proxploy/services/proxmox.py` | `cluster_status()`, `migrate_guest(kind, node, vmid, params)`. |
| `backend/tests/fakes/pve.py` | `cluster_status_rows` + migrate leaf + `make_addressed_factory(fakes_by_host)`. |
| `backend/tests/fakes/ssh.py` | Fake SFTP client for the transfer path. |
| `backend/tests/support.py` | `login_as(client, csrf, email, role)` helper (creates user + logs in). |
| `backend/tests/test_route_auth_invariant.py` | New PUBLIC entries for the OIDC routes (with reasons). |

**Frontend, new files**

| File | Responsibility |
|---|---|
| `frontend/src/api/account.ts` | TOTP enroll/confirm/disable, sessions, OIDC config types + hooks. |
| `frontend/src/api/teams.ts` | Teams/members/users types + hooks. |
| `frontend/src/api/apikeys.ts` | API-key types + hooks. |
| `frontend/src/api/migrate.ts` | Preflight + migrate types + hooks. |
| `frontend/src/components/TotpCard.tsx`, `SessionsCard.tsx`, `ApiKeysCard.tsx`, `TeamsCard.tsx`, `MigrateDialog.tsx` | The five new UI surfaces. |
| `frontend/src/tests/totp.test.tsx`, `sessions.test.tsx`, `apikeys.test.tsx`, `teams.test.tsx`, `migrate.test.tsx`, `login-totp.test.tsx` | Coverage. |

**Frontend, modified files**

`src/routes/login.tsx` (TOTP step + SSO button), `src/routes/settings.tsx` (Security / API keys / Teams cards), `src/routes/apps.tsx` + app detail (Migrate action), `src/components/HostForm.tsx` or host edit surface (team assignment).

---

## Task Order and Dependencies

```
RBAC & Teams
1  authz core (deps + casbin model + matrix + g-line sync, pure)
2  └─ authorize() dependency + lifespan wiring + hosts/cluster converted (the pattern)
3     └─ apps/catalog/consoles converted
4     └─ vms/storage/network/backups converted
5     └─ jobs/schedules/notifications/alerts/metrics/audit/settings/entitlements/meta/auth converted; require_role deleted
6  └─ teams + members + GET /users API, host team assignment, g-line sync on write
7     └─ RBAC invariant suite (every-route-has-authorize + viewer-cannot-mutate walk + cross-team scoping), stays a gate for every later task
AuthN
8  TOTP service + enroll/confirm/disable routes (independent of 1–7 internals, lands after 5 so its routes use authorize-era deps.py)
9  └─ login TOTP step + pending store + sessions list/revoke
10 OIDC config + service (discovery, PKCE, state store, joserfc validation, JIT)
11 └─ OIDC routes + mock IdP fixture + round-trip test
API tokens
12 bearer resolution + scopes + /api-keys routes (needs 2's authorize; scope check folds in)
13 └─ token-authed REST drive + OpenAPI-vs-frontend surface audit
Migration
14 ProxmoxClient cluster_status/migrate_guest + FakePVE support + preflight service + route
15 └─ migrate.app handler: cluster-native + shared-storage paths + route
16    └─ vzdump+SFTP-transfer path (executor/transfer.py)
Frontend
17 login TOTP step + SSO button            (needs 9, 11)
18 Security card: TOTP + Sessions          (needs 8, 9)
19 API keys card                           (needs 12)
20 Teams admin UI + host team assignment   (needs 6)
21 Migrate dialog with preflight/downtime  (needs 14–16)
Close-out
22 DoD verification script + notes + doc amendments + buildlog
```

Chains 1–7, 8–9, 10–11, 12–13 and 14–16 are independent of each other except where noted; frontend tasks need their backend counterparts landed. Task 22 is last.

---

## Task 1: AuthZ core: casbin model, permission matrix, membership sync

**Files:**
- Modify: `backend/pyproject.toml` (dependency list, after the `"APScheduler>=3.11,<4",` block)
- Create: `backend/proxploy/services/authz.py`
- Test: `backend/tests/test_authz_core.py`

**Interfaces:**
- Consumes: `proxploy.models.TeamMember`, `proxploy.api.deps.ROLE_ORDER` (import the dict from `deps`, do not duplicate it).
- Produces, for Tasks 2–7:
  - `PERMISSIONS: dict[tuple[str, str], str]`: `(resource, action) → min_role`, the one authoritative matrix.
  - `build_enforcer(db) -> casbin.Enforcer`: static p-lines + g-lines from `team_members`.
  - `sync_user(enforcer, db, user_id: int) -> None`: drop and re-add one user's g-lines (called after any membership write).
  - `enforce(enforcer, db, user, resource: str, action: str, *, team_id: int | None = None) -> bool`: domain-scoped when `team_id` given, any-of-my-teams otherwise.

- [ ] **Step 1: Add the dependencies**

In `backend/pyproject.toml`, after the APScheduler block, add:

```toml
  # Phase 8 (doc 10). All three verified against PyPI 2026-08-05 in a clean
  # venv and run through the exact ci.yml allow-only string: see
  # docs/superpowers/plans/2026-08-05-phase-8-scale.md Global Constraints.
  # casbin: RBAC-with-domains evaluation only, in-memory Enforcer, no adapter
  # (doc 04's casbin_rules mirror deliberately unused: one source of truth,
  # amendment recorded in docs/notes/phase-8-scale.md). Transitive: simpleeval (MIT).
  "casbin>=1.43,<2",
  # Authlib: OIDC authorization-code + PKCE client. ID-token verification uses
  # joserfc (Authlib's own dependency, BSD): authlib.jose is deprecated at 1.7.
  "Authlib>=1.7,<2",
  # pyotp: RFC 6238 TOTP. Zero dependencies.
  "pyotp>=2.10,<3",
```

Then: `./.venv/bin/pip install -e ".[dev]"`

- [ ] **Step 2: Confirm the licence gate still passes**

```bash
./.venv/bin/pip-licenses --partial-match --ignore-packages proxploy --allow-only "MIT;MIT License;BSD;BSD License;Apache;Apache Software License;ISC;Python Software Foundation;PSF-2.0;PostgreSQL;Public Domain;Mozilla Public License 2.0;Eclipse Public License v2.0;EPL-2.0;The Unlicense;CMU License (MIT-CMU)"
```

Expected: exit 0. `casbin` (Apache Software License), `simpleeval` (MIT License), `Authlib` (BSD License), `joserfc` (BSD License), `pyotp` (MIT) all clear. If anything fails here, stop; a dependency outside brief §3 does not ship.

- [ ] **Step 3: Write the failing tests**

Create `backend/tests/test_authz_core.py`:

```python
"""AuthZ core (doc 08 §6, doc 10 Phase 8): the casbin model, the static
permission matrix, and membership-driven grouping rules. Pure, no HTTP."""
import pytest

from proxploy.api.deps import ROLE_ORDER
from proxploy.models import Team, TeamMember, User
from proxploy.services.authz import PERMISSIONS, build_enforcer, enforce, sync_user
from tests.support import make_db


def _user(db, email, *, role, team):
    u = User(email=email)
    db.add(u); db.commit()
    db.add(TeamMember(team_id=team.id, user_id=u.id, role=role))
    db.commit()
    return u


def _team(db, slug):
    t = Team(name=slug.title(), slug=slug)
    db.add(t); db.commit()
    return t


@pytest.fixture
def world(tmp_path):
    db = make_db(tmp_path)
    a, b = _team(db, "team-a"), _team(db, "team-b")
    return {
        "db": db, "a": a, "b": b,
        "viewer": _user(db, "v@x.io", role="viewer", team=a),
        "operator": _user(db, "o@x.io", role="operator", team=a),
        "admin": _user(db, "ad@x.io", role="admin", team=a),
        "owner": _user(db, "ow@x.io", role="owner", team=a),
    }


def test_matrix_uses_only_known_roles():
    assert set(PERMISSIONS.values()) <= set(ROLE_ORDER)


def test_matrix_reads_are_viewer_and_matrix_has_no_write_at_viewer():
    """Doc 10 DoD: a viewer cannot mutate anything. The matrix itself must
    already say so, every non-read action requires operator or above."""
    for (resource, action), min_role in PERMISSIONS.items():
        if action != "read":
            assert ROLE_ORDER[min_role] >= ROLE_ORDER["operator"], (
                f"({resource}, {action}) grants a mutation to {min_role}")


def test_role_ladder_is_cumulative(world):
    e = build_enforcer(world["db"])
    dom = world["a"].id
    assert enforce(e, world["db"], world["viewer"], "app", "read", team_id=dom)
    assert not enforce(e, world["db"], world["viewer"], "app", "lifecycle", team_id=dom)
    assert enforce(e, world["db"], world["operator"], "app", "lifecycle", team_id=dom)
    assert not enforce(e, world["db"], world["operator"], "app", "install", team_id=dom)
    assert enforce(e, world["db"], world["admin"], "app", "install", team_id=dom)
    assert not enforce(e, world["db"], world["admin"], "host", "remove", team_id=dom)
    assert enforce(e, world["db"], world["owner"], "host", "remove", team_id=dom)


def test_domains_scope_roles_to_their_team(world):
    """An admin of team A is nobody in team B (doc 08 §6)."""
    e = build_enforcer(world["db"])
    assert enforce(e, world["db"], world["admin"], "host", "manage",
                   team_id=world["a"].id)
    assert not enforce(e, world["db"], world["admin"], "host", "manage",
                       team_id=world["b"].id)


def test_global_enforcement_passes_on_any_membership(world):
    """team_id=None = a global resource (settings, catalog, users): the check
    passes if ANY of the user's memberships grants it."""
    db = world["db"]
    e = build_enforcer(db)
    u = world["viewer"]
    assert not enforce(e, db, u, "settings", "manage")
    db.add(TeamMember(team_id=world["b"].id, user_id=u.id, role="admin"))
    db.commit()
    sync_user(e, db, u.id)
    assert enforce(e, db, u, "settings", "manage")


def test_fail_closed_everywhere(world):
    e = build_enforcer(world["db"])
    db = world["db"]
    # unknown resource, unknown action, user with no memberships: all deny
    assert not enforce(e, db, world["owner"], "nonsense", "read",
                       team_id=world["a"].id)
    assert not enforce(e, db, world["owner"], "app", "nonsense",
                       team_id=world["a"].id)
    lone = User(email="ghost@x.io")
    db.add(lone); db.commit()
    assert not enforce(e, db, lone, "app", "read", team_id=world["a"].id)
    assert not enforce(e, db, lone, "app", "read")


def test_sync_user_revokes_a_removed_membership(world):
    db = world["db"]
    e = build_enforcer(db)
    m = (db.query(TeamMember)
         .filter_by(user_id=world["admin"].id, team_id=world["a"].id).one())
    db.delete(m); db.commit()
    sync_user(e, db, world["admin"].id)
    assert not enforce(e, db, world["admin"], "host", "manage",
                       team_id=world["a"].id)
```

- [ ] **Step 4: Run to verify failure**

`./.venv/bin/python -m pytest tests/test_authz_core.py -q`: expected: ImportError (`proxploy.services.authz` does not exist).

- [ ] **Step 5: Implement `backend/proxploy/services/authz.py`**

```python
"""Authorizer seam (doc 08 §6, doc 03 AuthZ row): pycasbin RBAC with domains.

The ONLY module that imports casbin. The enforcer is in-memory: static
p-lines generated from PERMISSIONS below, g-lines derived from team_members.
The casbin_rules table stays empty, doc 04's "mirrored into casbin_rules"
design would be two sources of truth for the same memberships; team_members
is authoritative and the enforcer is a pure function of it (rebuilt at boot,
patched by sync_user() on every membership write). Amendment recorded in
docs/notes/phase-8-scale.md, mirroring Phase 7's APScheduler precedent.
"""
from __future__ import annotations

import casbin

from proxploy.api.deps import ROLE_ORDER
from proxploy.models import TeamMember, User

# RBAC with domains (doc 08 §6): sub = user:<id>, dom = team:<id>,
# obj = resource type, act = verb. p.dom is always "*" (the role→permission
# matrix is identical in every team; WHICH team a user holds a role in is
# what the g-lines scope). Matching is exact: no keyMatch, no regex, so an
# unknown obj/act can never accidentally glob onto a policy.
MODEL_TEXT = """
[request_definition]
r = sub, dom, obj, act

[policy_definition]
p = sub, dom, obj, act

[role_definition]
g = _, _, _

[policy_effect]
e = some(where (p.eft == allow))

[matchers]
m = g(r.sub, p.sub, r.dom) && (p.dom == "*" || p.dom == r.dom) && p.obj == r.obj && p.act == r.act
"""

# (resource, action) -> minimum role. Derived row-by-row from doc 05's Role
# column. This is the single authoritative matrix: authorize() (api/deps.py)
# refuses at import time to build a dependency for a pair not listed here.
# `read` is deliberately the only viewer-reachable action: doc 10's DoD
# ("a viewer cannot mutate anything") is a property of this table first and
# a test (test_rbac_invariant.py) second.
PERMISSIONS: dict[tuple[str, str], str] = {
    ("host", "read"): "viewer",
    ("host", "sync"): "operator",
    ("host", "manage"): "admin",        # onboard, patch, probe
    ("host", "credentials"): "owner",   # rotate stored secrets
    ("host", "remove"): "owner",
    ("host", "console"): "admin",       # node shell tickets (doc 08 §6 note)
    ("app", "read"): "viewer",
    ("app", "lifecycle"): "operator",
    ("app", "configure"): "operator",   # PATCH metadata, guest NICs
    ("app", "update"): "operator",
    ("app", "script"): "admin",         # PUT script (doc 05: admin)
    ("app", "console"): "operator",
    ("app", "install"): "admin",        # store install
    ("app", "adopt"): "admin",
    ("app", "remove"): "admin",
    ("app", "migrate"): "admin",
    ("vm", "read"): "viewer",
    ("vm", "lifecycle"): "operator",
    ("vm", "configure"): "operator",    # guest NICs
    ("vm", "snapshot"): "operator",     # take/delete
    ("vm", "rollback"): "admin",
    ("vm", "create"): "admin",
    ("vm", "clone"): "admin",
    ("vm", "remove"): "owner",
    ("vm", "console"): "operator",
    ("storage", "read"): "viewer",
    ("storage", "content"): "admin",    # upload/delete volumes
    ("storage", "manage"): "admin",     # attach/edit
    ("storage", "remove"): "owner",     # detach
    ("network", "read"): "viewer",
    ("network", "guest"): "operator",
    ("network", "host"): "admin",
    ("backup", "read"): "viewer",
    ("backup", "run"): "operator",
    ("backup", "restore"): "admin",
    ("backup", "manage"): "admin",      # delete, prune
    ("catalog", "read"): "viewer",
    ("catalog", "refresh"): "admin",
    ("job", "read"): "viewer",
    ("job", "cancel"): "operator",
    ("schedule", "read"): "viewer",
    ("schedule", "manage"): "admin",
    ("schedule", "run"): "operator",
    ("alert", "read"): "viewer",
    ("alert", "ack"): "operator",
    ("alert", "manage"): "admin",
    ("channel", "manage"): "admin",
    ("metric", "read"): "viewer",
    ("audit", "read"): "admin",
    ("audit", "export"): "owner",
    ("settings", "read"): "admin",
    ("settings", "manage"): "admin",
    ("user", "read"): "admin",
    ("user", "manage"): "admin",
    ("team", "read"): "viewer",
    ("team", "manage"): "owner",
    ("entitlement", "read"): "viewer",
    ("entitlement", "manage"): "owner",
    ("meta", "read"): "viewer",
    ("meta", "update"): "owner",        # self-update (Phase 9 route not built yet)
}


def _sub(user_id: int) -> str:
    return f"user:{user_id}"


def _dom(team_id: int) -> str:
    return f"team:{team_id}"


def build_enforcer(db) -> casbin.Enforcer:
    model = casbin.Model()
    model.load_model_from_text(MODEL_TEXT)
    e = casbin.Enforcer(model)  # no adapter: in-memory, nothing auto-saved
    for (resource, action), min_role in PERMISSIONS.items():
        for role, order in ROLE_ORDER.items():
            if order >= ROLE_ORDER[min_role]:
                e.add_policy(f"role:{role}", "*", resource, action)
    for m in db.query(TeamMember).all():
        e.add_grouping_policy(_sub(m.user_id), f"role:{m.role}", _dom(m.team_id))
    return e


def sync_user(enforcer, db, user_id: int) -> None:
    """Re-derive one user's g-lines after a membership write. remove_filtered_
    grouping_policy(0, sub) drops every rule whose field 0 is the subject."""
    enforcer.remove_filtered_grouping_policy(0, _sub(user_id))
    for m in db.query(TeamMember).filter_by(user_id=user_id).all():
        enforcer.add_grouping_policy(_sub(user_id), f"role:{m.role}", _dom(m.team_id))


def enforce(enforcer, db, user: User, resource: str, action: str, *,
            team_id: int | None = None) -> bool:
    """Domain-scoped when team_id is given (host/app/vm resources); otherwise
    a global resource, allowed if ANY of the user's memberships grants it.
    Fail-closed: no membership, unknown resource, unknown action all deny."""
    sub = _sub(user.id)
    if team_id is not None:
        return bool(enforcer.enforce(sub, _dom(team_id), resource, action))
    team_ids = [m.team_id for m in
                db.query(TeamMember.team_id).filter_by(user_id=user.id)]
    return any(enforcer.enforce(sub, _dom(t), resource, action) for t in team_ids)
```

Note: `remove_filtered_grouping_policy(0, sub)`; verify against the installed casbin 1.43 in the venv before relying on it (`python -c "import casbin; help(casbin.Enforcer.remove_filtered_grouping_policy)"`). If the signature differs, fall back to `remove_grouping_policy` per rule from `get_filtered_grouping_policy(0, sub)`.

- [ ] **Step 6: Run the tests**

`./.venv/bin/python -m pytest tests/test_authz_core.py -q`: expected: all pass.

- [ ] **Step 7: Full backend suite** (`pytest tests/ -m "not pve_integration and not e2e" -q`), expected: ≥ 663 passed, nothing newly failing.

- [ ] **Step 8: Commit**

```bash
git add backend/pyproject.toml backend/proxploy/services/authz.py backend/tests/test_authz_core.py
git commit -m "feat(authz): casbin RBAC-with-domains core, permission matrix, enforcer build, membership sync"
```

## Task 2: The `authorize()` dependency: wiring, scope resolvers, first two routers

**Files:**
- Modify: `backend/proxploy/api/deps.py`
- Modify: `backend/proxploy/main.py` (lifespan)
- Modify: `backend/proxploy/api/hosts.py`, `backend/proxploy/api/cluster.py`
- Test: `backend/tests/test_authorize_dep.py`

**Interfaces:**
- Consumes: `services.authz.{PERMISSIONS, build_enforcer, enforce}`, `get_current_user`, `get_db`.
- Produces, for Tasks 3–7 and every later route task:
  - `authorize(resource: str, action: str, *, scope_of=None)`: FastAPI dependency factory returning the `User`. Raises `RuntimeError` **at call time (route registration)** for a pair not in `PERMISSIONS`. The inner `dep` function carries `dep.__proxploy_authz__ = (resource, action)` so Task 7's meta-test can find it in the dependant tree.
  - Scope resolvers `scope_host(param="host_id")`, `scope_app(param="app_id")`, `scope_vm(param="vm_id")`, `scope_backup(param="backup_id")`, each returns a `(db, path_params) -> int | None` callable resolving the owning team id (`hosts.team_id`, or the default team when NULL). A missing row resolves to `None` (global semantics) so the handler's own 404 still fires and the resolver never becomes an existence oracle.
  - `app.state.authz`: the enforcer, built in lifespan.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_authorize_dep.py`:

```python
"""authorize() dependency behaviour (doc 08 §6 enforcement point), proven on
the two routers this task converts (hosts, cluster)."""
import pytest
from fastapi.testclient import TestClient

from proxploy.models import AuditEvent, Host, Team, TeamMember, User
from tests.support import make_app


def _mk_user(client, csrf_header, email, role, password="correct-horse-battery"):
    h = csrf_header(client)
    r = client.post("/api/v1/users", json={"email": email, "password": password,
                                           "role": role}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _login(client, csrf_header, email, password="correct-horse-battery"):
    r = client.post("/api/v1/auth/login", json={"email": email,
                    "password": password}, headers=csrf_header(client))
    assert r.status_code == 200, r.text


@pytest.fixture
def app_client(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)             # owner session, default team
        yield c


def test_unregistered_permission_pair_fails_at_registration():
    from proxploy.api.deps import authorize
    with pytest.raises(RuntimeError, match="unregistered"):
        authorize("gizmo", "frobnicate")


def test_viewer_reads_hosts_but_cannot_patch(app_client, csrf_header):
    _mk_user(app_client, csrf_header, "v@x.io", "viewer")
    app_client.post("/api/v1/auth/logout", headers=csrf_header(app_client))
    _login(app_client, csrf_header, "v@x.io")
    assert app_client.get("/api/v1/hosts").status_code == 200
    r = app_client.patch("/api/v1/hosts/1", json={"node_shell_enabled": True},
                         headers=csrf_header(app_client))
    assert r.status_code == 403


def test_denied_attempt_writes_an_audit_row(app_client, csrf_header, tmp_path):
    """Doc 08 §7: denials are evidence too."""
    _mk_user(app_client, csrf_header, "v2@x.io", "viewer")
    app_client.post("/api/v1/auth/logout", headers=csrf_header(app_client))
    _login(app_client, csrf_header, "v2@x.io")
    app_client.patch("/api/v1/hosts/1", json={"node_shell_enabled": True},
                     headers=csrf_header(app_client))
    with app_client.app.state.sessionmaker() as db:
        row = (db.query(AuditEvent)
               .filter_by(action="host.manage", result="denied").one())
        assert row.actor_type == "user"


def test_team_scoped_route_checks_the_owning_team(app_client, csrf_header):
    """Admin of team B cannot sync team A's host, the domain comes from
    hosts.team_id, not from 'has admin anywhere'."""
    with app_client.app.state.sessionmaker() as db:
        team_b = Team(name="B", slug="b")
        db.add(team_b); db.commit()
        h = Host(name="scoped", address="https://10.0.0.9:8006",
                 node_name="pve1")   # team_id NULL -> default team
        db.add(h); db.commit()
        host_id, team_b_id = h.id, team_b.id
    _mk_user(app_client, csrf_header, "badmin@x.io", "viewer")
    with app_client.app.state.sessionmaker() as db:
        u = db.query(User).filter_by(email="badmin@x.io").one()
        m = db.query(TeamMember).filter_by(user_id=u.id).one()
        m.role = "viewer"; db.commit()
        db.add(TeamMember(team_id=team_b_id, user_id=u.id, role="admin"))
        db.commit()
        from proxploy.services.authz import sync_user
        sync_user(app_client.app.state.authz, db, u.id)
    app_client.post("/api/v1/auth/logout", headers=csrf_header(app_client))
    _login(app_client, csrf_header, "badmin@x.io")
    r = app_client.post(f"/api/v1/hosts/{host_id}/sync",
                        headers=csrf_header(app_client))
    assert r.status_code == 403   # admin of B, viewer in the host's team


def test_anonymous_still_gets_401_not_403(app_client, csrf_header):
    h = csrf_header(app_client)
    app_client.post("/api/v1/auth/logout", headers=h)
    assert app_client.get("/api/v1/hosts").status_code == 401
    assert app_client.patch("/api/v1/hosts/1", json={},
                            headers=h).status_code == 401
```

Run: `pytest tests/test_authorize_dep.py -q`, expected: ImportError / 404s (nothing implemented).

- [ ] **Step 2: Implement `authorize()` in `backend/proxploy/api/deps.py`**

Append (keep `require_role` for the not-yet-converted routers, it dies in Task 5):

```python
def _team_of_host(db, host_id) -> int | None:
    from proxploy.models import Host
    h = db.get(Host, int(host_id))
    if h is None:
        return None          # let the handler 404; never an existence oracle
    return h.team_id if h.team_id is not None else default_team(db).id


def scope_host(param: str = "host_id"):
    def resolve(db, path_params) -> int | None:
        raw = path_params.get(param)
        return _team_of_host(db, raw) if raw is not None else None
    return resolve


def scope_app(param: str = "app_id"):
    def resolve(db, path_params) -> int | None:
        from proxploy.models import App
        raw = path_params.get(param)
        if raw is None:
            return None
        a = db.get(App, int(raw))
        return _team_of_host(db, a.host_id) if a else None
    return resolve


def scope_vm(param: str = "vm_id"):
    def resolve(db, path_params) -> int | None:
        from proxploy.models import Vm
        raw = path_params.get(param)
        if raw is None:
            return None
        v = db.get(Vm, int(raw))
        return _team_of_host(db, v.host_id) if v else None
    return resolve


def scope_backup(param: str = "backup_id"):
    def resolve(db, path_params) -> int | None:
        from proxploy.models import Backup
        raw = path_params.get(param)
        if raw is None:
            return None
        b = db.get(Backup, int(raw))
        return _team_of_host(db, b.host_id) if b else None
    return resolve


def authorize(resource: str, action: str, *, scope_of=None):
    """Doc 08 §6 enforcement point. Replaces require_role() route-by-route in
    Phase 8. Fail-closed twice over: an unregistered (resource, action) pair
    refuses to even build a dependency (so an ungoverned route cannot be
    registered), and the enforcer denies anything it does not recognise.
    Order on routes: dependencies=[Depends(authorize(...)),
    Depends(require_entitlement(...))], authorize resolves get_current_user
    first, so an anonymous caller still gets 401 before any 403."""
    from proxploy.services.authz import PERMISSIONS, enforce as _enforce
    if (resource, action) not in PERMISSIONS:
        raise RuntimeError(f"unregistered permission: ({resource!r}, {action!r})")

    def dep(request: Request, db=Depends(get_db),
            user: User = Depends(get_current_user)) -> User:
        team_id = scope_of(db, request.path_params) if scope_of else None
        # Task 12 folds API-key scope checks in here (require_key_scope).
        if not _enforce(request.app.state.authz, db, user, resource, action,
                        team_id=team_id):
            from proxploy.services.audit import write_audit
            write_audit(db, actor_type="user", actor_id=user.id,
                        action=f"{resource}.{action}", result="denied",
                        ip=request.client.host if request.client else None)
            raise HTTPException(403, "forbidden")
        return user

    dep.__proxploy_authz__ = (resource, action)   # Task 7's meta-test marker
    return dep
```

- [ ] **Step 3: Build the enforcer in lifespan, and sync it on user creation**

In `backend/proxploy/main.py`, immediately after `app.state.sessionmaker = make_sessionmaker(...)` and the entitlements load:

```python
from proxploy.services.authz import build_enforcer
with app.state.sessionmaker() as db:
    app.state.authz = build_enforcer(db)
```

**In the same step**, in `api/auth.py::create_user`, after the `TeamMember` insert + commit, add:

```python
from proxploy.services.authz import sync_user
sync_user(request.app.state.authz, db, user.id)
```

This cannot wait for Task 5: the enforcer is built at boot, before any test's users exist; without this sync, the bootstrap owner created inside a `TestClient` context has no g-lines and every converted route 403s the owner. (Task 6 adds the same call to team-member mutations; login never changes memberships, so nothing else needs it.)

- [ ] **Step 4: Convert `api/hosts.py` and `api/cluster.py`**

Mechanical pattern, applied to every route in both files; replace `Depends(require_role("X"))` (both the route-level `dependencies=[...]` copy and the parameter-level `user: User = Depends(...)` copy) with a module-level singleton of the matching matrix entry, e.g. in `hosts.py`:

```python
from proxploy.api.deps import authorize, scope_host

_read = authorize("host", "read")
_sync = authorize("host", "sync", scope_of=scope_host())
_manage = authorize("host", "manage", scope_of=scope_host())
_manage_global = authorize("host", "manage")          # POST /hosts (no id yet)
_credentials = authorize("host", "credentials", scope_of=scope_host())
_remove = authorize("host", "remove", scope_of=scope_host())
_console = authorize("host", "console", scope_of=scope_host())
```

Route-by-route mapping for `hosts.py` (from doc 05): `GET /hosts`, `GET /hosts/{id}`, `GET /hosts/{id}/tasks` → `_read`; `POST /hosts`, `POST /hosts/{id}/test` → `_manage_global`/`_manage`; `PATCH /hosts/{id}` → `_manage`; `DELETE /hosts/{id}` → `_remove`; `PUT /hosts/{id}/credentials/{kind}` → `_credentials`; `POST /hosts/{id}/sync` → `_sync`; shell tickets (if in this router; they are in `consoles.py`, leave for Task 3). For `cluster.py`: all three GETs → `authorize("cluster"…)`, **no**: cluster reads are host-shaped aggregates; use `authorize("host", "read")`. Keep the same singleton-reuse and role-before-entitlement ordering as today; the path param name in `hosts.py` routes must match the resolver's `param` (check each route's actual `{host_id}` spelling and pass `scope_host("hostId")` etc. where a router spells it differently, `storage.py` uses `hostId`).

Also in this step: `HostPatchIn` gains `team_id: int | None = None` (doc 05 "team assignment"), applied when present, with the audit row params gaining `{"team_id": ...}`. Update the class docstring (it currently claims node_shell_enabled is "the only editable field, deliberately").

- [ ] **Step 5: Run the new tests, then the full suites**

`pytest tests/test_authorize_dep.py tests/test_route_auth_invariant.py tests/test_hosts.py tests/test_cluster_api.py -q`: all pass; then the full backend suite ≥ its floor.

- [ ] **Step 6: Commit**

```bash
git add backend/proxploy/api/deps.py backend/proxploy/main.py backend/proxploy/api/hosts.py backend/proxploy/api/cluster.py backend/tests/test_authorize_dep.py
git commit -m "feat(authz): authorize() dependency with team-scope resolvers; hosts and cluster converted"
```

---

## Task 3: Convert apps, catalog, consoles routers

**Files:**
- Modify: `backend/proxploy/api/apps.py`, `backend/proxploy/api/catalog.py`, `backend/proxploy/api/consoles.py`
- Test: existing suites (`test_apps_vms_api.py`, `test_lifecycle_api.py`, `test_app_update_api.py`, `test_apps_adopt.py`, `test_app_script_api.py`, `test_catalog_api.py`, `test_catalog_install_api.py`, `test_consoles_api.py`, `test_consoletickets.py`, `test_route_auth_invariant.py`)

**Interfaces:**
- Consumes: `authorize`, `scope_app`, `scope_host`, `scope_vm` from Task 2.
- Produces: nothing new, behaviour-preserving conversion (same minimum roles as today, plus team-domain scoping on id-carrying routes).

- [ ] **Step 1: Convert `apps.py`**, replace `_require_admin`/`_require_operator`/`_require_viewer` with matrix singletons: reads → `authorize("app","read", scope_of=scope_app())` (list/discovered routes have no id → plain `authorize("app","read")`); lifecycle wildcard → `("app","lifecycle", scope_of=scope_app())`; PATCH → `("app","configure",…)`; DELETE → `("app","remove",…)`; update routes → `("app","update",…)`; script GET/versions → `("app","script",…)`, **check doc 05 first**: script GET is operator, PUT is admin; the matrix has one `("app","script")="admin"` entry, split it: add `("app","script_read")="operator"` to `PERMISSIONS` in the same commit if the existing tests assert operator can GET the script (they do, read `test_app_script_api.py` before choosing). adopt → `("app","adopt")`; console tickets → `("app","console", scope_of=scope_app())`; network sub-routes → `("app","configure",…)` for PUT, `("network","read")`-shaped GET stays as `("app","read",…)`; match whatever role the existing tests assert. **The existing per-router tests are the oracle: a conversion that changes any current status code is wrong.**
- [ ] **Step 2: Convert `catalog.py`**, reads → `("catalog","read")`, refresh → `("catalog","refresh")`, install → `("app","install", scope_of=…)`; install's body carries `host_id`, not a path param, so it stays global-domain (`ponytail:` comment noting body-derived team scoping as the upgrade path).
- [ ] **Step 3: Convert `consoles.py`**, CT console tickets `("app","console")`, VM `("vm","console")`, node shell `("host","console")`, each with its scope resolver; websocket routes authenticate by ticket, not session; leave their auth exactly as-is.
- [ ] **Step 4: Run** the listed suites, then the full backend suite. Fix any status-code drift by correcting the mapping, never by editing an existing test's expectation.
- [ ] **Step 5: Commit**, `feat(authz): apps, catalog, consoles on casbin authorize()`.

---

## Task 4: Convert vms, storage, network, backups routers

**Files:**
- Modify: `backend/proxploy/api/vms.py`, `backend/proxploy/api/storage.py`, `backend/proxploy/api/network.py`, `backend/proxploy/api/backups.py`
- Test: existing suites (`test_apps_vms_api.py`, `test_snapshots_api.py`, `test_vm_create_clone.py`, `test_storage_api.py`, `test_storage_content.py`, `test_storage_manage.py`, `test_network_api.py`, `test_network_hostconfig.py`, `test_backups_api.py`, `test_route_auth_invariant.py`)

- [ ] **Step 1: `vms.py`**, reads `("vm","read", scope_of=scope_vm())`, lifecycle `("vm","lifecycle",…)`, snapshots take/delete `("vm","snapshot",…)`, rollback `("vm","rollback",…)`, create `("vm","create")` (body-carried host), clone `("vm","clone",…)`, DELETE `("vm","remove",…)`, network PUT `("vm","configure",…)`.
- [ ] **Step 2: `storage.py`**, note the `hostId` param spelling: `scope_host("hostId")`. Reads → `("storage","read")`, content GET → `("storage","read")` vs mutations → `("storage","content")`, attach/PATCH → `("storage","manage")`, DELETE storage → `("storage","remove")`; again, existing tests are the oracle for exact minimum roles.
- [ ] **Step 3: `network.py`**, reads `("network","read")`, guest NIC PUTs are registered under apps/vms routers (already covered); host bridge mutations + apply/revert → `("network","host", scope_of=scope_host("hostId"))`.
- [ ] **Step 4: `backups.py`**, list `("backup","read")`, run `("backup","run")`, restore `("backup","restore", scope_of=scope_backup())`, delete `("backup","manage", scope_of=scope_backup())`, prune/preview `("backup","manage")`.
- [ ] **Step 5: Run** listed suites + full backend suite.
- [ ] **Step 6: Commit**, `feat(authz): vms, storage, network, backups on casbin authorize()`.

---

## Task 5: Convert the remaining routers; delete `require_role`

**Files:**
- Modify: `backend/proxploy/api/jobs.py`, `schedules.py`, `notifications.py`, `alerts.py`, `metrics.py`, `audit.py`, `settings.py`, `entitlements.py`, `meta.py`, `events.py`, `auth.py`
- Modify: `backend/proxploy/api/deps.py` (delete `require_role`; keep `user_role`, `/auth/me` still reports it)
- Test: existing suites for each router + `test_route_auth_invariant.py`

- [ ] **Step 1: Convert**, jobs reads `("job","read")`, cancel `("job","cancel")`; schedules reads `("schedule","read")`, CRUD `("schedule","manage")`, run-now `("schedule","run")`; notifications `("channel","manage")` throughout (doc 05: admin); alerts rules reads `("alert","read")`, rule CRUD `("alert","manage")`, ack `("alert","ack")`; metrics `("metric","read")`; audit `("audit","read")` / export `("audit","export")`; settings `("settings","read")`/`("settings","manage")`; entitlements GET `("entitlement","read")`, license/refresh `("entitlement","manage")`; meta version `("meta","read")`, update check `("settings","read")`-shaped?; **read `api/meta.py` first** and match today's roles exactly; events SSE keeps `get_current_user` (session-only stream, doc 05).
- [ ] **Step 2: `auth.py::create_user`**, after the first-run branch, replace the inline `ROLE_ORDER` comparison with the enforcer: `if not enforce(request.app.state.authz, db, actor, "user", "manage"): raise HTTPException(403...)`, keeping the owner-grants-owner special case as an explicit extra check (`if body.role == "owner" and user_role(db, actor) != "owner": 403`). (The `sync_user` call after the `TeamMember` insert already landed in Task 2 Step 3, verify it is there, do not duplicate it.)
- [ ] **Step 3: Delete `require_role`** from `deps.py`. `grep -rn "require_role" backend/proxploy/` must return nothing.
- [ ] **Step 4: Run** the full backend suite ≥ floor.
- [ ] **Step 5: Commit**, `feat(authz): remaining routers on authorize(); require_role stub retired`.

---

## Task 6: Teams & members API + `GET /users`

**Files:**
- Create: `backend/proxploy/api/teams.py`
- Modify: `backend/proxploy/api/__init__.py` (register router)
- Test: `backend/tests/test_teams_api.py`

**Interfaces:**
- Consumes: `authorize`, `services.authz.sync_user`, `default_team`, `write_audit`, `require_entitlement("teams.rbac")`.
- Produces, for the frontend (Task 20):
  - `GET /api/v1/teams` → `[{id, name, slug, description, member_count, host_count}]` (team read, entitlement `teams.rbac`)
  - `POST /api/v1/teams {name, slug?, description?}` → 201 (team manage); slug auto-derived from name when absent (lowercase, non-alnum → `-`)
  - `PATCH /api/v1/teams/{team_id} {name?, description?}` (team manage)
  - `DELETE /api/v1/teams/{team_id}` (team manage), refuses the default team (409); member rows cascade, hosts revert to `team_id=NULL` (= default team) first
  - `GET /api/v1/teams/{team_id}/members` → `[{user_id, email, display_name, role}]` (team read)
  - `PUT /api/v1/teams/{team_id}/members/{user_id} {role}` (team manage), upsert; 422 on a role outside `ROLE_ORDER`; calls `sync_user` after commit
  - `DELETE /api/v1/teams/{team_id}/members/{user_id}` (team manage), refuses removing the last owner of the default team (409, "cannot remove the last owner"); calls `sync_user`
  - `GET /api/v1/users` → `[{id, email, display_name, is_active, teams: [{team_id, role}]}]` (`("user","read")`); the member-picker source

- [ ] **Step 1: Write the failing tests**, `test_teams_api.py` covering: owner creates a team (201 + audit row `team.create`); admin cannot (`403`); member role upsert immediately changes enforcement (create a viewer, PUT them as `admin` of the new team, then as that user PATCH a host owned by that team succeeds; proves `sync_user` ran); removing the membership revokes it; deleting the default team → 409; removing the last default-team owner → 409; `GET /users` lists memberships; every route 401s anonymous (invariant test covers this automatically, still add one explicit check); entitlement `teams.rbac` off → 403 for a logged-in owner (`client.app.state.entitlements._features = {}` then restore).
- [ ] **Step 2: Run to verify failure** (404s).
- [ ] **Step 3: Implement `api/teams.py`**, singletons `_read = authorize("team", "read")`, `_manage = authorize("team", "manage")`, `_users_read = authorize("user", "read")`; every route also lists `Depends(require_entitlement("teams.rbac"))` **after** the authorize dep (users list gated by nothing, doc 05 shows no entitlement for `/users`). Every mutation: `write_audit` (`team.create`/`team.update`/`team.delete`/`team.member.set`/`team.member.remove`) + `sync_user(request.app.state.authz, db, <user_id>)` for member mutations. Register both routers in `api/__init__.py`.
- [ ] **Step 4: Run** new tests + `test_route_auth_invariant.py` + full suite.
- [ ] **Step 5: Commit**, `feat(teams): teams/members CRUD with live casbin sync + users list`.

---

## Task 7: The RBAC invariant suite

**Files:**
- Create: `backend/tests/test_rbac_invariant.py`
- Test: itself.

This is the doc-10 DoD clause made mechanical: *"a viewer cannot mutate anything (verified by test-suite against every route)"*, plus the guarantee that **every** route is casbin-governed at all. Both tests walk whatever FastAPI actually registered, so every route added later in this phase (migrate, api-keys, OIDC, TOTP) is automatically in scope; later tasks must keep this file green and extend its allowlists only with commented, reviewable entries.

- [ ] **Step 1: Write both invariants**

```python
"""Phase 8 DoD invariants (doc 10): every route is casbin-governed, and a
viewer session can mutate nothing. Both walk app.openapi()/app.routes, so a
route added after this task lands is automatically covered, extending an
allowlist below is a code-review-visible act, exactly like PUBLIC in
test_route_auth_invariant.py."""
import re

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from tests.support import make_app

# Routes that legitimately carry no authorize() dependency. Every entry needs
# a reason. Self-service auth = "acting on my own account", which no role can
# be denied (a viewer signing out is not a mutation of managed state).
UNGOVERNED = {
    ("GET", "/api/v1/meta/health"),          # public liveness
    ("GET", "/api/v1/meta/onboarding"),      # public first-run booleans
    ("POST", "/api/v1/auth/login"),          # how a session begins
    ("POST", "/api/v1/auth/totp"),           # second factor of login (Task 9)
    ("POST", "/api/v1/auth/logout"),         # self-service
    ("GET", "/api/v1/auth/me"),              # self-service
    ("GET", "/api/v1/auth/sessions"),        # self-service (Task 9)
    ("DELETE", "/api/v1/auth/sessions/{sid}"),
    ("POST", "/api/v1/auth/totp/enroll"),    # self-service (Task 8)
    ("POST", "/api/v1/auth/totp/confirm"),
    ("DELETE", "/api/v1/auth/totp"),
    ("GET", "/api/v1/auth/oidc/login"),      # public, pre-session (Task 11)
    ("GET", "/api/v1/auth/oidc/callback"),
    ("POST", "/api/v1/users"),               # first-run bootstrap; enforcer-checked inline
    ("GET", "/api/v1/events/stream"),        # session-authed SSE
    ("GET", "/api/v1/entitlements"),         # any-role flag map (doc 05: "any")
    ("GET", "/api/v1/api-keys"),             # self-service (Task 12)
    ("POST", "/api/v1/api-keys"),
    ("DELETE", "/api/v1/api-keys/{key_id}"),
}

# Mutations a viewer session IS allowed: own-account self-service only.
VIEWER_SELF = {
    ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/auth/totp"),
    ("POST", "/api/v1/auth/totp/enroll"),
    ("POST", "/api/v1/auth/totp/confirm"),
    ("DELETE", "/api/v1/auth/totp"),
    ("DELETE", "/api/v1/auth/sessions/{sid}"),
    ("POST", "/api/v1/api-keys"),            # key is capped by the viewer's own role
    ("DELETE", "/api/v1/api-keys/{key_id}"),
    ("POST", "/api/v1/users"),               # 403s inline anyway post-bootstrap; listed
                                             # because its DENIAL is enforcer-driven, and
                                             # a viewer probing it must see 403: asserted
                                             # separately below, not skipped
}


def _has_authz_marker(dependant) -> bool:
    for d in dependant.dependencies:
        if getattr(d.call, "__proxploy_authz__", None) or _has_authz_marker(d):
            return True
    return False


def test_every_route_carries_an_authorize_dependency(tmp_path):
    app = make_app(tmp_path)
    missing = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/v1"):
            continue
        for method in route.methods - {"HEAD", "OPTIONS"}:
            if (method, route.path) in UNGOVERNED:
                continue
            if not _has_authz_marker(route.dependant):
                missing.append((method, route.path))
    assert not missing, f"routes without authorize(): {sorted(missing)}"


def test_a_viewer_session_cannot_mutate_anything(tmp_path, csrf_header):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        h = csrf_header(c)
        c.post("/api/v1/users", json={"email": "o@x.io",
               "password": "correct-horse-battery"}, headers=h)   # owner bootstrap
        c.post("/api/v1/auth/login", json={"email": "o@x.io",
               "password": "correct-horse-battery"}, headers=h)
        c.post("/api/v1/users", json={"email": "v@x.io", "role": "viewer",
               "password": "correct-horse-battery"}, headers=h)
        c.post("/api/v1/auth/logout", headers=h)
        c.post("/api/v1/auth/login", json={"email": "v@x.io",
               "password": "correct-horse-battery"}, headers=h)

        checked = 0
        for path, methods in c.app.openapi()["paths"].items():
            probe = path
            for name in re.findall(r"{(\w+)}", path):
                probe = probe.replace(f"{{{name}}}",
                                      "start" if name == "action" else "1")
            for method in methods:
                m = method.upper()
                if m not in ("POST", "PUT", "PATCH", "DELETE"):
                    continue
                if (m, path) in VIEWER_SELF:
                    continue
                r = c.request(m, probe, headers=h, json={})
                checked += 1
                assert r.status_code == 403, (
                    f"viewer got {r.status_code} from {m} {path}: {r.text}")
        assert checked >= 50   # the walk really walked the mutating surface

        # And the one VIEWER_SELF row that must still deny:
        r = c.post("/api/v1/users", json={"email": "x@x.io", "role": "viewer",
                   "password": "correct-horse-battery"}, headers=h)
        assert r.status_code == 403
```

- [ ] **Step 2: Run it.** Every failure is a real conversion gap from Tasks 2–6, fix the route, not the test. The allowlist entries referencing Tasks 8–12 routes are inert until those routes exist (the walk only sees registered routes).
- [ ] **Step 3: Full backend suite**, then **Commit**; `test(authz): every-route casbin coverage + viewer-cannot-mutate invariants`.

## Task 8: TOTP service + enrollment routes

**Files:**
- Create: `backend/proxploy/services/totp.py`
- Modify: `backend/proxploy/api/auth.py` (three routes)
- Test: `backend/tests/test_totp.py`

**Interfaces:**
- Consumes: `app.state.secretstore` (`SecretStore.encrypt(bytes) -> bytes` / `.decrypt(bytes) -> bytes`, read `proxploy/secretstore.py` to confirm the exact method names before writing code), `services.authn.hash_password`/`verify_password` (argon2; reused for recovery codes, no new crypto), `pyotp`.
- Produces, for Task 9:
  - `totp.start_enrollment(db, secretstore, user) -> dict`: `{"secret", "otpauth_uri", "recovery_codes": [10 raw codes]}`; persists the blob with `totp_enabled` still False.
  - `totp.confirm(db, secretstore, user, code: str) -> bool`: flips `totp_enabled=True` on a valid code.
  - `totp.verify_login(db, secretstore, user, code: str) -> bool`: accepts a current TOTP code (`valid_window=1`) **or** an unused recovery code, burning it (blob rewritten without its hash).
  - `totp.disable(db, user) -> None`: clears `totp_secret_enc` + `totp_enabled`.

Blob format (the zero-migration decision from Global Constraints):
`users.totp_secret_enc = secretstore.encrypt(json.dumps({"secret": <base32>, "recovery": [<argon2 hash> × 10]}).encode())`.
Recovery codes are `"-".join(secrets.token_hex(2) for _ in range(2))` → e.g. `a3f1-9c02` (4+4 hex, ~32 bits; brute-force is closed off by the login rate limit and 5-attempt pending burn in Task 9, not by code length alone; state this in a comment), 10 of them, argon2-hashed via the same `PasswordHasher` as passwords.

- [ ] **Step 1: Write the failing tests**, `test_totp.py`:
  - `test_enrollment_returns_secret_uri_and_ten_codes_once`: returns 10 codes; DB holds neither raw codes nor raw secret (`users.totp_secret_enc` decrypts to hashes only for `recovery`, and the ciphertext ≠ plaintext); `totp_enabled` still False.
  - `test_confirm_requires_a_valid_code`: wrong code → False + still disabled; `pyotp.TOTP(secret).now()` → True + enabled.
  - `test_verify_login_accepts_totp_code` / `test_verify_login_burns_a_recovery_code_exactly_once`, a recovery code works once, second use → False; other 9 still work.
  - `test_disable_clears_the_blob`.
  - Route tests through `make_app` + `TestClient`: enroll requires a session (401 anonymous, already enforced by `test_route_auth_invariant.py`, but assert the flow: enroll → confirm with the real `pyotp` code → `GET /auth/me` shows `"totp_enabled": true`); `DELETE /auth/totp` without the right password → 403, with it → disabled; audit rows `auth.totp.enroll` / `auth.totp.confirm` / `auth.totp.disable` written.
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** `services/totp.py` per the interface, then the routes in `api/auth.py`:
  - `POST /auth/totp/enroll` (session required, `Depends(get_current_user)`; also `Depends(require_entitlement("auth.totp"))` **after** it) → `start_enrollment` result. Re-enrolling before confirm overwrites the pending blob; re-enrolling while enabled → 409 ("disable first").
  - `POST /auth/totp/confirm {code}` → `{"ok": true}` or 400.
  - `DELETE /auth/totp {password}`: verify with `authn.verify_password`; an OIDC-only account (`password_hash IS NULL`) may pass a current TOTP code in the same field instead (comment why: doc 08 requires re-auth, and a password is the one thing an OIDC account doesn't have).
  - `/auth/me` response gains `"totp_enabled": user.totp_enabled`.
  - Add the three routes to `test_rbac_invariant.py`'s allowlists **only if not already present** (they are, Task 7 pre-listed them).
- [ ] **Step 4: Run** new tests + invariant suites + full suite. **Commit**: `feat(auth): TOTP enrollment with argon2-hashed one-time recovery codes`.

---

## Task 9: TOTP login step + session management routes

**Files:**
- Modify: `backend/proxploy/api/auth.py` (login flow + 3 routes), `backend/proxploy/config.py` (`totp_pending_ttl_s: float = 300.0`), `backend/proxploy/main.py` (`app.state.pending_totp = {}` in lifespan)
- Test: `backend/tests/test_auth_totp_login.py`, `backend/tests/test_sessions_api.py`

**Interfaces:**
- Produces, for the frontend (Task 17):
  - `POST /auth/login`: when the user has `totp_enabled`: **no cookie is set**; response is `{"totp_required": true, "pending": "<raw token>"}`.
  - `POST /auth/totp {pending, code}`: completes the login: sets the session cookie, returns the same `{"ok", "user"}` shape as password login. Rate-limited `10/minute` like login.
  - `GET /auth/sessions` → `[{id, ip, user_agent, created_at, last_seen_at, current: bool}]` (own sessions, live only).
  - `DELETE /auth/sessions/{sid}` → revoke one of my sessions (404 for another user's).

Pending-login store: `app.state.pending_totp: dict[str, tuple[int, datetime, int]]` mapping `sha256(raw)` → `(user_id, expires_at, attempts)`. Raw token = `secrets.token_urlsafe(32)`, hashed with `services.authn._th`. Max 5 attempts, then the entry is deleted (re-login required). Expired entries pruned on every access. `# ponytail: in-memory pending-2FA store, single-process app by design (in-process JobBackend); a restart mid-2FA costs one re-login. Move to a table if multi-worker ever lands.`

- [ ] **Step 1: Write the failing tests**
  - `test_auth_totp_login.py`: password login for a TOTP-enabled user returns `totp_required` and **no `pp_session` cookie**; wrong code → 401 and still no cookie; right code (`pyotp.TOTP(secret).now()`) → cookie + `/auth/me` works; a recovery code also completes login and is burned; a pending token is single-success (reuse after success → 401); 6th attempt → 401 even with the right code (entry burned); expired pending (monkeypatch `totp_pending_ttl_s=0`... pass `Settings(totp_pending_ttl_s=0)` through `make_app(tmp_path, totp_pending_ttl_s=0.0)`; `make_app` forwards `**overrides`) → 401; audit rows: `auth.login.totp_pending`, `auth.login` on completion, `auth.login` `result="error"` on a bad code.
  - `test_sessions_api.py`: two logins → `GET /auth/sessions` lists 2 with `current` on the right one; `DELETE` the other → it can no longer call `/auth/me`; deleting another user's session id → 404; revoked/expired rows absent from the list.
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement**, in `login`: after the password check and before `create_session`, branch on `user.totp_enabled`; write the pending entry and audit. New `POST /auth/totp` route (decorated `@limiter.limit("10/minute")`, the limiter counts per-IP like login): pop-or-decrement per the attempt rules, call `totp.verify_login`, then the exact `create_session` + `set_cookie` + audit block password login uses (extract those ~6 lines into a module-local `_issue_session(request, response, db, user)` helper so the two paths cannot drift). Sessions routes query `SessionRow` filtered `user_id=user.id, revoked_at IS NULL, expires_at > utcnow()`; `current` = row hash matches the presented cookie.
- [ ] **Step 4: PUBLIC entry**, `POST /auth/totp` has no session dependency (it IS the second half of acquiring a session), so an anonymous probe with `json={}` gets a 422/401, not the 401 `test_route_auth_invariant.py` demands of non-PUBLIC routes. Add `("POST", "/api/v1/auth/totp")` to that test's `PUBLIC` set with the reason comment "second factor of login; pre-session by definition".
- [ ] **Step 5: Run** new tests + `test_auth.py` (existing login tests must be untouched, a user without TOTP logs in exactly as before) + invariant suites + full suite. **Commit**: `feat(auth): TOTP login step with attempt-capped pending store; session list/revoke`.

---

## Task 10: OIDC service: config, discovery, PKCE, validation, JIT

**Files:**
- Create: `backend/proxploy/services/oidc.py`
- Modify: `backend/proxploy/main.py` (`app.state.oidc_states = {}`)
- Test: `backend/tests/test_oidc.py` (service-level half; route half comes in Task 11)

**Interfaces:**
- Consumes: `settings` service (`get_setting`/`set_setting`), `app.state.secretstore`, `httpx`, `authlib.integrations.httpx_client.AsyncOAuth2Client` + `OAuth2Client`, `joserfc`.
- Produces, for Task 11:
  - `oidc.config(db, secretstore) -> dict | None`: `{"issuer", "client_id", "client_secret"}` from settings keys `oidc.issuer`, `oidc.client_id`, `oidc.client_secret.enc` (Fernet-decrypted); `None` unless all three present.
  - `oidc.set_config(db, secretstore, issuer, client_id, client_secret) -> None` / `oidc.clear_config(db) -> None`.
  - `async oidc.begin(app, db, redirect_uri: str) -> str`: returns the IdP authorization URL; stores `{state: (code_verifier, nonce, expires_at)}` in `app.state.oidc_states` (TTL 600 s, pruned on access; same single-process `ponytail:` note as Task 9).
  - `async oidc.complete(app, db, state: str, code: str, redirect_uri: str) -> User`: pops the state (single-use), exchanges the code, validates the ID token, returns the (possibly just-created) user. Raises `OIDCError(str)` on any failure, the route turns it into one generic redirect, never a leaky message.

Implementation requirements (all verified, see Global Constraints):
- Discovery: `GET {issuer}/.well-known/openid-configuration` via `httpx.AsyncClient(transport=app.state.oidc_transport)`, `app.state.oidc_transport` defaults to `None` (real network) and is the **test seam**: tests set it to `httpx.ASGITransport(app=fake_idp)`. Cache the metadata + JWKS on `app.state` keyed by issuer; refetch JWKS once on a `kid` miss.
- Authorization URL: `OAuth2Client(client_id, client_secret, redirect_uri=..., code_challenge_method="S256").create_authorization_url(auth_endpoint, nonce=nonce, code_verifier=verifier, scope="openid email profile")`; **`code_verifier=` must be passed here or PKCE is silently absent** (verified trap).
- Exchange: `AsyncOAuth2Client(...).fetch_token(token_endpoint, code=code, code_verifier=verifier, state=state)` (same transport seam).
- ID-token validation, joserfc only: `claims = jwt.decode(id_token, KeySet.import_key_set(jwks)).claims`, then `JWTClaimsRegistry(iss={"essential": True, "value": issuer}, aud={"essential": True, "value": client_id}, exp={"essential": True}, sub={"essential": True}).validate(claims)`, then `claims.get("nonce") == stored_nonce` or raise. A signature/claims/nonce failure is `OIDCError`, never a 500.
- JIT provisioning: look up `User` by `(oidc_issuer=issuer, oidc_sub=claims["sub"])` (the `ux_users_oidc` index). Absent → require `claims["email"]` (missing → `OIDCError("IdP returned no email claim")`, honest refusal, not a synthetic address); if a **local** user already owns that email → `OIDCError` ("account exists with password login", no silent account linking, that's a takeover vector); else create `User(email=..., display_name=claims.get("name"), oidc_issuer=..., oidc_sub=..., password_hash=None)`, membership in `default_team` with role from setting `oidc.default_role` (default `"viewer"`, validated against `ROLE_ORDER` at write), and `sync_user` the enforcer. `is_active=False` → `OIDCError`.

- [ ] **Step 1: Write the failing service tests** (using the Task 11 fixture, build `tests/fakes/oidc.py` in THIS task so both halves test against it; see Task 11 Step 1 for its code, write it here): begin() URL contains `state`/`nonce`/`code_challenge`/`code_challenge_method=S256`; complete() with the fake's code → creates a user with correct `(issuer, sub)`, role viewer, default team; second login reuses the same row (no duplicate); tampered `state` → `OIDCError`; wrong-nonce token → `OIDCError`; token signed by a different key → `OIDCError`; local-email collision → `OIDCError`; missing email → `OIDCError`; `oidc.default_role` setting honoured.
- [ ] **Step 2: Run to verify failure**, **Step 3: implement**, **Step 4: run + full suite**, **Step 5: Commit**, `feat(oidc): PKCE code flow service with joserfc validation and JIT provisioning`.

---

## Task 11: OIDC routes + mock IdP round-trip

**Files:**
- Create: `backend/tests/fakes/oidc.py` (if not landed in Task 10)
- Modify: `backend/proxploy/api/auth.py` (four routes), `backend/proxploy/api/meta.py` (`oidc` boolean in onboarding), `backend/tests/test_route_auth_invariant.py` (PUBLIC entries)
- Test: `backend/tests/test_oidc.py` (route half)

**Interfaces (frontend, Task 17):**
- `GET /auth/oidc/login` → 307 redirect to the IdP; **404** (`{"error": "oidc_not_configured"}`) when unconfigured or entitlement `auth.oidc` is off, deliberately not 403, because this route is PUBLIC and `test_route_auth_invariant.py` forbids anonymous 403s.
- `GET /auth/oidc/callback?state&code` → on success: session cookie + 307 to `/`; on any `OIDCError`: 307 to `/login?error=oidc` (no detail in the URL) + audit row `auth.login` `result="error"` with `params={"via": "oidc"}`.
- `GET /auth/oidc/config`: `authorize("settings", "manage")` for GET, PUT and DELETE alike (it is the "own flow" that `PATCH /settings`' `.enc` refusal points at, and settings are admin-owned in doc 05) → `{"issuer", "client_id", "configured": bool}`, never the secret.
- `PUT /auth/oidc/config {issuer, client_id, client_secret}` → stores via `oidc.set_config`; audit `oidc.config.set` (params redacted by key names, `client_secret` matches `REDACT_SUBSTRINGS`).
- `DELETE /auth/oidc/config` → `oidc.clear_config`; audit.
- `GET /meta/onboarding` gains `"oidc": <configured && entitled>` so the login page knows to show the SSO button pre-session.

Mock IdP fixture, `tests/fakes/oidc.py`:

```python
"""In-process mock OIDC provider. HONEST SUBSTITUTE (doc 10 DoD says "a real
Authelia"; there is no browser, no Authelia, and no live IdP on this machine):
this serves a real discovery document, enforces PKCE S256 end-to-end
(challenge stored at /authorize, verifier checked at /token), and signs real
RS256 ID tokens verified by the app against this fixture's real /jwks, the
protocol is fully exercised; only the third-party implementation is absent."""
import base64
import hashlib
import secrets

from fastapi import FastAPI, Form, HTTPException
from joserfc import jwt
from joserfc.jwk import RSAKey

ISSUER = "https://idp.test"


def make_idp(*, sub="alice-1", email="alice@example.com", name="Alice",
             client_id="proxploy", client_secret="s3cret"):
    key = RSAKey.generate_key(2048, {"alg": "RS256", "kid": "test-1"})
    codes: dict[str, dict] = {}   # code -> {nonce, code_challenge}
    idp = FastAPI()

    @idp.get("/.well-known/openid-configuration")
    def discovery():
        return {"issuer": ISSUER,
                "authorization_endpoint": f"{ISSUER}/authorize",
                "token_endpoint": f"{ISSUER}/token",
                "jwks_uri": f"{ISSUER}/jwks",
                "id_token_signing_alg_values_supported": ["RS256"]}

    @idp.get("/jwks")
    def jwks():
        return {"keys": [key.as_dict(private=False)]}

    @idp.get("/authorize")
    def authorize(state: str, nonce: str, code_challenge: str,
                  code_challenge_method: str, redirect_uri: str,
                  client_id_q: str | None = None):
        assert code_challenge_method == "S256"
        code = secrets.token_urlsafe(16)
        codes[code] = {"nonce": nonce, "challenge": code_challenge}
        return {"redirect": f"{redirect_uri}?state={state}&code={code}"}

    @idp.post("/token")
    def token(code: str = Form(...), code_verifier: str = Form(...),
              grant_type: str = Form("authorization_code"), **_kw):
        entry = codes.pop(code, None)
        if entry is None:
            raise HTTPException(400, "bad code")
        digest = hashlib.sha256(code_verifier.encode()).digest()
        if base64.urlsafe_b64encode(digest).rstrip(b"=").decode() != entry["challenge"]:
            raise HTTPException(400, "PKCE verifier mismatch")
        id_token = jwt.encode(
            {"alg": "RS256", "kid": "test-1"},
            {"iss": ISSUER, "aud": client_id, "sub": sub, "email": email,
             "name": name, "nonce": entry["nonce"], "exp": 9999999999},
            key)
        return {"access_token": "at", "token_type": "Bearer",
                "id_token": id_token}

    idp.state.key = key           # tests that need a wrong-key token
    idp.state.codes = codes
    return idp
```

(The fake's `/token` also receives `client_id`/`client_secret`/`redirect_uri` form fields from Authlib, accept and ignore via `**_kw`; if FastAPI rejects unknown form fields, take a `Request` and read `await request.form()` instead; the implementer verifies which shape works and keeps whichever runs.)

- [ ] **Step 1: Write the failing route tests**, the full round-trip through the app: `PUT /auth/oidc/config` as owner (fake transport installed via `client.app.state.oidc_transport = httpx.ASGITransport(app=idp)`) → anonymous `GET /auth/oidc/login` returns 307, parse `state`/`nonce`/`code_challenge` from the `Location` URL → call the fake IdP's `/authorize` directly (TestClient on the idp app) → `GET /auth/oidc/callback?state&code` → 307 to `/`, `pp_session` cookie set, `GET /auth/me` returns the JIT-provisioned viewer. Plus: unconfigured login → 404; replayed state → redirect to `/login?error=oidc`; secret never appears in `GET /auth/oidc/config` nor in any audit row (query `audit_events.params` for the raw secret string, must be absent).
- [ ] **Step 2: Run to verify failure**, **Step 3: implement routes** (PUBLIC additions to `test_route_auth_invariant.py`: the two `/auth/oidc/*` GET routes, each with a reason comment; note the 404-not-403 rule above), **Step 4: run** new tests + both invariant suites + full suite. **Step 5: Commit**: `feat(oidc): login/callback/config routes; PKCE round-trip proven against an in-process mock IdP`.

## Task 12: API keys: bearer resolution, scopes, routes

**Files:**
- Create: `backend/proxploy/api/apikeys.py`
- Modify: `backend/proxploy/api/deps.py` (`get_current_user` bearer path + `require_key_scope` folded into `authorize`), `backend/proxploy/api/__init__.py`
- Test: `backend/tests/test_apikeys.py`

**Interfaces:**
- Produces, for Task 13 and the frontend (Task 19):
  - `POST /api-keys {name, scopes?: [str], expires_at?: iso}` → 201 `{"id", "name", "prefix", "scopes", "expires_at", "key": "ppk_…"}`, **the only response that ever contains the raw key**. Session required; entitlement `api.tokens` (after auth). Scope strings validated against `^(read|[a-z]+:write)$` with the prefix of `:write` scopes required to be a resource name in `PERMISSIONS`, anything else 422s at creation, so an unknown scope can never exist to be misinterpreted later.
  - `GET /api-keys` → my keys: `[{id, name, prefix, scopes, expires_at, last_used_at, revoked_at, created_at}]`; no hash, no raw key.
  - `DELETE /api-keys/{key_id}` → sets `revoked_at` (own key; 404 for another user's, an admin revokes by deactivating the user, not by touching keys, keep it simple).
  - Bearer auth: any request with `Authorization: Bearer ppk_…` resolves through `api_keys` instead of the cookie. On success `request.state.api_key` is the row (Task 13's audit shim and the scope check read it).

Key material: `raw = "ppk_" + secrets.token_urlsafe(32)`; `prefix = raw[:8]` (doc 04: "first 8 chars"); `key_hash = hashlib.sha256(raw.encode()).hexdigest()` (doc 04 says SHA-256, a 256-bit random token needs no slow hash, unlike a password; comment this so nobody "upgrades" it to argon2 and adds 100 ms to every API call).

Bearer path in `get_current_user` (replaces the current body):

```python
def get_current_user(request: Request, db=Depends(get_db)) -> User:
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        raw = auth[7:]
        if not raw.startswith("ppk_"):
            raise HTTPException(401, "authentication required")
        if not request.app.state.entitlements.enabled("api.tokens"):
            raise HTTPException(401, "authentication required")  # feature off = no bearer auth, and a 403 here would leak flag state to an anonymous caller
        row = (db.query(ApiKey)
               .filter_by(key_hash=hashlib.sha256(raw.encode()).hexdigest())
               .one_or_none())
        now = utcnow()
        if (row is None or row.revoked_at
                or (row.expires_at and row.expires_at < now)):
            raise HTTPException(401, "authentication required")
        user = db.get(User, row.user_id)
        if not user or not user.is_active:
            raise HTTPException(401, "authentication required")
        if row.last_used_at is None or (now - row.last_used_at).total_seconds() > 60:
            row.last_used_at = now      # rate-limited write, one per key-minute
            db.commit()
        request.state.api_key = row
        return user
    raw = request.cookies.get(request.app.state.settings.session_cookie)
    user = resolve_session(db, raw) if raw else None
    if not user:
        raise HTTPException(401, "authentication required")
    return user
```

Scope enforcement, add to `authorize()`'s `dep`, immediately **before** the casbin check (a key can only narrow its user, never widen):

```python
key = getattr(request.state, "api_key", None)
if key is not None and key.scopes:            # empty scopes = full user rights (doc 04)
    allowed = ("read" in key.scopes and action == "read") or \
              (f"{resource}:write" in key.scopes)
    if not allowed:
        write_audit(db, actor_type="api_key", actor_id=key.id,
                    action=f"{resource}.{action}", result="denied",
                    ip=request.client.host if request.client else None)
        raise HTTPException(403, "key scope does not allow this")
```

(`"apps:write"` in doc 04's example is plural; the resource name is `app`. Scope grammar uses the **matrix resource name**, `app:write`, `vm:write`, `backup:write`; and the create route 422s anything not in the matrix, so the doc-04 example string is normalised, note it in the route docstring.)

- [ ] **Step 1: Write the failing tests**, `test_apikeys.py`:
  - create → 201 with `ppk_` key shown once; row in DB has sha256 hash, not the raw; list shows prefix only; the raw key string appears in **no** audit row (`audit_events.params` scan).
  - bearer works: fresh `TestClient` **without cookies**, `GET /api/v1/hosts` with the header → 200; no CSRF header needed on a bearer POST (middleware exemption).
  - revoked → 401; expired (`expires_at` in the past) → 401; deactivated user (`is_active=False`) → 401; garbage `ppk_` token → 401; entitlement `api.tokens` off → 401.
  - key is capped by the user's role: a viewer's unscoped key still gets 403 from `PATCH /hosts/1` (the casbin check runs after the scope check).
  - scopes: key with `["read"]` → GET 200, POST lifecycle 403 with `actor_type="api_key"` denial audit; key with `["app:write"]` → app lifecycle 202/409-path works, `POST /schedules` 403; creating a key with scope `"gizmo:write"` or `"admin"` → 422.
  - `last_used_at` stamped once per minute (two immediate calls → one write; freeze via monkeypatched `utcnow`?, simpler: assert it is non-None after the first call and unchanged after an immediate second).
- [ ] **Step 2: Run to verify failure**, **Step 3: implement** (`api/apikeys.py` routes use plain `Depends(get_current_user)` + `Depends(require_entitlement("api.tokens"))`, self-service, pre-listed in Task 7's allowlists), register the router. **Step 4: run** new tests + both invariant walks + `test_auth.py` (cookie path untouched) + full suite. **Step 5: Commit**: `feat(api-keys): scoped revocable bearer tokens, sha256 at rest, capped by casbin role`.

---

## Task 13: Token-authed REST drive + OpenAPI surface audit

**Files:**
- Create: `backend/tests/test_rest_token_drive.py`, `backend/tests/test_openapi_surface.py`
- Test: themselves. No production code except fixes for whatever the audit finds.

**Part A, the DoD clause "a CI script drives the product entirely through token-authed REST":** a pytest module (runs in CI with the normal suite = it IS the CI script) that, after a one-time cookie bootstrap (owner + API key creation are the documented cookie-first steps), **discards all cookies** and performs every remaining step with `Authorization: Bearer` only:

- [ ] **Step 1: Write it**, sequence, all bearer-authed against `make_app(tmp_path, fake=FakePVE(...))`:
  1. `POST /hosts` (FakePVE behind `make_fake_factory`) → 201; `GET /hosts` shows it connected.
  2. `POST /apps/adopt` for a CT the fake reports → 201 (drives the same identity machinery an install would, with no SSH needed).
  3. `POST /apps/{id}/start` → 202; poll `GET /jobs/{id}` to `succeeded` (use `app.state.jobs.wait` via TestClient's portal? No, poll the route with a small loop + timeout, staying strictly REST).
  4. `POST /schedules` (a `backup.sync` nightly) → 201; `GET /schedules` lists it.
  5. `POST /alert-rules` → 201; `GET /alerts` → 200.
  6. `GET /audit` shows the actions above.
  7. `DELETE /api-keys/{id}` (bearer revoking itself) → 200, and the very next bearer call → 401.
  Assert throughout: `client.cookies` presented on these calls is empty (build a second `TestClient(app)`, never log in on it, pass only the header), every response < 500.
- [ ] **Step 2: Run; this is expected to PASS immediately** if Tasks 2–12 are right; every failure it finds is a real integration bug (e.g. a route that quietly assumed a CSRF cookie). Fix the route, note the fix in the commit message.

**Part B, the DoD clause "OpenAPI surface audited so the full REST API covers everything the UI does":**

- [ ] **Step 3: Write `test_openapi_surface.py`**, extracts every literal path the frontend passes to `api(...)` and asserts each exists in the OpenAPI schema:

```python
"""Doc 10 Phase 8: '/api/docs covers everything the UI does'. Mechanical
audit: every path the frontend hands to api() must resolve to a documented
route. Template params (`${x}`) match any {param} segment. SSE/WebSocket
URLs are consumed by EventSource/WebSocket constructors, not api(), so this
regex covering api() calls covers exactly the REST surface, which is the
claim being audited."""
import re
from pathlib import Path

from tests.support import make_app

FRONTEND_SRC = Path(__file__).resolve().parents[2] / "frontend" / "src"
CALL_RE = re.compile(r"""api(?:<[^>(]*>)?\(\s*[`'"](/[^`'"?\s]*)""")


def _normalise(path: str) -> tuple:
    return tuple("{}" if seg.startswith("${") else seg
                 for seg in path.split("/") if seg)


def test_every_frontend_api_call_is_a_documented_route(tmp_path):
    app = make_app(tmp_path)
    documented = set()
    for path in app.openapi()["paths"]:
        assert path.startswith("/api/v1")
        documented.add(tuple("{}" if s.startswith("{") else s
                             for s in path.removeprefix("/api/v1").split("/") if s))
    calls = {}
    for f in FRONTEND_SRC.rglob("*.ts*"):
        for m in CALL_RE.finditer(f.read_text()):
            calls.setdefault(_normalise(m.group(1)), []).append(
                (f.relative_to(FRONTEND_SRC), m.group(1)))
    missing = {k: v for k, v in calls.items() if k not in documented}
    assert calls, "regex matched nothing; the extractor itself broke"
    assert not missing, f"UI calls without a documented route: {missing}"
```

- [ ] **Step 4: Run it.** Any hit is a genuine doc-10 gap, fix by adding/correcting the route (or, if the frontend path is simply wrong, that is a real UI bug to fix on the frontend side). Also assert once, manually, that `GET /api/docs` and `GET /api/openapi.json` serve 200 on a running `make_app` client; add that one-liner test here too.
- [ ] **Step 5: Full suite, Commit**; `test(api): token-only REST product drive + frontend↔OpenAPI surface audit`.

---

## Task 14: Migration preflight: client calls, strategy pick, estimates, route

**Files:**
- Modify: `backend/proxploy/services/proxmox.py` (two methods), `backend/tests/fakes/pve.py` (three additions), `backend/proxploy/config.py` (`migrate_assumed_bps: float = 80e6`)
- Create: `backend/proxploy/services/migrate.py` (preflight half)
- Modify: `backend/proxploy/api/apps.py` (preflight route, **above the wildcard**, per the WARNING comment at `apps.py:522`)
- Test: `backend/tests/test_migrate_preflight.py`

**Interfaces:**
- `ProxmoxClient.cluster_status(self) -> list[dict]`: `GET /cluster/status` (`self._connect().cluster.status.get()`), wrapped in the standard try/`_wrap` pattern every other method uses. A standalone node returns rows without a `{"type": "cluster"}` entry.
- `ProxmoxClient.migrate_guest(self, kind: str, node: str, vmid: int, params: dict) -> str`: `POST /nodes/{node}/{lxc|qemu}/{vmid}/migrate` → UPID (Task 15 uses it).
- `FakePVE`: `cluster_status_rows: list[dict]` attribute + `self.cluster.status = _AttrLeaf(self, "cluster_status_rows")` (reuse the lazy-attr leaf); `_MigrateLeaf` recording `(kind, node, vmid, params)` into `fake.migrations` and minting a UPID via `_record_action`; and:

```python
def make_addressed_factory(fakes: dict[str, "FakePVE"]):
    """Two-host tests: one FakePVE per host, keyed by the hostname the
    client's factory is called with (ProxmoxClient passes host=<hostname>)."""
    def factory(**kwargs):
        fake = fakes[kwargs["host"]]
        if fake.fail:
            raise ConnectionError("fake PVE unreachable")
        fake.kwargs = kwargs
        return fake
    return factory
```

- `services/migrate.py` preflight (blocking; the route calls it in-request like `hosts.py::test_host` does its probe):

```python
STRATEGY_CLUSTER = "cluster"            # same PVE cluster: native migrate
STRATEGY_SHARED = "shared_storage"      # both hosts see one backup storage
STRATEGY_TRANSFER = "transfer"          # vzdump + SFTP stream + restore

def preflight(app, db, app_row, target_host_id: int) -> dict
```

returning (shape consumed by Task 15's handler and Task 21's dialog):

```python
{
  "strategy": "...",                     # one of the three
  "source": {"host_id", "host_name", "node", "ctid"},
  "target": {"host_id", "host_name", "node", "ctid"},   # target ctid: nextid, or same for cluster
  "shared_storage": "pbs-ds" | None,
  "transfer_bytes": int | None,          # newest Backup row size for this guest,
                                         # else maxdisk from /cluster/resources
  "estimate_basis": "last_backup" | "allocated_disk",
  "est_downtime_s": int,                 # honest: whole stop→start window
  "est_note": "assumes ~80 MB/s sustained; measured downtime is reported by the job",
  "capacity_ok": bool,                   # target free space ≥ 1.2 × transfer_bytes (None-safe)
  "warnings": [ ... ],                   # always includes the IP/DHCP/MAC note for
                                         # non-cluster strategies; capacity_ok=False adds one
  "downtime_statement": "This is stop → backup → transfer → restore → start. "
                        "Expect roughly N minutes of downtime.",   # doc 11 §2 verbatim honesty
}
```

Strategy decision, in order: (1) both hosts' **live** `cluster_status()` contain a `{"type": "cluster"}` row with the same `name` → `cluster` (do NOT read `hosts.cluster_name`, verified: nothing in the codebase ever writes that column; preflight also refreshes it on both Host rows as a side effect, which un-deadens the column honestly); (2) else both hosts' `cluster_storage()` rows share a storage `storage` name with `type` in `{"pbs", "nfs", "cifs"}` and `"backup"` in its content string → `shared_storage`; (3) else `transfer`, which additionally requires a `dir`-type storage with backup content on each side (`cluster_storage()` rows carry `path` for dir storages); missing → the preflight returns `"strategy": "transfer"` with `capacity_ok=False`-style blocking warning `"no dir-type backup storage on <side>"` and the migrate route refuses to enqueue while `blockers` is non-empty (add `"blockers": [str]` to the shape; empty = go). Downtime estimate: `cluster` → `est_downtime_s = 30` with `est_note` "offline migrate; restart-scale downtime, network-bound" ; `shared_storage` → `2 × transfer_bytes / migrate_assumed_bps` (backup pass + restore pass); `transfer` → `3 ×` (dump, copy, restore). Self-migration: `selfguard.is_self(db, "app", app_id)` → include `"self_target": true` in the response (the route-level typed-confirm gate lands with the migrate route in Task 15).

- Route: `POST /api/v1/apps/{app_id}/migrate/preflight {target_host_id}` → 200 dict; `authorize("app", "migrate", scope_of=scope_app())` + `require_entitlement("migrate.preflight")`; 404 unknown app, 409 target==source or target not `connected`, 502 on `ProxmoxError` (the `hosts.py` probe precedent). **Registered above the `/{app_id}/{action}` wildcard.**

- [ ] **Step 1: Write the failing tests**, `test_migrate_preflight.py` with `make_addressed_factory`: two standalone fakes sharing a PBS storage name → `shared_storage`, `transfer_bytes` from a seeded `Backup` row, `est_downtime_s == 2*size/80e6` (int), warnings include the IP note; same-cluster rows on both → `cluster` + `hosts.cluster_name` now populated; no shared storage but dir storage both sides → `transfer` with 3× estimate; no dir storage on target → non-empty `blockers`; capacity: target `storages()` row with `avail < 1.2×size` → `capacity_ok is False`; route-level: viewer → 403, operator → 403, admin → 200; unknown target → 409; wildcard not shadowing (calling the route returns preflight JSON, not the lifecycle 422; the exact regression the WARNING comment predicts).
- [ ] **Step 2: verify failure → Step 3: implement → Step 4: run + invariant walks + full suite → Step 5: Commit**, `feat(migrate): preflight with live cluster/shared-storage detection and honest downtime estimates`.

---

## Task 15: `migrate.app` handler: cluster + shared-storage paths, migrate route

**Files:**
- Modify: `backend/proxploy/services/migrate.py` (handler half), `backend/proxploy/main.py` (import for handler registration `# noqa: F401`), `backend/proxploy/api/apps.py` (migrate route, above the wildcard)
- Test: `backend/tests/test_migrate_job.py`, `backend/tests/test_migrate_api.py`

**Interfaces:**
- `HANDLERS["migrate.app"]`: params `{"app_id", "target_host_id", "strategy", "target_ctid", "shared_storage": str|None}` (strategy/ctid/storage come from a fresh in-handler preflight, not trusted from the route; state can change between preflight and run; the route passes only app_id + target_host_id).
- Route: `POST /api/v1/apps/{app_id}/migrate {target_host_id, confirm?}` → 202 `{"job": …, "preflight": …}`; `authorize("app","migrate", scope_of=scope_app())` + `require_entitlement("migrate.cross_host")`; refuses while `preflight["blockers"]` non-empty (409 listing them); self-guard: when `is_self(db, "app", app_id)`, require `confirm == app.name` with the exact 409 `self_target` shape `enqueue_lifecycle` uses (`apps.py:499-510`); audit via `enqueue_and_audit(..., action="app.migrate")`.

Handler sequence (shared-storage path; cluster path replaces steps 3–5 with one `migrate_guest` call):

```python
async def migrate_app(ctx, params):
    app_ = ctx.backend.app
    # 0. blocking re-preflight in a thread; JobFailed on blockers
    # 1. ctx.log the honest downtime statement verbatim
    # 2. t0 = utcnow(); if source CT running: stop it (guest_action) + await_task
    #    -> downtime clock starts at the stop, doc 11 §2
    # 3. vzdump on source: {"vmid": ctid, "storage": shared, "mode": "stop",
    #    "compress": "zstd"} + await_task            (skip for cluster path)
    # 4. find the new archive: target client's storage_content(target_node,
    #    shared, content="backup"), newest row whose parse_volid() ==
    #    ("ct", source_ctid): backupjobs.parse_volid is the reusable parser
    # 5. restore on target: restore_guest("lxc", target_node, new_ctid,
    #    {"ostemplate": volid, "restore": 1}) + await_task
    #    cluster path instead: migrate_guest("lxc", src_node, ctid,
    #    {"target": target_node}) awaited on the SOURCE node, ctid unchanged
    # 6. start on target + await_task; health check: poll target
    #    cluster_resources() until the CT reports running (deadline 60s,
    #    JobFailed with rollback guidance on miss)
    # 7. downtime_s = (utcnow() - t0).total_seconds(): MEASURED, the DoD number
    # 8. repoint identity: app_row.host_id = target_host_id; app_row.ctid =
    #    new_ctid; commit. Source CT is left STOPPED AND INTACT (doc 11 §2:
    #    "renamed/flagged, not destroyed... single-click rollback = start the
    #    source again"); result carries the rollback instruction.
    # 9. bus.publish resource delta; return {"strategy", "downtime_s",
    #    "source_ctid", "target_ctid", "volid", "rollback":
    #    "source CT <ctid> on <host> is stopped but intact: start it to roll back"}
```

Failure ordering is the safety property (doc 11 §2 "not data loss, if we sequence correctly"): any `JobFailed` before step 8 leaves the source authoritative and the app row untouched, the handler must never repoint before the target passes its health check. A failure AFTER the target started but before repoint aborts with both CTs stopped-or-running and an explicit `ctx.log` line naming which CT is which; it must not delete anything, ever (no cleanup of the target CT on failure; say so in the transcript instead: "target CT <id> left for inspection").

- [ ] **Step 1: Write the failing handler tests**, `test_migrate_job.py` over `make_job_app` + `make_addressed_factory` (pattern: `tests/test_app_update_job.py` for running a handler inside `asyncio.run`): shared-storage happy path (fake source records vzdump; seed target fake's `content_by_storage` with the archive row; assert restore posted on target with `restore:1`, start recorded, `apps` row repointed to target host + new ctid, `result["downtime_s"] > 0`, source got stop but never delete); cluster path (both fakes same cluster name → `migrate_guest` recorded on source, ctid unchanged, no vzdump); restore fails (`task_exit="restore error"` on target fake) → `JobFailed`, app row untouched, transcript names the intact source; health-check timeout → same; a stopped source skips the stop call but downtime still measured.
- [ ] **Step 2: verify failure → Step 3: implement handler + route** (route tests in `test_migrate_api.py`: 202 + job row kind `migrate.app`; blockers → 409; self-target without confirm → 409 `self_target`; viewer/operator → 403; wildcard-shadowing regression check). **Step 4: run + invariant walks + full suite → Step 5: Commit**: `feat(migrate): cluster-native and shared-storage migration with measured downtime and intact-source rollback`.

---

## Task 16: The vzdump + SFTP transfer path

**Files:**
- Create: `backend/proxploy/executor/transfer.py`
- Modify: `backend/proxploy/services/migrate.py` (strategy 3 in the handler), `backend/tests/fakes/ssh.py` (fake SFTP)
- Test: `backend/tests/test_migrate_transfer.py`

**Interfaces:**
- `executor/transfer.py`: the **only** new module allowed to import asyncssh (`scripts/check_executor_isolation.py` enforces the boundary; `executor/` is its allowed zone, and doc 08 §4 names migration as an executor use-case):

```python
async def sftp_copy(connect_factory, *, src: dict, dst: dict,
                    src_path: str, dst_path: str,
                    on_progress) -> int:
    """Stream one file host→host through the Proxploy process (the two nodes
    have no credentials for each other; that is the point of this product).
    src/dst: {"host", "private_key_pem", "pinned_fingerprint",
    "on_new_fingerprint"}, the same arguments executor/ssh.py's
    default_connect_factory takes. 4 MiB chunks; on_progress(bytes_done)
    per chunk; returns total bytes. Callers outside executor/ resolve keys
    via SSHExecutor.run_for_host's pattern, this module gains a matching
    `sftp_copy_for_hosts(sessionmaker, secretstore, src_host_id, ...)`
    wrapper so raw key bytes never leave executor/ (doc 08 §4)."""
```

  Implementation: two `await connect_factory(...)` connections, `start_sftp_client()` on each, `async with s.open(src_path, "rb") as fsrc, d.open(dst_path, "wb") as fdst:` chunk loop. Verify asyncssh's actual SFTP file API against the installed 2.x (`python -c "import asyncssh, inspect..."`) before writing, `SFTPClient.open` returning an async file object with `read(n)`/`write(b)` is the expected shape.
- Handler strategy 3, between vzdump and restore: source archive volid → physical path = dir-storage `path` from `cluster_storage()` + `/dump/` + filename (the volid's `backup/…` tail); `sftp_copy_for_hosts` streams it to the target's dir-storage dump path; the target `restore_guest` then references `local:backup/<filename>`-style volid on the target storage (dir storages index `dump/` content on listing). `ctx.progress` maps copied bytes to 10–80%.
- `tests/fakes/ssh.py`: give `FakeSSHConnection` a `start_sftp_client()` returning a `FakeSFTP` over an in-memory `{path: bytes}` dict shared between the two fake connections via the test, with async `open()` supporting the read/write chunk protocol.

- [ ] **Step 1: failing tests**, `test_migrate_transfer.py`: `sftp_copy` unit (bytes land intact, progress called, total returned); handler end-to-end on two no-shared-storage fakes + fake SFTP (archive "copied", restore posted on target from the target-local volid, downtime measured, repoint happened); missing dir storage → `JobFailed` naming the side; SSH host-key mismatch surfaces as `JobFailed` (raise `SSHHostKeyMismatch` from the fake factory).
- [ ] **Step 2: verify failure → Step 3: implement → Step 4:** run + `test_isolation_lint.py` (transfer.py must pass the executor-isolation check) + full suite. **Step 5: Commit**: `feat(migrate): vzdump+SFTP transfer path for hosts with no shared storage`.

## Task 17: Frontend: login TOTP step + SSO button

**Files:**
- Create: `frontend/src/api/account.ts` (start here; Task 18 extends it), `frontend/src/tests/login-totp.test.tsx`
- Modify: `frontend/src/routes/login.tsx` (and `src/components/LoginForm.tsx` if the form logic lives there, read both first)

**Interfaces (consumed from Tasks 9/11):**
- `POST /auth/login` may return `{totp_required: true, pending: string}` instead of `{ok, user}`.
- `POST /auth/totp {pending, code}` completes it.
- `GET /meta/onboarding` now includes `oidc: boolean`.
- OIDC entry point is a plain browser navigation: `window.location.href = '/api/v1/auth/oidc/login'`, **not** an `api()` fetch (it's a 307 redirect chain ending back at `/`).

- [ ] **Step 1: Write the failing tests**, `login-totp.test.tsx` (mock `../api/client` per the `channels.test.tsx` pattern): submitting credentials whose response is `totp_required` swaps the password form for a single code input + "Use a recovery code" hint text (same input, recovery codes are entered in the same field); submitting the code calls `api('/auth/totp', …)` with `{pending, code}` and navigates on success; a 401 shows "code was not accepted, try again or use a recovery code" and keeps the pending token; the SSO button renders only when the (mocked) onboarding query says `oidc: true`, and is an `<a href="/api/v1/auth/oidc/login">` (assert the href, don't click through jsdom navigation).
- [ ] **Step 2: Run to verify failure** (`npm test -- login-totp`), **Step 3: implement** (state machine in the login route: `mode: 'password' | 'totp'` + stored pending token; on `?error=oidc` in the URL show "single sign-on failed, try again or use a password"), **Step 4:** `npm test` full run ≥ 157, `npm run build` clean. **Step 5: Commit**: `feat(ui): TOTP login step and SSO entry on the login page`.

---

## Task 18: Frontend: Security card (TOTP + sessions) in Settings

**Files:**
- Modify: `frontend/src/api/account.ts`
- Create: `frontend/src/components/TotpCard.tsx`, `frontend/src/components/SessionsCard.tsx`
- Modify: `frontend/src/routes/settings.tsx` (two new cards, using the local `Card` helper at `settings.tsx:25`)
- Test: `frontend/src/tests/totp.test.tsx`, `frontend/src/tests/sessions.test.tsx`

- [ ] **Step 1: failing tests**, 
  - `totp.test.tsx`: card shows "Enable two-factor" when `/auth/me` says `totp_enabled: false`; clicking enroll calls `POST /auth/totp/enroll` and renders the secret, the otpauth URI, and all ten recovery codes with copy affordance and the warning "these are shown once; store them now" (**no QR code, deliberate, zero-dependency: authenticator apps accept manual key entry; a QR needs a new npm dependency this phase doesn't take.** Render the otpauth URI as selectable monospace text); entering the confirm code calls `/auth/totp/confirm` and flips the card to enabled-state with a "Disable" flow that asks for the password.
  - `sessions.test.tsx`: lists sessions from `GET /auth/sessions`, marks `current`, "Sign out" per row calls the DELETE, "Sign out everywhere else" loops every non-current row.
- [ ] **Step 2–4:** verify failure → implement → `npm test` + build. Gate the TOTP card on `ent.has('auth.totp')` after the entitlements query resolves (Global Constraints frontend rule). **Step 5: Commit**: `feat(ui): security settings, TOTP enrollment with one-time recovery codes, session management`.

---

## Task 19: Frontend: API keys card

**Files:**
- Create: `frontend/src/api/apikeys.ts`, `frontend/src/components/ApiKeysCard.tsx`, `frontend/src/tests/apikeys.test.tsx`
- Modify: `frontend/src/routes/settings.tsx`

- [ ] **Step 1: failing tests**, create form (name, optional scopes as checkboxes: `read` plus one `<resource>:write` per matrix resource, hardcode the resource list in the component with a comment pointing at `services/authz.py::PERMISSIONS`; expiry optional date via native `<input type="date">`); the 201 response's `key` renders exactly once in a "copy now, shown once" panel and is dropped from state on dismiss; list shows `prefix + '…'`, scopes, last-used; revoke calls DELETE and refetches; card gated on `ent.has('api.tokens')`; a hint line links `/api/docs` ("the full REST API, everything this UI does").
- [ ] **Step 2–4:** verify failure → implement → `npm test` + build. **Step 5: Commit**: `feat(ui): API keys, scoped creation with show-once secret, revocation`.

---

## Task 20: Frontend: Teams admin UI + host team assignment

**Files:**
- Create: `frontend/src/api/teams.ts`, `frontend/src/components/TeamsCard.tsx`, `frontend/src/tests/teams.test.tsx`
- Modify: `frontend/src/routes/settings.tsx`; host edit surface (read `src/components/HostForm.tsx` + the Hosts card in settings first, add a team `<select>` to whichever place PATCHes a host today, or add a minimal per-host team select in the Hosts card if none does)

- [ ] **Step 1: failing tests**, teams list with member counts; create team (owner-only affordance, render the form regardless, let a 403 surface the API's answer in an error toast: role-hiding in the UI is cosmetics, enforcement is the backend's job; but DO gate the whole card on `ent.has('teams.rbac')`); expanding a team lists members with role `<select>` (viewer/operator/admin/owner) wired to `PUT /teams/{id}/members/{userId}`; "Add member" pulls `GET /users`; remove member; host team select PATCHes `{team_id}`.
- [ ] **Step 2–4:** verify failure → implement → `npm test` + build. **Step 5: Commit**: `feat(ui): teams administration and host team assignment`.

---

## Task 21: Frontend: migration dialog

**Files:**
- Create: `frontend/src/api/migrate.ts`, `frontend/src/components/MigrateDialog.tsx`, `frontend/src/tests/migrate.test.tsx`
- Modify: the app-detail / apps-page action surface (read `src/routes/apps.tsx` and how `RestoreDialog.tsx`/`CloneDialog.tsx` are launched, copy that pattern)

- [ ] **Step 1: failing tests**, opening the dialog for an app lists target hosts (existing hosts query, minus the app's own); choosing one fires `POST /apps/{id}/migrate/preflight` and renders: the strategy in plain words ("These hosts share a cluster, native migration" / "Via shared storage X" / "Backup, transfer, restore"), `transfer_bytes` humanised, the est downtime + the verbatim `downtime_statement`, every warning, and blockers as a red list with the confirm button disabled while any exist; confirming fires the migrate POST and swaps to the existing `JobLog` component streaming the job; a `self_target` 409 renders the typed-confirm input (reuse `ConfirmSelfDialog.tsx` if its API fits, read it first); the completed job's `result.downtime_s` is displayed as "actual downtime: Ns" next to the estimate, the honest before/after pair.
- [ ] **Step 2–4:** verify failure → implement (dialog gated on `ent.has('migrate.cross_host')`) → `npm test` + build. **Step 5: Commit**: `feat(ui): cross-host migration dialog with preflight, honest downtime, and live job log`.

---

## Task 22: DoD verification, notes, doc amendments, buildlog

**Files:**
- Create: `backend/dod_verify_phase8.py` (throwaway, already gitignored; `e8093d1` gitignores `dod_verify` scripts), `docs/notes/phase-8-scale.md`
- Modify: `docs/03-technology-dependency-map.md`, `docs/04-data-model.md`, `buildlog.md`

- [ ] **Step 1: `dod_verify_phase8.py`**, one script, four checks, each printing `OK`/`FAIL` and exiting non-zero on any failure, driving real routes via `tests.support.make_app` + `FakePVE` + fakes (the Phase 5–7 pattern):
  1. **Viewer cannot mutate**: run the Task 7 walk in-process (import and call the test function, or re-implement the loop) and print the count of mutating routes checked.
  2. **OIDC round-trips**: the Task 11 flow against `tests/fakes/oidc.py`, printing the JIT-provisioned user; the output line MUST read `OK (against local mock IdP, no Authelia on this machine; protocol-complete substitute)`.
  3. **Non-clustered migration**: two `FakePVE`s, no shared storage, fake SFTP: preflight (print the estimate), migrate job to completion (print `result["downtime_s"]`; the "accurate downtime shown" clause is this number existing and being measured, plus the estimate having been shown at preflight), assert the app row repointed and the source CT never deleted.
  4. **Token-authed REST drive**: the Task 13 Part A sequence, printing each step, no cookies.
  Run it twice; identical output both times.
- [ ] **Step 2: `docs/notes/phase-8-scale.md`**, same skeleton as `docs/notes/phase-7-operate.md`: what shipped per subsystem; findings that contradicted the docs (**at minimum**: the in-memory-enforcer amendment vs doc 04/08's `casbin_rules`-adapter wording; the recovery-codes-in-blob decision vs doc 04's "TOTP seed" cell; `hosts.cluster_name` was never populated before preflight; `authlib.jose` deprecated in favour of joserfc; doc 04's `"apps:write"` scope example normalised to `app:write`); residual limitations (**at minimum**: no real IdP / no browser on this box; token-authed audit rows attribute the acting user, `request.state.api_key` exists but the ~76 pre-existing `write_audit` call sites still write `actor_type="user"`, with the per-key evidence being scope-denial rows + `last_used_at`; upgrade path: thread an `actor_of(request)` helper through the call sites; OIDC/TOTP pending state is in-memory single-process; migration leaves the source CT for manual cleanup by design); gate numbers table (DoD script, backend count vs the 663 floor, frontend count vs 157, build, lint, `alembic heads` still `2330a95b98d2`); commit range.
- [ ] **Step 3: doc amendments**, 
  - `docs/03-technology-dependency-map.md`: AuthZ/OIDC/TOTP rows go from `†` to **verified 2026-08-05 @ casbin 1.43.0 (Apache-2.0) / Authlib 1.7.2 (BSD-3-Clause) / pyotp 2.10.0 (MIT)**, with the transitive rows `simpleeval` (MIT) and `joserfc` (BSD-3-Clause) added the way Phase 7 added `tzlocal`; the AuthZ row's justification notes the in-memory enforcer satisfying the `Authorizer` seam (no sqlalchemy-adapter dependency).
  - `docs/04-data-model.md`: `users.totp_secret_enc` cell → "Fernet-encrypted JSON: TOTP seed + argon2-hashed one-time recovery codes (amendment, Phase 8, 2026-08-05; see notes)"; `casbin_rules` section gains the amendment paragraph (table retained for forward compatibility, unused; enforcer is in-memory over `team_members`, the authoritative store).
  - `buildlog.md`: the phase entry in the established format.
- [ ] **Step 4: run everything**, DoD script ×2, full backend suite, full frontend suite + build + lint, `alembic heads`. Record the real numbers in the notes doc, never projected ones.
- [ ] **Step 5: Commit**, `docs(phase-8): DoD verification, notes, dependency-map and data-model amendments, buildlog`.

---

## Self-Review

Checked after writing, against doc 10's Phase 8 section and the shaping constraints:

1. **Scope coverage**: OIDC login (Tasks 10–11, 17) + TOTP with recovery codes (8–9, 17–18) ✓; RBAC on every route with owner/admin/operator/viewer, teams as casbin domains with host/app/VM scoping, team admin UI (1–7, 20) ✓; API tokens scoped/revocable/hashed + OpenAPI surface audit (12–13, 19) ✓; cross-host migration: preflight with capacity/storage mapping/size-time estimate, cluster-native when clustered, PBS-or-shared-storage backup/restore and vzdump+transfer when not, explicit downtime messaging (14–16, 21) ✓. All four DoD clauses have an executable proof (7, 11, 13, 15/16) plus the consolidated script (22). Nothing beyond doc 10's list was added; the only doc-05 rows pulled in beyond the literal scope list are `GET /users` (the team admin UI cannot exist without a member picker) and `PATCH /hosts.team_id` (host scoping cannot exist without an assignment path).
2. **Placeholder scan**: every task carries either full code or an exact contract (signatures, shapes, status codes) plus the named oracle ("existing tests are the oracle") for mechanical conversions; the two spots where the implementer must verify a library detail before coding (`remove_filtered_grouping_policy`, asyncssh SFTP file API) say exactly what to check and what the fallback is.
3. **Type consistency**: `authorize(resource, action, *, scope_of)` and `dep.__proxploy_authz__` are used identically in Tasks 2, 7, 12; `enforce(enforcer, db, user, resource, action, *, team_id=None)` identical in 1, 2, 5; the preflight dict shape in Task 14 is what Tasks 15 and 21 consume; `make_addressed_factory(fakes_by_host)` identical in 14–16; pending-store tuple shape `(user_id, expires_at, attempts)` only referenced in Task 9.
4. **Honesty**: the two unprovable DoD fragments ("real Authelia", real hardware migration) are declared as substitutes in Global Constraints, restated in the fixture docstring (Task 11), the DoD script's own output (Task 22 Step 1.2), and the notes' residual-limitations list. The audit-attribution simplification is declared as a residual limitation with its upgrade path, not hidden.




