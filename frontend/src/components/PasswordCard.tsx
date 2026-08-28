import { PasswordStrength } from './PasswordStrength'
import { refusal } from '../lib/password-strength'
import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, apiErrorDetail } from '../api/client'
import { notify } from '../lib/notify'
import { useMe } from '../api/hooks'
import { inputCls } from './LoginForm'
import { Button } from './ui/button'

const card = 'rounded-card border border-line-soft bg-panel p-5'
const label = 'mb-1 block text-[10.5px] uppercase tracking-wide text-text-3'

/**
 * Change your own password, stay signed in here while every other session is
 * dropped.
 */
export function PasswordCard() {
  const { data: me } = useMe()
  const qc = useQueryClient()
  const [pw, setPw] = useState('')
  const [busy, setBusy] = useState(false)

  async function savePassword() {
    if (!me) return
    setBusy(true)
    // Two POSTs, two outcomes, and they are not the same news. Under one try
    // a failed re-login reported the password as too short, which is both
    // untrue and backwards: the password HAS changed by then, and the user
    // was being told it had not.
    try {
      await api(`/users/${me.id}/password`, { method: 'POST',
        body: JSON.stringify({ password: pw }) })
    } catch (e) {
      // A refused password is usually a 403 or 404 whose reason the backend
      // states in words, so say that rather than guessing. The 12-character
      // rule is a Pydantic min_length, which comes back as a 422 whose detail
      // is a list of validation objects, not a sentence; apiErrorDetail
      // cannot read that, so the length rule stays as the fallback.
      notify.error(apiErrorDetail(e,
        'Could not set the password. It must be at least 12 characters.'))
      setBusy(false)
      return
    }
    // The reset revokes every session, this one included (auth.py's own
    // note: an admin-set password is a recovery mechanism). Logging straight
    // back in is what stops this card signing you out of itself.
    try {
      await api('/auth/login', { method: 'POST',
        body: JSON.stringify({ email: me.email, password: pw }) })
      setPw('')
      // The reset revoked every other session server-side, so the Sessions
      // section is now listing sessions that no longer exist. Only
      // ['auth', 'sessions'] is stale: ['me'] (email, role, display name) and
      // ['auth', 'me'] (totp_enabled) describe things a password reset does
      // not touch, and auth.py is explicit that it leaves TOTP alone.
      qc.invalidateQueries({ queryKey: ['auth', 'sessions'] })
      notify.success('Password updated.', { description: 'Other sessions were signed out.' })
    } catch {
      notify.error('Your password was changed, but signing back in here failed.', {
        description: 'Sign in again with the new password.' })
    } finally { setBusy(false) }
  }

  return (
    <section className={card}>
      <h2 className="mb-1 font-display text-[15px] font-semibold">Password</h2>
      <p className="mb-3 text-[12px] text-text-3">
        Changing it signs out every other session, including any you have forgotten about.
      </p>
      <div className="max-w-md">
        <label htmlFor="profile-pw" className={label}>New password</label>
        <input id="profile-pw" type="password" className={inputCls} value={pw}
          onChange={e => setPw(e.target.value)} />
        <PasswordStrength value={pw} email={me?.email} />
        <Button className="mt-2" disabled={busy || refusal(pw) !== null}
          onClick={savePassword}>
          Set new password
        </Button>
      </div>
    </section>
  )
}
