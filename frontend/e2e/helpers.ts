import { expect, request, type Page } from '@playwright/test'

import { mkdirSync, rmdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

// Matches playwright.config.ts's `use.baseURL`, kept as a plain constant
// (not a shared module) since this is a small e2e harness.
export const BASE_URL = 'http://127.0.0.1:5173'
export const ADMIN_EMAIL = 'e2e-admin@example.com'
export const ADMIN_PASSWORD = 'e2e-smoke-passphrase-1'

// Lives inside playwright.config.ts's `.e2e-data`, the throwaway dir its
// webServer command `rm -rf`s and recreates at the start of every run, so a
// lock directory left behind by a killed previous run can never wedge this
// one.
const LOCK_DIR = join(dirname(fileURLToPath(import.meta.url)), '../.e2e-data/seed.lock')
const LOCK_STALE_MS = 20_000

/**
 * `mkdir` is an atomic exclusive-create at the OS level, so it works as a
 * mutex across separate Playwright worker *processes*, an in-memory lock
 * cannot. seedAdmin() needs one: the e2e backend is a single dev uvicorn
 * process over SQLite, `test.beforeAll` runs once per worker, and
 * fullyParallel means several workers can call seedAdmin() at once. A
 * concurrent duplicate `POST /users` there doesn't fail cleanly, it throws
 * past Starlette's own error handling (confirmed against this backend:
 * "ERROR: Exception in ASGI application" in its logs) and can disrupt other
 * requests in flight at the same moment, not just the one that raced. This
 * serializes every seedAdmin() call so that race never happens.
 */
async function withSeedLock<T>(fn: () => Promise<T>): Promise<T> {
  const deadline = Date.now() + LOCK_STALE_MS
  let acquired = false
  while (!acquired) {
    try {
      mkdirSync(LOCK_DIR)
      acquired = true
    } catch {
      if (Date.now() > deadline) break // a stale lock from a killed run; proceed rather than hang forever
      await new Promise(r => setTimeout(r, 50 + Math.random() * 100))
    }
  }
  try {
    return await fn()
  } finally {
    if (acquired) { try { rmdirSync(LOCK_DIR) } catch { /* already gone */ } }
  }
}

// SidebarNav's accessible link names, in page order (frontend/src/components/
// SidebarNav.tsx), every one of them renders an `<h1>` with the identical
// text (verified against each route file), so the same list drives both the
// click and the heading assertion.
export const NAV_PAGES = [
  'Cluster', 'Apps', 'App Store', 'Virtual Machines',
  'Storage', 'Network', 'Backups', 'Alerts', 'Audit', 'Settings',
] as const

/**
 * Seed through the app's own real endpoints, no direct DB/ORM writes.
 * Mirrors the onboarding wizard's "Admin account" + "Done" steps
 * (frontend/src/routes/onboarding.tsx: POST /users, POST /auth/login, PATCH
 * /settings 'onboarding.complete'). Deliberately skips the wizard's "First
 * host" step, the stranger journey (Task 16) is what exercises that.
 *
 * Idempotent: playwright.config.ts's webServer boots ONE backend for the
 * whole run, so every spec file that calls this shares one database, and
 * `test.beforeAll` runs once per *worker*, not once per file; with
 * fullyParallel this can mean several concurrent first-callers. `withSeedLock`
 * serializes them; whichever runs first creates the admin, the rest find
 * admin_exists already true and skip straight to login. The retry below is a
 * second line of defence for a plain transient failure, not the race itself.
 */
export async function seedAdmin(baseURL = BASE_URL) {
  await withSeedLock(async () => {
    let lastErr: unknown
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        await seedAdminOnce(baseURL)
        return
      } catch (e) {
        lastErr = e
        await new Promise(r => setTimeout(r, 150 * (attempt + 1)))
      }
    }
    throw lastErr
  })
}

async function seedAdminOnce(baseURL: string) {
  const api = await request.newContext({ baseURL })
  try {
    const primed = await api.get('/api/v1/meta/health')
    expect(primed.ok(), 'priming GET for the pp_csrf cookie failed').toBeTruthy()
    const csrf = (await api.storageState()).cookies.find(c => c.name === 'pp_csrf')?.value
    if (!csrf) throw new Error('seed: pp_csrf cookie missing after the priming request')
    const headers = { 'X-CSRF-Token': csrf }

    const onboarding = await (await api.get('/api/v1/meta/onboarding')).json()
    if (!onboarding.admin_exists) {
      const created = await api.post('/api/v1/users', {
        headers, data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD, display_name: 'E2E Admin' },
      })
      if (!created.ok()) {
        const recheck = await (await api.get('/api/v1/meta/onboarding')).json()
        if (!recheck.admin_exists) throw new Error(`seed: admin creation failed: ${await created.text()}`)
      }
    }

    const loggedIn = await api.post('/api/v1/auth/login', {
      headers, data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
    })
    expect(loggedIn.ok(), await loggedIn.text()).toBeTruthy()

    const completed = await api.patch('/api/v1/settings', {
      headers, data: { 'onboarding.complete': true },
    })
    expect(completed.ok(), await completed.text()).toBeTruthy()
  } finally {
    await api.dispose()
  }
}

/** Fill and submit the login form. Does not assert what renders next, 
 *  callers want different things after (a heading, a console-error check). */
export async function signIn(page: Page) {
  await page.goto('/')
  await expect(page).toHaveURL(/\/login$/)
  await page.getByLabel('Email').fill(ADMIN_EMAIL)
  await page.getByLabel('Password').fill(ADMIN_PASSWORD)
  // The e2e backend is one dev uvicorn process over SQLite, shared by every
  // spec file this run, a login POST racing another spec's concurrent
  // write can occasionally hit real contention and surface as a genuine
  // "Sign-in failed" in the UI (LoginForm.tsx's non-401 branch). The form
  // keeps email/password filled on a completed failure, so resubmitting is
  // safe, but only once that failure has actually landed: racing a second
  // click against a first submit that is merely slow (not failed) double-
  // submits into a button that is about to be unmounted by the real
  // success, which is worse than waiting.
  const error = page.getByText(/sign-in failed|invalid email or password/i)
  for (let attempt = 1; ; attempt++) {
    await page.getByRole('button', { name: 'Sign in' }).click()
    const outcome = await Promise.race([
      page.waitForURL(u => !u.pathname.endsWith('/login'), { timeout: 15_000 }).then(() => 'ok' as const),
      error.waitFor({ state: 'visible', timeout: 15_000 }).then(() => 'error' as const),
    ]).catch(() => 'timeout' as const)
    if (outcome === 'ok') return
    if (attempt >= 3) throw new Error(`signIn: gave up after ${attempt} attempts (${outcome})`)
  }
}

/** Click a SidebarNav link and wait for its page's <h1> to render. */
export async function goToNavPage(page: Page, label: string) {
  await page.getByRole('navigation').getByRole('link', { name: label, exact: true }).click()
  await expect(page.getByRole('heading', { name: label, level: 1 })).toBeVisible()
}
