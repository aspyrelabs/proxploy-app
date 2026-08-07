# Phase 9b (Onboarding, empty states, error states, light theme): verification notes

> Doc 10's Phase 9 DoD says a stranger *"completes onboarding, installs an
> app, creates a VM, schedules a backup"*; four clauses no test had ever
> executed through the UI before this phase. 9a shipped how the product gets
> onto a box and updates itself; 9b is what a stranger sees once it's there:
> a wizard that survives a reload, failures that name what actually failed,
> lists that never lie about being empty, and a light theme nobody had run a
> single assertion against. Design spec:
> `docs/superpowers/specs/2026-08-06-phase-9b-onboarding-polish-design.md`.

## What shipped, per subsystem

**A Proxmox error you can act on (Task 1).** `ProxmoxError` gained a `kind`
`unreachable`, `auth`, `tls_fingerprint`, `refused`, `unknown`; classified
once in `_wrap`'s `_classify()` by substring match, because proxmoxer and
requests expose no typed failures for these. `POST /hosts/probe` and
`POST /hosts` both return `502 {"error": kind, "detail": scrubbed}` instead
of one flat string, so a wrong token and a closed firewall stop reading
identically to the wizard.

**SSH verification, not an honor system (Task 2).** `POST
/hosts/{id}/ssh/verify` runs `true` over the enrolled key
(`SSHExecutor.run_for_host`) and only then sets `HostCredential.
ssh_verified_at`. Failure kinds, `no_key`, `host_key_mismatch`,
`unreachable`, `timeout`, `command_failed`; are as specific as Task 1's.
Migration `01f962e7a491_ssh_verified_at_on_host_credentials.py` adds the
column; `alembic heads` reports it as the sole head.

**`ssh_pending` on `/meta/onboarding` (Task 3).** True whenever a host has an
`ssh_key` credential with `ssh_verified_at IS NULL`. This is the field the
rebuilt wizard derives its step from.

**Four states, one component (Tasks 4, 5).** `EmptyState` gained an optional
`action` slot; `QueryState` wraps a `UseQueryResult` and renders loading,
error, empty and data as four different things. Before it, the codebase
spelled every list as `(data ?? []).map`, so a failed fetch and an honestly
empty list were the same pixels, the regression `query-state.test.tsx`'s
third case exists to catch (`isPending` also goes false on error, so a naive
`!data` guard shows "Loading…" forever after a hard failure too).

**Every collection site converted (Tasks 6, 7, 8).** 25 page-level lists, 15
`<select>` option lists (which can't hold a `QueryState`, so they get a
disabled placeholder option on error/loading instead), and the two
detail-page sites (`routes/vms.tsx`, `routes/apps.tsx`) that rendered
`EmptyState title="Loading…"` forever on a hard error. The dead `useJob`
hook (no callers anywhere in `frontend/src`) was deleted in the same pass.
Three queries that weren't lists but lied reassuringly on failure, 
`useEntitlements` (gained an `unknown` flag; `has()` stays fail-closed on
purpose, since failing open would be a security bug), `useTotpStatus`
(`TotpCard`'s plan gate sat on "Loading…" forever because `isPending` goes
false on error too), and `useSummary` (cluster's rings now show `?` instead
of a calm, wrong 0%); were fixed the same way, keyed off `HealthFooter.tsx`
as the one place in the codebase that already did this right.

**Finding F1, closed (Task 9).** No route-level `errorComponent` meant a 5xx
during route load white-screened the app with TanStack's own fallback, which
sets colours via inline `style={}` and so ignores the theme entirely.
`RouteError.tsx` is now both `defaultErrorComponent` (router-wide) and the
shell route's own `errorComponent`, and distinguishes an unreachable backend
(`TypeError: Failed to fetch`) from a broken app. `shell.tsx`'s `beforeLoad`
had a second, related bug: its `/auth/me` catch redirected to `/login` on
*any* failure, so a reachable-but-500ing backend read as "not signed in"
rather than surfacing through the new `errorComponent`. Now only a 401
redirects; anything else re-throws.

**The two hardcoded colours (Task 11).** `UsageBar.tsx` and `StatRings.tsx`
both inlined `#1d2733` outside the token system. Fixed to `bg-elev` /
`var(--elev)`, with a new static guard (`no-hardcoded-colors.test.ts`)
walking every `.tsx`/`.ts` file for a literal hex in `style=`, `stroke=` or
`fill=`. The guard's first real run found a **third offender the manual
survey missed**, `StoreCard.tsx` inlined the same two gradient stops
`UsageBar.tsx` already exported as `CPU_GRADIENT`, just at a different
angle. Not a new colour, a duplicated literal; deduped into a
`STORE_GRADIENT` constant rather than widening the allowlist.

**The wizard derives its own step (Task 12).** `step` was `useState(0)`.
Reloading mid-wizard left `beforeLoad` seeing `complete: false` and
remounted at step 0, but the admin already existed and a session cookie
was already set, so resubmitting hit `create_user`'s non-first-run path and
409'd, surfaced as *"Could not create the admin account (password: 12+
characters)"*: the user was told their password was bad when what actually
happened is they'd already succeeded. `stepFrom(ob)` now derives the step
from `GET /meta/onboarding` on every render; a local `advanced` override
only ever moves forward within one session.

**Skippable host step, honest errors (Task 13).** `HostForm`'s `errText`
used to read `.detail`/`.title`/`.message` and throw the status away, so
every failure was one flat red line. It now maps Task 1's five `kind`
values to copy that names a specific fix, and a "Skip for now" button lets a
stranger reach the dashboard without a host, the shell's guard already only
checks `onboarding.complete`, never `host_added`, so no backend change was
needed.

**The authorize step stops taking your word for it (Task 14).** "I have
authorized it" was replaced with "Verify access", which calls Task 2's
endpoint and only advances on success; a mismatch or a still-failing key
surfaces specific copy instead of silently trusting a click.

**A backend the e2e suite can onboard against (Task 15).**
`tests/e2e_server.py` serves the real app with `FakePVE` + `FakeSSHConnection`
installed via `create_app(proxmox_factory=…, ssh_factory=…)`; no env-var
backdoor in `main.py`, per the global constraint. `POST /hosts`
unconditionally probes a live Proxmox API, so without this the stranger
journey could not start at all. `tests/` is already excluded from the
release tarball by 9a's `build_release.sh`, confirmed still true.

**The stranger journey (Task 16).** `frontend/e2e/journey.spec.ts` drives
the real UI through all four Phase 9 DoD clauses for the first time ever:
create the admin, add + SSH-verify a host, install an app from the Store,
create a VM, schedule a backup, each step ending in a visible assertion
that the thing exists afterward, not just that a button was clickable. See
**Findings** below for what it broke on first contact.

**The light-theme leg (Task 17).** `frontend/e2e/light-theme.spec.ts`
asserts, via `getComputedStyle`, that none of nine pages resolve to the
dark-only literal `rgb(29, 39, 51)` (`#1d2733`) the two Task 11 bypass bugs
used. This is a machine-checkable proxy for "light theme QA pass", there
are no human eyes on this box. Sign-in/navigation helpers were extracted
into `e2e/helpers.ts` and shared with `smoke.spec.ts` rather than copied a
third time.

**E2E gated in CI (Task 18).** Phase 8 wrote a Playwright harness that
nothing ran; `.github/workflows/ci.yml` gained an `e2e` job (checkout,
Python 3.12, Node 22, a real `backend/.venv` since `playwright.config.ts`'s
`webServer` hardcodes that path, `playwright install --with-deps chromium`,
`npx playwright test`) so these clauses can't quietly rot after passing
once.

## Findings: the phase's real output

**Two production bugs, both found by executing things, both hidden by test
fixtures supplying what the product itself never wrote:**

- **SSH passed a URL where asyncssh needs a hostname** (`fa5cce5`).
  `Host.address` is stored as a full `https://10.0.0.5:8006` URL and was
  handed straight to `asyncssh` as the `host` argument, `://` and an
  embedded port are not valid hostname characters. App install, app update,
  SSH verify, and both legs of cross-host migration **could never have
  worked against a real Proxmox node**, despite shipping across Phases 4, 7
  and 8 with passing DoDs every time. Nothing caught it because every SSH
  test's fake either ignores the `host` argument or, in two
  `test_migrate_transfer.py` cases, keys itself by the full URL; those two
  cases were passing for the wrong reason, matching the also-unnormalized
  code. Fixed once at the two chokepoints every caller already funnels
  through, `SSHExecutor.run()` and `executor/transfer.py::sftp_copy()`, 
  with a new `normalize_ssh_host()` helper (pure `urllib.parse`, same
  approach `services/proxmox.py::ProxmoxClient._connect` already uses for
  the HTTPS side) rather than at each of the four call sites individually.

- **`Host.node_name` was write-never** (`fa4c795`). `POST /hosts` has no way
  to learn a node's name, PVE's `/version` doesn't carry one, and
  `ingest_cycle()` never persisted it either; only `tests/support.py`'s
  `seed_host_row` test helper ever set it by hand. `GET /cluster/nodes` and
  the VM-create wizard's node picker both read that column directly, so a
  host created through the real onboarding flow offered no node to pick, 
  **a real user could not create a VM.** Found by the journey harness on its
  first real run, building the "create a VM" step. Fixed in
  `proxploy/pollers/__init__.py`: the first poll cycle that sees a node now
  writes it once, mirroring `main.py`'s own self-`ctid` write-once pattern
  (never clobbering an operator's manual choice on a multi-node cluster).
  Two new regression tests in `test_poller_ingest.py` cover the write and
  the no-clobber case.

**Smaller findings, each worth its line:**

- `TotpCard`'s plan gate sat on "Loading…" forever when `useEntitlements`
  failed, `isPending` goes `false` on error too, so a naive `!data` guard
  never resolves. Fixed alongside `useEntitlements` gaining an `unknown`
  flag.
- `SessionsCard`'s `Array.isArray(sessions.data)` guard existed only to
  paper over an incomplete test mock (`settings.test.tsx`'s generic `api()`
  fallback returned a lone object for any unhandled `GET`). Once
  `SessionsCard` renders through `QueryState`, the guard is gone and the
  mock was fixed to answer the path for real instead.
- The hardcoded-colour guard's first real run found a third offender
  (`StoreCard.tsx`) the manual survey that scoped this task had missed, 
  see Task 11 above.
- Task 17 found two real e2e races while building the light-theme leg:
  Playwright's `test.beforeAll` runs once per **worker**, not once per
  **file**, so `fullyParallel` scheduling let concurrent `seedAdmin()` calls
  double-post `POST /users` against the one shared dev backend, fixed with
  an `mkdirSync`-based cross-process lock in `helpers.ts`. And
  `POST /login` is rate-limited 10/minute per source IP
  (`proxploy/api/auth.py`), every request in the run shares one machine's
  IP, so nine independent UI sign-ins blew through it; `light-theme.spec.ts`
  now signs in through the real UI exactly once and hands every test the
  resulting session cookie.

**Open follow-up, stated plainly rather than silently left:** Task 1 gave
`api/hosts.py` a `kind` taxonomy for `ProxmoxError`. A repo-wide check found
**22** other `except ProxmoxError` sites across
`api/{consoles,backups,network,storage,vms,apps}.py` (consoles 3, backups 1,
network 8, storage 5, vms 3, apps 2) that still format `str(e)` straight
into an opaque `502`/`409`, none were in this phase's scope, and they are
now inconsistent with the taxonomy `hosts.py` has. (The plan's own survey
estimated 24; a direct `grep -n -A2 "except ProxmoxError"` over those six
files during this verification counted 22, recorded here as the actual
number, not the projection.)

## Residual limitations, stated plainly

- **No real Proxmox node.** The journey (Task 16) runs against `FakePVE` +
  `FakeSSHConnection` (`tests/e2e_server.py`), so it proves the product's own
  logic, routing and UI; not behaviour against real hardware. This phase is
  itself direct evidence of why that gap matters: running the fake-backed
  journey for the first time found two defects (`Host.address` vs. asyncssh,
  `Host.node_name` write-never) that had shipped through three prior phases'
  passing DoDs specifically *because* every test fixture supplied what the
  real product never wrote. The gap doesn't just mean "unproven against
  hardware", it actively hides real defects until something executes the
  real path.
- **Computed-style assertions are not visual review.** `light-theme.spec.ts`
  proves no element resolves to the one literal two known bugs used; "ugly
  but correct", bad contrast, misaligned spacing, an awkward but
  token-correct colour, passes it without complaint. **The light theme has
  not been seen by a human on this branch.**
- **The DoD script's onboarding check tests the contract, not the code.**
  `dod_verify_phase9b.py`'s check 4 reimplements `stepFrom` in Python and
  drives it through the four `GET /meta/onboarding` states. That proves the
  API returns the four booleans the wizard needs and that the intended
  mapping is coherent; it does **not** execute the real TypeScript
  `stepFrom` in `routes/onboarding.tsx`, so the two could drift apart and
  this check would still pass. The real function is covered by
  `src/tests/onboarding.test.tsx` and end-to-end by `journey.spec.ts`; the
  DoD check is a third, weaker angle and should not be read as more.
- **Environment quirks the journey hit, both worked around rather than
  fixed upstream:** this box's Chromium reports the deprecated timezone
  alias `Asia/Calcutta`, which its minimal tzdata has no backward-compat
  link for, `journey.spec.ts`'s schedule step overwrites the
  browser-derived default with `UTC` rather than depending on the sandbox's
  tzdata. And React Query's global `staleTime: 15_000` (`main.tsx`) can
  serve a stale cache against fresh backend state, the VM-create step in
  the journey does a hard `page.reload()` before trusting `GET
  /cluster/nodes`, because a direct `page.request.get()` bypasses the cache
  but a UI navigation does not.

## Gate numbers

All run and recorded directly in this session, none projected.

| Gate | Result |
|---|---|
| Backend suite | **827 passed, 2 skipped, 4 deselected** (baseline entering the phase: 810), `pytest tests/ -q -m "not pve_integration and not e2e"` |
| Frontend suite | **268 passed across 43 files** (baseline 205 across 37), `npx vitest run --no-file-parallelism` |
| Frontend build | clean |
| Frontend lint | exit 0, 30 warnings, 0 errors, pre-existing warning classes only |
| Playwright e2e | **11 passed** (baseline 1), `npx playwright test` (smoke + journey + 9 light-theme) |
| Migrations | `alembic heads` = **`01f962e7a491`**, one head. **One migration this phase** (`ssh_verified_at` on `host_credentials`, Task 2); unlike 9a, which shipped zero |
| `dod_verify_phase9b.py` | all four checks OK, exit 0, run twice, byte-identical both times |

The DoD script's four checks: (1) the stranger journey via a real Chromium
run of `journey.spec.ts` against fake PVE/SSH; (2) `query-state.test.tsx`'s
four cases, proving data/empty/error/loading render as four different
things; (3) `light-theme.spec.ts`'s nine page assertions; (4) a from-scratch
walk of `GET /meta/onboarding` through all four wizard states
(admin-only → host-added+ssh-pending → verified → complete), checked against
a Python re-implementation of the frontend's `stepFrom`.

Commit range: `a7bbf3d..fa4c795` (design spec through the last implementation
commit; this note's own commit follows).
