import { describe, expect, it } from 'vitest'
import { fmtBps, fmtBytes, fmtPct, fmtUptime } from '../lib/format'

describe('format helpers', () => {
  it('formats bytes with binary units', () => {
    expect(fmtBytes(0)).toBe('0.0 B')
    expect(fmtBytes(4294967296)).toBe('4.0 GiB')
    expect(fmtBytes(null)).toBe('—')
  })
  it('formats uptime coarsely', () => {
    expect(fmtUptime(90)).toBe('1m')
    expect(fmtUptime(7260)).toBe('2h 1m')
    expect(fmtUptime(864000)).toBe('10d 0h')
    expect(fmtUptime(null)).toBe('—')
  })
  it('formats percents and throughput', () => {
    expect(fmtPct(41.6)).toBe('42%')
    expect(fmtPct(null)).toBe('—')
    expect(fmtBps(1250000)).toBe('10.0 Mbps')
  })
})
