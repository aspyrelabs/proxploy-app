import { expect, test } from '@playwright/test'

import { goToNavPage, NAV_PAGES, seedAdmin, signIn } from './helpers'

// It deliberately skips the wizard's "First host" step: creating a host
// makes the backend probe a real Proxmox API (backend/proxploy/api/hosts.py
// `_client(...).version()`) and there is no live Proxmox host here, and
// there never will be. The shell route's guard (frontend/src/routes/
// shell.tsx) only checks onboarding.complete, not host_added, so seedAdmin()
// alone is enough to reach the nav.
test.beforeAll(async () => {
  await seedAdmin()
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
  // page that 401 is the correct answer, the app is asking "am I signed in?"
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
    // above already covers it with one. Everything else, a React render
    // warning escalated to error, a thrown effect; is kept.
    if (msg.type() === 'error' && !msg.text().startsWith('Failed to load resource')) {
      consoleErrors.push(`[${currentPage}] console.error: ${msg.text()}`)
    }
  })
  page.on('pageerror', err => {
    consoleErrors.push(`[${currentPage}] unhandled page exception: ${err.message}`)
  })

  await test.step('login', async () => {
    await signIn(page)
    currentPage = 'Cluster'
    await expect(page.getByRole('heading', { name: 'Cluster', level: 1 })).toBeVisible()
    expect(consoleErrors, consoleErrors.join('\n')).toEqual([])
  })

  for (const label of NAV_PAGES) {
    if (label === 'Cluster') continue // already there, asserted above
    // eslint-disable-next-line no-loop-func
    await test.step(label, async () => {
      currentPage = label
      await goToNavPage(page, label)
      expect(consoleErrors, consoleErrors.join('\n')).toEqual([])
    })
  }
})
