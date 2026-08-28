import { useEffect } from 'react'
import { Link } from '@tanstack/react-router'
import { useEntitlements } from '../api/hooks'
import { notify } from '../lib/notify'
import { Icon } from './ui/icon'
import { Skeleton, SkeletonGroup } from './ui/skeleton'

export const TIER_BADGE_PX = 16
export const TIER_MARKER_PX = 16

type TierSpec = { label: string; icon: string; tone: string; box: string }

const TIERS: Record<string, TierSpec> = {
  builtin: { label: 'FREE', icon: 'shield_lock', tone: 'text-amber',
             box: 'border-amber/30 bg-amber-dim' },
  pro: { label: 'PRO', icon: 'crown', tone: 'text-red',
         box: 'border-red/30 bg-red-dim' },
  teams: { label: 'TEAMS', icon: 'groups', tone: 'text-text',
           box: 'border-line bg-panel-2' },
  dev: { label: 'DEV', icon: 'frame_source', tone: 'text-green',
         box: 'border-green/30 bg-green-dim' },
}

const GRACE_YELLOW = '#EED202'
const ERROR_RED = '#FF0000'

type LicenceState = 'ok' | 'grace' | 'unreachable'

let announced: LicenceState = 'ok'

export function resetLicenceAnnouncement() {
  announced = 'ok'
}

function useLicenceToast(state: LicenceState, detail: string | null) {
  useEffect(() => {
    if (state === announced) return
    announced = state
    if (state === 'unreachable') {
      notify.error('Could not check your licence', {
        description: detail
          ? `Proxploy could not reach the licence server. ${detail}`
          : 'Proxploy could not reach the licence server. Your plan keeps working; it will retry on its own.',
      })
    } else if (state === 'grace') {
      notify.warning('Your licence is in its grace period', {
        description: 'Renew before the grace period ends or Proxploy falls back to the free plan.',
      })
    }
  }, [state, detail])
}

function Marker({ colour }: { colour: string }) {
  return (
    <span
      className="-mb-[7px] -ml-[2px] -mr-[8px] flex shrink-0 grow-0 items-center
                 justify-center self-end rounded-full bg-panel"
      style={{ flexBasis: TIER_MARKER_PX, width: TIER_MARKER_PX,
               height: TIER_MARKER_PX, color: colour }}
    >
      <Icon name="warning" size={13} className="pp-blink" />
    </span>
  )
}

export function TierPill() {
  const { tier, grace, refreshError, isPending } = useEntitlements()
  const licence: LicenceState = refreshError ? 'unreachable'
    : grace?.in_grace ? 'grace' : 'ok'
  useLicenceToast(isPending ? 'ok' : licence, refreshError)
  if (isPending) {
    return (
      <SkeletonGroup label="Checking your plan" className="shrink-0">
        <Skeleton className="h-[26px] w-[76px] rounded-ctl" />
      </SkeletonGroup>
    )
  }
  const spec: TierSpec = TIERS[tier]
    ?? { label: tier.toUpperCase(), icon: 'shield_lock', tone: 'text-text-3',
         box: 'border-line bg-panel-2' }
  const unreachable = Boolean(refreshError)
  const inGrace = !unreachable && Boolean(grace?.in_grace)
  const state = unreachable
    ? 'Proxploy could not reach the licence server to check this plan'
    : inGrace ? 'Licence is in its grace period' : undefined
  return (
    <Link
      to="/settings"
      search={{ section: 'plan' }}
      aria-label={state ? `${spec.label} plan. ${state}. Open plan settings`
                        : `${spec.label} plan. Open plan settings`}
      title={state}
      className={`inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-ctl border
                  px-1.5 py-1 font-badge font-bold leading-none tracking-[.04em]
                  ${spec.tone} ${spec.box}`}
      style={{ fontSize: TIER_BADGE_PX }}
    >
      <Icon name={spec.icon} size={TIER_BADGE_PX} />
      {spec.label}
      {unreachable && <Marker colour={ERROR_RED} />}
      {inGrace && <Marker colour={GRACE_YELLOW} />}
    </Link>
  )
}
