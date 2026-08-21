import { describe, expect, it } from 'vitest'
import { combineThroughput } from '../lib/throughput'
import type { HostThroughput } from '../api/network'

const host = (id: number, name: string, inV: (number | null)[],
              outV: (number | null)[], ts = [1, 2, 3]): HostThroughput => ({
  host_id: id, host_name: name,
  in: { resolution: '5m', ts, value: inV },
  out: { resolution: '5m', ts, value: outV },
})

describe('combineThroughput', () => {
  it('counts a cluster once however many hosts are enrolled into it', () => {
    // The bug this function exists to prevent. Both rows carry the SAME
    // whole-cluster series (pollers sums over every node the endpoint sees),
    // so adding them reports twice the traffic that exists.
    const rows = [host(1, 'node1', [10, 20, 30], [1, 2, 3]),
                  host(2, 'node2', [10, 20, 30], [1, 2, 3])]
    const out = combineThroughput(rows, () => 'lab-cluster')
    expect(out.inValues).toEqual([10, 20, 30])
    expect(out.outValues).toEqual([1, 2, 3])
  })

  it('adds distinct clusters together', () => {
    const rows = [host(1, 'a', [10, 10, 10], [1, 1, 1]),
                  host(2, 'b', [5, 5, 5], [2, 2, 2])]
    const out = combineThroughput(rows, (id) => (id === 1 ? 'one' : 'two'))
    expect(out.inValues).toEqual([15, 15, 15])
  })

  it('counts every standalone host, since two of them are two machines', () => {
    const rows = [host(1, 'a', [10, 10, 10], [1, 1, 1]),
                  host(2, 'b', [5, 5, 5], [2, 2, 2])]
    const out = combineThroughput(rows, () => null)
    expect(out.inValues).toEqual([15, 15, 15])
  })

  it('reports a bucket no host measured as a gap, never as zero', () => {
    const out = combineThroughput([host(1, 'a', [10, null, 30], [1, 1, 1])], () => null)
    expect(out.inValues).toEqual([10, null, 30])
  })

  it('drops a bucket one counted host missed rather than halving the total', () => {
    // A rate is not a level: the absent host's traffic did not stop, it went
    // unmeasured, and a partial sum drawn as a real sample is a dip that never
    // happened.
    const rows = [host(1, 'a', [10, 10, 10], [1, 1, 1]),
                  host(2, 'b', [5, null, 5], [2, 2, 2])]
    const out = combineThroughput(rows, (id) => (id === 1 ? 'one' : 'two'))
    expect(out.inValues).toEqual([15, null, 15])
  })

  it('lines buckets up by timestamp, not by position', () => {
    // Two hosts polled a beat apart return different bucket counts. Zipping by
    // index would add one host's 09:00 to the other's 09:05.
    const rows = [host(1, 'a', [10, 10], [1, 1], [2, 3]),
                  host(2, 'b', [5, 5, 5], [2, 2, 2], [1, 2, 3])]
    const out = combineThroughput(rows, (id) => (id === 1 ? 'one' : 'two'))
    expect(out.ts).toEqual([1, 2, 3])
    // Host a has nothing at ts 1, so the total there is unmeasured.
    expect(out.inValues).toEqual([null, 15, 15])
  })

  it('picks the same host for a cluster however the API ordered the rows', () => {
    // Otherwise a refetch that changed nothing reshuffles the chart.
    const rows = [host(2, 'b', [99, 99, 99], [9, 9, 9]),
                  host(1, 'a', [10, 10, 10], [1, 1, 1])]
    const out = combineThroughput(rows, () => 'lab-cluster')
    expect(out.inValues).toEqual([10, 10, 10])
  })

  it('answers empty for no hosts rather than throwing', () => {
    expect(combineThroughput([], () => null))
      .toEqual({ ts: [], inValues: [], outValues: [] })
  })
})
