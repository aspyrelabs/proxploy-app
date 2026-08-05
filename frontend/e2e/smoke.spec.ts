import { expect, request, test } from '@playwright/test'

// Matches playwright.config.ts's `use.baseURL` — kept as a plain constant
// (not a shared module) since this is a one-file smoke harness.
const BASE_URL = 'http://127.0.0.1:5173'
const ADMIN_EMAIL = 'e2e-admin@example.com'
const ADMIN_PASSWORD = 'e2e-smoke-passphrase-1'

// SidebarNav's accessible link names, in page order (frontend/src/components/
// SidebarNav.tsx) — every one of them renders an `<h1>` with the identical
// text (verified against each route file), so the same list drives both the
// click and the heading assertion.
const NAV_PAGES = [
  'Cluster', 'Apps', 'App Store', 'Virtual Machines',
  'Storage', 'Network', 'Backups', 'Alerts', 'Settings',
] as const

test.beforeAll(async () => {
  // Seed through the app's own real endpoints — no direct DB/ORM writes.
  // This mirrors the onboarding wizard's "Admin account" + "Done" steps
  // (frontend/src/routes/onboarding.tsx: POST /users, POST /auth/login,
  // PATCH /settings 'onboarding.complete'). It deliberately skips the
  // wizard's "First host" step: creating a host makes the backend probe a
  // real Proxmox API (backend/proxploy/api/hosts.py `_client(...).version()`)
  // and there is no live Proxmox host here, and there never will be. The
  // shell route's guard (frontend/src/routes/shell.tsx) only checks
  // onboarding.complete, not host_added, so this is enough to reach the nav.
  const api = await request.newContext({ baseURL: BASE_URL })

  const primed = await api.get('/api/v1/meta/health')
  expect(primed.ok(), 'priming GET for the pp_csrf cookie failed').toBeTruthy()
  const csrf = (await api.storageState()).cookies.find(c => c.name === 'pp_csrf')?.value
  if (!csrf) throw new Error('seed: pp_csrf cookie missing after the priming request')
  const headers = { 'X-CSRF-Token': csrf }

  const created = await api.post('/api/v1/users', {
    headers, data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD, display_name: 'E2E Admin' },
  })
  expect(created.ok(), await created.text()).toBeTruthy()

  const loggedIn = await api.post('/api/v1/auth/login', {
    headers, data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  })
  expect(loggedIn.ok(), await loggedIn.text()).toBeTruthy()

  const completed = await api.patch('/api/v1/settings', {
    headers, data: { 'onboarding.complete': true },
  })
  expect(completed.ok(), await completed.text()).toBeTruthy()

  await api.dispose()
})

test('login and every nav page renders with a clean console', async ({ page }) => {
  // The actual point of this harness: jsdom (Vitest) never runs real browser
  // JS, so it can't catch a console.error or an unhandled exception a
  // component throws at render/effect time. A real Chromium page can.
  const consoleErrors: string[] = []
  let currentPage = 'login'

  // Chromium logs EVERY non-2xx fetch as a console error, so the raw console
  // stream can't tell a broken page from a request that is 401 by design.
  // `useMe()` (src/api/hooks.ts) fires GET /auth/me on mount, and on the login
  // page that 401 is the correct answer — the app is asking "am I signed in?"
  // and being told no. That one case is expected; every other failed request
  // is not, and is reported with its status and URL so it can be diagnosed.
  const expected = (status: number, url: string) =>
    currentPage === 'login' && status === 401 && url.endsWith('/api/v1/auth/me')

  page.on('response', res => {
    const [status, url] = [res.status(), res.url()]
    if (status >= 400 && !expected(status, url)) {
      consoleErrors.push(`[${currentPage}] HTTP ${status} ${url}`)
    }
  })
  page.on('console', msg => {
    // The generic resource-load line carries no URL; the response listener
    // above already covers it with one. Everything else — a React render
    // warning escalated to error, a thrown effect — is kept.
    if (msg.type() === 'error' && !msg.text().startsWith('Failed to load resource')) {
      consoleErrors.push(`[${currentPage}] console.error: ${msg.text()}`)
    }
  })
  page.on('pageerror', err => {
    consoleErrors.push(`[${currentPage}] unhandled page exception: ${err.message}`)
  })

  await test.step('login', async () => {
    await page.goto('/')
    await expect(page).toHaveURL(/\/login$/)
    await page.getByLabel('Email').fill(ADMIN_EMAIL)
    await page.getByLabel('Password').fill(ADMIN_PASSWORD)
    await page.getByRole('button', { name: 'Sign in' }).click()
    currentPage = 'Cluster'
    await expect(page.getByRole('heading', { name: 'Cluster', level: 1 })).toBeVisible()
    expect(consoleErrors, consoleErrors.join('\n')).toEqual([])
  })

  for (const label of NAV_PAGES) {
    if (label === 'Cluster') continue // already there, asserted above
    // eslint-disable-next-line no-loop-func
    await test.step(label, async () => {
      currentPage = label
      await page.getByRole('navigation').getByRole('link', { name: label, exact: true }).click()
      await expect(page.getByRole('heading', { name: label, level: 1 })).toBeVisible()
      expect(consoleErrors, consoleErrors.join('\n')).toEqual([])
    })
  }
})
