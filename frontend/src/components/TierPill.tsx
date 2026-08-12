import { Link } from '@tanstack/react-router'
import { useEntitlements } from '../api/hooks'

export function TierPill() {
  const { tier, grace } = useEntitlements()
  const label = tier === 'builtin' ? 'FREE · ALL FEATURES'
    : grace?.in_grace ? `${tier.toUpperCase()} · GRACE` : tier.toUpperCase()
  // 'FREE · ALL FEATURES' is ~143px of tracked mono, and this pill is not
  // shrinkable, so on a 375px phone it was the single biggest reason the topbar
  // overran its own width. Below sm the qualifier goes and the tier alone
  // stays; grace is still legible without its word because the pill turns
  // amber, and either form links to Settings for the detail.
  const shortLabel = tier === 'builtin' ? 'FREE' : tier.toUpperCase()
  const cls = grace?.in_grace ? 'border-amber text-amber'
    : tier === 'builtin' ? 'border-line text-text-3' : 'border-amber/40 text-amber'
  return (
    <Link to="/settings" className={`shrink-0 whitespace-nowrap rounded-full border px-2.5 py-1 font-mono text-[9.5px] tracking-[.08em] ${cls}`}>
      <span className="sm:hidden">{shortLabel}</span>
      <span className="hidden sm:inline">{label}</span>
    </Link>
  )
}
