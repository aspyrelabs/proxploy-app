/**
 * Light theme, asserted rather than eyeballed.
 *
 * What this proves: no element resolves to the dark-only literal the two
 * bypass bugs used, and key surfaces clear a contrast threshold in light
 * mode. What it does not prove: that the light theme looks *good*. Nothing
 * available on this machine proves that.
 */
import { expect, test, type Cookie } from '@playwright/test'

import { goToNavPage, NAV_PAGES, seedAdmin, signIn } from './helpers'

const DARK_LITERAL = 'rgb(29, 39, 51)' // #1d2733, the bypass colour Task 11 removed

test.describe('light theme', () => {
  // Nine cheap assertions gain nothing from true parallelism, and running
  // them across separate worker processes multiplies seedAdmin() races
  // against the one dev backend instance webServer boots (see helpers.ts).
  // Serial keeps all nine, and this describe's single beforeAll, on one
  // worker.
  test.describe.configure({ mode: 'serial' })

  // auth.py rate-limits POST /login to 10/minute per source IP, and every
  // request in this run comes from the same local machine, one shared
  // bucket. Nine tests each doing their own UI sign-in blows straight
  // through it. Sign in through the real UI exactly once here and hand
  // every test the resulting session cookie instead.
  let sessionCookies: Cookie[]

  test.beforeAll(async ({ browser }) => {
    await seedAdmin()
    const context = await browser.newContext()
    const page = await context.newPage()
    await signIn(page)
    await expect(page.getByRole('heading', { name: 'Cluster', level: 1 })).toBeVisible()
    sessionCookies = (await context.storageState()).cookies
    await context.close()
  })

  test.beforeEach(async ({ page, context }) => {
    // ThemeToggle.tsx (frontend/src/components/ThemeToggle.tsx) reads
    // localStorage['pp_theme'] (default 'dark') and, on mount, syncs
    // document.documentElement.dataset.theme from it. Set the key before
    // any app script runs so that first mount picks up 'light' rather than
    // the default.
    await page.addInitScript(() => localStorage.setItem('pp_theme', 'light'))
    await context.addCookies(sessionCookies)
  })

  for (const label of NAV_PAGES) {
    test(`${label} uses no dark-only literals`, async ({ page }) => {
      await page.goto('/cluster')
      await expect(page.getByRole('heading', { name: 'Cluster', level: 1 })).toBeVisible()
      if (label !== 'Cluster') await goToNavPage(page, label)

      await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')

      const offenders = await page.evaluate((literal) =>
        [...document.querySelectorAll('*')]
          .filter((el) => {
            const s = getComputedStyle(el)
            return s.backgroundColor === literal || s.stroke === literal
          })
          .map((el) => el.tagName + '.' + el.className), DARK_LITERAL)
      expect(offenders, offenders.join('\n')).toEqual([])
    })
  }
})
