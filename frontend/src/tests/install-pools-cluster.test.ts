import { describe, expect, it } from 'vitest'
import { poolsFrom, servedTo, type StorageRow } from '../components/install/pools'

/**
 * The filter used to be `row.host_id === hostId`, which is wrong on every
 * cluster. GET /storage keys its dedupe on (cluster, node, storage) with
 * host_id deliberately absent, because both nodes of a cluster report the whole
 * cluster's storage and either can serve it; the surviving row carries
 * whichever host polled first. On the real two-node `lab-cluster` cluster that meant
 * node1's install dialog offered NO pools at all while node2's offered all of
 * them, and which host broke flipped on every backend restart.
 */
const row = (over: Partial<StorageRow>): StorageRow => ({
  host_id: 2, node: 'node2', storage: 'local-lvm', content: ['rootdir'],
  status: 'available', shared: false, cluster_name: 'lab-cluster', ...over,
})

// Exactly what GET /storage returned for `lab-cluster` on 2026-08-17: every row
// attributed to host 2, including the pools that live on node1.
const ASPYRE: StorageRow[] = [
  row({ node: 'node1', storage: 'local', content: ['backup', 'vztmpl', 'iso'] }),
  row({ node: 'node2', storage: 'local', content: ['backup', 'vztmpl', 'iso'] }),
  row({ node: 'node1', storage: 'local-lvm', content: ['rootdir', 'images'] }),
  row({ node: 'node2', storage: 'local-lvm', content: ['rootdir', 'images'] }),
  row({ node: 'node2', storage: 'nfs-shared', shared: true,
        content: ['backup', 'images', 'vztmpl', 'iso', 'rootdir'] }),
]

describe('storage pools across a cluster', () => {
  it('finds node1 pools even though every row is attributed to host 2', () => {
    expect(poolsFrom(ASPYRE, 1, 'node1', 'lab-cluster', 'rootdir'))
      .toEqual(['local-lvm', 'nfs-shared'])
    expect(poolsFrom(ASPYRE, 1, 'node1', 'lab-cluster', 'vztmpl'))
      .toEqual(['local', 'nfs-shared'])
  })

  it('still works for the host that did win the snapshot race', () => {
    expect(poolsFrom(ASPYRE, 2, 'node2', 'lab-cluster', 'rootdir'))
      .toEqual(['local-lvm', 'nfs-shared'])
  })

  it('keeps the node filter, so a sibling node local pool is not offered', () => {
    // node1's `local-lvm` and node2's are two different datastores that happen
    // to share a name; the shared one is the only cross-node candidate.
    const onlyNode1Local = [row({ node: 'node1', storage: 'node1-only',
                                  content: ['rootdir'] })]
    expect(poolsFrom(onlyNode1Local, 2, 'node2', 'lab-cluster', 'rootdir')).toEqual([])
  })

  it('exempts a shared pool from the node filter', () => {
    const shared = [row({ node: 'node2', storage: 'nfs-shared', shared: true,
                          content: ['rootdir'] })]
    expect(poolsFrom(shared, 1, 'node1', 'lab-cluster', 'rootdir'))
      .toEqual(['nfs-shared'])
  })

  it('never matches an unrelated standalone host', () => {
    // Two standalone hosts both report cluster_name null, and null means "not
    // clustered" rather than "unknown", so it must not be a match key.
    const other = [row({ host_id: 7, node: 'pve', storage: 'someone-elses',
                         cluster_name: null, content: ['rootdir'] })]
    expect(poolsFrom(other, 1, 'pve', null, 'rootdir')).toEqual([])
    expect(servedTo(other[0], 1, null)).toBe(false)
  })

  it('a standalone host still sees its own rows', () => {
    const own = [row({ host_id: 1, node: 'pve', storage: 'local-lvm',
                       cluster_name: null, content: ['rootdir'] })]
    expect(poolsFrom(own, 1, 'pve', null, 'rootdir')).toEqual(['local-lvm'])
  })

  it('drops a pool that is not available', () => {
    const stale = [row({ node: 'node1', storage: 'stale', status: 'unknown',
                         content: ['rootdir'] })]
    expect(poolsFrom(stale, 1, 'node1', 'lab-cluster', 'rootdir')).toEqual([])
  })
})
