// Never hide a gated feature, veil it.
//
// What is drawn under the veil is a SKELETON, not the real thing blurred. Two
// reasons, and the second is the load-bearing one:
//
//   1. A blurred panel of numbers you cannot have is a tease. The shape is the
//      honest part of the promise, so the shape is what stays.
//   2. There is usually nothing to blur. Every route behind these flags 403s
//      (deps.py::require_entitlement), so the queries that would fill the panel
//      are not issued at all on a plan that lacks it -- see the `allowed`
//      guards in ApiKeysCard/TeamsCard. Blurring an empty panel drew nothing.
//
// The skeleton is aria-hidden and there is deliberately no SkeletonGroup:
// SkeletonGroup announces role=status aria-busy, which is true while something
// loads and a lie forever on a plan that will never load it. The overlay text
// is the accessible content.
import type { ReactNode } from 'react'
import { amberLinkCls, buttonCls } from './ui/button'
import { Icon } from './ui/icon'
import { Skeleton, SkeletonLine } from './ui/skeleton'
import { useEntitlements } from '../api/hooks'
import type { FeatureKey } from '../api/feature-keys'
/** The tiers are one section on the homepage; proxploy-web has no /pricing
 *  route (see its src/App.tsx). Always the production site, never a
 *  env-derived base: this is the public price list, and a dev build sending
 *  someone to a staging price would be worse than a hardcoded link. */
export const PRICING_URL = 'https://proxploy.com/#pricing'

const TIER_LABEL: Record<string, string> = { pro: 'Pro', team: 'Team' }

/** This app's one card shape, the same string the routes spell inline. The
 *  SKELETON carries it, not the veil: unlocked, the child section draws the
 *  card, so a card on the veil too would nest two of them. */
const card = 'rounded-card border border-line-soft bg-panel p-5'

/** The default shape: a heading, a couple of lines, a small grid. Enough to
 *  read as "a panel belongs here" without claiming a shape the real feature
 *  does not have. Pass `skeleton` where the real shape is worth matching. */
function DefaultSkeleton() {
  return (
    <div aria-hidden className={`${card} space-y-3`}>
      <SkeletonLine className="w-40 text-[15px]" />
      <SkeletonLine className="w-full text-[13px]" />
      <SkeletonLine className="w-3/4 text-[13px]" />
      <div className="grid grid-cols-3 gap-3 pt-1">
        <Skeleton className="h-16 rounded-ctl" />
        <Skeleton className="h-16 rounded-ctl" />
        <Skeleton className="h-16 rounded-ctl" />
      </div>
    </div>
  )
}

export function LockVeil({ locked, feature, subtitle, skeleton, minHeight = 210, children }: {
  locked: boolean
  /** The entitlement key this veil stands in front of, e.g. "teams.rbac". The
   *  tier in the copy is looked up from it rather than written at the call
   *  site: four call sites used to say "Pro" in a hardcoded string, and three
   *  of those features are not Pro any more. */
  feature: FeatureKey
  /** One line on what the feature does, in the operator's words. The headline
   *  above it is generated, so this is the part worth writing. */
  subtitle: string
  /** A placeholder matching the real panel's shape, where that is worth doing. */
  skeleton?: ReactNode
  /** Floor for the veiled area, so a short skeleton still leaves the overlay
   *  room to sit in without cramping it. */
  minHeight?: number
  children: ReactNode
}) {
  const { tierFor } = useEntitlements()
  if (!locked) return <>{children}</>

  // null when entitlements could not be fetched at all. "a paid plan" is vague
  // on purpose there: naming the wrong tier is worse than naming none, and
  // `has` has already failed closed to get us here.
  const tier = TIER_LABEL[tierFor(feature) ?? ''] ?? null

  return (
    <div className="relative overflow-hidden rounded-card" style={{ minHeight }}>
      <div className="pointer-events-none select-none">{skeleton ?? <DefaultSkeleton />}</div>
      {/* bg-panel/80, NOT bg-scrim. The scrim token is deliberately the same
          near-black in both themes (tokens.css) because a dialog scrim exists
          to dim the whole page behind a modal. This is not that: it sits
          inside one card, and a near-black wash over a light card reads as a
          rendering fault rather than a locked panel. Panel-on-panel follows
          the theme and still separates the overlay from the skeleton. */}
      <div className="absolute inset-0 grid place-items-center bg-panel/80 px-5 backdrop-blur-[2px]">
        <div className="text-center">
          <span className="mx-auto mb-2 grid size-10 place-items-center rounded-tile
                           border border-amber/30 bg-amber-dim text-amber">
            <Icon name="lock" size={20} />
          </span>
          <div className="font-display text-[15px] font-semibold">
            {tier ? `This is a ${tier} feature` : 'This is a paid feature'}
          </div>
          <p className="mx-auto mb-3 mt-1 max-w-[42ch] text-[12.5px] text-text-3">{subtitle}</p>
          {/* A real <a>, not a Button with an onClick: this leaves the app for
              the public site, so middle-click, "open in new tab" and "copy
              link address" have to work the way they do on any other link. */}
          <a href={PRICING_URL} target="_blank" rel="noreferrer noopener"
             className={buttonCls('go')}>
            Please upgrade
            <Icon name="open_in_new" size={15} />
          </a>
          {/* Buying is one way in; pasting a key you already own is the other,
              and this veil used to be the only route to it.

              A plain <a>, not a router <Link>: this veil renders inside cards
              (ApiKeysCard, TeamsCard) that mount with no router in their
              tests, and a <Link> there throws on useLinkProps. One full page
              load on a link this rarely-clicked beats a component that can
              only be mounted under a router. */}
          <div className="mt-2 text-[11.5px] text-text-3">
            <a href="/settings?section=plan" className={amberLinkCls}>
              Already have a licence key?
            </a>
          </div>
        </div>
      </div>
    </div>
  )
}
