/**
 * The four Phase 9 DoD clauses nothing had ever executed: a stranger
 * completes onboarding, installs an app, creates a VM, and schedules a
 * backup, through the real UI, in a real browser.
 *
 * What this proves: the product's own logic, routing and UI, end to end; 
 * the onboarding wizard's server-derived step, the SSH-verify gate, the App
 * Store install flow, the VM-create wizard, and schedule creation, wired
 * together exactly as a stranger would click through them.
 *
 * What it does NOT prove: behaviour against real Proxmox hardware. There is
 * no Proxmox node on this machine and there never will be; every PVE and SSH
 * interaction below is served by tests/e2e_server.py's fakes (FakePVE +
 * FakeSSHConnection). Timing that depends on a real poll cycle against a
 * real cluster, real script execution over a real SSH session, and real disk
 * I/O are all outside what this test can speak to.
 *
 * This is the only spec that drives a truly fresh install; it must be the
 * first admin ever created on this backend, or its own "admin account" step
 * has nothing to do. playwright.config.ts's `journey` project has no
 * dependencies and every other project depends on it, which is what
 * guarantees this file finishes before smoke.spec.ts / light-theme.spec.ts's
 * seedAdmin() calls get a chance to race it.
 */
import { expect, test } from '@playwright/test'

import { ADMIN_EMAIL, ADMIN_PASSWORD, goToNavPage } from './helpers'

const HOST_NAME = 'pve-01'
const APP_NAME = 'e2e-demo-app'
const APP_CTID = '150'
const VM_NAME = 'e2e-test-vm'
const SCHEDULE_NAME = 'Nightly backup, e2e'
// Must match backend/tests/e2e_server.py's seeding exactly, that file is
// this journey's one source of fake infrastructure, not guessed here.
const ISO_VOLID = 'local:iso/ubuntu-24.04-live-server-amd64.iso'

test('a stranger onboards, installs an app, creates a VM and schedules a backup', async ({ page }) => {
  await test.step('onboarding: admin account', async () => {
    // Reuses helpers.ts's ADMIN_EMAIL/ADMIN_PASSWORD rather than a one-off
    // "stranger@example.com": every other spec's seedAdmin() shares this one
    // backend process/DB (playwright.config.ts's webServer), and once this
    // step creates the admin, seedAdmin() finds admin_exists already true and
    // skips straight to logging in with these exact credentials, a
    // different identity here would leave it nothing valid to log in as.
    await page.goto('/onboarding')
    await page.getByLabel('Email').fill(ADMIN_EMAIL)
    await page.getByLabel('Display name').fill('E2E Admin')
    await page.getByLabel('Password (12+ chars)').fill(ADMIN_PASSWORD)
    await page.getByRole('button', { name: 'Create admin account' }).click()
    await expect(page.getByRole('button', { name: 'Add host' })).toBeVisible()
  })

  await test.step('onboarding: first host', async () => {
    // Impossible before Task 15, POST /hosts probes a live Proxmox API.
    // SSH enrolment is checked deliberately, not just to exercise Task 14's
    // verify step: services/appstore.py::run_install needs an enrolled key
    // to SSH in at all (LookupError -> JobFailed with no credential), so
    // this is a hard prerequisite of the "install an app" clause below.
    await page.getByLabel('Name').fill(HOST_NAME)
    await page.getByLabel('Address').fill('https://10.0.0.5:8006')
    await page.getByLabel('API token id').fill('proxploy@pve!e2e')
    await page.getByLabel('API token secret').fill('secret')
    await page.getByLabel(/Enable App Store installs/).check()
    await page.getByRole('button', { name: 'Add host' }).click()
    await expect(page.getByRole('button', { name: 'Verify access' })).toBeVisible()
  })

  await test.step('onboarding: authorize the SSH key', async () => {
    // Task 14: a click used to be taken on its word. FakeSSHConnection
    // (exit_status 0) is what makes this call actually succeed.
    await page.getByRole('button', { name: 'Verify access' }).click()
    await expect(page.getByRole('button', { name: /open the dashboard/i })).toBeVisible()
  })

  await test.step('land on Cluster', async () => {
    await page.getByRole('button', { name: /open the dashboard/i }).click()
    await expect(page.getByRole('heading', { name: 'Cluster', level: 1 })).toBeVisible()
  })

  await test.step('install an app', async () => {
    await goToNavPage(page, 'App Store')
    // e2e_server.py seeds exactly one catalog entry (no network, a real
    // catalog sync hits community-scripts/ProxmoxVE on GitHub) so this is
    // never ambiguous with a second "Install" button.
    await page.getByRole('button', { name: 'Install', exact: true }).click()
    // Neither InstallDialog nor VmCreateWizard below use role="dialog", and
    // the overlay never unmounts the page underneath it, an unscoped
    // getByRole('button', { name: 'Install' }) on the dialog's own submit
    // button would also match the StoreCard button still sitting behind the
    // overlay. `.fixed.inset-0` is both dialogs' own overlay wrapper.
    const dialog = page.locator('.fixed.inset-0')
    await dialog.getByRole('combobox').selectOption({ label: HOST_NAME })
    await dialog.getByPlaceholder('App name').fill(APP_NAME)
    await dialog.getByPlaceholder('Container ID (CTID)').fill(APP_CTID)
    await dialog.getByLabel('I understand this runs as root on the node').check()
    await dialog.getByRole('button', { name: 'Install' }).click()
    await expect(dialog.getByText('succeeded')).toBeVisible({ timeout: 20_000 })
    await dialog.getByRole('button', { name: 'Close' }).click()

    await goToNavPage(page, 'Apps')
    await expect(page.getByText(APP_NAME)).toBeVisible()
  })

  await test.step('create a VM', async () => {
    // The VM-create wizard's node/storage pickers read Host.node_name and
    // GET /storage, both of which only exist after the poller's first cycle
    // against FakePVE, never at host-create time (see the fix in
    // proxploy/pollers/__init__.py this task's commit made to
    // ingest_cycle). e2e_server.py polls every 1s specifically so this
    // doesn't wait out a production 30s interval; this still retries rather
    // than trusting a single check, since "a poll happened by now" is a
    // timing claim, not a guarantee.
    await expect(async () => {
      const rows = await (await page.request.get('/api/v1/cluster/nodes')).json()
      expect(rows.some((r: { node: string | null }) => r.node)).toBe(true)
    }).toPass({ timeout: 20_000 })
    // That request bypassed the app entirely, so it never touched React
    // Query's cache, and main.tsx sets a 15s staleTime, so the "land on
    // Cluster" step's own earlier (pre-poll, node: null) fetch of this exact
    // ['cluster','nodes'] query would otherwise still be served as fresh to
    // the wizard below. A reload is the one thing guaranteed to start that
    // cache over.
    await page.reload()

    await goToNavPage(page, 'Virtual Machines')
    await page.getByRole('button', { name: 'New VM' }).click()
    const dialog = page.locator('.fixed.inset-0')

    await dialog.getByLabel('Host').selectOption({ label: HOST_NAME })
    await dialog.getByLabel('Node').selectOption({ label: 'pve1' })
    await dialog.getByLabel('VM name').fill(VM_NAME)
    await dialog.getByRole('button', { name: 'Next' }).click()

    await dialog.getByLabel('ISO storage').selectOption({ label: 'local' })
    await dialog.getByLabel('ISO image').selectOption({ label: ISO_VOLID })
    await dialog.getByRole('button', { name: 'Next' }).click()

    await dialog.getByLabel('Target storage').selectOption({ label: 'local-lvm' })
    await dialog.getByRole('button', { name: 'Next' }).click()

    await dialog.getByLabel('Bridge').selectOption({ label: 'vmbr0' })
    await dialog.getByRole('button', { name: 'Next' }).click()

    await dialog.getByRole('button', { name: 'Create' }).click()
    await expect(dialog.getByText('succeeded')).toBeVisible({ timeout: 20_000 })
    await dialog.getByRole('button', { name: 'Close' }).click()

    // A created VM is not written to the `vms` table by the create job on
    // purpose (services/guestjobs.py::create_vm: "the next poll cycle either
    // confirms or deletes"), it only appears once the poller's next cycle
    // discovers it, so this retries a fresh navigation rather than trusting
    // whatever the page already fetched.
    await expect(async () => {
      await page.reload()
      await expect(page.getByRole('heading', { name: 'Virtual Machines', level: 1 })).toBeVisible()
      await expect(page.getByRole('cell', { name: VM_NAME })).toBeVisible({ timeout: 3_000 })
    }).toPass({ timeout: 20_000 })
  })

  await test.step('schedule a backup', async () => {
    await goToNavPage(page, 'Settings')
    await page.getByRole('button', { name: 'New schedule' }).click()
    await page.getByLabel('Name').fill(SCHEDULE_NAME)
    // "What to run" defaults to backup.run ("Backup guests on a host") and
    // its target select auto-picks our one host (ScheduleForm.tsx's
    // single-candidate fallback), nothing else needed for a valid submit,
    // except the Timezone field: it defaults to the browser's own zone
    // (Intl.DateTimeFormat), and this sandbox's Chromium reports a
    // deprecated alias ("Asia/Calcutta") that this box's minimal tzdata has
    // no backward-compatibility link for, a real backend's zoneinfo would
    // accept it, this container's just doesn't. Overwritten with a zone
    // guaranteed to resolve rather than depending on the CI host's tzdata.
    await page.getByLabel('Timezone').fill('UTC')
    await page.getByRole('button', { name: 'Create schedule' }).click()
    await expect(page.getByRole('cell', { name: SCHEDULE_NAME })).toBeVisible()
  })
})
