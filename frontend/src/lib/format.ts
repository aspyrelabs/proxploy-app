export function fmtBytes(n?: number | null): string {
  if (n == null) return ', '
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(1)} ${units[i]}`
}

export function fmtUptime(s?: number | null): string {
  if (s == null || s <= 0) return ', '
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (d > 0) return `${d}d ${h}h`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

export function fmtPct(n?: number | null): string {
  return n == null ? ', ' : `${Math.round(n)}%`
}

/** bytes/s → Mbps display (network cards, doc 06 Network/throughput). */
export function fmtBps(n?: number | null): string {
  return n == null ? ', ' : `${((n * 8) / 1e6).toFixed(1)} Mbps`
}
