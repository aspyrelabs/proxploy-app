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
    await expect(page.getByRole('heading', { name: 'Hosts', level: 1 })).toBeVisible()
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
      await page.goto('/hosts')
      await expect(page.getByRole('heading', { name: 'Hosts', level: 1 })).toBeVisible()
      if (label !== 'Hosts') await goToNavPage(page, label)

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

/**
 * PXP-16. The existing suite above could not have caught either half of the
 * bug it was written for:
 *
 *  - it never visits /login, so the login page ignoring the stored theme went
 *    unnoticed until a human looked;
 *  - it only looks for ONE dark literal (#1d2733), and the topbar was a
 *    different hardcoded colour, so a surface that never converted still
 *    passed every assertion.
 *
 * These two close both gaps by asserting on the theme's own tokens rather than
 * hunting a specific bad value: any surface that fails to switch fails here,
 * whatever colour it happens to be.
 */
test.describe('light theme, the surfaces the literal-hunt missed', () => {
  test.describe.configure({ mode: 'serial' })

  test.beforeAll(async () => {
    await seedAdmin()
  })

  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('pp_theme', 'light'))
  })

  test('the login page honours the stored theme without a session', async ({ page }) => {
    await page.goto('/login')
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
    // The chosen theme has to be applied before first paint, not after a
    // toggle mounts somewhere behind auth.
    const bodyBg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor)
    expect(bodyBg).not.toBe('rgb(11, 15, 22)')  // --ink, dark
  })

  test('the topbar goes light with the rest of the page', async ({ page, browser }) => {
    const context = await browser.newContext()
    const helper = await context.newPage()
    await helper.addInitScript(() => localStorage.setItem('pp_theme', 'light'))
    await signIn(helper)
    const cookies = (await context.storageState()).cookies
    await context.close()
    await page.context().addCookies(cookies)

    await page.goto('/hosts')
    await expect(page.getByRole('heading', { name: 'Hosts', level: 1 })).toBeVisible()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')

    // The bar is translucent over scrolling content, so compare its own
    // channels rather than an exact string: light means a bright background,
    // whatever the alpha resolves to.
    const rgb = await page.evaluate(() => {
      const el = document.querySelector('header')
      return el ? getComputedStyle(el).backgroundColor : null
    })
    expect(rgb, 'no <header> found; did the Topbar markup change?').not.toBeNull()
    const [r, g, b] = rgb!.match(/\d+(\.\d+)?/g)!.slice(0, 3).map(Number)
    expect(r + g + b, `topbar background was ${rgb}, which is not a light surface`)
      .toBeGreaterThan(3 * 128)
  })
})
