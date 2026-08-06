# Phase 9b — Onboarding, empty states, error states, light theme

**Status:** design approved 2026-08-06, plan not yet written.
**Predecessor:** [Phase 9a](2026-08-05-phase-9a-install-update-design.md) (install + self-update), complete.

Doc 10's Phase 9 was one undifferentiated "Deliver" block; the 9a spec split it
into 9a–9d. This is 9b.

## What this phase is actually for

Doc 10's Phase 9 DoD, verbatim: *"a stranger installs via the one-liner on a
clean PVE box, **completes onboarding, installs an app, creates a VM, schedules
a backup**, and self-updates to the next tagged release — without reading source
code."*

9a proved the two outer clauses. The four bolded middle ones are 9b's. Doc 10
lists this phase's work as *"onboarding wizard polish to the full flow, empty
states, error states, light-theme QA pass"*, which reads as cosmetics — it is
not. Those four clauses are the "can a stranger actually drive this product"
claim, and nothing in Phases 1–8 executed them through the UI.

**The governing decision: 9b proves the stranger journey end to end against
fakes.** The DoD clauses become executed assertions rather than assertions of
intent. This is 9a's lesson applied forward — there, `/meta/health` answered
correctly while `/` served nothing, and only running the thing found it. A
green signal not backed by the thing it claims is the failure mode this phase
exists to prevent.

## Findings this design rests on

Established by direct survey of the codebase on 2026-08-06, not assumed:

- **The wizard's host step is a hard wall.** `api/hosts.py:101`'s
  `create_host` unconditionally probes the live Proxmox API before writing the
  row, raising 502 on failure. This is why `e2e/smoke.spec.ts:18-27` bypasses
  the step with direct API calls.
- **The wizard's position is local `useState`** (`routes/onboarding.tsx:20`)
  with no persistence. On reload, `beforeLoad` still sees `complete: false`
  and remounts at step 0 — but the admin now exists and a session cookie is
  set, so resubmitting hits `create_user`'s non-first-run path and 409s,
  surfaced through the copy *"Could not create the admin account (password:
  12+ characters)"*. The user is told they typed a bad password when what
  actually happened is that they already succeeded.
- **`GET /meta/onboarding` already returns `admin_exists`, `host_added` and
  `complete`** (`api/meta.py:36-42`). Deriving the step from server state is
  nearly free; only an SSH-pending signal is missing.
- **F1 is worse than Phase 8 recorded.** It is not that nothing renders:
  TanStack Router falls back to its built-in `ErrorComponent`, which styles
  itself with **inline `style={}`** and therefore ignores the app's theme
  entirely. Because it fires at the failing route's match, `AppShell` never
  mounts. A stranger hitting a 500 gets an unstyled grey box on a blank page.
  `shell.tsx:39`'s `GET /meta/onboarding` call is unwrapped, which is a live
  path into exactly this.
- **~40 `useQuery` call sites, 13 branch on `isError`.** The rest fall back to
  `?? []`, so **a failed query renders as an empty state** — the UI says "No
  VMs discovered" when it means "we could not reach the backend."
  `components/HealthFooter.tsx:24-27` already carries a comment naming this
  risk. `EmptyState` is also overloaded as a loading placeholder
  (`title="Loading…"`, `apps.tsx:159`, `vms.tsx:125`), which is the same
  conflation from the other direction.
- **The theme system is already disciplined.** CSS custom properties under
  `[data-theme]` (`styles/tokens.css:3-47`), and a scan for hardcoded Tailwind
  gray-scale classes returns **zero matches**. Exactly two literals break it —
  `UsageBar.tsx:12` and `StatRings.tsx:19`, both `#1d2733` — accounting for
  ~11 rendered instances across 7 files. "Light-theme QA pass" is a two-line
  fix plus a guard, not a sweep.
- **Both fake seams needed for the journey already exist.**
  `app.state.proxmox_factory` is how backend tests drive `FakePVE`;
  `executor/ssh.py:36,84`'s `connect_factory` is the identical seam for SSH.
  `services/sshkeys.py` only *generates* keys — there is no verification path
  today, so §1's SSH probe is new work.

## Design

### §1 — The wizard, rebuilt on server-derived state

Position becomes a function of server truth rather than component state.
`GET /meta/onboarding` grows an `ssh_pending` field alongside the three it
already returns; the wizard derives its step from that response. A reload
lands where the user actually is.

Four behaviours change:

1. **Resume-on-reload**, per above. The 409-reported-as-bad-password path
   disappears because the wizard no longer asks a user to redo a step they
   completed.
2. **The host step becomes skippable.** The shell's guard already permits a
   host-less app — it checks `onboarding.complete` and never `host_added`
   (`shell.tsx:38-42`) — so the wizard was the only thing enforcing the wall.
   Skipping lands on Cluster, which is why §4's Cluster empty state is load-
   bearing rather than decorative.
3. **The SSH-authorize step gets verified.** Today it is an honor-system "I
   have authorized it" button with no check, so a mis-pasted `authorized_keys`
   line fails later, at the first app install, far from its cause. A new
   endpoint runs a trivial command through the existing `SSHExecutor` and
   reports whether the key actually works.
4. **Host-step failures are distinguished.** Unreachable URL, bad token, TLS
   fingerprint mismatch and probe 502 are four different problems with four
   different user actions, and they currently collapse into generic copy.
   These are the errors a stranger on a real box is most likely to hit.

### §2 — F1, closed properly

A themed `errorComponent` on the root and shell routes, plus a
`defaultErrorComponent` on the router, so a throw renders inside the app's own
chrome and tokens. `shell.tsx:39`'s unwrapped call is handled.

The screen distinguishes **"backend unreachable"** from **"something broke"**,
because those ask different things of the user — the first wants a retry, the
second wants detail (dev-only) and a way out. Collapsing them into one
"Something went wrong" is what the built-in fallback already does badly.

### §3 — One four-state query wrapper

A single shared component renders **loading / error / empty / data** as four
distinct states, and every list-rendering query is converted to it. The point
is structural: it makes "error displayed as empty" impossible to express,
rather than a rule contributors must remember at ~40 call sites. It also
retires `EmptyState`-as-loading-placeholder.

**Which queries.** A full inventory taken 2026-08-06 counts **69 `useQuery`
sites** (one, `api/jobs.ts:45`, is dead code and gets deleted rather than
converted). **46 render a collection; 6 of those already branch on `isError`;
40 do not.** The 40 split into 25 page-level content lists and 15 form/dialog
select-option lists. Page lists come first — an error there reads as "there is
nothing here"; a select degrades to an empty dropdown, which is milder but
still wrong.

Single-value queries are out of scope **except** where failure renders a
reassuring falsehood rather than a blank. Three qualify and are in scope:

- **`api/hooks.ts:16` `useEntitlements`** — `has(key)` returns `false` on
  error, so a failed entitlements fetch silently hides every gated feature in
  the product as though the tenant were not entitled. It gates dozens of
  buttons and panels, which makes this the highest-impact false negative in
  the app.
- **`api/account.ts:41` `useTotpStatus`** — on error the card falls to its
  "not enrolled" branch and offers to enable two-factor when it may already be
  on. Security-relevant.
- **`routes/cluster.tsx:25` `useSummary`** — CPU/memory/storage rings fall back
  to `?? 0` and draw a calm 0% gauge when the truth is "unknown".

`components/HealthFooter.tsx:15` already does this correctly — it checks
`isError` before ever computing "All systems healthy" — and is the reference
pattern for the three above.

Each conversion is mechanical; the risk is tedium, not difficulty.

### §4 — Empty states

Cluster's node grid gets a real first-run empty state. With §1's skippable host
step this becomes the literal first screen of a fresh install, and today it is
a bare `<div>` — no heading, no message, no action. Alerts and Settings move
off ad-hoc inline text onto the shared component.

### §5 — Light theme

`UsageBar.tsx:12` and `StatRings.tsx:19` move from literal `#1d2733` to tokens,
which closes all ~11 broken instances. A guard keeps it closed, since the token discipline is
already good and the failure mode is bypass, not drift. **The guard is a test**
— a Vitest case that greps `frontend/src` for literal hex colours in `style`
props and SVG paint attributes and fails on any hit outside an explicit
allowlist — not an ESLint rule. A test runs in the existing frontend gate,
needs no new plugin dependency, and can carry the allowlist and its reasoning
in the same file.

Terminal and console surfaces (`ScriptPanel`, `TerminalPanel`,
`terminal/Terminal`, `console/VncConsole`, `onboarding.tsx:77`) stay dark in
both themes **by intent** — a terminal that follows a light theme stops looking
like a terminal. This is currently unmarked in the source; the guard needs an
explicit allowance so the intent is recorded rather than rediscovered as a
violation.

### §6 — The stranger journey, executed

A **test-only launcher in `e2e/`** imports `create_app` and installs `FakePVE`
via `app.state.proxmox_factory` and a fake SSH via `connect_factory`. It lives
entirely in test code: no environment variable, no test branch in shipped
code. A `PROXPLOY_E2E_FAKE_PVE` flag honoured by `main.py` would be a backdoor
that swaps a core client in the production binary, in a product whose trust
story is root-on-node. That is not shippable and is rejected on those grounds,
not on taste.

Playwright then drives the **real UI** through wizard → app install → VM create
→ backup schedule, converting the four DoD clauses into assertions. The suite
runs twice, dark and light; the light leg asserts computed styles — no element
resolving to the dark literal, contrast thresholds on key surfaces.

Computed-style assertions are chosen over screenshot review because they catch
the actual bug class (token bypass) mechanically. They do not prove the light
theme looks *good*; nothing available here does, and §"What this does not
prove" says so rather than implying otherwise.

**The e2e suite is not in CI today.** `.github/workflows/ci.yml` has seven jobs
and none runs Playwright; there is no `playwright install` step anywhere. Phase
8 closed the browser gap by writing the harness, but nothing runs it except by
hand. Building the DoD journey on an ungated harness would mean these clauses
pass once and then rot, so **adding an e2e CI job is part of this phase**, not
a follow-up. Chromium is present locally (`~/.cache/ms-playwright`); CI needs
`playwright install --with-deps chromium` plus the backend venv the harness
launches.

## What this phase does not prove

- **`FakePVE` is not a Proxmox node.** The journey proves the product's own
  logic, routing and UI against a fake, not its behaviour against real
  hardware. This is the standing gap every phase since 4 has recorded, and it
  will be stated in the e2e harness's own output rather than buried in a notes
  file.
- **Computed-style assertions are not visual review.** They prove no element
  resolves to the dark literal and that key surfaces clear a contrast
  threshold. "Ugly but correct" passes them.
- **The verified SSH step proves the key works against the fake transport**,
  under the same limitation as the PVE fake.

## Open item for the plan, not for implementation

§1's SSH verification endpoint is new: `services/sshkeys.py` generates keys and
nothing more. `executor/ssh.py`'s `SSHExecutor.run` and `connect_factory` are
the right foundation, but the endpoint's shape — where it lives, what it runs,
how failures map to the four distinguished host-step errors — is a planning
decision, and the plan must state it concretely rather than leaving it to the
implementer.
