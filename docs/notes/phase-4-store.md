# Phase 4 (Store) — verification notes

## What shipped, per subsystem

**SSH executor + host-key TOFU pinning** — `backend/proxploy/executor/`
(`ssh.py`: `SSHExecutor`, `SSHHostKeyMismatch`, `default_connect_factory`,
`run_for_host`; `keys.py`: `get_ssh_private_key`, the only function allowed
to decrypt an SSH private key). `Host.ssh_host_key_fingerprint` column
(migration `f691da7ec537`). First connect to a host pins its host key
fingerprint; every later connect must match or the connection is rejected
and closed. `scripts/check_executor_isolation.py` (wired in Phase 1, dormant
until this phase) mechanically forbids any module outside `proxploy/executor/`
from importing `asyncssh` or referencing `get_ssh_private_key` by name —
enforced by an AST walk, not a convention.

*Corrected in the final-review fix wave (Critical #1B):* `SSHExecutor.run`
passed its `env` dict to asyncssh's `create_process(env=…)`, which sends each
variable as an SSH protocol `env` channel request. Stock OpenSSH `sshd`
silently discards every variable not listed in its `AcceptEnv` directive, and
that directive is empty by default (only `LANG`/`LC_*` survive on most builds).
So on a default-configured Proxmox node, `MODE`, `PHS_SILENT` and every `var_*`
override vanished before `build.func` ever saw them, with no error anywhere —
i.e. the whole "export `MODE=default` for a genuinely unattended install"
design the Phase 4 spike's classifier work rests on did not work over a real
SSH connection. `run` now composes the vars as a `shlex.quote`d
`KEY=value … <command>` prefix on the command string itself and no longer
passes `env=` to `create_process` at all. Fixed in the executor rather than at
the `appstore.py` call site so every present and future caller gets it.

**Install-feasibility classifier** — `backend/proxploy/services/classifier.py`,
`classify_install_feasibility(ct_script, install_script) -> (bool, str | None)`.
Mechanical, not a guess: every community-scripts install script runs under
`catch_errors()`'s `set -Ee -o pipefail` + `trap ERR`, so an unconditional
`read`/`whiptail`/`dialog` prompt hard-aborts a non-interactive run rather than
defaulting. A prompt only counts as safe if it's env-var guarded or its `read`
short-circuits via `||`. Also rejects any `ct/*.sh` that doesn't call
`build_container` exactly once (multi-CT / docker-compose pattern).

*Corrected in the final-review fix wave (I1):* prompt detection used to
require a `-p`-shaped flag, so a bare `read ANSWER` or a `read -s PASS` — both
of which block on stdin identically — were missed entirely. It now flags any
`read` in command position, excluding the cases that plainly aren't prompts (a
`while read` stream loop, an explicit `<` redirect, a `| read` pipe, a `read -u`
non-stdin fd), matched against the line with quoted strings stripped so a `<`
inside prompt text (`<y/N>`) isn't read as a redirect. Guard detection used to
accept *any* `${X:-…}` within three lines above a prompt as a guard for that
prompt; it now requires the guard to name a variable the `read` itself assigns
into (case-insensitive), with the "any guard-shaped line counts" fallback kept
only for `whiptail`/`dialog`, which have no assignment target to correlate
against. The `||`-on-the-same-line exemption is unchanged. The real 24-slug
measurement below was re-run after this change and is still 15/24 — the
broadening caught no additional slug in this seed list, but it closes a real
false-negative class for future ones.

**CatalogSource ingest** — `backend/proxploy/services/catalog.py`
(`parse_ct_script`, `run_ingest`, `refresh_catalog` job handler),
`backend/proxploy/services/catalog_categories.py` (hand-maintained
slug→category map). Each refresh makes exactly ONE
`GET api.github.com/repos/community-scripts/ProxmoxVE/commits/main` call to
resolve the repo's HEAD commit SHA (unauthenticated, 60/hr/IP — one per
refresh job, never one per slug), then fetches
`ct/<slug>.sh` + `install/<slug>-install.sh` from
`raw.githubusercontent.com/community-scripts/ProxmoxVE/<sha>/…` — pinned to
that immutable commit, never to the moving `main` ref (doc 01 §3's
"community-scripts metadata API" framing was corrected during planning — no
such public bulk-read API exists; this is the concrete, verified mechanism).
Parses `APP=`/`# Source:`/`var_*` defaults, classifies feasibility, and
upserts into `catalog_entries` with `upstream_sha = <that commit>`.
Idempotency is keyed on that commit SHA: if the repo hasn't moved since the
last refresh, every slug short-circuits before any fetch.

*Corrected in the final-review fix wave (Critical #2, I2, I3):* ingest
previously fetched from `main` and tracked the `ct/` file's HTTP ETag as
`upstream_sha`. That was two bugs — the ETag never changed when only
`install/<slug>-install.sh` moved (so a real upstream change never
re-triggered a sync), and nothing tied the classified content to a fixed
commit, which is what made the `app_scripts` "pin" decorative (see the DoD
table's diff/pin row). `run_ingest` also used to let a single slug's
`JobFailed` (404, network hiccup) abort the whole batch, leaving every later
slug in the 24-slug list unprocessed; it now records `{slug, reason}` per
failure, continues, and returns `{synced, failed, upstream_sha}`, with each
failure narrated into the job transcript on `stderr`.

**Catalog API** — `backend/proxploy/api/catalog.py`: `GET /catalog`
(category/`q` filters), `GET /catalog/{slug}`, `POST /catalog/refresh`
(admin, fans out to ~24 GitHub fetches as one job). `Settings.catalog_slugs`
(`backend/proxploy/config.py`) is the 24-slug v1 seed list.

**Install job handler (`app.install`)** — `backend/proxploy/services/appstore.py`.
Resolves the catalog entry + host, refuses unsupported entries and entries with
no pinned `upstream_sha`, curls `ct/<slug>.sh` **from the pinned commit** and
runs it over SSH via `SSHExecutor.run_for_host` with output
streamed line-by-line into `ctx.log`, archives the script into `app_scripts`
(version 1, `source="upstream"`), creates the `App` row
(`slug = f"{catalog_slug}-{host_id}-{ctid}"` — corrected from the plan's
`{catalog_slug}-{ctid}` since `App.slug` has a global UNIQUE constraint and
two hosts could install the same app onto the same CTID).

*Corrected in the final-review fix wave (Critical #1A):* the operator's chosen
`ctid` was never sent to the remote script at all — `env` carried
`MODE`/`PHS_SILENT` and the `var_*` resource overrides but no `var_ctid`, so
`misc/build.func`'s `local requested_id="${var_ctid:-$NEXTID}"` silently
auto-picked the next free ID while the `App` row recorded whatever the operator
typed as fact. `env["var_ctid"] = str(ctid)` is now set last, so it also wins
over any `overrides` entry. Compounding it, none of that `env` dict reached the
remote process at all — see the `SSHExecutor` note above (Critical #1B).

**Install route + root-consent gate** — `POST /catalog/{slug}/install`
(`backend/proxploy/api/catalog.py`): two independent 400 gates, either can
fire first — explicit `consent: true` and an already-enrolled `ssh_key`
`HostCredential` — then entry-exists (404) and `installable` (400) checks,
then enqueues `app.install` and writes an audit row.

**Bulk adoption** — `POST /apps/adopt` (`backend/proxploy/api/apps.py`):
loops items, flushes per-item so a `(host_id, ctid)` collision raises
`IntegrityError` immediately (→ rollback of the *entire* batch → 409), one
`commit()` + one `write_audit` call per batch (never per item).

**Script view/edit/diff/history** — `GET/PUT /apps/{id}/script`,
`GET /apps/{id}/script/versions` (`backend/proxploy/api/apps.py`).
Note: `PUT` has an API but **no frontend caller** — the Config tab is
view-only, see "What was NOT verified".
`_diff_vs_upstream` computes a real `difflib.unified_diff` against the
catalog entry's current `raw.install_script` every time the script is read —
never cached — so an edited (or upstream-moved-on) script always shows a
fresh diff. `PUT` inserts a new `AppScript` version (`source="edited"`) and
audits `apps.script_edit`.

**Frontend** — `frontend/src/api/catalog.ts` (types + `useCatalog`/
`useCatalogEntry`/`useRefreshCatalog`/`useInstall` hooks), `StoreCard.tsx`,
`routes/store.tsx` (tile grid, category chips, real installable/unsupported
counts in the header), `InstallDialog.tsx` (host select, root-consent
checkbox gating a genuinely-`disabled` Install button, live `JobLog` once
the job starts), `BulkAdoptDialog.tsx` wired into `routes/apps.tsx`'s
discovered-CT panel, and the app detail Config tab (`ScriptPanel.tsx`:
**view-only** pinned-script + diff rendering, Task 14 — there is no edit UI,
see "What was NOT verified"). `routes/store.tsx` also fetches `/apps` and
derives each card's `installed` prop from the real set of installed
`catalog_slug`s (fix wave I6 — it was previously hardcoded `false`, which made
`StoreCard`'s own tested "Installed" disabled state unreachable in the real
page).

## DoD verification map (doc 10 Phase 4)

DoD: *"a real app (e.g. Immich) installs from the store onto a chosen host
as exactly one CT, with live log, archived log, audit row, and consent
step; catalog survives upstream being unreachable (serves cache with
staleness banner); an edited script shows its diff against upstream before
every run; the store reports the true installable count — no '300+
scripts' placeholder — with unsupported entries counted and shown
separately; a host with pre-existing CTs shows them in the discovered panel
and bulk-adopts cleanly."*

| Clause | Proving artifact | Verdict |
|---|---|---|
| Real app installs onto a chosen host as exactly one CT, with live log, archived log, audit row, and consent step | `dod_verify_phase4.py` (below): drives the real `POST /catalog/{slug}/install` → 202 → polled via `GET /jobs/{id}` to `succeeded`; asserts exactly one `App` row for `(host_id, ctid)`, one `AppScript` version=1 source=upstream, an `AuditEvent` row carrying the job id, `GET /jobs/{id}/events` containing the install narration line, and that `consent: false` 400s before any job is enqueued. Backend unit coverage: `tests/test_appstore_install.py` (3 tests), `tests/test_catalog_install_api.py` (3 tests) | PROVED |
| Catalog survives upstream being unreachable (serves cache with staleness banner) | `GET /catalog` reads only from the `catalog_entries` table (`backend/proxploy/api/catalog.py::list_catalog`) — it never calls upstream on a read, so an unreachable GitHub cannot affect a browse/search request; `run_ingest` (`backend/proxploy/services/catalog.py`) records a per-slug fetch failure and moves on without touching any other row, so a failed refresh leaves the existing cache exactly as it was, and a single bad slug no longer aborts the other 23 (`tests/test_catalog_ingest.py::test_one_bad_slug_does_not_abort_the_batch`). `::test_run_ingest_is_idempotent_on_an_unchanged_head_commit` covers the commit-SHA-cache half | PROVED (cache-survival) BY CODE INSPECTION + THE PER-SLUG-FAILURE TEST, NOT BY A DEDICATED "GITHUB DOWN" TEST — **and no staleness banner exists in the UI**: `synced_at` is returned by the API and typed in `frontend/src/api/catalog.ts` but never rendered anywhere in `routes/store.tsx`. Real, undelivered gap — see "What was NOT verified" |
| An edited script shows its diff against upstream before every run | `tests/test_app_script_api.py` (8 tests, real `difflib.unified_diff` output asserted, not stubbed): a matching script has no diff, an edited script's diff shows real `-`/`+` lines, and a script whose *upstream* moved on (the app's own content never changed) still surfaces a diff — proving the diff is computed live from current upstream every read, not cached at pin time. **The pin half of this clause was broken until the final-review fix wave and is now real:** ingest fetches, classifies and pins content from an immutable commit SHA, `catalog_entries.upstream_sha` records that commit, and `run_install` curls `ct/<slug>.sh` from *that same commit* — previously it archived the ingested `install_script` into `app_scripts` while separately curling a live, unpinned `…/main/{script_path}` (a *different* file, re-fetched at execution time), so the "pin" had zero effect on what actually ran. Proof: `tests/test_catalog_ingest.py::test_ingest_fetches_both_files_by_commit_sha_not_main` + `tests/test_appstore_install.py::test_install_sends_var_ctid_and_overrides_inline_on_the_command` (asserts the real composed command contains the SHA-pinned URL and no `/ProxmoxVE/main/`), and `::test_install_refuses_an_entry_with_no_pinned_commit` (never silently falls back to `main`) | PROVED for the diff, and for the pin **at one level only** — see the named residual gap under "What was NOT verified": the pinned `ct/*.sh` still `source`s `misc/build.func` and friends live from `main` at execution time |
| The store reports the true installable count — no "300+ scripts" placeholder — with unsupported entries counted and shown separately | `frontend/src/routes/store.tsx`: header line computes `installableCount`/`unsupportedCount` from the real `GET /catalog` response, not a hardcoded string. This task's own real 24-slug live classification run (see below) is the concrete proof the classifier produces a real, non-round number, not an estimate | PROVED — see the real 15/24 (62.5%) measurement below |
| A host with pre-existing CTs shows them in the discovered panel and bulk-adopts cleanly | `GET /apps/discovered` (Phase 2) feeds `routes/apps.tsx`'s discovered panel; `BulkAdoptDialog.tsx` (Task 13) posts `POST /apps/adopt`; backend: `tests/test_apps_adopt.py` (2 tests — creates rows for each item, 409s a duplicate `(host_id, ctid)` with the whole batch rolled back); frontend: `frontend/src/tests/adopt.test.tsx` | PROVED BY TEST, NOT BY BROWSER — see "What was NOT verified" |

### `dod_verify_phase4.py` — real output

Run against `tests.support.make_app` + a real `TestClient` (so the real
`JobBackend` runs the real `app.install` handler on the app's real event
loop) + `tests/fakes/ssh.py`'s `FakeSSHConnection` standing in for a live SSH
connection — no live PVE, no real SSH, matching the same no-PVE/no-Docker
verification approach Phases 1-3 used. Script was written to the repo root
of `backend/` (not committed — throwaway per this task's brief).

```
--- DoD clause: one real app installs onto a chosen host as exactly
    one CT, with live log, archived log, audit row, consent step ---
[PASS] consent=false is rejected (400) before any job is enqueued
[PASS] consent=true enqueues the install job (202)
  job id = 1
[PASS] job settles to succeeded (status=succeeded)
[PASS] live log (job_events, same rows GET /jobs/{id}/events serves as the archived transcript) contains the install narration line
[PASS] exactly one CT/App row created for (host_id=1, ctid=150) -- found 1
[PASS] script pinned into app_scripts as version=1 source=upstream
[PASS] an audit row exists carrying this job id
RESULT: PROVED -- one-CT install, script pinned, live+archived log, audit row, consent gate
```

## Real 24-slug live classifier measurement (not the spike's 493/559 estimate)

The spike (`docs/notes/phase-4-spike.md`) estimated 493/559 installable
across the *full* upstream community-scripts corpus. This plan's v1 seed
list (`Settings.catalog_slugs`) is only 24 slugs, so that full-corpus number
was never applicable here. To report a real, non-extrapolated figure, this
task fetched the real `ct/<slug>.sh` + `install/<slug>-install.sh` content
for all 24 configured slugs directly from
`raw.githubusercontent.com/community-scripts/ProxmoxVE/main` (real network,
no mocks) and called the real
`proxploy.services.classifier.classify_install_feasibility` on each pair —
the same function `catalog.py::_ingest_one` calls in production, not a
reimplementation.

| Slug | installable | unsupported_reason |
|---|---|---|
| redis | True | |
| postgresql | False | install script requires interactive input, no non-interactive entrypoint |
| mysql | False | install script requires interactive input, no non-interactive entrypoint |
| mariadb | False | install script requires interactive input, no non-interactive entrypoint |
| mongodb | False | install script requires interactive input, no non-interactive entrypoint |
| jellyfin | True | |
| plex | True | |
| immich | False | install script requires interactive input, no non-interactive entrypoint |
| homeassistant | True | |
| homebridge | True | |
| zigbee2mqtt | True | |
| grafana | True | |
| prometheus | True | |
| uptimekuma | True | |
| gitea | True | |
| n8n | True | |
| pihole | False | install script requires interactive input, no non-interactive entrypoint |
| adguard | True | |
| nginxproxymanager | True | |
| wireguard | False | install script requires interactive input, no non-interactive entrypoint |
| docker | False | install script requires interactive input, no non-interactive entrypoint |
| paperless-ngx | False | install script requires interactive input, no non-interactive entrypoint |
| vaultwarden | True | |
| proxmox-backup-server | True | |

**Measured: 24/24 slugs fetched and classified, 0 failed to fetch.**
**Installable: 15/24 (62.5%). Unsupported: 9/24 (37.5%), all for the same
reason** (`install script requires interactive input, no non-interactive
entrypoint` — none hit the multi-CT/docker-compose path in this particular
24-slug set).

**Re-measured after the fix wave's I1 classifier broadening**, this time
fetching by pinned HEAD commit `d7bc6b5` rather than `main`: still 15/24
installable, 9/24 unsupported, 0 fetch failures, same per-slug verdicts as the
table above. The broader `read` detection changed no verdict in this particular
seed list; it closes a false-negative class (bare `read VAR`, `read -s VAR`)
that would otherwise misclassify future slugs as installable.

This is the real, measured number for exactly the 24 scripts this build
ships — not a rounded-up or extrapolated figure, and explicitly not the
spike's 493/559 placeholder (that estimate applies to the ~559-script full
upstream corpus, which this v1 catalog does not attempt to ingest).

## Gate numbers (real, captured this run)

| Gate | Command | Result |
|---|---|---|
| Backend tests | `pytest tests/ -q -m "not pve_integration and not e2e"` | **306 passed, 2 skipped, 2 deselected** (was 290 before the final-review fix wave added 16) |
| Executor isolation | `scripts/check_executor_isolation.py` | **OK** |
| Isolation lint + executor unit tests | `pytest tests/test_isolation_lint.py tests/test_executor.py -v` | **10 passed** |
| Classifier unit tests | `pytest tests/test_classifier.py -v` | **11 passed** |
| Backend license audit | `pip-licenses --partial-match --ignore-packages proxploy --allow-only "..."` (doc 03 protocol) | **FAILS locally** on `psycopg:3.3.4` (LGPL-3.0-only) — expected: `psycopg` lives in the `postgres` extras group (`pyproject.toml`), not `dev`; CI's `backend` job only installs `.[dev]`, so this package is never present when the real gate runs. This local venv has `postgres` extras installed too (for Postgres-portability testing), so it sees a package CI never does. Pre-existing, documented in Phase 1's notes; not a Phase 4 regression |
| Frontend tests | `npx vitest run` | **52 passed (16 files)** (was 49) |
| Frontend build | `npm run build` | **clean** (`tsc -b` + vite build) |
| Frontend license audit | `npx license-checker-rseidelsohn --production --excludePackages "frontend@0.0.0" --onlyAllow "..."` | **OK, exit 0** — `asyncssh` is backend-only so it doesn't appear here; no new frontend dependency this phase needed a licensing exception |

## Every endpoint added this phase

| Method + path | Role | Entitlement | Notes |
|---|---|---|---|
| `GET /api/v1/catalog` | viewer | `store.catalog` | `category`/`q` filters |
| `GET /api/v1/catalog/{slug}` | viewer | `store.catalog` | includes `raw` (ct + install script text) |
| `POST /api/v1/catalog/refresh` | admin | `store.refresh` | enqueues `catalog.refresh`, ~24 GitHub fetches |
| `POST /api/v1/catalog/{slug}/install` | admin | `store.install` | root-consent + enrolled-ssh_key gates, 409 if `(host_id, ctid)` is already tracked, enqueues `app.install` |
| `POST /api/v1/apps/adopt` | admin | `apps.adopt` | bulk-adopt, single-batch commit + audit |
| `GET /api/v1/apps/{id}/script` | operator | `apps.script_edit` | latest pinned version + live diff-vs-upstream |
| `PUT /api/v1/apps/{id}/script` | admin | `apps.script_edit` | new version, `source="edited"`; `ScriptIn` body model (422 on missing `content`), 404 on unknown app. **No frontend caller** — API only |
| `GET /api/v1/apps/{id}/script/versions` | operator | `apps.script_edit` | full version history, newest first |

## Deviations from the plan (controller decisions during the build)

- **Task 1: `default_connect_factory`'s TOFU pinning had a real,
  behavior-only-visible-against-a-real-server bug**, caught in code review,
  not by the implementer's own test suite (which used a hand-written fake
  reimplementation of the pin-check logic). Two stacked bugs: `known_hosts=None`
  silently disables asyncssh's `validate_host_public_key` callback entirely
  (TOFU never activates), and once fixed, having that callback itself
  return the match/mismatch boolean makes asyncssh reject the handshake
  before the intended post-connect `SSHHostKeyMismatch` code ever runs. Fixed:
  `known_hosts=b""` (empty inline trust store, not "skip checking") plus the
  callback always returning `True` and only capturing the fingerprint,
  leaving the post-connect check to own the mismatch decision. Verified via a
  throwaway script driving a real `asyncssh.create_server`/`create_connection`
  pair through all three cases (first-connect pin, matching reconnect,
  mismatched reject) before writing the permanent test
  (`test_default_connect_factory_pins_then_accepts_then_rejects_changed_key`).
- **Tasks 4, 6, 7, 8: entitlement gating and audit-log writes were
  proactively added beyond the plan's literal sample code.** The plan's
  sample routes for `refresh_catalog`, `install_catalog_entry`, `apps/adopt`,
  and the script routes omitted `require_entitlement(...)` and/or
  `write_audit(...)` calls even though the entitlement registry already
  defined the right keys (`store.catalog`, `store.refresh`, `store.install`,
  `apps.adopt`, `apps.script_edit`) and every comparable existing router
  gates + audits its mutations. Task 4 surfaced this gap in its own
  self-review and it was fixed in a review round; Tasks 6-8 applied the same
  gating/audit shape proactively on the first pass, with no fix-round
  needed.
- **Task 5: the plan's sample `appstore.py` code called
  `get_ssh_private_key` directly**, which fails
  `scripts/check_executor_isolation.py` (`services/appstore.py:32 references
  get_ssh_private_key` — 1 violation). Fixed by adding
  `SSHExecutor.run_for_host(sessionmaker, secretstore, host_id, host, command, ...)`
  to `proxploy/executor/ssh.py`, which resolves the private key internally
  (exempt, since it lives under `executor/`) and never lets raw key bytes
  cross into `appstore.py`. Verified by running
  `scripts/check_executor_isolation.py` directly (OK) after the fix.
- **Task 5: `App.slug`'s scheme was corrected to include `host_id`**
  (`f"{catalog_slug}-{host_id}-{ctid}"`, not the plan's
  `f"{catalog_slug}-{ctid}"`) — `App.slug` has a global UNIQUE constraint,
  and two different hosts could each install the same catalog app onto the
  same CTID, which would collide without `host_id` in the slug.
- **Task 8: a test in the plan's own brief asserted a diff direction
  `difflib.unified_diff` cannot produce.**
  `test_upstream_moving_on_after_pin_also_surfaces_a_diff` asserted
  `"+msg_ok done v2" in diff`, but with `unified_diff(upstream, pinned, ...)`'s
  fixed argument order, content unique to *upstream* always renders as a `-`
  line regardless of which scenario produced the difference — the assertion
  as written was structurally unsatisfiable simultaneously with its sibling
  test. Fixed to assert `"-msg_ok done v2" in diff` (the real difflib
  output), preserving the test's actual intent (a diff must appear even when
  only upstream moved) without touching the diff code itself.
- **Task 12: the plan's install-dialog test clicked only the consent
  checkbox and asserted the Install button became enabled**, contradicting
  the plan's own `canSubmit` gate (`consent && hostId != null && name.trim()
  !== '' && ctid.trim() !== ''`) and the task's explicit self-review
  requirement that the button be genuinely disabled until host/name/ctid are
  *also* filled. Fixed by keeping the real 4-part gate and strengthening the
  test to fill host/name/ctid first, assert the button still stays disabled
  until consent is also checked, then check consent — a stricter proof of
  the same root-consent-as-final-gate intent than the plan's snippet, not a
  weakening.

No documented DoD clause or non-negotiable acceptance criterion was loosened by
any of the deviations above — every fix made the real behavior match its own
stated intent more closely, not less.

## Final whole-branch review fix wave (2026-07-30)

All 15 tasks were individually implemented and reviewed; a final cross-task
read of the whole install pipeline (catalog ingest → SSH executor → install job
handler) found issues only visible when the three are read together. One fix
wave, all landed:

| # | Finding | Fix |
|---|---|---|
| C1A | `ctid` never sent to the remote script — CT landed on whatever `build.func` auto-picked while the `App` row claimed otherwise | `env["var_ctid"] = str(ctid)` in `run_install`, set after `overrides` so it wins |
| C1B | The whole `env` dict was dropped in transit: asyncssh `env=` → SSH env channel requests → discarded by default sshd `AcceptEnv` | `SSHExecutor.run` inlines `shlex.quote`d `KEY=value` onto the command; `env=` kwarg removed. Fixed in the executor, so every caller benefits |
| C2 | The "pinned" script was not what executed: pin archived the ingested `install/` file while execution curled a live `…/main/{ct_path}` | One HEAD-commit lookup per refresh; ingest fetches/classifies/pins by that SHA; `run_install` curls that SHA. Residual one-level-down gap named in "What was NOT verified" |
| I1 | Prompt regex too narrow (`read -p` only), guard regex too loose (any nearby `${X:-}`) | Any `read` in command position minus non-prompt contexts; guards must name a variable the `read` assigns into |
| I2 | Per-`ct`-file ETag never re-triggered when only `install/…` changed | Resolved as a side effect of C2 — repo-wide commit SHA replaces the ETag entirely |
| I3 | One bad slug aborted the whole 24-slug refresh | Per-slug try/except, `{synced, failed: [{slug, reason}]}`, each failure narrated to the transcript on `stderr` |
| I4 | `PUT /apps/{id}/script` 500'd on a missing `content` or an unknown `app_id` | `ScriptIn` Pydantic body (422) + `db.get(App, …)` 404 |
| I6 | Duplicate install ran the script to completion on a real node, then `IntegrityError`'d — untracked container left behind. Store cards also hardcoded `installed={false}` | 409 pre-flight on `(host_id, ctid)` before enqueue; `store.tsx` derives `installed` from the real `/apps` list (needed `catalog_slug` added to `_app_out`) |
| M1 | Header read "showing 2 of 1 installable scripts" | "1 of 2 scripts installable (1 unsupported)" |
| M2 | `useRefreshCatalog` invalidated `['jobs']` only; `useInstall` invalidated `['catalog']`, which an install cannot change | Swapped: refresh → `['catalog']` + `['jobs']`; install → `['apps']` + `['jobs']` |

Deliberately **not** attempted here and left as named gaps: full transitive
vendoring of the community-scripts framework (see "What was NOT verified"), the
staleness banner (I5-adjacent, still open below), and minor findings M3-M10.

No documented DoD clause or non-negotiable acceptance criterion was loosened
by any of the above — every fix made the real behavior match its own stated
intent more closely, not less.

**The scoped re-review of that fix wave found one new issue introduced by the
fix itself**, closed in a second, narrower pass:

| # | Finding | Fix |
|---|---|---|
| N1 | `SSHExecutor.run`'s command-composition shell-quotes env *values* (`shlex.quote`) but never validated *keys* — an admin-supplied `overrides` dict key containing shell metacharacters (e.g. `"os; touch /tmp/x; a"`) landed unescaped in the composed command and executed as a second root command. Admin-role + `store.install` entitlement + explicit consent gated (not a privilege escalation — the whole point of this route is running a script as root), but a genuine, freshly-introduced hole with zero validation | `SSHExecutor.run` now rejects any env key not matching `^[A-Za-z_][A-Za-z0-9_]*$` before composing the command (the shared choke point, so no caller can reintroduce this); `InstallIn.overrides` also validates keys at the API layer for a clean 422 instead of a job failing deep in the executor |

**Parked, needs a product decision, not a further code fix:** deriving
`StoreCard`'s `installed` state from the real `/apps` list (fixing I6) made it
host-agnostic — once an app is installed on host A, that catalog entry now
shows disabled "Installed" everywhere in the Store, even though the backend's
409 check is scoped to `(host_id, ctid)` and installing the same app on host B
is still fully permitted server-side. The UI just has no way to attempt it
anymore. Options: show installed-on-N-hosts instead of a flat disabled state,
or accept it as v1 scope (most users won't install the identical app twice
across hosts on day one) — an explicit choice for whoever picks this back up,
not an oversight.

## Known ceilings

No new `ponytail:`-tagged shortcuts were added this phase. One carried
forward from Phase 3 now also governs Phase 4 work: `JobBackend`'s
`Semaphore(4)` (`backend/proxploy/jobs/backend.py:26`) caps installs and
lifecycle actions together at 4 concurrent jobs — a bulk-install of many
apps at once queues behind that same limit rather than running in parallel.
Upgrade path unchanged from Phase 3's note: a knob belongs with Phase 7's
scheduler UI.

`backend/proxploy/services/catalog_categories.py`'s `CATEGORY_MAP` is a
small hand-maintained slug→category table (documented as a known v1 gap in
the plan's header note, not hidden) — every new catalog slug added to
`Settings.catalog_slugs` needs a manual category entry or it falls back to
`"Uncategorized"`.

## What was NOT verified

- **Script pinning stops one level down — the community-scripts framework is
  still fetched live.** The `ct/<slug>.sh` that executes is now byte-pinned to
  the commit that was classified and diffed. But that file's own first line is
  a literal `source <(curl -fsSL …/ProxmoxVE/main/misc/build.func)`. Fetching
  the `ct/` file by commit SHA freezes that line's *text* (including its `main`
  reference), but the framework files it names — `misc/build.func`,
  `misc/error_handler.func`, `install/<slug>-install.sh` as sourced by the
  framework, etc. — are still fetched from `main` **at execution time**, by
  that line, one level down. So an upstream change to `build.func` between
  ingest and install still changes what runs. Full transitive vendoring (mirror
  the whole framework at a commit and rewrite the `source` lines to point at
  the mirror) is a real, separate, larger undertaking and is deliberately NOT
  attempted in this fix wave — it is a named open gap, not a solved problem.
  Flagged in a code comment at
  `backend/proxploy/services/appstore.py::run_install`.
- **No live Proxmox host.** Every proof above runs against
  `tests/fakes/ssh.py`'s `FakeSSHConnection`, matching every prior phase's
  no-live-PVE approach. The install flow's actual root-shell execution
  against a real node has never run in this environment. In particular the
  Critical #1 fixes are proved by asserting on the exact command string handed
  to `create_process` (`FakeSSHConnection.last_command`) — `var_ctid=150` is
  demonstrably *sent*, and `build.func`'s
  `local requested_id="${var_ctid:-$NEXTID}"` was read from the real upstream
  source to confirm it is honoured, but no container has actually been created
  at a chosen CTID on a real node from this environment.
- **No real sshd.** The `AcceptEnv` behaviour that motivated inlining env vars
  into the command string is standard, documented OpenSSH behaviour (and the
  reason asyncssh's `env=` silently no-ops), but it was not reproduced against
  a live `sshd` here. The fix is strictly safer either way: an inlined
  `KEY=value` prefix works regardless of the server's `AcceptEnv` config.
- **No real SSH connection.** `tests/test_executor.py`'s
  `test_default_connect_factory_pins_then_accepts_then_rejects_changed_key`
  is the closest this phase gets — a real `asyncssh` client against a real
  in-process `asyncssh` server — but that is still not a real remote host
  over a real network.
- **No Docker.** Not exercised by anything in this phase.
- **No browser on this box.** The Store page's tile grid, category chips,
  install dialog's live `JobLog` rendering, and the bulk-adopt dialog are
  proved by `frontend/src/tests/{store,install,adopt}.test.tsx` under jsdom,
  **not by a visual run in an actual browser.** No screenshot, no manual
  click-through happened or is claimed to have happened.
- **The Config tab is view-only — there is no script-edit UI.**
  `PUT /apps/{id}/script` exists, is entitlement-gated, audited and tested
  (`tests/test_app_script_api.py`), but **no frontend code calls it**:
  `frontend/src/components/ScriptPanel.tsx` renders the pinned content and the
  diff as read-only `<pre>` blocks with no textarea, no Save control and no
  mutation hook. Earlier wording in this doc said "script view/edit", which
  overstated what shipped; corrected. The DoD clause it serves ("an edited
  script shows its diff against upstream") is still satisfied — the diff is
  computed live on every read and an edit made via the API surfaces
  immediately — but a user cannot make that edit from the UI today.
- **No staleness banner exists.** The DoD clause asks for the catalog to
  serve "cache with staleness banner" when upstream is unreachable. The
  cache-survival half is real (`GET /catalog` never touches upstream; a
  failed refresh doesn't corrupt existing rows — see the DoD table above),
  but there is no UI element anywhere that tells a user the catalog data is
  stale or that the last refresh failed. `synced_at` is returned by the API
  and typed on the frontend but never rendered. This is a real, undelivered
  gap, not a semantic quibble.
- **The `category`/`description`/`icon_url`/`popularity` v1 gap**, called
  out in this plan's header note and doc 01 §3 / doc 04 before any code was
  written: community-scripts has no public bulk metadata API, so `category`
  is a small hand-maintained slug→category map
  (`catalog_categories.py`) and `description`/`icon_url`/`popularity` stay
  `null` in every `catalog_entries` row this phase ships. The Store page
  renders without an icon or description for every entry, and there is no
  popularity-based sort. This was a known, documented trade-off before
  implementation began, not something discovered during verification.
- Postgres-backend behavior for the new/changed tables (`hosts.
  ssh_host_key_fingerprint`, `catalog_entries`, `app_scripts`) — Phase 1/2's
  Postgres CI leg covers schema portability generically; nothing in Phase 4
  added Postgres-specific exercises.

## What Phase 9 (docs) should write

- User-facing docs for the App Store: what "installable" vs "unsupported"
  means in practice (a mechanical classifier reading the script, not a
  curated allowlist), and that the v1 catalog is 24 hand-picked apps, not
  the full community-scripts corpus.
- The root-consent step's exact wording and why it exists (running a
  third-party community-scripts.org script as root on a node).
- A decision on the staleness-banner gap above: either build it (surface
  `synced_at` + a "last refresh failed" indicator on the Store page) or
  formally defer it to a later phase, so it stops being an open DoD clause.
- A decision on `category`/`description`/`icon_url`/`popularity`: whether a
  real upstream metadata source is ever found, or whether the hand-maintained
  map is the permanent approach and the Store page's visual design should
  stop assuming icons/descriptions will eventually appear.
