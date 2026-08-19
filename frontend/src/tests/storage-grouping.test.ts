/** groupStorage: which datastores belong under which host on the Storage page.
 *
 * The shapes here are the real `lab-cluster` cluster's, captured 2026-08-19. What
 * makes this worth a test file of its own is that GET /storage's rows cannot
 * be grouped on the obvious field: its dedupe drops host_id from the key, so
 * EVERY row comes back owned by whichever host polled first, and a shared
 * datastore comes back once under whichever node was seen first.
 */
import { describe, expect, it } from 'vitest'
import { groupStorage } from '../routes/storage-groups'

const row = (over: Partial<Parameters<typeof groupStorage>[0][number]>) => ({
  host_id: 1, host_name: 'node1.lab.local', cluster_name: 'lab-cluster',
  node: 'node1', storage: 'local', type: 'dir', content: ['iso'],
  shared: false, status: 'available', used_bytes: 1, total_bytes: 2, used_pct: 50,
  ...over,
})

// Every row owned by host 1, because host 1 polled first.
const CLUSTER_ROWS = [
  row({ node: 'node1', storage: 'local', type: 'dir' }),
  row({ node: 'node1', storage: 'local-lvm', type: 'lvmthin' }),
  row({ node: 'node2', storage: 'local', type: 'dir' }),
  row({ node: 'node2', storage: 'local-lvm', type: 'lvmthin' }),
  row({ node: 'node1', storage: 'nfs-shared', type: 'nfs', shared: true }),
]
const CLUSTER_HOSTS = [
  { id: 1, name: 'node1.lab.local', node_name: 'node1', cluster_name: 'lab-cluster' },
  { id: 2, name: 'node2.lab.local', node_name: 'node2', cluster_name: 'lab-cluster' },
]

const namesIn = (groups: ReturnType<typeof groupStorage>, label: string) =>
  groups.find((g) => g.label === label)?.rows.map((r) => r.storage).sort()

describe('groupStorage', () => {
  it('gives every node its own group, not just the host that polled first', () => {
    const groups = groupStorage(CLUSTER_ROWS, CLUSTER_HOSTS)
    expect(namesIn(groups, 'node1.lab.local')).toEqual(['local', 'local-lvm'])
    // The bug this whole file exists for: node2's pools are in rows carrying
    // host_id 1, so grouping on host_id would leave this group empty.
    expect(namesIn(groups, 'node2.lab.local')).toEqual(['local', 'local-lvm'])
  })

  it('lifts a shared datastore out into one cluster group', () => {
    const groups = groupStorage(CLUSTER_ROWS, CLUSTER_HOSTS)
    expect(namesIn(groups, 'Shared')).toEqual(['nfs-shared'])
    // Once, not once per node: which node it is reported under is arbitrary
    // and flips on a backend restart, so it must not decide where it appears.
    expect(groups.flatMap((g) => g.rows).filter((r) => r.storage === 'nfs-shared'))
      .toHaveLength(1)
  })

  it('puts hosts by name first and the shared group last', () => {
    expect(groupStorage(CLUSTER_ROWS, CLUSTER_HOSTS).map((g) => g.label))
      .toEqual(['node1.lab.local', 'node2.lab.local', 'Shared'])
  })

  it('keeps a host with no datastores rather than dropping it', () => {
    // A host that silently vanishes reads exactly like the bug where one host
    // of a cluster saw nothing at all.
    const groups = groupStorage([row({ node: 'node1' })], CLUSTER_HOSTS)
    expect(groups.map((g) => g.label))
      .toEqual(['node1.lab.local', 'node2.lab.local'])
    expect(namesIn(groups, 'node2.lab.local')).toEqual([])
  })

  it('keeps a shared pool on a standalone host with that host', () => {
    // cluster_name null means not clustered, so "shared" is shared with nobody
    // and a cluster group would be a heading for one machine.
    const groups = groupStorage(
      [row({ cluster_name: null, node: 'pve', storage: 'nfs-box', shared: true })],
      [{ id: 1, name: 'host-01', node_name: 'pve', cluster_name: null }])
    expect(groups.map((g) => g.label)).toEqual(['host-01'])
    expect(namesIn(groups, 'host-01')).toEqual(['nfs-box'])
  })

  it('shows a node nobody is enrolled at under its own name', () => {
    // An unregistered cluster member's local pools belong to no host group;
    // dropping them would hide real datastores.
    const groups = groupStorage(
      [...CLUSTER_ROWS, row({ node: 'node3', storage: 'spare', type: 'dir' })],
      CLUSTER_HOSTS)
    expect(namesIn(groups, 'node3')).toEqual(['spare'])
  })
})
