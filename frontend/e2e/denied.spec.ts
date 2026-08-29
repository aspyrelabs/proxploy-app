/**
 * The denied gate, on a real free-tier install.
 *
 * Every other spec runs against the PROXPLOY_E2E_ENTITLED=1 backend, where
 * nothing is ever refused, so no other spec can see a gate say no. This one
 * drives the second pair of servers (playwright.config.ts, project `free`),
 * which run on the product's real free floor with no override at all.
 *
 * What it pins: adding the FIRST host is free, adding a SECOND is not, and
 * both routes that offer "Add host" agree about that. They did not. The gate
 * was a `blocked` prop defaulting to false, decided per caller: the Hosts page
 * passed it, Settings > Hosts did not, so Settings served the whole form and
 * let POST /hosts answer 403 after it was filled in.
 */
import { expect, test, type Page } from '@playwright/test'

import { goToNavPage, seedAdmin, signIn } from './helpers'

const FREE_BASE_URL = 'http://127.0.0.1:5273'

// Must match backend/tests/e2e_server.py, the same way peers.spec.ts does.
const HOST = { name: 'pve-02', address: 'https://10.0.0.6:8006' }

const UPSELL = /second host is where the multi-host plan starts/i

test.beforeAll(async () => {
  await seedAdmin(FREE_BASE_URL)
})

async function openAddHostFromSettings(page: Page) {
  await goToNavPage(page, 'Settings')
  await page.getByRole('button', { name: 'Add host' }).click()
}

test('a free install includes one host and refuses the second, from either route',
  async ({ page }) => {
    await test.step('sign in, on the free tier', async () => {
      await signIn(page)
      await expect(page.getByRole('heading', { name: 'Hosts', level: 1 })).toBeVisible()
      // Proves this project really is driving the unentitled backend. Without
      // it, a config slip that pointed `free` at the entitled pair would make
      // every assertion below silently meaningless.
      await expect(page.getByRole('link', { name: /FREE plan/i })).toBeVisible()
    })

    await test.step('the first host is included, so the form is offered', async () => {
      await openAddHostFromSettings(page)
      const form = page.locator('form')
      await expect(form.getByLabel('Name')).toBeVisible()
      await expect(page.getByText(UPSELL)).toHaveCount(0)

      await form.getByLabel('Name').fill(HOST.name)
      await form.getByLabel('Address').fill(HOST.address)
      await form.getByLabel('Monitoring token id', { exact: true })
        .fill('proxploy@pve!monitoring')
      await form.getByLabel('Monitoring token secret', { exact: true }).fill('secret')
      await form.getByRole('button', { name: 'Add host' }).click()

      // The host exists once the peer panel takes over, and the panel states
      // the free tier's other half: the cluster's remaining nodes were found
      // and cannot be enrolled. That sentence is only reachable on a free
      // install, so nothing outside this project has ever rendered it.
      await expect(page.getByText(/is part of cluster lab-cluster/i))
        .toBeVisible({ timeout: 15_000 })
      await expect(page.getByText(/needs a paid tier, so these nodes cannot be added/i))
        .toBeVisible()
      await page.getByRole('button', { name: 'Continue' }).click()

      // The host row is what proves POST /hosts was allowed, not just that the
      // form accepted a click.
      await expect(page.getByRole('cell', { name: HOST.name })).toBeVisible({ timeout: 15_000 })
    })

    await test.step('Settings refuses the second host and says why', async () => {
      await openAddHostFromSettings(page)
      await expect(page.getByText(UPSELL)).toBeVisible()
      // The point of the gate: no form to fill, rather than a 403 at the end
      // of one. This is the assertion that was false before the fix.
      await expect(page.locator('form').getByLabel('Name')).toHaveCount(0)
      // The dialog is modal, so the sidebar is unreachable until it is shut.
      await page.getByRole('button', { name: 'Close dialog' }).click()
    })

    await test.step('the Hosts page refuses it the same way', async () => {
      // Not goToNavPage: the Settings page renders a second `navigation`
      // landmark for its own section rail, which also holds a "Hosts" link.
      await page.goto('/hosts')
      await expect(page.getByRole('heading', { name: 'Hosts', level: 1 })).toBeVisible()
      await page.getByRole('button', { name: 'Add host' }).click()
      await expect(page.getByText(UPSELL)).toBeVisible()
      await expect(page.locator('form').getByLabel('Name')).toHaveCount(0)
    })
  })
