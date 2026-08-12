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
