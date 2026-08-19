import { useEffect, useState } from 'react'
import { createRoute } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import { shellRoute } from './shell'
import { api, apiErrorDetail } from '../api/client'
import { notify } from '../lib/notify'
import { useMe } from '../api/hooks'
import { inputCls } from '../components/LoginForm'
import { SessionsCard } from '../components/SessionsCard'
import { TrustedDevicesCard } from '../components/TrustedDevicesCard'
import { TotpCard } from '../components/TotpCard'
import { Button } from '../components/ui/button'
import { SkeletonLine } from '../components/ui/skeleton'

const card = 'rounded-card border border-line-soft bg-panel p-5'
const label = 'mb-1 block text-[10.5px] uppercase tracking-wide text-text-3'

/** The signed-in user's own account.
 *
 *  TotpCard and SessionsCard were already self-service, but they only existed
 *  inside Settings, next to fleet-wide admin controls. This is the page the
 *  avatar menu points at: your account, not the installation's. */
export function ProfilePage() {
  const { data: me, isPending: mePending } = useMe()
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [pw, setPw] = useState('')
  const [busy, setBusy] = useState(false)

  // me arrives async; seed the field once it does, without clobbering an edit
  // already in progress.
  useEffect(() => { setName(n => n || me?.display_name || '') }, [me?.display_name])

  async function saveName() {
    if (!me) return
    // PATCH rejects a no-op body with 422, so don't send one.
    if (name === (me.display_name ?? '')) { notify.info('Display name unchanged.'); return }
    setBusy(true)
    try {
      await api(`/users/${me.id}`, { method: 'PATCH',
        body: JSON.stringify({ display_name: name }) })
      qc.invalidateQueries({ queryKey: ['me'] })
      notify.success('Display name updated.')
    } catch { notify.error('Could not update the display name.') } finally { setBusy(false) }
  }

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
    // back in is what stops this page signing you out of itself.
    try {
      await api('/auth/login', { method: 'POST',
        body: JSON.stringify({ email: me.email, password: pw }) })
      setPw('')
      // The reset revoked every other session server-side, so the Sessions
      // card below is now listing sessions that no longer exist. Only
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
    <div className="space-y-5">
      <div>
        <h1 className="font-display text-[22px] font-semibold">Profile and security</h1>
        <p className="mt-0.5 text-[12.5px] text-text-3">Your account on this installation.</p>
      </div>

      <div className={card}>
        <h2 className="mb-3 text-[13px] font-semibold text-text">Account</h2>
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <span className={label}>Email</span>
            {/* Both readouts print "unknown" for anything falsy, which during
                the /auth/me fetch is a statement about the reader's own
                account rather than a wait. Same box either way, so nothing
                moves when the answer lands. */}
            {/* A div, not a <p>: SkeletonLine renders a div (its pulse box is
                one too), and a div cannot legally nest inside a <p> -- React
                warned about exactly that in the loading state. Tailwind's
                preflight zeroes margin on both tags, so nothing moves. */}
            <div className="rounded-ctl border border-line bg-panel-2 px-3 py-2 text-[13.5px] text-text-2">
              {mePending ? <SkeletonLine className="w-48 max-w-full text-[13.5px]" /> : me?.email ?? 'unknown'}
            </div>
            <p className="mt-1 text-[11.5px] text-text-3">
              The email cannot be changed after the account is created.
            </p>
          </div>
          <div>
            <span className={label}>Role</span>
            <div className="rounded-ctl border border-line bg-panel-2 px-3 py-2 font-mono text-[13px] text-text-2">
              {mePending ? <SkeletonLine className="w-20 text-[13px]" /> : me?.role ?? 'unknown'}
            </div>
          </div>
        </div>

        <div className="mt-4 max-w-md">
          <label htmlFor="profile-name" className={label}>Display name</label>
          <input id="profile-name" className={inputCls} value={name}
            onChange={e => setName(e.target.value)} />
          <Button variant="ghost" className="mt-2" disabled={busy} onClick={saveName}>
            Save display name
          </Button>
        </div>
      </div>

      <div className={card}>
        <h2 className="mb-1 text-[13px] font-semibold text-text">Password</h2>
        <p className="mb-3 text-[12px] text-text-3">
          Changing it signs out every other session, including any you have forgotten about.
        </p>
        <div className="max-w-md">
          <label htmlFor="profile-pw" className={label}>New password (12+ chars)</label>
          <input id="profile-pw" type="password" className={inputCls} value={pw}
            onChange={e => setPw(e.target.value)} />
          <Button className="mt-2" disabled={busy || pw.length < 12} onClick={savePassword}>
            Set new password
          </Button>
        </div>
      </div>

      <TotpCard />
      <SessionsCard />

      <TrustedDevicesCard />
    </div>
  )
}

export const profileRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/profile',
  component: ProfilePage,
})
