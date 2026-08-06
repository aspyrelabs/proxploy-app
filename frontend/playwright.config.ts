import { defineConfig, devices } from '@playwright/test'

import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.dirname(fileURLToPath(import.meta.url))
const backendDir = path.resolve(root, '../backend')

// Throwaway data dir + SQLite DB for the e2e run only — never the developer's
// real backend/data/. The wipe is a prefix on the backend command below rather
// than code at this module's scope: Playwright loads the config once per
// process (runner + every worker), so a module-scope rmSync runs again after
// the backend has booted and deletes the SQLite file out from under it
// mid-run. globalSetup can't do it either — webServer starts BEFORE
// globalSetup, so it would find the previous run's DB and refuse to boot
// (MasterKeyMissing: db exists, key gone). The command prefix is the one
// place that runs exactly once, in the right order.
const dataDir = path.resolve(root, '.e2e-data')

const BACKEND_PORT = 8000
const FRONTEND_PORT = 5173

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  reporter: 'list',
  use: {
    baseURL: `http://127.0.0.1:${FRONTEND_PORT}`,
    trace: 'on-first-retry',
  },
  projects: [
    // journey.spec.ts is the ONLY spec that drives a truly fresh install —
    // every other spec's seedAdmin() (helpers.ts) is idempotent and happy to
    // find an admin already there. All specs share one backend process/DB
    // for the whole run (webServer above), and fullyParallel schedules every
    // file's tests across workers with no ordering guarantee between files —
    // so without this, smoke/light-theme's seedAdmin() can win the race and
    // create their admin first, leaving journey.spec.ts's own "create the
    // admin through the wizard" step nothing to do. A project `dependencies`
    // edge is Playwright's documented way to force one project's tests to
    // finish before another's start; it is not overkill for a one-test file.
    { name: 'journey', testMatch: 'journey.spec.ts', use: { ...devices['Desktop Chrome'] } },
    {
      name: 'chromium',
      testIgnore: 'journey.spec.ts',
      dependencies: ['journey'],
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: [
    {
      // `--factory`: proxploy.main has no module-level ASGI `app`, only
      // create_app() (see main.py) — uvicorn calls it for us with no args,
      // so it picks up Settings() from the PROXPLOY_* env below.
      command: `rm -rf '${dataDir}' && mkdir -p '${dataDir}' && `
        + `${path.join(backendDir, '.venv/bin/uvicorn')} tests.e2e_server:create_e2e_app `
        + `--factory --host 127.0.0.1 --port ${BACKEND_PORT}`,
      cwd: backendDir,
      url: `http://127.0.0.1:${BACKEND_PORT}/api/v1/meta/health`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        PROXPLOY_DATA_DIR: dataDir,
        PROXPLOY_DB_URL: `sqlite:///${path.join(dataDir, 'proxploy.db')}`,
        PROXPLOY_MASTER_KEY_FILE: path.join(dataDir, 'master.key'),
        // No live Proxmox host here, and there never will be (see
        // docs/notes/phase-6-infra.md) — pollers/scheduler/alerts off so the
        // app doesn't thrash trying to reach one.
        PROXPLOY_POLL_ENABLED: 'false',
        PROXPLOY_SCHEDULER_ENABLED: 'false',
        PROXPLOY_ALERTS_ENABLED: 'false',
      },
    },
    {
      // Same proxy setup as `vite dev` (vite.config.ts: /api -> :8000).
      command: `npx vite --port ${FRONTEND_PORT} --strictPort`,
      cwd: root,
      url: `http://127.0.0.1:${FRONTEND_PORT}`,
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
})
