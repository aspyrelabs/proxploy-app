import { describe, expect, it } from 'vitest'
import { fmtBps, fmtBytes, fmtCron, fmtEta, fmtPct, fmtUptime } from '../lib/format'

describe('format helpers', () => {
  it('formats bytes with binary units', () => {
    expect(fmtBytes(0)).toBe('0.0 B')
    expect(fmtBytes(4294967296)).toBe('4.0 GiB')
    expect(fmtBytes(null)).toBe('unknown')
  })
  it('formats uptime coarsely', () => {
    expect(fmtUptime(90)).toBe('1m')
    expect(fmtUptime(7260)).toBe('2h 1m')
    expect(fmtUptime(864000)).toBe('10d 0h')
    expect(fmtUptime(null)).toBe('unknown')
  })
  it('formats percents and throughput', () => {
    expect(fmtPct(41.6)).toBe('42%')
    expect(fmtPct(null)).toBe('unknown')
    expect(fmtBps(1250000)).toBe('10.0 Mbps')
    expect(fmtBps(null)).toBe('unknown')
    // A real idle node trickles a few kB/s. Hard-wired Mbps reported that as
    // "0.0 Mbps", which reads as no traffic at all.
    expect(fmtBps(4657)).toBe('37.3 kbps')
    expect(fmtBps(100)).toBe('800.0 bps')
    expect(fmtBps(1_250_000_000)).toBe('10.0 Gbps')
  })
  it('never returns a bare separator for a missing value', () => {
    expect(fmtBytes(undefined)).not.toBe(', ')
    expect(fmtUptime(undefined)).not.toBe(', ')
    expect(fmtPct(undefined)).not.toBe(', ')
    expect(fmtBps(undefined)).not.toBe(', ')
  })
  it('formats an ETA down to the second, unlike fmtUptime which is minute-coarse', () => {
    expect(fmtEta(45)).toBe('45s')
    expect(fmtEta(90)).toBe('1m 30s')
    expect(fmtEta(120)).toBe('2m')
    expect(fmtEta(null)).toBe('unknown')
    expect(fmtEta(-1)).toBe('unknown')
  })
  it('describes a cron expression in plain language', () => {
    expect(fmtCron('0 2 * * *')).toBe('every day at 02:00')
    expect(fmtCron('30 3 * * 2')).toBe('every Tuesday at 03:30')
    expect(fmtCron('0 0 * * 0')).toBe('every Sunday at 00:00')
    expect(fmtCron('0 0 * * 7')).toBe('every Sunday at 00:00')   // cron takes both
    expect(fmtCron('0 * * * *')).toBe('every hour, on the hour')
    expect(fmtCron('15 * * * *')).toBe('every hour, 15 minutes past')
    expect(fmtCron('*/5 * * * *')).toBe('every 5 minutes')
    expect(fmtCron('  0   2  *  *  * ')).toBe('every day at 02:00')
  })
  it('names an expression it cannot describe instead of guessing at it', () => {
    // A wrong sentence about when a backup runs is worse than no sentence, so
    // every shape outside the presets falls through to the expression itself.
    expect(fmtCron('0 2 1 * *')).toBe('on the cron schedule 0 2 1 * *')
    expect(fmtCron('0 2 * 6 *')).toBe('on the cron schedule 0 2 * 6 *')
    expect(fmtCron('0 2 * * 1-5')).toBe('on the cron schedule 0 2 * * 1-5')
    expect(fmtCron('0 * * * 2')).toBe('on the cron schedule 0 * * * 2')
    expect(fmtCron('0 2 * *')).toBe('on the cron schedule 0 2 * *')
    expect(fmtCron('99 99 * * *')).toBe('on the cron schedule 99 99 * * *')
  })
})
