# Phase 9c — proxploy-docs and proxploy-web

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a documentation site and a marketing site for Proxploy from the material the project already has, fix the three defects that would make them publish falsehoods, and deploy neither.

**Architecture:** Three fixes land in `proxploy-app` first, because the docs would otherwise document things that are wrong: the OpenAPI schema reports the wrong version, nothing exports that schema to a file, and the advertised install one-liner fails its own argument validation. Then `proxploy-docs` is built as Astro 6 + Starlight following `layerr-docs` (including its content test suite), and `proxploy-web` as a single-package Vite + React site following `layerr-web`/`folderr-web` minus their Replit scaffolding and monorepo layout.

**Tech Stack:** Astro 6 + Starlight + vitest + pagefind (docs); Vite 7 + React 19 + TypeScript + Tailwind v4 + wouter + shadcn/Radix (web); FastAPI (the three app fixes); Docker + nginx (build configs).

**Spec:** `docs/superpowers/specs/2026-08-06-phase-9c-web-and-docs-design.md`

---

## Global Constraints

Every task's requirements implicitly include this section.

- **NOTHING PUBLISHES.** No repository visibility change, no GitHub release, no `gh repo create`, no deployment, no DNS. `proxploy-app` stays private. `proxploy-web` and `proxploy-docs` have no GitHub remote and **must not be given one** — they stay local git repos.
- **Three repos are in play.** `proxploy-app` (existing, private, has a remote), `proxploy-web` and `proxploy-docs` (bare scaffolds at `/home/aasim/workspace/aspyrelabs/proxploy/proxploy-{web,docs}`, one commit each, `.gitignore` + `README.md` only, **no remote**). Commit in the repo you are working in. Never `git push` in the two new repos.
- **Commit directly to `main`.** No branches, in any of the three repos.
- **No hash-anchor URLs.** Links use real paths (`/install`, `/privacy-policy`), never `#anchors`. Hyphens for multi-word paths. Standing rule across every Aspyre Labs property.
- **The legal entity is `Aspyre Labs LLC, 30 N Gould St #Ste R, Sheridan, WY 82801, USA`.** Use it verbatim in legal copy and the footer.
- **No pricing, no tier comparison, no Paddle, no checkout.** All 81 entitlement flags resolve ON today; selling tiers the code gives away is out of scope and deferred to a later phase. Do not add a pricing route even as a stub.
- **Do not claim the product is downloadable.** The install page prints the command and states the release is not published yet.
- **backend suite floor:** `cd backend && .venv/bin/python -m pytest tests/ -q -m "not pve_integration and not e2e"` → **827 passed, 2 skipped, 4 deselected**. Never let this drop.
- **The two new repos are single-package.** No pnpm workspace, no `artifacts/<name>/` nesting, no `catalog:` protocol — every dependency needs a literal version. Use **npm**, not pnpm: there is no workspace to justify it, and `layerr-docs` (the closest precedent, also single-package) uses npm.
- **Never copy Replit scaffolding.** No `.replit`, `.replitignore`, `attached_assets/`, `@assets` alias, `@replit/vite-plugin-*` (cartographer, dev-banner, runtime-error-modal), or `isReplit` / `allowedHosts` logic. Assets go in `src/assets/` or `public/` with sane filenames.

---

## Task Order and Dependencies

```
proxploy-app fixes, independent, do first:
  Task 1  FastAPI version + pinning test
  Task 2  openapi.json export script      -> unblocks 11
  Task 3  install.sh one-liner actually works -> unblocks 5

proxploy-docs:
  Task 4  scaffold + content test suite    -> unblocks 5-12
  Task 5  install pages                    (needs 3)
  Task 6  getting-started + token guide
  Task 7  trust model
  Task 8  feature guides: phases 4-5
  Task 9  feature guides: phase 6
  Task 10 feature guides: phases 7-8
  Task 11 API reference                    (needs 2)
  Task 12 Dockerfile + CI

proxploy-web:
  Task 13 scaffold                         -> unblocks 14-16
  Task 14 landing/features/screenshots/install
  Task 15 about + legal
  Task 16 prerender + sitemap + Dockerfile

  Task 17 doc 11 amendment, notes, buildlog  (last)
```

Tasks 1, 2, 3 are parallel (different files). Tasks 5–11 are parallel once 4 lands, **except** each writes into `src/content/docs/` — assign disjoint subfolders and they will not collide. Tasks 14–16 are sequential (all touch `src/`).

---

## Task 1: The OpenAPI schema reports the wrong version

**Repo:** `proxploy-app`

**Files:**
- Modify: `backend/proxploy/main.py:142-143`
- Test: `backend/tests/test_openapi_surface.py`

**Interfaces:**
- Produces: `app.openapi()["info"]["version"] == proxploy.__version__` holds.

`backend/proxploy/__init__.py` is one line: `__version__ = "1.0.0"`. But `main.py:142-143` is:

```python
    app = FastAPI(title="Proxploy", docs_url="/api/docs",
                  openapi_url="/api/openapi.json", lifespan=lifespan)
```

No `version=`, so FastAPI defaults to `"0.1.0"`. 9a Task 1 existed to make `__version__` the single source of truth; the published API reference would contradict it on its first page.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_openapi_surface.py` (it already imports `make_app` from `tests.support`):

```python
def test_openapi_version_is_the_product_version(tmp_path):
    """9a Task 1 made __version__ the single source of truth. An OpenAPI
    schema that reports something else republishes the drift it removed."""
    import proxploy

    assert make_app(tmp_path).openapi()["info"]["version"] == proxploy.__version__
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/python -m pytest tests/test_openapi_surface.py -q`
Expected: FAIL — `'0.1.0' != '1.0.0'`.

- [ ] **Step 3: Implement**

```python
    app = FastAPI(title="Proxploy", version=__version__, docs_url="/api/docs",
                  openapi_url="/api/openapi.json", lifespan=lifespan)
```

Check `main.py`'s imports for `__version__` — `from proxploy import __version__` may already be there (the version route uses it). Reuse it; do not add a duplicate import.

- [ ] **Step 4: Run the test, then the full suite**

Run: `cd backend && .venv/bin/python -m pytest tests/test_openapi_surface.py -q`
Then: `cd backend && .venv/bin/python -m pytest tests/ -q -m "not pve_integration and not e2e"` — must stay ≥ 827 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/proxploy/main.py backend/tests/test_openapi_surface.py
git commit -m "fix(api): the OpenAPI schema reports the product version, not 0.1.0"
```

---

## Task 2: Export the OpenAPI schema to a file

**Repo:** `proxploy-app`

**Files:**
- Create: `backend/scripts/export_openapi.py`
- Modify: `.github/workflows/ci.yml`
- Test: `backend/tests/test_openapi_export.py`

**Interfaces:**
- Produces, for Task 11: `backend/scripts/export_openapi.py <outfile>` writes the schema as formatted JSON and prints the route count. With no argument it writes to stdout.

The schema is live at `/api/openapi.json` but nothing writes it to disk. A docs site needs a static artifact. `backend/tests/test_openapi_surface.py` already calls `app.openapi()` in-process via `make_app(tmp_path)` — follow that, so the script needs no running server.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_openapi_export.py`:

```python
"""The docs site's API reference is generated from this artifact, so the
export has to be a pure function of the app — no server, no network."""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_openapi.py"


def test_export_writes_a_schema_with_the_product_version(tmp_path):
    import proxploy

    out = tmp_path / "openapi.json"
    subprocess.run([sys.executable, str(SCRIPT), str(out)], check=True)
    schema = json.loads(out.read_text())
    assert schema["info"]["version"] == proxploy.__version__
    assert schema["info"]["title"] == "Proxploy"


def test_export_covers_every_registered_route(tmp_path):
    """Guards the failure mode where the export silently drops routers."""
    from tests.support import make_app

    out = tmp_path / "openapi.json"
    subprocess.run([sys.executable, str(SCRIPT), str(out)], check=True)
    exported = set(json.loads(out.read_text())["paths"])
    live = set(make_app(tmp_path / "live").openapi()["paths"])
    assert exported == live
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/python -m pytest tests/test_openapi_export.py -q`
Expected: FAIL — the script does not exist.

- [ ] **Step 3: Implement**

Create `backend/scripts/export_openapi.py`. Read `backend/scripts/check_executor_isolation.py` first for the established script conventions (shebang, how it resolves the package root, how CI invokes it) and match them.

```python
#!/usr/bin/env python
"""Write the OpenAPI schema to a file for the docs site's API reference.

Builds the app in-process (the same way tests/test_openapi_surface.py does)
rather than hitting a running server, so regenerating the reference needs
nothing but a checkout and a venv.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.support import make_app  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        schema = make_app(Path(tmp)).openapi()
    text = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text)
        print(f"wrote {sys.argv[1]}: {len(schema['paths'])} paths")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`sort_keys=True` matters: without it the diff churns on every regeneration and the CI drift check below becomes noise.

**Note the import of `tests.support`.** That module is excluded from the release tarball (`build_release.sh --exclude='tests'`), and so is `scripts/`? **Verify this** — `grep -n "exclude" packaging/build_release.sh`. If `scripts/` ships but `tests/` does not, this script would be broken in a release; in that case move the app construction inline into the script (mirroring `make_app`'s body) rather than importing from `tests`. Report which you found.

- [ ] **Step 4: Run the tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_openapi_export.py -q`
Expected: 2 passed.

- [ ] **Step 5: Add the CI drift check**

In `.github/workflows/ci.yml`'s `backend` job, after the pytest step:

```yaml
      - name: openapi schema exports cleanly
        run: python scripts/export_openapi.py /tmp/openapi.json
```

This proves the export runs; the docs repo regenerates from it rather than committing a copy here.

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/export_openapi.py backend/tests/test_openapi_export.py .github/workflows/ci.yml
git commit -m "feat(api): export the OpenAPI schema for the docs site"
```

---

## Task 3: Make the advertised one-liner actually work

**Repo:** `proxploy-app`

**Files:**
- Modify: `install.sh` (the argument defaults and the usage text)
- Test: `packaging/tests/test_oneliner.sh` (new)

**Interfaces:**
- Produces, for Task 5: `curl -fsSL <url>/install.sh | bash` works with no arguments, using a compiled-in release public key and a default channel.

`install.sh:21-23` sets `CHANNEL=""`, `VERSION=""`, `PUBKEY=""`; lines 198-199 and 212-214 hard-require all three. So the command in `install.sh`'s own header — and the one doc 10's DoD is phrased around — dies with `--channel is required`. Every 9a harness passed explicit flags, so the bare form was never executed.

- [ ] **Step 1: Write the failing test**

Create `packaging/tests/test_oneliner.sh`:

```bash
#!/usr/bin/env bash
# The advertised one-liner takes NO arguments. Every 9a harness passed
# --channel/--version/--pubkey explicitly, so the piped form nobody tested
# is exactly the form every user will run.
set -euo pipefail
cd "$(dirname "$0")/../.."

# Argument parsing and defaulting happen long before anything is fetched or
# installed, so a non-root dry parse is enough to prove the defaults exist:
# we assert it gets PAST argument validation, not that it installs.
out=$(bash install.sh --shape systemd --dry-parse 2>&1 || true)
case "$out" in
  *"--channel is required"*|*"--version is required"*|*"--pubkey is required"*)
    echo "FAIL: the no-argument form still demands flags:"; echo "$out"; exit 1 ;;
esac
echo "OK: install.sh has usable defaults for channel, version and pubkey"

grep -q "BEGIN PUBLIC KEY" install.sh \
  || { echo "FAIL: no release public key compiled into install.sh"; exit 1; }
echo "OK: the release public key is compiled in"
echo "PASS: one-liner harness"
```

- [ ] **Step 2: Run to verify failure**

Run: `bash packaging/tests/test_oneliner.sh`
Expected: FAIL on the first check.

- [ ] **Step 3: Implement**

Three changes to `install.sh`:

1. **Compile in the release public key.** Add near the top, after the layout constants:

```bash
# The release public key, compiled in rather than fetched. This is what makes
# the no-argument one-liner possible: there is nothing unpacked yet to read a
# key out of, so the key has to arrive WITH the script. That is sound because
# the script itself arrives over TLS from a host the user chose to trust —
# the same trust the curl already places. Replacing this block is step 1 of
# docs/runbooks/publishing-a-release.md.
RELEASE_PUBKEY_PEM='-----BEGIN PUBLIC KEY-----
...contents of backend/proxploy/release_pubkey.pem...
-----END PUBLIC KEY-----'
```

Copy the literal contents of `backend/proxploy/release_pubkey.pem` (the current placeholder). When `--pubkey` is not given, write `$RELEASE_PUBKEY_PEM` to a temp file and use that path.

2. **Default the channel and version:**

```bash
DEFAULT_CHANNEL="https://proxploy.com/releases/latest"
```

`VERSION` defaults to whatever the fetched `manifest.json` reports, so if `--version` is absent, fetch the manifest first and read `version` out of it with the same `sed` extraction `proxploy-update` already uses. **Do not invent a second manifest parser** — check `packaging/lib/common.sh` for an existing helper and reuse it; if the extraction is inline in `proxploy-update`, factor it into `common.sh` so both use one copy.

3. **Add `--dry-parse`**, which exits 0 immediately after argument validation and defaulting, printing the resolved channel/version/pubkey path. That is what makes this testable without root, network, or a real channel.

Update the usage text so `--channel`, `--version` and `--pubkey` read as optional overrides, and correct the header comment's one-liner if the default host differs from `proxploy.com`.

- [ ] **Step 4: Run the new test and the existing harnesses**

```bash
bash packaging/tests/test_oneliner.sh
bash packaging/tests/test_install.sh
bash packaging/tests/test_upgrade_rollback.sh
bash packaging/tests/test_pve_half.sh
```
All must pass — the existing three pass explicit flags and must keep working.

- [ ] **Step 5: shellcheck and commit**

```bash
docker run --rm -v "$PWD:/mnt" -w /mnt koalaman/shellcheck:stable -x -P SCRIPTDIR install.sh packaging/proxploy-update packaging/lib/*.sh packaging/tests/*.sh packaging/build_release.sh
git add install.sh packaging/tests/test_oneliner.sh packaging/lib/common.sh
git commit -m "fix(install): the one-liner works with no arguments"
```

---

## Task 4: proxploy-docs scaffold and its content test suite

**Repo:** `proxploy-docs` (`/home/aasim/workspace/aspyrelabs/proxploy/proxploy-docs`)

**Files:**
- Create: `package.json`, `astro.config.mjs`, `vitest.config.ts`, `src/content.config.ts`, `src/content/docs/index.md`, `tests/utils.ts`, `tests/frontmatter.test.ts`, `tests/links.test.ts`, `tests/content-consistency.test.ts`, `tests/build.test.ts`

**Interfaces:**
- Produces, for Tasks 5–12: a building Starlight site with `npm test` running four content checks. Sidebar groups map to `src/content/docs/{install,getting-started,trust,guides,reference}/` via `autogenerate`.

Copy `layerr-docs` (`/home/aasim/workspace/aspyrelabs/layerr/layerr-docs`) as the template. **Read its files directly** — `package.json`, `astro.config.mjs`, `vitest.config.ts`, `src/content.config.ts`, and all of `tests/` — and adapt rather than retyping from this plan.

- [ ] **Step 1: Scaffold**

`package.json` — same shape as layerr-docs', minus the Excalidraw diagram tooling (no diagrams in scope):

```json
{
  "name": "proxploy-docs",
  "type": "module",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "astro dev",
    "build": "astro build",
    "preview": "astro preview",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "@astrojs/starlight": "^0.39.2",
    "astro": "^6.4.2",
    "sharp": "^0.34.5"
  },
  "devDependencies": {
    "github-slugger": "^2.0.0",
    "gray-matter": "^4.0.3",
    "vitest": "^4.1.10"
  }
}
```

`astro.config.mjs` — `site: 'https://docs.proxploy.com'`, `title: 'Proxploy'`, tagline from doc 00: *"Unraid's experience, but for Proxmox."*, and five `autogenerate` sidebar groups for `install`, `getting-started`, `trust`, `guides`, `reference`.

`src/content.config.ts` is layerr-docs' file verbatim (stock `docsLoader()` + `docsSchema()`).

**Do not create a `tsconfig.json`** — layerr-docs deliberately has none and relies on Astro 6's zero-config TS handling.

- [ ] **Step 2: Copy the test suite**

`tests/utils.ts` transfers **verbatim** — content-file discovery, frontmatter parsing, link extraction (markdown + raw `<img>`), and heading-slug generation using the same `github-slugger` Astro's pipeline uses. Do not rewrite it.

`tests/frontmatter.test.ts`, `tests/links.test.ts`, `tests/build.test.ts` transfer with only the obvious renames.

`tests/content-consistency.test.ts` must be **rewritten for this site** — layerr's version pins layerr-specific claims (intelligence-layer counts, routing categories) that do not exist here. Write the equivalent for Proxploy: assert that every guide under `guides/` is reachable from the index page's guide list, and that any *"N feature guides"*-style claim in `index.md` matches the actual file count. The point of the test is not the specific claim but the class of bug — a number in prose that silently stops matching the corpus.

- [ ] **Step 3: A minimal index page so the build has something to build**

`src/content/docs/index.md` with `title` and `description` frontmatter only (that is the pattern across layerr-docs' corpus) and no H1 in the body — `frontmatter.test.ts` enforces that, since the frontmatter `title` already renders as the heading.

- [ ] **Step 4: Verify**

```bash
cd /home/aasim/workspace/aspyrelabs/proxploy/proxploy-docs
npm install
npm run build
npm test
```
Expected: build succeeds; all four test files pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(docs): Astro + Starlight scaffold with the content test suite"
```

This repo has **no remote**. Do not push.

---

## Task 5: The install pages

**Repo:** `proxploy-docs`
**Files:** Create `src/content/docs/install/{index,lxc,docker,updating}.md`
**Interfaces:** Consumes Task 3's working one-liner.

**Sources — read these, do not invent behaviour:**
- `docs/notes/phase-9a-install-update.md:9-73` ("What shipped, per subsystem") in `proxploy-app`
- `install.sh`'s usage text (lines 31-63) and its header comment
- `packaging/docker/` for the Docker shape
- `docs/notes/phase-9a-install-update.md:99-127` (the rollback bug) — useful for the updating page's failure-modes section

- [ ] **Step 1: Write the pages**

- `install/index.md` — what installing does to a node, the three shapes (`lxc` on a Proxmox host, `systemd` on a plain Debian box, `docker`), and which to pick.
- `install/lxc.md` — the one-liner, what the PVE-host half does (`pct create`, push, exec), and the `--ctid`/`--storage`/`--bridge`/`--hostname` overrides.
- `install/docker.md` — compose file, and **the update boundary**: a Docker install never self-applies; `POST /meta/update` returns 409 with `docker compose pull && docker compose up -d`. State this as a deliberate capability decision, not a missing feature.
- `install/updating.md` — in-app update, what `proxploy-update` does in order (backup → verify → migrate → switch → health-check → roll back), and that a failed update rolls back automatically.

**Every install page must state that the release is not published yet** and the command will not fetch anything until it is. Put it in one consistent admonition, not scattered prose.

- [ ] **Step 2: Verify and commit**

```bash
npm test && npm run build
git add src/content/docs/install && git commit -m "docs: install pages"
```

---

## Task 6: Getting started and the minimal-privilege token guide

**Repo:** `proxploy-docs`
**Files:** Create `src/content/docs/getting-started/{index,proxmox-token,ssh-key}.md`

**Sources:**
- `docs/08-security-secrets-design.md` §2 (lines 22-67) — this has the **complete** capability → role → privileges table and the `pveum` generation flow. Transcribe it; do not derive privileges from code.
- `frontend/src/routes/onboarding.tsx` for the actual wizard steps as built in 9b.

- [ ] **Step 1: Write the pages**

- `getting-started/index.md` — the wizard walkthrough: admin account → first host → authorize SSH (optional) → land on Cluster. Mention the host step is skippable and a host can be added later from Settings.
- `getting-started/proxmox-token.md` — the four roles (`ProxployAudit`, `ProxployLifecycle`, `ProxployConsole`, `ProxployBackup`), their exact privileges, why privilege-separated tokens (`--privsep 1`) are used, and the copy-paste `pveum` script.
- `getting-started/ssh-key.md` — what SSH enrolment is for, that it is optional, and how to authorize the key.

**Carry doc 08's own caveat into the page, do not drop it:** *"Privilege names must be re-verified against the target PVE major version at implementation time; PVE occasionally splits privileges (as it did with `VM.Config.*`)."* A privilege table that is silently wrong for the reader's PVE version is worse than a link to upstream docs. State which PVE version the table was verified against.

- [ ] **Step 2: Verify and commit**

```bash
npm test && npm run build
git add src/content/docs/getting-started && git commit -m "docs: getting started and the minimal-privilege token guide"
```

---

## Task 7: The trust model page

**Repo:** `proxploy-docs`
**Files:** Create `src/content/docs/trust/index.md`

Doc 10 requires the trust model with "root-on-node stated plainly". This is the page a sceptical self-hoster reads before piping a script into `bash`. **Hedging it is the failure mode.**

**Sources, quote-faithful:**
- `CONSENT_NOTE` in `backend/proxploy/api/hosts.py:27-31`
- `docs/08-security-secrets-design.md:106-116` (why root SSH is structurally necessary — the Phase 4 spike found Proxmox has no LXC `exec` REST endpoint at all)
- `docs/08-security-secrets-design.md:117-145` (key handling, audit logging, host-key TOFU pinning)
- `docs/08-security-secrets-design.md:235` residual-risk row 1 — **"Root is root. A malicious script owns the node. Identical to running it yourself — Proxploy adds provenance and evidence, not sandboxing."** That sentence, or something equally direct, belongs on the page.

- [ ] **Step 1: Write the page**

Cover: the root shell and why it cannot be avoided; that SSH enrolment is optional and everything except installs/updates/migration works without it; audit logging and output archival; host-key pinning with hard-fail on change; the minimally-privileged API token; update signature verification (Ed25519 over raw manifest bytes before parsing, then sha256, then unpack, downgrades refused); that the release public key ships inside the artifact so rotation requires a release signed by the old key.

Also state: **the repository is private and the product is not source-available today.** Do not repeat doc 11's source-available claim — Task 17 records that contradiction as an open decision.

Include the `test-fixture-1` note: `backend/tests/contract/entitlement_token.fixture.json` carries a real test-only Ed25519 private key; it cannot grant anything because production loads only `BUNDLED_PUBLIC_KEYS` (one entry, `dev-2026-07`), unknown `kid` is hard-rejected with no fallback, and `build_release.sh --exclude='tests'` keeps it out of the tarball.

- [ ] **Step 2: Verify and commit**

```bash
npm test && npm run build
git add src/content/docs/trust && git commit -m "docs: the trust model, stated plainly"
```

---

## Task 8: Feature guides — App Store and consoles

**Repo:** `proxploy-docs`
**Files:** Create `src/content/docs/guides/{apps,app-store,consoles}.md`

**Sources — exact ranges, these are the only sections containing product behaviour rather than verification bookkeeping:**
- `docs/notes/phase-4-store.md:3-143` — App Store: SSH executor with host-key TOFU pinning, the install-feasibility classifier that parses community-scripts `install.sh` for unguarded prompts, catalog ingest pinned to an immutable upstream git commit SHA (not `main`), and the `app.install` job streaming output to the job log.
- `docs/notes/phase-5-console.md:3-95` — consoles: `termproxy`/`vncproxy`, single-use short-TTL tickets bound to one target, the CT/node text terminal, VM noVNC, and that node shell needs a separate `node_shell_enabled` opt-in because it is effectively root on the node.

- [ ] **Step 1: Write the guides, then verify and commit**

Write for a user, not a reviewer: what the feature does, how to use it, what it will refuse to do and why. Do not copy the notes' phrasing wholesale — they are written for the project's own record.

```bash
npm test && npm run build
git add src/content/docs/guides && git commit -m "docs: guides for apps, the App Store and consoles"
```

---

## Task 9: Feature guides — storage, network, backups, VMs

**Repo:** `proxploy-docs`
**Files:** Create `src/content/docs/guides/{storage,network,backups,vms}.md`

**Source:** `docs/notes/phase-6-infra.md:3-90` — storage attach/upload/delete with spooled multipart uploads; network bridge/NIC staged-edit-then-apply with typed node-name confirmation; backup sync/restore/prune (in-place restore refuses running or self-target guests); VM snapshot/create/clone/delete (delete is "owner" role behind a 3-gate confirmation).

The refusals are the interesting part for a user — document what each guard prevents and why.

- [ ] **Step 1: Write the guides, then verify and commit**

```bash
npm test && npm run build
git add src/content/docs/guides && git commit -m "docs: guides for storage, network, backups and VMs"
```

---

## Task 10: Feature guides — operations and multi-user

**Repo:** `proxploy-docs`
**Files:** Create `src/content/docs/guides/{schedules,updates,alerts,teams,sso,two-factor,api-tokens,migration}.md`

**Sources:**
- `docs/notes/phase-7-operate.md:3-80` — cron `Scheduler` with seeded system schedules, the `app.update` job re-running the pinned catalog script over the same SSH path as install, and the alert engine (continuous-breach duration semantics, auto-recovery, SSE + notifier).
- `docs/notes/phase-8-scale.md:6-61` — casbin RBAC-with-domains via a single `authorize()` path, teams as domains, OIDC with PKCE and deny-by-default JIT provisioning, TOTP two-step login with one-time recovery codes, `ppk_…` scoped API tokens that can only narrow their owner's rights, and migration strategy selection (cluster-native / shared-storage / vzdump+SFTP) with measured downtime.

- [ ] **Step 1: Write the guides, then verify and commit**

```bash
npm test && npm run build
git add src/content/docs/guides && git commit -m "docs: guides for schedules, updates, alerts, teams, SSO, 2FA, tokens and migration"
```

---

## Task 11: The API reference

**Repo:** `proxploy-docs`
**Files:** Create `src/content/docs/reference/`, modify `astro.config.mjs`, `package.json`

**Interfaces:** Consumes Task 2's `export_openapi.py`.

The app registers **127 routes** across 22 router files. `layerr-docs` hand-wrote its API reference (577 lines) and **has no OpenAPI plugin** — there is no in-house precedent here, so this is new ground.

- [ ] **Step 1: Verify the plugin works before committing to it**

```bash
cd /home/aasim/workspace/aspyrelabs/proxploy/proxploy-docs
npm install starlight-openapi
```

Check its peer-dependency range against the installed `@astrojs/starlight` (`^0.39.2`) and `astro` (`^6.4.2`). Plugin compatibility tracks Starlight's major closely.

**If it does not support these versions, do not force it and do not downgrade Starlight.** Fall back to generating markdown pages from `openapi.json` with a script in this repo and committing the output — that keeps the "regenerate, never hand-edit" property. **Hand-authoring 127 endpoints is not a fallback and is ruled out.** Report which path you took and why.

- [ ] **Step 2: Wire it up**

Generate the schema into this repo and point the plugin at it:

```bash
cd ../proxploy-app/backend && .venv/bin/python scripts/export_openapi.py ../../proxploy-docs/src/openapi.json
```

Add an npm script so regeneration is one command, and document in the repo README that `src/openapi.json` is generated — never hand-edited.

- [ ] **Step 3: Verify and commit**

```bash
npm test && npm run build
git add -A && git commit -m "docs: API reference generated from the OpenAPI schema"
```

Confirm the built reference reports version `1.0.0` (Task 1), not `0.1.0`.

---

## Task 12: Docs Dockerfile and CI

**Repo:** `proxploy-docs`
**Files:** Create `Dockerfile`, `.dockerignore`, `.github/workflows/test.yml`, `README.md`

- [ ] **Step 1: Dockerfile**

Copy `layerr-docs`' two-stage pattern verbatim in shape: pinned `node:22.18.0-slim` build stage running `npm ci --omit=dev && npm run build`, then pinned `nginx:1.27.4-alpine` serving `dist/`. **Pin both base images by digest** as layerr-docs does. It has no `nginx.conf` — stock nginx config is sufficient for a static Starlight build; do not add one.

- [ ] **Step 2: CI**

`.github/workflows/test.yml` copying layerr-docs' workflow: on push/PR to `main`, `actions/setup-node@v4` with `node-version: 22` and `cache: npm`, then `npm ci` and `npm test`.

**This workflow will not run anywhere** — the repo has no GitHub remote and must not be given one. It ships so CI works the day the repo is pushed.

- [ ] **Step 3: README** — what the site is, how to run it locally, and that `src/openapi.json` is generated by `proxploy-app/backend/scripts/export_openapi.py`.

- [ ] **Step 4: Verify and commit**

```bash
docker build -t proxploy-docs-test . && docker run --rm -d -p 8081:80 --name pd-test proxploy-docs-test
curl -fsS http://127.0.0.1:8081/ | grep -qi proxploy && echo "OK: docs serve"
docker rm -f pd-test
git add -A && git commit -m "build(docs): Dockerfile and CI"
```

---

## Task 13: proxploy-web scaffold

**Repo:** `proxploy-web` (`/home/aasim/workspace/aspyrelabs/proxploy/proxploy-web`)
**Files:** Create `package.json`, `vite.config.ts`, `tsconfig.json`, `index.html`, `src/main.tsx`, `src/App.tsx`, `src/index.css`, `components.json`, `src/lib/utils.ts`

**Interfaces:** Produces, for Tasks 14–16: a Vite + React + Tailwind v4 app with `wouter` routing and the `@/` → `src/` alias.

Single package at the repo root — **no `artifacts/` nesting, no pnpm workspace, no `catalog:` references.** Every dependency needs a literal version. Confirmed pins from the sibling catalog: `react` and `react-dom` `19.1.0`, `vite` `^7.3.6`, `tailwindcss` and `@tailwindcss/vite` `^4.3.2`. Read the remaining versions out of `layerr-web/artifacts/layerr-web/package.json` and the workspace `pnpm-workspace.yaml` catalog block rather than guessing.

- [ ] **Step 1: Scaffold**

`vite.config.ts` is `layerr-web`'s **minus every Replit branch** — no `@replit/*` plugins, no `isReplit`, no `allowedHosts`, no `@assets` alias:

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname, "src") },
    dedupe: ["react", "react-dom"],
  },
  build: { outDir: "dist/public", emptyOutDir: true },
});
```

`tsconfig.json` must be **self-contained** — there is no `tsconfig.base.json` to extend here. Take the merged settings from `layerr-web`'s pair (strict null checks, `moduleResolution: "bundler"`, `target: "es2022"`, `jsx: "preserve"`, `noEmit: true`) and add `"paths": {"@/*": ["./src/*"]}`.

`src/index.css` follows layerr-web's Tailwind v4 structure — `@import "tailwindcss"`, `@theme inline` mapping `--color-*` to CSS variables, and a `:root` block — but with **Proxploy's own palette**, not layerr's blue/cyan. Reuse the app's tokens from `proxploy-app/frontend/src/styles/tokens.css` (`--ink`, `--panel`, `--amber`, `--green`, …) so the marketing site and the product look like the same product.

Include only the shadcn primitives actually needed (button, card, accordion for an FAQ). Do not install all 28 Radix packages up front.

- [ ] **Step 2: Verify and commit**

```bash
cd /home/aasim/workspace/aspyrelabs/proxploy/proxploy-web
npm install && npm run build
git add -A && git commit -m "feat(web): Vite + React + Tailwind scaffold"
```

No remote. Do not push.

---

## Task 14: Landing, features, screenshots, install

**Repo:** `proxploy-web`
**Files:** Create `src/pages/{home,features,screenshots,install,not-found}.tsx`, `src/lib/site-meta.ts`, `src/components/{Navbar,Footer}.tsx`; modify `src/App.tsx`

**Interfaces:** Produces, for Task 16: `routeMeta`, `prerenderRoutes` and `SITE_URL` exported from `src/lib/site-meta.ts` — `scripts/prerender.mjs` imports exactly these three names.

- [ ] **Step 1: `src/lib/site-meta.ts` first**

Task 16's prerender script depends on its shape:

```ts
export const SITE_URL = "https://proxploy.com";

export const routeMeta: Record<string, { title: string; description: string }> = {
  "/": { title: "Proxploy — a web UI for Proxmox VE", description: "..." },
  // one entry per prerendered route
};

export const prerenderRoutes = Object.keys(routeMeta);
```

- [ ] **Step 2: Pages and routing**

Wire routes in `src/App.tsx` with `wouter`'s `Switch`/`Route`, following `layerr-web/src/App.tsx`. **Real paths only** (`/features`, `/screenshots`, `/install`) — no hash anchors.

Positioning comes from `docs/00-decision-brief.md:12-13`: *"A self-hosted, web-based management platform for Proxmox VE — 'Unraid's experience, but for Proxmox.'"*

The install page prints the one-liner from Task 3 and **states the release is not published yet**. No pricing route, and no "Download" call-to-action that implies a working download.

Screenshots: there is no browser here to capture the product UI. Either ship the page with a placeholder that is obviously a placeholder, or omit the route — **do not fabricate screenshots or describe UI you have not seen.** Say which you did in the commit.

- [ ] **Step 3: Verify and commit**

```bash
npm run build
git add -A && git commit -m "feat(web): landing, features, screenshots and install"
```

---

## Task 15: About and legal pages

**Repo:** `proxploy-web`
**Files:** Create `src/components/LegalLayout.tsx`, `src/pages/{about,privacy-policy,terms-of-service,refund-policy}.tsx`; modify `src/App.tsx`, `src/lib/site-meta.ts`

- [ ] **Step 1: `LegalLayout`**

Take **folderr-web's** approach over layerr-web's: the layout accepts `title` and `lastUpdated` as props and renders them, and exports a `LegalSection` helper. Layerr-web's version makes each page redefine its own `Section`/`Clause` helpers, which is duplication its own structure admits to. Export `Section` and `Clause` from the layout module so all four pages share one copy.

- [ ] **Step 2: The pages**

Use `layerr-web/src/pages/privacy-policy.tsx` as the content template — it is well-structured and already names the right entity. Adapt for Proxploy, and **be accurate about what is true here**:

- Proxploy is **self-hosted**; the product sends no data to Aspyre Labs by default.
- There is no checkout, no Paddle, and no analytics on this site unless you add one — **do not copy layerr's sub-processor list wholesale.** It names Paddle, Plausible and Postmark, none of which apply. Listing sub-processors that do not exist is a false statement in a legal document.
- Entity: **Aspyre Labs LLC, 30 N Gould St #Ste R, Sheridan, WY 82801, USA**.
- Keep the "not legal advice" disclaimer layerr-web carries.

A refund policy for a product with no purchase path is questionable. **Either omit it, or state plainly that paid plans are not yet available.** Say which you chose in the commit.

- [ ] **Step 3: Verify and commit**

```bash
npm run build
git add -A && git commit -m "feat(web): about and legal pages"
```

---

## Task 16: Prerender, sitemap, and the deploy config

**Repo:** `proxploy-web`
**Files:** Create `scripts/prerender.mjs`, `scripts/generate-sitemap.js`, `src/entry-server.tsx`, `Dockerfile`, `nginx.conf`, `.dockerignore`; modify `package.json`, `src/main.tsx`

**Interfaces:** Consumes `routeMeta`, `prerenderRoutes`, `SITE_URL` from Task 14.

- [ ] **Step 1: Prerender**

`scripts/prerender.mjs` and `src/entry-server.tsx` transfer from `layerr-web` essentially verbatim — read them and copy. `src/main.tsx` needs layerr-web's hydrate-or-render branch:

```tsx
if (container.hasChildNodes()) {
  hydrateRoot(container, <App />);
} else {
  createRoot(container).render(<App />);
}
```

Without it, prerendered markup is thrown away on load.

`scripts/generate-sitemap.js` transfers with `BASE_URL` changed to `https://proxploy.com`. It extracts routes by regex from `src/App.tsx`; keep that and keep an `EXCLUDE` set even if empty today.

The build script becomes the four-stage form from layerr-web: sitemap → client build → SSR build → prerender.

- [ ] **Step 2: Dockerfile**

Use **folderr-web's** nginx pattern, not layerr-web's. Layerr-web runs a separate Express `web-server` artifact because it is a monorepo; this repo is single-package and static, so the simpler build-then-nginx image is correct. Copy folderr-web's `nginx.conf` verbatim — its `try_files $uri $uri.html /index.html` ordering serves prerendered routes before the SPA shell, which is exactly what Task 16 produces.

Adapt the build stage to npm and a single package (no workspace manifest copying).

- [ ] **Step 3: Verify the prerender actually produced static HTML**

```bash
npm run build
test -f dist/public/install/index.html || { echo "FAIL: install route not prerendered"; exit 1; }
grep -q "Proxploy" dist/public/install/index.html || { echo "FAIL: prerendered HTML is empty"; exit 1; }
docker build -t proxploy-web-test . && docker run --rm -d -p 8082:80 --name pw-test proxploy-web-test
curl -fsS http://127.0.0.1:8082/install | grep -qi proxploy && echo "OK: web serves prerendered route"
docker rm -f pw-test
```

The `grep` matters: a prerender that silently emits the empty SPA shell still writes files, and the shell would pass a bare `test -f`.

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "build(web): prerender, sitemap and the nginx image"
```

---

## Task 17: Doc 11 amendment, notes, buildlog

**Repo:** `proxploy-app`
**Files:** Modify `docs/11-risks-open-decisions.md`, `buildlog.md`; create `docs/notes/phase-9c-web-and-docs.md`

- [ ] **Step 1: Amend doc 11**

`docs/11-risks-open-decisions.md:165-180` states Proxploy is source-available and that patching `Entitlements.enabled()` is *"accepted, not mitigated away"*, because customers buy *"support, updates, and honesty, not un-patchable bits"*. The repository is private and staying private.

**Record this as an open decision with both positions; do not silently rewrite history.** State: what doc 11 says, that the repo is private as of 2026-08-06, that the private posture makes the patching risk moot (nobody can patch what nobody can read), that it also removes the source-available claim from any marketing or trust copy, and that resolving it — amend the doc, or make the repo public — is an open decision owned by Aspyre Labs.

- [ ] **Step 2: Notes**

`docs/notes/phase-9c-web-and-docs.md`, same skeleton as `phase-9b-onboarding-polish.md`: what shipped per subsystem; findings; residual limitations; gate numbers; commit range.

**Findings that must appear:**
- The advertised one-liner did not work — `install.sh` required three flags it never defaulted, so `curl … | bash` died on `--channel is required`. The 9a harnesses all passed explicit flags, so the form every user would run was the one form never executed. Third instance this phase-group of tested path ≠ advertised path.
- The OpenAPI schema reported `0.1.0` while `__version__` was `1.0.0`, which would have published a contradiction on the reference's first page.
- `layerr-docs` has no OpenAPI plugin — its 577-line API reference is hand-written — so the generated reference here is new ground, not a copied pattern.

**Residual limitations, at minimum:**
- **Nothing is deployed and no page has been seen by a human.** There is no browser here for visual review; passing builds and link tests do not mean the pages look right.
- **The documented install path is unreachable** and cannot be verified end to end, because the release is unpublished.
- **The feature guides are assembled from phase notes**, not from using the product against real hardware — and 9b is evidence that gap hides real defects.
- Whatever Task 14 decided about screenshots, and Task 15 about the refund policy.

- [ ] **Step 3: Buildlog** — the phase entry in the established format, including "Known gaps, stated plainly".

- [ ] **Step 4: Record real numbers**

Backend suite, both new repos' `npm test` and `npm run build`, both Docker builds. **Never write a projected number.**

- [ ] **Step 5: Commit**

```bash
git add docs/11-risks-open-decisions.md docs/notes/phase-9c-web-and-docs.md buildlog.md
git commit -m "docs(phase-9c): doc 11 amendment, notes, buildlog"
```

---

## Self-Review

1. **Spec coverage.** §1 docs stack → Tasks 4, 12. §2 trust model → Task 7. §3 marketing site → Tasks 13–16. §4 OpenAPI export and version → Tasks 1, 2, 11. §5 the one-liner → Task 3. §6 deploy configs, deployed nowhere → Tasks 12, 16, and the global constraint. Install/getting-started/guides content → Tasks 5, 6, 8, 9, 10. Doc 11 contradiction → Task 17. Out-of-scope pricing → global constraints, enforced by absence of any pricing task.

2. **Placeholder scan.** No "TBD" or "handle appropriately". Five places direct the implementer to check a fact and say what to do with either answer: whether `scripts/` ships in the release tarball (Task 2), whether `starlight-openapi` supports the pinned Starlight (Task 11), whether a manifest-version helper already exists in `common.sh` (Task 3), the screenshots decision (Task 14), and the refund-policy decision (Task 15). Each states both branches.

3. **Type consistency.** `routeMeta` / `prerenderRoutes` / `SITE_URL` are defined in Task 14 and consumed by name in Task 16. `export_openapi.py <outfile>` is defined in Task 2 and invoked identically in Task 11. `--dry-parse` is introduced in Task 3 and used only by its own test. Sidebar directory names (`install`, `getting-started`, `trust`, `guides`, `reference`) are fixed in Task 4 and every content task writes into exactly those.

4. **Honesty.** The three things this phase cannot prove — a deployed site, a working install URL, and that any page looks right — are in the spec, in Task 17's residual limitations, and in the install pages' own admonition. The doc 11 contradiction is recorded rather than resolved by fiat.
