/**
 * Shared status colouring and relative-time formatting for anything that
 * renders a job/audit/alert row: ActivityFeed (the dashboard feed) and
 * BellPopover (the bell's job list). Kept in a plain .ts file rather than
 * exported alongside a component so oxlint's react/only-export-components
 * (fast-refresh) rule has nothing to flag here.
 */

export const TINT: Record<string, string> = {
  succeeded: 'bg-green-dim text-green',
  ok: 'bg-green-dim text-green',
  resolved: 'bg-green-dim text-green',
  failed: 'bg-red-dim text-red',
  error: 'bg-red-dim text-red',
  denied: 'bg-red-dim text-red',
  firing: 'bg-red-dim text-red',
  running: 'bg-blue-dim text-blue',
  queued: 'bg-blue-dim text-blue',
  canceled: 'bg-panel-2 text-text-3',
  interrupted: 'bg-amber-dim text-amber',
}

export function ago(iso: string): string {
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000))
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  return `${Math.round(s / 86400)}d ago`
}
