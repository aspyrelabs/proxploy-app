import { Link } from '@tanstack/react-router'
import { useEntitlements } from '../api/hooks'
import { Skeleton, SkeletonGroup } from './ui/skeleton'

export function TierPill() {
  const { tier, grace, isPending } = useEntitlements()
  // `tier` fail-closed defaults to 'builtin' until /entitlements resolves; the
  // pill must not render that as fact, so it shows a skeleton sized to its own
  // box (h-22px = 9.5px line + py-1 + 1px border) and the longest label's
  // width — this pill is `shrink-0` in a topbar that has overrun once.
  if (isPending) {
    return (
      <SkeletonGroup label="Checking your plan" className="shrink-0">
        <Skeleton className="h-[22px] w-10 rounded-full sm:w-36" />
      </SkeletonGroup>
    )
  }
  const label = tier === 'builtin' ? 'FREE · ALL FEATURES'
    : grace?.in_grace ? `${tier.toUpperCase()} · GRACE` : tier.toUpperCase()
  // 'FREE · ALL FEATURES' (~143px) overran the topbar on a 375px phone; below
  // sm the qualifier drops to the tier alone. Grace stays legible via the
  // amber pill; either form links to Settings.
  const shortLabel = tier === 'builtin' ? 'FREE' : tier.toUpperCase()
  const cls = grace?.in_grace ? 'border-amber text-amber'
    : tier === 'builtin' ? 'border-line text-text-3' : 'border-amber/40 text-amber'
  return (
    <Link to="/settings" search={{ section: 'plan' }} className={`shrink-0 whitespace-nowrap rounded-full border px-2.5 py-1 font-mono text-[9.5px] tracking-[.08em] ${cls}`}>
      <span className="sm:hidden">{shortLabel}</span>
      <span className="hidden sm:inline">{label}</span>
    </Link>
  )
}
