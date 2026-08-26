import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, apiErrorDetail } from '../api/client'
import { useEntitlements } from '../api/hooks'
import { useTotpStatus } from '../api/account'
import { notify } from '../lib/notify'
import type { TotpEnrollment } from '../api/account'
import { Button } from './ui/button'
import { CardLoadingOverlay } from './ui/card-loading-overlay'
import { Dialog } from './ui/dialog'

const copyText = (text: string) => { void navigator.clipboard?.writeText(text) }

// Shared by the enrollment panel, the activation confirm dialog, and the
// regenerate-codes result, so the three can't drift apart.
function RecoveryCodesBlock({ codes }: { codes: string[] }) {
  return (
    <>
      <p className="text-[12.5px] font-semibold text-amber">
        These recovery codes are shown once, store them now. Proxploy keeps
        only a hash of each one; if you lose them there is no way to recover them.
      </p>
      <div className="mt-2 grid grid-cols-2 gap-1.5">
        {codes.map((code) => (
          <code key={code} className="select-all rounded-ctl border border-line
                                      bg-panel-2 px-2 py-1 font-mono text-[12px] text-text">
            {code}
          </code>
        ))}
      </div>
      <Button size="sm" variant="ghost" className="mt-2"
        onClick={() => copyText(codes.join('\n'))}>
        Copy all codes
      </Button>
    </>
  )
}

// qrcode.react adds ~6 kB gzip; this card's QR only renders in the enroll
// flow, which most sessions never enter.
import { QRCodeSVG } from 'qrcode.react'

export function TotpCard() {
  const ent = useEntitlements()
  // Wait for the entitlement fetch: rendering the enroll button before
  // auth.totp resolves would flash it on plans without TOTP.
  const totpAllowed = ent.data != null && ent.has('auth.totp')
  const qc = useQueryClient()
  const me = useTotpStatus(totpAllowed)

  const [enrollment, setEnrollment] = useState<TotpEnrollment | null>(null)
  const [confirmCode, setConfirmCode] = useState('')
  // Activation happens only from inside the confirm dialog below.
  const [showActivateConfirm, setShowActivateConfirm] = useState(false)
  const [ackSaved, setAckSaved] = useState(false)
  const [disabling, setDisabling] = useState(false)
  const [password, setPassword] = useState('')
  const [regenerating, setRegenerating] = useState(false)
  const [regenPassword, setRegenPassword] = useState('')
  const [regeneratedCodes, setRegeneratedCodes] = useState<string[] | null>(null)

  const invalidateMe = () => qc.invalidateQueries({ queryKey: ['auth', 'me'] })

  const enroll = useMutation({
    mutationFn: () => api<TotpEnrollment>('/auth/totp/enroll', { method: 'POST' }),
    onSuccess: (r) => setEnrollment(r),
    onError: (e) => notify.error(apiErrorDetail(e, 'Request failed, try again.')),
  })

  const confirm = useMutation({
    mutationFn: () => api('/auth/totp/confirm', {
      method: 'POST', body: JSON.stringify({ code: confirmCode }),
    }),
    onSuccess: () => {
      setEnrollment(null)
      setConfirmCode('')
      setShowActivateConfirm(false)
      setAckSaved(false)
      invalidateMe()
    },
    onError: (e) => notify.error(apiErrorDetail(e, 'Request failed, try again.')),
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
    onError: (e) => notify.error(apiErrorDetail(e, 'Request failed, try again.')),
  })

  const regenerate = useMutation({
    mutationFn: () => api<{ recovery_codes: string[] }>('/auth/totp/recovery-codes/regenerate', {
      method: 'POST', body: JSON.stringify({ password: regenPassword }),
    }),
    onSuccess: (r) => {
      // Old codes are already deleted server-side, so these are shown once, here.
      setRegeneratedCodes(r.recovery_codes)
      setRegenerating(false)
      setRegenPassword('')
    },
    onError: (e) => notify.error(apiErrorDetail(e, 'Request failed, try again.')),
  })

  return (
    <CardLoadingOverlay state={{
      // `isPending`, not `isFetching`: stay quiet on the invalidateQueries
      // refetch each mutation below triggers.
      firstLoad: ent.isPending || (totpAllowed && me.isPending),
      // Any mutation swaps the card between major states -- the content-jump
      // case the veil exists for.
      mutating: enroll.isPending || confirm.isPending || disable.isPending || regenerate.isPending,
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
        // Security: me.data is undefined on error, same as a genuine
        // "not enrolled", so without this branch a failed read would offer to
        // enroll a user who may already have TOTP on.
        <p className="text-[12.5px] text-text-3">
          Could not check two-factor status, try reloading.
        </p>
      ) : me.data?.totp_enabled ? (
        <div>
          <p className="text-[13px] text-text-2">
            Two-factor authentication is <span className="text-green">enabled</span>.
          </p>
          {regeneratedCodes ? (
            <div className="mt-3">
              <p className="text-[12.5px] text-text-2">
                New recovery codes generated. Your old codes no longer work.
              </p>
              <div className="mt-2">
                <RecoveryCodesBlock codes={regeneratedCodes} />
              </div>
              <Button className="mt-3" onClick={() => setRegeneratedCodes(null)}>
                Done
              </Button>
            </div>
          ) : disabling ? (
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
          ) : regenerating ? (
            <div className="mt-3 flex flex-wrap items-end gap-3">
              <div>
                <label htmlFor="totp-regenerate-password"
                  className="mb-1 block text-[10.5px] uppercase tracking-wide text-text-3">
                  Password (or a current code, for OIDC-only accounts)
                </label>
                <input id="totp-regenerate-password" type="password" value={regenPassword}
                  onChange={(e) => setRegenPassword(e.target.value)}
                  className="rounded-ctl border border-line bg-panel-2 px-3 py-1.5 text-[13px] text-text" />
              </div>
              <Button disabled={!regenPassword || regenerate.isPending}
                onClick={() => regenerate.mutate()}>
                Confirm regenerate
              </Button>
              <Button variant="ghost"
                onClick={() => { setRegenerating(false); setRegenPassword('') }}>
                Cancel
              </Button>
            </div>
          ) : (
            <div className="mt-3 flex flex-wrap gap-2">
              <Button variant="danger" onClick={() => setDisabling(true)}>
                Disable two-factor
              </Button>
              <Button variant="ghost" onClick={() => setRegenerating(true)}>
                Regenerate recovery codes
              </Button>
            </div>
          )}
        </div>
      ) : enrollment ? (
        <div>
          <p className="text-[12.5px] text-text-3">
            Scan this with your authenticator app, or enter the secret below manually.
          </p>
          <div className="mt-3 flex justify-center">
            {/* QR colors pinned to black-on-white in both themes: scanability
              requirement, not a design choice. marginSize = spec quiet zone. */}
            <div className="rounded-ctl bg-white p-3">
                <QRCodeSVG value={enrollment.otpauth_uri} size={176} bgColor="#FFFFFF"
                  fgColor="#000000" marginSize={4} level="M"
                  title="Scan with your authenticator app" />
            </div>
          </div>
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
                <Button size="sm" variant="ghost"
                  onClick={() => copyText(enrollment.secret)}>
                  Copy
                </Button>
              </div>
            </div>
          </div>

          <div className="mt-4">
            <RecoveryCodesBlock codes={enrollment.recovery_codes} />
          </div>

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
            {/* Submitting only opens the confirm dialog below, the only place
               confirm.mutate() is called. */}
            <Button disabled={!confirmCode || confirm.isPending}
              onClick={() => setShowActivateConfirm(true)}>
              Confirm
            </Button>
          </div>

          {showActivateConfirm && (
            <Dialog title="Activate two-factor authentication?" width={440}
              onClose={() => setShowActivateConfirm(false)}>
              <p className="mt-2 text-[12.5px] text-text-2">
                Once activated, these recovery codes will not be shown again.
              </p>
              <div className="mt-3">
                <RecoveryCodesBlock codes={enrollment.recovery_codes} />
              </div>
              <label className="mt-4 flex items-center gap-2 text-[12.5px] text-text-2">
                <input type="checkbox" checked={ackSaved}
                  onChange={(e) => setAckSaved(e.target.checked)} />
                I've saved these recovery codes
              </label>
              <div className="mt-4 flex justify-end gap-2">
                <Button variant="ghost" onClick={() => setShowActivateConfirm(false)}>
                  Cancel
                </Button>
                <Button disabled={!ackSaved || confirm.isPending} onClick={() => confirm.mutate()}>
                  {confirm.isPending ? 'Activating…' : 'Activate'}
                </Button>
              </div>
            </Dialog>
          )}
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
