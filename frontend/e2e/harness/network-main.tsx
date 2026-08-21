import { createRoot } from 'react-dom/client'
import { NetworkStat, NetworkStatSkeleton, Ring, RingSkeleton } from '../../src/components/StatRings'
import './harness.css'

/**
 * Preview harness for the rewritten NetworkStat, the fourth tile in the Hosts
 * page cluster-usage row.
 *
 * NOT part of the app, for the reason e2e/harness/main.tsx gives: it builds
 * with the harness's own Vite config into e2e/harness/dist and nothing under
 * src/ imports it, so it cannot reach the shipped bundle.
 *
 * WHY IT EXISTS. The new tile has to be looked at beside the three real gauges
 * before it replaces what is on /hosts, and /hosts is behind login: a fresh
 * Playwright context has no session cookie, so driving the live route renders
 * the signed-out page instead. This reproduces the row exactly, with the REAL
 * Ring and the REAL stylesheet, and needs no backend at all.
 *
 * The rings are the shipped component untouched. Only the fourth tile changed.
 */

const card = 'rounded-card border border-line-soft bg-panel p-5'

/** A believable 15 minutes off /network/throughput: one sample a minute, a
 *  download burst partway through, and a quieter upload alongside it. The
 *  values are bytes/sec, which is what the metrics series carries and, on this
 *  tile alone, what gets printed. */
const TS = Array.from({ length: 16 }, (_, i) => 1_700_000_000 + i * 60)
const IN = [42_000, 51_000, 47_000, 63_000, 210_000, 480_000, 690_000, 620_000,
            410_000, 180_000, 96_000, 61_000, 55_000, 71_000, 58_000, 150_000]
// One reset in the middle: a node rebooted, the counter zeroed, and the poller
// recorded no sample rather than a fabricated spike. The tile must bridge that
// gap, not plot it.
const OUT: (number | null)[] = [18_000, 22_000, 19_000, 26_000, 44_000, 71_000,
                                null, 88_000, 62_000, 31_000, 24_000, 20_000,
                                19_000, 25_000, 21_000, 38_000]

/** The shipped three, so the fourth tile is judged against what it actually
 *  sits next to rather than against a description of it. */
function Rings() {
  return (
    <>
      <Ring label="CPU" pct={37} sub="4.4 / 12 cores" stops={['#F5B544', '#E0862B']} />
      <Ring label="Memory" pct={61} sub="19.5 GiB / 32.0 GiB" stops={['#34D3C6', '#5B9DF9']} />
      <Ring label="Storage" pct={78} sub="1.4 TiB / 1.8 TiB" stops={['#A78BFA', '#6D5AE6']} />
    </>
  )
}

const ROWS: { label: string; note: string; tile: React.ReactNode }[] = [
  {
    label: 'with-history',
    note: 'The everyday state: live rates from /cluster/summary, 15 minutes of '
        + 'history from /network/throughput, one gap where a node reset.',
    tile: <NetworkStat inBps={1_240_000} outBps={88_400} ts={TS}
      inValues={IN} outValues={OUT} />,
  },
  {
    label: 'no-history',
    note: 'Summary landed, throughput has not. The figures are real and the '
        + 'spark keeps its 34px, so the three rings do not move when it fills.',
    tile: <NetworkStat inBps={1_240_000} outBps={88_400} />,
  },
  {
    label: 'per-node-scope',
    note: 'A per-node caller names its scope, because that tile IS a departure '
        + 'from the combined reading the rest of the row means. The combined '
        + 'states above say the window and stop.',
    tile: <NetworkStat inBps={4_600} outBps={1_200} ts={TS}
      inValues={IN.map((v) => v / 40)} outValues={OUT.map((v) => v && v / 40)}
      scope="pve-1" />,
  },
  {
    label: 'quiet-cluster',
    note: 'An idle home node. A few kB/s must still read as traffic rather '
        + 'than round away to nothing.',
    tile: <NetworkStat inBps={4_600} outBps={310} ts={TS}
      inValues={IN.map((v) => v / 400)} outValues={OUT.map((v) => v && v / 400)} />,
  },
  {
    label: 'widest',
    // The worst case the formatter can produce: five digits and a decimal at
    // 19px, plus the longest unit. If anything is going to wrap out of the
    // 168px box or shove the three rings sideways, it is this.
    note: 'Not a realistic reading, a width check. 999.9 is the widest figure '
        + 'fmtByteRate can print, so this is the row that proves nothing wraps.',
    tile: <NetworkStat inBps={999_900_000} outBps={999_900} ts={TS}
      inValues={IN} outValues={OUT} />,
  },
  {
    label: 'unknown',
    note: '/cluster/summary failed. Not a calm 0, which is a different and '
        + 'false claim, and no stale spark under it either.',
    tile: <NetworkStat inBps={null} outBps={null} unknown inValues={IN} outValues={OUT} />,
  },
  {
    label: 'skeleton',
    note: 'Nothing fetched yet. Must lay out identically to the tile above it, '
        + 'which is the rule the ring skeletons already follow.',
    tile: <NetworkStatSkeleton />,
  },
]

function Harness() {
  return (
    // Reproduces AppShell: a w-[236px] sidebar that hides below 720px, beside
    // <main className="min-w-0 flex-1 p-6">, so the row's width matches /hosts.
    <div className="flex">
      <div className="w-[236px] shrink-0 max-[720px]:hidden" />
      <main className="min-w-0 flex-1 space-y-5 p-6">
        <h1 className="font-display text-[22px] font-semibold">
          Network tile, beside the three real gauges
        </h1>
        {ROWS.map((r) => (
          <div key={r.label} data-state={r.label}>
            <div className="mb-1.5 font-mono text-[11px] text-text-3">{r.label}</div>
            <div className={`${card} flex justify-around`}>
              {r.label === 'skeleton'
                ? (
                  <>
                    <RingSkeleton label="CPU" />
                    <RingSkeleton label="Memory" />
                    <RingSkeleton label="Storage" />
                  </>
                )
                : <Rings />}
              {r.tile}
            </div>
            <p className="mt-1.5 max-w-[760px] text-[11.5px] text-text-3">{r.note}</p>
          </div>
        ))}
      </main>
    </div>
  )
}

createRoot(document.getElementById('root')!).render(<Harness />)
