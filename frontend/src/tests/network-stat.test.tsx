import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

// Icon is stubbed so this file tests the TILE, not the font subset;
// icon.test.tsx pins Icon's own contract (host-actions-menu.test.tsx
// precedent).
vi.mock('../components/ui/icon', () => ({
  Icon: ({ name, className }: { name: string; className?: string }) => (
    <span data-icon={name} className={className} />
  ),
}))

import { NetworkStat } from '../components/StatRings'

const arrow = (name: string) =>
  document.querySelector(`[data-icon="${name}"]`) as HTMLElement

describe('NetworkStat', () => {
  it('blinks each arrow only in the direction that is actually moving', () => {
    render(<NetworkStat inBps={1_200_000} outBps={0} />)
    // Download is moving, so its arrow is live and green.
    expect(arrow('download_2').className).toContain('text-green')
    expect(arrow('download_2').className).toContain('animate-pulse')
    // Upload is idle, so it stays quiet rather than blinking a colour that
    // would then mean nothing.
    expect(arrow('upload_2').className).toContain('text-text-3')
    expect(arrow('upload_2').className).not.toContain('animate-pulse')
  })

  it('blinks upload red when traffic is going the other way', () => {
    render(<NetworkStat inBps={0} outBps={88_000} />)
    expect(arrow('upload_2').className).toContain('text-red')
    expect(arrow('upload_2').className).toContain('animate-pulse')
    expect(arrow('download_2').className).not.toContain('animate-pulse')
  })

  it('turns the blink off for anyone who asked for less motion', () => {
    render(<NetworkStat inBps={1_200_000} outBps={88_000} />)
    for (const n of ['upload_2', 'download_2']) {
      expect(arrow(n).className).toContain('motion-reduce:animate-none')
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
    expect(arrow('upload_2').className).not.toContain('animate-pulse')
    expect(arrow('download_2').className).not.toContain('animate-pulse')
  })
})
