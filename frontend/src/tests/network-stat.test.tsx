import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { NetworkStat, plotSamples, splitRate, windowLabel } from '../components/StatRings'
import { fmtBps, fmtByteRate } from '../lib/format'

const part = (name: string) => document.querySelector(`[data-part="${name}"]`)

/** A minute of samples, so the window line has something real to report. */
const ts = Array.from({ length: 16 }, (_, i) => 1_700_000_000 + i * 60)

describe('plotSamples', () => {
  it('keeps an ordinary series with its slots', () => {
    expect(plotSamples([10, 20, 30])).toEqual([[0, 10], [1, 20], [2, 30]])
  })

  it('skips a negative sample rather than drawing a counter reset', () => {
    // A reboot zeroes PVE's cumulative counter, so the delta the poller takes
    // goes negative. Drawing its absolute value is a fabricated traffic spike
    // at exactly the moment someone is watching, and drawing the negative is a
    // rate below zero. Neither happened, so neither is plotted.
    expect(plotSamples([10, -400, 30])).toEqual([[0, 10], [2, 30]])
  })

  it('skips a gap the poller recorded rather than calling it zero', () => {
    // null means "could not measure", which is a different claim from "no
    // traffic". The slot is kept, so the hole stays where it happened instead
    // of sliding every later sample left.
    expect(plotSamples([10, null, undefined, 30])).toEqual([[0, 10], [3, 30]])
    expect(plotSamples([10, Number.NaN, 30])).toEqual([[0, 10], [2, 30]])
  })

  it('keeps a genuine zero, which is a measurement', () => {
    expect(plotSamples([0, 5])).toEqual([[0, 0], [1, 5]])
  })
})

describe('fmtByteRate', () => {
  it('steps its unit every 1000, not every 1024', () => {
    // The unit is spelled KB, not KiB, so a 1024 step would be quietly wrong
    // by 2.4% against the label it prints.
    expect(fmtByteRate(0)).toBe('0.0 B/s')
    expect(fmtByteRate(1)).toBe('1.0 B/s')
    expect(fmtByteRate(999)).toBe('999.0 B/s')
    expect(fmtByteRate(1000)).toBe('1.0 KB/s')
    expect(fmtByteRate(1024)).toBe('1.0 KB/s')
    expect(fmtByteRate(1_200_000)).toBe('1.2 MB/s')
    expect(fmtByteRate(2_400_000_000)).toBe('2.4 GB/s')
    expect(fmtByteRate(5_000_000_000_000)).toBe('5.0 TB/s')
  })

  it('says unknown rather than printing a unit with no figure', () => {
    expect(fmtByteRate(null)).toBe('unknown')
    expect(fmtByteRate(undefined)).toBe('unknown')
  })

  it('leaves fmtBps alone, because the rest of the app still reads bits', () => {
    // Two rate formatters exist on purpose (see lib/format.ts). This asserts
    // the SAME input lands in two different vocabularies, so a later "cleanup"
    // that collapses them fails here instead of silently relabelling either
    // the Network page or this tile.
    expect(fmtBps(200_000)).toBe('1.6 Mbps')
    expect(fmtByteRate(200_000)).toBe('200.0 KB/s')
  })
})

describe('splitRate', () => {
  it('scales its unit rather than reporting a trickle as nothing', () => {
    // One decimal at every step, and the unit moves with the figure: a real
    // idle node's few KB/s must not round away to "0.0 MB/s".
    expect(splitRate(500)).toEqual(['500.0', 'B/s'])
    expect(splitRate(4_600)).toEqual(['4.6', 'KB/s'])
    expect(splitRate(1_200_000)).toEqual(['1.2', 'MB/s'])
    expect(splitRate(2_400_000_000)).toEqual(['2.4', 'GB/s'])
    expect(splitRate(0)).toEqual(['0.0', 'B/s'])
  })

  it('reads in bytes, not the bits every other network surface uses', () => {
    // 200 kB/s is the boundary case that reads differently in both figure and
    // unit: bits would make this "1.6 Mbps". A change back to fmtBps must fail
    // loudly here rather than quietly restyle the tile.
    expect(splitRate(200_000)).toEqual(['200.0', 'KB/s'])
    expect(splitRate(125)).toEqual(['125.0', 'B/s'])  // fmtBps would say 1.0 kbps
  })

  it('has no unit to show when there is no reading', () => {
    expect(splitRate(null)).toEqual(['unknown', ''])
  })
})

describe('windowLabel', () => {
  it('reports the span the samples actually cover', () => {
    expect(windowLabel(ts)).toBe('last 15 min')
    expect(windowLabel([0, 7200])).toBe('last 2 h')
  })

  it('says there is no history rather than inventing a window', () => {
    expect(windowLabel([])).toBe('no history yet')
    expect(windowLabel(undefined)).toBe('no history yet')
    expect(windowLabel([1_700_000_000])).toBe('no history yet')
  })
})

describe('NetworkStat', () => {
  it('leads with the figures, not the arrows', () => {
    // The whole point of the tile is two numbers. They take the display font at
    // 19px with tabular-nums so the digits do not jitter as values swap in on a
    // background poll; the arrows are 12px markers that only say which
    // direction each line is.
    render(<NetworkStat inBps={1_200_000} outBps={88_000} ts={ts} />)
    const figure = screen.getByText('1.2')
    expect(figure.className).toContain('font-display')
    expect(figure.className).toContain('tabular-nums')
    expect(screen.getByText('MB/s').className).toContain('font-mono')
    expect(part('in-arrow')?.className).toContain('text-[12px]')
  })

  it('colours down cyan and up amber', () => {
    render(<NetworkStat inBps={1_200_000} outBps={88_000} ts={ts} />)
    expect(part('in-arrow')?.textContent).toBe('↓')
    expect(part('in-arrow')?.className).toContain('text-cyan')
    expect(part('out-arrow')?.textContent).toBe('↑')
    expect(part('out-arrow')?.className).toContain('text-amber')
  })

  it('draws both directions on one spark, cyan in and amber out', () => {
    render(<NetworkStat inBps={1_200_000} outBps={88_000} ts={ts}
      inValues={[10, 90, 40]} outValues={[5, 8, 6]} />)
    expect(part('spark-in')?.getAttribute('stroke')).toBe('var(--cyan)')
    expect(part('spark-out')?.getAttribute('stroke')).toBe('var(--amber)')
  })

  it('shares one scale so a trickle does not look like a flood', () => {
    // Independent scales would stretch the quiet direction to full height, and
    // the two lines would report equal traffic for a 10x difference.
    render(<NetworkStat inBps={1} outBps={1} ts={ts}
      inValues={[0, 100]} outValues={[0, 10]} />)
    const top = (d: string | null | undefined) =>
      Math.min(...[...(d ?? '').matchAll(/[ML]\S+ ([\d.]+)/g)].map((m) => Number(m[1])))
    expect(top(part('spark-in')?.getAttribute('d'))).toBeLessThan(
      top(part('spark-out')?.getAttribute('d')))
  })

  it('holds its shape with no history instead of collapsing', () => {
    // A tile that shrinks when the series are missing drags the three rings
    // beside it out of line, so the spark keeps its 34px and its baseline.
    render(<NetworkStat inBps={1_200_000} outBps={88_000} />)
    expect(part('spark')?.getAttribute('height')).toBe('34')
    expect(part('spark-in')).toBeNull()
    expect(screen.getByText('no history yet')).toBeInTheDocument()
  })

  it('names the window under the figures, because a rate needs one', () => {
    // "1.2 MB/s" on its own is unreadable the second time you look at it:
    // measured over how long.
    render(<NetworkStat inBps={1_200_000} outBps={88_400} ts={ts} />)
    expect(screen.getByText('last 15 min')).toBeInTheDocument()
  })

  it('says nothing about scope when the reading is the combined one', () => {
    // The whole row is already cluster-wide and the three gauges beside this
    // one sum every host without announcing it, so "all hosts" here was
    // furniture. Pinned as an absence, so it cannot quietly come back.
    for (const props of [{ ts }, {}]) {  // with history and without
      const { unmount } = render(
        <NetworkStat inBps={1_200_000} outBps={88_400} {...props} />)
      const footer = screen.getByText(/^(last 15 min|no history yet)$/)
      expect(footer.textContent).not.toContain('·')
      expect(footer.textContent).not.toMatch(/host|node|cluster|all/i)
      expect(screen.getByRole('img',
        { name: 'Network, 1.2 MB/s in, 88.4 KB/s out' })).toBeInTheDocument()
      unmount()
    }
  })

  it('does name the scope when it is not the combined reading', () => {
    // A per-node tile IS a departure from what the row otherwise means, and
    // nothing else on screen would give that away.
    render(<NetworkStat inBps={1_200_000} outBps={88_400} ts={ts} scope="pve-1" />)
    expect(screen.getByText('last 15 min · pve-1')).toBeInTheDocument()
    expect(screen.getByRole('img',
      { name: 'Network, 1.2 MB/s in, 88.4 KB/s out, pve-1' })).toBeInTheDocument()
  })

  it('turns the spark transition off for anyone who asked for less motion', () => {
    render(<NetworkStat inBps={1} outBps={1} ts={ts} inValues={[1, 2]} outValues={[1, 2]} />)
    // getAttribute, not .className: on an SVG element that is an
    // SVGAnimatedString, which contains nothing a string matcher can see.
    expect(part('spark-in')?.getAttribute('class'))
      .toContain('motion-reduce:transition-none')
  })

  it('says unknown rather than drawing a calm idle zero', () => {
    // A failed /cluster/summary must not read as "no traffic", which is a
    // different and false claim from "we could not check".
    render(<NetworkStat inBps={null} outBps={null} unknown inValues={[5, 9]} />)
    // "?" in both figure slots and the word once underneath, which is exactly
    // how Ring spells an unmeasured gauge.
    expect(screen.getAllByText('?')).toHaveLength(2)
    expect(screen.getByText('unknown')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Network unknown' })).toBeInTheDocument()
    // The spark is suppressed too: stale history under an unknown reading
    // looks like a live series.
    expect(part('spark-in')).toBeNull()
  })
})
