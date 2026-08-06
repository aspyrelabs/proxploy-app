# Phase 9c (proxploy-docs and proxploy-web) — verification notes

> **Goal**, verbatim from the plan: *"Build a documentation site and a
> marketing site for Proxploy from the material the project already has,
> fix the three defects that would make them publish falsehoods, and deploy
> neither."* Three fixes landed in `proxploy-app` first, because the docs
> would otherwise document things that were wrong. Then `proxploy-docs`
> (Astro 6 + Starlight, following `layerr-docs`) and `proxploy-web` (Vite +
> React, following `layerr-web`/`folderr-web` minus their Replit scaffolding)
> were built as new, separate, unpublished repos. Plan:
> `docs/superpowers/plans/2026-08-06-phase-9c-web-and-docs.md`.

## What shipped, per subsystem

**Three `proxploy-app` fixes, landed before any docs content (Tasks 1–3).**
`FastAPI()` gained `version=__version__`, so the OpenAPI schema reports
`1.0.0` instead of the FastAPI default `0.1.0`
(`backend/proxploy/main.py`, commit `94a4326`). `backend/scripts/
export_openapi.py` writes the schema to a file as a pure function of the
app — no server, no network — for the docs site to consume (commit
`92d86db`). It inlines `make_app`'s app-construction body rather than
importing `tests.support`, because `packaging/build_release.sh` excludes
`tests/` from the release tarball but not `scripts/` — confirmed directly:
`grep -n exclude packaging/build_release.sh` shows `--exclude='tests'` and
no `scripts` exclusion. An installed release's copy of this script would
`ImportError` on the import form. And `install.sh` was fixed so the bare
`curl -fsSL https://proxploy.com/install.sh | bash` — the exact command in
the script's own header — actually runs, by compiling in the release public
key, defaulting `--channel`, fetching-then-reading the version out of
`manifest.json` when `--version` is omitted, and adding `--dry-parse` so
the defaulting logic is testable without root or network (commit `064a5b2`).
See **Findings** below — this one was a real, shipped defect, not a
speculative gap being closed early.

**`proxploy-docs`** (`/home/aasim/workspace/aspyrelabs/proxploy/proxploy-docs`,
new repo, no remote): Astro 6 + Starlight scaffold with a four-file content
test suite carried over from `layerr-docs` (frontmatter, links,
content-consistency, build) — `content-consistency.test.ts` rewritten for
Proxploy rather than layerr's intelligence-layer claims, asserting every
guide under `guides/` is reachable from the index and that any "N feature
guides"-style claim in prose matches the real file count. Content: install
pages (index/lxc/docker/updating), getting-started (wizard walkthrough,
Proxmox token roles, SSH key enrolment), the trust model page (root-on-node
stated plainly, per doc 10's own requirement), 15 feature guides across App
Store/consoles, storage/network/backups/VMs, and schedules/updates/alerts/
teams/SSO/2FA/tokens/migration, an API reference generated from
`export_openapi.py`'s output, and a Dockerfile + CI workflow that will not
run anywhere (no remote) but is correct the day the repo gets one.

**`proxploy-web`** (`/home/aasim/workspace/aspyrelabs/proxploy/proxploy-web`,
new repo, no remote): single-package Vite 7 + React 19 + Tailwind v4 +
wouter site, Proxploy's own design tokens (not layerr's blue/cyan), no
Replit scaffolding anywhere. Home, Features, Install, About, Privacy Policy
and Terms of Service pages, real paths only (`/features`, `/install`, no
hash anchors), a prerender pipeline (sitemap → client build → SSR build →
static HTML per route) and a folderr-web-style nginx image. No pricing
route, no checkout, no "Download" CTA that implies a working download — the
install page states plainly that the release is not published yet.

## Findings — the phase's real output

- **The advertised one-liner did not work.** `install.sh:21-23` initialised
  `CHANNEL`/`VERSION`/`PUBKEY` to `""`, and lines 198-199 / 212-214 hard-
  required all three — so `curl -fsSL https://proxploy.com/install.sh |
  bash`, the command in the script's own header and the one doc 10's DoD is
  phrased around, died with `--channel is required`. Every 9a harness
  (`test_install.sh`, `test_upgrade_rollback.sh`, `test_pve_half.sh`) passed
  explicit `--channel`/`--version`/`--pubkey` flags, so the exact form every
  real user would run was the one form never executed, across all of Phase
  9a. Fixed by compiling the release public key into the script itself (it
  cannot be fetched — nothing is unpacked yet to read it from), defaulting
  the channel, resolving the version from the fetched manifest when absent,
  and adding `--dry-parse` so this is testable without root or network.
  **This is the third instance in this phase-group of tested path ≠
  advertised path** — the other two, both found in 9b, were SSH being
  handed a full `https://` URL where asyncssh needs a bare hostname, and
  `Host.node_name` never being written by the code path a real onboarding
  flow actually takes.

- **The OpenAPI schema reported `0.1.0`** while `proxploy.__version__` was
  `1.0.0`, because `FastAPI()` was constructed without `version=`. Left
  unfixed, the generated API reference would have contradicted the product
  on its first page — the exact drift 9a Task 1 existed to make impossible
  by making `__version__` the single source of truth. Confirmed fixed: the
  built reference's `openapi.json` and rendered pages report `1.0.0`.

- **`starlight-openapi` was evaluated and rejected on evidence, not
  vibes.** The latest release requires `@astrojs/starlight >=0.41.0` and
  `astro >=7.0.2`; this repo pins `^0.39.2` / `^6.4.2`, so `npm install
  starlight-openapi` fails ERESOLVE outright. An older release, `0.25.3`,
  *does* satisfy those peers and was spiked to a successful build — then
  rejected because it generates roughly 130 virtual HTML routes outside
  `src/content/docs/`, which breaks `build.test.ts`'s page-count invariant
  and exempts every reference page from the frontmatter and link tests that
  govern every other page on the site, plus it pulls in a high-severity
  `form-data`/`httpsnippet` dependency chain. The fallback —
  `scripts/generate-reference.mjs`, turning `src/openapi.json` into real
  `.md` files under `src/content/docs/reference/` — keeps the reference
  covered by the same test suite as every hand-written page and preserves
  the "regenerate, never hand-edit" property. Also worth noting:
  `layerr-docs` — the template this entire site follows — has **no OpenAPI
  plugin at all**; its 577-line reference is hand-written. There was no
  in-house precedent to copy here; this was new ground.

- **An internal code comment leaks into the public API docs.** `backend/
  proxploy/api/network.py:159`, the docstring of `list_bridges` (`GET
  /network/bridges`), contains a `# ponytail:` line (a deliberate-
  simplification marker, not meant for end users) that flows straight into
  the OpenAPI `description` field for that route and is visible today at
  `/api/docs`. The reference generator now escapes a leading `#` in schema
  free-text — without that, the comment was being parsed as a markdown H1
  in the generated page — but **the comment is still in the production
  docstring**, unchanged. Recorded here as an open follow-up: the honest
  fix is moving the ponytail note out of the docstring (a plain code
  comment above the function, not inside the triple-quoted string), not
  papering over its rendering.

- **`scripts/` ships in the release tarball while `tests/` does not.**
  `packaging/build_release.sh` excludes `tests` but not `scripts`
  (`grep -n exclude packaging/build_release.sh` — confirmed directly, not
  assumed). `export_openapi.py` therefore inlines its own app construction
  (`_build_app`, a deliberate copy of `tests/support.py::make_app`'s body)
  instead of importing `tests.support` — an installed copy of the script
  would otherwise `ImportError` the moment it ran outside a full checkout.

- **99 unique paths, not 127 routes.** The plan's own Task 11 text said
  "The app registers 127 routes across 22 router files." `openapi()
  ["paths"]` is keyed by path, so multiple HTTP methods on one path (e.g.
  `GET`/`POST /schedules`) collapse to a single dict key — the export and
  the generated reference report **99 paths** covering **129 operations**
  (verified directly against `proxploy-docs/src/openapi.json`: `len(paths)
  == 99`, summed per-path methods `== 129`). The 127 figure in the plan
  counted route *operations*, not unique paths, and was itself close but
  not exact against the real number this task measured.

**Two judgement calls, both stated in their commits rather than defaulted
silently:**

- **The `/screenshots` route was omitted entirely**, not stubbed with a
  placeholder. There is no browser in this environment to capture the real
  product UI, and a page that is obviously a placeholder adds a stub with
  no real content for no benefit over not having the route yet — worse,
  arguably, since it invites a reader to expect something real behind it.
  Add the route once real screenshots exist.
- **The refund policy was omitted**, not written as a "not yet available"
  stub. There is no pricing route, no checkout, and no purchase path
  anywhere in `proxploy-web` today (the plan's global constraints bar even
  a pricing stub), and a refund policy is definitionally about purchases —
  with none possible, there is nothing for a policy to describe, even a
  placeholder one. Revisit once a paid plan exists.

## Residual limitations, stated plainly

- **Nothing is deployed and no page has been seen by a human.** There is no
  browser in this environment for visual review. Passing builds and link
  tests prove the sites are internally consistent and structurally sound —
  they do not prove the pages look right, read well at a glance, or work
  the way a stranger would expect on first contact.
- **The documented install path is unreachable and cannot be verified end
  to end.** The release channel is unpublished and `proxploy-app` is
  private, so nothing exists at `https://proxploy.com/install.sh` today.
  The one-liner fix in Task 3 is proven by `--dry-parse` and the packaging
  test harnesses against local fixtures — not by an actual `curl | bash`
  against a live, published channel, because no such channel exists yet.
- **The feature guides are assembled from phase notes, not from using the
  product against real hardware.** Every guide in `src/content/docs/
  guides/` traces back to a specific phase note's "what shipped" section,
  not to a human clicking through the real UI against a real Proxmox host.
  9b is direct evidence that this gap hides real defects, not just
  unproven claims: its own journey harness's first real run found two
  production bugs (SSH given a URL instead of a hostname; `Host.node_name`
  never written) that three prior phases' fake-backed DoDs had passed
  straight through. Nothing in 9c re-executed those paths against a real
  Proxmox host; the guides describe intended behaviour, verified only by
  the same class of fake-backed tests that let those two bugs through
  before.
- **`proxploy-web` and `proxploy-docs` have no git remote.** Both are local
  git repos on this one machine only, per the plan's global constraint —
  "no repository visibility change, no GitHub release, no `gh repo
  create`, no deployment, no DNS." All of this phase's work outside
  `proxploy-app` exists nowhere else.
- **Two backend tests flaked under concurrent full-suite load and passed in
  isolation, unrelated to any 9c change.** `test_backups_sync.py::
  test_concurrent_stale_reads_enqueue_only_one_sync` failed once during
  this phase's full-suite run (829 passed / 1 failed alongside the rest);
  re-run alone it passed three times in a row (64s, 3s, 2s — the first run
  itself timing-variable, matching a documented Phase 6 finding about this
  exact test). `test_alerts_loop.py` is the sibling test this class of
  flake was previously attributed to (see Phase 6/9b notes); both are
  timing/thread-race tests, not correctness regressions, and neither was
  touched by this phase.
- **The doc 11 amendment records a contradiction rather than resolving
  it.** `docs/11-risks-open-decisions.md` §6 still reads "Proxploy is
  self-hosted source-available code" — left as originally written on
  purpose, per this document's own rule against silently rewriting
  history — while the repository has been private since 2026-08-06 and
  `proxploy-docs`' trust page already states the accurate, current
  position. Which document is amended to close the gap (§6, to drop the
  source-available framing; or the repository, to go public and restore
  §6's premise) is an open decision owned by Aspyre Labs, not resolved by
  this phase.

## Real numbers — every one run directly in this session

| Gate | Result |
|---|---|
| Backend suite | **829 passed, 1 failed (flake, see above), 2 skipped, 4 deselected**, then the failing test **passed 3/3 in isolation** — `pytest tests/ -q -m "not pve_integration and not e2e"` (baseline entering the phase: 827) |
| `proxploy-docs` tests | **199 passed** across 4 test files — `npm test` |
| `proxploy-docs` build | **49 pages** built, Pagefind index over 49 HTML files, sitemap generated — `npm run build` |
| `proxploy-web` build | **6 routes prerendered** (`/`, `/features`, `/install`, `/about`, `/privacy-policy`, `/terms-of-service`) — `npm run build` |
| `proxploy-web` typecheck | clean, exit 0 — `npm run typecheck` |
| Alembic heads | **`01f962e7a491`**, one head, unchanged — `alembic -c alembic.ini heads` (9c adds no migration) |
| OpenAPI paths / operations | **99 paths, 129 operations** — measured directly against `proxploy-docs/src/openapi.json` |

**Note on the plan's own arithmetic.** The plan's prose (Task Order section
header) said "eleven feature guides"; the explicit per-task file lists in
Tasks 8, 9 and 10 total 3 + 4 + 8 = **15**. 15 guides shipped, matching the
file lists rather than the prose count — recorded here as a defect in the
plan document, not in the delivered work.

**Commit ranges** (both new repos started as one-commit empty scaffolds —
each repo's range is given in full since neither has been recorded before):

- `proxploy-app`: `8e67985..94a4326` (design spec through the last fix
  commit; this note's own commit and the buildlog/doc-11 commit follow)
  — 5 commits: `7ddde31`, `f8679f2`, `92d86db`, `064a5b2`, `94a4326`
- `proxploy-docs`: `a2af925..987a6c7` (full history, 10 commits)
- `proxploy-web`: `6b3608c..3b987cd` (full history, 5 commits)
