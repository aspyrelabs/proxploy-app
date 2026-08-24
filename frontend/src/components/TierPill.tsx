import { Link } from '@tanstack/react-router'
import { useEntitlements } from '../api/hooks'
import { Skeleton, SkeletonGroup } from './ui/skeleton'

export function TierPill() {
  const { tier, grace, isPending } = useEntitlements()
  // api/hooks.ts defaults `tier` to 'builtin' because a fail-closed default is
  // the right SECURITY answer, but this pill renders that default as a
  // statement of fact, so a paid installation's topbar read "FREE · ALL
  // FEATURES" for the length of the /entitlements fetch and then corrected
  // itself. The placeholder is pinned to the pill's own box (a 9.5px line
  // inside px-2.5 py-1 and a 1px border, so 22px) and to the width of the
  // longest label, because this pill is `shrink-0` in a topbar that has
  // already overrun its width once.
  if (isPending) {
    return (
      <SkeletonGroup label="Checking your plan" className="shrink-0">
        <Skeleton className="h-[22px] w-10 rounded-full sm:w-36" />
      </SkeletonGroup>
    )
  }
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
    <Link to="/settings" search={{ section: 'plan' }} className={`shrink-0 whitespace-nowrap rounded-full border px-2.5 py-1 font-mono text-[9.5px] tracking-[.08em] ${cls}`}>
      <span className="sm:hidden">{shortLabel}</span>
      <span className="hidden sm:inline">{label}</span>
    </Link>
  )
}
