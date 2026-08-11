/** TimeChart: the real chart behind CPU / memory / storage on the host page.
 *
 *  uPlot draws onto a canvas jsdom does not implement, so nothing here asserts
 *  pixels. What IS asserted is everything that decides what those pixels mean:
 *  which formatter a unit selects, that a percent chart pins its y scale to
 *  0..100, that both axes are switched ON (the Sparkline's defining choice was
 *  to switch them off), that the width comes from the container rather than a
 *  prop, and that an empty series says so in words.
 */
import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { TimeChart, buildOptions, timeTickFormatter, unitFormatter, yTop } from '../components/charts/TimeChart'

describe('unitFormatter', () => {
  it('renders percentages as percentages', () => {
    expect(unitFormatter('percent')(42.4)).toBe('42%')
    expect(unitFormatter('percent')(0)).toBe('0%')
  })

  it('keeps enough precision that an idle node is not reported as a dead one', () => {
    // Rounding to whole percent prints the live node's real 0.14% CPU as "0%".
    expect(unitFormatter('percent')(0.143)).toBe('0.14%')
    expect(unitFormatter('percent')(6.6)).toBe('6.6%')
  })

  it('renders bytes through the shared byte formatter, not as a raw count', () => {
    // The memory chart used to plot mem_bytes against unlabelled ticks, which
    // is where "not valid data" came from: 2161287168 reads as nothing.
    expect(unitFormatter('bytes')(2161287168)).toBe('2.0 GiB')
  })

  it('renders throughput at whatever magnitude it actually is', () => {
    expect(unitFormatter('bps')(1_300_000)).toBe('10.4 Mbps')
    // The measured peak on the node this was built against is 4.6 kB/s.
    expect(unitFormatter('bps')(4657)).toBe('37.3 kbps')
  })

  it('says unknown for a gap rather than drawing a zero', () => {
    expect(unitFormatter('percent')(null)).toBe('unknown')
  })
})

describe('timeTickFormatter', () => {
  const t = Date.UTC(2026, 7, 11, 14, 5) / 1000

  it('uses clock time inside a day', () => {
    expect(timeTickFormatter(6 * 3600)(t)).toMatch(/\d{2}:\d{2}/)
  })

  it('drops to a date once the range spans more than two days', () => {
    const label = timeTickFormatter(7 * 86400)(t)
    expect(label).not.toMatch(/:/)
    expect(label).toMatch(/Aug/)
  })
})

describe('yTop', () => {
  it('gives a nearly-idle percentage series room to show shape, in a stated band', () => {
    // Measured on the live node: cpu_pct peaks at 0.143, disk_pct at 0.30.
    expect(yTop('percent', 0.143)).toBe(5)
    expect(yTop('percent', 0.3)).toBe(5)
  })

  it('steps a percentage axis up in bands rather than tracking the data', () => {
    expect(yTop('percent', 6.6)).toBe(10)   // measured mem_pct
    expect(yTop('percent', 12)).toBe(25)
    expect(yTop('percent', 60)).toBe(100)
  })

  it('never exceeds 100 for a percentage', () => {
    expect(yTop('percent', 99)).toBe(100)
  })

  it('tracks the data for units that have no natural ceiling', () => {
    expect(yTop('bytes', 1000)).toBeCloseTo(1050)
    expect(yTop('bps', 0)).toBe(1)
  })
})

describe('buildOptions', () => {
  const base = { width: 600, height: 160, label: 'CPU', accent: 'rgb(1,2,3)',
                 axis: 'rgb(4,5,6)', grid: 'rgb(7,8,9)', span: 86400, max: 50 }

  it('turns both axes on, unlike the Sparkline it replaces', () => {
    const o = buildOptions({ ...base, unit: 'percent' })
    expect(o.axes).toHaveLength(2)
    expect(o.axes![0].show).not.toBe(false)
    expect(o.axes![1].show).not.toBe(false)
  })

  it('anchors every y scale at zero, whatever the unit', () => {
    // A floating baseline is how 0.1% gets drawn as a busy machine.
    expect((buildOptions({ ...base, unit: 'percent' }).scales!.y!.range as number[])[0]).toBe(0)
    expect((buildOptions({ ...base, unit: 'bytes' }).scales!.y!.range as number[])[0]).toBe(0)
  })

  it('sizes a percent axis to a band, not to 100 and not to the data', () => {
    expect(buildOptions({ ...base, unit: 'percent', max: 0.143 }).scales!.y!.range)
      .toEqual([0, 5])
  })

  it('labels a bytes axis in bytes', () => {
    const o = buildOptions({ ...base, unit: 'bytes' })
    const values = o.axes![1].values as (u: unknown, s: number[]) => string[]
    expect(values(null, [1073741824])).toEqual(['1.0 GiB'])
  })

  it('takes its width from the caller, so the container can drive it', () => {
    expect(buildOptions({ ...base, width: 313, unit: 'percent' }).width).toBe(313)
  })

  it('keeps the cursor on, so hovering reads out a value', () => {
    const o = buildOptions({ ...base, unit: 'percent' })
    expect(o.cursor?.show).not.toBe(false)
    expect(o.legend?.show).not.toBe(false)
  })
})

describe('TimeChart', () => {
  const originalRect = HTMLElement.prototype.getBoundingClientRect
  let observed: (() => void) | null = null

  beforeEach(() => {
    HTMLElement.prototype.getBoundingClientRect = function () {
      return { width: 640, height: 160, top: 0, left: 0, right: 640, bottom: 160,
               x: 0, y: 0, toJSON: () => ({}) } as DOMRect
    }
    class RO {
      constructor(cb: () => void) { observed = cb }
      observe() {}
      disconnect() { observed = null }
      unobserve() {}
    }
    vi.stubGlobal('ResizeObserver', RO)
  })

  afterEach(() => {
    HTMLElement.prototype.getBoundingClientRect = originalRect
    vi.unstubAllGlobals()
    observed = null
  })

  it('says "no data yet" instead of drawing an empty box', () => {
    render(<TimeChart ts={[]} values={[]} unit="percent" label="CPU" />)
    expect(screen.getByText(/no data yet/i)).toBeInTheDocument()
  })

  it('treats an all-null series as no data: disk_pct only started recording recently', () => {
    render(<TimeChart ts={[1, 2, 3]} values={[null, null, null]} unit="percent" label="Storage" />)
    expect(screen.getByText(/no data yet/i)).toBeInTheDocument()
  })

  it('draws a series of real zeroes: an idle node is not a missing node', () => {
    // The failure this guards against would hide working data behind the very
    // message this component exists to stop showing.
    render(<TimeChart ts={[1, 2, 3]} values={[0, 0, 0]} unit="percent" label="CPU" />)
    expect(screen.queryByText(/no data yet/i)).not.toBeInTheDocument()
    expect(screen.getByTestId('timechart-plot')).toBeInTheDocument()
  })

  it('states the current and peak value, so a flat line reads as idle', () => {
    render(<TimeChart ts={[1, 2, 3]} values={[0.1, 0.05, 0.14]} unit="percent" label="CPU" />)
    expect(screen.getByText('0.14%')).toBeInTheDocument()
    expect(screen.getByText('now')).toBeInTheDocument()
    expect(screen.getByText(/peak 0\.14%/)).toBeInTheDocument()
    // and says which band the axis is on, so "flat at the bottom of 5%" is
    // legible rather than mysterious
    expect(screen.getByText(/axis to 5\.0%/)).toBeInTheDocument()
  })

  it('draws when even a single real sample exists', () => {
    render(<TimeChart ts={[1, 2]} values={[null, 12]} unit="percent" label="CPU" />)
    expect(screen.queryByText(/no data yet/i)).not.toBeInTheDocument()
    expect(screen.getByTestId('timechart-plot')).toBeInTheDocument()
  })

  it('measures its container rather than taking a fixed width prop', () => {
    render(<TimeChart ts={[1, 2]} values={[10, 20]} unit="percent" label="CPU" />)
    expect(screen.getByTestId('timechart-plot')).toHaveAttribute('data-width', '640')
    // and it re-measures when the box changes, so a narrower viewport shrinks
    // the plot instead of letting the canvas spill out of its card
    HTMLElement.prototype.getBoundingClientRect = function () {
      return { width: 320, height: 160, top: 0, left: 0, right: 320, bottom: 160,
               x: 0, y: 0, toJSON: () => ({}) } as DOMRect
    }
    act(() => { observed?.() })
    expect(screen.getByTestId('timechart-plot')).toHaveAttribute('data-width', '320')
  })

  it('never lets its wrapper exceed the card it sits in', () => {
    const { container } = render(
      <TimeChart ts={[1, 2]} values={[10, 20]} unit="percent" label="CPU" />)
    expect(container.firstElementChild).toHaveClass('w-full')
    expect(container.firstElementChild).toHaveClass('overflow-hidden')
  })
})
