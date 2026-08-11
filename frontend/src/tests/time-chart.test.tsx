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

import { TimeChart, buildOptions, timeTickFormatter, unitFormatter } from '../components/charts/TimeChart'

describe('unitFormatter', () => {
  it('renders percentages as percentages', () => {
    expect(unitFormatter('percent')(42.4)).toBe('42%')
  })

  it('renders bytes through the shared byte formatter, not as a raw count', () => {
    // The memory chart used to plot mem_bytes against unlabelled ticks, which
    // is where "not valid data" came from: 2161287168 reads as nothing.
    expect(unitFormatter('bytes')(2161287168)).toBe('2.0 GiB')
  })

  it('renders throughput in Mbps', () => {
    expect(unitFormatter('bps')(1_300_000)).toBe('10.4 Mbps')
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

describe('buildOptions', () => {
  const base = { width: 600, height: 160, label: 'CPU', accent: 'rgb(1,2,3)',
                 axis: 'rgb(4,5,6)', grid: 'rgb(7,8,9)', span: 86400 }

  it('turns both axes on, unlike the Sparkline it replaces', () => {
    const o = buildOptions({ ...base, unit: 'percent' })
    expect(o.axes).toHaveLength(2)
    expect(o.axes![0].show).not.toBe(false)
    expect(o.axes![1].show).not.toBe(false)
  })

  it('pins a percent chart to 0..100 so a flat 3% is not drawn as a full box', () => {
    const o = buildOptions({ ...base, unit: 'percent' })
    expect(o.scales!.y!.range).toEqual([0, 100])
  })

  it('lets a bytes chart find its own range, but labels the ticks in bytes', () => {
    const o = buildOptions({ ...base, unit: 'bytes' })
    expect(o.scales!.y!.range).not.toEqual([0, 100])
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
