---
name: run-proxploy
description: Build, launch, drive, and screenshot the Proxploy dev app (FastAPI backend + React/Vite frontend). Use when asked to run, start, boot, smoke-test, screenshot, or visually check Proxploy, to reset onboarding to a fresh install, or to run its vitest/Playwright suites.
---

Proxploy ships as one product: a FastAPI backend (`backend/`) and a React 19 +
Vite frontend (`frontend/`). In dev they run as two processes; the frontend
proxies `/api` to the backend. The agent path is
`.claude/skills/run-proxploy/driver.mjs`, which drives the running app with
Playwright's Chromium and prints what it found.

**All paths below are relative to the repo root.** Verified on macOS (darwin,
Apple Silicon); the commands are what actually ran, not what the README claims.

## Prerequisites

The backend needs Python ≥3.11 and macOS system Python is 3.9. Use Homebrew's:

```bash
/opt/homebrew/bin/python3.12 --version   # 3.12.x
```

## Setup

Once per checkout. Both are slow (~1–2 min each); run them in the background.

```bash
cd backend && /opt/homebrew/bin/python3.12 -m venv .venv \
  && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -e '.[dev]'

cd frontend && npm install
cd frontend && npx playwright install chromium   # needed by the driver too
```

## Run

Two background processes. Start the backend first.

```bash
cd backend && .venv/bin/uvicorn --factory proxploy.main:create_app --reload --port 8000
cd frontend && npm run dev
```

Wait for both, then drive. `/meta/onboarding` is the health probe to use —
it is public, whereas `/meta/version` 401s when unauthenticated:

```bash
curl -sS --retry 30 --retry-connrefused http://127.0.0.1:8000/api/v1/meta/onboarding
```

## Run (agent path) — the driver

```bash
node .claude/skills/run-proxploy/driver.mjs smoke
node .claude/skills/run-proxploy/driver.mjs shot /tmp/pp.png /onboarding
node .claude/skills/run-proxploy/driver.mjs measure aside 'aside svg' /onboarding
node .claude/skills/run-proxploy/driver.mjs text /onboarding
```

- `smoke` — backend onboarding state, landed URL, title, console errors.
- `shot <out.png> [path]` — screenshot at 1440×900. **Open the file and look at
  it.** A blank frame is a failed launch, not a pass.
- `measure <css…> [path]` — bounding boxes as JSON. Use this for any layout
  claim; overlap is obvious in numbers and arguable in a screenshot.
- `text [path]` — rendered body text, for asserting copy without a screenshot.

Override targets with `PROXPLOY_WEB` / `PROXPLOY_API`.

## Reset to a fresh install

Onboarding is gated on server state, so "let me see the wizard again" means a
new database. Move the **whole** data dir — the SQLite file and `master.key`
must stay together, or the backend refuses to boot with `MasterKeyMissing`:

```bash
lsof -ti :8000 | xargs -r kill
cd backend && mv data "data.bak-$(date +%H%M%S)"
# restart uvicorn; it recreates data/ with a fresh DB and key
```

Confirm with `smoke`: `admin_exists` should be `false`.

## Test

```bash
cd frontend && npx vitest run --no-file-parallelism   # 331 tests
cd frontend && npx tsc -b && npx oxlint
cd backend && .venv/bin/python -m pytest tests/ -q -m "not pve_integration and not e2e"
```

Playwright e2e spawns **its own** backend and frontend, so the dev servers must
be stopped first:

```bash
lsof -ti :8000 | xargs -r kill
lsof -ti :5173 | xargs -r kill
cd frontend && npx playwright test journey.spec.ts
```

## Gotchas

- **Vite 8 binds IPv6 here.** `http://localhost:5173` works;
  `http://127.0.0.1:5173` is refused outright. The backend answers on either.
  This costs a confusing "connection refused" if you assume they are
  interchangeable.
- **Vitest must be run from `frontend/`.** From the repo root it picks up no
  jsdom config and *every* test fails with `ReferenceError: document is not
  defined` — which reads like a broken component, not a wrong cwd. Note the
  `RUN v4.x <path>` line vitest prints: if that path is the repo root, that is
  the bug. Cost me two false diagnoses in one session.
- **`--no-file-parallelism` is required**, per the README; suites flake without
  it.
- **The driver imports Playwright by absolute path** out of `frontend/`.
  `.claude/skills/` has no `node_modules` and is in no package, so a bare
  `import 'playwright'` does not resolve.
- **Playwright e2e refuses to start while the dev backend is up** —
  `http://127.0.0.1:8000/api/v1/meta/health is already used`. Kill port 8000
  first.
- **A headless browser has no session cookie**, so `/auth/me` 401s even when an
  admin exists. Pages that branch on the signed-in user render their
  signed-out state under the driver. That is the driver, not a bug.
- **`journey.spec.ts` fails at "install an app"** with `install script exited 0
  but CT 150 does not exist on pve-01`. Pre-existing and unrelated to whatever
  you are changing: `backend/tests/e2e_server.py` only mirrors `kind == "qemu"`
  guest-creates into the fake node's resource listing, and an App Store install
  creates an **LXC** container over fake SSH, which the fake PVE never sees.
  The onboarding steps before it all pass.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Failed to connect to 127.0.0.1 port 5173` | Use `localhost:5173`. Vite binds IPv6. |
| Every vitest test: `document is not defined` | You are in the repo root. `cd frontend` first. |
| `meta/health is already used` starting Playwright | Kill ports 8000 and 5173. |
| Backend exits with `MasterKeyMissing` | `data/proxploy.db` exists but `data/master.key` is gone. `SecretStore.ensure_key_file` refuses to regenerate a key over an existing DB on purpose (it would strand every stored credential as undecryptable ciphertext). Restore the key, or move the whole `data/` dir aside to re-onboard. |
| `pip install -e '.[dev]'` fails on Python 3.9 | `pyproject.toml` requires ≥3.11. Build the venv with `/opt/homebrew/bin/python3.12`. |
| Driver: `Cannot find package 'playwright'` | `cd frontend && npm install && npx playwright install chromium`. |
