# Phase 9c — proxploy-docs and proxploy-web

**Status:** design approved 2026-08-06, plan not yet written.
**Predecessors:** [9a](2026-08-05-phase-9a-install-update-design.md) (install + self-update), [9b](2026-08-06-phase-9b-onboarding-polish-design.md) (onboarding, empty/error states, light theme). Both complete.

Doc 10's Phase 9 was one undifferentiated "Deliver" block; the 9a spec split it
into 9a–9d. This is 9c.

## The governing constraint

**Nothing publishes.** `proxploy-app` stays a private repository until the
owner judges the project ready. No release is cut, no repository visibility
changes, no site is deployed. This phase **builds** two sites and leaves both
one command from live.

That constraint is not a limitation to work around — it decides the shape of
the work, and two consequences follow that the plan must respect:

1. **The docs describe an install path that is not yet reachable.** 9a's
   distribution design (D1) assumed a public repo: the one-liner fetches
   `install.sh` from raw GitHub and the updater fetches the tarball, manifest
   and signature from GitHub Releases. Private, those 404 for everyone. The
   docs therefore present the install *as designed*, with the URLs it will
   use, and say plainly on the page that the release is not published yet.
   They must not imply a working download.
2. **Doc 11 states the opposite posture, and this is not a small deviation.**
   `docs/11-risks-open-decisions.md:165-167` reads: *"Proxploy is self-hosted
   **source-available** code; anyone can patch `Entitlements.enabled()` to
   return true and unlock armed Pro features. This is **accepted, not
   mitigated away**."* — with the reasoning at :170-180 that paying customers
   *"are buying support, updates, and honesty, not un-patchable bits"*. A
   private repository is the opposite stance, and it also makes that whole
   risk analysis moot: nobody can patch what nobody can read.

   **This phase does not resolve that.** It records the contradiction in doc
   11 as an open decision with both positions stated, and the trust-model page
   (§2) describes what is true today — closed source — rather than repeating a
   source-available claim the repository does not honour. Rewriting doc 11 to
   match, or reverting the private decision, is the owner's call and is
   explicitly deferred.

**Distribution is deferred, not decided.** When publication does happen, the
artifacts need a host, and it need not be GitHub — `fetch_to` in
`packaging/lib/common.sh` handles `file://` and plain `curl`, and `--channel`
takes an arbitrary URL, so object storage behind a `releases.` subdomain would
need no installer change. That decision belongs to whoever runs
`docs/runbooks/publishing-a-release.md`, not to this phase.

## Explicitly out of scope: pricing and checkout

The owner initially chose a full commercial launch with Paddle checkout, on
the assumption that publication was happening. With nothing shipping, that
inverts: checkout cannot be exercised, and it depends on entitlement
enforcement that does not exist.

This is also what the existing docs already say to do.
`docs/09-repository-structure.md:161-164` lists proxploy-web's page inventory
with **"pricing (dormant until tiers arm)"**, and
`docs/01-product-spec.md:273-275` is blunt about the state of the tier model:
*"every one of these flags resolves ON today. The Free/Pro column is a pricing
sketch stored as config on proxploy-api, not behavior in the app."* The tier
labels (`Core`/`Free`/`Pro`) are marked **provisional and INERT** at
`01-product-spec.md:26-35`. Omitting pricing is therefore following the
design, not deviating from it.

Mechanically: `backend/proxploy/entitlements/registry.py` defines
`DEFAULT_FEATURES = {k: True for k in FLAG_KEYS}` — all 81 flags on — and
`proxploy-api`'s `tiers.py::resolve_features` short-circuits on
`tiers.yaml`'s `all_entitled: true`, whose own comment reads
*"filled in the day Aspyre decides to sell"*. Note also that `tier` is a
display string only: `client.py` carries it through from the token, but
nothing branches on it — **only `features[key]` gates anything**. So "arming
tiers" is a `tiers.yaml` edit plus app-side gating, not a refactor.

**Selling tiers the code hands out for free is the one sequencing mistake
worth refusing.** Billing lands after enforcement, as its own phase, in this
order:

- **9d** — `proxploy-api` hardening and entitlement resolution that stops
  returning all-entitled.
- **9e** — tier enforcement in `proxploy-app`. The flags exist; nothing gates
  on them.
- **9f** — Paddle products, checkout, webhooks, license delivery.

No pricing page, no tier comparison, and no Paddle SDK ships in 9c.

## Findings this design rests on

Established by direct survey on 2026-08-06, not assumed:

- **Both target repos are bare scaffolds.** `proxploy-web` and `proxploy-docs`
  each contain exactly `.gitignore` and `README.md`, one commit apiece, **no
  GitHub remote, and neither exists on GitHub**. This phase builds both from
  nothing.
- **There is strong in-house precedent for both, and it should be followed
  rather than re-chosen.** `layerr-docs` is Astro 6 + Starlight with pagefind
  search, pre-rendered Excalidraw diagrams, a vitest suite
  (`frontmatter.test.ts`, `content-consistency.test.ts`, `links.test.ts`,
  `build.test.ts`), a pinned-`node`/pinned-`nginx` Dockerfile, and a GitHub
  Actions test workflow. `layerr-web` and `folderr-web` are Vite + React +
  TypeScript, `wouter` routing, Tailwind v4 via `@tailwindcss/vite`,
  shadcn/ui on Radix, with prerender and sitemap scripts for SEO.
- **The sibling marketing sites are pnpm workspace monorepos** with an
  `artifacts/<name>/` layout — but that structure exists to share generated
  API clients (`lib/api-zod`, `lib/api-spec`, `lib/api-client-react`). A
  marketing site with nothing to share gains only ceremony from it.
- **`main.py:142` constructs `FastAPI(title="Proxploy", docs_url="/api/docs",
  openapi_url="/api/openapi.json", lifespan=lifespan)` with no `version=`**,
  so the schema reports FastAPI's default `0.1.0` while
  `proxploy.__version__` is `1.0.0`. 9a Task 1 existed to make that one number
  authoritative.
- **Nothing exports the OpenAPI schema to a file.** The schema is live at
  `/api/openapi.json` and `backend/tests/test_openapi_surface.py` calls
  `app.openapi()` in-process, but no script writes it to disk. A docs site
  needs a static artifact.
- **The committed test-only Ed25519 key is harmless but worth documenting.**
  `backend/tests/contract/entitlement_token.fixture.json` holds a real private
  key with `kid="test-fixture-1"`. Production loads only
  `BUNDLED_PUBLIC_KEYS` (one entry, `dev-2026-07`), rejects unknown `kid` with
  no fallback, and `build_release.sh --exclude='tests'` keeps the fixture out
  of the tarball. It becomes a risk only if that pubkey is pasted into
  `keys.py` or a future packaging path ships `backend/tests/` verbatim.

## Design

### §1 — `proxploy-docs`: Astro 6 + Starlight

Match `layerr-docs`'s stack and structure, including **its test suite** —
frontmatter validity, internal-link integrity, content consistency, and a
build check. A docs site whose links rot silently is worse than none, and the
precedent already solves this; re-deriving it would be wasted work.

Sidebar groups, each mapping to a `src/content/docs/` subfolder:

- **`install/`** — the LXC one-liner, the Docker/Compose shape, what the
  installer does to a node, and updating. Sourced from
  `docs/notes/phase-9a-install-update.md` and `packaging/`.
- **`getting-started/`** — onboarding walkthrough, and the **minimal-privilege
  Proxmox API token guide** doc 10 calls for: exactly which privileges
  Proxploy needs and how to create a scoped token rather than handing over
  root credentials.
- **`trust/`** — see §2.
- **`guides/`** — per-feature, assembled from `docs/notes/phase-4-store.md`
  through `phase-8-scale.md`: apps and the App Store, VMs and snapshots,
  storage, network, backups and schedules, consoles, updates and alerting,
  teams and RBAC, OIDC, TOTP and sessions, API tokens, cross-host migration.
- **`reference/`** — the API reference, generated (§4).

### §2 — The trust model page, written plainly

Doc 10 requires the trust model with "root-on-node stated plainly". This page
is the one a sceptical self-hoster reads before piping a script into `bash`,
and hedging it would be the wrong instinct. It states:

- Proxploy takes a **root shell on your node** via a dedicated SSH key, used
  for App Store install/update/migration scripts — exactly as if you ran them
  yourself as root. The consent copy already in `api/hosts.py`'s
  `CONSENT_NOTE` is the source of truth for the wording.
- Every use is audit-logged and its full output archived.
- SSH enrolment is **optional**; everything except installs, updates and
  migration works without it.
- The Proxmox API token should be minimally privileged, and the guide in
  `getting-started/` shows how.
- Updates verify an **Ed25519 signature over the raw manifest bytes before any
  parsing**, then a sha256 checksum, then unpack — and refuse downgrades.
- The release public key ships **inside** the artifact, so rotating it
  requires publishing a release signed by the old key.
- The repository is private; the product is not source-available today.
- The `test-fixture-1` key noted above: what it is, why it cannot grant
  anything, and the two changes that would make it dangerous.

### §3 — `proxploy-web`: Vite + React, single package

Stack per the sibling sites — Vite, React, TypeScript, `wouter`, Tailwind v4
via `@tailwindcss/vite`, shadcn/ui on Radix — but a **single package, not a
pnpm workspace**. The monorepo layout exists next door to share generated API
clients; here it would be structure for its own sake. Prerender and sitemap
scripts carry over, since they are what makes the site indexable.

Routes follow the inventory already specified at
`docs/09-repository-structure.md:161-164`, minus the two it marks as not-yet:
landing, features, screenshots/tour, install (pointing at the docs),
about/Aspyre Labs, and legal — terms, privacy, refund — naming **Aspyre Labs
LLC, 30 N Gould St #Ste R, Sheridan, WY 82801, USA**. Pricing is omitted per
the section above (doc 09 itself marks it "dormant until tiers arm"), and
blog/changelog is deferred — there is nothing to put in it and an empty blog
reads worse than none.

Legal pages follow the sibling implementation exactly: **component-based TSX
wrapped in a shared `LegalLayout`**, with `Section`/`Clause` sub-components and
a `LAST_UPDATED` constant — not MDX. Both `layerr-web` and `folderr-web` do it
this way and both statically prerender the output.

**All links use real paths** (`/install`, `/privacy-policy`), never
hash-anchors, with hyphens for multi-word paths. This is a standing rule
across every Aspyre Labs property.

The site must not claim the product is downloadable while it is not. The
install route presents the command and states that the release is not yet
published.

### §4 — OpenAPI export, and the version it reports

Two pieces:

1. **Fix `main.py:142`** to pass `version=__version__`, and add a test pinning
   the OpenAPI schema's version to `proxploy.__version__` so they cannot drift
   again. Without this the published reference contradicts the product on its
   first page.
2. **A script that writes `openapi.json` to disk**, run to regenerate the
   reference. It calls `app.openapi()` directly rather than requiring a
   running server, mirroring how `test_openapi_surface.py` already does it.

The reference pages are generated from that artifact by a **Starlight OpenAPI
plugin** (`starlight-openapi` + `@astrojs/starlight`'s schema hooks), not by a
hand-rolled markdown generator and not by hand-writing endpoint pages. The
plugin route means the reference is a build-time function of `openapi.json`,
so it cannot drift by omission; a hand-written reference across ~150 routes
would be stale within a phase.

The plan must confirm the plugin supports the installed Starlight major
version before committing to it — `layerr-docs` pins Starlight `^0.39.2` on
Astro `^6.4.2`, and plugin compatibility tracks Starlight's major closely. If
it does not support that version, the fallback is generating markdown pages
from `openapi.json` in a script and checking the output in, which keeps the
"regenerate, don't hand-edit" property; hand-authoring the reference is not a
fallback and is ruled out here.

Either way generation is repeatable and checked in CI, so the reference cannot
silently drift from the API — the same failure mode §1's link tests guard
against.

### §5 — Deployment configs, deployed nowhere

Both sites get their Dockerfiles and build setup so each is one command from
live: `proxploy-docs` follows `layerr-docs`'s pinned-node-build →
pinned-nginx-serve pattern; `proxploy-web` follows the static-build pattern
with an SPA fallback. Nothing is deployed, no DNS is configured, no hosting
account is touched.

**The two repos have no GitHub remote and do not exist on GitHub.** They stay
local unless the owner asks for private remotes; creating them is not this
phase's call to make.

## What this phase does not prove

- **No site is deployed and no page has been seen by a human.** There is no
  browser on this box for visual review. Builds passing and link tests passing
  do not mean the pages look right.
- **The documented install path is unreachable today** and cannot be verified
  end to end. 9a proved the installer works against a local channel; nothing
  here proves the public URLs the docs print, because those URLs do not exist.
- **The feature guides are assembled from phase notes, not from using the
  product against real hardware.** The standing "no live Proxmox node" gap
  applies, and 9b is evidence it hides real defects — two shipped features
  turned out to be non-functional on real hardware.

## Open item for the plan, not for implementation

The per-feature guides in §1 span eleven subsystems across five phases of
notes. The plan must decide whether that is one task or several, and must
state which note file is the source for each guide, so an implementer is never
inventing product behaviour from memory.
