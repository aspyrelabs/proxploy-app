import { Link } from '@tanstack/react-router'
import { useEntitlements } from '../api/hooks'

export function TierPill() {
  const { tier, grace } = useEntitlements()
  const label = tier === 'builtin' ? 'FREE · ALL FEATURES'
    : grace?.in_grace ? `${tier.toUpperCase()} · GRACE` : tier.toUpperCase()
  const cls = grace?.in_grace ? 'border-amber text-amber'
    : tier === 'builtin' ? 'border-line text-text-3' : 'border-amber/40 text-amber'
  return (
    // '/settings' lands in the route tree in Task 15; cast until then
    <Link to={'/settings' as never} className={`rounded-full border px-2.5 py-1 font-mono text-[9.5px] tracking-[.08em] ${cls}`}>
      {label}
    </Link>
  )
}
