/**
 * Cluster peer auto enrolment (docs/notes/cluster-peer-auto-enrolment-plan.md)
 * in a real browser: one node of a cluster is added, the panel offers the
 * other nodes, and only what is ticked is added.
 *
 * What this proves: the panel's own logic and wiring against the two routes it
 * calls, end to end, including that each peer is offered with the address the
 * cluster reported and the certificate that machine presented, and that a host
 * row with its own copies of the tokens exists afterwards. The last step
 * covers the same panel in the Edit dialog, where a host added before the
 * panel existed gets the offer.
 *
 * What it does NOT prove: behaviour against real Proxmox hardware. Every node
 * here is a FakePVE from backend/tests/e2e_server.py, one per address, and the
 * fingerprints come from a stub that answers per address; no certificate was
 * served by anything.
 *
 * NOT covered here, deliberately: the refusal when a node presents a different
 * certificate between the panel drawing and confirm. Nothing reachable from
 * the browser can change what the fake presents mid-test, so the only way to
 * write it here would be a test that pretends. backend/tests/test_hosts_peers
 * .py::test_a_peer_presenting_a_different_certificate_is_not_added covers it
 * against the same code path the panel calls.
 *
 * One test with steps, not several tests: every step depends on what the one
 * before it wrote, and fullyParallel would otherwise spread them across
 * workers in no particular order. journey.spec.ts stays the only spec that
 * drives a fresh install; this one seeds an admin like every other spec.
 */
import { expect, test, type Page } from '@playwright/test'

import { goToNavPage, seedAdmin, signIn } from './helpers'

// Must match backend/tests/e2e_server.py's CLUSTER, CLUSTER_NODES and its
// per-address fingerprint stub exactly. That file is this spec's one source of
// fake infrastructure, nothing here is guessed.
const CLUSTER = 'lab-cluster'
const FIRST = { name: 'pve-02', node: 'pve2', fingerprint: 'E2:E0:10.0.0.6',
                address: 'https://10.0.0.6:8006' }
const SECOND = { name: 'pve-03', node: 'pve3', fingerprint: 'E2:E0:10.0.0.7',
                 address: 'https://10.0.0.7:8006' }
const PEER = { node: 'pve4', fingerprint: 'E2:E0:10.0.0.8',
               address: 'https://10.0.0.8:8006' }

test.beforeAll(async () => {
  await seedAdmin()
})

/** Fill and submit the Settings page's Add host form, with two capability
 *  tokens so there is more than one for the peer to be given a copy of.
 *  Returns the form, which is where the peer panel renders once the host
 *  exists. */
async function addHost(page: Page, name: string, address: string) {
  await goToNavPage(page, 'Settings')
  await page.getByRole('button', { name: 'Add host' }).click()
  // The card's own toggle reads "Close" while the form is open, so the only
  // "Add host" button left is the form's submit.
  const form = page.locator('form')
  await form.getByLabel('Name').fill(name)
  await form.getByLabel('Address').fill(address)
  await form.getByRole('checkbox', { name: /^Lifecycle/ }).check()
  await form.getByLabel('Monitoring token id', { exact: true }).fill('proxploy@pve!monitoring')
  await form.getByLabel('Monitoring token secret', { exact: true }).fill('secret')
  await form.getByLabel('Lifecycle token id', { exact: true }).fill('proxploy@pve!lifecycle')
  await form.getByLabel('Lifecycle token secret', { exact: true }).fill('secret')
  await form.getByRole('button', { name: 'Add host' }).click()
  return form
}

test('the peer panel offers the rest of the cluster and adds only what is ticked',
  async ({ page }) => {
    await test.step('sign in', async () => {
      await signIn(page)
      await expect(page.getByRole('heading', { name: 'Hosts', level: 1 })).toBeVisible()
    })

    await test.step('adding one node of a cluster offers the others', async () => {
      const form = await addHost(page, FIRST.name, FIRST.address)
      await expect(form.getByText(`${FIRST.node} is part of cluster ${CLUSTER}. `
        + 'Proxploy found 2 other nodes in it.')).toBeVisible({ timeout: 15_000 })
      // The address the cluster reported and the certificate each machine
      // presented on it. The origin's own fingerprint appears on no peer row:
      // cluster nodes serve distinct certificates, and a peer wearing the
      // origin's would mean the pin was read off the wrong machine.
      await expect(form.getByText(`${SECOND.node}, ${SECOND.address}`)).toBeVisible()
      await expect(form.getByText(`TLS fingerprint ${SECOND.fingerprint}`)).toBeVisible()
      await expect(form.getByText(`${PEER.node}, ${PEER.address}`)).toBeVisible()
      await expect(form.getByText(`TLS fingerprint ${PEER.fingerprint}`)).toBeVisible()
      await expect(form.getByText(FIRST.fingerprint)).toHaveCount(0)
    })

    await test.step('Skip adds nothing at all', async () => {
      await page.locator('form').getByRole('button', { name: 'Skip' }).click()
      // The form closes on Skip and the hosts table refetches, so the host
      // that WAS added being in it is what makes the two absences mean
      // something rather than being a table that had not loaded yet.
      await expect(page.getByRole('cell', { name: FIRST.name })).toBeVisible()
      await expect(page.getByRole('cell', { name: SECOND.node, exact: true })).toHaveCount(0)
      await expect(page.getByRole('cell', { name: PEER.node, exact: true })).toHaveCount(0)
    })

    await test.step('a peer already in Proxploy is shown as information', async () => {
      const form = await addHost(page, SECOND.name, SECOND.address)
      // Shown, not hidden, and not a failure: it is disabled and unticked, so
      // it is never sent on confirm and never reported as an error. The
      // "skipped" result status the route returns for it cannot be reached
      // from this panel at all, because the checkbox that would send it is
      // disabled; backend/tests/test_hosts_peers.py covers that half.
      const already = form.getByRole('checkbox', {
        name: new RegExp(`Already in Proxploy as ${FIRST.name}`) })
      await expect(already).toBeDisabled({ timeout: 15_000 })
      await expect(already).not.toBeChecked()
      const addable = form.getByRole('checkbox', { name: new RegExp(PEER.node) })
      await expect(addable).toBeChecked()
      await expect(form.getByText(`TLS fingerprint ${PEER.fingerprint}`)).toBeVisible()
    })

    await test.step('confirming adds the ticked node with a copy of every token',
      async () => {
        const form = page.locator('form')
        await form.getByRole('button', { name: 'Add these nodes' }).click()
        await expect(form.getByText(`${PEER.node} was added, with these tokens `
          + 'stored: Read-only monitoring, Lifecycle.')).toBeVisible({ timeout: 15_000 })
        await form.getByRole('button', { name: 'Continue' }).click()
      })

    await test.step('the peer is a host of its own with its own tokens', async () => {
      const row = page.getByRole('row', { name: new RegExp(`^${PEER.node} `) })
      await expect(row).toContainText(PEER.address)
      await row.getByRole('button', { name: 'Edit' }).click()
      const dialog = page.getByRole('dialog')
      // Its own credential rows, each verified against pve4 itself before it
      // was written, not a note that the origin holds them.
      await expect(dialog.getByRole('button',
        { name: 'Monitoring token already stored' })).toBeVisible()
      await expect(dialog.getByRole('button',
        { name: 'Lifecycle token already stored' })).toBeVisible()
      // The pin, which nothing in this dialog prints unless it stops matching.
      // ProxmoxClient._connect refuses before it sends anything when a stored
      // fingerprint is not what the node presents, so connecting at all is
      // what proves pve4 was pinned to pve4's certificate and not the
      // origin's.
      await dialog.getByRole('button', { name: 'Test connection' }).click()
      await expect(dialog.getByText(/Connected, PVE/)).toBeVisible({ timeout: 15_000 })
      await dialog.getByRole('button', { name: 'Cancel' }).click()
    })

    // Phase 6: the same panel in the Edit dialog, so a host added by hand
    // before it shipped gets the offer without being removed and re-added.
    // pve-02 was added by hand at the top of this test, and by now every one
    // of its peers is in Proxploy, which is the normal state of this dialog
    // once a cluster has been enrolled.
    await test.step('the Edit dialog offers the same panel to a host added by hand',
      async () => {
        await page.getByRole('row', { name: new RegExp(`^${FIRST.name} `) })
          .getByRole('button', { name: 'Edit' }).click()
        const dialog = page.getByRole('dialog')
        await expect(dialog.getByText(`${FIRST.node} is part of cluster ${CLUSTER}. `
          + 'Proxploy found 2 other nodes in it.')).toBeVisible({ timeout: 15_000 })
        // Named, not hidden and not an error: each peer says the host name it
        // is already known by, and neither can be ticked again.
        for (const [node, name] of [[SECOND.node, SECOND.name], [PEER.node, PEER.node]]) {
          const already = dialog.getByRole('checkbox', {
            name: new RegExp(`${node}.*Already in Proxploy as ${name}`, 's') })
          await expect(already).toBeDisabled()
          await expect(already).not.toBeChecked()
        }
        // Nothing to continue to here, so nothing offers to: the dialog is
        // closed by its own Cancel and Save, as it always was.
        await expect(dialog.getByRole('button', { name: 'Skip' })).toHaveCount(0)
        await expect(dialog.getByRole('button', { name: 'Continue' })).toHaveCount(0)
        await dialog.getByRole('button', { name: 'Cancel' }).click()
      })
  })
