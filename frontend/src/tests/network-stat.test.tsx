import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { NetworkStat } from '../components/StatRings'

/** The arrow subpath inside one of the two icons. The bar subpath beside it
 *  is deliberately unlabelled: it never changes, which is the point. */
const arrow = (dir: 'upload' | 'download') =>
  document.querySelector(`[data-part="${dir}-arrow"]`) as SVGPathElement

/** Every path in the tile that is NOT an arrow, ie. the two baseline bars. */
const bars = () =>
  Array.from(document.querySelectorAll('svg path:not([data-part])'))

describe('NetworkStat', () => {
  it('colours and blinks only the arrow that is actually moving', () => {
    render(<NetworkStat inBps={1_200_000} outBps={0} />)
    // Download is moving: its arrow goes green and blinks.
    expect(arrow('download').getAttribute('class')).toContain('fill-green')
    expect(arrow('download').getAttribute('class')).toContain('animate-pulse')
    // Upload is idle, so it stays the ordinary label colour. A colour here
    // would mean nothing if it were always on.
    expect(arrow('upload').getAttribute('class')).toContain('fill-text-2')
    expect(arrow('upload').getAttribute('class')).not.toContain('animate-pulse')
  })

  it('blinks upload red when the traffic is going the other way', () => {
    render(<NetworkStat inBps={0} outBps={88_000} />)
    expect(arrow('upload').getAttribute('class')).toContain('fill-red')
    expect(arrow('upload').getAttribute('class')).toContain('animate-pulse')
    expect(arrow('download').getAttribute('class')).not.toContain('animate-pulse')
  })

  it('keeps the icon itself in the theme colour whatever the arrows do', () => {
    // The blink lives INSIDE the icon. The baseline bar is the icon's own
    // outline and must never take a status colour, or the tile reads as a
    // status light rather than as one of this row's labels.
    render(<NetworkStat inBps={1_200_000} outBps={88_000} />)
    expect(bars()).toHaveLength(2)
    for (const bar of bars()) {
      expect(bar.getAttribute('class')).toBe('fill-text-2')
    }
  })

  it('does not blink the two arrows as one', () => {
    // animate-pulse alone runs off a shared document timeline, so two elements
    // carrying it stay in lockstep and read as a single joined indicator.
    // Upload and download are independent streams and must look it.
    render(<NetworkStat inBps={1_200_000} outBps={88_000} />)
    const up = arrow('upload').getAttribute('class') ?? ''
    const down = arrow('download').getAttribute('class') ?? ''
    const duration = (cls: string) => /\[animation-duration:([\d.]+)s\]/.exec(cls)?.[1]
    expect(duration(up)).toBeDefined()
    expect(duration(down)).toBeDefined()
    expect(duration(up)).not.toBe(duration(down))
    // One starts mid-cycle, so they are out of phase from the first frame
    // rather than only drifting apart over time.
    expect(down).toMatch(/\[animation-delay:-[\d.]+s\]/)
  })

  it('turns the blink off for anyone who asked for less motion', () => {
    render(<NetworkStat inBps={1_200_000} outBps={88_000} />)
    for (const dir of ['upload', 'download'] as const) {
      expect(arrow(dir).getAttribute('class')).toContain('motion-reduce:animate-none')
    }
  })

  it('shows upload over download in bits per second, the charts vocabulary', () => {
    render(<NetworkStat inBps={1_200_000} outBps={88_000} />)
    expect(screen.getByText('704.0 kbps / 9.6 Mbps')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Network, 704.0 kbps up, 9.6 Mbps down' }))
      .toBeInTheDocument()
  })

  it('says unknown rather than drawing a calm idle zero', () => {
    // A failed /cluster/summary must not read as "no traffic", which is a
    // different and false claim from "we could not check".
    render(<NetworkStat inBps={null} outBps={null} unknown />)
    expect(screen.getByText('unknown')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Network unknown' })).toBeInTheDocument()
    expect(arrow('upload').getAttribute('class')).not.toContain('animate-pulse')
    expect(arrow('download').getAttribute('class')).not.toContain('animate-pulse')
  })
})
