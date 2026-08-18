/** Shared "no value" placeholder for every formatter below. Never a bare separator. */
export const UNKNOWN = 'unknown'

export function fmtBytes(n?: number | null): string {
  if (n == null) return UNKNOWN
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(1)} ${units[i]}`
}

export function fmtUptime(s?: number | null): string {
  if (s == null || s <= 0) return UNKNOWN
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (d > 0) return `${d}d ${h}h`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

export function fmtPct(n?: number | null): string {
  return n == null ? UNKNOWN : `${Math.round(n)}%`
}

/** Seconds remaining → a short duration ("45s", "3m 20s"), for an ETA that
 *  needs second-level precision fmtUptime's minute floor does not give
 *  (UploadDialog: a 30s ISO upload would otherwise read as "0m"). */
export function fmtEta(s?: number | null): string {
  if (s == null || !Number.isFinite(s) || s < 0) return UNKNOWN
  const r = Math.round(s)
  const m = Math.floor(r / 60)
  const sec = r % 60
  if (m === 0) return `${sec}s`
  return sec > 0 ? `${m}m ${sec}s` : `${m}m`
}

/** bytes/s → bit-rate display (network cards, doc 06 Network/throughput).
 *
 *  Scales its own unit. It used to be hard-wired to Mbps, which reports a real
 *  4.6 kB/s trickle (the actual traffic on an idle home node) as "0.0 Mbps",
 *  i.e. as nothing at all. Decimal steps, not binary: network rates have
 *  always been quoted in thousands. */
export function fmtBps(n?: number | null): string {
  if (n == null) return UNKNOWN
  const units = ['bps', 'kbps', 'Mbps', 'Gbps', 'Tbps']
  let v = n * 8
  let i = 0
  while (Math.abs(v) >= 1000 && i < units.length - 1) { v /= 1000; i++ }
  return `${v.toFixed(1)} ${units[i]}`
}

const DOW = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday',
             'Saturday', 'Sunday']  // cron accepts both 0 and 7 for Sunday

/**
 * A 5-field cron expression → the sentence it means ("every day at 02:00").
 *
 * The schedules table stores cron and nothing else (models.Schedule.cron, and
 * jobs/scheduler.py hands it straight to APScheduler's CronTrigger), so this
 * translates rather than replaces it: whatever an operator typed, or a preset
 * built, is described from the stored value itself and cannot drift from what
 * will actually fire.
 *
 * Deliberately partial. It covers the shapes the form's presets produce plus
 * the handful people write by hand, and anything else falls through to naming
 * the expression instead of guessing at it: a wrong sentence about when a
 * backup runs is worse than no sentence.
 */
export function fmtCron(cron: string): string {
  const f = cron.trim().split(/\s+/)
  const plain = `on the cron schedule ${cron.trim()}`
  if (f.length !== 5) return plain
  const [min, hour, dom, mon, dow] = f
  if (dom !== '*' || mon !== '*') return plain
  const every = /^\*\/(\d+)$/.exec(min)
  if (every && hour === '*' && dow === '*') {
    return `every ${every[1]} minutes`
  }
  if (!/^\d{1,2}$/.test(min)) return plain
  const at = (h: string) => `${h.padStart(2, '0')}:${min.padStart(2, '0')}`
  if (hour === '*') {
    if (dow !== '*') return plain  // "hourly but only on Tuesdays" is a rule, not a preset
    return Number(min) === 0 ? 'every hour, on the hour'
      : `every hour, ${Number(min)} minutes past`
  }
  if (!/^\d{1,2}$/.test(hour) || Number(hour) > 23 || Number(min) > 59) return plain
  if (dow === '*') return `every day at ${at(hour)}`
  if (/^[0-7]$/.test(dow)) return `every ${DOW[Number(dow)]} at ${at(hour)}`
  return plain
}
