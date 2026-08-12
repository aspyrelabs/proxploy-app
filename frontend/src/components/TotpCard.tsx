import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, ApiError } from '../api/client'
import { useEntitlements } from '../api/hooks'
import { useTotpStatus } from '../api/account'
import type { TotpEnrollment } from '../api/account'
import { Button } from './ui/button'
import { CardLoadingOverlay } from './ui/card-loading-overlay'

const detailOf = (e: unknown) =>
  e instanceof ApiError && typeof (e.body as any)?.detail === 'string'
    ? (e.body as any).detail : 'Request failed, try again.'

export function TotpCard() {
  const ent = useEntitlements()
  // Same wait-for-first-fetch pattern as ApiKeysCard/TeamsCard: fetching
  // /auth/me before auth.totp resolves true would still succeed (it's not
  // gated by an entitlement itself) but would render the enroll button for
  // a sliver of a second on plans that don't include TOTP at all.
  const totpAllowed = ent.data != null && ent.has('auth.totp')
  const qc = useQueryClient()
  const me = useTotpStatus(totpAllowed)

  const [enrollment, setEnrollment] = useState<TotpEnrollment | null>(null)
  const [confirmCode, setConfirmCode] = useState('')
  const [disabling, setDisabling] = useState(false)
  const [password, setPassword] = useState('')

  const invalidateMe = () => qc.invalidateQueries({ queryKey: ['auth', 'me'] })

  const enroll = useMutation({
    mutationFn: () => api<TotpEnrollment>('/auth/totp/enroll', { method: 'POST' }),
    onSuccess: (r) => setEnrollment(r),
    onError: (e) => toast.error(detailOf(e)),
  })

  const confirm = useMutation({
    mutationFn: () => api('/auth/totp/confirm', {
      method: 'POST', body: JSON.stringify({ code: confirmCode }),
    }),
    onSuccess: () => {
      // The recovery codes were shown once, above -- once TOTP is confirmed
      // enabled there is nothing left to show, so the enrollment panel goes
      // away rather than lingering with stale codes on screen.
      setEnrollment(null)
      setConfirmCode('')
      invalidateMe()
    },
    onError: (e) => toast.error(detailOf(e)),
  })

  const disable = useMutation({
    mutationFn: () => api('/auth/totp', {
      method: 'DELETE', body: JSON.stringify({ password }),
    }),
    onSuccess: () => {
      setDisabling(false)
      setPassword('')
      invalidateMe()
    },
    onError: (e) => toast.error(detailOf(e)),
  })

  const copy = (text: string) => { void navigator.clipboard?.writeText(text) }

  return (
    <CardLoadingOverlay state={{
      // Not-yet-known-if-entitled, then /auth/me's own first fetch.
      // `isPending`, not `isFetching`, so it stays quiet on the
      // invalidateQueries refetch each mutation below triggers.
      firstLoad: ent.isPending || (totpAllowed && me.isPending),
      // All three mutations are defined directly on this card and each one
      // swaps the card between its major states (not-enrolled / enrolling /
      // enabled), the exact "content jumps" case the veil exists for.
      mutating: enroll.isPending || confirm.isPending || disable.isPending,
    }}>
    <section className="rounded-card border border-line-soft bg-panel p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="font-display text-[15px] font-semibold">Two-factor authentication</h2>
      </div>
      {!totpAllowed ? (
        !ent.isPending && (
          <p className="text-[12.5px] text-text-3">
            {ent.unknown ? 'Could not check your plan, try reloading.' : 'Not included in your plan.'}
          </p>
        )
      ) : me.isError ? (
        // Security-relevant: me.data is undefined on error same as on a
        // genuine "not enrolled" response, so without this branch a failed
        // /auth/me read would fall straight to "Enable two-factor", offering
        // to enroll a user who may already have TOTP on.
        <p className="text-[12.5px] text-text-3">
          Could not check two-factor status, try reloading.
        </p>
      ) : me.data?.totp_enabled ? (
        <div>
          <p className="text-[13px] text-text-2">
            Two-factor authentication is <span className="text-green">enabled</span>.
          </p>
          {!disabling ? (
            <Button variant="danger" className="mt-3" onClick={() => setDisabling(true)}>
              Disable two-factor
            </Button>
          ) : (
            <div className="mt-3 flex flex-wrap items-end gap-3">
              <div>
                <label htmlFor="totp-disable-password"
                  className="mb-1 block text-[10.5px] uppercase tracking-wide text-text-3">
                  Password (or a current code, for OIDC-only accounts)
                </label>
                <input id="totp-disable-password" type="password" value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="rounded-ctl border border-line bg-panel-2 px-3 py-1.5 text-[13px] text-text" />
              </div>
              <Button variant="danger" disabled={!password || disable.isPending}
                onClick={() => disable.mutate()}>
                Confirm disable
              </Button>
              <Button variant="ghost" onClick={() => { setDisabling(false); setPassword('') }}>
                Cancel
              </Button>
            </div>
          )}
        </div>
      ) : enrollment ? (
        <div>
          <p className="text-[12.5px] text-text-3">
            No QR code -- add this manually in your authenticator app (every
            app that reads a QR code also accepts a typed key).
          </p>
          <div className="mt-3 space-y-3">
            <div>
              <label className="mb-1 block text-[10.5px] uppercase tracking-wide text-text-3">
                Secret
              </label>
              <div className="flex items-center gap-2">
                <code className="min-w-0 flex-1 select-all truncate rounded-ctl border border-line
                                 bg-panel-2 px-2 py-1.5 font-mono text-[12px] text-text">
                  {enrollment.secret}
                </code>
                <Button variant="ghost" className="px-2 py-1 text-[11px]"
                  onClick={() => copy(enrollment.secret)}>
                  Copy
                </Button>
              </div>
            </div>
            <div>
              <label className="mb-1 block text-[10.5px] uppercase tracking-wide text-text-3">
                otpauth URI
              </label>
              <div className="flex items-center gap-2">
                <code className="min-w-0 flex-1 select-all truncate rounded-ctl border border-line
                                 bg-panel-2 px-2 py-1.5 font-mono text-[12px] text-text">
                  {enrollment.otpauth_uri}
                </code>
                <Button variant="ghost" className="px-2 py-1 text-[11px]"
                  onClick={() => copy(enrollment.otpauth_uri)}>
                  Copy
                </Button>
              </div>
            </div>
          </div>

          <p className="mt-4 text-[12.5px] font-semibold text-amber">
            These recovery codes are shown once, store them now. Proxploy keeps
            only a hash of each one; if you lose them there is no way to recover them.
          </p>
          <div className="mt-2 grid grid-cols-2 gap-1.5">
            {enrollment.recovery_codes.map((code) => (
              <code key={code} className="select-all rounded-ctl border border-line
                                          bg-panel-2 px-2 py-1 font-mono text-[12px] text-text">
                {code}
              </code>
            ))}
          </div>
          <Button variant="ghost" className="mt-2 px-2 py-1 text-[11px]"
            onClick={() => copy(enrollment.recovery_codes.join('\n'))}>
            Copy all codes
          </Button>

          <div className="mt-4 flex flex-wrap items-end gap-3 border-t border-line-soft pt-4">
            <div>
              <label htmlFor="totp-confirm-code"
                className="mb-1 block text-[10.5px] uppercase tracking-wide text-text-3">
                Confirm code
              </label>
              <input id="totp-confirm-code" value={confirmCode}
                onChange={(e) => setConfirmCode(e.target.value)}
                placeholder="123456"
                className="rounded-ctl border border-line bg-panel-2 px-3 py-1.5 text-[13px] text-text" />
            </div>
            <Button disabled={!confirmCode || confirm.isPending} onClick={() => confirm.mutate()}>
              Confirm
            </Button>
          </div>
        </div>
      ) : (
        <Button onClick={() => enroll.mutate()} disabled={enroll.isPending}>
          Enable two-factor
        </Button>
      )}
    </section>
    </CardLoadingOverlay>
  )
}
