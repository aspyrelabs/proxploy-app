import { describe, expect, it } from 'vitest'
import {
  ENTITLEMENTS_DEGRADED_MS, ENTITLEMENTS_HEALTHY_MS, entitlementsInterval,
} from '../api/hooks'
import type { Entitlements } from '../api/hooks'

const base: Entitlements = {
  tier: 'pro', features: {}, grace: null, clock_skew: false,
  refresh_error: null, reason: null,
}

describe('entitlementsInterval', () => {
  it('polls once a day while the licence is healthy', () => {
    expect(entitlementsInterval(base)).toBe(ENTITLEMENTS_HEALTHY_MS)
    expect(ENTITLEMENTS_HEALTHY_MS).toBe(24 * 60 * 60_000)
  })

  it('polls hourly once the licence server could not be reached', () => {
    expect(entitlementsInterval({ ...base, refresh_error: 'connection refused' }))
      .toBe(ENTITLEMENTS_DEGRADED_MS)
    expect(ENTITLEMENTS_DEGRADED_MS).toBe(60 * 60_000)
  })

  it('polls hourly inside the grace period', () => {
    expect(entitlementsInterval({
      ...base,
      grace: { expires_at: '', grace_until: '', in_grace: true },
    })).toBe(ENTITLEMENTS_DEGRADED_MS)
  })

  it('drops back to daily once the licence recovers', () => {
    expect(entitlementsInterval({
      ...base,
      grace: { expires_at: '', grace_until: '', in_grace: false },
      refresh_error: null,
    })).toBe(ENTITLEMENTS_HEALTHY_MS)
  })

  it('uses the daily interval before the first response lands', () => {
    expect(entitlementsInterval(undefined)).toBe(ENTITLEMENTS_HEALTHY_MS)
  })
})
